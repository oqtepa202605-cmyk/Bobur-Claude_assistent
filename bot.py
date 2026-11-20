"""Entry point.

    python bot.py                       run the bot with settings from .env
    python bot.py --settings-from-env   run in a container (Railway): settings from environment variables
    python bot.py --check-claude        check the Claude CLI setup (no Telegram)
    python bot.py --try "text"          show the reply to a made-up message (no Telegram)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from assistant.claude_cli import ClaudeError
from assistant.config import (
    DEFAULT_ENV_FILE,
    SETTING_KEYS,
    ConfigError,
    Settings,
    env_file_warning,
    load_settings,
)
from assistant.language import LANGUAGE_NAMES, detect_language
from assistant.prompts import build_system_prompt, build_user_prompt
from assistant.service import make_claude_cli, profile_is_filled, read_profile
from assistant.store import ensure_private_dir

log = logging.getLogger("bot")

BAD_API_KEY_SOURCES = {"ANTHROPIC_API_KEY", "apiKeyHelper", "/login managed key"}


def settings_from_process_env(*, require_telegram: bool = True) -> Settings:
    """Read SETTING_KEYS from os.environ, then always remove them from os.environ,
    so the `claude` child process never inherits the bot token."""
    try:
        source = {key: os.environ[key] for key in SETTING_KEYS if key in os.environ}
        return load_settings(DEFAULT_ENV_FILE, require_telegram=require_telegram, source=source)
    finally:
        for key in SETTING_KEYS:
            os.environ.pop(key, None)


def check_inspection(result: Dict[str, Any]) -> List[str]:
    """Problems found in the `inspect()` result (empty list = all good)."""
    problems: List[str] = []
    init = result.get("init")
    if not init:
        problems.append("the CLI did not send an init event")
        return problems
    for key in ("tools", "mcp_servers", "plugins", "skills"):
        if init.get(key):
            problems.append(f"{key} should be empty but is {init.get(key)!r}")
    if init.get("apiKeySource") in BAD_API_KEY_SOURCES:
        problems.append(f"apiKeySource is {init.get('apiKeySource')!r}: an API key would be used, not the subscription")
    if init.get("apiProvider") not in ("firstParty", None):
        problems.append(f"apiProvider is {init.get('apiProvider')!r}, expected firstParty")
    return problems


def _setup_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def _check_claude(settings: Settings) -> int:
    cli = make_claude_cli(settings)
    try:
        result = await cli.inspect()
    except ClaudeError as exc:
        print(json.dumps({"auth": settings.claude_auth_mode, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    problems = check_inspection(result)
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print(f"OK: Claude CLI works and is isolated. Auth: {settings.claude_auth_mode} ({cli.claude_bin})")
    return 0


async def _try_message(settings: Settings, text: str) -> int:
    cli = make_claude_cli(settings)
    language = detect_language(text)
    system_prompt = build_system_prompt(read_profile(settings.profile_path), datetime.now())
    user_prompt = build_user_prompt([{"role": "other", "name": "Friend", "text": text}], language)
    try:
        reply = await cli.generate(system_prompt, user_prompt)
    except ClaudeError as exc:
        print(f"Claude error: {exc}")
        return 1
    print(f"Language: {LANGUAGE_NAMES.get(language or '', 'unknown')} ({language})")
    print(f"Message : {text}")
    print(f"Reply   : {reply}")
    return 0


async def _run_bot(settings: Settings) -> int:
    from aiogram import Bot, Dispatcher
    from aiogram.exceptions import TelegramUnauthorizedError

    from assistant.handlers import ALLOWED_UPDATES, build_router
    from assistant.service import build_assistant

    bot = Bot(token=settings.bot_token or "")
    try:
        try:
            me = await bot.get_me()
        except TelegramUnauthorizedError:
            log.error("Telegram rejected TELEGRAM_BOT_TOKEN. Check the token from @BotFather.")
            return 2
        assistant = build_assistant(settings)
        log.info("Bot @%s is running", me.username)
        if settings.auto_send:
            log.warning("Mode: AUTO-SEND - replies are sent to people from your account!")
        else:
            log.info("Mode: PREVIEW - replies are only shown in the logs, nothing is sent")
        log.info("Claude auth: %s", settings.claude_auth_mode)
        log.info("Claude binary: %s", settings.claude_bin)
        if assistant.state.paused:
            log.warning("The assistant starts PAUSED (send /resume to the bot to continue).")
        if not profile_is_filled(read_profile(settings.profile_path)):
            log.warning("profile.md is not filled in yet: replies will not sound like you.")
        dp = Dispatcher()
        dp.include_router(build_router(assistant, settings.owner_id))
        await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
        return 0
    finally:
        await bot.session.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Telegram Business personal assistant (Claude Code CLI).")
    parser.add_argument("--settings-from-env", action="store_true", help="read settings from environment variables (container / Railway)")
    parser.add_argument("--check-claude", action="store_true", help="check the Claude CLI setup and exit")
    parser.add_argument("--try", dest="try_text", metavar="TEXT", help="show the reply to a made-up message and exit")
    args = parser.parse_args(argv)

    _setup_output()
    require_telegram = not (args.check_claude or args.try_text is not None)
    try:
        if args.settings_from_env:
            settings = settings_from_process_env(require_telegram=require_telegram)
        else:
            settings = load_settings(DEFAULT_ENV_FILE, require_telegram=require_telegram)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.from_environment and settings.env_file is not None:
        warning = env_file_warning(settings.env_file)
        if warning:
            log.warning(warning)
    ensure_private_dir(settings.data_dir)
    ensure_private_dir(settings.claude_workdir)

    if args.check_claude:
        return asyncio.run(_check_claude(settings))
    if args.try_text is not None:
        return asyncio.run(_try_message(settings, args.try_text))
    try:
        return asyncio.run(_run_bot(settings))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
