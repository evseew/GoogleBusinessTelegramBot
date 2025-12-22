"""
Инструменты для работы с Pyrus API.
Создание задач для администраторов филиалов.
"""

import os
import json
import logging
import httpx
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --- Конфигурация Pyrus API ---
PYRUS_API_URL = os.getenv("PYRUS_API_URL", "https://api.pyrus.com/v4/")
PYRUS_LOGIN = os.getenv("PYRUS_LOGIN")
PYRUS_SECURITY_KEY = os.getenv("PYRUS_SECURITY_KEY")

# ID формы "Сообщение из бота"
PYRUS_FORM_ID = 2379057

# ID каталога филиалов в Pyrus
PYRUS_BRANCH_CATALOG_ID = 124811

# Mapping ID полей формы
FORM_FIELDS = {
    "branch": 1,           # Филиал (catalog)
    "client_name": 2,      # ФИО клиента (text)
    "client_phone": 3,     # Телефон клиента (phone)
    "student_name": 4,     # ФИО ребёнка (text)
    "group_number": 5,     # Группа (number)
    "message": 6           # Сообщение от клиента (text)
}

# Mapping названий филиалов branches.json → названия в Pyrus
# Ключ: id из branches.json, Значение: название в каталоге Pyrus
BRANCH_NAME_TO_PYRUS = {
    "chicherina_25b": "Северо-Запад: Чичерина, 25б",
    "kashirinykh_97": "Северо-Запад: Кашириных, 97",
    "kashirinykh_131": "Академ: Кашириных, 131",
    "makeeva_15": "Тополинка: Макеева, 15",
    "sverdlovsky_84b": "Центр: Свердловский, 84Б",
    "kommuny_106": "Центр: Коммуны, 106/1",
    "komarova_127a": "ЧТЗ: Комарова, 127А",
    "dzerzhinskogo_82": "Ленинский: Дзержинского, 82",
    "khmelnitskogo_19": "ЧМЗ: Б.Хмельницкого, 19",
    "parkovy": "Парковый: Краснопольский, 34",
    "zalcmana_10": "Чурилово: Зальцмана, 10",
    "kopeysk_kommunisticheskiy": "Копейск: Коммунистический, 22",
    "kopeysk_slavy": "Копейск: Славы, 30",
    "online": "Online"
}

# Обратный mapping: человекочитаемое название → Pyrus название
BRANCH_DISPLAY_TO_PYRUS = {
    # Короткие названия
    "чичерина": "Северо-Запад: Чичерина, 25б",
    "кашириных 97": "Северо-Запад: Кашириных, 97",
    "кашириных 131": "Академ: Кашириных, 131",
    "академ": "Академ: Кашириных, 131",
    "макеева": "Тополинка: Макеева, 15",
    "тополинка": "Тополинка: Макеева, 15",
    "свердловский": "Центр: Свердловский, 84Б",
    "коммуны": "Центр: Коммуны, 106/1",
    "комарова": "ЧТЗ: Комарова, 127А",
    "чтз": "ЧТЗ: Комарова, 127А",
    "дзержинского": "Ленинский: Дзержинского, 82",
    "ленинский": "Ленинский: Дзержинского, 82",
    "хмельницкого": "ЧМЗ: Б.Хмельницкого, 19",
    "чмз": "ЧМЗ: Б.Хмельницкого, 19",
    "парковый": "Парковый: Краснопольский, 34",
    "краснопольский": "Парковый: Краснопольский, 34",
    "зальцмана": "Чурилово: Зальцмана, 10",
    "чурилово": "Чурилово: Зальцмана, 10",
    "копейск коммунистический": "Копейск: Коммунистический, 22",
    "копейск славы": "Копейск: Славы, 30",
    "онлайн": "Online",
    "online": "Online",
    # Полные названия Pyrus (для точного совпадения)
    "северо-запад: чичерина, 25б": "Северо-Запад: Чичерина, 25б",
    "северо-запад: кашириных, 97": "Северо-Запад: Кашириных, 97",
    "академ: кашириных, 131": "Академ: Кашириных, 131",
    "тополинка: макеева, 15": "Тополинка: Макеева, 15",
    "центр: свердловский, 84б": "Центр: Свердловский, 84Б",
    "центр: коммуны, 106/1": "Центр: Коммуны, 106/1",
    "чтз: комарова, 127а": "ЧТЗ: Комарова, 127А",
    "ленинский: дзержинского, 82": "Ленинский: Дзержинского, 82",
    "чмз: б.хмельницкого, 19": "ЧМЗ: Б.Хмельницкого, 19",
    "парковый: краснопольский, 34": "Парковый: Краснопольский, 34",
    "чурилово: зальцмана, 10": "Чурилово: Зальцмана, 10",
    "копейск: коммунистический, 22": "Копейск: Коммунистический, 22",
    "копейск: славы, 30": "Копейск: Славы, 30",
}


# --- Кэш для каталога филиалов Pyrus (item_id mapping) ---
_pyrus_branch_catalog_cache: Optional[Dict[str, int]] = None
_pyrus_access_token: Optional[str] = None


def _join_url(path: str) -> str:
    """Безопасная склейка base_url и path."""
    base = PYRUS_API_URL.rstrip('/')
    path = path.lstrip('/')
    return f"{base}/{path}"


def _authenticate_sync() -> Optional[str]:
    """
    Синхронная авторизация в Pyrus API.
    Возвращает access_token или None при ошибке.
    """
    global _pyrus_access_token
    
    if not PYRUS_LOGIN or not PYRUS_SECURITY_KEY:
        logger.error("❌ Pyrus: PYRUS_LOGIN или PYRUS_SECURITY_KEY не заданы в .env")
        return None
    
    logger.info(f"🔐 Pyrus: Авторизация ({PYRUS_API_URL})...")
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                _join_url("auth"),
                json={
                    "login": PYRUS_LOGIN,
                    "security_key": PYRUS_SECURITY_KEY
                }
            )
            
            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                logger.error(f"❌ Pyrus: Ошибка авторизации HTTP {response.status_code}: {error_data}")
                return None
            
            data = response.json()
            token = data.get("access_token")
            
            if not token:
                logger.error("❌ Pyrus: Токен не найден в ответе API")
                return None
            
            _pyrus_access_token = token
            logger.info("✅ Pyrus: Авторизация успешна!")
            return token
            
    except Exception as e:
        logger.error(f"❌ Pyrus: Исключение при авторизации: {e}", exc_info=True)
        return None


def _get_token_sync() -> Optional[str]:
    """Получить access_token (с кешированием)."""
    global _pyrus_access_token
    if _pyrus_access_token:
        return _pyrus_access_token
    return _authenticate_sync()


def _load_branch_catalog_sync() -> Dict[str, int]:
    """
    Загружает каталог филиалов из Pyrus API.
    Возвращает словарь: название филиала → item_id
    """
    global _pyrus_branch_catalog_cache
    
    if _pyrus_branch_catalog_cache is not None:
        return _pyrus_branch_catalog_cache
    
    token = _get_token_sync()
    if not token:
        logger.error("❌ Pyrus: Не удалось получить токен для загрузки каталога")
        return {}
    
    logger.info(f"📂 Pyrus: Загрузка каталога филиалов (ID: {PYRUS_BRANCH_CATALOG_ID})...")
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                _join_url(f"catalogs/{PYRUS_BRANCH_CATALOG_ID}"),
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if response.status_code == 401:
                # Токен протух — переавторизуемся
                logger.warning("⚠️ Pyrus: Токен протух, переавторизация...")
                global _pyrus_access_token
                _pyrus_access_token = None
                token = _get_token_sync()
                if not token:
                    return {}
                response = client.get(
                    _join_url(f"catalogs/{PYRUS_BRANCH_CATALOG_ID}"),
                    headers={"Authorization": f"Bearer {token}"}
                )
            
            if response.status_code != 200:
                logger.error(f"❌ Pyrus: Ошибка загрузки каталога HTTP {response.status_code}")
                return {}
            
            data = response.json()
            items = data.get("items", [])
            
            # Строим mapping: название → item_id
            catalog_mapping = {}
            for item in items:
                # item обычно имеет структуру: {"item_id": 123, "values": ["Название"]}
                item_id = item.get("item_id")
                values = item.get("values", [])
                if item_id and values:
                    name = values[0]  # Первое значение — название
                    catalog_mapping[name] = item_id
                    logger.debug(f"  Филиал: '{name}' → item_id={item_id}")
            
            _pyrus_branch_catalog_cache = catalog_mapping
            logger.info(f"✅ Pyrus: Загружено {len(catalog_mapping)} филиалов из каталога")
            return catalog_mapping
            
    except Exception as e:
        logger.error(f"❌ Pyrus: Исключение при загрузке каталога: {e}", exc_info=True)
        return {}


def _resolve_branch_to_pyrus_item_id(branch_name: str) -> Optional[int]:
    """
    Преобразует название филиала в item_id каталога Pyrus.
    
    Args:
        branch_name: Название филиала (в любом формате)
    
    Returns:
        item_id для Pyrus или None если не найден
    """
    if not branch_name:
        return None
    
    branch_lower = branch_name.lower().strip()
    
    # 1. Пробуем найти через mapping BRANCH_DISPLAY_TO_PYRUS
    pyrus_name = BRANCH_DISPLAY_TO_PYRUS.get(branch_lower)
    
    # 2. Если не нашли — пробуем частичное совпадение
    if not pyrus_name:
        for key, value in BRANCH_DISPLAY_TO_PYRUS.items():
            if branch_lower in key or key in branch_lower:
                pyrus_name = value
                break
    
    if not pyrus_name:
        logger.warning(f"⚠️ Pyrus: Не удалось определить Pyrus-название для '{branch_name}'")
        # Используем как есть — может сработать
        pyrus_name = branch_name
    
    # 3. Загружаем каталог и ищем item_id
    catalog = _load_branch_catalog_sync()
    if not catalog:
        logger.warning(f"⚠️ Pyrus: Каталог пуст, возвращаем None для '{branch_name}'")
        return None
    
    # Точное совпадение
    if pyrus_name in catalog:
        return catalog[pyrus_name]
    
    # Поиск без учета регистра
    for cat_name, item_id in catalog.items():
        if cat_name.lower() == pyrus_name.lower():
            return item_id
    
    # Частичное совпадение
    for cat_name, item_id in catalog.items():
        if pyrus_name.lower() in cat_name.lower() or cat_name.lower() in pyrus_name.lower():
            logger.info(f"  Частичное совпадение: '{branch_name}' → '{cat_name}' (item_id={item_id})")
            return item_id
    
    logger.warning(f"⚠️ Pyrus: Филиал '{branch_name}' не найден в каталоге Pyrus")
    return None


def _create_task_sync(
    form_id: int,
    fields: List[Dict[str, Any]],
    text: Optional[str] = None,
    subject: Optional[str] = None
) -> Dict[str, Any]:
    """
    Создаёт задачу в Pyrus (синхронно).
    
    Args:
        form_id: ID формы
        fields: Список полей формы
        text: Комментарий к задаче
        subject: Тема задачи
    
    Returns:
        Результат создания задачи
    """
    token = _get_token_sync()
    if not token:
        return {"success": False, "error": "Не удалось авторизоваться в Pyrus"}
    
    payload = {
        "form_id": form_id,
        "fields": fields
    }
    
    if text:
        payload["text"] = text
    if subject:
        payload["subject"] = subject
    
    logger.info(f"📤 Pyrus: Создание задачи по форме {form_id}...")
    logger.debug(f"  Payload: {json.dumps(payload, ensure_ascii=False)}")
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                _join_url("tasks"),
                headers={"Authorization": f"Bearer {token}"},
                json=payload
            )
            
            if response.status_code == 401:
                # Токен протух
                logger.warning("⚠️ Pyrus: Токен протух при создании задачи, переавторизация...")
                global _pyrus_access_token
                _pyrus_access_token = None
                token = _get_token_sync()
                if not token:
                    return {"success": False, "error": "Не удалось переавторизоваться"}
                response = client.post(
                    _join_url("tasks"),
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload
                )
            
            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                logger.error(f"❌ Pyrus: Ошибка создания задачи HTTP {response.status_code}: {error_data}")
                return {
                    "success": False, 
                    "error": f"HTTP {response.status_code}: {error_data.get('error_message', 'Unknown error')}"
                }
            
            result = response.json()
            task = result.get("task", {})
            task_id = task.get("id")
            
            logger.info(f"✅ Pyrus: Задача создана! ID: {task_id}")
            
            return {
                "success": True,
                "task_id": task_id,
                "task_url": f"https://pyrus.com/t#{task_id}" if task_id else None
            }
            
    except Exception as e:
        logger.error(f"❌ Pyrus: Исключение при создании задачи: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# --- Основная функция для Function Calling ---

def create_pyrus_task(
    branch_name: str,
    message_text: str,
    client_name: Optional[str] = None,
    client_phone: Optional[str] = None,
    student_name: Optional[str] = None,
    group_number: Optional[int] = None,
    telegram_user_id: Optional[int] = None,
    login: Optional[str] = None
) -> Dict[str, Any]:
    """
    Создаёт задачу в Pyrus для администратора филиала.
    
    Используется когда клиент хочет передать информацию/вопрос
    администратору конкретного филиала.
    
    Args:
        branch_name: Название филиала (обязательно)
        message_text: Текст сообщения для администратора (обязательно)
        client_name: ФИО клиента (если известно)
        client_phone: Телефон клиента (если известен)
        student_name: ФИО ребёнка (если известно)
        group_number: Номер группы (если известен)
        telegram_user_id: ID пользователя Telegram (для автозаполнения из базы)
        login: Логин клиента/лицевой счёт (для автозаполнения из базы)
    
    Returns:
        Словарь с результатом:
        - success: True/False
        - task_id: ID созданной задачи (если успех)
        - message: Сообщение для клиента
    """
    logger.info(f"🎯 create_pyrus_task: branch='{branch_name}', message='{message_text[:50]}...', login={login}")
    
    # Автозаполнение данных из базы если переданы telegram_user_id и login
    if telegram_user_id and login:
        from .client_tools import get_verified_client_data
        
        logger.info(f"📋 Автозаполнение данных для login={login}")
        client_data = get_verified_client_data(login)
        
        if client_data:
            # Заполняем только те поля, которые не были переданы явно
            if not client_name:
                client_name = client_data.get('client_name')
                logger.info(f"  ✅ ФИО клиента: {client_name}")
            
            if not client_phone:
                client_phone = client_data.get('client_phone')
                logger.info(f"  ✅ Телефон: {client_phone}")
            
            if not student_name:
                student_name = client_data.get('student_name')
                logger.info(f"  ✅ ФИО ребёнка: {student_name}")
            
            if not group_number:
                group_number = client_data.get('group_number')
                logger.info(f"  ✅ Группа: {group_number}")
            
            # Если филиал не указан или пустой, берем из данных клиента
            if not branch_name or branch_name.strip() == '':
                branch_name = client_data.get('branch_name', branch_name)
                logger.info(f"  ✅ Филиал: {branch_name}")
        else:
            logger.warning(f"⚠️ Не удалось загрузить данные для login={login}")
    
    # Валидация обязательных полей
    if not branch_name or not branch_name.strip():
        return {
            "success": False,
            "error": "Не указан филиал",
            "message": "Для создания задачи необходимо указать филиал."
        }
    
    if not message_text or not message_text.strip():
        return {
            "success": False,
            "error": "Не указан текст сообщения",
            "message": "Для создания задачи необходимо указать текст сообщения."
        }
    
    # Получаем item_id филиала
    branch_item_id = _resolve_branch_to_pyrus_item_id(branch_name)
    
    # Формируем поля задачи
    fields = []
    
    # Поле 1: Филиал (catalog)
    if branch_item_id:
        fields.append({
            "id": FORM_FIELDS["branch"],
            "value": {"item_id": branch_item_id}
        })
    else:
        logger.warning(f"⚠️ Pyrus: Филиал '{branch_name}' не найден в каталоге, пропускаем поле")
    
    # Поле 2: ФИО клиента (text)
    if client_name and client_name.strip():
        fields.append({
            "id": FORM_FIELDS["client_name"],
            "value": client_name.strip()
        })
    
    # Поле 3: Телефон клиента (phone)
    if client_phone and client_phone.strip():
        # Нормализуем телефон
        phone = client_phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            if phone.startswith("8") and len(phone) == 11:
                phone = "+7" + phone[1:]
            elif phone.startswith("7") and len(phone) == 11:
                phone = "+" + phone
        fields.append({
            "id": FORM_FIELDS["client_phone"],
            "value": phone
        })
    
    # Поле 4: ФИО ребёнка (text)
    if student_name and student_name.strip():
        fields.append({
            "id": FORM_FIELDS["student_name"],
            "value": student_name.strip()
        })
    
    # Поле 5: Группа (number)
    if group_number is not None:
        fields.append({
            "id": FORM_FIELDS["group_number"],
            "value": group_number
        })
    
    # Поле 6: Сообщение (text) — ОБЯЗАТЕЛЬНО
    fields.append({
        "id": FORM_FIELDS["message"],
        "value": message_text.strip()
    })
    
    # Формируем тему задачи
    subject_parts = ["Сообщение из бота"]
    if client_name:
        subject_parts.append(f"от {client_name.strip()}")
    subject = " ".join(subject_parts)
    
    # Создаём задачу
    result = _create_task_sync(
        form_id=PYRUS_FORM_ID,
        fields=fields,
        subject=subject
    )
    
    if result.get("success"):
        return {
            "success": True,
            "task_id": result.get("task_id"),
            "message": (
                f"✅ Ваше обращение передано администратору филиала «{branch_name}». "
                f"Если потребуется, администратор передаст информацию старшему педагогу. "
                f"Задача создана и взята в работу — с вами свяжутся в ближайшее время!"
            )
        }
    else:
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "message": (
                "К сожалению, не удалось создать задачу. "
                "Скоро в чат подключится менеджер и поможет вам."
            )
        }


# --- Определение функции для OpenAI Tools ---

PYRUS_FUNCTION_NAME = "create_pyrus_task"

PYRUS_FUNCTION_DESCRIPTION = (
    "Создаёт задачу в системе Pyrus для администратора указанного филиала. "
    "Используй эту функцию ТОЛЬКО когда клиент подтвердил, что хочет передать "
    "информацию или вопрос администратору филиала. "
    "\n\n🔐 ПРОЦЕСС ВЕРИФИКАЦИИ И АВТОЗАПОЛНЕНИЯ (ВАЖНО!):\n"
    "1) Попроси клиента назвать номер телефона\n"
    "2) Вызови find_clients_by_phone(phone) → получишь логин\n"
    "3) Проверь верификацию: check_verification(telegram_user_id, login)\n"
    "4) Если НЕ верифицирован → покажи карточку, попроси подтверждение, вызови save_verification\n"
    "5) Выясни суть обращения и филиал\n"
    "6) ПЕРЕДАЙ telegram_user_id и login → данные заполнятся автоматически!\n"
    "7) Получи подтверждение от клиента и создай задачу\n"
    "\n💡 Если передашь telegram_user_id + login, поля (ФИО, телефон, ребёнок, группа) "
    "заполнятся из базы автоматически — клиенту не придется повторять данные!"
)

PYRUS_FUNCTION_PARAMETERS = {
    "type": "object",
    "properties": {
        "branch_name": {
            "type": "string",
            "description": (
                "Название филиала, администратору которого нужно передать сообщение. "
                "Например: 'Чичерина', 'Парковый', 'ЧТЗ', 'Копейск Коммунистический', 'Online'. "
                "ОБЯЗАТЕЛЬНЫЙ параметр."
            )
        },
        "message_text": {
            "type": "string",
            "description": (
                "Текст сообщения для администратора филиала. "
                "Должен содержать суть вопроса или просьбы клиента. "
                "Сформулируй чётко и понятно. ОБЯЗАТЕЛЬНЫЙ параметр."
            )
        },
        "telegram_user_id": {
            "type": "integer",
            "description": (
                "🔐 ID пользователя в Telegram (получи из контекста диалога). "
                "ПЕРЕДАВАЙ ВСЕГДА вместе с login для автозаполнения всех полей из базы! "
                "Это избавит клиента от повторного ввода ФИО, телефона, имени ребёнка и группы."
            )
        },
        "login": {
            "type": "string",
            "description": (
                "🔐 Логин (лицевой счёт) клиента, например '46168'. "
                "Получи через find_clients_by_phone после верификации. "
                "ПЕРЕДАВАЙ ВСЕГДА вместе с telegram_user_id → все поля заполнятся автоматически!"
            )
        },
        "client_name": {
            "type": "string",
            "description": (
                "ФИО клиента (родителя). "
                "⚠️ Можно НЕ указывать, если передал telegram_user_id + login (заполнится автоматически). "
                "Укажи явно только если нужно переопределить данные из базы."
            )
        },
        "client_phone": {
            "type": "string",
            "description": (
                "Контактный телефон клиента. "
                "⚠️ Можно НЕ указывать, если передал telegram_user_id + login (заполнится автоматически)."
            )
        },
        "student_name": {
            "type": "string",
            "description": (
                "ФИО ребёнка (студента). "
                "⚠️ Можно НЕ указывать, если передал telegram_user_id + login (заполнится автоматически)."
            )
        },
        "group_number": {
            "type": "integer",
            "description": (
                "Номер учебной группы. "
                "⚠️ Можно НЕ указывать, если передал telegram_user_id + login (заполнится автоматически)."
            )
        }
    },
    "required": ["branch_name", "message_text"]
}

# Формат для Chat Completions API
PYRUS_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": PYRUS_FUNCTION_NAME,
        "description": PYRUS_FUNCTION_DESCRIPTION,
        "parameters": PYRUS_FUNCTION_PARAMETERS
    }
}


def get_pyrus_tool_for_responses_api() -> Dict[str, Any]:
    """Возвращает tool в формате для Responses API."""
    return {
        "type": "function",
        "name": PYRUS_FUNCTION_NAME,
        "description": PYRUS_FUNCTION_DESCRIPTION,
        "parameters": PYRUS_FUNCTION_PARAMETERS
    }


# --- Список доступных филиалов для справки ---

def get_available_branches_for_pyrus() -> List[str]:
    """Возвращает список доступных филиалов для Pyrus."""
    return [
        "Северо-Запад: Чичерина, 25б",
        "Северо-Запад: Кашириных, 97",
        "Академ: Кашириных, 131",
        "Тополинка: Макеева, 15",
        "Центр: Свердловский, 84Б",
        "Центр: Коммуны, 106/1",
        "ЧТЗ: Комарова, 127А",
        "Ленинский: Дзержинского, 82",
        "ЧМЗ: Б.Хмельницкого, 19",
        "Парковый: Краснопольский, 34",
        "Чурилово: Зальцмана, 10",
        "Копейск: Коммунистический, 22",
        "Копейск: Славы, 30",
        "Online"
    ]

