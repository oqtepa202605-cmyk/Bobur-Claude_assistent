"""aiogram router: business updates go to the Assistant, owner commands in the bot chat."""
from __future__ import annotations

from typing import Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BusinessConnection, Message

from .service import Assistant

ALLOWED_UPDATES = ["message", "business_connection", "business_message"]

STRANGER_START_TEXT = (
    "Assalomu alaykum! Bu shaxsiy yordamchi bot, u faqat o'z egasi uchun ishlaydi. "
    "Bu yerda suhbatlashib bo'lmaydi — iltimos, egasiga to'g'ridan-to'g'ri yozing."
)


def build_router(assistant: Assistant, owner_id: Optional[int]) -> Router:
    router = Router(name="assistant")
    is_owner = (F.from_user.id == owner_id) & (F.chat.type == "private")

    @router.business_connection()
    async def on_business_connection(connection: BusinessConnection) -> None:
        assistant.on_business_connection(connection)

    @router.business_message()
    async def on_business_message(message: Message, bot: Bot) -> None:
        await assistant.on_business_message(bot, message)

    @router.message(CommandStart(), F.chat.type == "private")
    async def on_start(message: Message) -> None:
        if message.from_user is not None and message.from_user.id == owner_id:
            await message.answer(assistant.start_text())
        else:
            await message.answer(STRANGER_START_TEXT)

    @router.message(Command("pause"), is_owner)
    async def on_pause(message: Message) -> None:
        assistant.pause()
        await message.answer("⏸ Pauza. Hech kimga javob tayyorlanmaydi. Davom ettirish: /resume")

    @router.message(Command("resume"), is_owner)
    async def on_resume(message: Message) -> None:
        assistant.resume()
        await message.answer("▶️ Davom etyapman. Pauza, limit va kutish taymerlari tozalandi.")

    @router.message(Command("status"), is_owner)
    async def on_status(message: Message) -> None:
        await message.answer(assistant.status_text())

    @router.message()
    async def ignore_everything_else(message: Message) -> None:
        """Other direct messages to the bot are silently ignored."""
        return None

    return router
