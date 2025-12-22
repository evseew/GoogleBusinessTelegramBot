#!/usr/bin/env python3
"""
Скрипт для автоматического обновления groups.json из Google Sheets.

Скачивает Google Sheet как CSV и конвертирует в JSON.
Запускается по cron раз в день.

Использование:
    python scripts/update_groups.py

Требует переменные окружения:
    - SERVICE_ACCOUNT_FILE: путь к ключу сервисного аккаунта
    - GROUPS_SPREADSHEET_ID: ID таблицы Google Sheets
    - GROUPS_SHEET_GID: GID листа (опционально, по умолчанию 0)
"""

import io
import os
import sys
import tempfile
from datetime import datetime

# Добавляем корень проекта в путь для импорта
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Импортируем функции конвертации из существующего скрипта
from scripts.convert_groups_csv import convert_csv_to_json, print_stats, OUTPUT_FILE


# Загружаем .env
load_dotenv(os.path.join(PROJECT_DIR, '.env'))

# Конфигурация
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "service-account-key.json")
SPREADSHEET_ID = os.getenv("GROUPS_SPREADSHEET_ID")
SHEET_GID = os.getenv("GROUPS_SHEET_GID", "0")

# Если путь относительный — делаем абсолютным от корня проекта
if not os.path.isabs(SERVICE_ACCOUNT_FILE):
    SERVICE_ACCOUNT_FILE = os.path.join(PROJECT_DIR, SERVICE_ACCOUNT_FILE)


def log(message: str):
    """Логирование с временной меткой."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def get_sheets_service():
    """Создаёт сервис Google Sheets API."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets.readonly',
                'https://www.googleapis.com/auth/drive.readonly'
            ]
        )
        service = build('sheets', 'v4', credentials=credentials)
        log("✓ Google Sheets API инициализирован")
        return service
    except FileNotFoundError:
        log(f"❌ Файл ключа не найден: {SERVICE_ACCOUNT_FILE}")
        return None
    except Exception as e:
        log(f"❌ Ошибка инициализации Google Sheets API: {e}")
        return None


def get_drive_service():
    """Создаёт сервис Google Drive API для экспорта."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        service = build('drive', 'v3', credentials=credentials)
        log("✓ Google Drive API инициализирован")
        return service
    except Exception as e:
        log(f"❌ Ошибка инициализации Google Drive API: {e}")
        return None


def download_sheet_as_csv(spreadsheet_id: str, gid: str) -> str:
    """
    Скачивает лист Google Sheets как CSV.
    
    Returns:
        Содержимое CSV как строка
    """
    drive_service = get_drive_service()
    if not drive_service:
        raise RuntimeError("Не удалось инициализировать Google Drive API")
    
    # Формируем URL для экспорта конкретного листа как CSV
    # Используем export через Drive API
    export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    
    log(f"📥 Скачиваю лист (GID: {gid}) из таблицы {spreadsheet_id}...")
    
    try:
        # Используем files().export_media для Google Sheets
        request = drive_service.files().export_media(
            fileId=spreadsheet_id,
            mimeType='text/csv'
        )
        
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        
        while not done:
            status, done = downloader.next_chunk()
            if status:
                log(f"   Загрузка: {int(status.progress() * 100)}%")
        
        fh.seek(0)
        csv_content = fh.getvalue().decode('utf-8')
        
        log(f"✓ CSV скачан ({len(csv_content)} байт)")
        return csv_content
        
    except Exception as e:
        log(f"❌ Ошибка скачивания: {e}")
        # Пробуем альтернативный метод через requests
        return download_sheet_via_url(spreadsheet_id, gid)


def download_sheet_via_url(spreadsheet_id: str, gid: str) -> str:
    """
    Альтернативный метод: скачивание через URL.
    Работает если таблица расшарена на сервисный аккаунт.
    """
    import requests
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    
    log("📥 Пробую альтернативный метод скачивания...")
    
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    credentials.refresh(Request())
    
    export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    
    headers = {
        'Authorization': f'Bearer {credentials.token}'
    }
    
    response = requests.get(export_url, headers=headers)
    response.raise_for_status()
    
    csv_content = response.text
    log(f"✓ CSV скачан через URL ({len(csv_content)} байт)")
    return csv_content


def save_csv_and_convert(csv_content: str) -> bool:
    """
    Сохраняет CSV во временный файл и конвертирует в JSON.
    
    Returns:
        True если успешно, False если ошибка
    """
    # Создаём временный файл
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        f.write(csv_content)
        temp_csv_path = f.name
    
    log(f"📝 Временный CSV: {temp_csv_path}")
    
    try:
        # Конвертируем используя существующую функцию
        log("🔄 Конвертация CSV → JSON...")
        data = convert_csv_to_json(temp_csv_path)
        
        # Сохраняем JSON
        import json
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        log(f"✅ JSON сохранён: {OUTPUT_FILE}")
        
        # Выводим статистику
        print_stats(data)
        
        return True
        
    except Exception as e:
        log(f"❌ Ошибка конвертации: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Удаляем временный файл
        try:
            os.unlink(temp_csv_path)
        except:
            pass


def main():
    """Основная функция."""
    log("=" * 50)
    log("🚀 Запуск обновления groups.json из Google Sheets")
    log("=" * 50)
    
    # Проверяем конфигурацию
    if not SPREADSHEET_ID:
        log("❌ Не задан GROUPS_SPREADSHEET_ID в .env")
        sys.exit(1)
    
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        log(f"❌ Файл ключа не найден: {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)
    
    log(f"📊 Spreadsheet ID: {SPREADSHEET_ID}")
    log(f"📋 Sheet GID: {SHEET_GID}")
    log(f"🔑 Service Account: {SERVICE_ACCOUNT_FILE}")
    
    try:
        # Скачиваем CSV
        csv_content = download_sheet_as_csv(SPREADSHEET_ID, SHEET_GID)
        
        if not csv_content or len(csv_content) < 100:
            log("❌ CSV пустой или слишком маленький")
            sys.exit(1)
        
        # Конвертируем и сохраняем
        success = save_csv_and_convert(csv_content)
        
        if success:
            log("=" * 50)
            log("✅ Обновление завершено успешно!")
            log("=" * 50)
            sys.exit(0)
        else:
            log("❌ Обновление завершено с ошибками")
            sys.exit(1)
            
    except Exception as e:
        log(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

