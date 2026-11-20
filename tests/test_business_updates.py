from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest
from aiogram.methods import GetBusinessConnection, SendMessage

from assistant.claude_cli import ClaudeAuthError, ClaudeLimitError, ClaudeTimeout

from .conftest import CONN_ID, FOREIGN_ID, OWNER_ID

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")


def mode_of(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


# ---------------------------------------------------------------- preview mode


async def test_preview_shows_reply_and_sends_nothing(make_harness):
    h = make_harness()
    h.generator.queue("Yaxshi, o'zing-chi?")
    await h.connect()
    assert await h.business_message("Salom, qalesan?") == "previewed"
    assert h.session.sent == []
    assert len(h.previews) == 1 and h.previews[0].reply == "Yaxshi, o'zing-chi?"
    assert h.previews[0].language == "uz"
    lines = (h.data_dir / "previews.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["reply"] == "Yaxshi, o'zing-chi?"
    history = h.assistant.history.get(CONN_ID, 555)
    assert [i["role"] for i in history] == ["other"]  # the unsent reply is not in history


@posix_only
async def test_previews_file_is_private(make_harness):
    h = make_harness()
    await h.connect()
    await h.business_message()
    assert mode_of(h.data_dir / "previews.jsonl") == 0o600
    assert mode_of(h.data_dir) == 0o700


async def test_known_connection_makes_no_telegram_requests_in_preview(make_harness):
    h = make_harness()
    await h.connect()
    await h.business_message()
    await h.business_message("Yana bir savol bor")
    assert h.session.requests == []


async def test_unknown_connection_is_looked_up_once_then_cached(make_harness):
    h = make_harness()
    h.set_connection()
    await h.business_message("Salom")
    await h.business_message("Qalesan")
    assert len(h.session.of_type(GetBusinessConnection)) == 1
    assert h.session.sent == []
    assert h.outcomes == ["previewed", "previewed"]


async def test_connection_lookup_failure(make_harness):
    h = make_harness()
    assert await h.business_message("Salom", connection_id="missing") == "no_connection"
    assert h.generator.calls == []


async def test_message_without_connection(make_harness):
    h = make_harness()
    assert await h.business_message("Salom", connection_id=None) == "no_connection"


async def test_foreign_and_disabled_connections_do_not_call_claude(make_harness):
    h = make_harness()
    await h.connect(conn_id="foreign", user_id=FOREIGN_ID)
    assert await h.business_message("hi", connection_id="foreign") == "foreign_connection"
    await h.connect(conn_id="off", enabled=False)
    assert await h.business_message("hi", connection_id="off") == "connection_disabled"
    assert h.generator.calls == []


async def test_any_chat_gets_a_reply_without_allowlist(make_harness):
    h = make_harness()
    await h.connect()
    for chat in (11, 22, 33333):
        assert await h.business_message("Salom", from_id=chat) == "previewed"
    assert len(h.generator.calls) == 3


# ------------------------------------------------------------ owner takeover


async def test_owner_message_is_recorded_and_not_answered(make_harness):
    h = make_harness()
    await h.connect()
    assert await h.business_message("Hozir yozaman", from_id=OWNER_ID, chat_id=555) == "owner_message"
    assert h.generator.calls == []
    assert h.assistant.history.get(CONN_ID, 555)[0]["role"] == "owner"


async def test_takeover_silences_chat_then_expires(make_harness):
    h = make_harness(OWNER_TAKEOVER_MINUTES=15)
    await h.connect()
    await h.business_message("Men shu yerdaman", from_id=OWNER_ID, chat_id=555)
    assert await h.business_message("Salom", from_id=555) == "owner_active"
    assert await h.business_message("Salom", from_id=777) == "previewed"  # other chats unaffected
    h.clock.advance(15 * 60 + 1)
    assert await h.business_message("Javob ber", from_id=555) == "previewed"
    # The owner's message is part of the prompt.
    assert "[You]: Men shu yerdaman" in h.generator.calls[-1]["user"]


async def test_takeover_disabled_with_zero(make_harness):
    h = make_harness(OWNER_TAKEOVER_MINUTES=0)
    await h.connect()
    await h.business_message("Men", from_id=OWNER_ID, chat_id=555)
    assert await h.business_message("Salom", from_id=555) == "previewed"


# ------------------------------------------------------------- bots, dupes


async def test_bot_messages_are_ignored(make_harness):
    h = make_harness()
    await h.connect()
    assert await h.business_message("Auto reply", from_id=OWNER_ID, chat_id=555, via_business_bot=True) == "ignored_bot"
    assert await h.business_message("I am a bot", from_id=4242, is_bot=True) == "ignored_bot"
    assert h.generator.calls == []


async def test_duplicates_parallel_and_sequential(make_harness):
    h = make_harness()
    await h.connect()
    upd = h.business_update("Salom", message_id=77)
    await asyncio.gather(h.feed(upd), h.feed(upd))
    await h.feed(upd)
    assert sorted(h.outcomes) == ["duplicate", "duplicate", "previewed"]
    assert len(h.generator.calls) == 1


async def test_duplicates_after_restart(make_harness):
    h = make_harness()
    await h.connect()
    await h.business_message("Salom", message_id=88)
    h.restart()
    await h.connect()
    assert await h.business_message("Salom", message_id=88) == "duplicate"
    assert len(h.generator.calls) == 1


# ----------------------------------------------------------- message kinds


async def test_service_message_is_unsupported(make_harness):
    h = make_harness()
    await h.connect()
    outcome = await h.business_message(None, extra={"new_chat_title": "x"})
    assert outcome == "unsupported"


async def test_sticker_and_voice_are_described(make_harness):
    h = make_harness()
    await h.connect()
    sticker = {
        "sticker": {
            "file_id": "s1", "file_unique_id": "u1", "type": "regular", "width": 512, "height": 512,
            "is_animated": False, "is_video": False, "emoji": "😀",
        }
    }
    voice = {"voice": {"file_id": "v1", "file_unique_id": "uv1", "duration": 3}}
    await h.business_message(None, extra=sticker)
    await h.business_message(None, extra=voice)
    texts = [i["text"] for i in h.assistant.history.get(CONN_ID, 555)]
    assert texts == ["[sticker] 😀", "[voice message]"]


# ---------------------------------------------------------- history & language


async def test_history_is_separate_per_connection_and_chat(make_harness):
    h = make_harness()
    await h.connect()
    await h.connect(conn_id="conn-2")
    await h.business_message("Secret A", from_id=11)
    await h.business_message("Secret B", from_id=22)
    await h.business_message("Secret C", from_id=11, connection_id="conn-2")
    await h.business_message("Second A", from_id=11)
    prompt = h.generator.calls[-1]["user"]
    assert "Secret A" in prompt and "Second A" in prompt
    assert "Secret B" not in prompt and "Secret C" not in prompt


async def test_language_hints(make_harness):
    h = make_harness()
    await h.connect()
    await h.business_message("Привет, как дела?", from_id=11)
    assert "Russian" in h.generator.calls[-1]["user"]
    await h.business_message("Hi, are you free tonight?", from_id=22)
    assert "English" in h.generator.calls[-1]["user"]
    await h.business_message("Bugun bo'shmisan?", from_id=33)
    assert "Uzbek" in h.generator.calls[-1]["user"]
    await h.business_message("👍", from_id=11)
    assert "Their latest message is in Russian." in h.generator.calls[-1]["user"]


async def test_skip_is_not_shown(make_harness):
    h = make_harness()
    h.generator.queue("[SKIP]", "")
    await h.connect()
    assert await h.business_message("ok") == "skipped"
    assert await h.business_message("👍") == "skipped"
    assert h.previews == []


# ---------------------------------------------------------------- auto-send


async def test_auto_send_rechecks_connection_then_sends(make_harness):
    h = make_harness(AUTO_SEND="true")
    h.generator.queue("Zo'r, rahmat!")
    await h.connect()
    assert await h.business_message("Salom") == "sent"
    kinds = [type(r) for r in h.session.requests]
    assert kinds == [GetBusinessConnection, SendMessage]
    sent = h.session.sent[0]
    assert sent.business_connection_id == CONN_ID and sent.chat_id == 555 and sent.text == "Zo'r, rahmat!"
    history = h.assistant.history.get(CONN_ID, 555)
    assert history[-1]["role"] == "owner" and history[-1]["text"] == "Zo'r, rahmat!"


async def test_auto_send_splits_long_replies(make_harness):
    h = make_harness(AUTO_SEND="true")
    h.generator.queue("a" * 9000)
    await h.connect()
    assert await h.business_message("Salom") == "sent"
    assert [len(m.text) for m in h.session.sent] == [4000, 4000, 1000]


async def test_auto_send_refuses_without_can_reply(make_harness):
    h = make_harness(AUTO_SEND="true")
    await h.connect()
    h.set_connection(can_reply=False)  # rights changed in Telegram, no update received
    assert await h.business_message("Salom") == "permission_denied"
    assert h.session.sent == []
    assert "permission" in h.previews[-1].note


async def test_auto_send_refuses_when_connection_disabled(make_harness):
    h = make_harness(AUTO_SEND="true")
    await h.connect()
    h.set_connection(enabled=False)
    assert await h.business_message("Salom") == "permission_denied"
    assert h.session.sent == []


async def test_auto_send_stops_if_owner_writes_during_generation(make_harness):
    h = make_harness(AUTO_SEND="true")
    await h.connect()

    async def owner_writes():
        h.generator.hook = None
        await h.business_message("Men o'zim javob beraman", from_id=OWNER_ID, chat_id=555)

    h.generator.hook = owner_writes
    await h.feed(h.business_update("Salom", from_id=555))
    assert "owner_active" in h.outcomes
    assert h.session.sent == []
    assert h.previews[-1].note and "you wrote" in h.previews[-1].note


# ------------------------------------------------------------ owner commands


async def test_pause_and_resume_owner_only_and_persistent(make_harness):
    h = make_harness()
    await h.connect()
    await h.direct_message("/pause", from_id=FOREIGN_ID)
    assert h.session.sent == []
    assert h.assistant.state.paused is False

    await h.direct_message("/pause")
    assert h.assistant.state.paused is True
    assert await h.business_message("Salom") == "paused"
    h.restart()
    await h.connect()
    assert await h.business_message("Salom") == "paused"

    await h.direct_message("/resume")
    assert await h.business_message("Salom") == "previewed"
    assert all(m.chat_id == OWNER_ID for m in h.session.sent)


async def test_strangers_plain_messages_get_nothing(make_harness):
    h = make_harness()
    await h.direct_message("hello?", from_id=FOREIGN_ID)
    await h.direct_message("/status", from_id=FOREIGN_ID)
    await h.direct_message("/resume", from_id=FOREIGN_ID)
    assert h.session.requests == []


async def test_status_for_owner(make_harness):
    h = make_harness()
    await h.direct_message("/status")
    assert "PREVIEW" in h.session.sent[-1].text


async def test_start_for_owner_is_uzbek_guide(make_harness):
    h = make_harness()
    await h.direct_message("/start")
    text = h.session.sent[-1].text
    assert "PREVIEW" in text and "ishlayapti" in text
    assert "Chatbots" in text and "/pause" in text and "/resume" in text and "/status" in text
    assert "AUTO_SEND=true" in text


async def test_start_shows_auto_send_and_paused(make_harness):
    h = make_harness(AUTO_SEND="true")
    h.assistant.pause()
    await h.direct_message("/start")
    text = h.session.sent[-1].text
    assert "AUTO-SEND" in text and "pauzada" in text
    assert "AUTO_SEND=true qiling" not in text


async def test_start_for_stranger_is_short_and_private(make_harness):
    h = make_harness()
    await h.direct_message("/start", from_id=FOREIGN_ID)
    assert len(h.session.sent) == 1
    text = h.session.sent[0].text
    assert h.session.sent[0].chat_id == FOREIGN_ID
    assert "egasi" in text
    assert "Aziz" not in text and "Toshkent" not in text and "Chatbots" not in text
    assert h.generator.calls == []


# ------------------------------------------------------------------- limits


async def test_limit_waits_until_reset_then_continues(make_harness):
    h = make_harness()
    reset = h.clock.now + 3600
    h.generator.queue(ClaudeLimitError("limit", resets_at=reset), "Hello again")
    await h.connect()
    assert await h.business_message("Salom") == "limited"
    assert await h.business_message("Salom?") == "limited"
    assert len(h.generator.calls) == 1
    h.restart()
    await h.connect()
    assert await h.business_message("Salom??") == "limited"
    h.clock.advance(3601)
    assert await h.business_message("Salom!!!") == "previewed"


async def test_limit_without_reset_uses_cooldown(make_harness):
    h = make_harness(LIMIT_COOLDOWN_MINUTES=30)
    h.generator.queue(ClaudeLimitError("limit"))
    await h.connect()
    await h.business_message("Salom")
    assert h.assistant.state.limit_until == pytest.approx(h.clock.now + 30 * 60)
    h.clock.advance(29 * 60)
    assert await h.business_message("Salom") == "limited"
    h.clock.advance(2 * 60)
    assert await h.business_message("Salom") == "previewed"


async def test_limit_notifies_owner_in_auto_send_and_resume_clears(make_harness):
    h = make_harness(AUTO_SEND="true")
    h.generator.queue(ClaudeLimitError("limit", resets_at=h.clock.now + 7200))
    await h.connect()
    assert await h.business_message("Salom") == "limited"
    owner_msgs = [m for m in h.session.sent if m.chat_id == OWNER_ID]
    assert len(owner_msgs) == 1 and "limit" in owner_msgs[0].text
    assert not [m for m in h.session.sent if m.chat_id == 555]
    await h.direct_message("/resume")
    assert h.assistant.state.limit_until is None
    assert await h.business_message("Salom") == "sent"


async def test_limit_preview_mode_does_not_message_owner(make_harness):
    h = make_harness()
    h.generator.queue(ClaudeLimitError("limit"))
    await h.connect()
    await h.business_message("Salom")
    assert h.session.sent == []


# ------------------------------------------------------------ claude errors


async def test_timeout_and_auth_errors_send_nothing_to_chat_and_alert_once(make_harness):
    h = make_harness(AUTO_SEND="true")
    h.generator.queue(ClaudeTimeout("timed out"), ClaudeAuthError("login rejected", "detail"))
    await h.connect()
    assert await h.business_message("Salom") == "error"
    assert await h.business_message("Salom?") == "error"
    assert not [m for m in h.session.sent if m.chat_id == 555]
    owner_msgs = [m for m in h.session.sent if m.chat_id == OWNER_ID]
    assert len(owner_msgs) == 1  # not repeated within 10 minutes


async def test_errors_in_preview_mode_send_nothing(make_harness):
    h = make_harness()
    h.generator.queue(ClaudeTimeout("timed out"))
    await h.connect()
    assert await h.business_message("Salom") == "error"
    assert h.session.sent == []
