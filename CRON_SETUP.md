# Настройка автоматической синхронизации данных из 1С

## Быстрая настройка

### 1. Откройте редактор crontab
```bash
crontab -e
```

### 2. Добавьте следующие строки

```bash
# Ежедневная синхронизация клиентов и договоров в 6:00 утра
0 6 * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_daily.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_daily.log 2>&1

# Почасовая синхронизация транзакций (каждый час)
0 * * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_hourly.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_hourly.log 2>&1
```

### 3. Сохраните и выйдите
- Если используете `nano`: `Ctrl+X`, затем `Y`, затем `Enter`
- Если используете `vim`: нажмите `Esc`, затем`:wq`, затем `Enter`

### 4. Проверьте, что задачи добавлены
```bash
crontab -l
```

## Альтернативные варианты расписания

### Вариант 1: Синхронизация 2 раза в день
```bash
# Утром в 6:00 и вечером в 18:00
0 6,18 * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_daily.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_daily.log 2>&1

# Транзакции каждый час
0 * * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_hourly.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_hourly.log 2>&1
```

### Вариант 2: Синхронизация каждые 30 минут (для транзакций)
```bash
# Ежедневная в 6:00
0 6 * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_daily.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_daily.log 2>&1

# Транзакции каждые 30 минут
*/30 * * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_hourly.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_hourly.log 2>&1
```

### Вариант 3: Всё каждый час
```bash
# Всё (clients, contracts, transactions) каждый час
0 * * * * /opt/homebrew/bin/python3.10 /Users/test/Local_code/GoogleBusinessBot/tools/bitrix_sync.py >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_all.log 2>&1
```

## Проверка работы

### 1. Первый запуск (вручную)
```bash
# Запустите скрипты вручную чтобы убедиться что они работают
cd /Users/test/Local_code/GoogleBusinessBot

./scripts/sync_1c_daily.sh
./scripts/sync_1c_hourly.sh
```

Если всё прошло успешно, вы увидите:
```
✅ Синхронизация успешна
```

### 2. Проверка cron логов
```bash
# Смотрим последние 20 строк логов
tail -20 logs/sync_daily.log
tail -20 logs/sync_hourly.log
```

### 3. Проверка данных
```bash
# Проверяем что файлы созданы и актуальны
ls -lh data/*.json
cat data/clients.json | grep "updated_at"
```

## Отладка проблем

### Проблема: cron не запускается

1. Проверьте права на выполнение:
```bash
chmod +x /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_daily.sh
chmod +x /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_hourly.sh
```

2. Проверьте права на запись логов:
```bash
touch /Users/test/Local_code/GoogleBusinessBot/logs/sync_daily.log
touch /Users/test/Local_code/GoogleBusinessBot/logs/sync_hourly.log
```

3. Проверьте что cron работает:
```bash
# MacOS
sudo launchctl load -w /System/Library/LaunchDaemons/com.vix.cron.plist
```

### Проблема: ошибка авторизации

Убедитесь, что логин и пароль верные в файлах:
- `scripts/sync_1c_daily.sh`
- `scripts/sync_1c_hourly.sh`

### Проблема: Python не найден

Проверьте путь к Python в скриптах:
```bash
which python3.10
```

Если путь другой, отредактируйте скрипты и замените `/opt/homebrew/bin/python3.10` на ваш путь.

## Мониторинг

### Создайте простой скрипт проверки
```bash
cat > /Users/test/Local_code/GoogleBusinessBot/check_sync.sh << 'EOF'
#!/bin/bash
echo "=== Статус синхронизации данных 1С ==="
echo ""
echo "Клиенты:"
cat data/clients.json | grep -o '"updated_at":"[^"]*"' | head -1
cat data/clients.json | grep -o '"count":[0-9]*' | head -1

echo ""
echo "Договоры:"
cat data/contracts.json | grep -o '"updated_at":"[^"]*"' | head -1
cat data/contracts.json | grep -o '"count":[0-9]*' | head -1

echo ""
echo "Транзакции:"
cat data/transactions.json | grep -o '"updated_at":"[^"]*"' | head -1
cat data/transactions.json | grep -o '"count":[0-9]*' | head -1

echo ""
echo "Последние ошибки:"
tail -5 logs/sync_daily.log | grep -i error
tail -5 logs/sync_hourly.log | grep -i error
EOF

chmod +x /Users/test/Local_code/GoogleBusinessBot/check_sync.sh
```

Затем запускайте:
```bash
./check_sync.sh
```

## Удаление задач cron

Если нужно отключить автоматическую синхронизацию:

```bash
# Откройте редактор
crontab -e

# Удалите строки с sync_1c_daily.sh и sync_1c_hourly.sh
# Или закомментируйте их, добавив # в начало строки
```

## Рекомендации

✅ **Рекомендуемое расписание**:
- Clients & Contracts: **1 раз в день** (утром в 6:00)
- Transactions: **каждый час**

⚠️ **Не рекомендуется**:
- Синхронизировать всё чаще, чем каждые 30 минут (лишняя нагрузка)
- Запускать синхронизацию в часы пик (9:00-12:00, 14:00-18:00)

💡 **Совет**: Если данные обновляются редко, можно синхронизировать clients/contracts раз в неделю, а transactions — раз в 6 часов.
