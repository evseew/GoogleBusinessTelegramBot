#!/bin/bash

# Определяем директорию скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Функция для вывода справки
show_help() {
    echo "Управление ботом Google Business"
    echo "Использование: $0 [команда]"
    echo ""
    echo "Доступные команды:"
    echo "  start   - Запустить бота"
    echo "  stop    - Остановить бота"
    echo "  restart - Перезапустить бота"
    echo "  status  - Показать статус бота"
    echo "  logs    - Показать последние 50 строк логов (используйте Ctrl+C для выхода)"
    echo "  update  - Обновить базу знаний"
    echo "  check   - Проверить настройку сервера"
    echo "  help    - Показать эту справку"
}

# Функция для запуска бота (через systemd)
start_bot() {
    echo "🚀 Запускаем сервис google-business-bot..."
    systemctl start google-business-bot
}

# Функция для остановки бота (через systemd)
stop_bot() {
    echo "🛑 Останавливаем сервис google-business-bot..."
    systemctl stop google-business-bot
}

# Функция для перезапуска бота (через systemd)
restart_bot() {
    echo "🔄 Перезапускаем сервис google-business-bot..."
    systemctl restart google-business-bot
}

# Функция для проверки статуса бота (через systemd)
status_bot() {
    if systemctl is-active --quiet google-business-bot; then
        echo "✅ Сервис google-business-bot активен"
    else
        echo "❌ Сервис google-business-bot НЕ активен"
    fi
    systemctl status google-business-bot | cat
}

# Функция для обновления базы знаний
update_db() {
    echo "📚 One-shot обновление базы знаний через systemd..."
    systemctl start google-business-bot-update
}

# Функция для просмотра логов сервиса (journald)
show_logs() {
    echo "📋 Логи сервиса (Ctrl+C для выхода):"
    journalctl -u google-business-bot -n 50 -f
}

# Функция проверки настройки сервера
check_setup() {
    echo "🔍 Проверка настройки сервера..."
    
    # Проверка Python и виртуального окружения
    if [ -d "$SCRIPT_DIR/new_venv" ]; then
        echo "✅ Виртуальное окружение найдено"
    else
        echo "❌ Виртуальное окружение не найдено!"
    fi
    
    # Проверка конфигурационных файлов
    if [ -f "$SCRIPT_DIR/.env" ]; then
        echo "✅ Файл .env найден"
    else
        echo "❌ Файл .env не найден!"
    fi
    
    if [ -f "$SCRIPT_DIR/service-account-key.json" ]; then
        echo "✅ Ключ сервисного аккаунта Google найден"
    else
        echo "❌ Ключ сервисного аккаунта Google не найден!"
    fi
    
    # Проверка базы данных
    if [ -d "$SCRIPT_DIR/local_vector_db" ]; then
        echo "✅ Векторная база данных найдена"
    else
        echo "❌ Векторная база данных не найдена!"
    fi
    
    # Проверка службы systemd
    if systemctl is-enabled --quiet google-business-bot; then
        echo "✅ Служба systemd включена"
    else
        echo "⚠️ Служба systemd не включена в автозагрузку"
    fi
    if systemctl is-active --quiet google-business-bot; then
        echo "✅ Служба systemd активна"
    else
        echo "❌ Служба systemd не активна!"
    fi
    
    # Проверка cron-задач
    if crontab -l | grep -q "update_db.sh"; then
        echo "✅ Cron-задача для обновления базы найдена"
    else
        echo "❌ Cron-задача для обновления базы не найдена!"
    fi
}

# Обработка аргументов командной строки
case "$1" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        restart_bot
        ;;
    status)
        status_bot
        ;;
    logs)
        show_logs
        ;;
    update)
        update_db
        ;;
    check)
        check_setup
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "❓ Неизвестная команда: $1"
        show_help
        exit 1
        ;;
esac

exit 0
