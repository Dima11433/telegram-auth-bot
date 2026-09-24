import logging
import datetime
from typing import Optional
from aiogram import Bot
from aiogram.enums import ParseMode
from config import LOG_CHANNEL_ID

logger = logging.getLogger("log_notifier")

def _format_user_mention(user_id: int, username: Optional[str] = None, full_name: Optional[str] = None) -> str:
    display_name = full_name or username or f"ID:{user_id}"
    user_link = f"<a href='tg://user?id={user_id}'>{display_name}</a>"
    tag = f" (@{username})" if username else ""
    return f"{user_link}{tag} [<code>{user_id}</code>]"

def _now_str() -> str:
    return datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

async def send_log_message(bot: Bot, text: str):
    if not LOG_CHANNEL_ID:
        return
    try:
        await bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить лог в канал {LOG_CHANNEL_ID}: {e}")

async def log_new_user(
    bot: Bot,
    user_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
    start_payload: Optional[str] = None
):
    user_str = _format_user_mention(user_id, username, full_name)
    payload_str = f"\n🔗 <b>Параметр старта:</b> <code>{start_payload}</code>" if start_payload else ""
    text = (
        f"🚀 <b>НОВЫЙ ПОЛЬЗОВАТЕЛЬ</b>\n\n"
        f"👤 <b>Пользователь:</b> {user_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>{payload_str}"
    )
    await send_log_message(bot, text)

async def log_buyer_order_access(
    bot: Bot,
    buyer_id: int,
    buyer_username: Optional[str],
    buyer_full_name: Optional[str],
    phone: str,
    token: str
):
    user_str = _format_user_mention(buyer_id, buyer_username, buyer_full_name)
    text = (
        f"🛒 <b>ВХОД ПО ССЫЛКЕ АВТОРИЗАЦИИ (ПОКУПАТЕЛЬ)</b>\n\n"
        f"👤 <b>Покупатель:</b> {user_str}\n"
        f"📱 <b>Номер аккаунта:</b> <code>{phone}</code>\n"
        f"🔑 <b>Токен заказа:</b> <code>{token}</code>\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)

async def log_account_added(
    bot: Bot,
    phone: str,
    method: str,
    owner_id: Optional[int],
    owner_username: Optional[str] = None,
    first_name: Optional[str] = None,
    country: Optional[str] = None
):
    owner_str = _format_user_mention(owner_id, owner_username) if owner_id else "<i>Администратор / Система</i>"
    geo_str = f"\n🌍 <b>Страна:</b> {country}" if country else ""
    name_str = f"\n👤 <b>Имя в Telegram:</b> {first_name}" if first_name else ""
    text = (
        f"📥 <b>ЗАГРУЖЕН НОВЫЙ АККАУНТ</b>\n\n"
        f"📱 <b>Номер:</b> <code>{phone}</code>{geo_str}{name_str}\n"
        f"⚙️ <b>Способ добавления:</b> <code>{method}</code>\n"
        f"👑 <b>Загрузил:</b> {owner_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)

async def log_code_retrieved(
    bot: Bot,
    phone: str,
    code: str,
    user_id: int,
    username: Optional[str] = None,
    is_buyer: bool = False
):
    role = "🛒 Покупатель" if is_buyer else "💼 Продавец / Владелец"
    user_str = _format_user_mention(user_id, username)
    text = (
        f"🔑 <b>ВЫДАН КОД АВТОРИЗАЦИИ TELEGRAM</b>\n\n"
        f"📱 <b>Номер:</b> <code>{phone}</code>\n"
        f"🔢 <b>Код:</b> <code>{code}</code>\n"
        f"👤 <b>Получатель ({role}):</b> {user_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)

async def log_sessions_terminated(
    bot: Bot,
    phone: str,
    user_id: int,
    username: Optional[str] = None,
    is_buyer: bool = False
):
    role = "🛒 Покупатель" if is_buyer else "💼 Продавец / Владелец"
    user_str = _format_user_mention(user_id, username)
    text = (
        f"🛡 <b>СБРОС СТОРОННИХ СЕССИЙ</b>\n\n"
        f"📱 <b>Номер:</b> <code>{phone}</code>\n"
        f"👤 <b>Инициатор ({role}):</b> {user_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)

async def log_2fa_changed(
    bot: Bot,
    phone: str,
    user_id: int,
    username: Optional[str] = None
):
    user_str = _format_user_mention(user_id, username)
    text = (
        f"🔐 <b>ИЗМЕНЕН ОБЛАЧНЫЙ ПАРОЛЬ (2FA)</b>\n\n"
        f"📱 <b>Номер:</b> <code>{phone}</code>\n"
        f"👤 <b>Пользователь:</b> {user_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)

async def log_email_changed(
    bot: Bot,
    phone: str,
    email: Optional[str],
    user_id: int,
    username: Optional[str] = None,
    action: str = "bind"
):
    user_str = _format_user_mention(user_id, username)
    action_text = f"Привязан новый Email: <code>{email}</code>" if action == "bind" else "Email успешно отвязан"
    text = (
        f"📧 <b>ИЗМЕНЕНИЕ ПОЧТЫ (EMAIL)</b>\n\n"
        f"📱 <b>Номер:</b> <code>{phone}</code>\n"
        f"✉️ <b>Действие:</b> {action_text}\n"
        f"👤 <b>Пользователь:</b> {user_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)

async def log_account_deleted(
    bot: Bot,
    phone: str,
    user_id: int,
    username: Optional[str] = None
):
    user_str = _format_user_mention(user_id, username)
    text = (
        f"🗑 <b>УДАЛЕНИЕ АККАУНТА ИЗ БАЗЫ</b>\n\n"
        f"📱 <b>Номер:</b> <code>{phone}</code>\n"
        f"👤 <b>Инициатор:</b> {user_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)

async def log_proxy_added(
    bot: Bot,
    proxy_url: str,
    is_active: bool,
    phone: Optional[str] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None
):
    user_str = _format_user_mention(user_id, username) if user_id else "<i>Администратор</i>"
    status_icon = "✅ Работает" if is_active else "⚠️ Ошибка подключения"
    phone_str = f"\n📱 <b>Аккаунт:</b> <code>{phone}</code>" if phone else ""
    text = (
        f"🌐 <b>ДОБАВЛЕН ПРОКСИ</b>\n\n"
        f"🔗 <b>Прокси:</b> <code>{proxy_url}</code>{phone_str}\n"
        f"📊 <b>Статус проверки:</b> {status_icon}\n"
        f"👤 <b>Добавил:</b> {user_str}\n"
        f"⏱ <b>Время:</b> <code>{_now_str()}</code>"
    )
    await send_log_message(bot, text)
