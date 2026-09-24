import asyncio
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from config import ADMIN_IDS
from database.db import register_or_update_bot_user
from services.log_notifier import log_new_user

common_router = Router(name="common")

@common_router.message(CommandStart())
async def handle_start_common(message: Message):
    u = message.from_user
    user_id = u.id if u else 0
    username = u.username if u else None
    full_name = u.full_name if u else None

    if user_id:
        _, is_new = await register_or_update_bot_user(user_id, username, full_name)
        if is_new:
            asyncio.create_task(log_new_user(message.bot, user_id, username, full_name))

    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.answer(
            "👋 <b>Добро пожаловать в сервис автовыдачи аккаунтов!</b>\n\n"
            "Для получения купленного аккаунта перейдите по ссылке, которую вы получили в магазине.",
            parse_mode=ParseMode.HTML
        )

@common_router.message(Command("help"))
async def handle_help_common(message: Message):
    await message.answer(
        "ℹ️ <b>Справка по боту:</b>\n\n"
        "• Для покупателей: доступ к аккаунту осуществляется по индивидуальной ссылке из магазина.\n"
        "• Для продавцов: управление аккаунтами доступно администраторам по команде /admin.",
        parse_mode=ParseMode.HTML
    )
