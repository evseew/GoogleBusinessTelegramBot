#!/bin/bash

# Определяем директорию скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Создаем функцию для остановки бота
stop_bot() {
    local pid=$1
    echo "📦 Останавливаем бота с PID: $pid"
    
    # Сначала отправляем SIGTERM для корректного завершения
    kill -15 $pid
    
    # Ждем до 10 секунд для корректного завершения
    for i in {1..10}; do
        if ! ps -p $pid > /dev/null; then
            echo "✅ Бот успешно остановлен"
            return 0
        fi
        echo "⏳ Ожидаем завершения процесса... $i/10"
        sleep 1
    done
    
    # Если процесс всё еще работает, применяем SIGKILL
    if ps -p $pid > /dev/null; then
        echo "⚠️ Процесс не завершился корректно, применяем принудительное завершение"
        kill -9 $pid
        sleep 1
        
        if ! ps -p $pid > /dev/null; then
            echo "✅ Бот принудительно остановлен"
            return 0
        else
            echo "❌ Не удалось остановить бота"
            return 1
        fi
    fi
}

# Остановка бота
if [ -f bot.pid ]; then
    echo "🔍 Найден файл bot.pid"
    PID=$(cat bot.pid)
    
    if ps -p $PID > /dev/null; then
        stop_bot $PID
        if [ $? -eq 0 ]; then
            rm bot.pid
        fi
    else
        echo "⚠️ Процесс с PID $PID не найден"
        rm bot.pid
        echo "🗑️ Удален устаревший файл bot.pid"
    fi
else
    echo "⚠️ Файл bot.pid не найден, ищем процесс бота в текущей папке..."
    PIDS=$(pgrep -fa "$SCRIPT_DIR/bot.py" | awk '{print $1}' || true)
    if [ -n "$PIDS" ]; then
        echo "🔍 Найдены процессы бота: $PIDS"
        for PID in $PIDS; do
            stop_bot $PID
        done
    else
        echo "ℹ️ Процесс бота не найден. Возможно, бот не запущен."
    fi
fi

# Проверка запущенности после остановки (только процессы из этой папки)
if pgrep -fa "$SCRIPT_DIR/bot.py" > /dev/null; then
    echo "❌ Внимание! Бот все еще запущен. Проверьте процессы вручную."
else
    echo "✅ Бот не запущен."
fi 