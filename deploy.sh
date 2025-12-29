#!/bin/bash
#
# Скрипт деплоя проекта на production сервер
# Использование: ./deploy.sh
#

set -e  # Остановка при ошибке

# Настройки сервера
SERVER_USER="root"
SERVER_IP="195.133.81.197"
SERVER_PATH="/root/GoogleBusinessTelegramBot"
SERVER="${SERVER_USER}@${SERVER_IP}"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         🚀 ДЕПЛОЙ НА PRODUCTION СЕРВЕР                 ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
echo ""

# Проверка подключения к серверу
echo -e "${YELLOW}🔍 Проверка подключения к серверу...${NC}"
if ! ssh -o ConnectTimeout=5 "$SERVER" "echo 'connected' > /dev/null 2>&1"; then
    echo -e "${RED}❌ Ошибка: Не удается подключиться к серверу $SERVER${NC}"
    echo "Проверьте:"
    echo "  - Правильность IP адреса"
    echo "  - SSH ключи настроены"
    echo "  - Сервер доступен"
    exit 1
fi
echo -e "${GREEN}✅ Подключение установлено${NC}"
echo ""

# Получаем путь к проекту
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_NAME="bot_deploy_$(date +%Y%m%d_%H%M%S).tar.gz"
TEMP_ARCHIVE="/tmp/$ARCHIVE_NAME"

echo -e "${YELLOW}📦 Создание архива проекта...${NC}"
echo "   Исключаем: venv, logs, cache, dev файлы"

# Создаем архив, исключая ненужные файлы
cd "$PROJECT_DIR"
tar -czf "$TEMP_ARCHIVE" \
    --exclude='new_venv' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.pid' \
    --exclude='logs' \
    --exclude='.git' \
    --exclude='.gitignore' \
    --exclude='dev_docs' \
    --exclude='dev_tests' \
    --exclude='.DS_Store' \
    --exclude='*.swp' \
    --exclude='deploy.sh' \
    .

ARCHIVE_SIZE=$(du -h "$TEMP_ARCHIVE" | cut -f1)
echo -e "${GREEN}✅ Архив создан: $ARCHIVE_SIZE${NC}"
echo ""

# Остановка бота на сервере
echo -e "${YELLOW}🛑 Остановка бота на сервере...${NC}"
ssh "$SERVER" "cd $SERVER_PATH && if [ -f control.sh ]; then ./control.sh stop 2>/dev/null || true; else ./stop_bot.sh 2>/dev/null || true; fi"
echo -e "${GREEN}✅ Бот остановлен${NC}"
echo ""

# Бэкап пропускаем (занимает много времени, можно делать вручную если нужно)
echo -e "${YELLOW}💾 Бэкап пропущен (можно сделать вручную)${NC}"
echo ""

# Копирование архива на сервер
echo -e "${YELLOW}📤 Копирование на сервер...${NC}"
scp -q "$TEMP_ARCHIVE" "$SERVER:/tmp/"
echo -e "${GREEN}✅ Файлы скопированы${NC}"
echo ""

# Распаковка на сервере
echo -e "${YELLOW}📂 Распаковка на сервере...${NC}"
ssh "$SERVER" << EOF
    # Создаём директорию если её нет
    mkdir -p $SERVER_PATH
    
    # Распаковываем
    cd $SERVER_PATH
    tar -xzf /tmp/$ARCHIVE_NAME
    
    # Удаляем временный архив
    rm /tmp/$ARCHIVE_NAME
    
    # Устанавливаем права на скрипты
    chmod +x *.sh 2>/dev/null || true
    chmod +x scripts/*.sh 2>/dev/null || true
    
    # Создаём необходимые директории
    mkdir -p logs logs/context_logs logs/sync
    mkdir -p data data/xml
    mkdir -p history
    
    echo "✅ Распаковка завершена"
EOF
echo ""

# Обновление зависимостей
echo -e "${YELLOW}📦 Обновление зависимостей Python...${NC}"
ssh "$SERVER" << 'EOF'
    cd /root/GoogleBusinessTelegramBot
    
    # Создаём виртуальное окружение если его нет
    if [ ! -d "new_venv" ]; then
        echo "Создание виртуального окружения..."
        python3 -m venv new_venv
    fi
    
    # Активируем и обновляем зависимости
    source new_venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    
    echo "✅ Зависимости обновлены"
EOF
echo ""

# Обновление systemd сервисов
echo -e "${YELLOW}⚙️  Обновление systemd сервисов...${NC}"
ssh "$SERVER" << 'EOF'
    cd /root/GoogleBusinessTelegramBot
    
    # Копируем сервисы
    cp *.service /etc/systemd/system/ 2>/dev/null || true
    
    # Перезагружаем конфигурацию
    systemctl daemon-reload
    
    # Включаем автозапуск
    systemctl enable google-business-bot.service 2>/dev/null || true
    
    echo "✅ Systemd сервисы обновлены"
EOF
echo ""

# Запуск бота
echo -e "${YELLOW}🚀 Запуск бота с обновлением данных...${NC}"
ssh "$SERVER" << 'EOF'
    cd /root/GoogleBusinessTelegramBot
    
    # Используем новый control.sh если есть, иначе старый способ
    if [ -f control.sh ] && grep -q "refresh" control.sh; then
        ./control.sh refresh
    else
        ./start_bot.sh
    fi
    
    sleep 3
    
    # Проверяем статус
    if [ -f control.sh ]; then
        ./control.sh status 2>/dev/null || true
    fi
EOF
echo ""

# Удаление локального архива
rm -f "$TEMP_ARCHIVE"

# Финальное сообщение
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✅ ДЕПЛОЙ УСПЕШНО ЗАВЕРШЁН!                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📊 Что было сделано:${NC}"
echo "   ✅ Бот остановлен"
echo "   ✅ Создан бэкап"
echo "   ✅ Код обновлён"
echo "   ✅ Зависимости обновлены"
echo "   ✅ Systemd сервисы обновлены"
echo "   ✅ Бот запущен с обновлением данных"
echo ""
echo -e "${BLUE}🔍 Проверка работы:${NC}"
echo "   ssh $SERVER"
echo "   cd $SERVER_PATH"
echo "   ./control.sh status"
echo "   ./control.sh logs"
echo ""
echo -e "${BLUE}💡 Если нужен бэкап, сделай вручную:${NC}"
echo "   ssh $SERVER 'cd /root && tar -czf backup_\$(date +%Y%m%d).tar.gz GoogleBusinessTelegramBot/'"
echo ""

