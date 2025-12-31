# 🚀 Чеклист развертывания на production сервере

## 📍 Путь на сервере: `/root/GoogleBusinessTelegramBot/`

---

## 1️⃣ Подготовка сервера

### Установка зависимостей
```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Python 3.10+
sudo apt install python3 python3-pip python3-venv -y

# Установка git
sudo apt install git -y

# Установка системных утилит
sudo apt install curl wget nano htop -y
```

---

## 2️⃣ Клонирование проекта

```bash
# Переход в директорию root
cd /root

# Клонирование репозитория
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> GoogleBusinessTelegramBot

# Переход в папку проекта
cd /root/GoogleBusinessTelegramBot
```

---

## 3️⃣ Настройка виртуального окружения

```bash
# Создание виртуального окружения
python3 -m venv new_venv

# Активация окружения
source new_venv/bin/activate

# Установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt

# Проверка установки
python --version
pip list
```

---

## 4️⃣ Секретные файлы (КРИТИЧНО!)

### 📄 Создать `.env` файл

```bash
nano /root/GoogleBusinessTelegramBot/.env
```

**Минимально необходимые переменные:**
```ini
# Telegram Bot API
TELEGRAM_TOKEN=your_telegram_bot_token_here

# OpenAI API
OPENAI_API_KEY=your_openai_api_key_here

# Google Sheets API (если используется)
GOOGLE_SHEETS_ID=your_sheets_id_here

# 1C API (если используется)
ONEC_BASE_URL=your_1c_url_here
ONEC_USERNAME=your_1c_username
ONEC_PASSWORD=your_1c_password

# Админы (Telegram ID)
ADMIN_IDS=123456789,987654321
```

### 📄 Скопировать `service-account-key.json`

```bash
# Скопировать с локальной машины на сервер
scp service-account-key.json root@YOUR_SERVER:/root/GoogleBusinessTelegramBot/

# Проверить что файл скопирован
ls -la /root/GoogleBusinessTelegramBot/service-account-key.json
```

**Установить правильные права:**
```bash
chmod 600 /root/GoogleBusinessTelegramBot/.env
chmod 600 /root/GoogleBusinessTelegramBot/service-account-key.json
```

---

## 5️⃣ Обновление путей в systemd сервисах

### Файл: `google-business-bot.service`

```bash
nano /root/GoogleBusinessTelegramBot/google-business-bot.service
```

**Найти и заменить все пути:**
- `/Users/test/Local_code/GoogleBusinessBot` → `/root/GoogleBusinessTelegramBot`

**Ключевые строки для проверки:**
```ini
WorkingDirectory=/root/GoogleBusinessTelegramBot
Environment="PATH=/root/GoogleBusinessTelegramBot/new_venv/bin"
EnvironmentFile=/root/GoogleBusinessTelegramBot/.env
ExecStart=/root/GoogleBusinessTelegramBot/new_venv/bin/python /root/GoogleBusinessTelegramBot/bot.py
StandardOutput=append:/root/GoogleBusinessTelegramBot/logs/bot.log
StandardError=append:/root/GoogleBusinessTelegramBot/logs/bot_error.log
ExecStartPre=/bin/mkdir -p /root/GoogleBusinessTelegramBot/logs
ExecStartPre=/bin/mkdir -p /root/GoogleBusinessTelegramBot/logs/context_logs
```

### Файл: `google-business-bot-update.service`

```bash
nano /root/GoogleBusinessTelegramBot/google-business-bot-update.service
```

**Обновить пути аналогично:**
```ini
WorkingDirectory=/root/GoogleBusinessTelegramBot
Environment="PATH=/root/GoogleBusinessTelegramBot/new_venv/bin"
EnvironmentFile=/root/GoogleBusinessTelegramBot/.env
ExecStart=/root/GoogleBusinessTelegramBot/new_venv/bin/python /root/GoogleBusinessTelegramBot/update_kb.py
```

### Файл: `google-business-bot-notify@.service`

```bash
nano /root/GoogleBusinessTelegramBot/google-business-bot-notify@.service
```

**Обновить путь:**
```ini
WorkingDirectory=/root/GoogleBusinessTelegramBot
EnvironmentFile=/root/GoogleBusinessTelegramBot/.env
ExecStart=/bin/bash -lc '/root/GoogleBusinessTelegramBot/notify_admin.sh "%I" "$(systemctl show -p SubState --value %I)"'
```

---

## 6️⃣ Установка systemd сервисов

```bash
# Копирование сервисов в systemd
sudo cp /root/GoogleBusinessTelegramBot/*.service /etc/systemd/system/

# Перезагрузка конфигурации systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable google-business-bot.service
sudo systemctl enable google-business-bot-update.service

# Проверка статуса
systemctl status google-business-bot
```

---

## 7️⃣ Создание необходимых директорий

```bash
cd /root/GoogleBusinessTelegramBot

# Создание структуры папок
mkdir -p logs logs/context_logs logs/sync
mkdir -p data data/xml
mkdir -p history
mkdir -p local_vector_db local_vector_db_telegram

# Установка прав
chmod 755 logs data history
```

---

## 8️⃣ Настройка Cron задач

```bash
# Открыть crontab для редактирования
crontab -e
```

**Добавить следующие задачи:**

```cron
# Автозапуск бота после перезагрузки сервера
@reboot cd /root/GoogleBusinessTelegramBot && sleep 30 && ./start_bot.sh

# Ежедневная ротация логов в 1:00 утра
0 1 * * * cd /root/GoogleBusinessTelegramBot && ./rotate_logs.sh >> logs/logrotate.log 2>&1

# Ежедневное обновление групп из Google Sheets в 2:00 утра
0 2 * * * cd /root/GoogleBusinessTelegramBot && ./scripts/update_groups.sh >> logs/groups_update.log 2>&1

# Ежедневное обновление базы знаний в 3:00 утра
0 3 * * * cd /root/GoogleBusinessTelegramBot && ./update_db.sh >> logs/cron_update.log 2>&1

# Еженедельная перезагрузка бота (по воскресеньям в 4:00)
0 4 * * 0 cd /root/GoogleBusinessTelegramBot && ./restart.sh >> logs/cron_restart.log 2>&1

# Обновление данных 1С:
# Каждый час - балансы и бонусы (contracts)
0 * * * * /root/GoogleBusinessTelegramBot/scripts/sync_1c_hourly.sh >> /root/GoogleBusinessTelegramBot/logs/sync_hourly.log 2>&1

# Каждые 4 часа - транзакции
0 */4 * * * /root/GoogleBusinessTelegramBot/scripts/sync_1c_4hourly.sh >> /root/GoogleBusinessTelegramBot/logs/sync_4hourly.log 2>&1

# Раз в сутки в 6:00 - данные клиентов
0 6 * * * /root/GoogleBusinessTelegramBot/scripts/sync_1c_daily.sh >> /root/GoogleBusinessTelegramBot/logs/sync_daily.log 2>&1
```

**Сохранить и выйти:** `Ctrl+X` → `Y` → `Enter`

**Проверить установку:**
```bash
crontab -l
```

---

## 9️⃣ Копирование данных с текущего сервера (опционально)

Если есть рабочий сервер с данными, скопируй их:

```bash
# С локальной машины/старого сервера
scp -r data/*.json root@NEW_SERVER:/root/GoogleBusinessTelegramBot/data/
scp -r local_vector_db root@NEW_SERVER:/root/GoogleBusinessTelegramBot/
scp -r local_vector_db_telegram root@NEW_SERVER:/root/GoogleBusinessTelegramBot/
```

**Или:** Пропусти этот шаг и дай боту сгенерировать данные автоматически при первом запуске.

---

## 🔟 Первый запуск

### Вариант 1: Запуск с обновлением всех данных (рекомендуется)

```bash
cd /root/GoogleBusinessTelegramBot
./control.sh refresh
```

**Что происходит:**
- ✅ Запускается бот через systemd
- ✅ Обновляются группы из Google Sheets
- ✅ Синхронизируются данные из 1С
- ✅ Обновляется база знаний

### Вариант 2: Просто запуск (без обновления данных)

```bash
cd /root/GoogleBusinessTelegramBot
./control.sh start
```

---

## 1️⃣1️⃣ Проверка работы

### Проверка статуса бота

```bash
# Статус сервиса
./control.sh status

# Или напрямую через systemctl
systemctl status google-business-bot
```

### Просмотр логов

```bash
# Последние 50 строк логов (в реальном времени)
./control.sh logs

# Или напрямую
tail -f logs/bot.log
tail -f logs/bot_error.log

# Логи через journald
journalctl -u google-business-bot -n 100 -f
```

### Проверка синхронизации с 1С

```bash
./check_sync.sh
```

### Проверка настройки сервера

```bash
./control.sh check
```

---

## 1️⃣2️⃣ Управление ботом

### Основные команды

```bash
./control.sh start    # Запустить бота
./control.sh stop     # Остановить бота
./control.sh restart  # Перезапустить бота
./control.sh refresh  # Перезапустить + обновить все данные
./control.sh status   # Статус бота
./control.sh logs     # Логи в реальном времени
./control.sh update   # Обновить только базу знаний
./control.sh check    # Проверка настройки
./control.sh clean    # Очистка старых логов
```

---

## 🔥 Troubleshooting (если что-то не работает)

### Бот не запускается

```bash
# 1. Проверить логи
tail -100 logs/bot.log
tail -100 logs/bot_error.log

# 2. Проверить права на файлы
ls -la /root/GoogleBusinessTelegramBot/.env
ls -la /root/GoogleBusinessTelegramBot/service-account-key.json

# 3. Проверить виртуальное окружение
source new_venv/bin/activate
python bot.py  # Запустить вручную для отладки

# 4. Проверить systemd сервис
journalctl -u google-business-bot -n 50
```

### Cron задачи не выполняются

```bash
# Проверить что cron запущен
systemctl status cron

# Проверить логи cron
grep CRON /var/log/syslog
tail -100 logs/cron_*.log
```

### Проблемы с синхронизацией 1С

```bash
# Проверить логи синхронизации
tail -100 logs/sync/hourly.log
tail -100 logs/sync/daily.log

# Запустить синхронизацию вручную
./scripts/sync_1c_hourly.sh
./scripts/sync_1c_daily.sh
```

---

## 🔄 Обновление кода после изменений

```bash
cd /root/GoogleBusinessTelegramBot

# Получить изменения из git
git pull origin main

# Обновить зависимости (если изменился requirements.txt)
source new_venv/bin/activate
pip install -r requirements.txt

# Перезапустить с обновлением данных
./control.sh refresh
```

---

## 🛡️ Безопасность

### Проверить права доступа

```bash
# Секретные файлы должны быть доступны только root
chmod 600 /root/GoogleBusinessTelegramBot/.env
chmod 600 /root/GoogleBusinessTelegramBot/service-account-key.json
chown root:root /root/GoogleBusinessTelegramBot/.env
chown root:root /root/GoogleBusinessTelegramBot/service-account-key.json
```

### Настроить firewall (если нужно)

```bash
# Если используете внешние API
ufw allow 443/tcp  # HTTPS
ufw allow 80/tcp   # HTTP (если нужно)
ufw enable
```

---

## ✅ Финальный чеклист

- [ ] Установлены системные зависимости (Python, git, etc)
- [ ] Проект склонирован в `/root/GoogleBusinessTelegramBot/`
- [ ] Создано виртуальное окружение `new_venv`
- [ ] Установлены Python зависимости из `requirements.txt`
- [ ] Создан файл `.env` с реальными токенами
- [ ] Скопирован файл `service-account-key.json`
- [ ] Обновлены пути в `.service` файлах
- [ ] Установлены systemd сервисы
- [ ] Настроены cron задачи
- [ ] Созданы необходимые директории (logs, data, history)
- [ ] Бот запущен и работает (`./control.sh status`)
- [ ] Логи показывают успешную работу (`./control.sh logs`)
- [ ] Синхронизация с 1С работает (`./check_sync.sh`)

---

## 📞 Контакты для поддержки

В случае проблем проверь:
1. Логи: `./control.sh logs`
2. Статус: `./control.sh status`
3. Настройку: `./control.sh check`

---

**Дата создания:** 25.12.2024  
**Версия:** 1.0




