"""
Инструменты для работы с филиалами Planet English.
Используются для OpenAI Function Calling.
"""

import json
import os
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Путь к файлу данных
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
BRANCHES_FILE = os.path.join(DATA_DIR, "branches.json")

# Кэш данных (загружается один раз)
_branches_cache: Optional[dict] = None


def load_branches_data() -> dict:
    """Загружает данные о филиалах из JSON-файла."""
    global _branches_cache
    if _branches_cache is None:
        with open(BRANCHES_FILE, "r", encoding="utf-8") as f:
            _branches_cache = json.load(f)
    return _branches_cache


def reload_branches_data() -> dict:
    """Принудительно перезагружает данные (если файл обновился)."""
    global _branches_cache
    _branches_cache = None
    return load_branches_data()


def _has_any_verification(telegram_user_id: int) -> bool:
    """
    Проверяет, есть ли у пользователя хотя бы одна актуальная верификация.
    
    Args:
        telegram_user_id: ID пользователя в Telegram
    
    Returns:
        True если есть хотя бы один верифицированный логин, False иначе
    """
    try:
        from tools.verification_tools import _load_verifications, is_client_verified
        
        verifications = _load_verifications()
        user_key = str(telegram_user_id)
        
        if user_key not in verifications:
            logger.debug(f"Верификация НЕ найдена для telegram_user={telegram_user_id}")
            return False
        
        user_data = verifications[user_key]
        logins = user_data.get('logins', [])
        
        # Проверяем, есть ли хотя бы один актуальный логин
        for login in logins:
            if is_client_verified(telegram_user_id, login):
                logger.debug(f"✅ Найдена верификация для telegram_user={telegram_user_id}, login={login}")
                return True
        
        logger.debug(f"Верификаций не найдено или все истекли для telegram_user={telegram_user_id}")
        return False
        
    except Exception as e:
        logger.error(f"Ошибка проверки верификации: {e}")
        return False


def get_branches(
    query_type: str,
    district: Optional[str] = None,
    city: Optional[str] = None,
    search_query: Optional[str] = None,
    telegram_user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Универсальная функция получения информации о филиалах.
    
    Args:
        query_type: Тип запроса
            - "all" — все филиалы
            - "by_district" — по району
            - "by_city" — по городу  
            - "by_name" — поиск по названию/адресу
        district: Название района (для by_district)
        city: Город (для by_city)
        search_query: Поисковый запрос (для by_name)
        telegram_user_id: ID пользователя в Telegram (для проверки верификации перед выдачей кода домофона)
    
    Returns:
        Словарь с результатами поиска
    """
    data = load_branches_data()
    branches = data["branches"]
    
    if query_type == "all":
        return _format_all_branches(branches, data, telegram_user_id)
    
    elif query_type == "by_district":
        if not district:
            return {"error": "Не указан район для поиска"}
        return _find_by_district(branches, district, data, telegram_user_id)
    
    elif query_type == "by_city":
        if not city:
            return {"error": "Не указан город для поиска"}
        return _find_by_city(branches, city, data, telegram_user_id)
    
    elif query_type == "by_name":
        if not search_query:
            return {"error": "Не указан поисковый запрос"}
        return _find_by_name(branches, search_query, telegram_user_id)
    
    return {"error": f"Неизвестный тип запроса: {query_type}"}


def _format_all_branches(branches: List[dict], data: dict, telegram_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Форматирует все филиалы, сгруппированные по районам."""
    by_district: Dict[str, List[dict]] = {}
    
    for b in branches:
        district = b["district"]
        if district not in by_district:
            by_district[district] = []
        by_district[district].append({
            "name": b["name"],
            "address": b["address"]
        })
    
    # Формируем читаемый вывод
    total = data["total_count"]
    
    return {
        "success": True,
        "total_chelyabinsk": total["Челябинск"],
        "total_kopeysk": total["Копейск"],
        "branches_by_district": by_district,
        "online_available": data["online"]["available"],
        "online_min_age": data["online"]["min_age"],
        "summary": f"Всего {total['Челябинск']} филиалов в Челябинске и {total['Копейск']} в Копейске. Также доступен онлайн-формат (от {data['online']['min_age']} лет)."
    }


def _find_by_district(
    branches: List[dict], 
    district: str, 
    data: dict,
    telegram_user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Ищет филиалы по району."""
    district_lower = district.lower().strip()
    found = []
    matched_district = None
    
    for b in branches:
        is_match = False
        
        # Проверяем название района
        if b["district"].lower() == district_lower:
            is_match = True
            
        # Проверяем алиасы района
        if not is_match:
            for alias in b["district_aliases"]:
                if district_lower == alias.lower() or district_lower in alias.lower():
                    is_match = True
                    break
        
        if is_match:
            branch_info = {
                "name": b["name"],
                "address": b["address"]
            }
            if b.get("landmark"):
                branch_info["landmark"] = b["landmark"]
            found.append(branch_info)
            matched_district = b["district"]
    
    if not found:
        return {
            "success": False,
            "found": False,
            "message": f"Филиалов в районе '{district}' не найдено",
            "suggestion": "Уточните район или запросите список всех филиалов"
        }
    
    # Проверяем, есть ли особые указания для этого района
    note = None
    grouping = data.get("districts_grouping", {})
    if matched_district and matched_district in grouping:
        note = grouping[matched_district].get("note")
    
    result = {
        "success": True,
        "found": True,
        "count": len(found),
        "district": matched_district or district,
        "branches": found
    }
    
    if note:
        result["note"] = note
    
    return result


def _find_by_city(branches: List[dict], city: str, data: dict, telegram_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Ищет филиалы по городу."""
    city_lower = city.lower().strip()
    found = []
    
    for b in branches:
        if b["city"].lower() == city_lower:
            branch_info = {
                "name": b["name"],
                "address": b["address"],
                "district": b["district"]
            }
            if b.get("landmark"):
                branch_info["landmark"] = b["landmark"]
            found.append(branch_info)
    
    if not found:
        return {
            "success": False,
            "found": False,
            "message": f"Филиалов в городе '{city}' не найдено",
            "available_cities": ["Челябинск", "Копейск"]
        }
    
    result = {
        "success": True,
        "found": True,
        "city": city.capitalize(),
        "count": len(found),
        "branches": found
    }
    
    # Для Копейска добавляем примечание
    grouping = data.get("districts_grouping", {})
    if city_lower == "копейск" and "Копейск" in grouping:
        result["note"] = grouping["Копейск"].get("note")
    
    return result


def _format_branch_details(b: dict, telegram_user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Форматирует полную информацию о филиале.
    
    Args:
        b: Данные филиала
        telegram_user_id: ID пользователя в Telegram (для проверки верификации)
    
    Returns:
        Словарь с деталями филиала
    """
    details = {
        "name": b["name"],
        "address": b["address"],
        "district": b["district"],
        "city": b["city"]
    }
    
    # Добавляем дополнительную информацию, если есть
    if b.get("landmark"):
        details["landmark"] = b["landmark"]
    if b.get("entrance"):
        details["entrance"] = b["entrance"]
    if b.get("floor"):
        details["floor"] = b["floor"]
    
    # 🔑 КОД ДОМОФОНА - защищённая выдача с верификацией
    if b.get("intercom_code"):
        # Проверяем верификацию, если передан telegram_user_id
        if telegram_user_id is not None:
            is_verified = _has_any_verification(telegram_user_id)
            
            if is_verified:
                # ✅ Клиент верифицирован - выдаём код
                details["intercom_code"] = b["intercom_code"]
                details["intercom_security_note"] = "⚠️ ОБЯЗАТЕЛЬНО добавь после кода: 'Напоминаем, что домофоны ведут видео- и аудиозапись в целях безопасности 📹'"
                logger.info(f"✅ Код домофона выдан верифицированному пользователю telegram_user={telegram_user_id}, филиал={b['name']}")
            else:
                # ❌ Клиент НЕ верифицирован - требуем верификацию
                details["intercom_code_protected"] = True
                details["verification_required"] = True
                details["verification_instruction"] = (
                    "🔐 Для получения кода домофона необходимо подтвердить, что вы родитель. "
                    "Спроси: 'Вы родитель? Как фамилия ребёнка и в какой группе он занимается?' "
                    "После подтверждения используй функцию find_clients_by_phone или search_client_by_name, "
                    "затем save_verification, и снова вызови get_branches с telegram_user_id."
                )
                logger.info(f"🔒 Код домофона НЕ выдан - требуется верификация telegram_user={telegram_user_id}, филиал={b['name']}")
        else:
            # Если telegram_user_id не передан - выдаём код (обратная совместимость)
            details["intercom_code"] = b["intercom_code"]
            details["intercom_security_note"] = "⚠️ ОБЯЗАТЕЛЬНО добавь после кода: 'Напоминаем, что домофоны ведут видео- и аудиозапись в целях безопасности 📹'"
            details["intercom_verification_required"] = "⚠️ ПЕРЕД выдачей кода спроси: 'Вы родитель? Как фамилия ребёнка и в какой группе он занимается?'"
            logger.warning(f"⚠️ Код домофона выдан БЕЗ проверки верификации (telegram_user_id не передан), филиал={b['name']}")
    
    # Специальные заметки о входе (для филиалов без стандартного домофона)
    if b.get("intercom_note"):
        details["intercom_note"] = b["intercom_note"]
    
    # Режим работы администратора
    if b.get("has_admin") is False:
        details["admin_info"] = "Филиал работает без администратора"
    elif b.get("admin_hours"):
        hours = b["admin_hours"]
        if "weekdays" in hours and "weekends" in hours:
            details["admin_info"] = f"Администратор: будни {hours['weekdays']}, выходные {hours['weekends']}"
        elif "weekdays" in hours and "weekends_off" in hours:
            details["admin_info"] = f"Администратор: будни {hours['weekdays']}, выходные: {', '.join(hours['weekends_off'])}"
    
    return details


def _find_by_name(branches: List[dict], query: str, telegram_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Ищет филиал по названию, адресу или алиасам."""
    query_lower = query.lower().strip()
    found = []
    
    for b in branches:
        matched = False
        
        # Проверяем название
        if query_lower in b["name"].lower():
            matched = True
        
        # Проверяем адрес
        if not matched and query_lower in b["address"].lower():
            matched = True
        
        # Проверяем display_name
        if not matched and query_lower in b["display_name"].lower():
            matched = True
        
        # Проверяем остановку
        if not matched and b.get("bus_stop") and query_lower in b["bus_stop"].lower():
            matched = True
        
        # Проверяем ориентир
        if not matched and b.get("landmark") and query_lower in b["landmark"].lower():
            matched = True
        
        # Проверяем алиасы
        if not matched:
            for alias in b["aliases"]:
                if query_lower in alias.lower() or alias.lower() in query_lower:
                    matched = True
                    break
        
        if matched:
            found.append(_format_branch_details(b, telegram_user_id))
    
    if not found:
        return {
            "success": False,
            "found": False,
            "message": f"Филиал по запросу '{query}' не найден",
            "suggestion": "Попробуйте указать район или запросите список всех филиалов"
        }
    
    # Если нашли ровно один — возвращаем детально
    if len(found) == 1:
        return {
            "success": True,
            "found": True,
            "exact_match": True,
            "branch": found[0]
        }
    
    # Если несколько — список
    return {
        "success": True,
        "found": True,
        "exact_match": False,
        "count": len(found),
        "branches": [
            {"name": b["name"], "address": b["address"], "district": b["district"]}
            for b in found
        ],
        "message": f"Найдено {len(found)} филиала по запросу '{query}'"
    }


def get_branch_by_id(branch_id: str) -> Optional[Dict[str, Any]]:
    """Получает филиал по ID (для внутреннего использования)."""
    data = load_branches_data()
    for b in data["branches"]:
        if b["id"] == branch_id:
            return b
    return None


def get_all_districts() -> List[str]:
    """Возвращает список всех районов."""
    data = load_branches_data()
    districts = set()
    for b in data["branches"]:
        districts.add(b["district"])
    return sorted(list(districts))


# --- Определение функции для OpenAI Tools ---

# Параметры функции (общие для обоих форматов)
BRANCHES_FUNCTION_PARAMETERS = {
    "type": "object",
    "properties": {
        "query_type": {
            "type": "string",
            "enum": ["all", "by_district", "by_city", "by_name"],
            "description": (
                "Тип запроса: "
                "all — все филиалы, "
                "by_district — по району, "
                "by_city — по городу, "
                "by_name — по названию/адресу"
            )
        },
        "district": {
            "type": "string",
            "description": (
                "Название района (Северо-Запад, Центр, ЧТЗ, ЧМЗ, "
                "Ленинский, Парковый, Чурилово, Копейск). "
                "Используй если query_type = by_district"
            )
        },
        "city": {
            "type": "string",
            "description": (
                "Город (Челябинск или Копейск). "
                "Используй если query_type = by_city"
            )
        },
        "search_query": {
            "type": "string",
            "description": (
                "Поисковый запрос по названию или адресу "
                "(например 'кашириных', 'чтз', 'комарова'). "
                "Используй если query_type = by_name"
            )
        },
        "telegram_user_id": {
            "type": "integer",
            "description": (
                "ID пользователя в Telegram (получи из контекста диалога). "
                "ОБЯЗАТЕЛЬНО передавай этот параметр, если клиент спрашивает код домофона! "
                "Это нужно для проверки верификации перед выдачей кода."
            )
        }
    },
    "required": ["query_type"]
}

BRANCHES_FUNCTION_NAME = "get_branches"
BRANCHES_FUNCTION_DESCRIPTION = (
    "Получить информацию о филиалах школы Planet English. "
    "Используй когда клиент спрашивает о расположении офисов, адресах, "
    "филиалах в конкретном районе или городе, а также КОГДА КЛИЕНТ СПРАШИВАЕТ КОД ДОМОФОНА. "
    "⚠️ ВАЖНО: Если клиент спрашивает код домофона - ОБЯЗАТЕЛЬНО передай telegram_user_id для проверки верификации!"
)

# Формат для Chat Completions API
BRANCHES_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": BRANCHES_FUNCTION_NAME,
        "description": BRANCHES_FUNCTION_DESCRIPTION,
        "parameters": BRANCHES_FUNCTION_PARAMETERS
    }
}

# Формат для Responses API (используется напрямую)
def get_branches_tool_for_responses_api():
    """Возвращает tool в формате для Responses API."""
    return {
        "type": "function",
        "name": BRANCHES_FUNCTION_NAME,
        "description": BRANCHES_FUNCTION_DESCRIPTION,
        "parameters": BRANCHES_FUNCTION_PARAMETERS
    }

