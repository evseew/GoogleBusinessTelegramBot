#!/bin/bash
#
# Синхронизация транзакций из 1С каждые 4 часа
# Скачивает transactions.xml и конвертирует в JSON
#
# Запускать через cron: 0 */4 * * * (каждые 4 часа: 0, 4, 8, 12, 16, 20)
#

# Переходим в директорию проекта
cd "$(dirname "$0")/.." || exit 1

# Активируем виртуальное окружение если есть
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "=================================================="
echo "Синхронизация транзакций 1С (каждые 4 часа)"
echo "Время: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="

# Запускаем синхронизацию только transactions
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

# Синхронизируем transactions (история операций)
logger.info('Синхронизация transactions (история операций)...')
if client.sync_file('transactions'):
    logger.info('✅ Синхронизация транзакций завершена успешно')
    sys.exit(0)
else:
    logger.error('❌ Ошибка синхронизации transactions')
    sys.exit(1)
"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo "✅ Синхронизация успешна"
else
    echo "❌ Ошибка синхронизации (код: $exit_code)"
fi

exit $exit_code



