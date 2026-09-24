import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, SESSIONS_DIR, ADMIN_IDS
from database.db import init_db, sync_sessions_from_disk
from handlers import buyer_router, admin_router, seller_router, common_router

# Setup UTF-8 encoding for Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

async def main():
    if not BOT_TOKEN:
        logger.error("❌ ОШИБКА: BOT_TOKEN не установлен в файле .env!")
        print("\n" + "="*60)
        print("❗ ВНИМАНИЕ: Укажите ваш BOT_TOKEN в файле .env (или скопируйте .env.example -> .env)")
        print("="*60 + "\n")
        return

    logger.info("Инициализация базы данных...")
    await init_db()
    logger.info("База данных готова.")

    # Auto-recovery: scan and sync any session files from disk into DB
    await sync_sessions_from_disk()

    # Ensure sessions directory exists
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Директория сессий: {SESSIONS_DIR}")

    # Initialize Bot & Dispatcher
    bot = DefaultBotProperties(parse_mode=ParseMode.HTML)
    bot_client = Bot(token=BOT_TOKEN, default=bot)
    dp = Dispatcher(storage=MemoryStorage())

    # Register Routers in order
    dp.include_router(buyer_router)
    dp.include_router(admin_router)
    dp.include_router(seller_router)
    dp.include_router(common_router)

    bot_user = await bot_client.get_me()
    logger.info(f"🚀 Бот @{bot_user.username} успешно запущен!")
    if ADMIN_IDS:
        logger.info(f"Администраторы: {ADMIN_IDS}")
    else:
        logger.warning("⚠️ ADMIN_IDS пуст — доступ к админ-панели разрешен всем пользователям.")

    # Start Web Client Server (for in-browser direct access)
    from services.web_app import start_web_server
    web_runner = None
    try:
        web_runner = await start_web_server()
    except Exception as e:
        logger.warning(f"Не удалось запустить встроенный Web-сервер: {e}")

    try:
        await bot_client.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot_client)
    finally:
        if web_runner:
            try:
                await web_runner.cleanup()
            except Exception:
                pass
        await bot_client.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
