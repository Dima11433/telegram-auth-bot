from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional
from database.models import Account, Proxy

def superadmin_dashboard_keyboard(page: int = 1, total_pages: int = 1) -> InlineKeyboardMarkup:
    """
    Superadmin global dashboard keyboard:
    - 🔄 Проверить ВСЕ аккаунты
    - 📦 Выгрузить ВСЕ ссылки
    - 🌐 Глобальные прокси
    - 📊 Полная статистика базы
    - 🏠 Вернуться в личный кабинет
    - Пагинация
    """
    buttons = [
        [
            InlineKeyboardButton(text="🔄 Проверить ВСЕ аккаунты", callback_data="superadmin_check_all"),
        ],
        [
            InlineKeyboardButton(text="📦 Выгрузить ВСЕ ссылки", callback_data="superadmin_export_all"),
        ],
        [
            InlineKeyboardButton(text="🌐 Настройка прокси", callback_data="admin_proxy_menu"),
            InlineKeyboardButton(text="📊 Статистика сервиса", callback_data="admin_stats"),
        ],
        [
            InlineKeyboardButton(text="🏠 В мой личный кабинет", callback_data="seller_main_menu"),
        ]
    ]

    if total_pages > 1:
        prev_p = max(1, page - 1)
        next_p = min(total_pages, page + 1)
        buttons.append([
            InlineKeyboardButton(text="⏮", callback_data="superadmin_page:1"),
            InlineKeyboardButton(text="◀️", callback_data=f"superadmin_page:{prev_p}"),
            InlineKeyboardButton(text=f"{page} из {total_pages}", callback_data="admin_page_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"superadmin_page:{next_p}"),
            InlineKeyboardButton(text="⏭", callback_data=f"superadmin_page:{total_pages}"),
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxy_menu_keyboard(proxies: List[Proxy], selected_proxy_id: Optional[int] = None) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        status_icon = "🟩" if p.is_active else "🟥"
        is_selected = " [Выбран]" if selected_proxy_id == p.id else ""
        text = f"{status_icon} {p.protocol.upper()} {p.host}:{p.port}{is_selected}"
        buttons.append([
            InlineKeyboardButton(text=text, callback_data=f"proxy_view:{p.id}")
        ])

    buttons.append([
        InlineKeyboardButton(text="➕ Добавить прокси", callback_data="proxy_add"),
        InlineKeyboardButton(text="🔄 Проверить все", callback_data="proxy_test_all"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🔑 Работать без прокси", callback_data="proxy_select_none")
    ])
    buttons.append([
        InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="admin_global_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_to_superadmin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_global_menu")
        ]
    ])
