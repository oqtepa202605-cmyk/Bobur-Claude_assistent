from __future__ import annotations

import json
import os
import stat
import sys
import textwrap
import time
from pathlib import Path

import pytest

from assistant.claude_cli import (
    ISOLATION_SETTINGS,
    ClaudeAuthError,
    ClaudeCLI,
    ClaudeError,
    ClaudeLimitError,
    ClaudeTimeout,
    classify_failure,
    parse_result,
)

TOKEN = "sk-ant-oat01-" + "Ab1_" * 15
PARENT_TOKEN = "sk-ant-oat01-" + "PARENT" * 8

FAKE_CLAUDE = r'''
import json, os, stat, subprocess, sys, time

argv = sys.argv[1:]
stdin = sys.stdin.buffer.read().decode("utf-8")
mode = os.environ.get("FAKE_MODE", "ok")
record = {
    "argv": argv,
    "stdin": stdin,
    "env": dict(os.environ),
    "cwd": os.getcwd(),
    "cwd_files": sorted(os.listdir(os.getcwd())),
    "pid": os.getpid(),
}
if "--system-prompt-file" in argv:
    path = argv[argv.index("--system-prompt-file") + 1]
    record["prompt_path"] = path
    with open(path, encoding="utf-8") as fh:
        record["prompt"] = fh.read()
    record["prompt_mode"] = stat.S_IMODE(os.stat(path).st_mode)
record["cwd_mode"] = stat.S_IMODE(os.stat(os.getcwd()).st_mode)

def save():
    with open(os.environ["FAKE_RECORD"], "w", encoding="utf-8") as fh:
        json.dump(record, fh)

def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")

def result(text, error=False, status=None):
    return {"type": "result", "subtype": "success", "is_error": error, "result": text, "api_error_status": status}

token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
if mode == "sleep":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    record["grandchild"] = child.pid
    save()
    time.sleep(60)
save()
if mode == "ok":
    if "stream-json" in argv:
        out({"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "plugins": [], "skills": [],
             "apiKeySource": "none", "apiProvider": "firstParty", "model": "claude-test"})
        out(result("OK"))
    else:
        out(result("  Hello there  \n"))
elif mode == "limit_epoch":
    out(result("Claude AI usage limit reached|1760000000", error=True))
elif mode == "limit_text":
    out(result("You've hit your limit · resets 3pm (Asia/Tashkent)", error=True))
elif mode == "auth":
    sys.stderr.write("auth failed for token " + token + "\n")
    out(result("Invalid API key · Please run /login (token " + token + ")", error=True, status=401))
elif mode == "crash":
    sys.stderr.write("Segmentation fault: boom\n")
    sys.exit(3)
elif mode == "empty":
    out(result("   "))
elif mode == "echo_token":
    out(result("token is " + token))
'''


def _make_fake(directory: Path) -> Path:
    src = directory / "src"
    src.mkdir()
    body = textwrap.dedent(FAKE_CLAUDE)
    if os.name == "posix":
        path = directory / "claude"
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)
        return path
    # Windows: wrap the script in a .exe launcher (same mechanism pip uses for console scripts).
    from pip._vendor.distlib.scripts import ScriptMaker

    (src / "claude.py").write_text(f"#!/usr/bin/env python\n{body}", encoding="utf-8")
    maker = ScriptMaker(str(src), str(directory))
    maker.executable = sys.executable
    maker.variants = {""}
    made = maker.make("claude.py")
    return Path(made[0])


@pytest.fixture(scope="session")
def fake_claude(tmp_path_factory) -> Path:
    return _make_fake(tmp_path_factory.mktemp("fakebin"))


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    record = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_RECORD", str(record))
    monkeypatch.setenv("FAKE_MODE", "ok")
    for key in list(os.environ):
        if key.upper().startswith("ANTHROPIC_") or key.upper().startswith("CLAUDE"):
            monkeypatch.delenv(key, raising=False)

    def read() -> dict:
        return json.loads(record.read_text(encoding="utf-8"))

    return read


def make_cli(fake: Path, tmp_path: Path, **kwargs) -> ClaudeCLI:
    kwargs.setdefault("timeout", 30)
    return ClaudeCLI(str(fake), workdir=tmp_path / "data" / "claude-run", **kwargs)


def _alive(pid: int) -> bool:
    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


# ------------------------------------------------------------- happy path


async def test_reply_is_stripped(fake_claude, tmp_path, run_env):
    cli = make_cli(fake_claude, tmp_path)
    assert await cli.generate("system", "hello") == "Hello there"


async def test_message_only_in_stdin_and_profile_in_private_temp_file(fake_claude, tmp_path, run_env):
    cli = make_cli(fake_claude, tmp_path)
    await cli.generate("PROFILE: secret-profile-text", "MESSAGE: hi there")
    rec = run_env()
    assert rec["stdin"] == "MESSAGE: hi there"
    joined = " ".join(rec["argv"])
    assert "MESSAGE" not in joined and "secret-profile-text" not in joined
    assert rec["prompt"] == "PROFILE: secret-profile-text"
    if os.name == "posix":
        assert rec["prompt_mode"] == 0o600
    assert not Path(rec["prompt_path"]).exists()  # removed afterwards


async def test_temp_file_removed_on_error(fake_claude, tmp_path, run_env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "crash")
    cli = make_cli(fake_claude, tmp_path)
    with pytest.raises(ClaudeError):
        await cli.generate("system", "hi")
    assert not Path(run_env()["prompt_path"]).exists()
    assert list((tmp_path / "data" / "claude-run").iterdir()) == []


async def test_no_shell_is_used(fake_claude, tmp_path, run_env):
    marker = tmp_path / "pwned"
    text = f"$(touch {marker}) `touch {marker}` ; touch {marker} && echo hi"
    cli = make_cli(fake_claude, tmp_path)
    await cli.generate("system", text)
    assert run_env()["stdin"] == text
    assert not marker.exists()


async def test_isolation_flags_in_order(fake_claude, tmp_path, run_env):
    cli = make_cli(fake_claude, tmp_path, effort="medium")
    await cli.generate("system", "hi")
    argv = run_env()["argv"]
    expected = [
        "-p", "--safe-mode", "--settings", json.dumps(ISOLATION_SETTINGS), "--tools", "", "--strict-mcp-config",
        "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
        "--system-prompt-file", argv[12], "--output-format", "json", "--effort", "medium",
    ]
    assert argv == expected
    assert "--mcp-config" not in argv and "--bare" not in argv
    settings = json.loads(argv[3])
    assert settings["disableAllHooks"] is True
    assert settings["enabledPlugins"] and not any(settings["enabledPlugins"].values())
    assert "cc-plugin-telemetry@builtin" in settings["enabledPlugins"]


async def test_model_flag_and_stream_json_verbose(fake_claude, tmp_path, run_env):
    cli = make_cli(fake_claude, tmp_path, model="sonnet")
    await cli.inspect()
    argv = run_env()["argv"]
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"


async def test_child_environment_is_cleaned(fake_claude, tmp_path, run_env, monkeypatch):
    home = str(tmp_path / "home")
    monkeypatch.setenv("HOME", home)
    for key, value in {
        "ANTHROPIC_API_KEY": "sk-ant-api03-xxx",
        "ANTHROPIC_BASE_URL": "http://evil",
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "CLAUDE_CODE_OAUTH_TOKEN": PARENT_TOKEN,
        "CLAUDE_CODE_SIMPLE": "1",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_USE_VERTEX": "1",
        "CLAUDE_CODE_USE_FOUNDRY": "1",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
    }.items():
        monkeypatch.setenv(key, value)
    cli = make_cli(fake_claude, tmp_path)
    await cli.generate("system", "hi")
    env = {k.upper(): v for k, v in run_env()["env"].items()}
    assert not [k for k in env if k.startswith("ANTHROPIC_")]
    for key in ("TELEGRAM_BOT_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        assert key not in env
    assert env["HOME"] == home
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"


async def test_configured_token_only_reaches_child_env(fake_claude, tmp_path, run_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", PARENT_TOKEN)
    cli = make_cli(fake_claude, tmp_path, oauth_token=TOKEN)
    await cli.generate("system prompt", "user text")
    rec = run_env()
    env = {k.upper(): v for k, v in rec["env"].items()}
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert TOKEN not in " ".join(rec["argv"]) and TOKEN not in rec["stdin"] and TOKEN not in rec["prompt"]
    assert TOKEN not in repr(cli)


async def test_no_token_configured_means_no_token_in_child(fake_claude, tmp_path, run_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", PARENT_TOKEN)
    cli = make_cli(fake_claude, tmp_path)
    await cli.generate("system", "hi")
    env = {k.upper(): v for k, v in run_env()["env"].items()}
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


async def test_token_is_redacted_from_output(fake_claude, tmp_path, run_env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "echo_token")
    cli = make_cli(fake_claude, tmp_path, oauth_token=TOKEN)
    reply = await cli.generate("system", "hi")
    assert TOKEN not in reply and "[REDACTED]" in reply


async def test_rejected_token_message(fake_claude, tmp_path, run_env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "auth")
    cli = make_cli(fake_claude, tmp_path, oauth_token=TOKEN)
    with pytest.raises(ClaudeAuthError) as info:
        await cli.generate("system", "hi")
    text = str(info.value)
    assert "claude setup-token" in text and "CLI said:" in text and "Invalid API key" in text
    assert TOKEN not in text and TOKEN not in info.value.detail
    assert "[REDACTED]" in text


async def test_login_error_without_token(fake_claude, tmp_path, run_env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "auth")
    cli = make_cli(fake_claude, tmp_path)
    with pytest.raises(ClaudeAuthError) as info:
        await cli.generate("system", "hi")
    assert "/login" in str(info.value)


async def test_inspect_reports_auth(fake_claude, tmp_path, run_env):
    cli = make_cli(fake_claude, tmp_path, oauth_token=TOKEN, auth_label="subscription token from .env")
    result = await cli.inspect()
    assert result["auth"] == "subscription token from .env"
    assert result["init"]["plugins"] == [] and result["init"]["apiProvider"] == "firstParty"
    assert result["reply"] == "OK"
    rec = run_env()
    assert rec["stdin"] == "ping" and rec["prompt"] == "Reply with exactly: OK"
    plain = make_cli(fake_claude, tmp_path)
    assert (await plain.inspect())["auth"] == "this machine's claude login"


async def test_runs_in_own_private_empty_dir(fake_claude, tmp_path, run_env):
    cli = make_cli(fake_claude, tmp_path)
    await cli.generate("system", "hi")
    rec = run_env()
    assert Path(rec["cwd"]).resolve() == (tmp_path / "data" / "claude-run").resolve()
    assert rec["cwd_files"] == [Path(rec["prompt_path"]).name]
    if os.name == "posix":
        assert rec["cwd_mode"] == 0o700


async def test_timeout_kills_process_group(fake_claude, tmp_path, run_env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    cli = make_cli(fake_claude, tmp_path, timeout=2)
    started = time.monotonic()
    with pytest.raises(ClaudeTimeout):
        await cli.generate("system", "hi")
    assert time.monotonic() - started < 5  # the fake would sleep for 60 s
    rec = run_env()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (_alive(rec["grandchild"]) or _alive(rec["pid"])):
        time.sleep(0.1)
    assert not _alive(rec["grandchild"])
    assert not _alive(rec["pid"])


@pytest.mark.parametrize(
    "mode, exc_type",
    [
        ("limit_epoch", ClaudeLimitError),
        ("limit_text", ClaudeLimitError),
        ("auth", ClaudeAuthError),
        ("crash", ClaudeError),
        ("empty", ClaudeError),
    ],
)
async def test_failures_are_classified(fake_claude, tmp_path, run_env, monkeypatch, mode, exc_type):
    monkeypatch.setenv("FAKE_MODE", mode)
    cli = make_cli(fake_claude, tmp_path)
    with pytest.raises(exc_type) as info:
        await cli.generate("system", "hi")
    if mode == "limit_epoch":
        assert info.value.resets_at == 1760000000
    if mode == "limit_text":
        assert info.value.reset_text == "resets 3pm (Asia/Tashkent)"
    if mode == "crash":
        assert "Segmentation fault" in str(info.value)
        assert not isinstance(info.value, (ClaudeLimitError, ClaudeAuthError))


async def test_missing_binary(tmp_path, run_env):
    cli = ClaudeCLI(str(tmp_path / "nope" / "claude"), workdir=tmp_path / "run")
    with pytest.raises(ClaudeError) as info:
        await cli.generate("system", "hi")
    assert "not found" in str(info.value)


# ----------------------------------------------------------- pure functions


def test_classify_failure_limit():
    exc = classify_failure("Claude AI usage limit reached|1760000000")
    assert isinstance(exc, ClaudeLimitError)
    assert exc.resets_at == 1760000000 and exc.detail == "Claude AI usage limit reached"
    assert str(exc).startswith("Claude subscription usage limit reached (resets ")
    text = classify_failure("You're out of extra usage · resets 5am (UTC)")
    assert isinstance(text, ClaudeLimitError) and text.reset_text == "resets 5am (UTC)"
    assert "resets 5am (UTC)" in str(text)
    assert isinstance(classify_failure("anything", 429), ClaudeLimitError)
    assert isinstance(classify_failure("Rate-limit exceeded"), ClaudeLimitError)
    assert isinstance(classify_failure("QUOTA exceeded"), ClaudeLimitError)


def test_classify_failure_auth():
    for msg in ("Not logged in · Please run /login", "Invalid API key", "OAuth token has expired", "Unauthorised"):
        exc = classify_failure(msg)
        assert isinstance(exc, ClaudeAuthError), msg
        assert "/login" in str(exc)
    assert isinstance(classify_failure("x", 401), ClaudeAuthError)
    assert isinstance(classify_failure("x", 403), ClaudeAuthError)
    assert len(classify_failure("authentication " + "y" * 1000).detail) == 300


def test_classify_failure_other():
    exc = classify_failure("weird " + "z" * 2000)
    assert type(exc) is ClaudeError
    assert len(str(exc)) < 600


def test_parse_result():
    ok = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": " hi "})
    assert parse_result(0, "noise\n" + ok + "\n\n", "") == "hi"
    err = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in"})
    with pytest.raises(ClaudeAuthError):
        parse_result(1, err, "")
    other = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": False, "result": "x"})
    with pytest.raises(ClaudeError):
        parse_result(0, other, "")
    with pytest.raises(ClaudeError) as info:
        parse_result(0, json.dumps({"type": "result", "subtype": "success", "result": ""}), "")
    assert "empty" in str(info.value)
    with pytest.raises(ClaudeError) as info:
        parse_result(2, "", "")
    assert "exit code 2" in str(info.value)
    with pytest.raises(ClaudeLimitError):
        parse_result(1, "not json", "usage limit reached|1760000000")
    status = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "x", "api_error_status": 429})
    with pytest.raises(ClaudeLimitError):
        parse_result(1, status, "")
