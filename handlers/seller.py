import os
import io
import time
import asyncio
import zipfile
import logging
from pathlib import Path
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, FSInputFile
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from config import SESSIONS_DIR, ADMIN_IDS, WEB_BASE_URL
from utils.tdata_converter import (
    convert_tdata_zip_to_session_file,
    export_session_to_tdata_zip,
    create_telethon_session_file
)
from telethon.sessions import StringSession
from database.models import AccountStatus, Account, Proxy
from database.db import (
    get_accounts_list,
    get_all_accounts,
    get_account_by_id,
    add_or_update_account,
    update_account_status,
    update_account_info,
    delete_account_by_id,
    create_order_link,
    get_existing_active_link_for_account,
    get_all_proxies,
    add_proxy,
    delete_proxy,
    get_first_active_proxy,
    get_proxy_by_id,
    set_active_proxy,
    update_proxy_status,
    register_or_update_bot_user,
    get_bot_user_by_tg_id
)
from services.session_manager import (
    validate_session,
    get_session_file_path,
    get_latest_login_code,
    create_telethon_client,
    get_account_auth_key,
    update_profile_info,
    update_profile_username,
    update_profile_2fa,
    get_active_authorizations,
    terminate_other_sessions,
    generate_qr_png_bytes,
    start_qr_login,
    wait_qr_login_result,
    complete_qr_2fa_login,
    get_account_dialogs,
    get_saved_messages_id,
    search_account_dialogs,
    get_chat_paged_messages,
    download_message_photo_bytes,
    click_bot_message_button,
    send_message_as_account,
    leave_chat_as_account,
    join_chat_as_account,
    get_account_email_info,
    request_set_account_email,
    confirm_account_email_code,
    remove_account_email
)
from services.proxy_manager import parse_proxy_string, test_proxy_connection
from services.log_notifier import (
    log_new_user,
    log_account_added,
    log_code_retrieved,
    log_sessions_terminated,
    log_2fa_changed,
    log_email_changed,
    log_account_deleted,
    log_proxy_added
)
from keyboards.seller_kb import (
    seller_dashboard_keyboard,
    upload_format_keyboard,
    account_action_keyboard,
    invalid_account_keyboard,
    account_management_keyboard,
    devices_management_keyboard,
    account_dialogs_keyboard,
    chat_actions_keyboard,
    cancel_to_chat_keyboard,
    cancel_to_dialogs_keyboard,
    cancel_to_seller_keyboard,
    proxy_menu_keyboard
)

logger = logging.getLogger(__name__)
seller_router = Router(name="seller")

# FSM States
class SellerUploadSessionState(StatesGroup):
    waiting_for_document = State()
    waiting_for_2fa = State()

class SellerUploadZipState(StatesGroup):
    waiting_for_zip = State()

class SellerUploadTDataState(StatesGroup):
    waiting_for_tdata_zip = State()

class SellerUploadStringSessionState(StatesGroup):
    waiting_for_string = State()
    waiting_for_2fa = State()

class SellerUploadQRState(StatesGroup):
    waiting_for_scan = State()
    waiting_for_2fa = State()

class SellerPhoneLoginState(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class SellerProxyAddState(StatesGroup):
    waiting_for_proxy_string = State()

class SellerReplaceSessionState(StatesGroup):
    waiting_for_document = State()

class SellerEditFirstNameState(StatesGroup):
    waiting_for_name = State()

class SellerEditLastNameState(StatesGroup):
    waiting_for_name = State()

class SellerEdit2FAState(StatesGroup):
    waiting_for_password = State()

class SellerEditEmailState(StatesGroup):
    waiting_for_email = State()
    waiting_for_code = State()

class SellerEditUsernameState(StatesGroup):
    waiting_for_username = State()

class SellerEditBioState(StatesGroup):
    waiting_for_bio = State()

class SellerSendChatMessageState(StatesGroup):
    waiting_for_text = State()

class SellerJoinChatState(StatesGroup):
    waiting_for_link = State()

class SellerSearchChatState(StatesGroup):
    waiting_for_query = State()

class SellerAccountSetProxyState(StatesGroup):
    waiting_for_proxy = State()


from utils.country_detector import group_accounts_by_country, get_country_info


async def get_user_display_header(user_id: int) -> str:
    """Returns the user's nickname/full_name or username for personalized dashboard header."""
    user = await get_bot_user_by_tg_id(user_id)
    if user:
        if user.full_name:
            return user.full_name
        if user.username:
            return f"@{user.username}"
    return f"Пользователь {user_id}"


async def build_seller_dashboard_view(user_id: int, bot: Bot, country_code: Optional[str] = None, page: int = 1, limit: int = 6):
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    user_accs = await get_all_accounts(owner_tg_id=user_id, include_unassigned=is_admin)
    total_count = len(user_accs)
    active_count = sum(1 for a in user_accs if a.status == AccountStatus.ACTIVE)
    issued_count = sum(1 for a in user_accs if a.status == AccountStatus.ISSUED)
    invalid_count = sum(1 for a in user_accs if a.status in (AccountStatus.INVALID, AccountStatus.BANNED, AccountStatus.ERROR))

    user_header = await get_user_display_header(user_id)
    country_groups = group_accounts_by_country(user_accs)
    builder = InlineKeyboardBuilder()

    if country_code is None:
        text = (
            f"💼 <b>{user_header}</b>\n\n"
            "📊 <b>Список моих аккаунтов:</b>\n"
            f"• Всего аккаунтов: <code>{total_count}</code>\n"
            f"• Доступно: <code>{active_count}</code> | Выдано: <code>{issued_count}</code>\n"
            f"• Невалид / Бан: <code>{invalid_count}</code>\n\n"
        )

        if not user_accs:
            text += "<i>У вас еще нет загруженных аккаунтов. Нажмите «➕ Залить аккаунты».</i>"
        else:
            text += "📁 <b>Выберите категорию (страну) аккаунтов:</b>"
            for c_code, grp in country_groups.items():
                info = grp["info"]
                cnt = len(grp["accounts"])
                btn_text = f"{info['flag']} {info['name']} ({info['prefix']}) — {cnt} шт."
                builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"seller_country:{c_code}:1"))

            if len(country_groups) > 1:
                builder.row(InlineKeyboardButton(text=f"📋 Все страны ({total_count} шт.)", callback_data="seller_country:ALL:1"))

        # Control buttons
        builder.row(InlineKeyboardButton(text="🔄 Проверить валидность", callback_data="seller_check_validity"))
        builder.row(InlineKeyboardButton(text="➕ Залить аккаунты", callback_data="seller_upload_menu"))
        builder.row(InlineKeyboardButton(text="📦 Выгрузить ссылки", callback_data="seller_export_links"))
        builder.row(InlineKeyboardButton(text="🌐 Настройка прокси", callback_data="seller_proxy_menu"))

        if is_admin:
            builder.row(InlineKeyboardButton(text="👑 Панель Администратора", callback_data="admin_global_menu"))

        return text, builder.as_markup()

    else:
        # Filtered view by country
        if country_code == "ALL":
            target_accs = user_accs
            country_title = f"📋 <b>Все аккаунты ({len(target_accs)} шт.):</b>"
        else:
            grp = country_groups.get(country_code)
            target_accs = grp["accounts"] if grp else []
            info = grp["info"] if grp else get_country_info(country_code)
            country_title = f"{info['flag']} <b>Категория: {info['name']} ({info['prefix']}) — {len(target_accs)} шт.</b>"

        total_pages = max(1, (len(target_accs) + limit - 1) // limit)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * limit
        paged_accs = target_accs[offset : offset + limit]

        text = (
            f"💼 <b>{user_header}</b>\n\n"
            f"{country_title}\n\n"
        )

        if not paged_accs:
            text += "<i>В этой категории нет аккаунтов.</i>"
        else:
            text += "<i>Выберите аккаунт для управления:</i>"

        for acc in paged_accs:
            status_icon = "🟢" if acc.status == AccountStatus.ACTIVE else ("🔵" if acc.status == AccountStatus.ISSUED else "🔴")
            btn_text = f"{status_icon} {acc.phone} ({acc.full_name()[:15]})"
            builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"acc_view:{acc.id}"))

        # Pagination row
        if total_pages > 1:
            prev_p = max(1, page - 1)
            next_p = min(total_pages, page + 1)
            builder.row(
                InlineKeyboardButton(text="⏮", callback_data=f"seller_country:{country_code}:1"),
                InlineKeyboardButton(text="◀️", callback_data=f"seller_country:{country_code}:{prev_p}"),
                InlineKeyboardButton(text=f"{page} из {total_pages}", callback_data="seller_page_noop"),
                InlineKeyboardButton(text="▶️", callback_data=f"seller_country:{country_code}:{next_p}"),
                InlineKeyboardButton(text="⏭", callback_data=f"seller_country:{country_code}:{total_pages}"),
            )

        builder.row(InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="seller_main_menu"))
        builder.row(InlineKeyboardButton(text="➕ Залить аккаунты", callback_data="seller_upload_menu"))

        return text, builder.as_markup()


_CACHED_BOT_USERNAME: Optional[str] = None

async def get_cached_bot_username(bot: Bot) -> str:
    global _CACHED_BOT_USERNAME
    if not _CACHED_BOT_USERNAME:
        try:
            me = await bot.get_me()
            _CACHED_BOT_USERNAME = me.username or ""
        except Exception:
            _CACHED_BOT_USERNAME = "bot"
    return _CACHED_BOT_USERNAME


async def format_account_seller_card(acc: Account, bot: Bot):
    bot_username = await get_cached_bot_username(bot)
    order = await get_existing_active_link_for_account(acc.id)
    if not order:
        order = await create_order_link(acc.id)

    auth_link = f"https://t.me/{bot_username}?start=order_{order.token}"
    web_link = f"{WEB_BASE_URL}/web?token={order.token}"
    first_name = acc.first_name or "Отсутствует"
    last_name = acc.last_name or "Отсутствует"
    two_fa = f"<code>{acc.two_fa}</code>" if acc.two_fa else "Отсутствует"
    email_val = f"<code>{acc.email}</code>" if acc.email else "Не привязана"
    created_date = acc.created_at.strftime("%d.%m.%y") if acc.created_at else "—"

    status_warning = ""
    if acc.status in (AccountStatus.INVALID, AccountStatus.ERROR):
        status_warning = "⚠️ <b>Внимание: Сессия слетела (невалидна)!</b>\n<i>Замените .session файл кнопкой ниже.</i>\n\n"
    elif acc.status == AccountStatus.BANNED:
        status_warning = "🚫 <b>Внимание: Аккаунт заблокирован в Telegram!</b>\n\n"

    text = (
        "📴 <b>Меню аккаунта:</b>\n\n"
        f"{status_warning}"
        f"<b>Номер:</b> <code>{acc.phone}</code>\n"
        f"<b>Имя:</b> {first_name}\n"
        f"<b>Фамилия:</b> {last_name}\n"
        f"<b>Облачный пароль:</b> {two_fa}\n"
        f"<b>Email (Почта):</b> {email_val}\n"
        f"<b>Дата добавления:</b> {created_date}\n\n"
        "🔗 <b>Ссылка для выдачи покупателю (Telegram):</b>\n"
        f"<code>{auth_link}</code>"
    )
    return text, auth_link, web_link


# --- Entrypoint for all users ---

@seller_router.message(CommandStart())
async def cmd_seller_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    u = message.from_user
    user_id = u.id if u else 0
    username = u.username if u else None
    full_name = u.full_name if u else None

    if user_id:
        _, is_new = await register_or_update_bot_user(user_id, username, full_name)
        if is_new:
            asyncio.create_task(log_new_user(bot, user_id, username, full_name))

    text, kb = await build_seller_dashboard_view(user_id, bot, country_code=None, page=1)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data == "seller_main_menu")
async def cb_seller_main_menu(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.clear()
    user_id = callback.from_user.id if callback.from_user else 0
    text, kb = await build_seller_dashboard_view(user_id, bot, country_code=None, page=1)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("seller_country:"))
async def cb_seller_country(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    parts = callback.data.split(":")
    country_code = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 1
    user_id = callback.from_user.id if callback.from_user else 0
    text, kb = await build_seller_dashboard_view(user_id, bot, country_code=country_code, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass


@seller_router.callback_query(F.data.startswith("seller_page:"))
async def cb_seller_page(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else 0
    page = int(callback.data.split(":")[1])
    text, kb = await build_seller_dashboard_view(user_id, bot, country_code=None, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass


@seller_router.callback_query(F.data == "seller_page_noop")
async def cb_seller_page_noop(callback: CallbackQuery):
    await callback.answer()


# --- Account View (Screenshot 1) ---

@seller_router.callback_query(F.data.startswith("acc_view:"))
async def cb_acc_view(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    
    # Check permissions: user can view their own account or if admin
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.message.answer("⚠️ Аккаунт не найден.")
        return

    text, auth_link, web_link = await format_account_seller_card(acc, bot)
    back_cb = "admin_global_menu" if (is_admin and acc.owner_tg_id != user_id) else "seller_main_menu"
    if acc.status in (AccountStatus.INVALID, AccountStatus.BANNED, AccountStatus.ERROR):
        kb = invalid_account_keyboard(acc.id, back_callback=back_cb)
    else:
        kb = account_action_keyboard(acc.id, share_url=auth_link, web_url=web_link, back_callback=back_cb)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error editing message for acc_view {acc_id}: {e}")
        await callback.message.answer(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )


@seller_router.callback_query(F.data.startswith("acc_web_client:"))
async def cb_acc_web_client(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.message.answer("⚠️ Аккаунт не найден.")
        return

    order = await get_existing_active_link_for_account(acc.id)
    if not order:
        order = await create_order_link(acc.id)

    web_url = f"{WEB_BASE_URL}/web?token={order.token}"
    builder = InlineKeyboardBuilder()
    if web_url.startswith("https://") or web_url.startswith("tg://"):
        builder.row(InlineKeyboardButton(text="🌐 Открыть Web-клиент", url=web_url))
    builder.row(InlineKeyboardButton(text="🔙 Назад к аккаунту", callback_data=f"acc_view:{acc_id}"))

    await callback.message.answer(
        f"🌐 <b>Прямая ссылка на Web-клиент для {acc.phone}:</b>\n\n"
        f"<code>{web_url}</code>\n\n"
        "👉 Скопируйте ссылку и откройте в браузере (на ПК или телефоне) для мгновенного входа.",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )


@seller_router.callback_query(F.data.startswith("acc_share:"))
async def cb_acc_share(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.message.answer("⚠️ Аккаунт не найден.")
        return

    _, auth_link, web_link = await format_account_seller_card(acc, bot)
    await callback.message.answer(
        f"🔗 <b>Ссылка для выдачи на номер {acc.phone}:</b>\n<code>{auth_link}</code>\n\n"
        f"🌐 <b>Прямая Web-ссылка:</b>\n<code>{web_link}</code>",
        parse_mode=ParseMode.HTML
    )


@seller_router.callback_query(F.data.startswith("acc_check:"))
async def cb_acc_check(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("⏳ Проверяем сессию...")
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    is_valid, user_info, err = await validate_session(session_file, proxy=proxy_dict)
    if is_valid and user_info:
        await update_account_info(
            acc.id,
            first_name=user_info.get("first_name"),
            last_name=user_info.get("last_name"),
            username=user_info.get("username"),
            tg_user_id=user_info.get("tg_user_id"),
            dc_id=user_info.get("dc_id"),
            status=AccountStatus.ACTIVE
        )
        acc = await get_account_by_id(acc_id)
        text, auth_link, web_link = await format_account_seller_card(acc, bot)
        back_cb = "admin_global_menu" if (is_admin and acc.owner_tg_id != user_id) else "seller_main_menu"
        try:
            await callback.message.edit_text(
                text,
                reply_markup=account_action_keyboard(acc.id, share_url=auth_link, web_url=web_link, back_callback=back_cb),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await callback.message.answer(
                f"✅ <b>Аккаунт {acc.phone} валиден!</b>",
                parse_mode=ParseMode.HTML
            )
    else:
        new_status = AccountStatus.BANNED if "заблокирован" in str(err).lower() else AccountStatus.INVALID
        await update_account_status(acc.id, new_status)
        acc = await get_account_by_id(acc_id)
        status_icon = "🚫" if new_status == AccountStatus.BANNED else "❌"
        status_label = "Забанен" if new_status == AccountStatus.BANNED else "Сессия слетела"
        text = (
            f"{status_icon} <b>Аккаунт невалиден: {acc.phone}</b>\n\n"
            f"<b>Причина:</b> {err}\n\n"
            f"<b>Статус:</b> {status_label}\n\n"
            "📤 <b>Загрузите новый .session файл</b> для этого аккаунта, чтобы он снова заработал.\n"
            "Все данные аккаунта (имя, 2FA, история) сохранены."
        )
        back_cb = "admin_global_menu" if (is_admin and acc.owner_tg_id != user_id) else "seller_main_menu"
        try:
            await callback.message.edit_text(
                text,
                reply_markup=invalid_account_keyboard(acc.id, back_callback=back_cb),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=invalid_account_keyboard(acc.id, back_callback=back_cb),
                parse_mode=ParseMode.HTML
            )


@seller_router.callback_query(F.data.startswith("acc_replace_session:"))
async def cb_acc_replace_session(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await state.update_data(replace_account_id=acc_id)
    await state.set_state(SellerReplaceSessionState.waiting_for_document)
    await callback.message.answer(
        f"📤 <b>Замена сессии для аккаунта {acc.phone}</b>\n\n"
        "Отправьте боту новый <b>.session</b> файл как документ.\n"
        "Сессия должна быть создана через Telethon / MTProto.",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerReplaceSessionState.waiting_for_document, F.document)
async def process_replace_session_doc(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    data = await state.get_data()
    acc_id = data.get("replace_account_id")
    if not acc_id:
        await message.answer("⚠️ Ошибка контекста замены. Попробуйте снова из меню.")
        await state.clear()
        return

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await message.answer("❌ Аккаунт не найден в базе.")
        await state.clear()
        return

    doc = message.document
    if not doc.file_name or not doc.file_name.endswith(".session"):
        await message.answer("⚠️ Файл должен иметь расширение <b>.session</b>. Попробуйте снова.")
        return

    status_msg = await message.answer("⏳ Скачиваем новую сессию и проверяем авторизацию...")
    temp_name = f"replace_temp_{doc.file_name}"
    temp_path = SESSIONS_DIR / temp_name
    await bot.download(doc, destination=temp_path)

    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
    if not proxy_dict:
        active_proxy = await get_first_active_proxy()
        proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    is_valid, user_info, err = await validate_session(temp_path, proxy=proxy_dict)
    if not is_valid or not user_info:
        if temp_path.exists():
            temp_path.unlink()
        await status_msg.edit_text(
            f"❌ <b>Загруженная сессия невалидна:</b> {err}\n\nПопробуйте отправить другой рабочий файл сессии.",
            reply_markup=cancel_to_seller_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    # Valid session! Overwrite old session file
    dest_path = get_session_file_path(acc.session_name)
    if dest_path.exists():
        try:
            dest_path.unlink()
        except Exception:
            pass
    try:
        temp_path.replace(dest_path)
    except Exception:
        import shutil
        shutil.move(str(temp_path), str(dest_path))

    # Update account info and status in DB
    await update_account_info(
        acc.id,
        first_name=user_info.get("first_name"),
        last_name=user_info.get("last_name"),
        username=user_info.get("username"),
        tg_user_id=user_info.get("tg_user_id"),
        dc_id=user_info.get("dc_id"),
        status=AccountStatus.ACTIVE
    )
    await state.clear()

    acc = await get_account_by_id(acc.id)
    text, auth_link, web_link = await format_account_seller_card(acc, bot)
    back_cb = "admin_global_menu" if (is_admin and acc.owner_tg_id != user_id) else "seller_main_menu"

    try:
        await status_msg.delete()
    except Exception:
        pass

    await message.answer(
        f"🎉 <b>Сессия для аккаунта {acc.phone} успешно заменена и проверена!</b>\n\n"
        f"Аккаунт снова активен и готов к выдаче.",
        reply_markup=account_action_keyboard(acc.id, share_url=auth_link, web_url=web_link, back_callback=back_cb),
        parse_mode=ParseMode.HTML
    )


@seller_router.message(SellerReplaceSessionState.waiting_for_document)
async def process_replace_session_non_doc(message: Message):
    await message.answer(
        "⚠️ Пожалуйста, отправьте файл <b>.session</b> как документ, либо нажмите кнопку «Отмена».",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )


@seller_router.callback_query(F.data.startswith("acc_get_code:"))
async def cb_acc_get_code(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Ищем код от Telegram...")
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    code, details, raw = await get_latest_login_code(session_file, proxy=proxy_dict, max_age_seconds=1800)
    if code:
        text = f"🔑 <b>Код авторизации для {acc.phone}:</b>\n\n<code>{code}</code>\n\n{details or ''}"
        asyncio.create_task(log_code_retrieved(
            callback.bot,
            phone=acc.phone,
            code=code,
            user_id=callback.from_user.id if callback.from_user else 0,
            username=callback.from_user.username if callback.from_user else None,
            is_buyer=False
        ))
    else:
        text = f"ℹ️ <b>Для {acc.phone} нет свежих кодов:</b>\n<i>{raw}</i>\n\nОтправьте запрос на вход в Telegram и повторите попытку."
    
    await callback.message.answer(text, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_get_authkey:"))
async def cb_acc_get_authkey(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Извлекаем Auth Key...")
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    auth_key_hex, dc_id, string_sess, err = await get_account_auth_key(session_file, proxy=proxy_dict)
    if not auth_key_hex:
        await callback.message.answer(f"❌ Ошибка извлечения Auth Key: {err}")
        return

    text = (
        f"🔑 <b>Auth Key & Данные авторизации ({acc.phone}):</b>\n\n"
        f"<b>DC ID:</b> <code>{dc_id}</code>\n\n"
        f"<b>Auth Key (HEX):</b>\n<code>{auth_key_hex}</code>\n\n"
        f"<b>Telethon StringSession:</b>\n<code>{string_sess}</code>"
    )
    await callback.message.answer(text, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_download_tdata:"))
async def cb_acc_download_tdata(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.message.answer("⚠️ Аккаунт не найден.")
        return

    session_file = get_session_file_path(acc.session_name)
    if not session_file.exists():
        await callback.message.answer("❌ Файл сессии не найден на диске.")
        return

    wait_msg = await callback.message.answer("⏳ Генерируем Tdata архив...")
    
    clean_phone = acc.phone.replace("+", "").strip()
    zip_path = SESSIONS_DIR / f"tdata_{clean_phone}.zip"
    
    ok, err = export_session_to_tdata_zip(session_file, zip_path, user_id=acc.tg_user_id or 0)
    if not ok or not zip_path.exists():
        await wait_msg.edit_text(f"❌ Ошибка генерации Tdata: {err}")
        return

    doc_file = FSInputFile(str(zip_path), filename=f"tdata_{clean_phone}.zip")
    await callback.message.answer_document(
        doc_file,
        caption=(
            f"📁 <b>Tdata архив для {acc.phone}</b>\n\n"
            f"<b>Как использовать:</b>\n"
            f"1. Распакуйте архив\n"
            f"2. Поместите папку <code>tdata</code> в директорию Telegram Desktop\n"
            f"3. Запустите Telegram Desktop — вход произойдет моментально!"
        ),
        parse_mode=ParseMode.HTML
    )
    try:
        await wait_msg.delete()
    except Exception:
        pass


@seller_router.callback_query(F.data.startswith("acc_download_session:"))
async def cb_acc_download_session(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.message.answer("⚠️ Аккаунт не найден.")
        return

    session_file = get_session_file_path(acc.session_name)
    if not session_file.exists():
        await callback.message.answer("❌ Файл сессии не найден на диске.")
        return

    clean_phone = acc.phone.replace("+", "").strip()
    doc_file = FSInputFile(str(session_file), filename=f"{clean_phone}.session")
    await callback.message.answer_document(
        doc_file,
        caption=f"📄 <b>Telethon .session файл для аккаунта:</b> <code>{acc.phone}</code>",
        parse_mode=ParseMode.HTML
    )


@seller_router.callback_query(F.data.startswith("acc_delete:"))
async def cb_acc_delete(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if acc:
        session_file = get_session_file_path(acc.session_name)
        if session_file.exists():
            try:
                session_file.unlink()
            except Exception:
                pass
        await delete_account_by_id(acc_id)
        asyncio.create_task(log_account_deleted(
            bot,
            phone=acc.phone,
            user_id=user_id,
            username=callback.from_user.username if callback.from_user else None
        ))
    await callback.answer("Аккаунт удален", show_alert=True)
    text, kb = await build_seller_dashboard_view(user_id, bot, page=1)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# --- Account Management Sub-menu (Screenshot 2) ---

@seller_router.callback_query(F.data.startswith("acc_manage:"))
async def cb_acc_manage(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if not acc:
        await callback.message.answer("⚠️ Аккаунт не найден.")
        return

    text, _, _ = await format_account_seller_card(acc, bot)
    await callback.message.edit_text(
        text,
        reply_markup=account_management_keyboard(acc.id, is_admin=is_admin),
        parse_mode=ParseMode.HTML
    )


@seller_router.callback_query(F.data.startswith("acc_edit_first_name:"))
async def cb_edit_first_name(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    await state.update_data(editing_account_id=acc_id)
    await state.set_state(SellerEditFirstNameState.waiting_for_name)
    await callback.message.answer(
        "📝 <b>Введите новое имя для аккаунта:</b>",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerEditFirstNameState.waiting_for_name, F.text)
async def process_first_name(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    data = await state.get_data()
    acc_id = data.get("editing_account_id")
    new_name = message.text.strip()

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if acc:
        session_file = get_session_file_path(acc.session_name)
        proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
        
        ok, res_msg = await update_profile_info(session_file, first_name=new_name, proxy=proxy_dict)
        if ok:
            await update_account_info(acc_id, first_name=new_name)
            await message.answer(f"✅ Имя успешно изменено на: <b>{new_name}</b>", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ {res_msg}")

    await state.clear()
    acc = await get_account_by_id(acc_id)
    text, _, _ = await format_account_seller_card(acc, bot)
    await message.answer(text, reply_markup=account_management_keyboard(acc.id, is_admin=is_admin), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_edit_last_name:"))
async def cb_edit_last_name(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    await state.update_data(editing_account_id=acc_id)
    await state.set_state(SellerEditLastNameState.waiting_for_name)
    await callback.message.answer(
        "📝 <b>Введите новую фамилию для аккаунта (или <code>-</code> чтобы удалить):</b>",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerEditLastNameState.waiting_for_name, F.text)
async def process_last_name(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    data = await state.get_data()
    acc_id = data.get("editing_account_id")
    raw_name = message.text.strip()
    new_name = "" if raw_name == "-" else raw_name

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if acc:
        session_file = get_session_file_path(acc.session_name)
        proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
        
        ok, res_msg = await update_profile_info(session_file, last_name=new_name, proxy=proxy_dict)
        if ok:
            await update_account_info(acc_id, last_name=new_name if new_name else None)
            await message.answer(f"✅ Фамилия обновлена: <b>{new_name or 'Удалена'}</b>", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ {res_msg}")

    await state.clear()
    acc = await get_account_by_id(acc_id)
    text, _, _ = await format_account_seller_card(acc, bot)
    await message.answer(text, reply_markup=account_management_keyboard(acc.id, is_admin=is_admin), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_edit_2fa:"))
async def cb_edit_2fa(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    await state.update_data(editing_account_id=acc_id)
    await state.set_state(SellerEdit2FAState.waiting_for_password)
    await callback.message.answer(
        "🔐 <b>Введите новый 2FA пароль (или отправьте <code>-</code> чтобы удалить пароль):</b>",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerEdit2FAState.waiting_for_password, F.text)
async def process_edit_2fa(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    data = await state.get_data()
    acc_id = data.get("editing_account_id")
    raw_pwd = message.text.strip()
    new_pwd = None if raw_pwd in ("-", "0", "") else raw_pwd

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if acc:
        session_file = get_session_file_path(acc.session_name)
        proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
        
        status_msg = await message.answer("⏳ Обновляем 2FA на серверах Telegram...")
        ok, res_msg = await update_profile_2fa(session_file, new_password=new_pwd, current_password=acc.two_fa, proxy=proxy_dict)
        if ok:
            await update_account_info(acc_id, two_fa=new_pwd)
            asyncio.create_task(log_2fa_changed(
                bot,
                phone=acc.phone,
                user_id=user_id,
                username=message.from_user.username if message.from_user else None
            ))
            await status_msg.edit_text(res_msg, parse_mode=ParseMode.HTML)
        else:
            await status_msg.edit_text(f"❌ {res_msg}", parse_mode=ParseMode.HTML)

    await state.clear()
    acc = await get_account_by_id(acc_id)
    text, _, _ = await format_account_seller_card(acc, bot)
    await message.answer(text, reply_markup=account_management_keyboard(acc.id, is_admin=is_admin), parse_mode=ParseMode.HTML)


# --- Email Management Handlers ---

@seller_router.callback_query(F.data.startswith("acc_edit_email:"))
async def cb_acc_edit_email(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
    
    # Check live email info from Telegram
    ok, email_pattern, details = await get_account_email_info(session_file, proxy=proxy_dict)
    current_email = email_pattern or acc.email or "Не привязана"

    await state.set_state(SellerEditEmailState.waiting_for_email)
    await state.update_data(account_id=acc_id)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отвязать текущую почту", callback_data=f"acc_unbind_email:{acc_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"acc_manage:{acc_id}"))

    text = (
        f"📧 <b>Управление почтой (Email) для <code>{acc.phone}</code></b>\n\n"
        f"<b>Текущий статус:</b> <code>{current_email}</code>\n\n"
        "✉️ Отправьте <b>новый адрес электронной почты</b> (например, <code>myemail@gmail.com</code>):\n"
        "<i>Telegram отправит 6-значный проверочный код на этот ящик для подтверждения.</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await callback.answer()


@seller_router.callback_query(F.data.startswith("acc_unbind_email:"))
async def cb_acc_unbind_email(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    acc_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    wait_msg = await callback.message.answer("⏳ Отвязываем почту от аккаунта...")
    ok, err = await remove_account_email(session_file, current_password=acc.two_fa, proxy=proxy_dict)
    if ok:
        await update_account_info(acc_id, email=None)
        asyncio.create_task(log_email_changed(
            callback.bot,
            phone=acc.phone,
            email=None,
            user_id=user_id,
            username=callback.from_user.username if callback.from_user else None,
            action="unbind"
        ))
        await wait_msg.edit_text("✅ <b>Email успешно отвязан от аккаунта!</b>", parse_mode=ParseMode.HTML)
    else:
        await wait_msg.edit_text(f"❌ <b>Не удалось отвязать почту:</b> {err}", parse_mode=ParseMode.HTML)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⚙️ К управлению аккаунтом", callback_data=f"acc_manage:{acc_id}"))
    await callback.message.answer("Выберите действие:", reply_markup=builder.as_markup())
    await callback.answer()


@seller_router.message(SellerEditEmailState.waiting_for_email, F.text)
async def process_seller_edit_email(message: Message, state: FSMContext):
    new_email = message.text.strip() if message.text else ""
    if "@" not in new_email or "." not in new_email:
        await message.answer("❌ Введите корректный email (например, <code>example@gmail.com</code>). Попробуйте еще раз:")
        return

    data = await state.get_data()
    acc_id = data.get("account_id")
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await message.answer("❌ Аккаунт не найден.")
        await state.clear()
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    wait_msg = await message.answer(f"⏳ Отправляем код подтверждения на <code>{new_email}</code>...", parse_mode=ParseMode.HTML)
    ok, res = await request_set_account_email(session_file, new_email, current_password=acc.two_fa, proxy=proxy_dict)

    if ok:
        await state.set_state(SellerEditEmailState.waiting_for_code)
        await state.update_data(account_id=acc_id, pending_email=new_email)
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"acc_manage:{acc_id}"))
        await wait_msg.edit_text(
            f"📬 <b>Код подтверждения отправлен на почту <code>{new_email}</code>!</b>\n\n"
            "Введите <b>код из письма</b>, чтобы завершить привязку:",
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
    else:
        await wait_msg.edit_text(
            f"❌ <b>Ошибка при отправке кода:</b>\n{res}\n\nПопробуйте ввести другой email:",
            parse_mode=ParseMode.HTML
        )


@seller_router.message(SellerEditEmailState.waiting_for_code, F.text)
async def process_seller_edit_email_code(message: Message, state: FSMContext):
    code = message.text.strip() if message.text else ""
    data = await state.get_data()
    acc_id = data.get("account_id")
    pending_email = data.get("pending_email")
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await message.answer("❌ Аккаунт не найден.")
        await state.clear()
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    wait_msg = await message.answer("⏳ Проверяем код...", parse_mode=ParseMode.HTML)
    ok, res = await confirm_account_email_code(session_file, code, proxy=proxy_dict)

    if ok:
        await update_account_info(acc_id, email=pending_email)
        asyncio.create_task(log_email_changed(
            message.bot,
            phone=acc.phone,
            email=pending_email,
            user_id=user_id,
            username=message.from_user.username if message.from_user else None,
            action="bind"
        ))
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="⚙️ К управлению аккаунтом", callback_data=f"acc_manage:{acc_id}"))
        builder.row(InlineKeyboardButton(text="🏠 В главное меню", callback_data="seller_main_menu"))
        await wait_msg.edit_text(
            f"✅ <b>Почта <code>{pending_email}</code> успешно привязана к аккаунту!</b>",
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
    else:
        await wait_msg.edit_text(
            f"❌ <b>{res}</b>\n\nПопробуйте ввести код еще раз или нажмите Отмена:",
            parse_mode=ParseMode.HTML
        )


@seller_router.callback_query(F.data.startswith("acc_edit_username:"))
async def cb_edit_username(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    await state.update_data(editing_account_id=acc_id)
    await state.set_state(SellerEditUsernameState.waiting_for_username)
    await callback.message.answer(
        "📝 <b>Введите новый @username (или <code>-</code> чтобы удалить):</b>",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerEditUsernameState.waiting_for_username, F.text)
async def process_edit_username(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    data = await state.get_data()
    acc_id = data.get("editing_account_id")
    raw_usr = message.text.strip().replace("@", "")
    new_usr = "" if raw_usr == "-" else raw_usr

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if acc:
        session_file = get_session_file_path(acc.session_name)
        proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
        
        ok, res_msg = await update_profile_username(session_file, username=new_usr, proxy=proxy_dict)
        if ok:
            await update_account_info(acc_id, username=new_usr if new_usr else None)
            await message.answer(res_msg, parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ {res_msg}")

    await state.clear()
    acc = await get_account_by_id(acc_id)
    text, _, _ = await format_account_seller_card(acc, bot)
    await message.answer(text, reply_markup=account_management_keyboard(acc.id, is_admin=is_admin), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_edit_bio:"))
async def cb_edit_bio(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    await state.update_data(editing_account_id=acc_id)
    await state.set_state(SellerEditBioState.waiting_for_bio)
    await callback.message.answer(
        "📝 <b>Введите текст \"О себе\" (или <code>-</code> чтобы очистить):</b>",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerEditBioState.waiting_for_bio, F.text)
async def process_edit_bio(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    data = await state.get_data()
    acc_id = data.get("editing_account_id")
    raw_bio = message.text.strip()
    new_bio = "" if raw_bio == "-" else raw_bio

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        acc = await get_account_by_id(acc_id)
    if acc:
        session_file = get_session_file_path(acc.session_name)
        proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
        
        ok, res_msg = await update_profile_info(session_file, about=new_bio, proxy=proxy_dict)
        if ok:
            await message.answer("✅ Био успешно обновлено!", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"❌ {res_msg}")

    await state.clear()
    acc = await get_account_by_id(acc_id)
    text, _, _ = await format_account_seller_card(acc, bot)
    await message.answer(text, reply_markup=account_management_keyboard(acc.id, is_admin=is_admin), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_devices:"))
async def cb_acc_devices(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Получаем список сессий...")
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, devices, err = await get_active_authorizations(session_file, proxy=proxy_dict)
    if not ok:
        await callback.message.answer(f"❌ Ошибка получения сессий: {err}")
        return

    text = f"💻 <b>Активные устройства для {acc.phone} ({len(devices)} шт.):</b>\n\n"
    for idx, d in enumerate(devices, start=1):
        cur = " (🌟 Текущая)" if d.get("current") else ""
        date_str = d.get("date_active").strftime("%d.%m.%Y %H:%M") if d.get("date_active") else "—"
        text += (
            f"<b>{idx}. {d.get('device_model')} ({d.get('platform')})</b>{cur}\n"
            f"• IP: <code>{d.get('ip')}</code> ({d.get('country')})\n"
            f"• Активность: {date_str}\n\n"
        )

    await callback.message.edit_text(text, reply_markup=devices_management_keyboard(acc.id), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_term_all:"))
async def cb_acc_term_all(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Сбрасываем сторонние сессии...")
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, msg = await terminate_other_sessions(session_file, proxy=proxy_dict)
    if ok:
        asyncio.create_task(log_sessions_terminated(
            callback.bot,
            phone=acc.phone,
            user_id=user_id,
            username=callback.from_user.username if callback.from_user else None,
            is_buyer=False
        ))
    await callback.message.answer(msg, parse_mode=ParseMode.HTML)


# --- Chat & Channel Management ---

async def _render_dialogs_view(acc, target_message: Message, filter_type: str = "all", page: int = 1, edit: bool = True):
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, dialogs, err = await get_account_dialogs(session_file, proxy=proxy_dict, limit=80)
    if not ok:
        if edit:
            try:
                await target_message.edit_text(f"❌ Не удалось загрузить диалоги: {err}")
                return
            except Exception:
                pass
        await target_message.answer(f"❌ Не удалось загрузить диалоги: {err}")
        return

    if filter_type != "all":
        filtered = [d for d in dialogs if d.get("type") == filter_type]
    else:
        filtered = dialogs

    limit_per_page = 6
    total_pages = max(1, (len(filtered) + limit_per_page - 1) // limit_per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * limit_per_page
    paged_dialogs = filtered[offset:offset + limit_per_page]

    filter_names = {
        "all": "Все диалоги",
        "user": "Личные сообщения (ЛС)",
        "group": "Группы",
        "channel": "Каналы",
        "bot": "Боты"
    }

    text = (
        f"💬 <b>Чаты и каналы аккаунта {acc.phone}</b>\n\n"
        f"📊 Всего найдено: <b>{len(filtered)}</b> (Фильтр: <i>{filter_names.get(filter_type, filter_type)}</i>)\n\n"
        "<i>Выберите диалог из списка ниже, откройте «⭐️ Избранное» или воспользуйтесь поиском:</i>"
    )

    kb = account_dialogs_keyboard(acc.id, paged_dialogs, page=page, total_pages=total_pages, filter_type=filter_type)
    if edit:
        try:
            await target_message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass
    await target_message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def _render_chat_view(acc, chat_id: int, target_message: Message, offset_id: int = 0, edit: bool = True):
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, chat_info, messages, oldest_msg_id, err = await get_chat_paged_messages(
        session_file, chat_id, offset_id=offset_id, limit=6, proxy=proxy_dict
    )
    if not ok:
        if edit:
            try:
                await target_message.edit_text(f"❌ Ошибка открытия чата: {err}")
                return
            except Exception:
                pass
        await target_message.answer(f"❌ Ошибка открытия чата: {err}")
        return

    title = chat_info.get("title", f"ID: {chat_id}")
    usr = f"@{chat_info.get('username')}" if chat_info.get("username") else ("Избранное" if chat_info.get("is_saved") else "Личный диалог")
    is_bot = chat_info.get("is_bot", False)
    is_saved = chat_info.get("is_saved", False)

    page_note = f" (История от сообщения #{offset_id})" if offset_id > 0 else ""
    text = (
        f"💬 <b>Чат: {title}</b>{page_note}\n"
        f"🏷 Тип: <code>{usr}</code> | ID: <code>{chat_id}</code>\n\n"
        "📜 <b>Переписка:</b>\n"
    )

    photo_msg_ids = []
    bot_buttons = None

    if not messages:
        text += "<i>Сообщений не найдено (достигнуто начало истории).</i>\n"
    else:
        for m in reversed(messages):
            out_icon = "📤" if m.get("is_out") else "📥"
            text += f"{out_icon} <b>{m.get('sender')}</b> <i>({m.get('date')})</i>:\n{m.get('text')}\n\n"
            if m.get("has_photo"):
                photo_msg_ids.append(m["id"])
            if m.get("buttons") and not bot_buttons:
                bot_buttons = []
                for row in m["buttons"]:
                    row_with_id = []
                    for b in row:
                        b_copy = dict(b)
                        b_copy["msg_id"] = m["id"]
                        row_with_id.append(b_copy)
                    bot_buttons.append(row_with_id)

    kb = chat_actions_keyboard(
        acc.id,
        chat_id,
        offset_id=offset_id,
        oldest_msg_id=oldest_msg_id,
        photo_msg_ids=photo_msg_ids,
        is_bot=is_bot,
        bot_buttons=bot_buttons,
        reply_buttons=chat_info.get("reply_keyboard"),
        is_saved=is_saved
    )

    if edit:
        try:
            await target_message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass
    await target_message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_dialogs:"))
async def cb_acc_dialogs(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Просмотр и управление чатами доступны только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    filter_type = parts[2] if len(parts) > 2 else "all"
    page = int(parts[3]) if len(parts) > 3 else 1

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Загружаем чаты и каналы...")
    await _render_dialogs_view(acc, callback.message, filter_type=filter_type, page=page, edit=True)


@seller_router.callback_query(F.data == "acc_dialogs_noop")
async def cb_acc_dialogs_noop(callback: CallbackQuery):
    await callback.answer()


@seller_router.callback_query(F.data.startswith("acc_saved_messages:"))
async def cb_acc_saved_messages(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Доступ к «Избранному» разрешен только администраторам.", show_alert=True)
        return

    acc_id = int(callback.data.split(":")[1])
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Открываем Избранное...")
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, saved_id, err = await get_saved_messages_id(session_file, proxy=proxy_dict)
    if not ok:
        await callback.message.answer(f"❌ Ошибка открытия Избранного: {err}")
        return

    await _render_chat_view(acc, saved_id, callback.message, offset_id=0, edit=True)


@seller_router.callback_query(F.data.startswith("acc_search_chats:"))
async def cb_acc_search_chats(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Поиск чатов доступен только администраторам.", show_alert=True)
        return

    acc_id = int(callback.data.split(":")[1])
    await state.update_data(search_acc_id=acc_id)
    await state.set_state(SellerSearchChatState.waiting_for_query)

    await callback.message.answer(
        "🔍 <b>Поиск диалогов, каналов, ботов и пользователей</b>\n\n"
        "Отправьте @юзернейм, ссылку или название для поиска:\n"
        "• Например: <code>@BotFather</code>, <code>@durov</code> или <code>CryptoBot</code>",
        reply_markup=cancel_to_dialogs_keyboard(acc_id),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerSearchChatState.waiting_for_query, F.text)
async def process_search_chats(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await message.answer("⛔ Поиск чатов доступен только администраторам.")
        await state.clear()
        return

    data = await state.get_data()
    acc_id = data.get("search_acc_id")
    query = message.text.strip()

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await message.answer("❌ Аккаунт не найден.")
        await state.clear()
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    status_msg = await message.answer(f"🔍 Ищем «<code>{query}</code>»...")
    ok, dialogs, err = await search_account_dialogs(session_file, query, proxy=proxy_dict)
    await state.clear()

    if not ok:
        await status_msg.edit_text(f"❌ Ошибка поиска: {err}")
        return

    if not dialogs:
        await status_msg.edit_text(
            f"🔍 По запросу «<code>{query}</code>» ничего не найдено.\nПопробуйте ввести точный <b>@юзернейм</b>.",
            reply_markup=cancel_to_dialogs_keyboard(acc_id),
            parse_mode=ParseMode.HTML
        )
        return

    await status_msg.delete()
    text = (
        f"🔍 <b>Результаты поиска по «{query}» ({len(dialogs)} шт.):</b>\n\n"
        "<i>Нажмите на результат для перехода в переписку:</i>"
    )
    kb = account_dialogs_keyboard(acc.id, dialogs[:6], page=1, total_pages=max(1, (len(dialogs)+5)//6), filter_type="all")
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_open_chat:"))
@seller_router.callback_query(F.data.startswith("chat_history:"))
async def cb_acc_open_chat(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Просмотр переписок доступен только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    chat_id = int(parts[2])
    offset_id = int(parts[3]) if len(parts) > 3 else 0

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Загружаем переписку...")
    await _render_chat_view(acc, chat_id, callback.message, offset_id=offset_id, edit=True)


@seller_router.callback_query(F.data.startswith("chat_photo:"))
async def cb_chat_photo(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Доступ к просмотру фото разрешен только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    chat_id = int(parts[2])
    msg_id = int(parts[3])

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await callback.answer("Загружаем фото с аккаунта...")
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, photo_bytes, caption, err = await download_message_photo_bytes(session_file, chat_id, msg_id, proxy=proxy_dict)
    if not ok or not photo_bytes:
        await callback.message.answer(f"❌ {err or 'Не удалось загрузить фото'}")
        return

    photo_file = BufferedInputFile(photo_bytes, filename=f"photo_{msg_id}.jpg")
    cap_text = f"🖼 <b>Фото из сообщения #{msg_id}</b>\n\n{caption}" if caption else f"🖼 <b>Фото из сообщения #{msg_id}</b>"
    await callback.message.answer_photo(photo_file, caption=cap_text, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("chat_send_start:"))
async def cb_chat_send_start(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Управление ботами доступно только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    chat_id = int(parts[2])

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    await callback.answer("Отправляем /start боту...")
    ok, res_msg = await send_message_as_account(session_file, chat_id, "/start", proxy=proxy_dict)
    await callback.message.answer(res_msg, parse_mode=ParseMode.HTML)

    await asyncio.sleep(1.0)
    await _render_chat_view(acc, chat_id, callback.message, offset_id=0, edit=False)


@seller_router.callback_query(F.data.startswith("bot_btn:"))
async def cb_bot_btn(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Управление ботами доступно только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    chat_id = int(parts[2])
    msg_id = int(parts[3])
    row_col = parts[4].split("_")
    row, col = int(row_col[0]), int(row_col[1])

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    await callback.answer("Нажимаем кнопку...")
    ok, msg, btn_url = await click_bot_message_button(session_file, chat_id, msg_id, row, col, proxy=proxy_dict)
    if not ok:
        await callback.message.answer(f"❌ {msg}")
        return

    if btn_url:
        await callback.message.answer(
            f"🔗 <b>Ссылка действия:</b>\n<code>{btn_url}</code>",
            parse_mode=ParseMode.HTML
        )

    await _render_chat_view(acc, chat_id, callback.message, offset_id=0, edit=False)


@seller_router.callback_query(F.data.startswith("bot_rbtn:"))
async def cb_bot_rbtn(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Управление ботами доступно только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    chat_id = int(parts[2])
    row, col = map(int, parts[3].split("_"))

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, chat_info, messages, _, err = await get_chat_paged_messages(session_file, chat_id, limit=5, proxy=proxy_dict)
    if not ok:
        await callback.answer(f"Ошибка: {err}", show_alert=True)
        return

    r_kb = chat_info.get("reply_keyboard", [])
    if row < len(r_kb) and col < len(r_kb[row]):
        btn_text = r_kb[row][col]
        await callback.answer(f"Нажимаем «{btn_text}»...")
        await send_message_as_account(session_file, chat_id, btn_text, proxy=proxy_dict)
        await asyncio.sleep(1.2)
        await _render_chat_view(acc, chat_id, callback.message, offset_id=0, edit=False)
    else:
        await callback.answer("Кнопка устарела, обновляем...", show_alert=True)
        await _render_chat_view(acc, chat_id, callback.message, offset_id=0, edit=False)


@seller_router.callback_query(F.data.startswith("chat_send_msg:"))
async def cb_chat_send_msg(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Отправка сообщений доступна только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    chat_id = int(parts[2])

    await state.update_data(sending_acc_id=acc_id, sending_chat_id=chat_id)
    await state.set_state(SellerSendChatMessageState.waiting_for_text)

    await callback.message.answer(
        "✍️ <b>Введите текст сообщения, которое нужно отправить в этот чат от имени аккаунта:</b>",
        reply_markup=cancel_to_chat_keyboard(acc_id, chat_id),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerSendChatMessageState.waiting_for_text, F.text)
async def process_send_chat_message(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await message.answer("⛔ Отправка сообщений доступна только администраторам.")
        await state.clear()
        return

    data = await state.get_data()
    acc_id = data.get("sending_acc_id")
    chat_id = data.get("sending_chat_id")
    text_to_send = message.text

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await message.answer("❌ Аккаунт не найден.")
        await state.clear()
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    status_msg = await message.answer("⏳ Отправляем сообщение от имени аккаунта...")
    ok, res_msg = await send_message_as_account(session_file, chat_id, text_to_send, proxy=proxy_dict)

    await state.clear()
    await status_msg.edit_text(res_msg, parse_mode=ParseMode.HTML)

    await _render_chat_view(acc, chat_id, message, offset_id=0, edit=False)


@seller_router.callback_query(F.data.startswith("chat_leave:"))
async def cb_chat_leave(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Выход из чатов доступен только администраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    acc_id = int(parts[1])
    chat_id = int(parts[2])

    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    await callback.answer("Покидаем чат...")
    ok, msg = await leave_chat_as_account(session_file, chat_id, proxy=proxy_dict)
    await callback.message.answer(msg, parse_mode=ParseMode.HTML)

    await _render_dialogs_view(acc, callback.message, filter_type="all", page=1, edit=False)


@seller_router.callback_query(F.data.startswith("acc_join_chat:"))
async def cb_acc_join_chat(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await callback.answer("⛔ Вступление в чаты доступно только администраторам.", show_alert=True)
        return

    acc_id = int(callback.data.split(":")[1])
    await state.update_data(joining_acc_id=acc_id)
    await state.set_state(SellerJoinChatState.waiting_for_link)
    
    await callback.message.answer(
        "🔗 <b>Отправьте ссылку или @юзернейм канала/чата, в который нужно вступить:</b>\n\n"
        "• Например: <code>https://t.me/durov</code> или <code>@durov</code> или ссылка-приглашение <code>https://t.me/+AbCdEfGh</code>",
        reply_markup=cancel_to_dialogs_keyboard(acc_id),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@seller_router.message(SellerJoinChatState.waiting_for_link, F.text)
async def process_join_chat(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    if not is_admin:
        await message.answer("⛔ Вступление в чаты доступно только администраторам.")
        await state.clear()
        return

    data = await state.get_data()
    acc_id = data.get("joining_acc_id")
    target_link = message.text.strip()
    
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await message.answer("❌ Аккаунт не найден.")
        await state.clear()
        return
        
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None
    
    status_msg = await message.answer("⏳ Вступаем в чат/канал от имени аккаунта...")
    ok, res_msg = await join_chat_as_account(session_file, target_link, proxy=proxy_dict)
    
    await state.clear()
    await status_msg.edit_text(res_msg, parse_mode=ParseMode.HTML)


# --- Upload Flows (Associated with current seller user_id) ---

@seller_router.callback_query(F.data == "seller_upload_menu")
async def cb_seller_upload_menu(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    text = (
        f"💼 <b>{user_header} / Меню добавления аккаунтов</b>\n\n"
        "В каком формате будем добавлять аккаунт?"
    )
    await callback.message.edit_text(text, reply_markup=upload_format_keyboard(), parse_mode=ParseMode.HTML)
    await callback.answer()


# 1. Upload .session file
@seller_router.callback_query(F.data == "seller_upload_session")
async def cb_upload_session(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SellerUploadSessionState.waiting_for_document)
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    text = (
        f"💼 <b>{user_header}</b>\n\n"
        "Для подключения аккаунта отправьте боту <b>.session</b> файл.\n\n"
        "▪️ .session файл должен быть создан через Telethon / MTProto."
    )
    await callback.message.edit_text(text, reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)
    await callback.answer()


@seller_router.message(SellerUploadSessionState.waiting_for_document, F.document)
async def process_upload_session_doc(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    doc = message.document
    if not doc.file_name or not doc.file_name.endswith(".session"):
        await message.answer("⚠️ Файл должен иметь расширение <b>.session</b>. Попробуйте снова.")
        return

    status_msg = await message.answer("⏳ Скачиваем сессию и проверяем авторизацию...")
    
    temp_name = f"temp_{doc.file_name}"
    temp_path = SESSIONS_DIR / temp_name
    await bot.download(doc, destination=temp_path)

    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    is_valid, user_info, err = await validate_session(temp_path, proxy=proxy_dict)
    if not is_valid or not user_info:
        if temp_path.exists():
            temp_path.unlink()
        await status_msg.edit_text(f"❌ <b>Сессия не валидна:</b> {err}\n\nПопробуйте другой файл.", reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)
        return

    phone = user_info.get("phone")
    if not phone:
        phone = doc.file_name.replace(".session", "")

    clean_phone = phone.replace("+", "").strip()
    final_session_name = f"{clean_phone}.session"
    final_path = SESSIONS_DIR / final_session_name

    if final_path.exists():
        final_path.unlink()
    temp_path.rename(final_path)

    await state.update_data(
        phone=phone,
        session_name=final_session_name,
        user_info=user_info,
        proxy_id=active_proxy.id if active_proxy else None,
        owner_tg_id=user_id,
        owner_username=username
    )
    await state.set_state(SellerUploadSessionState.waiting_for_2fa)

    await status_msg.edit_text(
        f"✅ <b>Сессия валидна!</b>\n\n"
        f"📱 Номер: <code>{phone}</code>\n"
        f"👤 Имя: {user_info.get('first_name') or ''} {user_info.get('last_name') or ''}\n"
        f"🌐 DC: {user_info.get('dc_id')}\n\n"
        "🔐 <b>Укажите 2FA облачный пароль</b> (или отправьте <code>-</code>, если пароля нет):",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )


@seller_router.message(SellerUploadSessionState.waiting_for_2fa)
async def process_session_2fa(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    raw_2fa = message.text.strip() if message.text else ""
    two_fa = None if raw_2fa in ("-", "0", "") else raw_2fa

    data = await state.get_data()
    user_info = data.get("user_info", {})
    phone = data.get("phone")
    session_name = data.get("session_name")
    proxy_id = data.get("proxy_id")
    owner_tg_id = data.get("owner_tg_id", user_id)
    owner_username = data.get("owner_username")

    account = await add_or_update_account(
        phone=phone,
        session_name=session_name,
        tg_user_id=user_info.get("tg_user_id"),
        first_name=user_info.get("first_name"),
        last_name=user_info.get("last_name"),
        username=user_info.get("username"),
        dc_id=user_info.get("dc_id"),
        two_fa=two_fa,
        status=AccountStatus.ACTIVE,
        proxy_id=proxy_id,
        owner_tg_id=owner_tg_id,
        owner_username=owner_username
    )

    asyncio.create_task(log_account_added(
        message.bot,
        phone=account.phone,
        method="Session Файл",
        owner_id=owner_tg_id,
        owner_username=owner_username,
        first_name=user_info.get("first_name")
    ))

    await state.clear()
    await message.answer(
        f"🎉 <b>Аккаунт {account.phone} успешно добавлен в ваш профиль!</b>\n\n"
        f"• Статус: 🟢 Валиден\n"
        f"• 2FA: <code>{account.two_fa or 'Не установлен'}</code>\n",
        parse_mode=ParseMode.HTML
    )

    text, kb = await build_seller_dashboard_view(user_id, message.bot, page=1)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# 2. Upload by ZIP archive
@seller_router.callback_query(F.data == "seller_upload_zip")
async def cb_upload_zip(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SellerUploadZipState.waiting_for_zip)
    text = (
        "🗂 <b>Массовая загрузка аккаунтов из ZIP</b>\n\n"
        "Отправьте боту <b>.zip архив</b> с .session файлами."
    )
    await callback.message.edit_text(text, reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)
    await callback.answer()


@seller_router.message(SellerUploadZipState.waiting_for_zip, F.document)
async def process_upload_zip(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    doc = message.document
    if not doc.file_name or not (doc.file_name.endswith(".zip") or doc.file_name.endswith(".rar")):
        await message.answer("⚠️ Файл должен быть <b>.zip архивом</b>. Попробуйте снова.")
        return

    status_msg = await message.answer("⏳ Скачиваем и распаковываем архив...")
    
    file_bytes = io.BytesIO()
    await bot.download(doc, destination=file_bytes)
    file_bytes.seek(0)

    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    added = 0
    failed = 0

    try:
        with zipfile.ZipFile(file_bytes, 'r') as zip_ref:
            session_files = [f for f in zip_ref.namelist() if f.endswith(".session") and not f.startswith("__MACOSX")]
            
            if not session_files:
                await status_msg.edit_text("❌ В архиве не найдено ни одного .session файла.", reply_markup=cancel_to_seller_keyboard())
                await state.clear()
                return

            await status_msg.edit_text(f"🔍 Найдено {len(session_files)} сессий. Проверяем...")

            for item in session_files:
                basename = Path(item).name
                extracted_data = zip_ref.read(item)
                target_path = SESSIONS_DIR / basename
                
                with open(target_path, "wb") as f_out:
                    f_out.write(extracted_data)

                is_valid, user_info, err = await validate_session(target_path, proxy=proxy_dict)
                if is_valid and user_info:
                    phone = user_info.get("phone") or basename.replace(".session", "")
                    clean_phone = phone.replace("+", "").strip()
                    final_name = f"{clean_phone}.session"
                    final_path = SESSIONS_DIR / final_name
                    
                    if target_path != final_path:
                        if final_path.exists():
                            final_path.unlink()
                        target_path.rename(final_path)

                    await add_or_update_account(
                        phone=phone,
                        session_name=final_name,
                        tg_user_id=user_info.get("tg_user_id"),
                        first_name=user_info.get("first_name"),
                        last_name=user_info.get("last_name"),
                        username=user_info.get("username"),
                        dc_id=user_info.get("dc_id"),
                        status=AccountStatus.ACTIVE,
                        proxy_id=active_proxy.id if active_proxy else None,
                        owner_tg_id=user_id,
                        owner_username=username
                    )
                    asyncio.create_task(log_account_added(
                        bot,
                        phone=phone,
                        method="ZIP Архив",
                        owner_id=user_id,
                        owner_username=username,
                        first_name=user_info.get("first_name")
                    ))
                    added += 1
                else:
                    if target_path.exists():
                        target_path.unlink()
                    failed += 1

    except Exception as e:
        logger.error(f"Error extracting zip: {e}")
        await status_msg.edit_text(f"❌ Ошибка обработки ZIP: {str(e)}", reply_markup=cancel_to_seller_keyboard())
        await state.clear()
        return

    await state.clear()
    await status_msg.edit_text(
        f"📊 <b>Результат импорта:</b>\n\n"
        f"✅ Добавлено: <b>{added}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>\n",
        parse_mode=ParseMode.HTML
    )
    text, kb = await build_seller_dashboard_view(user_id, bot, page=1)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# 2.1 Upload by TData (ZIP archive)
@seller_router.callback_query(F.data == "seller_upload_tdata")
async def cb_upload_tdata(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SellerUploadTDataState.waiting_for_tdata_zip)
    text = (
        "📁 <b>Загрузка аккаунта в формате Tdata (Telegram Desktop)</b>\n\n"
        "Отправьте боту <b>.zip архив</b>, содержащий папку <code>tdata</code> (с файлами <code>key_datas</code> и сессиями).\n\n"
        "⚡️ Бот автоматически сконвертирует Tdata, проверит валидность сессии и подключит аккаунт к вашему кабинету для полного управления."
    )
    await callback.message.edit_text(text, reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)


@seller_router.message(SellerUploadTDataState.waiting_for_tdata_zip, F.document)
async def process_upload_tdata_doc(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    doc = message.document
    if not doc.file_name or not (doc.file_name.endswith(".zip") or doc.file_name.endswith(".rar")):
        await message.answer("⚠️ Файл должен быть <b>.zip архивом</b> с папкой <code>tdata</code>. Попробуйте снова.")
        return

    status_msg = await message.answer("⏳ Скачиваем Tdata архив и конвертируем...")
    
    file_bytes = io.BytesIO()
    await bot.download(doc, destination=file_bytes)
    file_bytes.seek(0)

    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    # Temporary session destination
    temp_sess_name = f"tdata_temp_{int(time.time())}.session"
    temp_sess_path = SESSIONS_DIR / temp_sess_name

    ok_conv, dc_id, conv_err = convert_tdata_zip_to_session_file(file_bytes, temp_sess_path)
    if not ok_conv or not temp_sess_path.exists():
        await status_msg.edit_text(
            f"❌ <b>Ошибка конвертации Tdata:</b> {conv_err}\n\nУбедитесь, что архив содержит корректную папку <code>tdata</code> с файлом <code>key_datas</code>.",
            reply_markup=cancel_to_seller_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    # Validate session
    await status_msg.edit_text("🔍 Конвертация успешна! Проверяем валидность аккаунта в Telegram...")
    is_valid, user_info, err = await validate_session(temp_sess_path, proxy=proxy_dict)
    if not is_valid or not user_info:
        if temp_sess_path.exists():
            temp_sess_path.unlink()
        await status_msg.edit_text(
            f"❌ <b>Аккаунт невалиден или слетел:</b> {err}\n\nПопробуйте другой Tdata архив.",
            reply_markup=cancel_to_seller_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    phone = user_info.get("phone") or doc.file_name.replace(".zip", "")
    clean_phone = phone.replace("+", "").strip()
    final_session_name = f"{clean_phone}.session"
    final_path = SESSIONS_DIR / final_session_name

    if final_path.exists():
        final_path.unlink()
    temp_sess_path.rename(final_path)

    account = await add_or_update_account(
        phone=phone,
        session_name=final_session_name,
        tg_user_id=user_info.get("tg_user_id"),
        first_name=user_info.get("first_name"),
        last_name=user_info.get("last_name"),
        username=user_info.get("username"),
        dc_id=user_info.get("dc_id") or dc_id,
        status=AccountStatus.ACTIVE,
        proxy_id=active_proxy.id if active_proxy else None,
        owner_tg_id=user_id,
        owner_username=username
    )

    asyncio.create_task(log_account_added(
        bot,
        phone=account.phone,
        method="Tdata (ZIP)",
        owner_id=user_id,
        owner_username=username,
        first_name=user_info.get("first_name")
    ))

    await state.clear()
    await status_msg.edit_text(
        f"🎉 <b>Tdata аккаунт {account.phone} успешно подключен!</b>\n\n"
        f"• Имя: <b>{account.full_name()}</b>\n"
        f"• Username: @{account.username or '—'}\n"
        f"• DC ID: <code>{account.dc_id}</code>\n"
        f"• Статус: 🟢 <b>Активен и готов к управлению</b>",
        parse_mode=ParseMode.HTML
    )

    text, kb = await build_seller_dashboard_view(user_id, bot, page=1)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# 2.2 Upload by Telethon StringSession (Text)
@seller_router.callback_query(F.data == "seller_upload_string_session")
async def cb_upload_string_session(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SellerUploadStringSessionState.waiting_for_string)
    text = (
        "🔑 <b>Подключение аккаунта по Telethon StringSession</b>\n\n"
        "Отправьте боту строку сессии Telethon (начинается с <code>1...</code>):\n\n"
        "<i>Пример:</i> <code>1ApWapzMBu9...</code>"
    )
    await callback.message.edit_text(text, reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)


@seller_router.message(SellerUploadStringSessionState.waiting_for_string, F.text)
async def process_upload_string_session(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    raw_str = message.text.strip()

    status_msg = await message.answer("⏳ Проверяем StringSession и подключаемся к Telegram...")

    try:
        sess = StringSession(raw_str)
        if not sess.auth_key or not sess.auth_key.key or len(sess.auth_key.key) != 256:
            await status_msg.edit_text(
                "❌ <b>Некорректная StringSession:</b> ключ авторизации не распознан.\n\nПроверьте строку и отправьте заново.",
                reply_markup=cancel_to_seller_keyboard(),
                parse_mode=ParseMode.HTML
            )
            return

        temp_name = f"str_temp_{int(time.time())}.session"
        temp_path = SESSIONS_DIR / temp_name
        create_telethon_session_file(temp_path, sess.dc_id or 2, sess.auth_key.key, sess.port or 443)

    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Ошибка разбора StringSession:</b> {e}",
            reply_markup=cancel_to_seller_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    is_valid, user_info, err = await validate_session(temp_path, proxy=proxy_dict)
    if not is_valid or not user_info:
        if temp_path.exists():
            temp_path.unlink()
        await status_msg.edit_text(
            f"❌ <b>Сессия не валидна:</b> {err}\n\nПопробуйте другую строку сессии.",
            reply_markup=cancel_to_seller_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    phone = user_info.get("phone") or f"sess_{int(time.time())}"
    clean_phone = phone.replace("+", "").strip()
    final_session_name = f"{clean_phone}.session"
    final_path = SESSIONS_DIR / final_session_name

    if final_path.exists():
        final_path.unlink()
    temp_path.rename(final_path)

    await state.update_data(
        phone=phone,
        session_name=final_session_name,
        user_info=user_info,
        proxy_id=active_proxy.id if active_proxy else None,
        owner_tg_id=user_id,
        owner_username=username
    )
    await state.set_state(SellerUploadStringSessionState.waiting_for_2fa)

    await status_msg.edit_text(
        f"✅ <b>StringSession валидна!</b>\n\n"
        f"📱 Номер: <code>{phone}</code>\n"
        f"👤 Имя: {user_info.get('first_name') or ''} {user_info.get('last_name') or ''}\n"
        f"🌐 DC: {user_info.get('dc_id')}\n\n"
        "🔐 <b>Укажите 2FA облачный пароль</b> (или отправьте <code>-</code>, если пароля нет):",
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )


@seller_router.message(SellerUploadStringSessionState.waiting_for_2fa)
async def process_string_session_2fa(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    raw_2fa = message.text.strip() if message.text else ""
    two_fa = None if raw_2fa in ("-", "0", "") else raw_2fa

    data = await state.get_data()
    user_info = data.get("user_info", {})
    phone = data.get("phone")
    session_name = data.get("session_name")
    proxy_id = data.get("proxy_id")
    owner_tg_id = data.get("owner_tg_id", user_id)
    owner_username = data.get("owner_username")

    account = await add_or_update_account(
        phone=phone,
        session_name=session_name,
        tg_user_id=user_info.get("tg_user_id"),
        first_name=user_info.get("first_name"),
        last_name=user_info.get("last_name"),
        username=user_info.get("username"),
        dc_id=user_info.get("dc_id"),
        two_fa=two_fa,
        status=AccountStatus.ACTIVE,
        proxy_id=proxy_id,
        owner_tg_id=owner_tg_id,
        owner_username=owner_username
    )

    asyncio.create_task(log_account_added(
        message.bot,
        phone=account.phone,
        method="Telethon StringSession",
        owner_id=owner_tg_id,
        owner_username=owner_username,
        first_name=user_info.get("first_name")
    ))

    await state.clear()
    await message.answer(
        f"🎉 <b>Аккаунт {account.phone} успешно подключен по StringSession!</b>\n\n"
        f"• Статус: 🟢 Валиден\n"
        f"• 2FA: <code>{account.two_fa or 'Не установлен'}</code>\n",
        parse_mode=ParseMode.HTML
    )

    text, kb = await build_seller_dashboard_view(user_id, message.bot, page=1)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# 3. Upload by QR Code
@seller_router.callback_query(F.data == "seller_upload_qr")
async def cb_upload_qr(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id if callback.from_user else 0
    username = callback.from_user.username if callback.from_user else None
    await state.clear()

    await callback.answer("Генерируем QR-код...")
    status_msg = await callback.message.answer("⏳ <i>Подключаемся к Telegram и генерируем QR-код...</i>", parse_mode=ParseMode.HTML)

    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    success, png_bytes, qr_url, err = await start_qr_login(user_id, proxy=proxy_dict)
    if not success or not png_bytes:
        await status_msg.edit_text(f"❌ Ошибка генерации QR: {err}", reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)
        return

    photo_file = BufferedInputFile(png_bytes, filename="qr_login.png")
    caption_text = (
        "📷 <b>Авторизация по QR-коду</b>\n\n"
        "1. Откройте Telegram на телефоне\n"
        "2. Перейдите в <b>Настройки ➔ Устройства ➔ Подключить устройство</b>\n"
        "3. Наведите камеру на QR-код выше\n\n"
        "<i>Ожидание сканирования...</i>"
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    qr_msg = await callback.message.answer_photo(
        photo=photo_file,
        caption=caption_text,
        reply_markup=cancel_to_seller_keyboard(),
        parse_mode=ParseMode.HTML
    )

    await state.update_data(
        proxy_id=active_proxy.id if active_proxy else None,
        owner_tg_id=user_id,
        owner_username=username,
        qr_msg_id=qr_msg.message_id
    )
    await state.set_state(SellerUploadQRState.waiting_for_scan)

    asyncio.create_task(_qr_wait_worker(user_id, username, qr_msg, callback.message.chat.id, state, bot, active_proxy.id if active_proxy else None))


async def _qr_wait_worker(user_id: int, username: Optional[str], qr_msg: Message, chat_id: int, state: FSMContext, bot: Bot, proxy_id: Optional[int]):
    success, user_info, req_2fa, err = await wait_qr_login_result(user_id, timeout=90)
    if req_2fa:
        await state.set_state(SellerUploadQRState.waiting_for_2fa)
        try:
            await qr_msg.edit_caption(
                caption=(
                    "🔐 <b>QR-код отсканирован!</b>\n\n"
                    "На аккаунте установлен облачный пароль (2FA).\n"
                    "<b>Введите ваш 2FA пароль в ответном сообщении:</b>"
                ),
                reply_markup=cancel_to_seller_keyboard(),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await bot.send_message(
                chat_id=chat_id,
                text="🔐 <b>На аккаунте установлен 2FA пароль.</b>\nВведите ваш пароль двухфакторной аутентификации:",
                reply_markup=cancel_to_seller_keyboard(),
                parse_mode=ParseMode.HTML
            )
    elif success and user_info:
        await add_or_update_account(
            phone=user_info["phone"],
            session_name=user_info["session_name"],
            tg_user_id=user_info.get("tg_user_id"),
            first_name=user_info.get("first_name"),
            last_name=user_info.get("last_name"),
            username=user_info.get("username"),
            dc_id=user_info.get("dc_id"),
            status=AccountStatus.ACTIVE,
            proxy_id=proxy_id,
            owner_tg_id=user_id,
            owner_username=username
        )
        asyncio.create_task(log_account_added(
            bot,
            phone=user_info["phone"],
            method="QR-код",
            owner_id=user_id,
            owner_username=username,
            first_name=user_info.get("first_name")
        ))
        await state.clear()
        try:
            await qr_msg.edit_caption(
                caption=(
                    f"🎉 <b>QR-код успешно отсканирован!</b>\n\n"
                    f"👤 Имя: <b>{user_info.get('first_name')}</b>\n"
                    f"🏷 Username: @{user_info.get('username') or '—'}\n"
                    f"📱 Номер: <code>{user_info.get('phone', 'Скрыт')}</code>"
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        text, kb = await build_seller_dashboard_view(user_id, bot, page=1)
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await state.clear()
        try:
            await qr_msg.edit_caption(
                caption=f"❌ <b>{err or 'Время ожидания QR-кода истекло.'}</b>\nНажмите кнопку ниже, чтобы попробовать снова.",
                reply_markup=cancel_to_seller_keyboard(),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


@seller_router.message(SellerUploadQRState.waiting_for_2fa, F.text)
async def process_qr_2fa(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id if message.from_user else 0
    password = message.text.strip()
    data = await state.get_data()
    proxy_id = data.get("proxy_id")
    owner_tg_id = data.get("owner_tg_id", user_id)
    owner_username = data.get("owner_username")

    status_msg = await message.answer("⏳ Проверяем 2FA пароль...")
    success, user_info, err = await complete_qr_2fa_login(user_id, password)

    if not success or not user_info:
        await status_msg.edit_text(f"❌ {err or 'Неверный 2FA пароль'}\nПопробуйте ввести пароль еще раз:", reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)
        return

    await add_or_update_account(
        phone=user_info["phone"],
        session_name=user_info["session_name"],
        tg_user_id=user_info.get("tg_user_id"),
        first_name=user_info.get("first_name"),
        last_name=user_info.get("last_name"),
        username=user_info.get("username"),
        dc_id=user_info.get("dc_id"),
        two_fa=password,
        status=AccountStatus.ACTIVE,
        proxy_id=proxy_id,
        owner_tg_id=owner_tg_id,
        owner_username=owner_username
    )

    asyncio.create_task(log_account_added(
        bot,
        phone=user_info["phone"],
        method="QR-код + 2FA",
        owner_id=owner_tg_id,
        owner_username=owner_username,
        first_name=user_info.get("first_name")
    ))

    await state.clear()
    await status_msg.edit_text(
        f"🎉 <b>Аккаунт {user_info['phone']} успешно подключен!</b>\n\n"
        f"👤 Имя: <b>{user_info.get('first_name')}</b>\n"
        f"🏷 Username: @{user_info.get('username') or '—'}\n"
        f"📱 Номер: <code>{user_info.get('phone')}</code>\n"
        f"🔐 2FA: <code>{password}</code>",
        parse_mode=ParseMode.HTML
    )
    text, kb = await build_seller_dashboard_view(user_id, bot, page=1)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# 4. Upload by Phone & Code
@seller_router.callback_query(F.data == "seller_upload_phone")
async def cb_upload_phone(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SellerPhoneLoginState.waiting_for_phone)
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    text = (
        f"💼 <b>{user_header}</b>\n\n"
        "🔄 <b>Для подключения аккаунта отправьте боту его номер:</b>\n\n"
        "▪️ На аккаунт будет отправлен код подтверждения для входа\n"
        "▪️ Не подключайте аккаунт, с которого сидите в этом боте\n"
        "▪️ Пример: <code>+79800654632</code>"
    )
    await callback.message.edit_text(text, reply_markup=cancel_to_seller_keyboard(), parse_mode=ParseMode.HTML)
    await callback.answer()


@seller_router.message(SellerPhoneLoginState.waiting_for_phone, F.text)
async def process_phone_input(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    phone = message.text.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = f"+{phone}"

    clean_phone = phone.replace("+", "")
    if not clean_phone.isdigit() or len(clean_phone) < 8:
        await message.answer("⚠️ Неверный формат номера телефона. Пример: <code>+79800654632</code>", parse_mode=ParseMode.HTML)
        return

    status_msg = await message.answer(f"⏳ Отправляем код подтверждения на номер <code>{phone}</code>...")

    session_name = f"{clean_phone}.session"
    session_path = SESSIONS_DIR / session_name

    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    client = create_telethon_client(session_path, proxy_dict)
    try:
        await client.connect()
        send_code_res = await client.send_code_request(phone)
        phone_code_hash = send_code_res.phone_code_hash

        await state.update_data(
            phone=phone,
            session_name=session_name,
            phone_code_hash=phone_code_hash,
            proxy_id=active_proxy.id if active_proxy else None,
            owner_tg_id=user_id,
            owner_username=username
        )
        await state.set_state(SellerPhoneLoginState.waiting_for_code)

        await status_msg.edit_text(
            f"📩 <b>Код подтверждения отправлен в Telegram на номер {phone}!</b>\n\n"
            "Введите полученный 5-значный код (например: <code>12345</code>):",
            reply_markup=cancel_to_seller_keyboard(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error sending code to {phone}: {e}")
        await status_msg.edit_text(f"❌ Ошибка отправки кода: {str(e)}", reply_markup=cancel_to_seller_keyboard())
        await state.clear()
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


@seller_router.message(SellerPhoneLoginState.waiting_for_code, F.text)
async def process_code_input(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    code = message.text.strip().replace(" ", "")
    data = await state.get_data()
    phone = data.get("phone")
    session_name = data.get("session_name")
    phone_code_hash = data.get("phone_code_hash")
    proxy_id = data.get("proxy_id")
    owner_tg_id = data.get("owner_tg_id", user_id)
    owner_username = data.get("owner_username")

    session_path = SESSIONS_DIR / session_name
    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    client = create_telethon_client(session_path, proxy_dict)
    try:
        await client.connect()
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            me = await client.get_me()
            dc_id = client.session.dc_id
            
            await add_or_update_account(
                phone=phone,
                session_name=session_name,
                tg_user_id=me.id,
                first_name=me.first_name,
                last_name=me.last_name,
                username=me.username,
                dc_id=dc_id,
                status=AccountStatus.ACTIVE,
                proxy_id=proxy_id,
                owner_tg_id=owner_tg_id,
                owner_username=owner_username
            )

            asyncio.create_task(log_account_added(
                message.bot,
                phone=phone,
                method="Номер + Код",
                owner_id=owner_tg_id,
                owner_username=owner_username,
                first_name=me.first_name
            ))

            await state.clear()
            await message.answer(f"🎉 <b>Аккаунт {phone} успешно подключен и сохранен!</b>", parse_mode=ParseMode.HTML)
            text, kb = await build_seller_dashboard_view(user_id, message.bot, page=1)
            await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)

        except Exception as e:
            if "password" in str(e).lower() or "SessionPasswordNeededError" in str(type(e)):
                await state.set_state(SellerPhoneLoginState.waiting_for_2fa)
                await message.answer(
                    "🔐 <b>На аккаунте установлен облачный пароль (2FA).</b>\n\n"
                    "Введите пароль двухфакторной аутентификации:",
                    reply_markup=cancel_to_seller_keyboard(),
                    parse_mode=ParseMode.HTML
                )
            else:
                raise e

    except Exception as e:
        logger.error(f"Sign in error: {e}")
        await message.answer(f"❌ Ошибка входа: {str(e)}", reply_markup=cancel_to_seller_keyboard())
        await state.clear()
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


@seller_router.message(SellerPhoneLoginState.waiting_for_2fa, F.text)
async def process_phone_2fa(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else 0
    password = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    session_name = data.get("session_name")
    proxy_id = data.get("proxy_id")
    owner_tg_id = data.get("owner_tg_id", user_id)
    owner_username = data.get("owner_username")

    session_path = SESSIONS_DIR / session_name
    active_proxy = await get_first_active_proxy()
    proxy_dict = active_proxy.to_telethon_dict() if active_proxy else None

    client = create_telethon_client(session_path, proxy_dict)
    try:
        await client.connect()
        await client.sign_in(password=password)
        me = await client.get_me()
        dc_id = client.session.dc_id

        await add_or_update_account(
            phone=phone,
            session_name=session_name,
            tg_user_id=me.id,
            first_name=me.first_name,
            last_name=me.last_name,
            username=me.username,
            dc_id=dc_id,
            two_fa=password,
            status=AccountStatus.ACTIVE,
            proxy_id=proxy_id,
            owner_tg_id=owner_tg_id,
            owner_username=owner_username
        )

        await state.clear()
        await message.answer(
            f"🎉 <b>Аккаунт {phone} успешно авторизован!</b>",
            parse_mode=ParseMode.HTML
        )
        text, kb = await build_seller_dashboard_view(user_id, message.bot, page=1)
        await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"2FA sign in error: {e}")
        await message.answer(f"❌ Неверный 2FA пароль или ошибка: {str(e)}", reply_markup=cancel_to_seller_keyboard())
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# --- Batch Check & Export for this Seller ---

@seller_router.callback_query(F.data == "seller_check_validity")
async def cb_seller_check_validity(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    accounts = await get_all_accounts(owner_tg_id=user_id, include_unassigned=is_admin)
    if not accounts:
        await callback.answer("У вас нет аккаунтов для проверки", show_alert=True)
        return

    await callback.answer("Проверка ваших аккаунтов запущена...")
    status_msg = await callback.message.answer(f"⏳ Проверяем {len(accounts)} аккаунтов...")

    valid_count = 0
    dead_count = 0

    for idx, acc in enumerate(accounts, start=1):
        session_file = get_session_file_path(acc.session_name)
        proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

        is_valid, user_info, err = await validate_session(session_file, proxy=proxy_dict)
        if is_valid and user_info:
            valid_count += 1
            await update_account_info(
                acc.id,
                first_name=user_info.get("first_name"),
                last_name=user_info.get("last_name"),
                username=user_info.get("username"),
                tg_user_id=user_info.get("tg_user_id"),
                dc_id=user_info.get("dc_id"),
                status=AccountStatus.ACTIVE
            )
        else:
            dead_count += 1
            new_st = AccountStatus.BANNED if "заблокирован" in str(err).lower() else AccountStatus.INVALID
            await update_account_status(acc.id, new_st)

    await status_msg.edit_text(
        f"📊 <b>Результат проверки:</b>\n\n"
        f"🟢 Валидных: <b>{valid_count}</b>\n"
        f"🔴 Невалидных / В бане: <b>{dead_count}</b>\n",
        parse_mode=ParseMode.HTML
    )
    text, kb = await build_seller_dashboard_view(user_id, bot, page=1)
    await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data == "seller_export_links")
async def cb_seller_export_links(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    accounts = await get_all_accounts(owner_tg_id=user_id, status=AccountStatus.ACTIVE, include_unassigned=is_admin)
    if not accounts:
        await callback.answer("У вас нет активных аккаунтов для выгрузки", show_alert=True)
        return

    await callback.answer("Генерируем ссылки на выдачу...")
    bot_user = await bot.get_me()

    links_lines = []
    for acc in accounts:
        order = await get_existing_active_link_for_account(acc.id)
        if not order:
            order = await create_order_link(acc.id)
        link = f"https://t.me/{bot_user.username}?start=order_{order.token}"
        links_lines.append(f"{acc.phone} | {link} | 2FA: {acc.two_fa or 'нет'}")

    txt_content = "\n".join(links_lines)
    file_data = txt_content.encode("utf-8")
    doc_file = BufferedInputFile(file_data, filename="my_order_links.txt")

    preview_text = (
        f"📦 <b>Выгрузка ссылок на автовыдачу ({len(accounts)} шт.):</b>\n\n"
        "Файл готов для загрузки в бота магазина."
    )
    await callback.message.answer_document(doc_file, caption=preview_text, parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data == "seller_proxy_menu")
async def cb_seller_proxy_menu(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    proxies = await get_all_proxies()
    first_active = await get_first_active_proxy()
    sel_id = first_active.id if first_active else None

    text = (
        f"💼 <b>{user_header} / Настройка прокси</b>\n\n"
        "Прокси повышают траст аккаунтов и защищают от блокировок.\n\n"
        f"🔸 <b>Текущий прокси:</b> {first_active.to_url() if first_active else 'без прокси'}"
    )
    await callback.message.edit_text(text, reply_markup=proxy_menu_keyboard(proxies, sel_id), parse_mode=ParseMode.HTML)
    await callback.answer()


@seller_router.callback_query(F.data.startswith("acc_proxy:"))
async def cb_acc_proxy(callback: CallbackQuery):
    acc_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    current_p = acc.proxy.to_url() if acc.proxy else "Прямое подключение (без прокси)"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Привязать / Изменить прокси", callback_data=f"acc_set_proxy:{acc_id}"))
    if acc.proxy:
        builder.row(InlineKeyboardButton(text="❌ Отвязать прокси (прямой IP)", callback_data=f"acc_clear_proxy:{acc_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад к аккаунту", callback_data=f"acc_view:{acc_id}"))

    text = (
        f"📡 <b>Настройка прокси для аккаунта {acc.phone}</b>\n\n"
        f"<b>Текущий прокси:</b>\n<code>{current_p}</code>\n\n"
        "💡 <i>Поддерживаются MTProto ссылки (t.me/proxy?...), блоки текста из Telegram, SOCKS5 и HTTP прокси.</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await callback.answer()


@seller_router.callback_query(F.data.startswith("acc_clear_proxy:"))
async def cb_acc_clear_proxy(callback: CallbackQuery):
    acc_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id if callback.from_user else 0
    is_admin = bool(ADMIN_IDS and user_id in ADMIN_IDS)
    acc = await get_account_by_id(acc_id, owner_tg_id=None if is_admin else user_id)
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await update_account_info(acc_id, proxy_id=None)
    await callback.answer("Прокси успешно отвязан", show_alert=True)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Привязать прокси", callback_data=f"acc_set_proxy:{acc_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад к аккаунту", callback_data=f"acc_view:{acc_id}"))
    text = (
        f"📡 <b>Настройка прокси для аккаунта {acc.phone}</b>\n\n"
        "<b>Текущий прокси:</b>\n<code>Прямое подключение (без прокси)</code>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("acc_set_proxy:"))
async def cb_acc_set_proxy(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    await state.set_state(SellerAccountSetProxyState.waiting_for_proxy)
    await state.update_data(proxy_acc_id=acc_id)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"acc_proxy:{acc_id}"))

    text = (
        "🌐 <b>Привязка прокси к аккаунту</b>\n\n"
        "Отправьте прокси в любом удобном виде:\n"
        "• <b>MTProto ссылка:</b>\n<code>https://t.me/proxy?server=...&port=443&secret=...</code>\n"
        "• <b>Текст из настроек Telegram / каналов:</b>\n"
        "<code>Server: ad1.arixo.shop\nPort: 443\nSecret: ee609a...</code>\n"
        "• <b>SOCKS5 / HTTP:</b>\n<code>socks5://user:pass@ip:port</code> или <code>ip:port:user:pass</code>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await callback.answer()


@seller_router.message(SellerAccountSetProxyState.waiting_for_proxy, F.text)
async def process_account_set_proxy(message: Message, state: FSMContext):
    raw_str = message.text.strip()
    data = await state.get_data()
    acc_id = data.get("proxy_acc_id")

    parsed = parse_proxy_string(raw_str)
    if not parsed:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"acc_proxy:{acc_id}"))
        await message.answer(
            "⚠️ <b>Не удалось распознать формат прокси.</b>\n"
            "Поддерживаются ссылки <code>https://t.me/proxy?...</code>, блоки текста <code>Server: ... Port: ... Secret: ...</code> и строки <code>ip:port:user:pass</code>.\n\n"
            "Попробуйте отправить еще раз:",
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        return

    proto, host, port, user, pwd = parsed
    status_msg = await message.answer("⏳ Тестируем соединение с прокси...")
    
    is_ok, msg = await test_proxy_connection(proto, host, port, user, pwd)
    proxy_obj = await add_proxy(proto, host, port, user, pwd)
    await update_account_info(acc_id, proxy_id=proxy_obj.id)
    await state.clear()
    
    target_acc = await get_account_by_id(acc_id)
    asyncio.create_task(log_proxy_added(
        message.bot,
        proxy_url=proxy_obj.to_url(),
        is_active=is_ok,
        phone=target_acc.phone if target_acc else None,
        user_id=message.from_user.id if message.from_user else None,
        username=message.from_user.username if message.from_user else None
    ))

    status_text = "✅ <b>Прокси успешно привязан и работает!</b>" if is_ok else f"⚠️ <b>Прокси привязан, но тест вернул предупреждение:</b>\n{msg}"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⚙️ К аккаунту", callback_data=f"acc_view:{acc_id}"))
    builder.row(InlineKeyboardButton(text="🏠 В главное меню", callback_data="seller_main_menu"))
    
    await status_msg.edit_text(
        f"{status_text}\n\n<b>Прокси:</b>\n<code>{proxy_obj.to_url()}</code>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )


# --- Global / Seller Proxy Management Handlers ---

@seller_router.callback_query(F.data == "proxy_add")
async def cb_proxy_add_seller(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SellerProxyAddState.waiting_for_proxy_string)
    text = (
        "🌐 <b>Добавление прокси</b>\n\n"
        "Отправьте прокси в любом формате (можно одну строку или список с новой строки):\n\n"
        "• <b>ip:port:user:pass</b> <i>(или ip:port:login:password)</i>\n"
        "• <b>user:pass@ip:port</b>\n"
        "• <b>socks5://... или http://...</b>\n"
        "• <b>MTProto ссылка:</b> <code>https://t.me/proxy?server=...&port=443&secret=...</code>\n\n"
        "<i>Пример:</i>\n<code>185.162.228.11:10001:user123:pass456</code>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="seller_proxy_menu"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@seller_router.message(SellerProxyAddState.waiting_for_proxy_string, F.text)
async def process_seller_proxy_input(message: Message, state: FSMContext):
    raw_lines = [line.strip() for line in message.text.split("\n") if line.strip()]
    if not raw_lines:
        await message.answer("⚠️ Введите строку с прокси.")
        return

    status_msg = await message.answer(f"⏳ Проверяем {len(raw_lines)} прокси...")
    added_count = 0
    failed_count = 0
    results_text = []

    for line in raw_lines:
        parsed = parse_proxy_string(line)
        if not parsed:
            failed_count += 1
            results_text.append(f"❌ <code>{line[:30]}...</code> — неверный формат")
            continue

        proto, host, port, user, pwd = parsed
        is_ok, msg, detected_proto = await test_proxy_connection(proto, host, port, user, pwd)
        proxy_obj = await add_proxy(detected_proto, host, port, user, pwd)
        await update_proxy_status(proxy_obj.id, is_active=is_ok, protocol=detected_proto)
        
        asyncio.create_task(log_proxy_added(
            message.bot,
            proxy_url=proxy_obj.to_url(),
            is_active=is_ok,
            user_id=message.from_user.id if message.from_user else None,
            username=message.from_user.username if message.from_user else None
        ))

        if is_ok:
            added_count += 1
            results_text.append(f"✅ <b>{detected_proto.upper()}</b> <code>{proxy_obj.to_url()}</code>")
        else:
            added_count += 1
            results_text.append(f"⚠️ <code>{proxy_obj.to_url()}</code> ({msg})")

    await state.clear()
    proxies = await get_all_proxies()
    first_active = await get_first_active_proxy()
    sel_id = first_active.id if first_active else None

    summary = (
        f"📊 <b>Результат добавления прокси:</b>\n"
        f"• Добавлено: <b>{added_count}</b>\n"
        f"• Ошибок формата: <b>{failed_count}</b>\n\n"
        + "\n".join(results_text[:10])
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌐 Перейти в меню прокси", callback_data="seller_proxy_menu"))
    builder.row(InlineKeyboardButton(text="🏠 В главное меню", callback_data="seller_main_menu"))
    await status_msg.edit_text(summary, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("proxy_view:"))
async def cb_proxy_view(callback: CallbackQuery):
    await callback.answer()
    p_id = int(callback.data.split(":")[1])
    proxy_obj = await get_proxy_by_id(p_id)
    if not proxy_obj:
        await callback.message.answer("⚠️ Прокси не найден.")
        return

    status_icon = "🟢 Активен / Работает" if proxy_obj.is_active else "🔴 Не отвечает / Ошибка"
    auth_info = f"<code>{proxy_obj.username}:{proxy_obj.password}</code>" if proxy_obj.username else "Без авторизации"

    text = (
        f"📡 <b>Информация о прокси #{proxy_obj.id}:</b>\n\n"
        f"• <b>Протокол:</b> <code>{proxy_obj.protocol.upper()}</code>\n"
        f"• <b>Хост и порт:</b> <code>{proxy_obj.host}:{proxy_obj.port}</code>\n"
        f"• <b>Авторизация:</b> {auth_info}\n"
        f"• <b>Статус:</b> {status_icon}\n"
        f"• <b>Полная ссылка:</b>\n<code>{proxy_obj.to_url()}</code>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Проверить соединение", callback_data=f"proxy_retest:{p_id}"))
    if not proxy_obj.is_active:
        builder.row(InlineKeyboardButton(text="⭐️ Сделать по умолчанию", callback_data=f"proxy_set_default:{p_id}"))
    else:
        builder.row(InlineKeyboardButton(text="✅ Установлен по умолчанию", callback_data="seller_page_noop"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить прокси", callback_data=f"proxy_del:{p_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад к списку", callback_data="seller_proxy_menu"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("proxy_retest:"))
async def cb_proxy_retest(callback: CallbackQuery):
    await callback.answer("Тестируем соединение...")
    p_id = int(callback.data.split(":")[1])
    proxy_obj = await get_proxy_by_id(p_id)
    if not proxy_obj:
        await callback.message.answer("⚠️ Прокси не найден.")
        return

    is_ok, msg, detected_proto = await test_proxy_connection(
        proxy_obj.protocol,
        proxy_obj.host,
        proxy_obj.port,
        proxy_obj.username,
        proxy_obj.password
    )
    await update_proxy_status(p_id, is_active=is_ok, protocol=detected_proto)
    
    alert_text = f"✅ Прокси работает! ({detected_proto.upper()})" if is_ok else f"❌ Ошибка: {msg}"
    await callback.answer(alert_text, show_alert=True)
    
    # Refresh view
    callback.data = f"proxy_view:{p_id}"
    await cb_proxy_view(callback)


@seller_router.callback_query(F.data.startswith("proxy_set_default:"))
async def cb_proxy_set_default(callback: CallbackQuery):
    p_id = int(callback.data.split(":")[1])
    await set_active_proxy(p_id)
    await callback.answer("⭐️ Прокси установлен по умолчанию для новых аккаунтов!", show_alert=True)
    proxies = await get_all_proxies()
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    first_active = await get_first_active_proxy()
    text = (
        f"💼 <b>{user_header} / Настройка прокси</b>\n\n"
        "Прокси повышают траст аккаунтов и защищают от блокировок.\n\n"
        f"🔸 <b>Текущий прокси:</b> {first_active.to_url() if first_active else 'без прокси'}"
    )
    await callback.message.edit_text(text, reply_markup=proxy_menu_keyboard(proxies, p_id), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data == "proxy_select_none")
async def cb_proxy_select_none(callback: CallbackQuery):
    await set_active_proxy(None)
    await callback.answer("Работаем напрямую без прокси", show_alert=True)
    proxies = await get_all_proxies()
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    text = (
        f"💼 <b>{user_header} / Настройка прокси</b>\n\n"
        "Прокси повышают траст аккаунтов и защищают от блокировок.\n\n"
        "🔸 <b>Текущий прокси:</b> без прокси (прямое подключение)"
    )
    await callback.message.edit_text(text, reply_markup=proxy_menu_keyboard(proxies, None), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data == "proxy_test_all")
async def cb_proxy_test_all(callback: CallbackQuery):
    await callback.answer("Проверяем все прокси...")
    proxies = await get_all_proxies()
    if not proxies:
        await callback.answer("Список прокси пуст", show_alert=True)
        return

    status_msg = await callback.message.answer("⏳ Тестируем все прокси из базы...")
    for p in proxies:
        is_ok, _, detected_proto = await test_proxy_connection(p.protocol, p.host, p.port, p.username, p.password)
        await update_proxy_status(p.id, is_active=is_ok, protocol=detected_proto)

    await status_msg.delete()
    proxies = await get_all_proxies()
    first_active = await get_first_active_proxy()
    sel_id = first_active.id if first_active else None
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    text = (
        f"💼 <b>{user_header} / Настройка прокси</b>\n\n"
        "Прокси повышают траст аккаунтов и защищают от блокировок.\n\n"
        f"🔸 <b>Текущий прокси:</b> {first_active.to_url() if first_active else 'без прокси'}"
    )
    await callback.message.edit_text(text, reply_markup=proxy_menu_keyboard(proxies, sel_id), parse_mode=ParseMode.HTML)


@seller_router.callback_query(F.data.startswith("proxy_del:"))
async def cb_proxy_del(callback: CallbackQuery):
    p_id = int(callback.data.split(":")[1])
    await delete_proxy(p_id)
    await callback.answer("Прокси удален", show_alert=True)
    proxies = await get_all_proxies()
    first_active = await get_first_active_proxy()
    sel_id = first_active.id if first_active else None
    user_id = callback.from_user.id if callback.from_user else 0
    user_header = await get_user_display_header(user_id)
    text = (
        f"💼 <b>{user_header} / Настройка прокси</b>\n\n"
        "Прокси повышают траст аккаунтов и защищают от блокировок.\n\n"
        f"🔸 <b>Текущий прокси:</b> {first_active.to_url() if first_active else 'без прокси'}"
    )
    await callback.message.edit_text(text, reply_markup=proxy_menu_keyboard(proxies, sel_id), parse_mode=ParseMode.HTML)
