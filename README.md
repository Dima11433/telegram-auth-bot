# 🤖 Telegram Auth & Shop Bot

Полнофункциональный бот для автоматизации магазина Telegram-аккаунтов, выдачи кодов подтверждения, конвертации Tdata / .session и управления аккаунтами.

[📖 Полная инструкция по установке (INSTALL_GUIDE.md)](INSTALL_GUIDE.md) | [📖 Инструкция на русском (ИНСТРУКЦИЯ_ПО_УСТАНОВКЕ.md)](ИНСТРУКЦИЯ_ПО_УСТАНОВКЕ.md)

---

## ✨ Ключевые возможности

- 📲 **Многоформатная загрузка аккаунтов:** `.session`, `tdata.zip`, массовые ZIP-архивы, QR-код, вход по SMS/коду.
- 🔑 **Авто-выдача кодов покупателям:** перехват кодов подтверждения из служебного чата Telegram 777000 в реальном времени.
- 📁 **Конвертер TData:** экспорт рабочего Telegram Desktop tdata архива в 1 клик с точным сохранением AuthKey и ID.
- 🛡️ **Anti-Freeze система (защита от вылетов):**
  - Имитация официального Telegram Desktop (Windows 11, `PC 64bit`, `5.6.3 x64`).
  - Мгновенный дисконнект бота после считывания кода — никаких одновременных сокетов и конфликтов `seqno`.
  - Отключение фонового флуда обновлениями (`catch_up=False`).
  - Отсутствие опасных деструктивных команд завершения сессий со стороны сервера.
- 🚪 **Безопасный выход:** покупатель может безопасно отключить сессию бота без сброса своих устройств.
- 📡 **Встроенный прокси-менеджер:** поддержка SOCKS5/HTTP/HTTPS с авторизацией, автоматическая проверка валидности и пинга.
- ⚙️ **Управление аккаунтами:** смена имени, фамилии, 2FA пароля, Email, просмотр диалогов.
- ❓ **Интерактивный FAQ:** пошаговые инструкции прямо в Telegram-интерфейсе для покупателей.

---

## ⚡ Быстрый запуск на Windows (в 1 клик)

1. **Распакуйте архив** с ботом в любую удобную папку (например, `C:\telegram_bot`).
2. Запустите файл **`START.bat`**:
   - При первом запуске он автоматически создаст файл конфигурации `.env` из шаблона.
3. Откройте созданный файл **`.env`** через Блокнот и укажите:
   - `BOT_TOKEN` — токен вашего бота (получить у [@BotFather](https://t.me/BotFather)).
   - `ADMIN_IDS` — ваш числовой Telegram ID (узнать можно в [@userinfobot](https://t.me/userinfobot)).
4. **Сохраните файл `.env`** и снова запустите **`START.bat`**.
   - Скрипт сам создаст виртуальное окружение, установит все библиотеки и запустит бота!

---

## 🐧 Установка и запуск на Linux / VDS / VPS (Ubuntu / Debian)

### 1. Установка необходимых пакетов
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git
```

### 2. Клонирование или загрузка проекта
```bash
git clone https://github.com/Dima11433/telegram-auth-bot.git
cd telegram-auth-bot
```

### 3. Создание виртуального окружения и установка зависимостей
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Настройка файла .env
```bash
cp .env.example .env
nano .env
```
Укажите:
- `BOT_TOKEN` — токен от @BotFather.
- `ADMIN_IDS` — ваш Telegram ID (например `123456789`).

*(Нажмите `Ctrl + O` и `Enter` для сохранения, затем `Ctrl + X` для выхода).*

### 5. Фоновый запуск 24/7 (через systemd)
Создайте файл службы:
```bash
sudo nano /etc/systemd/system/tgbot.service
```

Вставьте конфигурацию (замените путь на вашу директорию):
```ini
[Unit]
Description=Telegram Auth Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/telegram-auth-bot
ExecStart=/root/telegram-auth-bot/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Запустите службу:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tgbot
sudo systemctl start tgbot
```

Проверить статус:
```bash
sudo systemctl status tgbot
```

---

## ⚙️ Описание параметров в .env

| Параметр | Описание | Обязательный? |
| :--- | :--- | :---: |
| `BOT_TOKEN` | Токен бота от @BotFather | **Да** |
| `ADMIN_IDS` | ID администраторов через запятую (например: `123456789`) | **Да** |
| `API_ID` | Telegram API ID (по умолчанию официальный Telegram Desktop: 2040) | Нет |
| `API_HASH` | Telegram API Hash (по умолчанию официальный) | Нет |
| `LOG_CHANNEL_ID` | ID канала для отправки логов действий (например `-1001234567890`) | Нет |
| `CODE_WAIT_TIMEOUT` | Время ожидания кода от Telegram в секундах (по умолчанию 90) | Нет |
| `WEB_PORT` | Порт встроенного веб-сервера (по умолчанию 8080) | Нет |
