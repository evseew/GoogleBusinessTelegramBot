import asyncio
import sys
import logging
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# Запускает обновление базы знаний как one-shot процесс под systemd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Загружаем переменные окружения
load_dotenv()

try:
    # Импортируем из основного бота готовую функцию обновления
    from bot import update_vector_store_telegram
except Exception as e:
    print(f"❌ Не удалось импортировать update_vector_store_telegram из bot.py: {e}")
    sys.exit(1)


def send_telegram_notification(message: str):
    """Отправить уведомление админу через Telegram API"""
    try:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        admin_id = os.getenv("ADMIN_USER_ID")
        
        if not bot_token or not admin_id:
            logging.warning("❌ TELEGRAM_BOT_TOKEN или ADMIN_USER_ID не найдены в .env")
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": admin_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=data, timeout=10)
        
        if response.status_code == 200:
            logging.info("✅ Уведомление отправлено админу")
            return True
        else:
            logging.warning(f"⚠️ Ошибка отправки уведомления: {response.status_code}")
            return False
            
    except Exception as e:
        logging.error(f"❌ Ошибка отправки уведомления: {e}")
        return False


async def main() -> int:
    try:
        logging.info("--- One-shot обновление базы знаний (systemd) ---")
        result = await update_vector_store_telegram()
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if result.get("success"):
            added = result.get('added_chunks', 'N/A')
            total = result.get('total_chunks', 'N/A')
            
            logging.info("✅ Обновление завершено успешно: added=%s total=%s", added, total)
            
            # Отправляем уведомление админу
            message = (
                f"🔔 *Автообновление базы знаний*\n\n"
                f"⏰ Время: {current_time}\n"
                f"✅ Статус: Успешно\n"
                f"➕ Добавлено чанков: {added}\n"
                f"📊 Всего в базе: {total}"
            )
            send_telegram_notification(message)
            
            return 0
        else:
            error = result.get("error", "Неизвестная ошибка")
            logging.error("❌ Обновление завершилось с ошибкой: %s", error)
            
            # Отправляем уведомление об ошибке
            message = (
                f"🔔 *Автообновление базы знаний*\n\n"
                f"⏰ Время: {current_time}\n"
                f"❌ Статус: Ошибка\n"
                f"⚠️ Описание: {error}"
            )
            send_telegram_notification(message)
            
            return 2
    except Exception as e:
        logging.exception("❌ Критическая ошибка one-shot обновления: %s", e)
        
        # Отправляем уведомление о критической ошибке
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            f"🔔 *Автообновление базы знаний*\n\n"
            f"⏰ Время: {current_time}\n"
            f"💥 Критическая ошибка: {str(e)[:200]}"
        )
        send_telegram_notification(message)
        
        return 3


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)


