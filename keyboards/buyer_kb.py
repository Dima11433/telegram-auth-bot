from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import WEB_BASE_URL

def buyer_order_keyboard(token: str) -> InlineKeyboardMarkup:
    """
    Main actions keyboard for buyer on the account card.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📩 Получить код", callback_data=f"buyer_get_code:{token}"),
        ],
        [
            InlineKeyboardButton(text="⏳ Ожидать код онлайн", callback_data=f"buyer_wait_code:{token}"),
        ],
        [
            InlineKeyboardButton(text="🚪 Выйти ботом с аккаунта", callback_data=f"buyer_logout_bot:{token}"),
        ],
        [
            InlineKeyboardButton(text="📁 Скачать Tdata (ZIP)", callback_data=f"buyer_download_tdata:{token}"),
            InlineKeyboardButton(text="📄 Скачать .session", callback_data=f"buyer_download_session:{token}"),
        ],
        [
            InlineKeyboardButton(text="📖 Инструкция", callback_data=f"buyer_help:{token}"),
            InlineKeyboardButton(text="🔄 Обновить статус", callback_data=f"buyer_refresh:{token}"),
        ]
    ])

def buyer_back_keyboard(token: str) -> InlineKeyboardMarkup:
    """
    Back to order card button.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Вернуться к аккаунту", callback_data=f"buyer_refresh:{token}")
        ]
    ])

def buyer_faq_menu_keyboard(token: str) -> InlineKeyboardMarkup:
    """
    Interactive FAQ sections menu.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Вход по коду и номеру", callback_data=f"buyer_faq:login:{token}"),
        ],
        [
            InlineKeyboardButton(text="📁 Вход через Tdata (ПК)", callback_data=f"buyer_faq:tdata:{token}"),
        ],
        [
            InlineKeyboardButton(text="🌐 Настройка Прокси (Proxy)", callback_data=f"buyer_faq:proxy:{token}"),
        ],
        [
            InlineKeyboardButton(text="🚪 Завершение сессии бота", callback_data=f"buyer_faq:security:{token}"),
        ],
        [
            InlineKeyboardButton(text="📄 Использование .session", callback_data=f"buyer_faq:session:{token}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Вернуться к аккаунту", callback_data=f"buyer_refresh:{token}"),
        ]
    ])

def buyer_faq_back_keyboard(token: str) -> InlineKeyboardMarkup:
    """
    Navigation inside an FAQ subsection.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 К разделам FAQ", callback_data=f"buyer_help:{token}"),
            InlineKeyboardButton(text="⬅️ К аккаунту", callback_data=f"buyer_refresh:{token}")
        ]
    ])

def buyer_cancel_wait_keyboard(token: str) -> InlineKeyboardMarkup:
    """
    Cancel live waiting button.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📩 Проверить код прямо сейчас", callback_data=f"buyer_get_code:{token}")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"buyer_refresh:{token}")
        ]
    ])
