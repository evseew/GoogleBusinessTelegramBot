import sys
import os
import time # используется time.time()
import asyncio
import logging
import datetime # используется datetime.datetime, datetime.timedelta
import glob
import io
from io import BytesIO
import json
import re
import signal # Для корректного завершения
import shutil
from asyncio import Lock # <--- ИЗМЕНЕНО: Убран RLock, т.к. используем кастомный
from collections import defaultdict # Для user_processing_locks
from typing import Optional, List, Dict, Any

# --- Dependency Imports ---
import openai
import chromadb
from dotenv import load_dotenv, find_dotenv, dotenv_values
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import docx
import PyPDF2

from aiogram import Bot, Dispatcher, Router, types as aiogram_types, F
from aiogram.filters import Command
from aiogram.enums import ChatAction # Для статуса "печатает"

# LangChain components
from langchain_openai import OpenAIEmbeddings # Не используется напрямую, но может понадобиться если OpenAI API клиент не будет использоваться для эмбеддингов
from langchain.text_splitter import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_core.documents import Document # Langchain Document

# --- Custom AsyncRLock Implementation (for Python < 3.9) ---
class AsyncRLock:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._owner = None
        self._count = 0

    async def acquire(self):
        current_task = asyncio.current_task()
        if self._owner == current_task:
            self._count += 1
            return True # Уже владеем, просто увеличиваем счетчик

        # Если блокировка занята другой задачей или свободна, пытаемся захватить основной лок
        await self._lock.acquire()
        # После успешного захвата основного лока, мы - владелец
        self._owner = current_task
        self._count = 1
        return True

    def release(self):
        current_task = asyncio.current_task()
        if self._owner != current_task:
            # Получаем имя текущей задачи для более информативного сообщения
            current_task_name = current_task.get_name() if hasattr(current_task, 'get_name') else str(current_task)
            owner_task_name = self._owner.get_name() if self._owner and hasattr(self._owner, 'get_name') else str(self._owner)
            raise RuntimeError(f"Cannot release un-acquired lock or lock acquired by another task. Owner: {owner_task_name}, Current: {current_task_name}")
        
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release() # Освобождаем основной лок только когда счетчик доходит до 0

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

    def locked(self):
        return self._lock.locked()
    
    # Дополнительные методы для отладки, если понадобятся
    def get_owner_task(self):
        return self._owner

    def get_recursion_count(self):
        return self._count
# --- End Custom AsyncRLock ---

# --- Load Environment Variables ---
# load_dotenv(override=True) # <--- Старый вызов load_dotenv закомментирован для новой логики
# print(f"DEBUG: dotenv_path used: {find_dotenv()}") # <--- Старый print закомментирован
# print(f"DEBUG: OPENAI_API_KEY из окружения до getenv: {os.environ.get('OPENAI_API_KEY')}") # <--- Старый print закомментирован

dotenv_path_found = find_dotenv()
print(f"DEBUG: Полный путь к .env файлу, найденный find_dotenv(): {dotenv_path_found}")

if dotenv_path_found and os.path.exists(dotenv_path_found):
    print(f"DEBUG: Попытка загрузить переменные из файла: {dotenv_path_found}")
    # Напрямую парсим значения из .env файла
    parsed_values = dotenv_values(dotenv_path_found)
    raw_key_from_file = parsed_values.get("OPENAI_API_KEY")
    print(f"DEBUG: OPENAI_API_KEY напрямую из файла '{dotenv_path_found}' (через dotenv_values): {raw_key_from_file}")
    
    # Теперь загружаем в os.environ с override=True, используя найденный путь
    load_dotenv(dotenv_path=dotenv_path_found, override=True)
    print(f"DEBUG: load_dotenv(override=True) был вызван для файла: {dotenv_path_found}")
else:
    print(f"DEBUG: .env файл не найден по пути '{dotenv_path_found}' или путь не существует. load_dotenv не будет вызван с конкретным путем.")
    # Пытаемся загрузить .env из стандартных мест (если find_dotenv не нашел, но вдруг)
    load_dotenv(override=True)
    print(f"DEBUG: load_dotenv(override=True) был вызван без указания конкретного пути (поиск по умолчанию).")

print(f"DEBUG: OPENAI_API_KEY из os.environ.get ПОСЛЕ load_dotenv: {os.environ.get('OPENAI_API_KEY')}")
print(f"DEBUG: OPENAI_API_KEY из os.getenv ПОСЛЕ load_dotenv: {os.getenv('OPENAI_API_KEY')}")


# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # <--- Это значение используется приложением
# print(f"DEBUG: OPENAI_API_KEY после getenv: {OPENAI_API_KEY}") # <--- Заменено следующим print
print(f"DEBUG: Итоговое значение OPENAI_API_KEY, присвоенное конфигурационной переменной: {OPENAI_API_KEY}")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", 'service-account-key.json')
FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

try:
    ADMIN_USER_ID_STR = os.getenv("ADMIN_USER_ID")
    if not ADMIN_USER_ID_STR:
        raise ValueError("ADMIN_USER_ID не найден в .env")
    ADMIN_USER_ID = int(ADMIN_USER_ID_STR)
except (ValueError, TypeError) as e:
    logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Некорректное значение ADMIN_USER_ID в .env: {e}")
    sys.exit(1)

try:
    manager_ids_str = os.getenv("MANAGER_USER_IDS", "")
    MANAGER_USER_IDS = [int(id_str.strip()) for id_str in manager_ids_str.split(',') if id_str.strip()]
except (ValueError, TypeError) as e:
    logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Некорректные значения MANAGER_USER_IDS в .env: {e}")
    sys.exit(1)

MESSAGE_BUFFER_SECONDS = int(os.getenv("MESSAGE_BUFFER_SECONDS", "4"))
LOGS_DIR = os.getenv("LOGS_DIR", "./logs/context_logs_telegram")
SILENCE_STATE_FILE = os.getenv("TELEGRAM_SILENCE_STATE_FILE", "telegram_silence_state.json")

VECTOR_DB_BASE_PATH = os.getenv("VECTOR_DB_BASE_PATH_TELEGRAM", "./local_vector_db_telegram")
ACTIVE_DB_INFO_FILE = os.getenv("ACTIVE_DB_INFO_FILE_TELEGRAM", "active_db_path_telegram.txt")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
try:
    _dim_str = os.getenv("OPENAI_EMBEDDING_DIMENSIONS")
    OPENAI_EMBEDDING_DIMENSIONS = int(_dim_str) if _dim_str and _dim_str.lower() != 'none' else None
except ValueError:
    logging.warning(f"Некорректное значение OPENAI_EMBEDDING_DIMENSIONS ('{_dim_str}'), используется None.")
    OPENAI_EMBEDDING_DIMENSIONS = None

CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME_TELEGRAM", "documents_telegram")
RELEVANT_CONTEXT_COUNT = int(os.getenv("RELEVANT_CONTEXT_COUNT", "3"))
OPENAI_RUN_TIMEOUT_SECONDS = int(os.getenv("OPENAI_RUN_TIMEOUT_SECONDS", "90"))
LOG_RETENTION_SECONDS = int(os.getenv("LOG_RETENTION_SECONDS_TELEGRAM", "86400")) # 24 часа
USE_VECTOR_STORE_STR = os.getenv("USE_VECTOR_STORE_TELEGRAM", "True")
USE_VECTOR_STORE = USE_VECTOR_STORE_STR.lower() == 'true'

# Флаги для управления автообновлением базы знаний при управлении через скрипты
# По умолчанию отключены, чтобы избежать дублей с cron/ручными скриптами
ENABLE_STARTUP_KB_UPDATE = os.getenv("ENABLE_STARTUP_KB_UPDATE_TELEGRAM", "False").lower() == 'true'
ENABLE_DAILY_KB_UPDATE = os.getenv("ENABLE_DAILY_KB_UPDATE_TELEGRAM", "False").lower() == 'true'

MESSAGE_LIFETIME_DAYS = int(os.getenv("MESSAGE_LIFETIME_DAYS", "100")) 
MESSAGE_LIFETIME = datetime.timedelta(days=MESSAGE_LIFETIME_DAYS)


# --- Validate Configuration ---
required_vars = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "ASSISTANT_ID": ASSISTANT_ID,
    "FOLDER_ID": FOLDER_ID,
    "ADMIN_USER_ID": ADMIN_USER_ID
}
missing_vars_list = [name for name, value in required_vars.items() if not value and value != 0]
if missing_vars_list:
    logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют переменные окружения: {', '.join(missing_vars_list)}. Проверьте .env файл.")
    sys.exit(1)

# --- Setup Logging ---
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG, # ИЗМЕНЕНО: Установите DEBUG для более подробного логирования
    format='%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- Initialize API Clients ---
try:
    openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
    logger.info("Клиент OpenAI Async инициализирован.")
except Exception as e:
    logger.critical(f"Не удалось инициализировать клиент OpenAI: {e}", exc_info=True)
    sys.exit(1)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

# --- Global State (In-Memory) ---
user_threads: Dict[int, str] = {} 
user_messages: Dict[int, List[Dict[str, Any]]] = {} 

pending_messages: Dict[int, List[str]] = {}  
user_message_timers: Dict[int, asyncio.Task] = {}  
user_processing_locks: defaultdict[int, AsyncRLock] = defaultdict(AsyncRLock) # <--- ИЗМЕНЕНО: Используем наш AsyncRLock

chat_silence_state: Dict[int, bool] = {} 

# --- Vector Store (ChromaDB) ---
vector_collection: Optional[chromadb.api.models.Collection.Collection] = None

def _get_active_db_full_path_telegram() -> Optional[str]: # Renamed from _get_active_db_subpath_telegram
    try:
        active_db_info_filepath = os.path.join(VECTOR_DB_BASE_PATH, ACTIVE_DB_INFO_FILE)
        if os.path.exists(active_db_info_filepath):
            with open(active_db_info_filepath, "r", encoding="utf-8") as f:
                active_subdir_or_fullname = f.read().strip() 
            
            if not active_subdir_or_fullname:
                logger.warning(f"Файл '{ACTIVE_DB_INFO_FILE}' (TG) пуст.")
                return None

            # Проверяем, является ли сохраненное значение полным путем или относительным
            # Это для обратной совместимости, если раньше сохранялся относительный путь
            potential_full_path = active_subdir_or_fullname
            if not os.path.isabs(potential_full_path): # Если это не абсолютный путь
                 potential_full_path = os.path.join(VECTOR_DB_BASE_PATH, active_subdir_or_fullname)
            
            if os.path.isdir(potential_full_path): 
                logger.info(f"Найдена активная директория БД (TG): '{potential_full_path}'")
                return potential_full_path
            else: 
                logger.warning(f"В файле '{ACTIVE_DB_INFO_FILE}' (TG) указан путь '{active_subdir_or_fullname}', но директория '{potential_full_path}' не существует.")
                return None
        else: 
            logger.info(f"Файл информации об активной БД '{ACTIVE_DB_INFO_FILE}' (TG) не найден.")
            return None
    except Exception as e:
        logger.error(f"Ошибка при чтении файла информации об активной БД (TG): {e}", exc_info=True)
        return None

async def _initialize_active_vector_collection_telegram():
    global vector_collection
    active_db_full_path = _get_active_db_full_path_telegram()
    if active_db_full_path:
        try:
            def _init_chroma():
                chroma_client_init = chromadb.PersistentClient(path=active_db_full_path)
                return chroma_client_init.get_or_create_collection(
                    name=CHROMA_COLLECTION_NAME,
                )
            vector_collection = await asyncio.to_thread(_init_chroma)
            logger.info(f"Успешно подключено к ChromaDB (TG): '{active_db_full_path}'. Коллекция: '{CHROMA_COLLECTION_NAME}'.")
            if vector_collection:
                count = await asyncio.to_thread(vector_collection.count)
                logger.info(f"Документов в активной коллекции (TG) при старте: {count}")
        except Exception as e:
            logger.error(f"Ошибка инициализации ChromaDB (TG) для пути '{active_db_full_path}': {e}. Поиск по базе знаний будет недоступен.", exc_info=True)
            vector_collection = None
    else:
        logger.warning("Не удалось определить активную директорию БД (TG). База знаний будет недоступна.")
        vector_collection = None

# --- Google Drive ---
drive_service_instance = None # Инициализируется в main

def get_drive_service_sync(): 
    global drive_service_instance
    if drive_service_instance:
        return drive_service_instance
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        drive_service_instance = build('drive', 'v3', credentials=credentials)
        logger.info("Сервис Google Drive инициализирован (синхронно).")
        return drive_service_instance
    except FileNotFoundError:
        logger.error(f"Файл ключа Google Service Account не найден: {SERVICE_ACCOUNT_FILE}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении сервиса Google Drive: {e}", exc_info=True)
        return None

def _download_file_content_sync(service, file_id, export_mime_type=None): 
    if export_mime_type:
        request = service.files().export_media(fileId=file_id, mimeType=export_mime_type)
    else:
        request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done: # Corrected loop condition
        status, done = downloader.next_chunk()
        if status: logger.debug(f"Загрузка файла {file_id} (TG): {int(status.progress() * 100)}%.")
    fh.seek(0)
    return fh

def read_data_from_drive_sync() -> List[Dict[str,str]]: 
    service = get_drive_service_sync()
    if not service:
        logger.error("Чтение из Google Drive (TG) невозможно: сервис не инициализирован.")
        return []
    
    result_docs: List[Dict[str,str]] = []
    try:
        files_response = service.files().list(
            q=f"'{FOLDER_ID}' in parents and trashed=false",
            fields="files(id, name, mimeType)", pageSize=1000
        ).execute()
        files = files_response.get('files', [])
        logger.info(f"Найдено {len(files)} файлов в папке Google Drive (TG).")

        downloader_map = {
            'application/vnd.google-apps.document': lambda s, f_id: download_google_doc_sync(s, f_id),
            'application/pdf': lambda s, f_id: download_pdf_sync(s, f_id),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': lambda s, f_id: download_docx_sync(s, f_id),
            'text/plain': lambda s, f_id: download_text_sync(s, f_id),
            'text/markdown': lambda s, f_id: download_text_sync(s, f_id),
        }

        for file_item in files:
            file_id, mime_type, file_name = file_item['id'], file_item['mimeType'], file_item['name']
            if mime_type in downloader_map:
                logger.info(f"Обработка файла (TG): '{file_name}' (ID: {file_id}, Type: {mime_type})")
                try:
                    content_str = downloader_map[mime_type](service, file_id)
                    if content_str and content_str.strip():
                        result_docs.append({'name': file_name, 'content': content_str})
                        logger.info(f"Успешно прочитан файл (TG): '{file_name}' ({len(content_str)} симв)")
                    else:
                        logger.warning(f"Файл '{file_name}' (TG) пуст или не удалось извлечь контент.")
                except Exception as e_read_file:
                    logger.error(f"Ошибка чтения файла '{file_name}' (TG): {e_read_file}", exc_info=True)
            else:
                logger.debug(f"Файл '{file_name}' (TG) имеет неподдерживаемый тип ({mime_type}).")
    except Exception as e:
        logger.error(f"Критическая ошибка при чтении из Google Drive (TG): {e}", exc_info=True)
        return []
    logger.info(f"Чтение из Google Drive (TG) завершено. Прочитано {len(result_docs)} документов.")
    return result_docs

def download_google_doc_sync(service, file_id) -> str: 
    fh = _download_file_content_sync(service, file_id, export_mime_type='text/plain')
    return fh.getvalue().decode('utf-8', errors='ignore')

def download_pdf_sync(service, file_id) -> str: 
    fh = _download_file_content_sync(service, file_id)
    try:
        pdf_reader = PyPDF2.PdfReader(fh)
        return "".join(page.extract_text() + "\n" for page in pdf_reader.pages if page.extract_text())
    except Exception as e:
         logger.error(f"Ошибка обработки PDF (ID: {file_id}, TG): {e}", exc_info=True)
         return ""

def download_docx_sync(service, file_id) -> str: 
    fh = _download_file_content_sync(service, file_id)
    try:
        doc = docx.Document(fh)
        return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text)
    except Exception as e:
         logger.error(f"Ошибка обработки DOCX (ID: {file_id}, TG): {e}", exc_info=True)
         return ""

def download_text_sync(service, file_id) -> str: 
    fh = _download_file_content_sync(service, file_id)
    try:
        return fh.getvalue().decode('utf-8')
    except UnicodeDecodeError:
         logger.warning(f"Не удалось декодировать {file_id} (TG) как UTF-8, пробуем cp1251.")
         try: return fh.getvalue().decode('cp1251', errors='ignore')
         except Exception as e_decode:
              logger.error(f"Не удалось декодировать {file_id} (TG): {e_decode}")
              return ""

# --- Helper Functions ---
async def get_or_create_thread(user_id: int) -> Optional[str]:
    if user_id in user_threads:
        thread_id = user_threads[user_id]
        try:
            await openai_client.beta.threads.messages.list(thread_id=thread_id, limit=1)
            logger.info(f"Используем существующий тред {thread_id} для user_id={user_id} (TG)")
            return thread_id
        except openai.NotFoundError:
            logger.warning(f"Тред {thread_id} не найден в OpenAI для user_id={user_id} (TG). Создаем новый.")
            if user_id in user_threads: del user_threads[user_id]
            save_user_threads_to_file()
        except Exception as e:
            logger.error(f"Ошибка доступа к треду {thread_id} для user_id={user_id} (TG): {e}. Создаем новый.")
            if user_id in user_threads: del user_threads[user_id]
            save_user_threads_to_file()
    try:
        logger.info(f"Создаем новый тред для user_id={user_id} (TG)...")
        thread = await openai_client.beta.threads.create()
        thread_id = thread.id
        user_threads[user_id] = thread_id
        save_user_threads_to_file()
        user_messages[user_id] = [] 
        logger.info(f"Создан новый тред {thread_id} для user_id={user_id} (TG)")
        # --- Досылаем историю в новый тред ---
        await replay_history_to_thread(user_id, thread_id, max_messages=30)
        return thread_id
    except Exception as e:
        logger.error(f"Критическая ошибка при создании нового треда для user_id={user_id} (TG): {e}", exc_info=True)
        return None

async def cleanup_old_messages_in_memory(): 
    current_time = datetime.datetime.now()
    for user_id in list(user_messages.keys()):
        async with user_processing_locks[user_id]:
            if user_id in user_messages:
                user_messages[user_id] = [
                    msg for msg in user_messages[user_id]
                    if current_time - msg['timestamp'] < MESSAGE_LIFETIME
                ]

async def add_message_to_history(user_id: int, role: str, content: str):
    logger.debug(f"add_message_to_history: Попытка получить блокировку для user_id={user_id}")
    async with user_processing_locks[user_id]:
        logger.debug(f"add_message_to_history: Блокировка для user_id={user_id} ПОЛУЧЕНА.")
        if user_id not in user_messages:
            user_messages[user_id] = []
        user_messages[user_id].append({
            'role': role,
            'content': content,
            'timestamp': datetime.datetime.now()
        })
        logger.debug(f"add_message_to_history: Сообщение добавлено для user_id={user_id}. Блокировка будет ОСВОБОЖДЕНА.")

# --- Silence Mode Management ---
async def save_silence_state_to_file():
    logger.debug("Сохранение состояния режимов молчания (TG) в файл...")
    data_to_save = {str(chat_id): True for chat_id, is_silent in chat_silence_state.items() if is_silent}
    try:
        def _save():
            with open(SILENCE_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=4)
        await asyncio.to_thread(_save)
        logger.info(f"Состояние режимов молчания (TG) сохранено в {SILENCE_STATE_FILE}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении состояния режимов молчания (TG): {e}", exc_info=True)

async def load_silence_state_from_file():
    global chat_silence_state
    logger.info("Загрузка состояния режимов молчания (TG) из файла...")
    try:
        def _load():
            if not os.path.exists(SILENCE_STATE_FILE):
                logger.info(f"Файл {SILENCE_STATE_FILE} (TG) не найден. Пропускаем загрузку.")
                return None
            with open(SILENCE_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        
        loaded_data = await asyncio.to_thread(_load)
        if not loaded_data:
            return

        restored_count = 0
        for chat_id_str, should_be_silent in loaded_data.items():
            try:
                chat_id = int(chat_id_str)
                if should_be_silent: 
                    chat_silence_state[chat_id] = True
                    logger.info(f"Восстановлен постоянный режим молчания для chat_id={chat_id} (TG)")
                    restored_count += 1
            except (ValueError, KeyError) as e:
                logger.error(f"Ошибка при обработке записи (TG) для chat_id_str='{chat_id_str}': {e}", exc_info=True)
        
        if restored_count > 0:
            logger.info(f"Успешно восстановлено {restored_count} состояний постоянного молчания (TG).")
        else:
            logger.info("Активных состояний постоянного молчания для восстановления (TG) не найдено.")
    except FileNotFoundError:
        logger.info(f"Файл {SILENCE_STATE_FILE} (TG) не найден. Запуск с чистым состоянием молчания.")
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON из файла {SILENCE_STATE_FILE} (TG). Файл может быть поврежден.")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при загрузке состояния режимов молчания (TG): {e}", exc_info=True)

async def is_chat_silent(chat_id: int) -> bool:
    return chat_silence_state.get(chat_id, False)

async def set_chat_silence_permanently(chat_id: int, silent: bool):
    log_prefix = f"set_chat_silence_permanently(chat:{chat_id}, silent:{silent}):"
    current_state = chat_silence_state.get(chat_id, False)
    if current_state == silent:
        logger.debug(f"{log_prefix} Состояние постоянного молчания не изменилось ({silent}).")
        return

    if silent:
        chat_silence_state[chat_id] = True
        logger.info(f"{log_prefix} Включен ПОСТОЯННЫЙ режим молчания.")
    else: 
        if chat_id in chat_silence_state:
            del chat_silence_state[chat_id]
            logger.info(f"{log_prefix} ПОСТОЯННЫЙ режим молчания снят.")
        else:
            logger.debug(f"{log_prefix} Попытка снять молчание, но чат не был в списке.")
    await save_silence_state_to_file()

# --- Message Buffering ---
async def schedule_buffered_processing(user_id: int, chat_id: int, business_connection_id: Optional[str]):
    log_prefix = f"schedule_buffered_processing(user:{user_id}, chat:{chat_id}):"
    current_task = asyncio.current_task()
    try:
        logger.debug(f"{log_prefix} Ожидание {MESSAGE_BUFFER_SECONDS} секунд...")
        await asyncio.sleep(MESSAGE_BUFFER_SECONDS)

        task_in_dict = user_message_timers.get(user_id)
        if task_in_dict is not current_task:
            logger.info(f"{log_prefix} Таймер сработал, но он устарел. Обработка отменена.")
            return

        if user_id in user_message_timers: # Проверка перед удалением
             del user_message_timers[user_id]
        logger.debug(f"{log_prefix} Таймер сработал и удален. Вызов process_buffered_messages.")
        asyncio.create_task(process_buffered_messages(user_id, chat_id, business_connection_id))

    except asyncio.CancelledError:
        logger.info(f"{log_prefix} Таймер отменен.")
    except Exception as e:
        logger.error(f"{log_prefix} Ошибка в задаче таймера: {str(e)}", exc_info=True)
        if user_id in user_message_timers and user_message_timers.get(user_id) is current_task:
            del user_message_timers[user_id]

async def process_buffered_messages(user_id: int, chat_id: int, business_connection_id: Optional[str]):
    log_prefix = f"process_buffered_messages(user:{user_id}, chat:{chat_id}):"
    async with user_processing_locks[user_id]: 
        logger.debug(f"{log_prefix} Блокировка для user_id={user_id} получена.")
        messages_to_process = pending_messages.pop(user_id, [])
        
        if user_id in user_message_timers: 
            logger.warning(f"{log_prefix} Таймер для user_id={user_id} все еще существовал! Отменяем и удаляем.")
            timer_to_cancel = user_message_timers.pop(user_id)
            if not timer_to_cancel.done():
                try: timer_to_cancel.cancel()
                except Exception as e_inner_cancel: logger.debug(f"{log_prefix} Ошибка отмены таймера: {e_inner_cancel}")

        # Повторная проверка режима молчания перед обработкой буфера
        try:
            if await is_chat_silent(chat_id):
                logger.info(f"{log_prefix} Чат в режиме молчания при обработке буфера. Ответ не будет отправлен.")
                return
        except Exception as silence_check_error:
            logger.error(f"{log_prefix} Ошибка повторной проверки молчания: {silence_check_error}")

        if not messages_to_process:
            logger.info(f"{log_prefix} Нет сообщений в буфере для user_id={user_id}.")
            return

        combined_input = "\n".join(messages_to_process)
        num_messages = len(messages_to_process)
        logger.info(f'{log_prefix} Объединенный запрос для user_id={user_id} ({num_messages} сообщ.): "{combined_input[:200]}..."')
        
        try:
            action_params = {"chat_id": chat_id, "action": ChatAction.TYPING}
            if business_connection_id: action_params["business_connection_id"] = business_connection_id
            await bot.send_chat_action(**action_params)
            logger.debug(f"{log_prefix} Отправлен статус 'typing'.")

            response_text = await chat_with_assistant(user_id, combined_input)
            
            message_params = {"chat_id": chat_id, "text": response_text}
            if business_connection_id: message_params["business_connection_id"] = business_connection_id
            await bot.send_message(**message_params)
            logger.info(f"{log_prefix} Успешно обработан и отправлен ответ для user_id={user_id}.")
        except Exception as e:
            logger.error(f"{log_prefix} Ошибка при обработке или отправке ответа для user_id={user_id}: {e}", exc_info=True)
            try:
                error_msg_params = {"chat_id": chat_id, "text": "Произошла внутренняя ошибка. Попробуйте позже."}
                if business_connection_id: error_msg_params["business_connection_id"] = business_connection_id
                await bot.send_message(**error_msg_params)
            except Exception as send_err_e: logger.error(f"{log_prefix} Не удалось отправить сообщение об ошибке user_id={user_id}: {send_err_e}")
        finally:
            logger.debug(f"{log_prefix} Блокировка для user_id={user_id} освобождена.")

# --- OpenAI Assistant Interaction ---
async def chat_with_assistant(user_id: int, user_input: str) -> str:
    log_prefix = f"chat_with_assistant(user:{user_id}):"
    logger.info(f"{log_prefix} Запрос: {user_input[:100]}...")

    thread_id = await get_or_create_thread(user_id)
    if not thread_id:
        return "Произошла внутренняя ошибка (не удалось создать или получить тред OpenAI)."

    context = ""
    if USE_VECTOR_STORE and vector_collection:
        logger.debug(f"{log_prefix} Попытка получить контекст из векторной базы...")
        try: context = await get_relevant_context_telegram(user_input, k=RELEVANT_CONTEXT_COUNT)
        except Exception as e_ctx: logger.error(f"{log_prefix} Ошибка получения контекста: {e_ctx}", exc_info=True)
        logger.debug(f"{log_prefix} Контекст из векторной базы получен (или пуст).")

    full_prompt = user_input
    if context:
        full_prompt = (
            f"Используй следующую информацию из базы знаний для ответа:\n"
            f"--- НАЧАЛО КОНТЕКСТА ---\n{context}\n--- КОНЕЦ КОНТЕКСТА ---\n\n"
            f"Вопрос пользователя: {user_input}"
        )
        logger.info(f"{log_prefix} Контекст добавлен к запросу.")
    else:
        logger.info(f"{log_prefix} Контекст не найден или база знаний отключена.")

    # --- ДОБАВЛЯЕМ ДАТУ И ВРЕМЯ В НАЧАЛО PROMPT ---
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    full_prompt = f"Сегодня: {now_str}.\n" + full_prompt
    # --- КОНЕЦ ДОБАВЛЕНИЯ ---

    logger.debug(f"{log_prefix} Вызов add_message_to_history для user_input...")
    await add_message_to_history(user_id, "user", user_input) 
    logger.debug(f"{log_prefix} add_message_to_history для user_input ВЫПОЛНЕН.")

    MAX_RETRIES = 2  # всего 2 попытки (первая + одна повторная)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"{log_prefix} Попытка {attempt} отправки запроса в OpenAI...")
            # --- основной блок отправки запроса (скопировано из текущей реализации) ---
            logger.debug(f"{log_prefix} Проверка активных runs для треда {thread_id} ПЕРЕД созданием нового сообщения...")
            active_runs_response = await openai_client.beta.threads.runs.list(thread_id=thread_id)
            active_runs_to_cancel = [run for run in active_runs_response.data if run.status in ['queued', 'in_progress', 'requires_action']]
            if active_runs_to_cancel:
                logger.warning(f"{log_prefix} Найдено {len(active_runs_to_cancel)} активных/ожидающих runs. Отменяем...")
                for run_to_cancel in active_runs_to_cancel:
                    try:
                        logger.debug(f"{log_prefix} Попытка отменить run {run_to_cancel.id}...")
                        await openai_client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run_to_cancel.id)
                        logger.info(f"{log_prefix} Отменен run {run_to_cancel.id}")
                    except Exception as cancel_error: logger.warning(f"{log_prefix} Не удалось отменить run {run_to_cancel.id}: {cancel_error}")
            logger.debug(f"{log_prefix} Проверка активных runs ЗАВЕРШЕНА.")
            
            logger.debug(f"{log_prefix} Попытка создать сообщение в треде {thread_id}...")
            await openai_client.beta.threads.messages.create(thread_id=thread_id, role="user", content=full_prompt)
            logger.info(f"{log_prefix} Сообщение добавлено в тред {thread_id}. Попытка запустить run...")

            current_run = await openai_client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ASSISTANT_ID)
            logger.info(f"{log_prefix} Запущен новый run {current_run.id}. Начало опроса статуса...")

            start_time = time.time()
            run_completed_successfully = False
            while time.time() - start_time < OPENAI_RUN_TIMEOUT_SECONDS:
                await asyncio.sleep(1.5) 
                run_status = await openai_client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=current_run.id)
                logger.debug(f"{log_prefix} Статус run {current_run.id}: {run_status.status}")
                if run_status.status == 'completed':
                    logger.info(f"{log_prefix} Run {current_run.id} успешно завершен.")
                    run_completed_successfully = True
                    break
                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    error_message_detail = f"Run {current_run.id} статус '{run_status.status}'."
                    last_error = getattr(run_status, 'last_error', None)
                    if last_error: error_message_detail += f" Ошибка: {last_error.message} (Код: {last_error.code})"
                    logger.error(f"{log_prefix} {error_message_detail}")
                    await log_context_telegram(user_id, user_input, context, f"ОШИБКА OPENAI: {error_message_detail}")
                    break  # не retry, а сразу выход
                elif run_status.status == 'requires_action':
                     logger.warning(f"{log_prefix} Run {current_run.id} требует действия (Function Calling?).")
                     await openai_client.beta.threads.runs.cancel(thread_id=thread_id, run_id=current_run.id)
                     await log_context_telegram(user_id, user_input, context, "ОШИБКА OPENAI: requires_action")
                     break  # не retry, а сразу выход
            
            if not run_completed_successfully:
                logger.warning(f"{log_prefix} Таймаут ({OPENAI_RUN_TIMEOUT_SECONDS}s) для run {current_run.id}")
                try:
                    await openai_client.beta.threads.runs.cancel(thread_id=thread_id, run_id=current_run.id)
                    logger.info(f"{log_prefix} Отменен run {current_run.id} из-за таймаута.")
                except Exception as cancel_error: logger.warning(f"{log_prefix} Ошибка отмены run {current_run.id} после таймаута: {cancel_error}")
                await log_context_telegram(user_id, user_input, context, "ОШИБКА OPENAI: Таймаут")
                if attempt < MAX_RETRIES:
                    logger.info(f"{log_prefix} Повторная попытка через 2 секунды...")
                    await asyncio.sleep(2)
                    continue
                else:
                    return "Ошибка доставки сообщения. Попробуйте позже."

            messages_response = await openai_client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=5)
            assistant_response_content = None
            for msg in messages_response.data:
                if msg.role == "assistant" and msg.run_id == current_run.id:
                    if msg.content and msg.content[0].type == 'text': # Предполагаем один текстовый блок
                        assistant_response_content = msg.content[0].text.value
                        logger.info(f"{log_prefix} Получен релевантный ответ: {assistant_response_content[:100]}...")
                        break
            
            if assistant_response_content:
                await add_message_to_history(user_id, "assistant", assistant_response_content)
                await log_context_telegram(user_id, user_input, context, assistant_response_content)
                return assistant_response_content
            else:
                logger.warning(f"{log_prefix} Текстовый ответ от ассистента для run {current_run.id} не найден.")
                await log_context_telegram(user_id, user_input, context, "ОТВЕТ АССИСТЕНТА НЕ НАЙДЕН ИЛИ ПУСТ")
                return "Ошибка доставки сообщения. Попробуйте позже."
        except openai.APIError as e: # Более общая ошибка API OpenAI
            logger.error(f"{log_prefix} Ошибка OpenAI API: {e}", exc_info=True)
            if attempt < MAX_RETRIES:
                logger.info(f"{log_prefix} Повторная попытка через 2 секунды после ошибки OpenAI API...")
                await asyncio.sleep(2)
                continue
            else:
                return f"Ошибка OpenAI: {str(e)}. Попробуйте позже."
        except Exception as e:
            logger.error(f"{log_prefix} Непредвиденная ошибка: {e}", exc_info=True)
            await log_context_telegram(user_id, user_input, context, f"НЕПРЕДВИДЕННАЯ ОШИБКА: {e}")
            if attempt < MAX_RETRIES:
                logger.info(f"{log_prefix} Повторная попытка через 2 секунды после непредвиденной ошибки...")
                await asyncio.sleep(2)
                continue
            else:
                return "Ошибка доставки сообщения. Попробуйте позже."

# --- Vector Store Management (ChromaDB) ---
async def get_relevant_context_telegram(query: str, k: int) -> str:
    if not vector_collection:
        logger.warning("Запрос контекста (TG), но vector_collection не инициализирована.")
        return ""
    try:
        try:
            query_embedding_response = await openai_client.embeddings.create(
                 input=[query], model=OPENAI_EMBEDDING_MODEL, dimensions=OPENAI_EMBEDDING_DIMENSIONS
            )
            query_embedding = query_embedding_response.data[0].embedding
            logger.debug(f"Эмбеддинг для запроса (TG) '{query[:50]}...' создан.")
        except Exception as e_embed:
            logger.error(f"Ошибка создания эмбеддинга (TG): {e_embed}", exc_info=True)
            return ""

        def _query_chroma():
            return vector_collection.query(query_embeddings=[query_embedding], n_results=k, include=["documents", "metadatas"]) # Убрали distances для упрощения
        results = await asyncio.to_thread(_query_chroma)
        logger.debug(f"Поиск в ChromaDB (TG) для '{query[:50]}...' выполнен.")

        if not results or not results.get("ids") or not results["ids"][0] or \
           not results.get("documents") or not results["documents"][0]:
            logger.info(f"Релевантных документов (TG) не найдено для: '{query[:50]}...'")
            return ""

        documents = results["documents"][0]
        metadatas = results["metadatas"][0] if results.get("metadatas") and results["metadatas"][0] else [{}] * len(documents)
        context_pieces = []
        logger.info(f"Найдено {len(documents)} док-в (TG) для '{query[:50]}...'. Топ {k}:")
        for i, doc_content in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            source = meta.get('source', 'Неизвестный источник')
            logger.info(f"  #{i+1} (TG): Источник='{source}', Контент='{doc_content[:100]}...'")
            context_pieces.append(f"Из документа '{source}':\n{doc_content}")

        if not context_pieces: return ""
        return "\n\n---\n\n".join(context_pieces)
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при получении контекста (TG): {e}", exc_info=True)
        return ""

async def update_vector_store_telegram(chat_id_to_notify: Optional[int] = None) -> Dict[str, Any]:
    logger.info("--- Запуск обновления базы знаний (TG) ---")
    os.makedirs(VECTOR_DB_BASE_PATH, exist_ok=True)
    timestamp_dir_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_new_tg"
    new_db_subpath = timestamp_dir_name 
    new_db_full_path = os.path.join(VECTOR_DB_BASE_PATH, new_db_subpath)
    logger.info(f"Новая директория для БД (TG): {new_db_full_path}")

    previous_active_full_path = _get_active_db_full_path_telegram() 

    try:
        os.makedirs(new_db_full_path, exist_ok=True)
    except Exception as e_mkdir:
        logger.error(f"Не удалось создать директорию '{new_db_full_path}' (TG): {e_mkdir}.", exc_info=True)
        return {"success": False, "error": f"Failed to create temp dir: {e_mkdir}", "added_chunks": 0, "total_chunks": 0}

    temp_vector_collection: Optional[chromadb.api.models.Collection.Collection] = None
    try:
        def _init_temp_chroma():
            temp_chroma_client = chromadb.PersistentClient(path=new_db_full_path)
            return temp_chroma_client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)
        temp_vector_collection = await asyncio.to_thread(_init_temp_chroma)
        logger.info(f"Временная коллекция '{CHROMA_COLLECTION_NAME}' (TG) создана/получена в '{new_db_full_path}'.")

        logger.info("Получение данных из Google Drive (TG)...")
        documents_data = await asyncio.to_thread(read_data_from_drive_sync)
        if not documents_data:
            logger.warning("Документы в Google Drive (TG) не найдены. Обновление отменено.")
            if os.path.exists(new_db_full_path):
                await asyncio.to_thread(shutil.rmtree, new_db_full_path)
            return {"success": False, "error": "No documents in Google Drive", "added_chunks": 0, "total_chunks": 0}
        
        logger.info(f"Получено {len(documents_data)} документов из Google Drive (TG).")
        all_texts, all_metadatas = [], []
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")])
        MD_SECTION_MAX_LEN = 2000 

        for doc_info in documents_data:
            doc_name, doc_content_str = doc_info['name'], doc_info['content']
            if not doc_content_str or not doc_content_str.strip():
                logger.warning(f"Документ '{doc_name}' (TG) пуст.")
                continue
            
            enhanced_doc_content = f"Документ: {doc_name}\n\n{doc_content_str}" # ИСПРАВЛЕНО \n
            chunk_idx = 0
            is_md = doc_name.lower().endswith(('.md', '.markdown'))
            try:
                target_splits = markdown_splitter.split_text(enhanced_doc_content) if is_md else text_splitter.split_text(enhanced_doc_content)
                
                for item_split in target_splits:
                    page_content = item_split.page_content if isinstance(item_split, Document) else item_split
                    current_metadata = item_split.metadata if isinstance(item_split, Document) else {}
                    
                    if is_md and len(page_content) > MD_SECTION_MAX_LEN and not isinstance(item_split, Document): # Дополнительная проверка для MD без Document
                        sub_chunks = text_splitter.split_text(page_content)
                        for sub_chunk_text in sub_chunks:
                            all_texts.append(sub_chunk_text)
                            all_metadatas.append({"source": doc_name, **current_metadata, "type": "md_split", "chunk": chunk_idx})
                            chunk_idx += 1
                    elif isinstance(item_split, Document) and len(page_content) > MD_SECTION_MAX_LEN : # Если это Document и длинный
                        sub_chunks = text_splitter.split_text(page_content)
                        for sub_chunk_text in sub_chunks:
                            all_texts.append(sub_chunk_text)
                            all_metadatas.append({"source": doc_name, **current_metadata, "type": "doc_split", "chunk": chunk_idx}) # type: doc_split
                            chunk_idx +=1
                    else:
                        all_texts.append(page_content)
                        all_metadatas.append({"source": doc_name, **current_metadata, "type": "md" if is_md else "text", "chunk": chunk_idx})
                        chunk_idx += 1
                logger.info(f"Документ '{doc_name}' (TG) разбит на {chunk_idx} чанков.")
            except Exception as e_split:
                logger.error(f"Ошибка разбиения '{doc_name}' (TG): {e_split}", exc_info=True)
                try: # Fallback
                    chunks = text_splitter.split_text(enhanced_doc_content)
                    chunk_idx_fb = 0 
                    for chunk_text in chunks:
                        all_texts.append(chunk_text)
                        all_metadatas.append({"source": doc_name, "type": "text_fallback", "chunk": chunk_idx_fb})
                        chunk_idx_fb += 1
                    logger.info(f"Документ '{doc_name}' (TG) (fallback) разбит на {chunk_idx_fb} чанков.")
                except Exception as e_fallback: logger.error(f"Ошибка fallback-разбиения '{doc_name}' (TG): {e_fallback}", exc_info=True)
        
        if not all_texts:
            logger.warning("Нет текстовых данных для добавления в базу (TG).")
            if os.path.exists(new_db_full_path):
                await asyncio.to_thread(shutil.rmtree, new_db_full_path)
            return {"success": False, "error": "No text data to add", "added_chunks": 0, "total_chunks": 0}

        logger.info(f"Создание эмбеддингов для {len(all_texts)} чанков (TG)...")
        embeddings_response = await openai_client.embeddings.create(
            input=all_texts, model=OPENAI_EMBEDDING_MODEL, dimensions=OPENAI_EMBEDDING_DIMENSIONS
        )
        all_embeddings = [item.embedding for item in embeddings_response.data]
        all_ids = [f"{meta['source']}_{meta.get('type','unk')}_{meta['chunk']}_{i}" for i, meta in enumerate(all_metadatas)] # Упрощенные ID

        if temp_vector_collection:
            def _add_to_chroma():
                temp_vector_collection.add(ids=all_ids, embeddings=all_embeddings, metadatas=all_metadatas, documents=all_texts)
                return temp_vector_collection.count()
            final_total = await asyncio.to_thread(_add_to_chroma)
            final_added = len(all_ids)
            logger.info(f"Успешно добавлено {final_added} чанков (TG). Всего: {final_total}.")
        else: # Не должно случиться
            logger.error("temp_vector_collection (TG) не инициализирована!")
            if os.path.exists(new_db_full_path):
                await asyncio.to_thread(shutil.rmtree, new_db_full_path)
            return {"success": False, "error": "temp_vector_collection is None", "added_chunks": 0, "total_chunks": 0}

        active_db_info_filepath = os.path.join(VECTOR_DB_BASE_PATH, ACTIVE_DB_INFO_FILE)
        with open(active_db_info_filepath, "w", encoding="utf-8") as f: f.write(new_db_subpath) # <--- ИЗМЕНЕНО: сохраняем только имя поддиректории
        logger.info(f"Подпуть к новой активной базе (TG) '{new_db_subpath}' сохранен в '{active_db_info_filepath}'. Активная директория БД: '{new_db_full_path}'") # <--- ИЗМЕНЕНО: сообщение в логе

        await _initialize_active_vector_collection_telegram()
        if not vector_collection:
             logger.error("Критическая ошибка (TG): не удалось перезагрузить vector_collection!")
             return {"success": False, "error": "Failed to reload global vector_collection", "added_chunks": final_added, "total_chunks": final_total}
        
        if previous_active_full_path and previous_active_full_path != new_db_full_path and os.path.exists(previous_active_full_path):
            try:
                await asyncio.to_thread(shutil.rmtree, previous_active_full_path)
                logger.info(f"Удалена предыдущая директория БД (TG): '{previous_active_full_path}'")
            except Exception as e_rm_old: logger.error(f"Не удалось удалить предыдущую БД (TG) '{previous_active_full_path}': {e_rm_old}", exc_info=True)
        
        logger.info("--- Обновление базы знаний (TG) успешно завершено ---")
        return {"success": True, "added_chunks": final_added, "total_chunks": final_total, "new_active_path": new_db_full_path}

    except openai.APIError as e_openai:
         logger.error(f"OpenAI API ошибка (TG): {e_openai}", exc_info=True)
         if os.path.exists(new_db_full_path):
             await asyncio.to_thread(shutil.rmtree, new_db_full_path)
         return {"success": False, "error": f"OpenAI API error: {e_openai}", "added_chunks": 0, "total_chunks": 0}
    except Exception as e_main_update:
        logger.error(f"Критическая ошибка обновления БЗ (TG): {e_main_update}", exc_info=True)
        if os.path.exists(new_db_full_path):
            await asyncio.to_thread(shutil.rmtree, new_db_full_path)
        return {"success": False, "error": f"Critical update error: {e_main_update}", "added_chunks": 0, "total_chunks": 0}

# --- Telegram Command Handlers ---
@router.message(Command("start"))
async def start_command(message: aiogram_types.Message):
    await message.answer("👋 Здравствуйте! Обновляю базу знаний...")
    asyncio.create_task(run_update_and_notify_telegram(message.chat.id))

async def run_update_and_notify_telegram(chat_id: int):
    logger.info(f"Обновление БЗ (TG) для чата {chat_id}...")
    update_result = await update_vector_store_telegram(chat_id_to_notify=chat_id)
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    user_message = f"🔔 Отчет об обновлении БЗ ({current_time}):\n"
    if update_result.get("success"):
        user_message += (f"✅ Успешно!\n➕ Добавлено: {update_result.get('added_chunks', 'N/A')}\n"
                         f"📊 Всего: {update_result.get('total_chunks', 'N/A')}\n")
        if update_result.get("new_active_path"): user_message += f"📁 Путь: {os.path.basename(update_result['new_active_path'])}" # Показываем только имя папки
    else:
        user_message += f"❌ Ошибка: {update_result.get('error', 'N/A')}"
    
    try: await bot.send_message(chat_id, user_message)
    except Exception as e: logger.error(f"Ошибка отправки уведомления пользователю {chat_id} (TG): {e}")

    if ADMIN_USER_ID and chat_id != ADMIN_USER_ID: # Дублируем админу, если это не он инициировал
        try: await bot.send_message(ADMIN_USER_ID, "[Авто] " + user_message)
        except Exception as e: logger.error(f"Ошибка отправки уведомления админу (TG): {e}")

@router.message(Command("update"))
async def update_knowledge_command(message: aiogram_types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ Нет прав!")
        return
    await message.answer("🔄 Обновляю базу знаний (TG)...")
    asyncio.create_task(run_update_and_notify_telegram(ADMIN_USER_ID))

@router.message(Command("reset"))
async def reset_conversation_command(message: aiogram_types.Message):
    user_id = message.from_user.id
    logger.info(f"Команда /reset от user_id={user_id} (TG).")
    
    async with user_processing_locks[user_id]:
        if user_id in pending_messages: del pending_messages[user_id]
        if user_id in user_message_timers:
            timer = user_message_timers.pop(user_id)
            if not timer.done(): timer.cancel()
        thread_id = user_threads.pop(user_id, None)
        if thread_id: logger.info(f"Тред {thread_id} для user_id={user_id} удален из памяти (TG).")
        if user_id in user_messages: del user_messages[user_id]
    # --- Удаляем файл истории пользователя ---
    history_file = os.path.join(HISTORY_DIR, f"history_{user_id}.jsonl")
    if os.path.exists(history_file):
        try:
            os.remove(history_file)
            logger.info(f"Файл истории {history_file} удалён по /reset.")
        except Exception as e:
            logger.error(f"Ошибка удаления файла истории {history_file}: {e}")
    # --- Сохраняем user_threads после удаления ---
    save_user_threads_to_file()
    await message.answer("🔄 Диалог сброшен!")

@router.message(Command("reset_all"))
async def reset_all_command(message: aiogram_types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ Нет прав!")
        return
    logger.warning(f"Админ {ADMIN_USER_ID} инициировал ПОЛНЫЙ СБРОС (TG)!")
    timers_cancelled = 0
    for timer_task in list(user_message_timers.values()):
        if not timer_task.done():
            timer_task.cancel()
            timers_cancelled +=1
    user_message_timers.clear()
    pending_messages_cleared = len(pending_messages)
    pending_messages.clear()
    threads_cleared = len(user_threads)
    user_threads.clear()
    user_messages_cleared = len(user_messages)
    user_messages.clear()
    # --- Удаляем все файлы истории ---
    for fname in glob.glob(os.path.join(HISTORY_DIR, "history_*.jsonl")):
        try:
            os.remove(fname)
            logger.info(f"Файл истории {fname} удалён по /reset_all.")
        except Exception as e:
            logger.error(f"Ошибка удаления файла истории {fname}: {e}")
    # --- Сохраняем user_threads после очистки ---
    save_user_threads_to_file()
    # --- Удаляем файл user_threads.json ---
    if os.path.exists(USER_THREADS_FILE):
        try:
            os.remove(USER_THREADS_FILE)
            logger.info(f"Файл {USER_THREADS_FILE} удалён по /reset_all.")
        except Exception as e:
            logger.error(f"Ошибка удаления {USER_THREADS_FILE}: {e}")
    await message.answer(f"🔄 ВСЕ ДИАЛОГИ СБРОШЕНЫ (TG).\n"
                         f"- Таймеров отменено: {timers_cancelled}\n"
                         f"- Буферов очищено: {pending_messages_cleared}\n"
                         f"- Тредов (память): {threads_cleared}\n"
                         f"- Историй (память): {user_messages_cleared}\n"
                         f"- Файлы истории удалены: да\n"
                         f"- user_threads.json удалён: да")

@router.message(Command("speak"))
async def speak_command(message: aiogram_types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    is_manager_or_admin = user_id == ADMIN_USER_ID or user_id in MANAGER_USER_IDS

    if not is_manager_or_admin:
        logger.debug(f"User {user_id} (не менеджер) попытался /speak в чате {chat_id}.")
        return

    if await is_chat_silent(chat_id):
        await set_chat_silence_permanently(chat_id, False)
        # --- Подгружаем историю при снятии молчания ---
        load_user_history_from_file(user_id)
        await message.answer("🤖 Режим молчания снят. Бот снова активен.")
        logger.info(f"Менеджер/админ {user_id} снял молчание для чата {chat_id} (TG).")
    else:
        await message.answer("ℹ️ Бот уже был активен.")

@router.message(Command("check_db"))
async def check_database_command(message: aiogram_types.Message):
    await message.answer("🔍 Проверяю активную базу векторов (TG)...")
    active_db_full_path = _get_active_db_full_path_telegram()

    if not active_db_full_path:
        await message.answer("❌ Активная база знаний (TG) не определена.")
        return

    report = [f"✅ Активный путь БД (TG): {active_db_full_path}"]
    try:
        files = await asyncio.to_thread(os.listdir, active_db_full_path)
        report.append(f"📄 Файлы в директории: {', '.join(files) if files else 'Пусто'}")
    except Exception as e: report.append(f"❌ Ошибка чтения файлов: {e}")

    if vector_collection:
        try:
            count = await asyncio.to_thread(vector_collection.count)
            report.append(f"📊 Кол-во записей (глоб.): {count}")
        except Exception as e: report.append(f"⚠️ Ошибка доступа к глоб. коллекции: {e}")
    else:
        report.append("ℹ️ Глобальная vector_collection не инициализирована. Попытка прямого подключения...")
        try:
            def _direct_count():
                client = chromadb.PersistentClient(path=active_db_full_path)
                return client.get_collection(CHROMA_COLLECTION_NAME).count()
            count_direct = await asyncio.to_thread(_direct_count)
            report.append(f"📊 Кол-во записей (прямое): {count_direct}")
        except Exception as e: report.append(f"❌ Ошибка прямого доступа: {e}")
    
    await message.answer("\n".join(report))

# --- Message Handlers ---
# Важно: хендлеры команд должны быть зарегистрированы в router ДО общих хендлеров сообщений,
# чтобы они имели приоритет. Aiogram обычно это делает автоматически, если Command фильтры используются.

@dp.business_message() 
async def handle_business_message(message: aiogram_types.Message):
    user_id = message.from_user.id 
    chat_id = message.chat.id 
    message_text = message.text or ""
    business_connection_id = message.business_connection_id
    log_prefix = f"handle_business_message(user:{user_id}, chat:{chat_id}, biz_conn:{business_connection_id}):"

    # --- Подгружаем историю, если её нет в памяти ---
    if user_id not in user_messages:
        load_user_history_from_file(user_id)

    # --- НОВАЯ ЛОГИКА: Автоматическое молчание для менеджеров ---
    # Эта проверка должна быть до общей проверки is_chat_silent,
    # чтобы менеджер мог активировать молчание, даже если оно еще не было включено.
    is_sender_admin = user_id == ADMIN_USER_ID
    is_sender_manager = user_id in MANAGER_USER_IDS
    
    # Если менеджер (не админ) пишет боту через бизнес-соединение
    if is_sender_manager and not is_sender_admin:
        if not await is_chat_silent(chat_id):
            logger.info(f"{log_prefix} Бизнес-сообщение от менеджера {user_id}. Включаем пост. молчание для chat_id={chat_id}.")
            await set_chat_silence_permanently(chat_id, True) # Включает молчание и сохраняет состояние
        else:
            logger.info(f"{log_prefix} Бизнес-сообщение от менеджера {user_id}, но бот уже молчит для chat_id={chat_id}.")
        return # Прекращаем обработку, если это менеджер (активировал молчание или оно уже было)
    # --- КОНЕЦ НОВОЙ ЛОГИКИ ---

    # Общая проверка: если чат УЖЕ в режиме молчания (например, включен командой /silence,
    # или это сообщение от обычного пользователя, а чат замолчал из-за предыдущего сообщения менеджера)
    if await is_chat_silent(chat_id):
        logger.info(f"{log_prefix} Бот в режиме молчания (общая проверка). Сообщение игнорируется.")
        return
    
    if not message_text.strip(): # Проверка на пустое сообщение
        logger.info(f"{log_prefix} Пустое бизнес-сообщение. Игнорируем.")
        return

    pending_messages.setdefault(user_id, []).append(message_text)
    logger.debug(f"{log_prefix} Бизнес-сообщение от обычного пользователя или админа добавлено в буфер.")
    
    if user_id in user_message_timers: # Отменяем предыдущий таймер, если есть
        timer = user_message_timers.pop(user_id)
        if not timer.done(): timer.cancel()
    
    new_timer = asyncio.create_task(schedule_buffered_processing(user_id, chat_id, business_connection_id))
    user_message_timers[user_id] = new_timer

@router.message(F.business_connection_id.is_(None)) 
async def handle_regular_message(message: aiogram_types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    message_text = message.text or ""
    log_prefix = f"handle_regular_message(user:{user_id}, chat:{chat_id}):"

    # --- Подгружаем историю, если её нет в памяти ---
    if user_id not in user_messages:
        load_user_history_from_file(user_id)

    is_sender_admin = user_id == ADMIN_USER_ID
    is_sender_manager = user_id in MANAGER_USER_IDS
    
    # Если менеджер (не админ) пишет боту напрямую (не команда)
    if is_sender_manager and not is_sender_admin and not message_text.startswith('/'):
        if not await is_chat_silent(chat_id):
            logger.info(f"{log_prefix} Сообщение от менеджера {user_id}. Включаем пост. молчание для chat_id={chat_id}.")
            await set_chat_silence_permanently(chat_id, True)
        else:
            logger.info(f"{log_prefix} Сообщение от менеджера {user_id}, но бот уже молчит для chat_id={chat_id}.")
        return 

    if await is_chat_silent(chat_id):
        logger.info(f"{log_prefix} Бот в режиме молчания. Сообщение игнорируется.")
        return
    if not message_text.strip():
        logger.info(f"{log_prefix} Пустое обычное сообщение. Игнорируем.")
        return

    pending_messages.setdefault(user_id, []).append(message_text)
    logger.debug(f"{log_prefix} Обычное сообщение добавлено в буфер.")
    if user_id in user_message_timers:
        timer = user_message_timers.pop(user_id)
        if not timer.done(): timer.cancel()
    
    new_timer = asyncio.create_task(schedule_buffered_processing(user_id, chat_id, None))
    user_message_timers[user_id] = new_timer

# --- Background Tasks & Utility ---
async def log_context_telegram(user_id: int, query: str, context: str, response_text: Optional[str] = None):
    try:
        ts = datetime.datetime.now()
        log_filename = os.path.join(LOGS_DIR, f"context_tg_{user_id}_{ts.strftime('%Y%m%d_%H%M%S_%f')}.log")
        async def _write():
            with open(log_filename, "w", encoding="utf-8") as f:
                f.write(f"Timestamp: {ts.isoformat()}\nUser ID: {user_id}\n"
                        f"--- User Query ---\n{query}\n"
                        f"--- Retrieved Context ---\n{context or 'Контекст не найден.'}\n")
                if response_text: f.write(f"--- Assistant Response ---\n{response_text}\n")
        await asyncio.to_thread(_write)
        logger.debug(f"Контекст (TG) для user_id {user_id} сохранен в {log_filename}")
    except Exception as e: logger.error(f"Ошибка логирования контекста (TG) для user_id={user_id}: {e}", exc_info=True)

async def daily_database_update_telegram():
    logger.info("Задача ежедневного обновления БД (TG) запущена.")
    while True:
        try:
            now = datetime.datetime.now()
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if now >= target: target += datetime.timedelta(days=1)
            sleep_duration = (target - now).total_seconds()
            logger.info(f"Ежедневное обновление БД (TG) в {target:%Y-%m-%d %H:%M:%S}. Ожидание {sleep_duration:.0f}с...")
            await asyncio.sleep(sleep_duration)
            
            logger.info("Ежедневное обновление БД (TG): Запуск...")
            update_result = await update_vector_store_telegram()
            logger.info("Ежедневное обновление БД (TG): Завершено.")
            
            if ADMIN_USER_ID:
                msg = f"🔔 Ежедневное авто-обновление БЗ (TG):\n"
                if update_result.get("success"):
                    msg += (f"✅ Успешно!\n➕ Добавлено: {update_result.get('added_chunks', 'N/A')}\n"
                            f"📊 Всего: {update_result.get('total_chunks', 'N/A')}\n")
                    if update_result.get("new_active_path"): msg += f"📁 Путь: {os.path.basename(update_result['new_active_path'])}"
                else: msg += f"❌ Ошибка: {update_result.get('error', 'N/A')}"
                try: await bot.send_message(ADMIN_USER_ID, msg)
                except Exception as e: logger.error(f"Ошибка отправки отчета админу (TG): {e}")
            await asyncio.sleep(60)
        except asyncio.CancelledError:
             logger.info("Задача ежедневного обновления БД (TG) отменена.")
             break
        except Exception as e:
            logger.error(f"Ошибка в цикле ежедневного обновления БД (TG): {e}", exc_info=True)
            await asyncio.sleep(3600)

async def periodic_cleanup_telegram():
    logger.info("Задача периодической очистки (TG) запущена.")
    while True:
        try:
            await cleanup_old_messages_in_memory()
            logger.info("Периодическая очистка (TG) выполнена.")
            await asyncio.sleep(3600) 
        except asyncio.CancelledError:
             logger.info("Задача периодической очистки (TG) отменена.")
             break
        except Exception as e:
            logger.error(f"Ошибка периодической очистки (TG): {e}", exc_info=True)
            await asyncio.sleep(300)

# --- PID File Management and Signal Handling ---
PID_FILE_BASENAME = "telegram_bot"
def create_pid_file():
    pid = os.getpid()
    pid_file = f'{PID_FILE_BASENAME}.pid'; i = 1
    while os.path.exists(pid_file): i += 1; pid_file = f'{PID_FILE_BASENAME}_{i}.pid'
    try:
        with open(pid_file, 'w') as f: f.write(str(pid))
        logger.info(f"Создан PID файл: {pid_file} (PID: {pid})")
    except OSError as e: logger.error(f"Не удалось создать PID файл {pid_file}: {e}")

def remove_pid_files():
    pid_files = glob.glob(f'{PID_FILE_BASENAME}*.pid')
    if not pid_files: return
    logger.info(f"Удаление PID файлов (TG): {pid_files}...")
    for pf in pid_files:
        try: os.remove(pf); logger.info(f"Удален {pf} (TG)")
        except OSError as e: logger.error(f"Ошибка удаления {pf} (TG): {e}")

async def shutdown(signal_obj, loop):
    logger.warning(f"Получен сигнал {signal_obj.name}, начинаю остановку...")
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"Отменяю {len(tasks)} активных задач...")
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Все активные задачи отменены.")
    
    # Закрытие сессии бота перед остановкой цикла
    if bot and bot.session and not bot.session.closed:
        logger.info("Закрытие сессии бота...")
        await bot.session.close()
        logger.info("Сессия бота закрыта.")

    if loop.is_running(): # Проверяем, что цикл все еще запущен
        logger.info("Остановка event loop...")
        loop.stop()

# --- История сообщений ---
HISTORY_DIR = "history"
os.makedirs(HISTORY_DIR, exist_ok=True)

USER_THREADS_FILE = "user_threads.json"

# Сохраняет сообщение в историю пользователя
def add_message_to_file_history(user_id: int, role: str, content: str):
    filename = os.path.join(HISTORY_DIR, f"history_{user_id}.jsonl")
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "role": role,
        "content": content
    }
    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# Очищает историю старше N дней (по умолчанию 100)
def cleanup_old_history(days: int = 100):
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    for fname in os.listdir(HISTORY_DIR):
        if not fname.startswith("history_") or not fname.endswith(".jsonl"):
            continue
        full_path = os.path.join(HISTORY_DIR, fname)
        new_lines = []
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["timestamp"])
                        if ts >= cutoff:
                            new_lines.append(line)
                    except Exception:
                        continue  # пропускаем битые строки
            # Перезаписываем файл только если были удалены старые записи
            if len(new_lines) < sum(1 for _ in open(full_path, "r", encoding="utf-8")):
                with open(full_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
        except Exception:
            continue

# Периодическая асинхронная задача для автоочистки истории
def start_periodic_history_cleanup():
    async def periodic_history_cleanup():
        while True:
            cleanup_old_history(100)  # 100 дней
            await asyncio.sleep(24 * 60 * 60)  # сутки
    return asyncio.create_task(periodic_history_cleanup())

# Встраиваем вызовы сохранения истории в нужные места:
# 1. В add_message_to_history (чтобы всегда писать и в память, и в файл)
_old_add_message_to_history = add_message_to_history
async def add_message_to_history(user_id: int, role: str, content: str):
    add_message_to_file_history(user_id, role, content)
    await _old_add_message_to_history(user_id, role, content)

# --- Функция загрузки истории пользователя из файла ---
def load_user_history_from_file(user_id: int, days: int = 100):
    filename = os.path.join(HISTORY_DIR, f"history_{user_id}.jsonl")
    if not os.path.exists(filename):
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    history = []
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts >= cutoff:
                    history.append({
                        'role': entry['role'],
                        'content': entry['content'],
                        'timestamp': ts
                    })
            except Exception:
                continue
    if history:
        user_messages[user_id] = history

# --- Загрузка соответствия user_id ↔ thread_id из файла ---
def load_user_threads_from_file():
    global user_threads
    if os.path.exists(USER_THREADS_FILE):
        try:
            with open(USER_THREADS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                user_threads.clear()
                for k, v in data.items():
                    try:
                        user_threads[int(k)] = v
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"Ошибка загрузки user_threads из файла: {e}")

# --- Сохранение соответствия user_id ↔ thread_id в файл ---
def save_user_threads_to_file():
    try:
        with open(USER_THREADS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in user_threads.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения user_threads в файл: {e}")

# --- Досылка истории в новый тред OpenAI ---
async def replay_history_to_thread(user_id: int, thread_id: str, max_messages: int = 20):
    filename = os.path.join(HISTORY_DIR, f"history_{user_id}.jsonl")
    if not os.path.exists(filename):
        return
    history = []
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                history.append(entry)
            except Exception:
                continue
    # Берём только последние max_messages
    history = history[-max_messages:]
    for msg in history:
        try:
            await openai_client.beta.threads.messages.create(
                thread_id=thread_id,
                role=msg['role'],
                content=msg['content']
            )
        except Exception as e:
            logger.error(f"Ошибка досылки истории в тред {thread_id}: {e}")

async def main():
    logger.info("--- 🚀 Запуск Telegram бота ---")
    # --- Загружаем user_threads из файла ---
    load_user_threads_from_file()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop)))

    get_drive_service_sync()
    if not drive_service_instance:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Google Drive не инициализирован. Остановка.")
        remove_pid_files(); return

    await load_silence_state_from_file()
    await _initialize_active_vector_collection_telegram()
    
    if ENABLE_STARTUP_KB_UPDATE and ADMIN_USER_ID: # Запускаем обновление только если флаг включен
        logger.info("Запуск первоначального обновления БЗ (TG) включен флагом окружения.")
        asyncio.create_task(run_update_and_notify_telegram(ADMIN_USER_ID))
    else:
        logger.info("Первоначальное обновление БЗ (TG) при старте отключено (ENABLE_STARTUP_KB_UPDATE_TELEGRAM=False).")

    dp.include_router(router) 
    cleanup_task = asyncio.create_task(periodic_cleanup_telegram())
    daily_update_db_task = None
    if ENABLE_DAILY_KB_UPDATE:
        logger.info("Ежедневное авто-обновление БД (TG) включено флагом окружения.")
        daily_update_db_task = asyncio.create_task(daily_database_update_telegram())
    else:
        logger.info("Ежедневное авто-обновление БД (TG) отключено (ENABLE_DAILY_KB_UPDATE_TELEGRAM=False).")
    # --- Запуск автоочистки истории ---
    start_periodic_history_cleanup()
    
    logger.info("🤖 Telegram бот готов к работе.")
    logger.info(f"🔇 Молчание для чатов: {list(chat_silence_state.keys())}")

    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError: logger.info("Основная задача dp.start_polling отменена.")
    except Exception as e: logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА start_polling: {e}", exc_info=True)
    finally:
        logger.info("--- 🛑 Завершение работы Telegram бота (из finally main) ---")
        # Отмена фоновых задач, если они еще не были отменены через shutdown
        if cleanup_task and not cleanup_task.done(): cleanup_task.cancel()
        if daily_update_db_task and not daily_update_db_task.done(): daily_update_db_task.cancel()

        # Дожидаемся завершения отмены (учитываем, что daily_update_db_task может быть None)
        tasks_to_wait = [cleanup_task]
        if daily_update_db_task:
            tasks_to_wait.append(daily_update_db_task)
        await asyncio.gather(*tasks_to_wait, return_exceptions=True)

        # Закрытие сессии (на случай если shutdown не был вызван или не успел)
        if bot and bot.session and not bot.session.closed:
            logger.info("Закрытие сессии бота (из finally main)...")
            await bot.session.close()
            logger.info("Сессия бота закрыта (из finally main).")
            
        # PID-файлы теперь управляются внешним супервизором (start_bot.sh)
        logger.info("--- Telegram бот остановлен ---")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logger.info("Процесс прерван (KeyboardInterrupt/SystemExit).")
    except Exception as e: logger.critical(f"КРИТИЧЕСКАЯ НЕПЕРЕХВАЧЕННАЯ ОШИБКА ЗАПУСКА: {e}", exc_info=True)
    finally: logger.info("Процесс завершен.")