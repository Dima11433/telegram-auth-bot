from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional
from database.models import Proxy

def seller_dashboard_keyboard(page: int = 1, total_pages: int = 1, is_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Main dashboard keyboard for sellers:
    - 🔄 Проверить валидность
    - ➕ Залить аккаунты
    - 📦 Выгрузить ссылки
    - 🌐 Настройка прокси
    - (Для админа скрытая кнопка 👑 Админ-панель)
    - Пагинация
    """
    buttons = [
        [
            InlineKeyboardButton(text="🔄 Проверить валидность", callback_data="seller_check_validity"),
        ],
        [
            InlineKeyboardButton(text="➕ Залить аккаунты", callback_data="seller_upload_menu"),
        ],
        [
            InlineKeyboardButton(text="📦 Выгрузить ссылки", callback_data="seller_export_links"),
        ],
        [
            InlineKeyboardButton(text="🌐 Настройка прокси", callback_data="seller_proxy_menu"),
        ]
    ]

    if is_admin:
        buttons.append([
            InlineKeyboardButton(text="👑 Админ-панель (Все аккаунты)", callback_data="admin_global_menu")
        ])

    if total_pages > 1:
        prev_p = max(1, page - 1)
        next_p = min(total_pages, page + 1)
        buttons.append([
            InlineKeyboardButton(text="⏮", callback_data="seller_page:1"),
            InlineKeyboardButton(text="◀️", callback_data=f"seller_page:{prev_p}"),
            InlineKeyboardButton(text=f"{page} из {total_pages}", callback_data="seller_page_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"seller_page:{next_p}"),
            InlineKeyboardButton(text="⏭", callback_data=f"seller_page:{total_pages}"),
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def upload_format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📄 .session файл", callback_data="seller_upload_session"),
            InlineKeyboardButton(text="📁 Tdata (ZIP архив)", callback_data="seller_upload_tdata"),
        ],
        [
            InlineKeyboardButton(text="🔑 StringSession (строка)", callback_data="seller_upload_string_session"),
            InlineKeyboardButton(text="📲 Номер и код", callback_data="seller_upload_phone"),
        ],
        [
            InlineKeyboardButton(text="📷 QR-код", callback_data="seller_upload_qr"),
            InlineKeyboardButton(text="🗂 ZIP с .session файлами", callback_data="seller_upload_zip"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="seller_main_menu")
        ]
    ])


def account_action_keyboard(
    account_id: int,
    share_url: Optional[str] = None,
    web_url: Optional[str] = None,
    back_callback: str = "seller_main_menu"
) -> InlineKeyboardMarkup:
    """
    Matches screenshot 1:
    - 🌐 Войти в Web-клиент (в браузере)
    - 🔄 Проверить | 🗑 Удалить
    - 📩 Получить код авторизации
    - 🔑 Получить Auth Key
    - 📁 Скачать Tdata | 📄 Скачать .session
    - 🔄 Управлять аккаунтом
    - 📢 Поделиться | 📡 Прокси
    - 🔙 Вернуться в меню
    """
    share_btn = (
        InlineKeyboardButton(text="📢 Поделиться", url=f"https://t.me/share/url?url={share_url}")
        if share_url else
        InlineKeyboardButton(text="📢 Поделиться", callback_data=f"acc_share:{account_id}")
    )

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Проверить", callback_data=f"acc_check:{account_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"acc_delete:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📩 Получить код авторизации", callback_data=f"acc_get_code:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔑 Получить Auth Key", callback_data=f"acc_get_authkey:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📁 Скачать Tdata (ZIP)", callback_data=f"acc_download_tdata:{account_id}"),
            InlineKeyboardButton(text="📄 Скачать .session", callback_data=f"acc_download_session:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔄 Управлять аккаунтом", callback_data=f"acc_manage:{account_id}"),
        ],
        [
            share_btn,
            InlineKeyboardButton(text="📡 Прокси", callback_data=f"acc_proxy:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data=back_callback)
        ]
    ])


def invalid_account_keyboard(
    account_id: int,
    back_callback: str = "seller_main_menu"
) -> InlineKeyboardMarkup:
    """
    Keyboard shown when account session is INVALID or BANNED.
    Allows re-uploading a fresh session without deleting the account record.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 Заменить сессию (.session)", callback_data=f"acc_replace_session:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔄 Проверить снова", callback_data=f"acc_check:{account_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"acc_delete:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data=back_callback)
        ]
    ])


def account_management_keyboard(account_id: int, is_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Account management keyboard:
    - 💬 Чаты и Каналы (Only for Admins)
    - 📝 Изменить имя
    - 📝 Изменить фамилию
    - 📝 Изменить 2FA
    - 📧 Изменить / Привязать Email
    - 📝 Изменить @username
    - 📝 Изменить "о себе"
    - 📝 Управление устройствами
    - 🔙 Вернуться назад
    """
    rows = []
    if is_admin:
        rows.append([
            InlineKeyboardButton(text="💬 Чаты и Каналы", callback_data=f"acc_dialogs:{account_id}:all:1"),
        ])
    rows.extend([
        [
            InlineKeyboardButton(text="📝 Изменить имя", callback_data=f"acc_edit_first_name:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📝 Изменить фамилию", callback_data=f"acc_edit_last_name:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📝 Изменить 2FA", callback_data=f"acc_edit_2fa:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📧 Изменить / Привязать Email", callback_data=f"acc_edit_email:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📝 Изменить @username", callback_data=f"acc_edit_username:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📝 Изменить \"о себе\"", callback_data=f"acc_edit_bio:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="📝 Управление устройствами", callback_data=f"acc_devices:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Вернуться назад", callback_data=f"acc_view:{account_id}")
        ]
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_dialogs_keyboard(
    account_id: int,
    dialogs: list,
    page: int = 1,
    total_pages: int = 1,
    filter_type: str = "all"
) -> InlineKeyboardMarkup:
    buttons = []

    # Quick Access row
    buttons.append([
        InlineKeyboardButton(text="⭐️ Избранное (Saved Messages)", callback_data=f"acc_saved_messages:{account_id}"),
        InlineKeyboardButton(text="🔍 Поиск (@ / Текст)", callback_data=f"acc_search_chats:{account_id}")
    ])

    # Filter tabs
    f_all = "• Все •" if filter_type == "all" else "Все"
    f_user = "• 👤 ЛС •" if filter_type == "user" else "👤 ЛС"
    f_grp = "• 👥 Группы •" if filter_type == "group" else "👥 Группы"
    f_chn = "• 📢 Каналы •" if filter_type == "channel" else "📢 Каналы"
    f_bot = "• 🤖 Боты •" if filter_type == "bot" else "🤖 Боты"

    buttons.append([
        InlineKeyboardButton(text=f_all, callback_data=f"acc_dialogs:{account_id}:all:1"),
        InlineKeyboardButton(text=f_user, callback_data=f"acc_dialogs:{account_id}:user:1"),
        InlineKeyboardButton(text=f_grp, callback_data=f"acc_dialogs:{account_id}:group:1"),
    ])
    buttons.append([
        InlineKeyboardButton(text=f_chn, callback_data=f"acc_dialogs:{account_id}:channel:1"),
        InlineKeyboardButton(text=f_bot, callback_data=f"acc_dialogs:{account_id}:bot:1"),
    ])

    # Dialog items
    type_icons = {
        "user": "👤",
        "bot": "🤖",
        "group": "👥",
        "channel": "📢"
    }

    for d in dialogs:
        icon = type_icons.get(d.get("type"), "💬")
        unread = f" [{d.get('unread_count')}]" if d.get("unread_count") else ""
        title_snippet = d.get("title", "")[:22]
        btn_text = f"{icon} {title_snippet}{unread}"
        buttons.append([
            InlineKeyboardButton(text=btn_text, callback_data=f"acc_open_chat:{account_id}:{d.get('id')}")
        ])

    # Action row
    buttons.append([
        InlineKeyboardButton(text="➕ Вступить по ссылке / @", callback_data=f"acc_join_chat:{account_id}")
    ])

    # Pagination row
    if total_pages > 1:
        prev_p = max(1, page - 1)
        next_p = min(total_pages, page + 1)
        buttons.append([
            InlineKeyboardButton(text="⏮", callback_data=f"acc_dialogs:{account_id}:{filter_type}:1"),
            InlineKeyboardButton(text="◀️", callback_data=f"acc_dialogs:{account_id}:{filter_type}:{prev_p}"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="acc_dialogs_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"acc_dialogs:{account_id}:{filter_type}:{next_p}"),
            InlineKeyboardButton(text="⏭", callback_data=f"acc_dialogs:{account_id}:{filter_type}:{total_pages}"),
        ])

    buttons.append([
        InlineKeyboardButton(text="🔙 В управление аккаунтом", callback_data=f"acc_manage:{account_id}")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def chat_actions_keyboard(
    account_id: int,
    chat_id: int,
    offset_id: int = 0,
    oldest_msg_id: int = 0,
    photo_msg_ids: Optional[list] = None,
    is_bot: bool = False,
    bot_buttons: Optional[list] = None,
    reply_buttons: Optional[list] = None,
    is_saved: bool = False
) -> InlineKeyboardMarkup:
    buttons = []

    # Main action row
    action_row = [
        InlineKeyboardButton(text="✉️ Написать текст / сумму", callback_data=f"chat_send_msg:{account_id}:{chat_id}")
    ]
    if is_bot:
        action_row.append(InlineKeyboardButton(text="🚀 Запустить /start", callback_data=f"chat_send_start:{account_id}:{chat_id}"))
    buttons.append(action_row)

    # Bot persistent reply keyboard buttons (e.g. [👛 Кошелек], [💳 Чеки] from CryptoBot)
    if reply_buttons:
        for r_idx, row in enumerate(reply_buttons):
            row_btns = []
            for c_idx, btn_text in enumerate(row):
                row_btns.append(InlineKeyboardButton(
                    text=f"⌨️ {btn_text[:25]}",
                    callback_data=f"bot_rbtn:{account_id}:{chat_id}:{r_idx}_{c_idx}"
                ))
            if row_btns:
                buttons.append(row_btns)

    # Interactive bot inline keyboard buttons (if present in the latest message)
    if bot_buttons:
        for row in bot_buttons:
            row_btns = []
            for b in row:
                btn_text = b['text']
                btn_url = b.get("url")
                if b.get("is_url") and btn_url and (btn_url.startswith("http://") or btn_url.startswith("https://") or btn_url.startswith("tg://")):
                    row_btns.append(InlineKeyboardButton(
                        text=f"🔗 {btn_text}",
                        url=btn_url
                    ))
                else:
                    row_btns.append(InlineKeyboardButton(
                        text=f"🔘 {btn_text}",
                        callback_data=f"bot_btn:{account_id}:{chat_id}:{b.get('msg_id', 0)}:{b['row']}_{b['col']}"
                    ))
            if row_btns:
                buttons.append(row_btns)

    # Photos view row (if any messages on current screen have photo/media)
    if photo_msg_ids:
        photo_row = []
        for p_id in photo_msg_ids[:3]:
            photo_row.append(InlineKeyboardButton(
                text=f"🖼 Посмотреть фото #{p_id}",
                callback_data=f"chat_photo:{account_id}:{chat_id}:{p_id}"
            ))
        buttons.append(photo_row)

    # History pagination row
    nav_row = []
    if oldest_msg_id > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Ранее (История)", callback_data=f"chat_history:{account_id}:{chat_id}:{oldest_msg_id}"))
    if offset_id > 0:
        nav_row.append(InlineKeyboardButton(text="🔄 В начало", callback_data=f"acc_open_chat:{account_id}:{chat_id}"))
    else:
        nav_row.append(InlineKeyboardButton(text="🔄 Обновить", callback_data=f"acc_open_chat:{account_id}:{chat_id}"))
    buttons.append(nav_row)

    # Bottom control row
    bottom_row = []
    if not is_saved:
        bottom_row.append(InlineKeyboardButton(text="🚪 Покинуть чат", callback_data=f"chat_leave:{account_id}:{chat_id}"))
    bottom_row.append(InlineKeyboardButton(text="⬅️ К списку чатов", callback_data=f"acc_dialogs:{account_id}:all:1"))
    buttons.append(bottom_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_to_chat_keyboard(account_id: int, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"acc_open_chat:{account_id}:{chat_id}")
        ]
    ])


def cancel_to_dialogs_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"acc_dialogs:{account_id}:all:1")
        ]
    ])


def devices_management_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Завершить все остальные сессии", callback_data=f"acc_term_all:{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в управление", callback_data=f"acc_manage:{account_id}")
        ]
    ])


def cancel_to_seller_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="seller_main_menu")
        ]
    ])


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
        InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="seller_main_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
