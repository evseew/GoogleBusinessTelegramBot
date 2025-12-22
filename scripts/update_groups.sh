#!/bin/bash
# Скрипт обновления groups.json из Google Sheets
# Запускается по cron раз в день

set -e

# Переходим в директорию проекта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "$(date): Запуск обновления groups.json"
echo "Директория: $PROJECT_DIR"

# Активируем виртуальное окружение
if [ -d "new_venv" ]; then
    source new_venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "ОШИБКА: Виртуальное окружение не найдено"
    exit 1
fi

# Загружаем переменные окружения
if [ -f ".env" ]; then
    source .env
fi

# Создаём директорию для логов
mkdir -p logs

# Запускаем Python скрипт
python scripts/update_groups.py

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date): Обновление groups.json завершено успешно"
else
    echo "$(date): ОШИБКА при обновлении groups.json (код: $EXIT_CODE)"
fi

exit $EXIT_CODE

