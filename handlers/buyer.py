import logging
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, CommandObject
from aiogram.enums import ParseMode

from database.db import get_order_link_by_token, mark_order_link_accessed, get_first_active_proxy, update_account_status
from database.models import AccountStatus
from services.session_manager import (
    get_latest_login_code,
    listen_for_new_code,
    logout_session,
    terminate_other_sessions,
    get_session_file_path,
    disconnect_pooled_client
)
from utils.tdata_converter import export_session_to_tdata_zip
from keyboards.buyer_kb import (
    buyer_order_keyboard,
    buyer_back_keyboard,
    buyer_cancel_wait_keyboard,
    buyer_faq_menu_keyboard,
    buyer_faq_back_keyboard
)
from config import DEFAULT_BUYER_INSTRUCTION, CODE_WAIT_TIMEOUT, SESSIONS_DIR
from services.log_notifier import (
    log_buyer_order_access,
    log_code_retrieved,
    log_sessions_terminated
)

logger = logging.getLogger(__name__)
buyer_router = Router(name="buyer")

async def resolve_order_proxy_dict(acc) -> Optional[dict]:
    """Returns the Telethon proxy dictionary for the account or the seller's active default proxy."""
    if acc and acc.proxy and acc.proxy.is_active:
        return acc.proxy.to_telethon_dict()
    default_p = await get_first_active_proxy()
    if default_p:
        return default_p.to_telethon_dict()
    return None

def format_account_card(order) -> str:
    acc = order.account
    two_fa_block = f"\n\n🔐 <b>Облачный пароль (2FA):</b> <code>{acc.two_fa}</code>" if acc.two_fa else ""
    
    text = (
        "📩 <b>Отправьте код авторизации в Telegram на номер:</b>\n"
        f"<code>{acc.phone}</code>"
        f"{two_fa_block}\n\n"
        "<blockquote>После отправки кода нажмите «📩 Получить код» или «⏳ Ожидать код онлайн».\n"
        "После входа нажмите «🚪 Выйти ботом с аккаунта», чтобы на аккаунте осталось только ваше устройство.</blockquote>"
    )
    return text


@buyer_router.message(CommandStart(deep_link=True))
async def handle_buyer_deeplink(message: Message, command: CommandObject):
    """
    Handles deep links like /start order_abcdef123456
    """
    args = command.args or ""
    if not args.startswith("order_"):
        return # Will be caught by common router if not an order link

    token = args.replace("order_", "").strip()
    order = await get_order_link_by_token(token)

    if not order:
        await message.answer("❌ <b>Ссылка недействительна или срок ее действия истек.</b>")
        return

    if not order.is_active:
        await message.answer("⚠️ <b>Данная ссылка на выдачу была деактивирована администратором.</b>")
        return

    # Mark as accessed by buyer
    buyer_user = message.from_user
    await mark_order_link_accessed(
        token=token,
        buyer_tg_id=buyer_user.id if buyer_user else 0,
        buyer_username=buyer_user.username if buyer_user else None
    )

    if buyer_user and order.account:
        asyncio.create_task(log_buyer_order_access(
            message.bot,
            buyer_id=buyer_user.id,
            buyer_username=buyer_user.username,
            buyer_full_name=buyer_user.full_name,
            phone=order.account.phone,
            token=token
        ))

    card_text = format_account_card(order)
    await message.answer(
        card_text,
        reply_markup=buyer_order_keyboard(token),
        parse_mode=ParseMode.HTML
    )


@buyer_router.callback_query(F.data.startswith("buyer_refresh:"))
async def handle_buyer_refresh(callback: CallbackQuery):
    await callback.answer()
    token = callback.data.split(":")[1]
    order = await get_order_link_by_token(token)

    if not order:
        await callback.message.answer("⚠️ Ссылка не найдена.")
        return

    card_text = format_account_card(order)
    try:
        await callback.message.edit_text(
            card_text,
            reply_markup=buyer_order_keyboard(token),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


@buyer_router.callback_query(F.data.startswith("buyer_get_code:"))
async def handle_buyer_get_code(callback: CallbackQuery):
    token = callback.data.split(":")[1]
    order = await get_order_link_by_token(token)

    if not order or not order.account:
        await callback.answer("Ошибка: аккаунт не найден", show_alert=True)
        return

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = await resolve_order_proxy_dict(acc)

    await callback.answer("⏳ Проверяем сообщения от Telegram...")
    status_msg = await callback.message.answer("🔍 <i>Подключаемся к сессии и считываем код...</i>")

    code, details, raw_text = await get_latest_login_code(session_file, proxy=proxy_dict, max_age_seconds=1800)

    if code:
        reply_text = (
            f"✅ <b>Код подтверждения Telegram:</b>\n\n"
            f"🔑 <code>{code}</code> <i>(нажмите для копирования)</i>\n\n"
        )
        if details:
            reply_text += f"{details}\n\n"
        reply_text += "⚠️ <i>Если код не подходит, запросите новый в приложении Telegram и нажмите кнопку еще раз.</i>"
        
        await status_msg.edit_text(reply_text, reply_markup=buyer_back_keyboard(token), parse_mode=ParseMode.HTML)
        
        buyer_u = callback.from_user
        asyncio.create_task(log_code_retrieved(
            callback.bot,
            phone=acc.phone,
            code=code,
            user_id=buyer_u.id if buyer_u else 0,
            username=buyer_u.username if buyer_u else None,
            is_buyer=True
        ))
    else:
        err_hint = raw_text or "Код еще не поступил."
        reply_text = (
            f"ℹ️ <b>Код пока не получен.</b>\n\n"
            f"<i>{err_hint}</i>\n\n"
            "📌 <b>Убедитесь, что:</b>\n"
            f"1. Вы ввели номер <code>{acc.phone}</code> в Telegram и нажали «Далее» / «Отправить код».\n"
            "2. Telegram отправляет код в активную сессию (в приложение).\n\n"
            "👉 Нажмите <b>«⏳ Ожидать код онлайн»</b> — бот автоматически перехватит код, как только Telegram его отправит!"
        )
        await status_msg.edit_text(reply_text, reply_markup=buyer_order_keyboard(token), parse_mode=ParseMode.HTML)


@buyer_router.callback_query(F.data.startswith("buyer_wait_code:"))
async def handle_buyer_wait_code(callback: CallbackQuery):
    token = callback.data.split(":")[1]
    order = await get_order_link_by_token(token)

    if not order or not order.account:
        await callback.answer("Ошибка: аккаунт не найден", show_alert=True)
        return

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = await resolve_order_proxy_dict(acc)

    await callback.answer("Режим ожидания кода запущен")
    
    wait_msg = await callback.message.answer(
        f"⏳ <b>Ожидание кода в реальном времени...</b>\n\n"
        f"📱 Номер: <code>{acc.phone}</code>\n"
        f"⏱ Время ожидания: {CODE_WAIT_TIMEOUT} секунд.\n\n"
        "👉 <b>Отправьте запрос на вход в Telegram прямо сейчас.</b> Как только код придет, бот мгновенно отобразит его здесь.",
        reply_markup=buyer_cancel_wait_keyboard(token),
        parse_mode=ParseMode.HTML
    )

    code, details, text = await listen_for_new_code(session_file, proxy=proxy_dict, timeout=CODE_WAIT_TIMEOUT)

    if code:
        reply_text = (
            f"🎉 <b>Код успешно получен!</b>\n\n"
            f"🔑 Код: <code>{code}</code> <i>(нажмите для копирования)</i>\n\n"
        )
        if details:
            reply_text += f"{details}\n\n"
        reply_text += "Вставьте данный код в ваше приложение Telegram."
        await wait_msg.edit_text(reply_text, reply_markup=buyer_back_keyboard(token), parse_mode=ParseMode.HTML)
        
        buyer_u = callback.from_user
        asyncio.create_task(log_code_retrieved(
            callback.bot,
            phone=acc.phone,
            code=code,
            user_id=buyer_u.id if buyer_u else 0,
            username=buyer_u.username if buyer_u else None,
            is_buyer=True
        ))
    else:
        err = text or "Таймаут ожидания."
        await wait_msg.edit_text(
            f"⚠️ <b>{err}</b>\n\n"
            "Попробуйте запросить код в Telegram заново и нажать <b>«📩 Получить код»</b>.",
            reply_markup=buyer_order_keyboard(token),
            parse_mode=ParseMode.HTML
        )


@buyer_router.callback_query(F.data.startswith("buyer_logout_bot:"))
async def handle_buyer_logout_bot(callback: CallbackQuery):
    token = callback.data.split(":")[1]
    order = await get_order_link_by_token(token)

    if not order or not order.account:
        await callback.answer("Ошибка: аккаунт не найден", show_alert=True)
        return

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = await resolve_order_proxy_dict(acc)

    await callback.answer("🚪 Завершаем сессию бота на аккаунте...")
    status_msg = await callback.message.answer("⏳ <i>Выходим из аккаунта и удаляем сессию бота...</i>")

    ok, msg = await logout_session(session_file, proxy=proxy_dict)
    await update_account_status(acc.id, AccountStatus.ISSUED)

    buyer_u = callback.from_user
    asyncio.create_task(log_sessions_terminated(
        callback.bot,
        phone=acc.phone,
        user_id=buyer_u.id if buyer_u else 0,
        username=buyer_u.username if buyer_u else None,
        is_buyer=True
    ))

    success_text = (
        "🎉 <b>Бот успешно вышел из аккаунта!</b>\n\n"
        f"📱 Номер: <code>{acc.phone}</code>\n"
        "✅ Сессия бота в Telegram полностью завершена (Logged Out).\n"
        "🔒 <b>Теперь на аккаунте активна только ваша сессия (ваше устройство).</b>\n"
        "Вам не нужно ждать КД в Telegram для сброса других устройств.\n\n"
        "<i>Приятного пользования!</i>"
    )
    await status_msg.edit_text(success_text, reply_markup=buyer_back_keyboard(token), parse_mode=ParseMode.HTML)


@buyer_router.callback_query(F.data.startswith("buyer_term_sessions:"))
async def handle_buyer_terminate_sessions(callback: CallbackQuery):
    token = callback.data.split(":")[1]
    order = await get_order_link_by_token(token)

    if not order or not order.account:
        await callback.answer("Ошибка: аккаунт не найден", show_alert=True)
        return

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = await resolve_order_proxy_dict(acc)

    await callback.answer("Выполняется сброс сессий...")
    success, msg = await terminate_other_sessions(session_file, proxy=proxy_dict)
    
    buyer_u = callback.from_user
    asyncio.create_task(log_sessions_terminated(
        callback.bot,
        phone=acc.phone,
        user_id=buyer_u.id if buyer_u else 0,
        username=buyer_u.username if buyer_u else None,
        is_buyer=True
    ))

    await callback.message.answer(
        msg,
        reply_markup=buyer_back_keyboard(token),
        parse_mode=ParseMode.HTML
    )


@buyer_router.callback_query(F.data.startswith("buyer_help:"))
async def handle_buyer_help(callback: CallbackQuery):
    token = callback.data.split(":")[1]
    await callback.answer()

    faq_main_text = (
        "📚 <b>База знаний и Инструкции (FAQ)</b>\n\n"
        "Выберите интересующий вас раздел, чтобы прочитать подробную инструкцию:\n\n"
        "📱 <b>Вход по коду и номеру</b> — пошаговый вход на телефоне или ПК\n"
        "📁 <b>Вход через Tdata (ПК)</b> — мгновенный вход в Telegram Desktop\n"
        "🌐 <b>Настройка Прокси (Proxy)</b> — защита от блокировок и смена IP\n"
        "🚪 <b>Завершение сессии бота</b> — как сделать сессию только своей без КД\n"
        "📄 <b>Использование .session</b> — для разработчиков и программ"
    )
    try:
        await callback.message.edit_text(
            faq_main_text,
            reply_markup=buyer_faq_menu_keyboard(token),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await callback.message.answer(
            faq_main_text,
            reply_markup=buyer_faq_menu_keyboard(token),
            parse_mode=ParseMode.HTML
        )


@buyer_router.callback_query(F.data.startswith("buyer_faq:"))
async def handle_buyer_faq_topic(callback: CallbackQuery):
    await callback.answer()
    parts = callback.data.split(":")
    topic = parts[1] if len(parts) > 1 else "login"
    token = parts[2] if len(parts) > 2 else ""

    if topic == "login":
        text = (
            "📱 <b>Инструкция: Вход по коду и номеру</b>\n\n"
            "1. <b>Откройте официальное приложение Telegram</b> (на телефоне или компьютере).\n"
            "2. Выберите <b>«Вход по номеру телефона»</b> и введите номер из карточки аккаунта.\n"
            "3. Нажмите <b>«Далее»</b> / <b>«Отправить код»</b>.\n"
            "4. Вернитесь в этого бота и нажмите:\n"
            "   • <b>«📩 Получить код»</b> — бот моментально проверит сообщения от Telegram и выдаст код.\n"
            "   • <b>«⏳ Ожидать код онлайн»</b> — бот будет ожидать код в реальном времени и сразу пришлет его.\n"
            "5. Введите полученный 5-значный код в приложении Telegram.\n"
            "6. Если на аккаунте есть <b>Облачный пароль (2FA)</b> — скопируйте его из карточки и введите.\n"
            "7. <b>После успешного входа:</b> обязательно нажмите в боте кнопку <b>«🚪 Выйти ботом с аккаунта»</b>, чтобы на аккаунте осталось только ваше устройство!"
        )
    elif topic == "tdata":
        text = (
            "📁 <b>Инструкция: Вход через Tdata (Telegram Desktop на ПК)</b>\n\n"
            "<i>Формат Tdata позволяет войти в Telegram Desktop сразу без ввода номера телефона и кодов!</i>\n\n"
            "<b>Пошаговые действия:</b>\n"
            "1. Нажмите в карточке аккаунта кнопку <b>«📁 Скачать Tdata (ZIP)»</b>.\n"
            "2. Скачайте официальную Portable-версию Telegram с сайта <code>desktop.telegram.org</code> (архив с <code>Telegram.exe</code>).\n"
            "3. Распакуйте скачанный ZIP архив от бота — внутри будет папка <code>tdata</code>.\n"
            "4. Поместите папку <code>tdata</code> в папку с файлом <code>Telegram.exe</code> (заменив существующую папку <code>tdata</code>, если она была).\n"
            "5. Запустите <code>Telegram.exe</code> — вы сразу окажетесь внутри авторизованного профиля!"
        )
    elif topic == "proxy":
        text = (
            "🌐 <b>Инструкция: Настройка и использование Прокси (Proxy)</b>\n\n"
            "<b>Зачем нужен прокси?</b>\n"
            "Telegram может заморозить аккаунт (SpamBlock / Freeze), если вход осуществляется с IP-адреса другой страны. Использование качественного прокси под гео аккаунта обеспечивает максимальную безопасность и надежность.\n\n"
            "<b>Как настроить прокси в Telegram:</b>\n"
            "1. <b>На ПК (Desktop):</b> Настройки ➔ Продвинутые настройки ➔ Тип подключения ➔ Добавить прокси (SOCKS5 / MTProto).\n"
            "2. <b>На Телефоне:</b> Настройки ➔ Данные и память ➔ Прокси ➔ Добавить прокси.\n"
            "3. Введите <code>Хост</code>, <code>Порт</code>, <code>Логин</code> и <code>Пароль</code>.\n"
            "4. Включите <b>«Использовать прокси»</b> (вверху появится синий щит ✅).\n"
            "5. После подключения прокси выполняйте вход в аккаунт."
        )
    elif topic == "security":
        text = (
            "🚪 <b>Инструкция: Безопасность и завершение сессии бота</b>\n\n"
            "<b>Почему это важно?</b>\n"
            "В Telegram на новых сессиях действует защита (КД 24 часа), запрещающая новому устройству сразу завершать старые сессии.\n\n"
            "<b>Как сделать аккаунт на 100% личным:</b>\n"
            "1. После входа в аккаунт нажмите кнопку <b>«🚪 Выйти ботом с аккаунта»</b>.\n"
            "2. Бот сам выполнит выход (Log Out) и навсегда удалит файл сессии с сервера.\n"
            "3. <b>Результат:</b> На аккаунте останется <b>только ваше личное устройство</b> (без ожидания КД 24 часа).\n"
            "4. В Telegram перейдите в <i>Настройки ➔ Конфиденциальность ➔ Облачный пароль (2FA)</i> и установите свой собственный пароль."
        )
    elif topic == "session":
        text = (
            "📄 <b>Инструкция: Использование файла .session</b>\n\n"
            "<i>Формат .session предназначен для скриптов, ботов и программ автоматизации.</i>\n\n"
            "<b>Как использовать:</b>\n"
            "1. Нажмите в боте кнопку <b>«📄 Скачать .session»</b>.\n"
            "2. Файл сессии является стандартной базой данных Telethon (SQLite).\n"
            "3. <b>Пример на Python (Telethon):</b>\n"
            "<code>from telethon import TelegramClient\n"
            "client = TelegramClient('phone', api_id, api_hash)\n"
            "await client.connect()</code>\n"
            "4. Всегда подключайтесь через прокси страны аккаунта для стабильной работы."
        )
    else:
        text = DEFAULT_BUYER_INSTRUCTION

    try:
        await callback.message.edit_text(
            text,
            reply_markup=buyer_faq_back_keyboard(token),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=buyer_faq_back_keyboard(token),
            parse_mode=ParseMode.HTML
        )


@buyer_router.callback_query(F.data.startswith("buyer_download_tdata:"))
async def handle_buyer_download_tdata(callback: CallbackQuery):
    await callback.answer()
    token = callback.data.split(":")[1]
    order = await get_order_link_by_token(token)
    if not order or not order.account:
        await callback.message.answer("⚠️ Аккаунт не найден или ссылка недействительна.")
        return

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    if not session_file.exists():
        await callback.message.answer("❌ Файл сессии не найден.")
        return

    wait_msg = await callback.message.answer("⏳ Подготавливаем Tdata архив...")
    clean_phone = acc.phone.replace("+", "").strip()
    zip_path = SESSIONS_DIR / f"tdata_{clean_phone}.zip"

    # Disconnect any open sockets in the bot so Telegram Desktop has exclusive connection
    await disconnect_pooled_client(session_file)

    ok, err = export_session_to_tdata_zip(session_file, zip_path, user_id=acc.tg_user_id or 0)
    if not ok or not zip_path.exists():
        await wait_msg.edit_text(f"❌ Ошибка формирования Tdata: {err}")
        return

    doc_file = FSInputFile(str(zip_path), filename=f"tdata_{clean_phone}.zip")
    await callback.message.answer_document(
        doc_file,
        caption=(
            f"📁 <b>Tdata архив для {acc.phone}</b>\n\n"
            f"<b>Инструкция по входу:</b>\n"
            f"1. Распакуйте скачанный ZIP архив\n"
            f"2. Поместите папку <code>tdata</code> в папку с <code>Telegram.exe</code>\n"
            f"3. Запустите Telegram — вы сразу окажетесь внутри аккаунта!"
        ),
        parse_mode=ParseMode.HTML
    )
    try:
        await wait_msg.delete()
    except Exception:
        pass


@buyer_router.callback_query(F.data.startswith("buyer_download_session:"))
async def handle_buyer_download_session(callback: CallbackQuery):
    await callback.answer()
    token = callback.data.split(":")[1]
    order = await get_order_link_by_token(token)
    if not order or not order.account:
        await callback.message.answer("⚠️ Аккаунт не найден или ссылка недействительна.")
        return

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    if not session_file.exists():
        await callback.message.answer("❌ Файл сессии не найден.")
        return

    clean_phone = acc.phone.replace("+", "").strip()
    doc_file = FSInputFile(str(session_file), filename=f"{clean_phone}.session")
    await callback.message.answer_document(
        doc_file,
        caption=f"📄 <b>Telethon .session файл для аккаунта:</b> <code>{acc.phone}</code>",
        parse_mode=ParseMode.HTML
    )
