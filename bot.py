import sys
import os
import time
import aiohttp
import re
import glob
import asyncio
from collections import deque
import datetime
import subprocess
import signal
import shutil
from asyncio import Lock

# Отладочная информация
print(f"Python: {sys.version}")
print(f"Python path: {sys.executable}")
print(f"Virtual env: {os.environ.get('VIRTUAL_ENV', 'Not in a virtual environment')}")
print(f"Working directory: {os.getcwd()}")

# Проверка наличия библиотеки
print("Используем OpenAI Embeddings вместо sentence-transformers")

import openai
import logging
from aiogram import Bot, Dispatcher, Router, types as aiogram_types, F
from aiogram.filters import Command, Filter
from dotenv import load_dotenv
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from io import BytesIO
import docx
import PyPDF2
import io
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import MarkdownHeaderTextSplitter

# Загружаем переменные из .env
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

# Добавляем константу для пути к ключу сервисного аккаунта
SERVICE_ACCOUNT_FILE = 'service-account-key.json'
FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")  # ID папки с документами

# Добавим константу с ID администратора бота
ADMIN_USER_ID = 164266775  # Замените на ваш ID пользователя
# Добавим список ID менеджеров
MANAGER_USER_IDS = [7924983011]

# Проверяем, загрузились ли переменные
if not all([TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, ASSISTANT_ID, FOLDER_ID]):
     # Добавляем FOLDER_ID в проверку
     logging.critical("КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют одна или несколько переменных окружения (TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, ASSISTANT_ID, GOOGLE_DRIVE_FOLDER_ID). Проверьте .env файл.")
     # Завершаем работу, если критические переменные отсутствуют
     sys.exit("Критические переменные окружения не установлены.")

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s'
)

# Создаем объекты бота, диспетчера и роутера
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Хранение `thread_id` и истории сообщений пользователей
user_threads = {}
user_messages = {}
MESSAGE_LIFETIME = timedelta(days=100)

# --- Убираем неиспользуемые кэши --- 
# response_cache = {}
# drive_cache = {}

# Включаем векторную базу
USE_VECTOR_STORE = True
# Создаем директорию для логов
LOGS_DIR = "./logs/context_logs"
os.makedirs(LOGS_DIR, exist_ok=True)

# --- ЛОГИКА БУФЕРИЗАЦИИ (Корректная версия) ---
MESSAGE_BUFFER_SECONDS = 4  # Время ожидания перед отправкой объединенного сообщения
pending_messages: dict[int, list[str]] = {}  # Хранилище буферизированных сообщений {user_id: [text1, text2]}
user_message_timers: dict[int, asyncio.Task] = {}  # Хранилище таймеров для каждого пользователя {user_id: task}
user_processing_locks: dict[int, asyncio.Lock] = {} # Блокировки для обработки сообщений одного пользователя {user_id: Lock}
# ------------------------------------

# --- РЕЖИМ МОЛЧАНИЯ ДЛЯ ЧАТОВ ---
chat_silence_state = {} # Ключ: chat_id, Значение: True (молчание), False (активен)
chat_silence_timers = {} # Ключ: chat_id, Значение: Task для отсчета времени деактивации молчания
MANAGER_ACTIVE_TIMEOUT = 86400  # 24 часа
# ------------------------------------

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (get_or_create_thread, cleanup_old_messages, add_message_to_history) ---

async def get_or_create_thread(user_id):
    """Получает или создает новый thread_id для пользователя."""
    if user_id in user_threads:
        thread_id = user_threads[user_id]
        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            client.beta.threads.messages.list(thread_id=thread_id)
            return thread_id
        except Exception as e:
            logging.error(f"Ошибка доступа к треду {thread_id}: {str(e)}. Создаем новый.")
            del user_threads[user_id]
            if user_id in user_messages:
                del user_messages[user_id]

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    thread = client.beta.threads.create()
    thread_id = thread.id
    user_threads[user_id] = thread_id
    user_messages[user_id] = []
    logging.info(f"Создан новый тред {thread_id} для пользователя {user_id}")
    return thread_id

async def cleanup_old_messages():
    """Очищает старые сообщения по времени"""
    current_time = datetime.now()
    for user_id in list(user_messages.keys()): # Итерируем по копии ключей
        user_messages[user_id] = [
            msg for msg in user_messages[user_id]
            if current_time - msg['timestamp'] < MESSAGE_LIFETIME
        ]

async def add_message_to_history(user_id, role, content):
    """Добавляет сообщение в историю"""
    if user_id not in user_messages:
        user_messages[user_id] = []
    user_messages[user_id].append({
        'role': role,
        'content': content,
        'timestamp': datetime.now()
    })

# --- GOOGLE DRIVE FUNCTIONS ---
# (get_drive_service, read_data_from_drive, download_google_doc, download_pdf, download_docx, download_text)
# ... (Код этих функций с улучшениями обработки ошибок и логов)

def get_drive_service():
    """Получение сервиса Google Drive через сервисный аккаунт"""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        logging.error(f"Ошибка при получении сервиса Google Drive: {e}", exc_info=True)
        raise

def read_data_from_drive():
    """Читает данные из Google Drive"""
    logging.info("Загружаем данные из Google Drive...")
    service = get_drive_service()
    result = []
    page_token = None
    try:
        while True:
            response = service.files().list(
                q=f"'{FOLDER_ID}' in parents and trashed=false",
                spaces='drive',
                fields='nextPageToken, files(id, name, mimeType)',
                pageToken=page_token
            ).execute()
            files = response.get('files', [])
            logging.info(f"Найдено {len(files)} файлов на этой странице.")

            for file in files:
                content = ""
                file_id = file['id']
                file_name = file['name']
                mime_type = file['mimeType']
                logging.debug(f"Обработка файла: {file_name} (ID: {file_id}, Type: {mime_type})")

                try:
                    if mime_type == 'application/vnd.google-apps.document':
                        content = download_google_doc(service, file_id)
                    elif mime_type == 'application/pdf':
                        content = download_pdf(service, file_id)
                    elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                        content = download_docx(service, file_id)
                    elif mime_type == 'text/plain':
                        content = download_text(service, file_id)
                    else:
                         logging.warning(f"Пропуск файла '{file_name}' с неподдерживаемым типом: {mime_type}")
                         continue

                    if content:
                        result.append({
                            'name': file_name,
                            'content': content
                        })
                        logging.debug(f"Успешно прочитан файл: {file_name}")
                    else:
                         logging.warning(f"Файл '{file_name}' прочитан, но не содержит текста.")

                except Exception as e:
                    logging.error(f"Ошибка при чтении файла {file_name} (ID: {file_id}): {str(e)}")
                    continue

            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break

    except Exception as e:
        logging.error(f"Критическая ошибка при чтении из Google Drive: {str(e)}")

    logging.info(f"Завершено чтение из Google Drive. Получено {len(result)} документов с текстом.")
    return result

def download_google_doc(service, file_id):
    """Скачивает и читает содержимое Google Doc."""
    try:
        content_bytes = service.files().export(
            fileId=file_id,
            mimeType='text/plain'
        ).execute()
        return content_bytes.decode('utf-8')
    except Exception as e:
        logging.error(f"Ошибка скачивания Google Doc (ID: {file_id}): {str(e)}")
        return ""

def download_pdf(service, file_id):
    """Скачивает и читает содержимое PDF файла."""
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            # logging.debug(f"Скачивание PDF (ID: {file_id}): {int(status.progress() * 100)}%") # Закомментировано

        fh.seek(0)
        pdf_reader = PyPDF2.PdfReader(fh)
        text = ""
        for page_num, page in enumerate(pdf_reader.pages):
             try:
                 page_text = page.extract_text()
                 if page_text:
                     text += page_text + "\n"
                 # else:
                 #     logging.warning(f"Не удалось извлечь текст со страницы {page_num+1} PDF (ID: {file_id})")
             except Exception as page_err:
                 logging.error(f"Ошибка извлечения текста со страницы {page_num+1} PDF (ID: {file_id}): {page_err}")
        return text
    except Exception as e:
        logging.error(f"Ошибка скачивания/чтения PDF (ID: {file_id}): {str(e)}")
        return ""

def download_docx(service, file_id):
    """Скачивает и читает содержимое DOCX файла."""
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            # logging.debug(f"Скачивание DOCX (ID: {file_id}): {int(status.progress() * 100)}%") # Закомментировано

        fh.seek(0)
        doc = docx.Document(fh)
        return "\n".join([paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()])
    except Exception as e:
        logging.error(f"Ошибка скачивания/чтения DOCX (ID: {file_id}): {str(e)}")
        return ""

def download_text(service, file_id):
    """Скачивает и читает содержимое текстового файла."""
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            # logging.debug(f"Скачивание TXT (ID: {file_id}): {int(status.progress() * 100)}%") # Закомментировано

        fh.seek(0)
        content_bytes = fh.getvalue()
        try:
            return content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            logging.warning(f"Ошибка декодирования TXT (ID: {file_id}) как UTF-8, пробуем cp1251")
            try:
                 return content_bytes.decode('cp1251')
            except Exception as decode_err:
                 logging.error(f"Не удалось декодировать TXT (ID: {file_id}): {decode_err}")
                 return ""
    except Exception as e:
        logging.error(f"Ошибка скачивания/чтения TXT (ID: {file_id}): {str(e)}")
        return ""

# --- VECTOR STORE FUNCTIONS ---

async def get_relevant_context(query: str, k: int = 3) -> str:
    """Получает релевантный контекст из векторного хранилища."""
    collection_name = "documents"
    empty_context = ""
    
    # Определяем базовый путь и файл для хранения пути активной БД
    base_persist_directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_vector_db")
    active_db_path_file = os.path.join(base_persist_directory, "active_db_path.txt")
    persist_directory = None # Инициализируем

    # --- Чтение пути к активной БД --- 
    try:
        if os.path.exists(active_db_path_file):
            with open(active_db_path_file, "r") as f:
                active_path = f.read().strip()
            if active_path and os.path.isdir(active_path): # Проверяем, что путь валидный и директория существует
                persist_directory = active_path
                logging.info(f"GET_CONTEXT: Используется активная директория из файла: {persist_directory}")
            else:
                logging.warning(f"GET_CONTEXT: Путь в файле {active_db_path_file} невалидный ('{active_path}') или директория не существует.")
        else:
            logging.warning(f"GET_CONTEXT: Файл {active_db_path_file} не найден. Невозможно определить активную базу.")
    except Exception as e_read_path:
        logging.error(f"GET_CONTEXT: Ошибка чтения файла {active_db_path_file}: {e_read_path}")

    # Если не удалось определить активную директорию, выходим
    if persist_directory is None:
        logging.error("GET_CONTEXT: Не удалось определить путь к активной базе данных. Контекст не используется.")
        return empty_context
    # --- Конец чтения пути --- 

    try:
        # Убрана проверка на существование persist_directory, т.к. она уже сделана выше при чтении пути
        # if not os.path.exists(persist_directory) or not os.path.isdir(persist_directory):
        #     logging.error(f"Директория базы данных не найдена '{persist_directory}'. Контекст не используется.")
        #     return empty_context
        try:
            import chromadb
            from openai import OpenAI
        except ImportError as ie:
            logging.error(f"Не установлена библиотека (chromadb или openai): {str(ie)}. Контекст не используется.")
            return empty_context
        try:
            logging.debug(f"Подключение к ChromaDB: '{persist_directory}'")
            chroma_client = chromadb.PersistentClient(path=persist_directory)
        except Exception as client_err:
            logging.error(f"Ошибка подключения к ChromaDB: {client_err}. Контекст не используется.")
            return empty_context
        try:
            collection = chroma_client.get_collection(name=collection_name)
            count = collection.count()
            if count == 0:
                logging.warning("База векторов пуста. Контекст не используется.")
                return empty_context
            logging.info(f"В базе найдено {count} записей")
        except Exception as coll_err:
            # Проверяем специфичную ошибку "does not exist"
            if "does not exist" in str(coll_err).lower():
                 logging.error(f"Коллекция '{collection_name}' не найдена! Запустите /update. Контекст не используется.")
            else:
                 logging.error(f"Ошибка при доступе к коллекции '{collection_name}': {coll_err}. Контекст не используется.")
            return empty_context
        try:
            client = OpenAI()
            model_name = "text-embedding-3-large"
            embed_dim = 1536
            logging.debug(f"Получение вектора для запроса: '{query}' (модель: {model_name}, dim: {embed_dim})")
            query_embedding_response = client.embeddings.create(
                input=[query],
                model=model_name,
                dimensions=embed_dim
            )
            query_embedding = query_embedding_response.data[0].embedding
        except Exception as embed_error:
            logging.error(f"Ошибка создания embedding для запроса '{query}': {str(embed_error)}. Контекст не используется.")
            return empty_context
        try:
            logging.debug(f"Выполнение поиска по запросу: '{query}' (k={k})")
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=max(k, 5),
                include=["documents", "metadatas", "distances"]
            )
        except Exception as query_err:
            logging.error(f"Ошибка при поиске в ChromaDB: {query_err}. Контекст не используется.")
            return empty_context
        if not results or not results.get("ids") or not results["ids"][0]:
            logging.warning(f"Не найдено релевантных документов для запроса: '{query}'. Контекст не используется.")
            return empty_context

        doc_tuples = list(zip(results["documents"][0], results["metadatas"][0], results["distances"][0]))
        logging.info(f"Найдено {len(doc_tuples)} документов для запроса '{query}'")
        # Логируем только первые несколько для краткости
        for i, (doc_text, metadata, distance) in enumerate(doc_tuples[:5]):
            logging.debug(f"Док #{i+1}: Src: {metadata.get('source', 'N/A')}, Dist: {distance:.4f}, Text: {doc_text[:100]}...")

        top_docs = doc_tuples[:k]
        context_pieces = []
        for doc_text, metadata, distance in top_docs:
            source = metadata.get('source', 'неизвестный источник')
            context_pieces.append(f"Контекст из документа '{source}':\n{doc_text}")
        found_text = "\n\n".join(context_pieces)
        if not found_text:
            logging.warning(f"Не найдено релевантных документов (k={k}) для запроса: '{query}'. Контекст не используется.")
            return empty_context
        logging.debug(f"Итоговый контекст для '{query}':\n{found_text[:300]}...")
        return found_text
    except Exception as e:
        logging.error(f"Непредвиденная ошибка в get_relevant_context: {str(e)}", exc_info=True)
        return empty_context

async def update_vector_store(chat_id=None, chunks=None, force_reload=False):
    """Обновляет векторную базу данных на основе текстовых документов."""
    collection_name = "documents"
    
    # Определяем базовый путь и файл для хранения пути активной БД
    base_persist_directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_vector_db")
    active_db_path_file = os.path.join(base_persist_directory, "active_db_path.txt")
    os.makedirs(base_persist_directory, exist_ok=True) # Убедимся, что базовая директория существует

    # Генерируем уникальный путь для новой БД
    timestamp_dir_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    persist_directory = os.path.join(base_persist_directory, timestamp_dir_name) 
    logging.info(f"Новая директория для обновления БД: {persist_directory}")
    
    # Удаляем старую вспомогательную функцию и ее вызовы
    # def _get_current_chunk_count_or_na(): ... (определение функции удаляется)
    # Заменяем вызовы _get_current_chunk_count_or_na() на 'N/A' или 0 в блоках except

    try:
        # --- Создание новой директории ---
        # Нет необходимости удалять persist_directory, т.к. она каждый раз новая
        try:
            os.makedirs(persist_directory, mode=0o777, exist_ok=True) 
            logging.info(f"Целевая директория '{persist_directory}' создана/проверена с правами 0o777.")
        except Exception as e_mkdir:
            logging.error(f"НЕ УДАЛОСЬ создать/проверить целевую директорию '{persist_directory}': {str(e_mkdir)}. Обновление прервано.", exc_info=True)
            return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"Failed to create target dir: {str(e_mkdir)}"} # Используем 'N/A'

        logging.info("Начинаем обновление: получаем данные из Google Drive...")
        documents_data = read_data_from_drive()
        if not documents_data:
            logging.warning("Не получено данных из Google Drive. Обновление базы знаний прервано (нет новых данных).")
            # Если нет данных, нет смысла создавать пустую базу и чистить старые
            return {'success': True, 'added_chunks': 0, 'total_chunks': 0, 'error': "No data from Google Drive"}
        
        logging.info(f"Получено {len(documents_data)} документов из Google Drive.")
        docs = []
        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "h1"),("##", "h2"),("###", "h3")])
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
        for doc_data in documents_data:
            content_str = doc_data.get('content', '')
            doc_name = doc_data.get('name', 'N/A')
            if not isinstance(content_str, str) or not content_str.strip():
                logging.warning(f"Документ '{doc_name}' пуст, пропускаем.")
                continue
            enhanced_content = f"Документ: {doc_name}\\\\n\\\\n{content_str}"
            is_markdown = doc_name.endswith('.md')
            try:
                splits = markdown_splitter.split_text(enhanced_content) if is_markdown else text_splitter.split_text(enhanced_content)
                for split in splits:
                    if isinstance(split, Document):
                        page_content = split.page_content
                        metadata = split.metadata
                    else:
                        page_content = split
                        metadata = {}
                    metadata["source"] = doc_name
                    metadata["doc_type"] = "markdown" if is_markdown else "text"
                    if len(page_content) > text_splitter._chunk_size:
                         sub_splits = text_splitter.split_text(page_content)
                         for sub_split in sub_splits:
                              docs.append(Document(page_content=sub_split, metadata=metadata.copy()))
                    else:
                         docs.append(Document(page_content=page_content, metadata=metadata))
            except Exception as e_doc:
                 logging.error(f"Не удалось обработать '{doc_name}': {str(e_doc)}")
                 continue
        
        if not docs:
            logging.warning("После обработки документов не осталось чанков для добавления в базу.")
            # Если нет чанков, нет смысла создавать пустую базу и чистить старые
            return {'success': True, 'added_chunks': 0, 'total_chunks': 0, 'error': "No processable chunks from documents"}
        
        logging.info(f"Подготовлено {len(docs)} чанков для базы.")
        
        try:
            import chromadb 
            from openai import OpenAI 
        except ImportError as ie:
            logging.error(f"Не установлена необходимая библиотека (chromadb или openai): {str(ie)}")
            return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"ImportError: {str(ie)}"} # Используем 'N/A'
        
        try:
            client = OpenAI()
            model_name = "text-embedding-3-large"
            embed_dim = 1536
            
            # ---> НАЧАЛО: Проверка прав на запись <---\n            
            logging.info(f"Проверка прав на запись в директорию: {persist_directory}")
            try:
                test_file_path = os.path.join(persist_directory, "write_test.tmp")
                with open(test_file_path, "w") as f:
                    f.write("test")
                os.remove(test_file_path)
                logging.info(f"ПРОВЕРКА ПРАВ: Директория '{persist_directory}' доступна для записи.")
            except Exception as e_write_test:
                logging.error(f"ОШИБКА ПРАВ: Директория '{persist_directory}' НЕ доступна для записи: {e_write_test}", exc_info=True)
                # Удаляем неудачно созданную директорию перед выходом
                try: shutil.rmtree(persist_directory) 
                except: pass
                return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"Directory not writable: {persist_directory}. Error: {e_write_test}"} # Используем 'N/A'
            # ---> КОНЕЦ: Проверка прав на запись <---\n
            
            logging.info(f"Инициализация ChromaDB клиента в '{persist_directory}'...")
            chroma_client = chromadb.PersistentClient(path=persist_directory)
            logging.info(f"ChromaDB клиент инициализирован.")
            # Проверка создания файла БД
            sqlite_file_path = os.path.join(persist_directory, "chroma.sqlite3")
            if os.path.exists(sqlite_file_path):
                logging.info(f"ПРОВЕРКА: chroma.sqlite3 СУЩЕСТВУЕТ в {persist_directory} после PersistentClient. Права: {oct(os.stat(sqlite_file_path).st_mode)[-4:]}")
            else:
                # Это все еще может быть проблемой, но с уникальным путем менее вероятно
                logging.warning(f"ПРЕДУПРЕЖДЕНИЕ ПРОВЕРКИ: chroma.sqlite3 НЕ СУЩЕСТВУЕТ в {persist_directory} после PersistentClient!")

            time.sleep(1.0) # Оставим небольшую паузу на всякий случай
            
            collection = None # Инициализируем переменную
            try:
                # ---> НАЧАЛО: Упрощенное создание коллекции <---\n                
                logging.info(f"Попытка создать коллекцию '{collection_name}' (ожидается, что ее нет)...")
                collection = chroma_client.create_collection(name=collection_name)
                logging.info(f"Коллекция '{collection_name}' успешно создана.")
                # ---> КОНЕЦ: Упрощенное создание коллекции <---\n
                # ---> НАЧАЛО: Проверка начального количества чанков <---\n                
                try:
                    initial_count = collection.count()
                    logging.info(f"НАЧАЛЬНОЕ количество чанков в ЯВНО СОЗДАННОЙ коллекции '{collection_name}': {initial_count}")
                except Exception as e_initial_count:
                    logging.error(f"Ошибка при получении начального количества чанков: {e_initial_count}", exc_info=True)
                # ---> КОНЕЦ: Проверка начального количества чанков <---\n
            
            except chromadb.errors.InternalError as e_internal_chroma:
                # Эта ветка не должна срабатывать при уникальном пути, но оставим для надежности
                logging.warning(f"Перехвачено chromadb.errors.InternalError: {e_internal_chroma}")
                if "already exists" in str(e_internal_chroma).lower() or "already exist" in str(e_internal_chroma).lower():
                    logging.warning(f"КОНФЛИКТ (InternalError): Коллекция '{collection_name}' уже существует несмотря на уникальный путь! Попытка получить ее.")
                    try:
                        collection = chroma_client.get_collection(name=collection_name)
                        logging.info(f"КОНФЛИКТ (InternalError): Существующая коллекция '{collection_name}' получена.")
                        # Проверка чанков в полученной коллекции
                        try:
                            initial_count = collection.count()
                            logging.info(f"НАЧАЛЬНОЕ количество чанков в ПОЛУЧЕННОЙ коллекции '{collection_name}': {initial_count}")
                        except Exception as e_initial_count_get:
                            logging.error(f"Ошибка при получении начального количества чанков в ПОЛУЧЕННОЙ коллекции: {e_initial_count_get}", exc_info=True)
                    except Exception as e_get_coll_conflict:
                        logging.error(f"КОНФЛИКТ (InternalError): Не удалось получить существующую коллекцию '{collection_name}': {e_get_coll_conflict}", exc_info=True)
                        try: shutil.rmtree(persist_directory) 
                        except: pass
                        return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"Conflict (InternalError): Collection already exists and could not be retrieved: {str(e_get_coll_conflict)}"} # 'N/A'
                else:
                    logging.error(f"Критическая ошибка chromadb.errors.InternalError (не 'already exists'): {e_internal_chroma}", exc_info=True)
                    try: shutil.rmtree(persist_directory) 
                    except: pass
                    return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"ChromaDB InternalError (not 'already exists'): {str(e_internal_chroma)}"} # 'N/A'
            except Exception as e_coll_other:
                 logging.error(f"Неожиданная ошибка при создании/получении коллекции '{collection_name}': {e_coll_other}", exc_info=True)
                 try: shutil.rmtree(persist_directory) 
                 except: pass
                 return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"Unexpected collection creation/access error: {str(e_coll_other)}"} # 'N/A'

            if collection is None: # Если коллекция так и не была успешно создана или получена
                logging.error("Не удалось инициализировать объект коллекции.")
                try: shutil.rmtree(persist_directory) 
                except: pass
                return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': "Failed to initialize collection object"} # 'N/A'

            # ... (код подготовки ids_to_add, docs_to_add, metadatas_to_add остается прежним) ...
            batch_size = 100
            total_added = 0
            ids_to_add = []
            docs_to_add = []
            metadatas_to_add = []
            import hashlib
            existing_ids = set() # При уникальном пути всегда пусто
            for i, doc_item in enumerate(docs):
                hasher = hashlib.sha256()
                hasher.update(doc_item.page_content.encode('utf-8'))
                hasher.update(str(doc_item.metadata.get('source','N/A')).encode('utf-8'))
                doc_id = hasher.hexdigest()
                if doc_id not in existing_ids:
                    ids_to_add.append(doc_id)
                    docs_to_add.append(doc_item.page_content)
                    metadatas_to_add.append(doc_item.metadata)

            logging.info(f"Необходимо добавить {len(ids_to_add)} новых чанков.")
            if not ids_to_add:
                 logging.info("Нет новых чанков для добавления.")
                 # Нет смысла сохранять пустую базу и чистить старые
                 try: shutil.rmtree(persist_directory) 
                 except: pass
                 return {'success': True, 'added_chunks': 0, 'total_chunks': 0, 'error': "No chunks to add"}

            # --- Цикл добавления батчей ---
            batch_errors = False
            for i in range(0, len(ids_to_add), batch_size):
                # ... (код получения батчей и embeddings) ...
                batch_ids = ids_to_add[i:i+batch_size]
                batch_docs = docs_to_add[i:i+batch_size]
                batch_metadatas = metadatas_to_add[i:i+batch_size]
                current_batch_size = len(batch_ids)
                logging.info(f"Обработка партии {i//batch_size + 1}/{(len(ids_to_add) - 1)//batch_size + 1} ({current_batch_size} чанков)...")
                try:
                    # ... (код получения embeddings) ...
                    logging.debug(f"Получение {current_batch_size} embeddings...")
                    embeddings_response = client.embeddings.create(input=batch_docs, model=model_name, dimensions=embed_dim)
                    batch_embeddings = [e.embedding for e in embeddings_response.data]
                    logging.debug(f"Добавление {current_batch_size} чанков в ChromaDB...")
                    collection.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metadatas, embeddings=batch_embeddings)
                    total_added += current_batch_size
                    logging.info(f"Добавлено {total_added}/{len(ids_to_add)} новых чанков.")
                except Exception as e_batch:
                    logging.error(f"Ошибка при обработке партии {i//batch_size + 1}: {str(e_batch)}", exc_info=True)
                    logging.warning("Пропуск этой партии из-за ошибки.")
                    batch_errors = True # Помечаем, что была ошибка
                    continue 
            
            final_added_chunks = total_added
            final_total_chunks = 0
            try:
                final_total_chunks = collection.count()
                logging.info(f"Итоговое количество чанков в базе: {final_total_chunks}")
            except Exception as count_err:
                logging.warning(f"Не удалось получить итоговое количество чанков после добавления: {count_err}")
                final_total_chunks = 'N/A'

            if batch_errors or final_added_chunks < len(ids_to_add): 
                error_msg = "Errors during batch processing, not all chunks added."
                logging.warning(f"Не все чанки были добавлены. Планировалось: {len(ids_to_add)}, добавлено: {final_added_chunks}")
                # Не сохраняем путь к неполной базе и не чистим старые
                try: shutil.rmtree(persist_directory) # Удаляем неудачную попытку
                except Exception as e_rm_fail: logging.warning(f"Не удалось удалить директорию с неполной базой {persist_directory}: {e_rm_fail}")
                return {'success': False, 'added_chunks': final_added_chunks, 'total_chunks': final_total_chunks, 'error': error_msg}
            else:
                # --- УСПЕШНОЕ ЗАВЕРШЕНИЕ ---
                logging.info(f"Обновление векторного хранилища успешно завершено. Добавлено {final_added_chunks} новых чанков.")
                
                # --- Сохраняем путь к активной базе ---
                try:
                    with open(active_db_path_file, "w") as f:
                        f.write(persist_directory)
                    logging.info(f"Путь к активной базе '{persist_directory}' сохранен в: {active_db_path_file}")
                except Exception as e_save_path:
                    logging.error(f"НЕ УДАЛОСЬ сохранить путь к активной базе '{persist_directory}' в файл {active_db_path_file}: {e_save_path}")
                    # Обновление прошло, но путь не сохранен - это проблема для get_context
                    # Возвращаем успех, но с предупреждением
                    return {'success': True, 'added_chunks': final_added_chunks, 'total_chunks': final_total_chunks, 'warning': f"DB updated but failed to save active path: {e_save_path}"}
                
                # --- Очистка старых директорий ---
                logging.info(f"Очистка старых директорий баз данных в {base_persist_directory}...")
                cleaned_count = 0
                try:
                    for item in os.listdir(base_persist_directory):
                        item_path = os.path.join(base_persist_directory, item)
                        # Удаляем только директории, имя которых похоже на метку времени, и не текущую
                        if os.path.isdir(item_path) and item != timestamp_dir_name and re.match(r'^\\d{8}_\\d{6}_\\d{6}$', item):
                            try:
                                shutil.rmtree(item_path)
                                logging.info(f"Удалена старая директория базы данных: {item_path}")
                                cleaned_count += 1
                            except Exception as e_clean:
                                logging.warning(f"Не удалось удалить старую директорию {item_path}: {e_clean}")
                    logging.info(f"Очистка завершена. Удалено старых директорий: {cleaned_count}")
                except Exception as e_list_clean:
                    logging.warning(f"Ошибка при получении списка для очистки старых директорий: {e_list_clean}")

                save_vector_db_creation_time() # Сохраняем время в last_update.txt (для информации)
                return {'success': True, 'added_chunks': final_added_chunks, 'total_chunks': final_total_chunks}

        except Exception as e_chroma:
            logging.error(f"Критическая ошибка при работе с ChromaDB: {str(e_chroma)}", exc_info=True)
            try: shutil.rmtree(persist_directory) # Удаляем неудачную попытку
            except: pass
            return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"ChromaDB critical error: {str(e_chroma)}"} # 'N/A'
            
    except Exception as e_main:
        logging.error(f"Критическая ошибка при обновлении векторного хранилища: {str(e_main)}", exc_info=True)
        # Неясно, была ли создана директория, поэтому не пытаемся ее удалять здесь
        return {'success': False, 'added_chunks': 0, 'total_chunks': 'N/A', 'error': f"Main update vector store error: {str(e_main)}"} # 'N/A'

# --- Удаление старой функции ---
# Определение функции _get_current_chunk_count_or_na должно быть полностью удалено из файла.
# Я не могу явно удалить функцию, но убедитесь, что ее определения больше нет.

def _get_active_db_path():
    """Читает и возвращает путь к активной базе данных из файла."""
    base_persist_directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_vector_db")
    active_db_path_file = os.path.join(base_persist_directory, "active_db_path.txt")
    try:
        if os.path.exists(active_db_path_file):
            with open(active_db_path_file, "r") as f:
                active_path = f.read().strip()
            if active_path and os.path.isdir(active_path):
                logging.info(f"_get_active_db_path: Найден активный путь: {active_path}")
                return active_path
            else:
                logging.warning(f"_get_active_db_path: Путь в файле {active_db_path_file} невалидный ('{active_path}') или директория не существует.")
                return None
        else:
            logging.warning(f"_get_active_db_path: Файл {active_db_path_file} не найден.")
            return None
    except Exception as e:
        logging.error(f"_get_active_db_path: Ошибка чтения файла {active_db_path_file}: {e}")
        return None

# Код обработки документов и разбивки на чанки (placeholder)
# ...
        logging.error(f"Критическая ошибка в chat_with_assistant для user_id {user_id}: {str(e)}", exc_info=True)
        return f"Произошла внутренняя ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."


# --- ФУНКЦИИ БУФЕРИЗАЦИИ (Корректная версия) ---

async def process_buffered_messages(user_id: int, chat_id: int, business_connection_id: str | None):
    """
    Обрабатывает накопленные сообщения для пользователя после срабатывания таймера.
    Эта функция вызывается из schedule_buffered_processing.
    """
    log_prefix = f"process_buffered_messages(user:{user_id}, chat:{chat_id}):"
    logging.debug(f"{log_prefix} Начало")
    lock = user_processing_locks.setdefault(user_id, asyncio.Lock())

    if lock.locked():
        logging.warning(f"{log_prefix} Блокировка уже занята. Пропускаем этот вызов.")
        # Не удаляем таймер здесь, так как он уже должен быть удален в schedule_buffered_processing
        return

    async with lock:
        logging.debug(f"{log_prefix} Блокировка получена")
        # Забираем сообщения из буфера ТОЛЬКО ПОСЛЕ получения блокировки
        messages_to_process = pending_messages.pop(user_id, [])
        # Таймер должен быть уже удален в schedule_buffered_processing к моменту входа сюда
        if user_id in user_message_timers:
             logging.warning(f"{log_prefix} Таймер все еще существует внутри блокировки! Удаляем.")
             # Отменяем на всякий случай, вдруг это другая задача
             try: 
                user_message_timers[user_id].cancel()
             except Exception as e:
                logging.debug(f"{log_prefix} Ошибка при отмене таймера: {e}")
             del user_message_timers[user_id]

        if not messages_to_process:
            logging.info(f"{log_prefix} Нет сообщений в буфере для обработки.")
            # Блокировка будет освобождена
            return

        combined_input = "\n".join(messages_to_process)
        num_messages = len(messages_to_process)
        logging.info(f"{log_prefix} Объединенный запрос ({num_messages} сообщ.): {combined_input[:200]}...")

        try:
            logging.debug(f"{log_prefix} Вызов chat_with_assistant")
            response = await chat_with_assistant(user_id, combined_input)
            logging.info(f"{log_prefix} Получен ответ (начало): {response[:200]}...")
            try:
                logging.debug(f"{log_prefix} Отправка ответа (business_id: {business_connection_id})")
                await bot.send_message(
                    chat_id=chat_id,
                    text=response,
                    business_connection_id=business_connection_id
                )
                logging.info(f"{log_prefix} Успешно отправлен ответ.")
            except Exception as send_error:
                logging.error(f"{log_prefix} Ошибка отправки ответа: {str(send_error)}")
        except Exception as processing_error:
            logging.error(f"{log_prefix} Ошибка вызова chat_with_assistant: {str(processing_error)}", exc_info=True)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Извините, произошла внутренняя ошибка при обработке вашего запроса.",
                    business_connection_id=business_connection_id
                )
            except Exception as error_msg_error:
                logging.error(f"{log_prefix} Не удалось отправить сообщение об ошибке: {str(error_msg_error)}")
        # Блокировка освобождается
        logging.debug(f"{log_prefix} Блокировка освобождена")

async def schedule_buffered_processing(user_id: int, chat_id: int, business_connection_id: str | None):
    """
    Задача, которая ждет MESSAGE_BUFFER_SECONDS и затем вызывает process_buffered_messages.
    """
    log_prefix = f"schedule_buffered_processing(user:{user_id}, chat:{chat_id}):"
    current_task = asyncio.current_task()
    try:
        logging.debug(f"{log_prefix} Ожидание {MESSAGE_BUFFER_SECONDS} секунд...")
        await asyncio.sleep(MESSAGE_BUFFER_SECONDS)

        # --- Добавленное логирование для отладки ---
        task_in_dict = user_message_timers.get(user_id)
        comparison_result = task_in_dict is not current_task
        logging.debug(f"{log_prefix} Таймер сработал.")
        logging.debug(f"{log_prefix}   - Текущая задача (current_task): {current_task}")
        logging.debug(f"{log_prefix}   - Задача в словаре (task_in_dict): {task_in_dict}")
        logging.debug(f"{log_prefix}   - Сравнение (task_in_dict is not current_task): {comparison_result}")
        # --- Конец добавленного логирования ---

        # Таймер сработал. Проверяем, актуальна ли эта задача таймера
        if task_in_dict is not current_task:
            # Если задачи не совпадают, значит, был создан НОВЫЙ таймер.
            # Эта задача устарела, ничего не делаем. Новый таймер сработает позже.
            logging.info(f"{log_prefix} Таймер сработал, но он устарел (был заменен новым). Обработка отменена.")
            return

        # Если это все еще актуальный таймер, удаляем его и запускаем обработку
        del user_message_timers[user_id]
        logging.debug(f"{log_prefix} Таймер сработал и удален. Вызов process_buffered_messages.")
        asyncio.create_task(process_buffered_messages(user_id, chat_id, business_connection_id))

    except asyncio.CancelledError:
        logging.info(f"{log_prefix} Таймер отменен (вероятно, пришло новое сообщение).")
        # Если таймер был отменен, он уже должен быть удален из словаря при создании нового
    except Exception as e:
        logging.error(f"{log_prefix} Ошибка в задаче таймера: {str(e)}", exc_info=True)
        # Удаляем таймер в случае непредвиденной ошибки, если он все еще там
        if user_id in user_message_timers and user_message_timers[user_id] is current_task:
            del user_message_timers[user_id]

# --- РЕЖИМ МОЛЧАНИЯ --- 
# (is_chat_silent, set_chat_silence, deactivate_silence_after_timeout)
# ... (Код этих функций с улучшенными логами и проверками)
async def is_chat_silent(chat_id):
    """Проверяет, должен ли бот молчать в данном чате."""
    return chat_silence_state.get(chat_id, False)

async def set_chat_silence(chat_id, silent: bool):
    """Устанавливает статус молчания для чата и управляет таймером."""
    log_prefix = f"set_chat_silence(chat:{chat_id}):"
    current_state = chat_silence_state.get(chat_id, False)
    if current_state == silent:
         # Если состояние не меняется, но silent=True, продлеваем таймер
         if silent and chat_id in chat_silence_timers:
              logging.debug(f"{log_prefix} Продление режима молчания.")
              # Отменяем старый и создаем новый - самый простой способ продлить
              if not chat_silence_timers[chat_id].done():
                  chat_silence_timers[chat_id].cancel()
              silence_task = asyncio.create_task(deactivate_silence_after_timeout(chat_id))
              chat_silence_timers[chat_id] = silence_task
         else:
              logging.debug(f"{log_prefix} Состояние молчания не изменилось ({silent}).")
         return

    chat_silence_state[chat_id] = silent
    if silent:
        logging.info(f"{log_prefix} Включение режима молчания на {MANAGER_ACTIVE_TIMEOUT} сек.")
        if chat_id in chat_silence_timers and not chat_silence_timers[chat_id].done():
            chat_silence_timers[chat_id].cancel()
        silence_task = asyncio.create_task(deactivate_silence_after_timeout(chat_id))
        chat_silence_timers[chat_id] = silence_task
    else:
        logging.info(f"{log_prefix} Выключение режима молчания.")
        if chat_id in chat_silence_timers and not chat_silence_timers[chat_id].done():
            chat_silence_timers[chat_id].cancel()
            # Удаляем сразу после отмены
            del chat_silence_timers[chat_id]

async def deactivate_silence_after_timeout(chat_id, timeout=MANAGER_ACTIVE_TIMEOUT):
    """Автоматически деактивирует режим молчания после таймаута."""
    log_prefix = f"deactivate_silence_after_timeout(chat:{chat_id}):"
    current_task = asyncio.current_task()
    try:
        await asyncio.sleep(timeout)
        # Проверяем перед деактивацией
        if await is_chat_silent(chat_id):
            logging.info(f"{log_prefix} Таймер истек. Деактивация режима молчания.")
            await set_chat_silence(chat_id, False)
        else:
            logging.info(f"{log_prefix} Таймер истек, но режим молчания уже был деактивирован.")
    except asyncio.CancelledError:
        logging.info(f"{log_prefix} Таймер деактивации отменен.")
    except Exception as e:
        logging.error(f"{log_prefix} Ошибка: {str(e)}")
    finally:
        # Удаляем задачу из словаря только если это была именно она
        if chat_id in chat_silence_timers and chat_silence_timers[chat_id] is current_task:
            del chat_silence_timers[chat_id]

# --- ОБРАБОТЧИКИ КОМАНД TELEGRAM ---
# (Команды /start, /update, /check_db, /debug_db, /db_time, /full_debug, /debug_context обновлены)
# (Команды /clear, /reset обновлены для работы с буфером)

@router.message(Command("start"))
async def start_command(message: aiogram_types.Message):
    """Приветственное сообщение при старте и запуск обновления базы."""
    await message.answer("👋 Здравствуйте! Я готов к работе. Обновляю базу знаний, это может занять некоторое время...")
    asyncio.create_task(run_update_and_notify(message.chat.id))

async def run_update_and_notify(chat_id: int):
    """Выполняет обновление базы и уведомляет пользователя."""
    logging.info(f"Запущено обновление базы знаний по команде из чата {chat_id}...")
    update_result = await update_vector_store(chat_id)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if chat_id is None:
            logging.info("Не отправляем уведомление, т.к. chat_id=None")
            return
            
        if update_result['success']:
            message_text = (
                f"✅ База знаний успешно обновлена!\n"
                f"🕒 Время: {current_time}\n"
                f"➕ Добавлено новых чанков: {update_result.get('added_chunks', 'N/A')}\n"
                f"📊 Всего чанков в базе: {update_result.get('total_chunks', 'N/A')}"
            )
            await bot.send_message(chat_id, message_text)
            logging.info(f"Обновление базы (чат {chat_id}) завершено успешно.")
        else:
            error_details = update_result.get('error', 'Подробности в основных логах.')
            message_text = (
                 f"⚠️ Произошла ошибка во время обновления базы знаний.\n"
                 f"🕒 Время: {current_time}\n"
                 f"Бот будет использовать старые данные (если они есть).\n"
                 f"Детали ошибки: {error_details}"
            )
            await bot.send_message(chat_id, message_text)
            logging.error(f"Обновление базы (чат {chat_id}) завершено с ошибкой: {error_details}")
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления об обновлении базы в чат {chat_id}: {e}")

@router.message(Command("clear"))
async def clear_history(message: aiogram_types.Message):
    """Очищает историю сообщений пользователя и сбрасывает буфер."""
    user_id = message.from_user.id
    log_prefix = f"clear_history(user:{user_id}):"
    logging.info(f"{log_prefix} Команда получена.")
    if user_id in user_messages:
        user_messages[user_id] = []
        logging.debug(f"{log_prefix} История сообщений очищена.")
    if user_id in pending_messages:
        del pending_messages[user_id]
        logging.debug(f"{log_prefix} Буфер сообщений очищен.")
    if user_id in user_message_timers:
        old_timer = user_message_timers.pop(user_id)
        if not old_timer.done():
            try:
                old_timer.cancel()
                logging.debug(f"{log_prefix} Активный таймер обработки отменен.")
            except Exception as e:
                logging.warning(f"{log_prefix} Ошибка при отмене таймера: {e}")
    await message.answer("🧹 История разговора и буфер текущих сообщений очищены!")

@router.message(Command("reset"))
async def reset_conversation(message: aiogram_types.Message):
    """Полностью сбрасывает разговор, включая удаление треда, истории и буфера."""
    user_id = message.from_user.id
    log_prefix = f"reset_conversation(user:{user_id}):"
    logging.info(f"{log_prefix} Команда получена.")
    # Очистка локальных данных
    if user_id in user_messages: del user_messages[user_id]
    if user_id in pending_messages: del pending_messages[user_id]
    if user_id in user_message_timers:
        old_timer = user_message_timers.pop(user_id)
        if not old_timer.done():
            try: 
                old_timer.cancel()
            except Exception as e:
                logging.debug(f"{log_prefix} Ошибка при отмене таймера: {e}")
    # Очистка треда OpenAI (локально)
    if user_id in user_threads:
        thread_id_to_delete = user_threads.pop(user_id)
        logging.info(f"{log_prefix} Удаление локальной записи о треде {thread_id_to_delete}...")
        # Опционально: физическое удаление треда на стороне OpenAI
        # try:
        #     client = openai.OpenAI(api_key=OPENAI_API_KEY)
        #     client.beta.threads.delete(thread_id_to_delete)
        #     logging.info(f"{log_prefix} Тред {thread_id_to_delete} удален на OpenAI.")
        # except Exception as e_del:
        #     logging.warning(f"{log_prefix} Не удалось удалить тред {thread_id_to_delete} на OpenAI: {e_del}")

    logging.debug(f"{log_prefix} Сброс завершен.")
    await message.answer("🔄 Разговор полностью сброшен! Ваш следующий вопрос начнет новый диалог.")

@router.message(Command("reset_all"))
async def reset_all_conversations(message: aiogram_types.Message):
    """Полностью сбрасывает все разговоры всех пользователей (только для администратора)."""
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        await message.answer("❌ У вас нет прав для выполнения этой команды!")
        return
    logging.warning(f"Администратор {user_id} инициировал полный сброс!")
    active_timer_count = len(user_message_timers)
    for task in user_message_timers.values():
        try: 
            task.cancel()
        except Exception as e:
            logging.debug(f"Ошибка при отмене таймера: {e}")
    user_message_timers.clear()
    pending_messages.clear()
    user_messages.clear()
    user_threads.clear()
    logging.info(f"Полный сброс: {active_timer_count} таймеров отменено, буферы, история и треды очищены.")
    await message.answer("🔄 Все разговоры (история, буферы, таймеры, треды) всех пользователей полностью сброшены!")

@router.message(Command("update"))
async def update_knowledge(message: aiogram_types.Message):
    """Запускает обновление базы знаний вручную и уведомляет."""
    await message.answer("🔄 Обновляю базу знаний в фоновом режиме...")
    asyncio.create_task(run_update_and_notify(message.chat.id))

@router.message(Command("check_db"))
async def check_database(message: aiogram_types.Message):
    """Проверяет наличие и содержимое активной векторной базы знаний."""
    active_persist_directory = _get_active_db_path()
    
    if not active_persist_directory:
        await message.answer("❌ Активная база знаний не определена (файл пути не найден или некорректен).")
        return

    # Проверка существования активной директории (хотя _get_active_db_path это уже делает)
    if not os.path.exists(active_persist_directory) or not os.path.isdir(active_persist_directory):
        await message.answer(f"❌ Активная директория базы '{active_persist_directory}', указанная в файле, не найдена!")
        return
        
    files_list = []
    try:
        files_list = os.listdir(active_persist_directory)
        # Пытаемся подключиться и получить количество записей
        import chromadb
        client = chromadb.PersistentClient(path=active_persist_directory)
        try:
            collection = client.get_collection("documents")
            count = collection.count()
            await message.answer(f"✅ Активная база: '{active_persist_directory}' ({count} зап.).\nФайлы: {', '.join(files_list)}")
        except Exception as e:
             await message.answer(f"✅ Активная база: '{active_persist_directory}' существует, но ошибка доступа к коллекции 'documents': {e}\nФайлы: {', '.join(files_list)}")
    except ImportError:
         await message.answer(f"✅ Активная директория: '{active_persist_directory}'.\nФайлы: {', '.join(files_list)}\n(chromadb не импортирован для проверки коллекции)")
    except Exception as e:
         files_str = ", ".join(files_list) if files_list else "(не удалось прочитать)"
         await message.answer(f"✅ Активная директория: '{active_persist_directory}'.\nФайлы: {files_str}\n(Ошибка доступа к базе/директории: {e})")

@router.message(Command("debug_db"))
async def debug_database(message: aiogram_types.Message):
    """Диагностика активной базы данных векторов."""
    try:
        await message.answer("🔍 Проверяю активную базу векторов...")
        active_persist_directory = _get_active_db_path()

        if not active_persist_directory:
            await message.answer("❌ Активная база знаний не определена (файл пути не найден или некорректен).")
            # Дополнительно проверим базовую директорию на всякий случай
            base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_vector_db")
            if os.path.exists(base_dir):
                await message.answer(f"Базовая директория '{base_dir}' существует.")
            else:
                await message.answer(f"Базовая директория '{base_dir}' не существует.")
            return

        await message.answer(f"📂 Активный путь базы: {active_persist_directory}")

        # Проверка существования (хотя _get_active_db_path это уже делает)
        if not os.path.exists(active_persist_directory) or not os.path.isdir(active_persist_directory):
            await message.answer(f"❌ Директория активной базы '{active_persist_directory}', указанная в файле, не найдена!")
            return
            
        db_time = get_vector_db_creation_time() # Время последнего успешного ЗАВЕРШЕНИЯ обновления
        time_str = db_time.strftime("%d.%m.%Y %H:%M:%S") if db_time else "Не определено (last_update.txt)"
        await message.answer(f"📅 Время последнего успешного обновления (из last_update.txt): {time_str}")
        
        try:
            files = os.listdir(active_persist_directory)
            await message.answer(f"📄 Файлы в активной базе: {', '.join(files)}")
        except Exception as list_err:
             await message.answer(f"❌ Не удалось прочитать файлы в активной директории: {list_err}")

        try:
            import chromadb
            client = chromadb.PersistentClient(path=active_persist_directory)
            await message.answer("✅ Клиент ChromaDB для активной базы создан.")
            try:
                collection = client.get_collection("documents")
                count = collection.count()
                await message.answer(f"✅ Коллекция 'documents' в активной базе ({count} зап.).")
                await message.answer("⏳ Тестовый запрос 'тест' к активной базе...")
                # get_relevant_context уже использует _get_active_db_path внутри себя
                test_context = await get_relevant_context("тест", k=1) 
                if test_context:
                    await message.answer(f"✅ Запрос к активной базе успешен. Контекст:\n{test_context[:500]}...")
                else:
                     await message.answer("⚠️ Запрос к активной базе выполнен, контекст не найден.")
            except Exception as e_coll:
                await message.answer(f"❌ Ошибка доступа к коллекции в активной базе: {str(e_coll)}")
        except ImportError:
            await message.answer("❌ chromadb не импортирован.")
        except Exception as e_client:
            await message.answer(f"❌ Ошибка клиента ChromaDB для активной базы: {str(e_client)}")
    except Exception as e_main:
        await message.answer(f"❌ Ошибка диагностики: {str(e_main)}")

@router.message(Command("db_time"))
async def check_db_time(message: aiogram_types.Message):
    """Показывает время последнего обновления базы данных."""
    db_time = get_vector_db_creation_time()
    if db_time:
        time_str = db_time.strftime("%d.%m.%Y %H:%M:%S")
        await message.answer(f"📅 База данных обновлялась (файл/мод.): {time_str}")
    else:
        await message.answer("❌ Не удалось определить время обновления.")

@router.message(Command("full_debug"))
async def full_debug(message: aiogram_types.Message):
    """Полная диагностика системы и базы данных"""
    try:
        await message.answer("🔎 Запускаю полную диагностику...")
        current_dir = os.getcwd()
        await message.answer(f"🐍 Рабочая директория python: {current_dir}")
        
        # --- Проверка активной базы --- 
        active_persist_directory = _get_active_db_path()
        if active_persist_directory:
            await message.answer(f"✅ Активный путь базы данных (из файла): {active_persist_directory}")
        else:
            await message.answer("⚠️ Активный путь базы данных не определен (файл пути не найден/некорректен).")
        # --- Конец проверки активной базы ---
        
        # --- Проверка базовой директории (остается полезной для обзора) ---
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_vector_db")
        await message.answer(f"📂 Проверяемая базовая директория: {base_dir}")
        
        # Убираем лишний db_paths, проверяем только base_dir
        # db_paths = ["./local_vector_db", os.path.join(current_dir, "local_vector_db")]
        # found_path = None 
        # for path in db_paths:
        
        if os.path.exists(base_dir) and os.path.isdir(base_dir):
            await message.answer(f"✅ Базовая директория существует.")
            # found_path = base_dir
            try:
                items = os.listdir(base_dir)
                subdirs = [d for d in items if os.path.isdir(os.path.join(base_dir, d)) and re.match(r'^\\d{8}_\\d{6}_\\d{6}$', d)]
                other_files = [f for f in items if os.path.isfile(os.path.join(base_dir, f))]
                
                await message.answer(f"📄 Поддиректорий с базами данных (похожих на временные метки): {len(subdirs)}")
                if subdirs:
                    await message.answer(f"   (Последние 5: {", ".join(sorted(subdirs)[-5:])})")
                await message.answer(f"📄 Других файлов в базовой директории: {len(other_files)} ({", ".join(other_files)})")
                    
                # Размер и время модификации самой базовой директории (не очень информативно)
                # total_size = sum(os.path.getsize(os.path.join(base_dir, f)) for f in items if os.path.isfile(os.path.join(base_dir, f)))
                # await message.answer(f"📊 Общий размер файлов в базовой директории: {total_size/1024/1024:.2f} МБ")
                # try:
                #      latest_mod = max(os.path.getmtime(os.path.join(base_dir, f)) for f in items if os.path.isfile(os.path.join(base_dir, f)))
                #      mod_time = datetime.fromtimestamp(latest_mod)
                #      await message.answer(f"🕒 Последнее изменение файла в базовой директории: {mod_time.strftime('%d.%m.%Y %H:%M:%S')}")
                # except ValueError:
                #       await message.answer("🕒 Нет файлов для определения времени.")
                # except Exception as e_time:
                #       await message.answer(f"❌ Ошибка времени изменения: {str(e_time)}")
            except Exception as e_list:
                 await message.answer(f"❌ Ошибка листинга {base_dir}: {str(e_list)}")
        else:
            await message.answer(f"❌ Базовая директория не существует: {base_dir}")
        # --- Конец проверки базовой директории ---
        
        # Время из last_update.txt все еще может быть полезно
        db_time_from_file = get_vector_db_creation_time()
        time_str = db_time_from_file.strftime("%d.%m.%Y %H:%M:%S") if db_time_from_file else "Не найдено"
        await message.answer(f"📅 Время последнего УСПЕШНОГО обновления (из last_update.txt): {time_str}")
        
        await message.answer("✅ Диагностика путей завершена.")
    except Exception as e:
        await message.answer(f"❌ Ошибка диагностики: {str(e)}")

@router.message(Command("debug_context"))
async def debug_context(message: aiogram_types.Message):
    """Показывает контекст, который модель получает для запроса."""
    user_id = message.from_user.id
    query = message.text.replace("/debug_context", "").strip()
    if not query:
        await message.answer("Укажите запрос после команды: `/debug_context ваш вопрос`")
        return
    await message.answer(f"🔍 Получаю контекст для: '{query}'...")
    context = await get_relevant_context(query)
    if not context:
        await message.answer("❌ Контекст из базы не найден.")
        history = user_messages.get(user_id, [])
        if history:
             history_text = "\n".join([f"{msg['role']}: {msg['content'][:100]}..." for msg in history[-5:]])
             await message.answer(f"📜 История диалога (последние 5):\n{history_text}")
        return
    max_length = 4000
    if len(context) <= max_length:
        await message.answer(f"📚 Найденный контекст:\n\n{context}")
    else:
        parts = [context[i:i+max_length] for i in range(0, len(context), max_length)]
        await message.answer(f"📚 Найденный контекст ({len(parts)} частей):")
        for i, part in enumerate(parts):
            try:
                await message.answer(f"Часть {i+1}/{len(parts)}:\n\n{part}")
                await asyncio.sleep(0.5)
            except Exception as e_send:
                 logging.error(f"Ошибка отправки части {i+1} контекста: {e_send}")
                 await message.answer(f"❌ Не удалось отправить часть {i+1}.")
                 break

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ (Корректная буферизация) ---

@dp.business_message()
async def handle_business_message(message: aiogram_types.Message):
    """Обрабатывает входящее бизнес-сообщение: менеджер или клиент."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_input = message.text or "" # Используем пустую строку если текста нет
    business_connection_id = message.business_connection_id
    log_prefix = f"handle_business_message(user:{user_id}, chat:{chat_id}):"
    logging.debug(f"{log_prefix} Вход")

    # --- Логика определения менеджера ---
    is_from_manager = message.from_user.id in MANAGER_USER_IDS or message.from_user.id == ADMIN_USER_ID
    # ---

    if is_from_manager:
        # Проверяем, является ли отправитель администратором
        if message.from_user.id == ADMIN_USER_ID:
            logging.info(f"{log_prefix} Сообщение от АДМИНИСТРАТОРА. Режим молчания НЕ включается.")
            # Не включаем режим молчания и не выходим, позволяем обработке продолжиться ниже
            pass # Просто продолжаем выполнение кода для обработки как сообщение клиента
        else:
            # Это сообщение от МЕНЕДЖЕРА (не админа)
            logging.info(f"{log_prefix} Сообщение от МЕНЕДЖЕРА. Проверяем команды.")
            try:
                # Обработка команды /speak от менеджера
                if user_input.lower() in ["speak", "/speak"]:
                    if await is_chat_silent(chat_id):
                        logging.info(f"{log_prefix} Менеджер активировал бота командой '{user_input}'.")
                        await set_chat_silence(chat_id, False)
                    else:
                        logging.info(f"{log_prefix} Бот уже активен, команда '{user_input}' проигнорирована.")
                    # Отправляем звездочку в любом случае, чтобы показать, что команда получена
                    try: 
                        await message.answer("*")
                    except Exception as e:
                        logging.debug(f"Не удалось отправить подтверждение: {e}")
                    return # Завершаем обработку команды активации
                
                # Любое другое сообщение от менеджера включает режим молчания
                logging.info(f"{log_prefix} Сообщение от менеджера (не /speak). Включаем/продлеваем режим молчания.")
                await set_chat_silence(chat_id, True) # Включает или обновляет таймер
                # Бот не отвечает на другие сообщения менеджеров
                return
            except Exception as manager_error:
                logging.error(f"{log_prefix} Ошибка при обработке сообщения от менеджера: {manager_error}", exc_info=True)
                return # Не продолжаем обработку в случае ошибки

    # --- Обработка сообщения от КЛИЕНТА (или АДМИНА в бизнес-чате) ---
    try:
        # Проверяем режим молчания
        if await is_chat_silent(chat_id):
            logging.info(f"{log_prefix} Бот в режиме молчания, сообщение клиента игнорируется.")
            return

        # Игнорируем пустые сообщения от клиента
        if not user_input.strip():
             logging.info(f"{log_prefix} Пустое сообщение от клиента, игнорируем.")
             return

        # Логика буферизации
        logging.debug(f"{log_prefix} Добавление бизнес-сообщения в буфер.")
        pending_messages.setdefault(user_id, []).append(user_input)
        logging.debug(f"{log_prefix} Текущий буфер: {pending_messages.get(user_id, [])}")

        # Отменяем старый таймер, если он есть и активен
        if user_id in user_message_timers:
            old_timer = user_message_timers.pop(user_id) # Удаляем сразу
            if not old_timer.done():
                try:
                    old_timer.cancel()
                    logging.debug(f"{log_prefix} Предыдущий бизнес-таймер отменен.")
                except Exception as e_cancel:
                    logging.warning(f"{log_prefix} Не удалось отменить старый бизнес-таймер: {e_cancel}")

        # Запускаем новый таймер
        logging.debug(f"{log_prefix} Запуск нового бизнес-таймера ({MESSAGE_BUFFER_SECONDS} сек).")
        new_timer_task = asyncio.create_task(
            schedule_buffered_processing(user_id, chat_id, business_connection_id) # Передаем ID
        )
        user_message_timers[user_id] = new_timer_task
        logging.debug(f"{log_prefix} Новый бизнес-таймер сохранен.")

    except Exception as client_error:
        # Эта ошибка ловится до вызова асинхронных операций буферизации
        logging.error(f"{log_prefix} Ошибка при начальной обработке сообщения клиента: {client_error}", exc_info=True)

@router.message(F.business_connection_id.is_(None))
async def handle_message(message: aiogram_types.Message):
    """Обрабатывает входящее обычное (не бизнес) сообщение пользователя."""
    user_id = message.from_user.id
    user_input = message.text or "" # Используем пустую строку если текста нет
    chat_id = message.chat.id
    log_prefix = f"handle_message(user:{user_id}, chat:{chat_id}):"
    logging.debug(f"{log_prefix} Вход")

    # Игнорируем пустые сообщения
    if not user_input.strip():
        logging.info(f"{log_prefix} Пустое сообщение, игнорируем.")
        return

    # Логика буферизации (аналогично бизнес-чатам, но без business_connection_id)
    logging.debug(f"{log_prefix} Добавление сообщения в буфер.")
    pending_messages.setdefault(user_id, []).append(user_input)
    logging.debug(f"{log_prefix} Текущий буфер: {pending_messages.get(user_id, [])}")

    # Отменяем старый таймер, если он есть и активен
    if user_id in user_message_timers:
        old_timer = user_message_timers.pop(user_id) # Удаляем сразу
        if not old_timer.done():
             try:
                 old_timer.cancel()
                 logging.debug(f"{log_prefix} Предыдущий таймер отменен.")
             except Exception as e_cancel:
                 logging.warning(f"{log_prefix} Не удалось отменить старый таймер: {e_cancel}")

    # Запускаем новый таймер
    logging.debug(f"{log_prefix} Запуск нового таймера ({MESSAGE_BUFFER_SECONDS} сек).")
    new_timer_task = asyncio.create_task(
        schedule_buffered_processing(user_id, chat_id, None) # business_connection_id is None
    )
    user_message_timers[user_id] = new_timer_task
    logging.debug(f"{log_prefix} Новый таймер сохранен.")

# --- Удаляем старые/ошибочные функции --- 
# async def process_user_message_queue(user_id):
#    ...
# async def handle_message_timer(user_id, chat_id):
#    ...

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (periodic_cleanup, save/get_vector_db_creation_time, log_context, main, PID, signal_handler) ---

async def periodic_cleanup():
    """Запускает периодическую очистку логов контекста"""
    while True:
        try:
            await cleanup_old_context_logs()
            logging.info("periodic_cleanup: Выполнена очистка старых логов контекста.")
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
             logging.info("periodic_cleanup: Задача очистки логов отменена.")
             break
        except Exception as e:
            logging.error(f"periodic_cleanup: Ошибка: {str(e)}", exc_info=True)
            await asyncio.sleep(300)

async def cleanup_old_context_logs():
    """Удаляет логи контекста, которые старше 24 часов"""
    try:
        current_time = time.time()
        one_day_ago = current_time - 86400
        log_files = glob.glob(os.path.join(LOGS_DIR, "context_log_*_*.txt"))
        count = 0
        for log_file in log_files:
            try:
                file_mod_time = os.path.getmtime(log_file)
                if file_mod_time < one_day_ago:
                    os.remove(log_file)
                    count += 1
            except OSError as e:
                 logging.warning(f"Не удалось удалить старый лог {log_file}: {e}")
        if count > 0:
            logging.info(f"cleanup_old_context_logs: Удалено {count} устаревших файлов контекста.")
        else:
            logging.debug("cleanup_old_context_logs: Устаревшие файлы контекста не найдены.")
    except Exception as e:
        logging.error(f"cleanup_old_context_logs: Ошибка при очистке логов: {str(e)}")

def save_vector_db_creation_time():
    """Сохраняет текущее время как время создания/обновления векторной базы данных"""
    persist_directory = "./local_vector_db"
    timestamp_file = os.path.join(persist_directory, "last_update.txt")
    try:
        os.makedirs(persist_directory, exist_ok=True)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(timestamp_file, "w") as f:
            f.write(current_time)
        logging.info(f"Сохранено время обновления базы: {current_time} в {timestamp_file}")
        return True
    except Exception as e:
        logging.error(f"Ошибка при сохранении времени обновления базы в {timestamp_file}: {str(e)}")
        return False

def get_vector_db_creation_time():
    """Получает время создания/обновления векторной базы данных из файла или по модификации."""
    persist_directory = "./local_vector_db"
    timestamp_file = os.path.join(persist_directory, "last_update.txt")
    db_time = None
    if os.path.exists(timestamp_file):
        try:
            with open(timestamp_file, "r") as f:
                time_str = f.read().strip()
                db_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                logging.debug(f"Время обновления базы из файла: {db_time}")
                return db_time
        except Exception as file_err:
            logging.warning(f"Ошибка чтения файла времени ({timestamp_file}): {str(file_err)}")
    logging.debug("Файл времени не найден/ошибка, проверяем модификацию файлов...")
    if os.path.exists(persist_directory) and os.path.isdir(persist_directory):
        try:
            files = [os.path.join(persist_directory, f) for f in os.listdir(persist_directory)
                     if os.path.isfile(os.path.join(persist_directory, f))]
            if files:
                latest_time_ts = max(os.path.getmtime(f) for f in files)
                db_time = datetime.fromtimestamp(latest_time_ts)
                logging.debug(f"Время обновления базы по модификации: {db_time}")
                return db_time
            else:
                 logging.warning(f"Директория {persist_directory} пуста.")
        except Exception as mod_err:
            logging.error(f"Ошибка получения времени модификации {persist_directory}: {str(mod_err)}")
    else:
        logging.warning(f"Директория базы {persist_directory} не существует.")
    if db_time is None:
        logging.warning("Не удалось определить время обновления базы.")
    return db_time

async def log_context(user_id, query, context):
    """Логирует запрос и контекст в отдельный файл"""
    try:
        timestamp = int(time.time())
        filename = f"context_log_{user_id}_{timestamp}.txt"
        filepath = os.path.join(LOGS_DIR, filename)
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"User ID: {user_id}\n")
            f.write(f"Запрос:\n{query}\n\n")
            f.write(f"Найденный контекст:\n{context}\n")
        logging.debug(f"Контекст для user_id {user_id} сохранен в {filepath}")
    except Exception as e:
        logging.error(f"Ошибка логирования контекста для user_id {user_id}: {str(e)}")

async def main():
    """Основная функция запуска бота."""
    logging.info("🚀 Запуск бота...")
    if not all([TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, ASSISTANT_ID, FOLDER_ID]):
         logging.critical("КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют переменные окружения.")
         return
    create_pid_file()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    cleanup_task = None
    try:
        logging.info("📁 Проверка Google Drive...")
        try:
             get_drive_service()
             logging.info("✅ Google Drive доступен.")
        except Exception as drive_err:
             logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Google Drive недоступен: {drive_err}. Остановка.")
             return
        logging.info("Запуск обновления базы в фоне...")
        asyncio.create_task(update_vector_store()) # Не ждем завершения здесь
        dp.include_router(router)
        cleanup_task = asyncio.create_task(periodic_cleanup())
        logging.info("🤖 Бот готов к работе")
        logging.info(f"⏱️ Буферизация: {MESSAGE_BUFFER_SECONDS} сек")
        await dp.start_polling(bot)
    except asyncio.CancelledError:
         logging.info("Основная задача бота отменена.")
    except Exception as e:
        logging.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА при работе бота: {str(e)}", exc_info=True)
    finally:
        logging.info("Остановка бота...")
        if cleanup_task and not cleanup_task.done():
            cleanup_task.cancel()
            logging.info("Задача очистки логов отменена.")
        active_timers = list(user_message_timers.values())
        if active_timers:
             logging.info(f"Отмена {len(active_timers)} таймеров обработки...")
             for timer_task in active_timers:
                 timer_task.cancel()
             await asyncio.sleep(1)
        try:
             await bot.session.close()
             logging.info("Сессия бота закрыта.")
        except Exception as e_close:
             logging.warning(f"Ошибка при закрытии сессии бота: {e_close}")
        logging.info("Остановка завершена.")
        remove_pid_files()

def create_pid_file():
    """Создает PID файл для текущего процесса."""
    pid = os.getpid()
    pid_file_base = 'bot'
    pid_file = f'{pid_file_base}.pid'
    i = 1
    while os.path.exists(pid_file):
        i += 1
        pid_file = f'{pid_file_base}_{i}.pid'
    try:
        with open(pid_file, 'w') as f:
            f.write(str(pid))
        logging.info(f"Создан PID файл: {pid_file} (PID: {pid})")
    except OSError as e:
         logging.error(f"Не удалось создать PID файл {pid_file}: {e}")

def remove_pid_files():
    """Удаляет все PID файлы, соответствующие шаблону bot*.pid"""
    pid_files = glob.glob('bot*.pid')
    if not pid_files:
         logging.debug("PID файлы не найдены для удаления.")
         return
    logging.info(f"Удаление PID файлов: {pid_files}...")
    for pid_file in pid_files:
        try:
            os.remove(pid_file)
            logging.info(f"Удален файл {pid_file}")
        except OSError as e:
            logging.error(f"Ошибка при удалении {pid_file}: {str(e)}")

def signal_handler(sig, frame):
    """Обработчик сигналов для корректного завершения работы."""
    signame = signal.Signals(sig).name
    logging.warning(f"Получен сигнал {signame}. Начинаем остановку...")
    remove_pid_files()
    try:
        loop = asyncio.get_running_loop()
        logging.info("Отменяем все активные задачи asyncio...")
        for task in asyncio.all_tasks(loop):
            if task is not asyncio.current_task(): # Не отменяем саму себя
                 task.cancel()
        # Даем время задачам на отмену
        # loop.create_task(asyncio.sleep(1)) # Не лучший способ
    except RuntimeError: # Если loop не запущен
         logging.info("Event loop не запущен, остановка без отмены задач.")
    # Остановка должна произойти в finally блока main
    logging.info(f"Сигнал {signame} обработан. Завершение...")
    # Не вызываем sys.exit(), чтобы finally в main мог выполниться


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную (KeyboardInterrupt).")
    except asyncio.CancelledError:
         logging.info("Основная задача выполнения отменена.")
    except Exception as e:
        logging.critical(f"КРИТИЧЕСКАЯ НЕПЕРЕХВАЧЕННАЯ ОШИБКА: {str(e)}", exc_info=True)
        remove_pid_files()