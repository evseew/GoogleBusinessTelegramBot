#!/bin/bash

# Создаем директорию для логов, если она не существует
mkdir -p logs
mkdir -p logs/context_logs

# Проверяем, не запущен ли уже бот (по bot.pid и по процессу)
if [ -f bot.pid ]; then
    PID=$(cat bot.pid)
    if ps -p $PID > /dev/null; then
        echo "⚠️ Бот уже запущен (по bot.pid) с PID: $PID"
        echo "Для перезапуска используйте: ./restart.sh"
        exit 1
    else
        echo "⚠️ Найден устаревший PID файл, удаляем..."
        rm -f bot.pid
    fi
fi

# Дополнительная проверка дублей по процессу (если процесс есть, но bot.pid нет)
if pgrep -f "python.*bot.py" > /dev/null; then
    EXIST_PID=$(pgrep -f "python.*bot.py" | head -n 1)
    echo "⚠️ Найден уже запущенный процесс бота (по pgrep), PID: $EXIST_PID"
    echo "Для перезапуска используйте: ./restart.sh"
    exit 1
fi

# Выводим полный путь к виртуальному окружению
echo "🔄 Активируем окружение: $(pwd)/new_venv"

# Активация окружения
source "$(pwd)/new_venv/bin/activate"

# Проверка окружения
if ! python3 -c "import openai" &> /dev/null; then
    echo "⚠️ Библиотека OpenAI не установлена, устанавливаем..."
    pip install openai
fi

# Дополнительно устанавливаем необходимые библиотеки
pip install langchain-huggingface

# Проверка наличия файла .env
if [ ! -f .env ]; then
    echo "❌ Ошибка: файл .env не найден!"
    exit 1
fi

# Супервизорный цикл с перезапуском
echo "🚀 Запуск супервизора бота..."
source .env

# Ловим сигналы и корректно завершаем дочерний процесс
terminate() {
  echo "🛑 Получен сигнал на завершение, останавливаем дочерний процесс..."
  if [ -n "$CHILD_PID" ] && ps -p $CHILD_PID > /dev/null; then
    kill -15 $CHILD_PID
    # ждем до 10с
    for i in {1..10}; do
      if ! ps -p $CHILD_PID > /dev/null; then
        break
      fi
      sleep 1
    done
    if ps -p $CHILD_PID > /dev/null; then
      echo "⚠️ Принудительное завершение дочернего процесса"
      kill -9 $CHILD_PID
    fi
  fi
  rm -f bot.pid
  exit 0
}
trap terminate INT TERM

echo $$ > bot.pid
echo "✅ Супервизор запущен, PID: $$"

RESTART_DELAY=5
while true; do
  echo "▶️ Старт bot.py..."
  nohup python3 bot.py >> logs/bot.log 2>&1 &
  CHILD_PID=$!
  echo "👶 Дочерний PID: $CHILD_PID"

  # Ждем завершения дочернего процесса
  wait $CHILD_PID
  EXIT_CODE=$?
  echo "⚠️ bot.py завершился с кодом: $EXIT_CODE. Перезапуск через ${RESTART_DELAY}s..." | tee -a logs/bot.log
  sleep $RESTART_DELAY
done