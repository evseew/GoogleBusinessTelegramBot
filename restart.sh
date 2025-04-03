#!/bin/bash

# Выводим информацию о начале перезапуска
echo "🔄 Перезапуск бота начат: $(date)"

# Остановка бота
echo "🛑 Останавливаю бота..."
./stop_bot.sh

# Небольшая задержка перед запуском
echo "⏳ Ожидаем 5 секунд перед запуском..."
sleep 5

# Запуск бота
echo "🚀 Запускаю бота..."
./start_bot.sh

echo "✅ Процесс перезапуска завершен: $(date)" 