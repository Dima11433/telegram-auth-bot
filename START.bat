@echo off
title Telegram Auth Bot
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================================
echo          Telegram Auth & Account Seller Bot
echo ========================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден в системе!
    echo Установите Python 3.10+ с сайта https://www.python.org/downloads/
    echo Обязательно отметьте галочку "Add Python to PATH" при установке.
    echo.
    pause
    exit /b 1
)

:: 2. Check .env
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" > nul
        echo [!] Файл конфигурации .env не был найден.
        echo [!] Был создан новый файл .env из шаблона .env.example.
        echo.
        echo --------------------------------------------------------
        echo ВНИМАНИЕ: Откройте файл .env в Блокноте и вставьте:
        echo   1. BOT_TOKEN - токен вашего бота из @BotFather
        echo   2. ADMIN_IDS - ваш Telegram ID (узнать в @userinfobot)
        echo --------------------------------------------------------
        echo.
        echo После сохранения файла .env запустите START.bat повторно!
        echo.
        pause
        exit /b 0
    ) else (
        echo [ОШИБКА] Файл .env и .env.example не найдены!
        pause
        exit /b 1
    )
)

:: 3. Setup virtual environment if not exists
if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Создание виртуального окружения Python (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Не удалось создать .venv!
        pause
        exit /b 1
    )
    echo [2/2] Установка необходимых библиотек (requirements.txt)...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\pip.exe install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ОШИБКА] Ошибка при установке зависимостей!
        pause
        exit /b 1
    )
    echo.
    echo [OK] Установка успешно завершена!
    echo.
)

:: 4. Run bot
echo Запуск бота...
echo Для остановки нажмите Ctrl + C.
echo.
.venv\Scripts\python.exe main.py

echo.
echo ========================================================
echo   Бот был остановлен. Нажмите любую клавишу для выхода.
echo ========================================================
pause
