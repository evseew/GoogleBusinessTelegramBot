#!/bin/bash
# Скрипт ротации логов для Google Business Bot

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Запускаем logrotate с нашим конфигом
/usr/sbin/logrotate -s "$SCRIPT_DIR/logrotate.state" "$SCRIPT_DIR/logrotate.conf"

# Опционально: очищаем старые архивы (старше 30 дней)
find "$SCRIPT_DIR/logs" -name "*.log.*" -mtime +30 -delete 2>/dev/null || true
find "$SCRIPT_DIR/logs" -name "*.gz" -mtime +30 -delete 2>/dev/null || true

exit 0

