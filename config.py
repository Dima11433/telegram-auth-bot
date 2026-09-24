import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Telegram Bot API Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Telegram MTProto API Credentials (my.telegram.org)
# By default, we provide a valid fallback Telegram Android/Desktop official API ID & Hash if not configured in .env
API_ID = int(os.getenv("API_ID", "2040"))
API_HASH = os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627")

# Administrator Telegram IDs (separated by comma, e.g. "123456789,987654321")
raw_admin_ids = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip().isdigit()]

# Log Channel / Group ID for real-time event logs
raw_log_channel = os.getenv("LOG_CHANNEL_ID", "")
try:
    LOG_CHANNEL_ID = int(raw_log_channel.strip()) if raw_log_channel and raw_log_channel.strip() else None
except Exception:
    LOG_CHANNEL_ID = None

# Web Client Server Configuration
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
WEB_BASE_URL = os.getenv("WEB_BASE_URL", f"http://localhost:{WEB_PORT}").rstrip("/")

# Data directory (supports Railway Persistent Volume e.g. /data)
DATA_DIR_PATH = os.getenv("DATA_DIR", "")
DATA_DIR = Path(DATA_DIR_PATH).resolve() if DATA_DIR_PATH else BASE_DIR

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR / 'database.sqlite3'}")

# Sessions directory
SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Code retrieval timeout in seconds
CODE_WAIT_TIMEOUT = int(os.getenv("CODE_WAIT_TIMEOUT", "90"))

# Default instructions text shown to the buyer
DEFAULT_BUYER_INSTRUCTION = (
    "<b>📖 Инструкция по авторизации в аккаунт:</b>\n\n"
    "1. Откройте официальный клиент Telegram (Desktop, мобильное приложение или Telegram Web).\n"
    "2. Нажмите <b>Войти по номеру телефона</b> и введите номер аккаунта выше.\n"
    "3. После отправки запроса в Telegram нажмите кнопку <b>«📩 Получить код»</b> в этом боте.\n"
    "4. Бот моментально пришлет полученный 5-значный код подтверждения.\n"
    "5. Если на аккаунте установлен облачный пароль (2FA) — введите указанный в карточке пароль.\n"
    "6. После успешного входа вы можете нажать <b>«🔄 Завершить другие сессии»</b> для безопасности."
)
