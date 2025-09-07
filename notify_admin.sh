#!/bin/bash

# Назначение: отправить уведомление админу в Telegram о падении сервиса
# Использует TELEGRAM_BOT_TOKEN и ADMIN_USER_ID из .env (или окружения systemd)

SERVICE_NAME="$1"
STATUS_TEXT="$2"

if [ -z "$SERVICE_NAME" ]; then
  SERVICE_NAME="google-business-bot"
fi

# Подгружаем .env из текущей директории, если systemd не подал переменные
if [ -f ./.env ]; then
  set -o allexport
  # shellcheck disable=SC1091
  source ./.env
  set +o allexport
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$ADMIN_USER_ID" ]; then
  echo "❌ Не заданы TELEGRAM_BOT_TOKEN или ADMIN_USER_ID"
  exit 1
fi

TEXT="⚠️ Сервис ${SERVICE_NAME} перешёл в состояние FAILED и не восстановился.\nСтатус: ${STATUS_TEXT}"

curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
     -H 'Content-Type: application/json' \
     -d "{\"chat_id\": ${ADMIN_USER_ID}, \"text\": \"${TEXT}\"}" >/dev/null || true

exit 0


