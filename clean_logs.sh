#!/bin/bash
# Скрипт для ручной очистки логов с архивированием

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
ARCHIVE_DIR="$LOG_DIR/archive"

# Создаём директорию для архивов
mkdir -p "$ARCHIVE_DIR"

# Текущая дата для имён архивов
DATE_SUFFIX=$(date +%Y%m%d_%H%M%S)

echo "🧹 Начинаю очистку логов..."

# Архивируем основные логи, если они не пустые
for LOG_FILE in bot.log db_update.log supervisor.out; do
    LOG_PATH="$LOG_DIR/$LOG_FILE"
    
    if [ -f "$LOG_PATH" ] && [ -s "$LOG_PATH" ]; then
        ARCHIVE_PATH="$ARCHIVE_DIR/${LOG_FILE%.log}_${DATE_SUFFIX}.log.gz"
        echo "📦 Архивирую $LOG_FILE → $ARCHIVE_PATH"
        gzip -c "$LOG_PATH" > "$ARCHIVE_PATH"
        
        # Очищаем оригинальный файл
        > "$LOG_PATH"
        echo "   ✓ Очищено: $LOG_FILE"
    else
        echo "   ⊘ Пропускаю $LOG_FILE (не существует или пуст)"
    fi
done

# Очищаем старые context_logs (старше 7 дней)
echo ""
echo "🗑️  Удаляю старые context_logs (> 7 дней)..."
DELETED_COUNT=$(find "$LOG_DIR/context_logs" -name "*.txt" -mtime +7 -delete -print 2>/dev/null | wc -l)
echo "   ✓ Удалено файлов: $DELETED_COUNT"

# Очищаем старые архивы (старше 30 дней)
echo ""
echo "🗑️  Удаляю старые архивы (> 30 дней)..."
DELETED_ARCHIVES=$(find "$ARCHIVE_DIR" -name "*.gz" -mtime +30 -delete -print 2>/dev/null | wc -l)
echo "   ✓ Удалено архивов: $DELETED_ARCHIVES"

# Показываем статистику
echo ""
echo "📊 Итоговая статистика:"
echo "   Размер logs/: $(du -sh "$LOG_DIR" 2>/dev/null | cut -f1)"
echo "   Размер archive/: $(du -sh "$ARCHIVE_DIR" 2>/dev/null | cut -f1)"

echo ""
echo "✅ Очистка завершена!"



