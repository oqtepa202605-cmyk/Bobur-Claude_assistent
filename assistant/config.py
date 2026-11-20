"""Settings loading.

Settings come from exactly one source and are never mixed:

* local development: only the ``.env`` file (read with ``dotenv_values``; the
  shell environment is ignored on purpose);
* container (Railway): ``bot.py --settings-from-env`` reads the process
  environment and passes it in as ``source``; ``.env`` is not read at all.

Nothing is ever written to ``os.environ``, so tokens do not leak into other
processes.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional

from dotenv import dotenv_values

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_DIR / ".env"

SETTING_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "OWNER_ID",
    "AUTO_SEND",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_BIN",
    "CLAUDE_MODEL",
    "CLAUDE_EFFORT",
    "CLAUDE_TIMEOUT_SECONDS",
    "LIMIT_COOLDOWN_MINUTES",
    "OWNER_TAKEOVER_MINUTES",
    "HISTORY_LIMIT",
    "DATA_DIR",
    "PROFILE_PATH",
)

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}
_BOT_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]+$")

ENV_SOURCE_NAME = "the environment variables"
CREATE_ENV_HINT = "cp .env.example .env && chmod 600 .env"


class ConfigError(Exception):
    """Invalid or missing configuration. Messages never echo secret values."""


@dataclass(frozen=True)
class Settings:
    bot_token: Optional[str] = field(repr=False)
    owner_id: Optional[int]
    auto_send: bool
    claude_oauth_token: Optional[str] = field(repr=False)
    claude_bin: str
    claude_model: Optional[str]
    claude_effort: str
    claude_timeout: float
    limit_cooldown_minutes: int
    owner_takeover_minutes: int
    history_limit: int
    data_dir: Path
    profile_path: Path
    env_file: Optional[Path] = None
    from_environment: bool = False

    @property
    def claude_auth_mode(self) -> str:
        if not self.claude_oauth_token:
            return "this machine's claude login"
        if self.from_environment:
            return "subscription token from environment variables"
        return "subscription token from .env"

    @property
    def claude_workdir(self) -> Path:
        return self.data_dir / "claude-run"


def default_claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(local)


def _clean(values: Mapping[str, Optional[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        out[key] = str(value).strip()
    return out


def _parse_bool(name: str, raw: str, where: str, default: bool) -> bool:
    if raw == "":
        return default
    low = raw.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false (also 1/0, yes/no, on/off). Check {where}.")


def _parse_int(name: str, raw: str, where: str, default: int, minimum: int) -> int:
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number. Check {where}.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}. Check {where}.")
    return value


def _parse_oauth_token(raw: str, where: str) -> Optional[str]:
    if raw == "":
        return None
    if raw.startswith("sk-ant-api"):
        raise ConfigError(
            "CLAUDE_CODE_OAUTH_TOKEN looks like an Anthropic API key, not a subscription token. "
            "API keys are not used by this bot. Run `claude setup-token` and use its sk-ant-oat... "
            f"token instead. Check {where}."
        )
    if not raw.startswith("sk-ant-oat") or re.search(r"\s", raw):
        raise ConfigError(
            "CLAUDE_CODE_OAUTH_TOKEN is not a valid `claude setup-token` token: it must start with "
            "sk-ant-oat and be on a single line without spaces. "
            f"Check {where}."
        )
    return raw


def _resolve_path(raw: str, default: str, base: Path) -> Path:
    path = Path(raw or default).expanduser()
    if not path.is_absolute():
        path = base / path
    return path


def load_settings(
    env_file: os.PathLike | str = DEFAULT_ENV_FILE,
    *,
    require_telegram: bool = True,
    overrides: Optional[Mapping[str, Optional[str]]] = None,
    source: Optional[Mapping[str, Optional[str]]] = None,
) -> Settings:
    env_path = Path(env_file)
    base = env_path.resolve().parent
    from_environment = source is not None

    if from_environment:
        values = _clean(source or {})
        where = ENV_SOURCE_NAME
    else:
        if not env_path.is_file():
            raise ConfigError(f"Settings file {env_path} not found. Create it with: {CREATE_ENV_HINT}")
        values = _clean(dotenv_values(env_path))
        where = str(env_path)

    if overrides:
        values.update(_clean(overrides))

    def get(key: str) -> str:
        return values.get(key, "")

    bot_token = get("TELEGRAM_BOT_TOKEN") or None
    owner_raw = get("OWNER_ID")
    if require_telegram:
        if not bot_token:
            raise ConfigError(f"TELEGRAM_BOT_TOKEN is empty. Get a token from @BotFather and set it in {where}.")
        if not _BOT_TOKEN_RE.match(bot_token):
            raise ConfigError(f"TELEGRAM_BOT_TOKEN does not look like a bot token (<digits>:<text>). Check {where}.")
        if not owner_raw:
            raise ConfigError(f"OWNER_ID is empty. Put your numeric Telegram user ID (from @userinfobot) in {where}.")
    owner_id: Optional[int] = None
    if owner_raw:
        if not owner_raw.isdigit():
            raise ConfigError(f"OWNER_ID must contain only digits. Check {where}.")
        owner_id = int(owner_raw)

    effort = (get("CLAUDE_EFFORT") or "low").lower()
    if effort not in EFFORT_LEVELS:
        raise ConfigError(f"CLAUDE_EFFORT must be one of: {', '.join(EFFORT_LEVELS)}. Check {where}.")

    return Settings(
        bot_token=bot_token,
        owner_id=owner_id,
        auto_send=_parse_bool("AUTO_SEND", get("AUTO_SEND"), where, False),
        claude_oauth_token=_parse_oauth_token(get("CLAUDE_CODE_OAUTH_TOKEN"), where),
        claude_bin=get("CLAUDE_BIN") or default_claude_bin(),
        claude_model=get("CLAUDE_MODEL") or None,
        claude_effort=effort,
        claude_timeout=float(_parse_int("CLAUDE_TIMEOUT_SECONDS", get("CLAUDE_TIMEOUT_SECONDS"), where, 120, 1)),
        limit_cooldown_minutes=_parse_int("LIMIT_COOLDOWN_MINUTES", get("LIMIT_COOLDOWN_MINUTES"), where, 30, 1),
        owner_takeover_minutes=_parse_int("OWNER_TAKEOVER_MINUTES", get("OWNER_TAKEOVER_MINUTES"), where, 15, 0),
        history_limit=_parse_int("HISTORY_LIMIT", get("HISTORY_LIMIT"), where, 30, 1),
        data_dir=_resolve_path(get("DATA_DIR"), "data", base),
        profile_path=_resolve_path(get("PROFILE_PATH"), "profile.md", base),
        env_file=None if from_environment else env_path,
        from_environment=from_environment,
    )


def env_file_warning(path: os.PathLike | str) -> Optional[str]:
    """Return a warning if the .env file is readable by group/others (POSIX only)."""
    if os.name != "posix":
        return None
    p = Path(path)
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
    except OSError:
        return None
    if mode & 0o077:
        return (
            f"{p} is readable by other users (mode {oct(mode)}). It holds secret tokens; "
            f"run: chmod 600 {p}"
        )
    return None
