#!/bin/bash
#
# Ежедневная синхронизация данных из 1С
# Скачивает clients.xml и contracts.xml, конвертирует в JSON
#
# Запускать через cron: 0 6 * * * (каждый день в 6:00)
#

# Переходим в директорию проекта
cd "$(dirname "$0")/.." || exit 1

# Активируем виртуальное окружение если есть
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "=================================================="
echo "Ежедневная синхронизация данных 1С"
echo "Время: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="

# Запускаем синхронизацию только clients и contracts
/opt/homebrew/bin/python3.10 -c "
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

# Синхронизируем clients и contracts
success = True
for file_type in ['clients', 'contracts']:
    logger.info(f'Синхронизация {file_type}...')
    if not client.sync_file(file_type):
        logger.error(f'Ошибка синхронизации {file_type}')
        success = False

if success:
    logger.info('✅ Ежедневная синхронизация завершена успешно')
    sys.exit(0)
else:
    logger.error('❌ Ежедневная синхронизация завершена с ошибками')
    sys.exit(1)
"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "✅ Синхронизация успешна"
else
    echo "❌ Ошибка синхронизации (код: $exit_code)"
fi

exit $exit_code
