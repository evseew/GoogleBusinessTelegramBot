#!/bin/bash
#
# Почасовая синхронизация балансов и бонусов из 1С
# Скачивает contracts.xml и конвертирует в JSON
#
# Запускать через cron: 0 * * * * (каждый час)
#

# Переходим в директорию проекта
cd "$(dirname "$0")/.." || exit 1

# Активируем виртуальное окружение если есть
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "=================================================="
echo "Почасовая синхронизация балансов и бонусов 1С"
echo "Время: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="

# Запускаем синхронизацию только contracts (балансы и бонусы)
python3 -c "
import sys
sys.path.insert(0, '.')
from tools.bitrix_sync import BitrixSyncClient
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Настройки
BASE_URL = 'https://student.planetenglish.ru'
LOGIN = 'konstantin@planetenglish.ru'
PASSWORD = 'Fv%8D3_(5Wp'

# Создаем клиент и авторизуемся
client = BitrixSyncClient(BASE_URL, LOGIN, PASSWORD)

if not client.authenticate():
    logger.error('Ошибка авторизации')
    sys.exit(1)

# Синхронизируем contracts (балансы и бонусы на счетах)
logger.info('Синхронизация contracts (балансы и бонусы)...')
if client.sync_file('contracts'):
    logger.info('✅ Почасовая синхронизация завершена успешно')
    sys.exit(0)
else:
    logger.error('❌ Ошибка синхронизации contracts')
    sys.exit(1)
"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "✅ Синхронизация успешна"
else
    echo "❌ Ошибка синхронизации (код: $exit_code)"
fi

exit $exit_code
