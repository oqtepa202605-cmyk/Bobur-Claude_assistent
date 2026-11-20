"""Runs the Claude Code CLI (`claude -p`) to generate one reply.

* The subscription is used through a `claude setup-token` OAuth token (or the
  local `claude` login); an Anthropic API key is never used.
* No shell is involved: the process is started with an argv list.
* The conversation goes through stdin only; the system prompt (with the
  profile) goes through a private temporary file, so neither shows up in `ps`.
* `--bare` is NOT used: it ignores OAuth logins and would break the subscription.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

log = logging.getLogger(__name__)

# Built-in plugins shipped inside Claude Code 2.1.328 (read from the
# `plugins` field of the stream-json init event). All of them are disabled.
BUILTIN_PLUGINS = (
    "cc-plugin-agents-md@builtin",
    "cc-plugin-telemetry@builtin",
    "cc-plugin-privacy@builtin",
    "cc-plugin-plugin-authoring@builtin",
)

ISOLATION_SETTINGS: Dict[str, Any] = {
    "disableAllHooks": True,
    "enabledPlugins": {name: False for name in BUILTIN_PLUGINS},
}

STRIPPED_ENV_KEYS = frozenset(
    {
        "TELEGRAM_BOT_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SIMPLE",  # set by --bare; it disables the OAuth login
    }
)

ISOLATION_ENV = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
}

REDACTED = "[REDACTED]"
_GENERIC_TOKEN_RE = re.compile(r"sk-ant-(?:oat|api)[A-Za-z0-9_\-]{8,}")

_LIMIT_RE = re.compile(
    r"usage limit|hit your (?:usage )?limit|limit reached|rate[ _-]?limit|out of (?:extra )?usage|quota",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"not logged in|/login|invalid api key|authentication|unauthori[sz]ed|oauth token",
    re.IGNORECASE,
)
_EPOCH_RE = re.compile(r"\|\s*(\d{9,11})\b")
_RESET_TEXT_RE = re.compile(r"\b(resets?\s+[^|\n]+)", re.IGNORECASE)


class ClaudeError(Exception):
    """A Claude failure whose message is safe to show to the owner."""


class ClaudeTimeout(ClaudeError):
    pass


class ClaudeAuthError(ClaudeError):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class ClaudeLimitError(ClaudeError):
    def __init__(self, detail: str = "", resets_at: Optional[float] = None, reset_text: Optional[str] = None) -> None:
        self.detail = detail
        self.resets_at = resets_at
        self.reset_text = reset_text
        if reset_text:
            when = reset_text[len("resets"):].strip() if reset_text.lower().startswith("resets") else reset_text
        elif resets_at:
            when = datetime.fromtimestamp(resets_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        else:
            when = "at an unknown time"
        super().__init__(f"Claude subscription usage limit reached (resets {when})")


def classify_failure(message: str, status: Optional[int] = None) -> ClaudeError:
    """Turn CLI error text into the right exception (returned, not raised)."""
    text = (message or "").strip() or "unknown error"
    if status == 429 or _LIMIT_RE.search(text):
        m = _EPOCH_RE.search(text)
        resets_at = float(m.group(1)) if m else None
        detail = _EPOCH_RE.sub("", text).strip()
        r = _RESET_TEXT_RE.search(detail)
        reset_text = r.group(1).strip().rstrip(".") if r else None
        return ClaudeLimitError(detail, resets_at, reset_text)
    if status in (401, 403) or _AUTH_RE.search(text):
        return ClaudeAuthError(
            "Claude CLI is not logged in or its login was rejected. Run `claude` and use /login "
            "(or set CLAUDE_CODE_OAUTH_TOKEN).",
            text[:300],
        )
    return ClaudeError(f"Claude CLI failed: {text[:500]}")


def parse_result(returncode: int, stdout: str, stderr: str) -> str:
    """Parse `--output-format json` (or the last stream-json line) into the reply text."""
    lines = [line for line in (stdout or "").splitlines() if line.strip()]
    data: Any = None
    if lines:
        try:
            data = json.loads(lines[-1])
        except ValueError:
            data = None
    if not isinstance(data, dict):
        raise classify_failure((stderr or "").strip() or (stdout or "").strip() or f"exit code {returncode}")
    result = data.get("result")
    if data.get("is_error") or data.get("subtype") != "success":
        parts = [str(result).strip() if result else "", (stderr or "").strip()]
        message = " ".join(p for p in parts if p) or f"exit code {returncode}"
        status = data.get("api_error_status")
        raise classify_failure(message, status if isinstance(status, int) else None)
    if not isinstance(result, str) or not result.strip():
        raise ClaudeError("Claude returned an empty reply")
    return result.strip()


def build_env(oauth_token: Optional[str] = None, base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Environment for the child `claude` process."""
    source = os.environ if base is None else base
    env = {
        k: v
        for k, v in source.items()
        if not k.upper().startswith("ANTHROPIC_") and k.upper() not in STRIPPED_ENV_KEYS
    }
    env.update(ISOLATION_ENV)
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    return env


def _kill_tree(pid: int) -> None:
    """Kill the child and everything it started."""
    if os.name == "posix":
        try:
            os.killpg(pid, signal.SIGKILL)  # the child is a session (and group) leader
        except (ProcessLookupError, PermissionError):
            pass
    else:  # Windows: local development only
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)


class ClaudeCLI:
    def __init__(
        self,
        claude_bin: str,
        *,
        workdir: os.PathLike | str,
        model: Optional[str] = None,
        effort: str = "low",
        timeout: float = 120,
        oauth_token: Optional[str] = None,
        auth_label: Optional[str] = None,
    ) -> None:
        self.claude_bin = str(claude_bin)
        self.workdir = Path(workdir)
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self._oauth_token = oauth_token or None
        self._auth_label = auth_label

    def __repr__(self) -> str:
        return (
            f"ClaudeCLI(claude_bin={self.claude_bin!r}, workdir={str(self.workdir)!r}, model={self.model!r}, "
            f"effort={self.effort!r}, timeout={self.timeout!r}, auth={self.auth_mode!r})"
        )

    @property
    def auth_mode(self) -> str:
        if self._auth_label:
            return self._auth_label
        return "subscription token" if self._oauth_token else "this machine's claude login"

    def build_command(self, system_prompt_file: os.PathLike | str, output_format: str = "json") -> list:
        cmd = [
            self.claude_bin, "-p",
            "--safe-mode",
            "--settings", json.dumps(ISOLATION_SETTINGS),
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--system-prompt-file", str(system_prompt_file),
            "--output-format", output_format,
            "--effort", self.effort,
        ]
        if output_format == "stream-json":
            cmd.append("--verbose")
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def redact(self, text: str) -> str:
        if not text:
            return text
        if self._oauth_token:
            text = text.replace(self._oauth_token, REDACTED)
        return _GENERIC_TOKEN_RE.sub(REDACTED, text)

    async def _run(self, system_prompt: str, user_text: str, output_format: str) -> Tuple[int, str, str]:
        self.workdir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.workdir, 0o700)
        except OSError:
            pass
        fd, prompt_path = tempfile.mkstemp(prefix="system-", suffix=".md", dir=str(self.workdir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(system_prompt)
            try:
                os.chmod(prompt_path, 0o600)
            except OSError:
                pass
            cmd = self.build_command(prompt_path, output_format)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.workdir),
                    env=build_env(self._oauth_token),
                    start_new_session=True,
                )
            except FileNotFoundError:
                raise ClaudeError(
                    f"Claude CLI not found at {self.claude_bin}. Install Claude Code or set CLAUDE_BIN."
                ) from None
            except PermissionError:
                raise ClaudeError(f"Claude CLI at {self.claude_bin} is not executable (not found or no permission).") from None
            try:
                out, err = await asyncio.wait_for(proc.communicate(user_text.encode("utf-8")), self.timeout)
            except asyncio.TimeoutError:
                await self._kill(proc)
                raise ClaudeTimeout(f"Claude CLI timed out after {self.timeout:g}s") from None
            except asyncio.CancelledError:
                await self._kill(proc)
                raise
            return (
                proc.returncode if proc.returncode is not None else -1,
                self.redact(out.decode("utf-8", "replace")),
                self.redact(err.decode("utf-8", "replace")),
            )
        finally:
            try:
                os.unlink(prompt_path)
            except OSError:
                pass

    @staticmethod
    async def _kill(proc: "asyncio.subprocess.Process") -> None:
        _kill_tree(proc.pid)
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass

    def _explain_auth(self, exc: ClaudeAuthError) -> ClaudeAuthError:
        if not self._oauth_token:
            return exc
        detail = self.redact(exc.detail)
        return ClaudeAuthError(
            "Claude rejected the subscription token or it has expired: run `claude setup-token` on a computer "
            f"with a browser and update CLAUDE_CODE_OAUTH_TOKEN. CLI said: {detail}",
            detail,
        )

    async def generate(self, system_prompt: str, user_text: str) -> str:
        code, out, err = await self._run(system_prompt, user_text, "json")
        try:
            return parse_result(code, out, err)
        except ClaudeAuthError as exc:
            raise self._explain_auth(exc) from None

    async def inspect(self) -> Dict[str, Any]:
        """Tiny stream-json request that reports what the CLI loaded."""
        code, out, err = await self._run("Reply with exactly: OK", "ping", "stream-json")
        init: Optional[Dict[str, Any]] = None
        for line in out.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "init":
                init = {
                    key: event.get(key)
                    for key in ("tools", "mcp_servers", "plugins", "skills", "apiKeySource", "apiProvider", "model")
                }
                break
        try:
            reply: Optional[str] = parse_result(code, out, err)
        except ClaudeAuthError as exc:
            raise self._explain_auth(exc) from None
        return {"auth": self.auth_mode, "init": init, "reply": reply}
