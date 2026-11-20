"""Offline test harness: a recording aiogram session, a fake generator and a fake clock."""
from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetBusinessConnection, SendMessage, TelegramMethod
from aiogram.types import BusinessConnection, Chat, Message, Update, User

from assistant.config import Settings, load_settings
from assistant.handlers import build_router
from assistant.service import Assistant, Preview

OWNER_ID = 1001
FOREIGN_ID = 2002
BOT_ID = 9999
BOT_TOKEN = "123456:TEST-token_abc"
CONN_ID = "conn-1"
START_TS = 1_800_000_000.0


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: List[TelegramMethod] = []
        self.connections: Dict[str, Optional[BusinessConnection]] = {}
        self._ids = itertools.count(50_000)

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: Optional[int] = None) -> Any:
        self.requests.append(method)
        if isinstance(method, GetBusinessConnection):
            conn = self.connections.get(method.business_connection_id)
            if conn is None:
                raise TelegramBadRequest(method=method, message="Bad Request: business connection not found")
            return conn
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids),
                date=int(START_TS),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
                business_connection_id=method.business_connection_id,
            )
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise AssertionError("stream_content must not be used in tests")
        yield b""

    # helpers
    def of_type(self, kind: type) -> List[TelegramMethod]:
        return [r for r in self.requests if isinstance(r, kind)]

    @property
    def sent(self) -> List[SendMessage]:
        return self.of_type(SendMessage)  # type: ignore[return-value]


class FakeGenerator:
    """Returns queued replies (or raises queued exceptions) and records every call."""

    def __init__(self, *responses: Any) -> None:
        self.responses: List[Any] = list(responses)
        self.calls: List[Dict[str, str]] = []
        self.hook: Optional[Callable[[], Any]] = None

    def queue(self, *responses: Any) -> None:
        self.responses.extend(responses)

    async def generate(self, system_prompt: str, user_text: str) -> str:
        self.calls.append({"system": system_prompt, "user": user_text})
        if self.hook is not None:
            result = self.hook()
            if asyncio.iscoroutine(result):
                await result
        await asyncio.sleep(0)
        item = self.responses.pop(0) if self.responses else "Default reply"
        if isinstance(item, BaseException):
            raise item
        return item


class Clock:
    def __init__(self, now: float = START_TS) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def connection_payload(
    *, conn_id: str = CONN_ID, user_id: int = OWNER_ID, enabled: bool = True, can_reply: bool = True
) -> Dict[str, Any]:
    rights = {"can_reply": True} if can_reply else {}
    return {
        "id": conn_id,
        "user": {"id": user_id, "is_bot": False, "first_name": "Owner" if user_id == OWNER_ID else "Stranger"},
        "user_chat_id": user_id,
        "date": int(START_TS),
        "is_enabled": enabled,
        "rights": rights,
        "can_reply": can_reply,  # legacy field, for older aiogram versions
    }


class Harness:
    def __init__(self, tmp_path: Path, **overrides: Any) -> None:
        self.tmp_path = tmp_path
        self.data_dir = tmp_path / "data"
        self.profile = tmp_path / "profile.md"
        self.profile.write_text("# Men haqimda\n- Ism: Aziz\n- Shahar: Toshkent\n", encoding="utf-8")
        env_file = tmp_path / ".env"
        env_file.write_text("", encoding="utf-8")
        values = {
            "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
            "OWNER_ID": str(OWNER_ID),
            "AUTO_SEND": "false",
            "DATA_DIR": str(self.data_dir),
            "PROFILE_PATH": str(self.profile),
            "CLAUDE_BIN": str(tmp_path / "no-claude"),
        }
        values.update({k: str(v) for k, v in overrides.items()})
        self.settings: Settings = load_settings(env_file, overrides=values)
        self.session = RecordingSession()
        self.bot = Bot(token=BOT_TOKEN, session=self.session)
        self.generator = FakeGenerator()
        self.clock = Clock()
        self.previews: List[Preview] = []
        self._message_ids = itertools.count(1)
        self._build()

    def _build(self) -> None:
        self.assistant = Assistant(
            self.settings, self.generator, clock=self.clock, preview_sink=self.previews.append
        )
        self.dp = Dispatcher()
        self.dp.include_router(build_router(self.assistant, self.settings.owner_id))

    def restart(self) -> None:
        self._build()

    @property
    def outcomes(self) -> List[str]:
        return [o.value for o in self.assistant.outcomes]

    @property
    def last_outcome(self) -> str:
        return self.assistant.outcomes[-1].value

    async def feed(self, update: Dict[str, Any]) -> None:
        upd = Update.model_validate(update, context={"bot": self.bot})
        await self.dp.feed_update(self.bot, upd)

    def set_connection(self, **kwargs: Any) -> BusinessConnection:
        payload = connection_payload(**kwargs)
        conn = BusinessConnection.model_validate(payload)
        self.session.connections[payload["id"]] = conn
        return conn

    async def connect(self, **kwargs: Any) -> None:
        payload = connection_payload(**kwargs)
        self.set_connection(**kwargs)
        await self.feed({"update_id": next(self._message_ids), "business_connection": payload})

    def business_update(
        self,
        text: Optional[str] = "Salom, qalesan?",
        *,
        from_id: int = 555,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        connection_id: Optional[str] = CONN_ID,
        is_bot: bool = False,
        via_business_bot: bool = False,
        first_name: str = "Ali",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        chat_id = chat_id if chat_id is not None else (555 if from_id == OWNER_ID else from_id)
        msg: Dict[str, Any] = {
            "message_id": message_id if message_id is not None else next(self._message_ids),
            "date": int(self.clock.now),
            "chat": {"id": chat_id, "type": "private", "first_name": "Ali"},
            "from": {"id": from_id, "is_bot": is_bot, "first_name": "Owner" if from_id == OWNER_ID else first_name},
        }
        if connection_id is not None:
            msg["business_connection_id"] = connection_id
        if text is not None:
            msg["text"] = text
        if via_business_bot:
            msg["sender_business_bot"] = {"id": BOT_ID, "is_bot": True, "first_name": "Assistant", "username": "assistant_bot"}
        if extra:
            msg.update(extra)
        return {"update_id": next(self._message_ids), "business_message": msg}

    async def business_message(self, text: Optional[str] = "Salom, qalesan?", **kwargs: Any) -> str:
        await self.feed(self.business_update(text, **kwargs))
        return self.last_outcome

    async def direct_message(self, text: str, *, from_id: int = OWNER_ID) -> None:
        msg: Dict[str, Any] = {
            "message_id": next(self._message_ids),
            "date": int(self.clock.now),
            "chat": {"id": from_id, "type": "private", "first_name": "X"},
            "from": {"id": from_id, "is_bot": False, "first_name": "X"},
            "text": text,
        }
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        await self.feed({"update_id": next(self._message_ids), "message": msg})


@pytest.fixture
def make_harness(tmp_path: Path) -> Callable[..., Harness]:
    def factory(**overrides: Any) -> Harness:
        return Harness(tmp_path, **overrides)

    return factory
