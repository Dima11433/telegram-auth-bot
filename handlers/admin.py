import os
import io
import logging
import asyncio
from pathlib import Path
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from config import SESSIONS_DIR, ADMIN_IDS
from utils.filters import IsAdmin
from database.models import AccountStatus, Account, Proxy
from database.db import (
    get_accounts_list,
    get_all_accounts,
    get_account_by_id,
    update_account_status,
    update_account_info,
    create_order_link,
    get_existing_active_link_for_account,
    get_all_proxies,
    add_proxy,
    delete_proxy,
    get_first_active_proxy,
    count_unique_sellers
)
from services.session_manager import (
    validate_session,
    get_session_file_path,
    get_latest_login_code
)
from services.proxy_manager import parse_proxy_string, test_proxy_connection
from services.log_notifier import log_proxy_added
from keyboards.admin_kb import (
    superadmin_dashboard_keyboard,
    proxy_menu_keyboard,
    cancel_to_superadmin_keyboard
)

logger = logging.getLogger(__name__)
admin_router = Router(name="superadmin")
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())

class SuperadminProxyAddState(StatesGroup):
    waiting_for_proxy_string = State()


from utils.country_detector import group_accounts_by_country, get_country_info


async def build_superadmin_dashboard_view(bot: Bot, country_code: Optional[str] = None, page: int = 1, limit: int = 6):
    all_accs = await get_all_accounts()
    total_count = len(all_accs)
    total_sellers = await count_unique_sellers()
    active_count = sum(1 for a in all_accs if a.status == AccountStatus.ACTIVE)
    issued_count = sum(1 for a in all_accs if a.status == AccountStatus.ISSUED)
    invalid_count = sum(1 for a in all_accs if a.status in (AccountStatus.INVALID, AccountStatus.BANNED, AccountStatus.ERROR))

    country_groups = group_accounts_by_country(all_accs)
    builder = InlineKeyboardBuilder()

    if country_code is None:
        text = (
            "👑 <b>Панель Администратора (Вся база)</b>\n\n"
            "📊 <b>Общая статистика платформы:</b>\n"
            f"• Всего аккаунтов в базе: <code>{total_count}</code>\n"
            f"• Всего продавцов/пользователей: <code>{total_sellers}</code>\n"
            f"• Доступных: <code>{active_count}</code> | Выданных: <code>{issued_count}</code>\n"
            f"• Невалид / Бан: <code>{invalid_count}</code>\n\n"
        )

        if not all_accs:
            text += "<i>В базе пока нет аккаунтов.</i>"
        else:
            text += "📁 <b>Выберите категорию (страну) базы:</b>"
            for c_code, grp in country_groups.items():
                info = grp["info"]
                cnt = len(grp["accounts"])
                btn_text = f"{info['flag']} {info['name']} ({info['prefix']}) — {cnt} шт."
                builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"superadmin_country:{c_code}:1"))

            if len(country_groups) > 1:
                builder.row(InlineKeyboardButton(text=f"📋 Все страны ({total_count} шт.)", callback_data="superadmin_country:ALL:1"))

        # Global control buttons
        builder.row(InlineKeyboardButton(text="🔄 Проверить ВСЕ аккаунты", callback_data="superadmin_check_all"))
        builder.row(InlineKeyboardButton(text="📦 Выгрузить ВСЕ ссылки", callback_data="superadmin_export_all"))
        builder.row(
            InlineKeyboardButton(text="🌐 Настройка прокси", callback_data="admin_proxy_menu"),
            InlineKeyboardButton(text="📊 Детальная статистика", callback_data="admin_stats")
        )
        builder.row(InlineKeyboardButton(text="🏠 В мой личный кабинет", callback_data="seller_main_menu"))

        return text, builder.as_markup()

    else:
        if country_code == "ALL":
            target_accs = all_accs
            country_title = f"📋 <b>Все аккаунты базы ({len(target_accs)} шт.)</b>"
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
            f"👑 <b>Панель Администратора</b>\n\n"
            f"{country_title}\n\n"
        )

        if not paged_accs:
            text += "<i>В этой категории пока нет аккаунтов.</i>"
        else:
            text += "<i>Выберите аккаунт для управления:</i>"

        for acc in paged_accs:
            status_icon = "🟢" if acc.status == AccountStatus.ACTIVE else ("🔵" if acc.status == AccountStatus.ISSUED else "🔴")
            owner_tag = f"@{acc.owner_username}" if acc.owner_username else f"ID:{acc.owner_tg_id or 'admin'}"
            btn_text = f"{status_icon} {acc.phone} ({owner_tag})"
            builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"acc_view:{acc.id}"))

        # Pagination row
        if total_pages > 1:
            prev_p = max(1, page - 1)
            next_p = min(total_pages, page + 1)
            builder.row(
                InlineKeyboardButton(text="⏮", callback_data=f"superadmin_country:{country_code}:1"),
                InlineKeyboardButton(text="◀️", callback_data=f"superadmin_country:{country_code}:{prev_p}"),
                InlineKeyboardButton(text=f"{page} из {total_pages}", callback_data="admin_page_noop"),
                InlineKeyboardButton(text="▶️", callback_data=f"superadmin_country:{country_code}:{next_p}"),
                InlineKeyboardButton(text="⏭", callback_data=f"superadmin_country:{country_code}:{total_pages}"),
            )

        builder.row(InlineKeyboardButton(text="🔙 Назад к категориям базы", callback_data="admin_global_menu"))
        builder.row(InlineKeyboardButton(text="🏠 В мой личный кабинет", callback_data="seller_main_menu"))

        return text, builder.as_markup()


@admin_router.message(Command("admin"))
async def cmd_superadmin(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    text, kb = await build_superadmin_dashboard_view(bot, country_code=None, page=1)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_global_menu")
async def cb_admin_global_menu(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.clear()
    text, kb = await build_superadmin_dashboard_view(bot, country_code=None, page=1)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data.startswith("superadmin_country:"))
async def cb_superadmin_country(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    parts = callback.data.split(":")
    country_code = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 1
    text, kb = await build_superadmin_dashboard_view(bot, country_code=country_code, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass


@admin_router.callback_query(F.data.startswith("superadmin_page:"))
async def cb_superadmin_page(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    page = int(callback.data.split(":")[1])
    text, kb = await build_superadmin_dashboard_view(bot, country_code=None, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass


@admin_router.callback_query(F.data == "superadmin_check_all")
async def cb_superadmin_check_all(callback: CallbackQuery, bot: Bot):
    accounts = await get_all_accounts()
    if not accounts:
        await callback.answer("База пуста", show_alert=True)
        return

    await callback.answer("Запущена глобальная проверка всех аккаунтов...")
    status_msg = await callback.message.answer(f"⏳ Проверяем {len(accounts)} аккаунтов со всей базы...")

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
        f"📊 <b>Результат глобальной проверки:</b>\n\n"
        f"🟢 Валидных: <b>{valid_count}</b>\n"
        f"🔴 Невалидных / В бане: <b>{dead_count}</b>\n",
        parse_mode=ParseMode.HTML
    )
    text, kb = await build_superadmin_dashboard_view(bot, page=1)
    await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "superadmin_export_all")
async def cb_superadmin_export_all(callback: CallbackQuery, bot: Bot):
    accounts = await get_all_accounts(status=AccountStatus.ACTIVE)
    if not accounts:
        await callback.answer("Нет активных аккаунтов для выгрузки", show_alert=True)
        return

    await callback.answer("Генерируем ссылки со всей базы...")
    bot_user = await bot.get_me()

    links_lines = []
    for acc in accounts:
        order = await get_existing_active_link_for_account(acc.id)
        if not order:
            order = await create_order_link(acc.id)
        link = f"https://t.me/{bot_user.username}?start=order_{order.token}"
        owner_str = f"Владелец: @{acc.owner_username or 'id'+str(acc.owner_tg_id)}"
        links_lines.append(f"{acc.phone} | {link} | 2FA: {acc.two_fa or 'нет'} | {owner_str}")

    txt_content = "\n".join(links_lines)
    file_data = txt_content.encode("utf-8")
    doc_file = BufferedInputFile(file_data, filename="global_all_orders_export.txt")

    preview_text = (
        f"📦 <b>Полная выгрузка ссылок со всей базы ({len(accounts)} шт.):</b>\n\n"
        "Файл содержит ссылки на все активные аккаунты всех пользователей."
    )
    await callback.message.answer_document(doc_file, caption=preview_text, parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    all_accs = await get_all_accounts()
    active_count = sum(1 for a in all_accs if a.status == AccountStatus.ACTIVE)
    issued_count = sum(1 for a in all_accs if a.status == AccountStatus.ISSUED)
    total_sellers = await count_unique_sellers()
    total = len(all_accs)
    session_files_on_disk = len(list(SESSIONS_DIR.glob("*.session")))

    text = (
        "📊 <b>Детальная статистика всей базы:</b>\n\n"
        f"• Всего аккаунтов в БД: <b>{total}</b>\n"
        f"• Всего пользователей-продавцов: <b>{total_sellers}</b>\n"
        f"• Доступных к продаже: <b>{active_count}</b>\n"
        f"• Выданных заказов: <b>{issued_count}</b>\n"
        f"• Файлов .session на сервере: <b>{session_files_on_disk}</b>\n"
    )
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    await callback.answer()


@admin_router.callback_query(F.data == "admin_proxy_menu")
async def cb_admin_proxy_menu(callback: CallbackQuery):
    proxies = await get_all_proxies()
    first_active = await get_first_active_proxy()
    sel_id = first_active.id if first_active else None

    text = (
        "👑 <b>Глобальная настройка прокси</b>\n\n"
        "Прокси обеспечивают стабильную работу без блокировок по IP.\n\n"
        f"🔸 <b>Выбранный прокси по умолчанию:</b> {first_active.to_url() if first_active else 'без прокси'}"
    )
    await callback.message.edit_text(text, reply_markup=proxy_menu_keyboard(proxies, sel_id), parse_mode=ParseMode.HTML)
    await callback.answer()


@admin_router.callback_query(F.data == "proxy_add")
async def cb_proxy_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SuperadminProxyAddState.waiting_for_proxy_string)
    text = (
        "🌐 <b>Добавление прокси (Глобально)</b>\n\n"
        "Отправьте прокси в любом удобном виде:\n"
        "• <b>MTProto ссылка:</b>\n<code>https://t.me/proxy?server=...&port=443&secret=...</code>\n"
        "• <b>Текст из настроек Telegram / каналов:</b>\n"
        "<code>Server: ad1.arixo.shop\nPort: 443\nSecret: ee609a...</code>\n"
        "• <b>SOCKS5 / HTTP:</b>\n<code>socks5://user:pass@ip:port</code> или <code>ip:port:user:pass</code>"
    )
    await callback.message.edit_text(text, reply_markup=cancel_to_superadmin_keyboard(), parse_mode=ParseMode.HTML)
    await callback.answer()


@admin_router.message(SuperadminProxyAddState.waiting_for_proxy_string, F.text)
async def process_proxy_string(message: Message, state: FSMContext):
    raw_str = message.text.strip()
    parsed = parse_proxy_string(raw_str)
    if not parsed:
        await message.answer(
            "⚠️ <b>Не удалось распознать формат.</b>\n"
            "Поддерживаются ссылки <code>https://t.me/proxy?...</code>, блоки <code>Server: ... Port: ... Secret: ...</code> и строки <code>ip:port:user:pass</code>.\n\n"
            "Попробуйте снова:",
            reply_markup=cancel_to_superadmin_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return

    proto, host, port, user, pwd = parsed
    status_msg = await message.answer("⏳ Тестируем соединение...")
    
    is_ok, msg = await test_proxy_connection(proto, host, port, user, pwd)
    proxy_obj = await add_proxy(proto, host, port, user, pwd)
    await state.clear()
    
    asyncio.create_task(log_proxy_added(
        message.bot,
        proxy_url=proxy_obj.to_url(),
        is_active=is_ok,
        user_id=message.from_user.id if message.from_user else None,
        username=message.from_user.username if message.from_user else None
    ))

    status_text = "✅ Прокси работает!" if is_ok else f"⚠️ Добавлен с ошибкой: {msg}"
    await status_msg.edit_text(f"{status_text}\n<code>{proxy_obj.to_url()}</code>", parse_mode=ParseMode.HTML)
    
    proxies = await get_all_proxies()
    text = f"👑 <b>Глобальная настройка прокси</b>\n\n🔸 <b>Выбран:</b> {proxy_obj.to_url()}"
    await message.answer(text, reply_markup=proxy_menu_keyboard(proxies, proxy_obj.id), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data.startswith("proxy_del:"))
async def cb_proxy_del(callback: CallbackQuery):
    p_id = int(callback.data.split(":")[1])
    await delete_proxy(p_id)
    await callback.answer("Прокси удален", show_alert=True)
    proxies = await get_all_proxies()
    text = "👑 <b>Настройка прокси</b>"
    await callback.message.edit_text(text, reply_markup=proxy_menu_keyboard(proxies, None), parse_mode=ParseMode.HTML)
