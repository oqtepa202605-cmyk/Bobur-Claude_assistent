"""Core logic: decides whether and how to answer a Telegram Business message."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BusinessConnection, Message

from .claude_cli import ClaudeCLI, ClaudeError, ClaudeLimitError
from .config import Settings
from .language import detect_language
from .prompts import SKIP_TOKEN, build_system_prompt, build_user_prompt
from .store import HistoryStore, RuntimeState, SeenMessages, ensure_private_dir

log = logging.getLogger(__name__)

MAX_CHUNK = 4000
OWNER_ALERT_INTERVAL = 600  # seconds between "Claude failed" alerts to the owner


class Outcome(str, Enum):
    previewed = "previewed"
    sent = "sent"
    duplicate = "duplicate"
    ignored_bot = "ignored_bot"
    no_connection = "no_connection"
    foreign_connection = "foreign_connection"
    connection_disabled = "connection_disabled"
    unsupported = "unsupported"
    owner_message = "owner_message"
    owner_active = "owner_active"
    paused = "paused"
    limited = "limited"
    skipped = "skipped"
    permission_denied = "permission_denied"
    error = "error"


class Generator(Protocol):
    async def generate(self, system_prompt: str, user_text: str) -> str: ...


@dataclass
class Preview:
    connection_id: str
    chat_id: int
    chat_name: str
    language: Optional[str]
    incoming: str
    reply: str
    note: Optional[str] = None


def print_preview(preview: Preview) -> None:
    bar = "-" * 60
    lines = [
        bar,
        f"PREVIEW, not sent | chat {preview.chat_id} ({preview.chat_name}) | lang={preview.language or '?'}",
        f"  them : {preview.incoming}",
        f"  reply: {preview.reply}",
    ]
    if preview.note:
        lines.append(f"  note : {preview.note}")
    lines.append(bar)
    log.info("\n".join(lines))


def describe(message: Message) -> Optional[str]:
    """Plain-text description of a message, or None for service messages."""
    if message.text:
        return message.text
    caption = f" {message.caption}" if message.caption else ""
    if message.photo:
        return f"[photo]{caption}"
    if message.video:
        return f"[video]{caption}"
    if message.animation:
        return f"[GIF]{caption}"
    if message.voice:
        return f"[voice message]{caption}"
    if message.video_note:
        return "[video message]"
    if message.audio:
        return f"[audio]{caption}"
    if message.document:
        name = f" {message.document.file_name}" if message.document.file_name else ""
        return f"[file{name}]{caption}"
    if message.sticker:
        emoji = f" {message.sticker.emoji}" if message.sticker.emoji else ""
        return f"[sticker]{emoji}"
    if message.location:
        return "[location]"
    if message.contact:
        return "[contact]"
    if message.poll:
        return f"[poll] {message.poll.question}"
    if message.dice:
        return f"[dice] {message.dice.emoji}"
    return None


def can_reply(connection: BusinessConnection) -> bool:
    rights = getattr(connection, "rights", None)
    if rights is not None:
        return bool(getattr(rights, "can_reply", False))
    return bool(getattr(connection, "can_reply", False))


_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def read_profile(path: os.PathLike | str) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    return _COMMENT_RE.sub("", text).strip()


def profile_is_filled(profile: str) -> bool:
    """True when the profile has any content beyond the empty template."""
    for line in profile.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if re.fullmatch(r"[-*]\s*[^:]*:\s*", s):
            continue
        return True
    return False


def _chunks(text: str, size: int = MAX_CHUNK) -> List[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class Assistant:
    def __init__(
        self,
        settings: Settings,
        generator: Generator,
        *,
        clock: Callable[[], float] = time.time,
        preview_sink: Callable[[Preview], None] = print_preview,
    ) -> None:
        self.settings = settings
        self.generator = generator
        self.clock = clock
        self.preview_sink = preview_sink
        data_dir = ensure_private_dir(settings.data_dir)
        self.history = HistoryStore(data_dir / "history.json", settings.history_limit)
        self.seen = SeenMessages(data_dir / "seen.json")
        self.state = RuntimeState(data_dir / "state.json")
        self.previews_path = data_dir / "previews.jsonl"
        self.connections: Dict[str, BusinessConnection] = {}
        self.outcomes: Deque[Outcome] = deque(maxlen=100)
        self._takeover_until: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_owner_alert: Optional[float] = None

    # ------------------------------------------------------------------ events

    def on_business_connection(self, connection: BusinessConnection) -> None:
        self.connections[connection.id] = connection
        if connection.user.id != self.settings.owner_id:
            log.warning(
                "Business connection %s belongs to another account (user=%s); it will be ignored.",
                connection.id,
                connection.user.id,
            )
            return
        log.info(
            "Business connection %s: user=%s enabled=%s can_reply=%s",
            connection.id,
            connection.user.id,
            connection.is_enabled,
            can_reply(connection),
        )

    async def on_business_message(self, bot: Bot, message: Message) -> Outcome:
        outcome = await self._handle(bot, message)
        self.outcomes.append(outcome)
        log.debug("business message %s in chat %s -> %s", message.message_id, message.chat.id, outcome.value)
        return outcome

    # --------------------------------------------------------------- internals

    def _blocked(self, key: str) -> Optional[Outcome]:
        now = self.clock()
        if self.state.paused:
            return Outcome.paused
        limit_until = self.state.limit_until
        if limit_until and limit_until > now:
            return Outcome.limited
        if self._takeover_until.get(key, 0) > now:
            return Outcome.owner_active
        return None

    def _check_connection(self, connection: BusinessConnection) -> Optional[str]:
        """Return why we may not reply through this connection, or None."""
        if connection.user.id != self.settings.owner_id:
            return "the business connection belongs to another account"
        if not connection.is_enabled:
            return "the business connection is disabled"
        if not can_reply(connection):
            return "the bot has no permission to reply in Telegram Business settings"
        return None

    async def _handle(self, bot: Bot, message: Message) -> Outcome:
        conn_id = message.business_connection_id
        if not conn_id:
            return Outcome.no_connection
        chat_id = message.chat.id

        # Mark before any await so parallel copies of the same update are caught.
        if not self.seen.first_time(f"{conn_id}:{chat_id}:{message.message_id}"):
            return Outcome.duplicate

        if message.sender_business_bot is not None or (message.from_user is not None and message.from_user.is_bot):
            return Outcome.ignored_bot

        connection = self.connections.get(conn_id)
        if connection is None:
            try:
                connection = await bot.get_business_connection(business_connection_id=conn_id)
            except Exception as exc:  # TelegramAPIError, network errors
                log.warning("Could not look up business connection %s: %s", conn_id, exc)
                return Outcome.no_connection
            self.connections[conn_id] = connection
        if connection.user.id != self.settings.owner_id:
            log.warning("Message from a business connection of another account (%s); ignored.", connection.user.id)
            return Outcome.foreign_connection
        if not connection.is_enabled:
            return Outcome.connection_disabled

        text = describe(message)
        if text is None:
            return Outcome.unsupported

        key = HistoryStore.key(conn_id, chat_id)
        now = self.clock()
        sender = message.from_user

        if sender is not None and sender.id == self.settings.owner_id:
            self.history.add(conn_id, chat_id, role="owner", name=sender.full_name, text=text, lang=None, ts=now)
            if self.settings.owner_takeover_minutes > 0:
                self._takeover_until[key] = now + self.settings.owner_takeover_minutes * 60
            return Outcome.owner_message

        language = detect_language(text) or self.history.last_language(conn_id, chat_id)
        name = sender.full_name if sender is not None else (message.chat.full_name or str(chat_id))
        self.history.add(conn_id, chat_id, role="other", name=name, text=text, lang=language, ts=now)

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            blocked = self._blocked(key)
            if blocked is not None:
                return blocked

            system_prompt = build_system_prompt(read_profile(self.settings.profile_path), datetime.now())
            user_prompt = build_user_prompt(self.history.get(conn_id, chat_id), language)
            try:
                reply = await self.generator.generate(system_prompt, user_prompt)
            except ClaudeLimitError as exc:
                return await self._on_limit(bot, exc)
            except ClaudeError as exc:
                log.error("Claude failed for chat %s: %s", chat_id, exc)
                await self._alert_owner(bot, f"⚠️ Claude javob tayyorlay olmadi: {exc}", rate_limited=True)
                return Outcome.error

            reply = (reply or "").strip()
            if not reply or reply.upper().startswith(SKIP_TOKEN):
                log.info("Claude chose not to reply in chat %s.", chat_id)
                return Outcome.skipped

            preview = Preview(conn_id, chat_id, name, language, text, reply)

            if not self.settings.auto_send:
                self._emit_preview(preview)
                return Outcome.previewed

            # Auto-send: the owner may have written while Claude was thinking.
            blocked = self._blocked(key)
            if blocked is not None:
                reasons = {
                    Outcome.owner_active: "not sent: you wrote in this chat while the reply was being generated",
                    Outcome.paused: "not sent: the assistant was paused",
                    Outcome.limited: "not sent: the usage limit was hit",
                }
                preview.note = reasons.get(blocked, "not sent")
                self._emit_preview(preview)
                return blocked

            # Ask Telegram again (not the cache) right before sending.
            try:
                fresh = await bot.get_business_connection(business_connection_id=conn_id)
            except Exception as exc:
                preview.note = f"not sent: could not re-check the business connection ({exc})"
                self._emit_preview(preview)
                return Outcome.permission_denied
            self.connections[conn_id] = fresh
            problem = self._check_connection(fresh)
            if problem:
                preview.note = f"not sent: {problem}"
                self._emit_preview(preview)
                return Outcome.permission_denied

            try:
                for part in _chunks(reply):
                    await bot.send_message(chat_id, part, business_connection_id=conn_id)
            except TelegramAPIError as exc:
                log.error("Sending the reply to chat %s failed: %s", chat_id, exc)
                return Outcome.error

            owner_name = fresh.user.full_name
            self.history.add(conn_id, chat_id, role="owner", name=owner_name, text=reply, lang=None, ts=self.clock())
            log.info("Sent a reply to chat %s (%s).", chat_id, name)
            return Outcome.sent

    async def _on_limit(self, bot: Bot, exc: ClaudeLimitError) -> Outcome:
        now = self.clock()
        if exc.resets_at and exc.resets_at > now:
            until = exc.resets_at
        else:
            until = now + self.settings.limit_cooldown_minutes * 60
        self.state.limit_until = until
        log.warning("%s. Replies are paused until %s.", exc, _fmt_time(until))
        await self._alert_owner(
            bot,
            f"⏸ Claude obuna limiti tugadi. Javoblar {_fmt_time(until)} gacha to'xtatildi. "
            "Darhol davom ettirish uchun: /resume",
            rate_limited=False,
        )
        return Outcome.limited

    async def _alert_owner(self, bot: Bot, text: str, *, rate_limited: bool) -> None:
        if not self.settings.auto_send or self.settings.owner_id is None:
            return
        now = self.clock()
        if rate_limited and self._last_owner_alert is not None and now - self._last_owner_alert < OWNER_ALERT_INTERVAL:
            return
        self._last_owner_alert = now
        try:
            await bot.send_message(self.settings.owner_id, text[:MAX_CHUNK])
        except TelegramAPIError as exc:
            log.error("Could not notify the owner: %s", exc)

    def _emit_preview(self, preview: Preview) -> None:
        try:
            self.preview_sink(preview)
        except Exception:  # never let logging break the flow
            log.exception("Preview sink failed")
        record = asdict(preview)
        record["ts"] = self.clock()
        line = json.dumps(record, ensure_ascii=False) + "\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
        fd = os.open(self.previews_path, flags, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    # ------------------------------------------------------------ owner control

    def pause(self) -> None:
        self.state.paused = True
        log.info("Assistant paused by the owner.")

    def resume(self) -> None:
        self.state.paused = False
        self.state.limit_until = None
        self._takeover_until.clear()
        log.info("Assistant resumed by the owner.")

    def _limit_active(self) -> Optional[float]:
        until = self.state.limit_until
        return until if until and until > self.clock() else None

    def status_text(self) -> str:
        mode = "AUTO-SEND" if self.settings.auto_send else "PREVIEW (replies are only shown in the logs)"
        state = "paused" if self.state.paused else "running"
        limit = self._limit_active()
        lines = [
            f"Mode: {mode}",
            f"State: {state}",
            f"Usage limit: until {_fmt_time(limit)}" if limit else "Usage limit: none",
            f"Chats in history: {self.history.chat_count()}",
        ]
        return "\n".join(lines)

    def start_text(self) -> str:
        mode = (
            "AUTO-SEND — javoblar avtomatik yuboriladi"
            if self.settings.auto_send
            else "PREVIEW — javoblar hech kimga yuborilmaydi, faqat logda ko'rinadi"
        )
        state = "⏸ pauzada" if self.state.paused else "▶️ ishlayapti"
        limit = self._limit_active()
        minutes = self.settings.owner_takeover_minutes
        lines = [
            "Salom! Men sizning shaxsiy yordamchingizman.",
            "Sizga Telegram'da kimdir yozsa, Claude yordamida sizning uslubingizda, sizning nomingizdan javob tayyorlayman.",
            "",
            "Hozirgi holat:",
            f"• Rejim: {mode}",
            f"• Holat: {state}",
        ]
        if limit:
            lines.append(f"• Claude limiti: {_fmt_time(limit)} gacha kutilmoqda")
        lines += [
            "",
            "Qanday ulanadi:",
            "1. Telegram → Settings → Telegram Business → Chatbots",
            "2. Shu botning username'ini kiriting",
            "3. Bot qaysi chatlarni ko'rishini tanlang",
            "4. Javob berish ruxsatini yoqing",
            "Telegram Business uchun Telegram Premium kerak.",
            "",
            "Buyruqlar:",
            "/pause — javob berishni to'xtatish",
            "/resume — davom ettirish (limit va kutishlarni ham tozalaydi)",
            "/status — holatni ko'rish",
            "",
            "Bilib qo'ying:",
        ]
        if minutes > 0:
            lines.append(f"• Chatga o'zingiz yozsangiz, bot o'sha chatda {minutes} daqiqa jim turadi.")
        lines += [
            "• Pul, qarz, uchrashuv va rejalar bo'yicha hech narsaga rozilik bermaydi.",
            "• Men haqingizda bilishim uchun profile.md faylini to'ldiring.",
        ]
        if not self.settings.auto_send:
            lines.append("• Hozir PREVIEW rejimi. Javoblarni haqiqatan yuborish uchun AUTO_SEND=true qiling.")
        return "\n".join(lines)


# --------------------------------------------------------------------- factories


def make_claude_cli(settings: Settings) -> ClaudeCLI:
    return ClaudeCLI(
        settings.claude_bin,
        workdir=settings.claude_workdir,
        model=settings.claude_model,
        effort=settings.claude_effort,
        timeout=settings.claude_timeout,
        oauth_token=settings.claude_oauth_token,
        auth_label=settings.claude_auth_mode,
    )


def build_assistant(settings: Settings, **kwargs: Any) -> Assistant:
    generator = kwargs.pop("generator", None) or make_claude_cli(settings)
    return Assistant(settings, generator, **kwargs)
