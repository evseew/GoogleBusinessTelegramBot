import asyncio
import sys
import logging

# Запускает обновление базы знаний как one-shot процесс под systemd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    # Импортируем из основного бота готовую функцию обновления
    from bot import update_vector_store_telegram
except Exception as e:
    print(f"❌ Не удалось импортировать update_vector_store_telegram из bot.py: {e}")
    sys.exit(1)


async def main() -> int:
    try:
        logging.info("--- One-shot обновление базы знаний (systemd) ---")
        result = await update_vector_store_telegram()
        if result.get("success"):
            logging.info("✅ Обновление завершено успешно: added=%s total=%s", result.get('added_chunks'), result.get('total_chunks'))
            return 0
        else:
            logging.error("❌ Обновление завершилось с ошибкой: %s", result.get("error"))
            return 2
    except Exception as e:
        logging.exception("❌ Критическая ошибка one-shot обновления: %s", e)
        return 3


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)


