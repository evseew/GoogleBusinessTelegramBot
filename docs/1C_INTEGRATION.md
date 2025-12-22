# Интеграция с 1С через Bitrix

## Описание

Система автоматически скачивает данные из 1С (клиенты, договоры, транзакции) с Bitrix-сайта, конвертирует их в JSON и предоставляет доступ через API бота.

## Структура данных

### 1. Clients (Клиенты/Ученики)
- **Файл**: `data/clients.json`
- **Обновление**: Ежедневно в 6:00
- **Источник**: `/upload/1c_exchange/clients/clients.xml`
- **Содержит**:
  - ФИО ученика
  - Логин (лицевой счет)
  - Филиал и группа
  - Преподаватель
  - Контактные данные (телефон, email)
  - Бонусы

### 2. Contracts (Договоры)
- **Файл**: `data/contracts.json`
- **Обновление**: Ежедневно в 6:00
- **Источник**: `/upload/1c_exchange/contracts/contracts.xml`
- **Содержит**:
  - ID договора
  - Баланс
  - Бонусы
  - Связь с клиентом

### 3. Transactions (Транзакции)
- **Файл**: `data/transactions.json`
- **Обновление**: Каждый час
- **Источник**: `/upload/1c_exchange/tranzactions/transactions.xml`
- **Содержит**:
  - Дата и время
  - Сумма
  - Описание операции
  - Связь с договором

## Доступные инструменты (Tools)

### 1. `search_client_by_name(last_name, first_name?)`
Поиск клиента по фамилии и имени

**Пример**:
```python
search_client_by_name("Иванов", "Петр")
```

### 2. `get_client_balance(login?, last_name?)`
Получение баланса и информации о клиенте

**Пример**:
```python
get_client_balance(login="41304")
get_client_balance(last_name="Иванов")
```

### 3. `get_recent_transactions(login?, last_name?, limit=10)`
Получение последних транзакций клиента

**Пример**:
```python
get_recent_transactions(login="41304", limit=5)
```

## Настройка автоматической синхронизации

### Вариант 1: Через crontab (рекомендуется)

```bash
# Редактируем crontab
crontab -e

# Добавляем задачи:

# Ежедневная синхронизация clients и contracts в 6:00
0 6 * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_daily.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_daily.log 2>&1

# Почасовая синхронизация transactions
0 * * * * /Users/test/Local_code/GoogleBusinessBot/scripts/sync_1c_hourly.sh >> /Users/test/Local_code/GoogleBusinessBot/logs/sync_hourly.log 2>&1
```

### Вариант 2: Ручной запуск

```bash
# Ежедневная синхронизация
./scripts/sync_1c_daily.sh

# Почасовая синхронизация
./scripts/sync_1c_hourly.sh

# Или напрямую через Python
python3 tools/bitrix_sync.py
```

## Проверка работы

### 1. Проверить последнюю синхронизацию
```bash
# Посмотреть метку времени обновления
cat data/clients.json | grep "updated_at"
cat data/contracts.json | grep "updated_at"
cat data/transactions.json | grep "updated_at"
```

### 2. Проверить количество записей
```bash
cat data/clients.json | grep '"count"'
cat data/contracts.json | grep '"count"'
cat data/transactions.json | grep '"count"'
```

### 3. Посмотреть логи синхронизации
```bash
tail -f logs/sync_daily.log
tail -f logs/sync_hourly.log
```

## Безопасность

⚠️ **Важно**: 
- XML файлы и JSON с данными НЕ коммитятся в Git (добавлены в `.gitignore`)
- Логин и пароль для Bitrix хранятся в скриптах (в production переместите в `.env`)
- Файлы в `data/xml/` содержат исходные XML и занимают много места (~21 МБ)

## Структура файлов

```
/Users/test/Local_code/GoogleBusinessBot/
├── tools/
│   ├── bitrix_sync.py          # Модуль синхронизации
│   └── client_tools.py         # Инструменты для работы с данными
├── scripts/
│   ├── sync_1c_daily.sh        # Скрипт ежедневной синхронизации
│   └── sync_1c_hourly.sh       # Скрипт почасовой синхронизации
├── data/
│   ├── clients.json            # Клиенты (JSON)
│   ├── contracts.json          # Договоры (JSON)
│   ├── transactions.json       # Транзакции (JSON)
│   └── xml/                    # Исходные XML файлы
│       ├── clients.xml
│       ├── contracts.xml
│       └── transactions.xml
└── logs/
    ├── sync_daily.log          # Логи ежедневной синхронизации
    └── sync_hourly.log         # Логи почасовой синхронизации
```

## Тестирование

### Тест модуля синхронизации
```bash
python3 tools/bitrix_sync.py
```

### Тест инструментов
```python
from tools.client_tools import search_client_by_name, get_client_balance

# Поиск клиента
result = search_client_by_name("Иванов")
print(result)

# Баланс клиента
result = get_client_balance(login="41304")
print(result)
```

## Troubleshooting

### Ошибка "No module named 'bs4'"
```bash
pip install beautifulsoup4 lxml requests
```

### Ошибка авторизации
Проверьте логин и пароль в скриптах:
- `scripts/sync_1c_daily.sh`
- `scripts/sync_1c_hourly.sh`
- `tools/bitrix_sync.py`

### Файлы не скачиваются
1. Проверьте подключение к интернету
2. Проверьте URL файлов (возможно изменилась структура)
3. Посмотрите логи: `logs/sync_daily.log` или `logs/sync_hourly.log`

## Примеры использования в боте

Бот автоматически распознает запросы и использует нужные инструменты:

```
Пользователь: Найди клиента Иванов
Бот: [использует search_client_by_name("Иванов")]

Пользователь: Какой баланс у ученика 41304?
Бот: [использует get_client_balance(login="41304")]

Пользователь: Покажи последние платежи Иванова
Бот: [использует get_recent_transactions(last_name="Иванов")]
```

## Производительность

- **clients.xml**: ~3.9 МБ → **clients.json**: ~2.5 МБ (2937 записей)
- **contracts.xml**: ~879 КБ → **contracts.json**: ~400 КБ (2540 записей)
- **transactions.xml**: ~17.3 МБ → **transactions.json**: ~7 МБ (45236 записей)

Время синхронизации:
- Ежедневная (clients + contracts): ~2-3 секунды
- Почасовая (transactions): ~1-2 секунды

## Поддержка

При возникновении проблем:
1. Проверьте логи в `logs/`
2. Убедитесь, что данные обновляются (смотрите `updated_at` в JSON)
3. Запустите ручную синхронизацию для диагностики
