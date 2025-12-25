"""
Инструменты для работы с ценами Planet English.
Используются для OpenAI Function Calling.
"""

import json
import os
from typing import Optional, Dict, Any, List

# Путь к файлам данных
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PRICES_FILE = os.path.join(DATA_DIR, "prices.json")
BRANCHES_FILE = os.path.join(DATA_DIR, "branches.json")

# Кэш данных
_prices_cache: Optional[dict] = None
_branches_cache: Optional[dict] = None


def load_prices_data() -> dict:
    """Загружает данные о ценах из JSON-файла."""
    global _prices_cache
    if _prices_cache is None:
        with open(PRICES_FILE, "r", encoding="utf-8") as f:
            _prices_cache = json.load(f)
    return _prices_cache


def load_branches_data() -> dict:
    """Загружает данные о филиалах для определения price_tier."""
    global _branches_cache
    if _branches_cache is None:
        with open(BRANCHES_FILE, "r", encoding="utf-8") as f:
            _branches_cache = json.load(f)
    return _branches_cache


def reload_prices_data() -> dict:
    """Принудительно перезагружает данные о ценах."""
    global _prices_cache
    _prices_cache = None
    return load_prices_data()


def get_branch_price_tier(branch_id: Optional[str] = None, 
                          branch_name: Optional[str] = None) -> Optional[str]:
    """
    Определяет ценовую категорию филиала.
    
    Returns:
        "standard" или "reduced", None если филиал не найден
    """
    if not branch_id and not branch_name:
        return None
    
    branches_data = load_branches_data()
    
    for branch in branches_data.get("branches", []):
        # Поиск по ID
        if branch_id and branch.get("id") == branch_id:
            return branch.get("price_tier", "standard")
        
        # Поиск по имени или алиасам
        if branch_name:
            name_lower = branch_name.lower()
            if (name_lower in branch.get("name", "").lower() or
                name_lower in branch.get("display_name", "").lower() or
                any(name_lower in alias.lower() for alias in branch.get("aliases", []))):
                return branch.get("price_tier", "standard")
    
    return None


def get_prices(
    query_type: str,
    course: Optional[str] = None,
    price_tier: Optional[str] = None,
    schedule_type: Optional[str] = None,
    branch_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Универсальная функция получения информации о ценах.
    
    Args:
        query_type: Тип запроса
            - "general" — общий диапазон цен (когда клиент просто спрашивает "сколько стоит")
            - "by_course" — цены для конкретного курса
            - "exact" — точная цена (когда известны курс + филиал/ценовая категория)
        course: Название курса (pe_kids, pe_start, pe_five, pe_future, oge_ege, pe_world, pe_online, chinese, stem_math)
        price_tier: Ценовая категория ("standard" или "reduced")
        schedule_type: Тип расписания ("weekdays" или "weekends") - только для PE Start и китайского
        branch_name: Название филиала для автоматического определения price_tier
    
    Returns:
        Словарь с информацией о ценах
    """
    data = load_prices_data()
    
    # Если указан филиал, но не указан price_tier — определяем автоматически
    if branch_name and not price_tier:
        price_tier = get_branch_price_tier(branch_name=branch_name)
    
    if query_type == "general":
        return _get_general_prices(data)
    
    elif query_type == "by_course":
        if not course:
            return {"error": "Не указан курс для получения цены", "success": False}
        return _get_course_prices(data, course, price_tier, schedule_type)
    
    elif query_type == "exact":
        if not course:
            return {"error": "Не указан курс для получения точной цены", "success": False}
        if not price_tier:
            return {
                "error": "Для точной цены нужно указать филиал или ценовую категорию",
                "success": False,
                "hint": "Уточните у клиента, в каком филиале он планирует заниматься"
            }
        return _get_exact_price(data, course, price_tier, schedule_type)
    
    elif query_type == "list_courses":
        return _list_available_courses(data)
    
    return {"error": f"Неизвестный тип запроса: {query_type}", "success": False}


def _get_general_prices(data: dict) -> Dict[str, Any]:
    """Возвращает общий диапазон цен для ориентировки."""
    ranges = data.get("price_ranges", {})
    
    return {
        "success": True,
        "type": "general_range",
        "price_per_academic_hour": {
            "min": ranges.get("general", {}).get("min_per_academic_hour", 350),
            "max": ranges.get("general", {}).get("max_per_academic_hour", 420),
            "unit": "рублей за академический час"
        },
        "price_per_month": {
            "min": ranges.get("per_month", {}).get("min", 4800),
            "max": ranges.get("per_month", {}).get("max", 6720),
            "unit": "рублей в месяц"
        },
        "message": (
            "Стоимость зависит от курса, филиала и формата занятий. "
            "Академический час стоит от 350 до 420 рублей. "
            "В месяц выходит от 4800 до 6720 рублей."
        ),
        "clarification_needed": [
            "Возраст ребёнка (или взрослый студент)",
            "Удобный филиал",
            "Предпочтения по расписанию (будни/выходные)"
        ],
        "benefits": [
            "Налоговый вычет 13%",
            "Семейная скидка 20% на второго ребёнка"
        ]
    }


def _get_course_prices(
    data: dict, 
    course: str, 
    price_tier: Optional[str],
    schedule_type: Optional[str]
) -> Dict[str, Any]:
    """Возвращает цены для конкретного курса."""
    courses = data.get("courses", {})
    course_key = _normalize_course_name(course)
    
    if course_key not in courses:
        return {
            "success": False,
            "error": f"Курс '{course}' не найден",
            "available_courses": list(courses.keys())
        }
    
    course_data = courses[course_key]
    pricing = course_data.get("pricing", {})
    
    result = {
        "success": True,
        "course": course_data.get("name"),
        "display_name": course_data.get("display_name"),
        "description": course_data.get("description"),
        "target_audience": course_data.get("target_audience"),
        "has_schedule_options": course_data.get("has_schedule_options", False),
        "benefits": _format_benefits(course_data.get("benefits", []), data)
    }
    
    # Курсы с единой ценой (PE Kids, PE Online)
    if "unified" in pricing:
        unified = pricing["unified"]
        result["pricing_type"] = "unified"
        
        # Если unified содержит weekdays/weekends — показываем варианты расписания
        if "weekdays" in unified or "weekends" in unified:
            if schedule_type and schedule_type in unified:
                # Конкретное расписание указано
                result["schedule_type"] = schedule_type
                result["price"] = _format_price_details(unified[schedule_type])
                result["price"]["note"] = unified[schedule_type].get("note", "Единая цена для всех филиалов")
            else:
                # Показываем оба варианта
                result["schedule_options"] = {}
                for sched in ["weekdays", "weekends"]:
                    if sched in unified:
                        result["schedule_options"][sched] = _format_price_details(unified[sched])
                        result["schedule_options"][sched]["note"] = unified[sched].get("note", "Единая цена для всех филиалов")
                result["clarification_needed"] = "Уточните предпочтения по расписанию (будни или выходные)"
        else:
            # Плоская структура unified (как PE Online)
            result["price"] = _format_price_details(unified)
            result["price"]["note"] = unified.get("note", "Единая цена для всех филиалов")
        return result
    
    # Индивидуальные занятия и мини-группы — особая структура
    if course_key in ["individual", "mini_groups"]:
        result["pricing_type"] = "individual_or_mini"
        result["offer_condition"] = course_data.get("offer_condition")
        
        if course_key == "individual":
            result["use_cases"] = course_data.get("use_cases", [])
            result["recommended_response"] = course_data.get("recommended_response")
        else:
            result["features"] = course_data.get("features", [])
        
        # Форматируем цены по тарифам и типам преподавателей
        result["prices_by_tier"] = {}
        for tier in ["standard", "reduced"]:
            if tier in pricing:
                tier_data = pricing[tier]
                tier_result = {
                    "description": (
                        "Основные районы Челябинска" if tier == "standard"
                        else "Отдалённые районы (Копейск, Чурилово, ЧМЗ)"
                    ),
                    "russian_teacher": {},
                    "foreign_teacher": {}
                }
                
                # Русскоязычный преподаватель
                if "russian_teacher" in tier_data:
                    for key, val in tier_data["russian_teacher"].items():
                        if isinstance(val, dict):
                            tier_result["russian_teacher"][key] = {
                                "price_per_academic_hour": val.get("price_per_academic_hour"),
                                "description": val.get("description")
                            }
                
                # Иностранный преподаватель
                if "foreign_teacher" in tier_data:
                    for key, val in tier_data["foreign_teacher"].items():
                        if isinstance(val, dict):
                            tier_result["foreign_teacher"][key] = {
                                "price_per_academic_hour": val.get("price_per_academic_hour"),
                                "description": val.get("description")
                            }
                
                result["prices_by_tier"][tier] = tier_result
        
        if price_tier and price_tier in result["prices_by_tier"]:
            result["price_tier"] = price_tier
            result["selected_tier_prices"] = result["prices_by_tier"][price_tier]
        
        return result
    
    # PE World — оплата за академический час
    if course_data.get("pricing_type") == "per_academic_hour":
        result["pricing_type"] = "per_academic_hour"
        if price_tier and price_tier in pricing:
            tier_data = pricing[price_tier]
            result["price_tier"] = price_tier
            result["price"] = {
                "price_per_academic_hour": tier_data.get("price_per_academic_hour"),
                "format": tier_data.get("format"),
                "examples": tier_data.get("examples"),
                "note": tier_data.get("note")
            }
        else:
            # Показываем оба варианта
            result["prices_by_tier"] = {}
            for tier in ["standard", "reduced"]:
                if tier in pricing:
                    tier_data = pricing[tier]
                    result["prices_by_tier"][tier] = {
                        "price_per_academic_hour": tier_data.get("price_per_academic_hour"),
                        "examples": tier_data.get("examples")
                    }
            result["clarification_needed"] = "Укажите филиал для точной цены"
        return result
    
    # Курсы с ценовыми категориями (standard/reduced)
    result["pricing_type"] = "tiered"
    
    if price_tier and price_tier in pricing:
        # Известна ценовая категория
        tier_pricing = pricing[price_tier]
        result["price_tier"] = price_tier
        result["price_tier_description"] = (
            "Основные районы Челябинска" if price_tier == "standard" 
            else "Отдалённые районы (Копейск, Чурилово, ЧМЗ)"
        )
        
        # Если есть выбор расписания
        if course_data.get("has_schedule_options"):
            if schedule_type and schedule_type in tier_pricing:
                # Точное расписание указано
                sched_data = tier_pricing[schedule_type]
                result["schedule_type"] = schedule_type
                result["price"] = _format_price_details(sched_data)
            else:
                # Показываем оба варианта расписания
                result["schedule_options"] = {}
                for sched in ["weekdays", "weekends"]:
                    if sched in tier_pricing:
                        result["schedule_options"][sched] = _format_price_details(tier_pricing[sched])
                result["clarification_needed"] = "Уточните предпочтения по расписанию (будни или выходные)"
        else:
            # Только один вариант расписания
            if "weekdays" in tier_pricing:
                result["price"] = _format_price_details(tier_pricing["weekdays"])
    else:
        # Ценовая категория неизвестна — показываем диапазон
        result["prices_by_tier"] = {}
        for tier in ["standard", "reduced"]:
            if tier in pricing:
                tier_pricing = pricing[tier]
                tier_result = {
                    "description": (
                        "Основные районы" if tier == "standard" 
                        else "Отдалённые районы"
                    )
                }
                
                if course_data.get("has_schedule_options"):
                    tier_result["schedule_options"] = {}
                    for sched in ["weekdays", "weekends"]:
                        if sched in tier_pricing:
                            tier_result["schedule_options"][sched] = _format_price_details(tier_pricing[sched])
                else:
                    if "weekdays" in tier_pricing:
                        tier_result["price"] = _format_price_details(tier_pricing["weekdays"])
                
                result["prices_by_tier"][tier] = tier_result
        
        result["clarification_needed"] = "Укажите филиал для точной цены"
    
    return result


def _get_exact_price(
    data: dict,
    course: str,
    price_tier: str,
    schedule_type: Optional[str]
) -> Dict[str, Any]:
    """Возвращает точную цену для конкретной комбинации параметров."""
    courses = data.get("courses", {})
    course_key = _normalize_course_name(course)
    
    if course_key not in courses:
        return {
            "success": False,
            "error": f"Курс '{course}' не найден"
        }
    
    course_data = courses[course_key]
    pricing = course_data.get("pricing", {})
    
    result = {
        "success": True,
        "course": course_data.get("name"),
        "display_name": course_data.get("display_name"),
        "price_tier": price_tier,
        "price_tier_description": (
            "Основные районы Челябинска" if price_tier == "standard"
            else "Отдалённые районы (Копейск, Чурилово, ЧМЗ)"
        ),
        "benefits": _format_benefits(course_data.get("benefits", []), data)
    }
    
    # Единая цена
    if "unified" in pricing:
        unified = pricing["unified"]
        result["price"] = _format_price_details(unified)
        result["note"] = "Единая цена для всех филиалов"
        return result
    
    # PE World
    if course_data.get("pricing_type") == "per_academic_hour":
        if price_tier not in pricing:
            return {"success": False, "error": f"Ценовая категория '{price_tier}' не найдена для курса"}
        
        tier_data = pricing[price_tier]
        result["pricing_type"] = "per_academic_hour"
        result["price"] = {
            "price_per_academic_hour": tier_data.get("price_per_academic_hour"),
            "format": tier_data.get("format"),
            "examples": tier_data.get("examples"),
            "note": tier_data.get("note")
        }
        return result
    
    # Курсы с тарифами
    if price_tier not in pricing:
        return {"success": False, "error": f"Ценовая категория '{price_tier}' не найдена для курса"}
    
    tier_pricing = pricing[price_tier]
    
    # Курс с выбором расписания
    if course_data.get("has_schedule_options"):
        if not schedule_type:
            # Нужно уточнить расписание
            result["schedule_options"] = {}
            for sched in ["weekdays", "weekends"]:
                if sched in tier_pricing:
                    result["schedule_options"][sched] = _format_price_details(tier_pricing[sched])
            result["clarification_needed"] = "Уточните: будни или выходные?"
            return result
        
        if schedule_type not in tier_pricing:
            return {"success": False, "error": f"Расписание '{schedule_type}' не найдено для курса"}
        
        result["schedule_type"] = schedule_type
        result["schedule_description"] = "Будни" if schedule_type == "weekdays" else "Выходные"
        result["price"] = _format_price_details(tier_pricing[schedule_type])
    else:
        # Единственный вариант расписания
        if "weekdays" in tier_pricing:
            result["price"] = _format_price_details(tier_pricing["weekdays"])
    
    return result


def _list_available_courses(data: dict) -> Dict[str, Any]:
    """Возвращает список всех доступных курсов."""
    courses = data.get("courses", {})
    
    result = {
        "success": True,
        "courses": []
    }
    
    for key, course in courses.items():
        result["courses"].append({
            "id": key,
            "name": course.get("name"),
            "display_name": course.get("display_name"),
            "description": course.get("description"),
            "age_range": course.get("age_range"),
            "target_audience": course.get("target_audience")
        })
    
    return result


def _normalize_course_name(course: str) -> str:
    """Нормализует название курса к ключу в JSON."""
    course_lower = course.lower().strip()
    
    mapping = {
        "pe kids": "pe_kids",
        "pe_kids": "pe_kids",
        "пе кидс": "pe_kids",
        "дошкольники": "pe_kids",
        
        "pe start": "pe_start",
        "pe_start": "pe_start",
        "пе старт": "pe_start",
        
        "pe five": "pe_five",
        "pe_five": "pe_five",
        "пе файв": "pe_five",
        
        "pe future": "pe_future",
        "pe_future": "pe_future",
        "пе фьючер": "pe_future",
        
        "огэ": "oge_ege",
        "егэ": "oge_ege",
        "oge": "oge_ege",
        "ege": "oge_ege",
        "oge_ege": "oge_ege",
        "огэ/егэ": "oge_ege",
        "огэ егэ": "oge_ege",
        "экзамены": "oge_ege",
        
        "pe world": "pe_world",
        "pe_world": "pe_world",
        "пе ворлд": "pe_world",
        "взрослые": "pe_world",
        
        "pe online": "pe_online",
        "pe_online": "pe_online",
        "онлайн": "pe_online",
        
        "chinese": "chinese",
        "китайский": "chinese",
        "китайский язык": "chinese",
        
        "individual": "individual",
        "индивидуальные": "individual",
        "индивидуальные занятия": "individual",
        "индивидуально": "individual",
        "персональные": "individual",
        
        "mini_groups": "mini_groups",
        "мини-группы": "mini_groups",
        "мини группы": "mini_groups",
        "минигруппы": "mini_groups",
        "мини-группа": "mini_groups",
    }
    
    return mapping.get(course_lower, course_lower)


def _format_price_details(price_data: dict) -> Dict[str, Any]:
    """Форматирует детали цены."""
    result = {
        "format": price_data.get("format"),
        "lessons_per_week": price_data.get("lessons_per_week"),
        "duration_minutes": price_data.get("duration_minutes"),
        "duration_academic_hours": price_data.get("duration_academic_hours"),
        "price_per_lesson": price_data.get("price_per_lesson"),
        "price_per_academic_hour": price_data.get("price_per_academic_hour"),
        "price_per_month": price_data.get("price_per_month"),
        "lessons_per_month": price_data.get("lessons_per_month"),
        "recommended_price_unit": price_data.get("recommended_price_unit", "per_academic_hour")
    }
    
    # Добавляем подсказку для бота какую цену называть клиенту
    unit = result["recommended_price_unit"]
    if unit == "per_academic_hour" and result.get("price_per_academic_hour"):
        result["display_price"] = f"{result['price_per_academic_hour']} ₽ за академический час"
        result["display_hint"] = "Называй клиенту стоимость за АКАДЕМИЧЕСКИЙ ЧАС"
    elif unit == "per_lesson" and result.get("price_per_lesson"):
        result["display_price"] = f"{result['price_per_lesson']} ₽ за занятие"
        result["display_hint"] = "Называй клиенту стоимость за ЗАНЯТИЕ"
    
    return result


def _format_benefits(benefit_keys: List[str], data: dict) -> List[Dict[str, Any]]:
    """Форматирует информацию о бонусах."""
    benefits_info = data.get("benefits_info", {})
    result = []
    
    for key in benefit_keys:
        if key in benefits_info:
            info = benefits_info[key]
            result.append({
                "name": info.get("name"),
                "value": info.get("value"),
                "description": info.get("description")
            })
    
    return result


# --- Определение функции для OpenAI Tools ---

PRICES_FUNCTION_NAME = "get_prices"
PRICES_FUNCTION_DESCRIPTION = (
    "Получить информацию о стоимости обучения в Planet English. "
    "Используй когда клиент спрашивает о ценах, стоимости курсов, "
    "сколько стоит обучение, какие расценки."
)

PRICES_FUNCTION_PARAMETERS = {
    "type": "object",
    "properties": {
        "query_type": {
            "type": "string",
            "enum": ["general", "by_course", "exact", "list_courses"],
            "description": (
                "Тип запроса: "
                "general — общий диапазон цен (клиент просто спрашивает 'сколько стоит'), "
                "by_course — цены для конкретного курса, "
                "exact — точная цена (известны курс и филиал), "
                "list_courses — список всех курсов"
            )
        },
        "course": {
            "type": "string",
            "enum": [
                "pe_kids", "pe_start", "pe_five", "pe_future", 
                "oge_ege", "pe_world", "pe_online", "chinese",
                "stem_math", "individual", "mini_groups"
            ],
            "description": (
                "Название курса: "
                "pe_kids — дошкольники 3-5 лет, "
                "pe_start — 6-9 лет (до 2 класса включительно), "
                "pe_five — школьники с проблемами, "
                "pe_future — школьники без проблем (для развития), "
                "oge_ege — подготовка к экзаменам 9-11 класс, "
                "pe_world — взрослые от 18 лет, "
                "pe_online — онлайн-формат, "
                "chinese — китайский язык, "
                "stem_math — школа креативной математики (1-4 классы), "
                "individual — индивидуальные занятия (ТОЛЬКО по запросу клиента!), "
                "mini_groups — мини-группы 2-4 человека (ТОЛЬКО по запросу клиента!)"
            )
        },
        "price_tier": {
            "type": "string",
            "enum": ["standard", "reduced"],
            "description": (
                "Ценовая категория: "
                "standard — основные районы Челябинска, "
                "reduced — отдалённые районы (Копейск, Чурилово, ЧМЗ)"
            )
        },
        "schedule_type": {
            "type": "string",
            "enum": ["weekdays", "weekends"],
            "description": (
                "Тип расписания (только для PE Start и китайского): "
                "weekdays — будни (2 раза в неделю), "
                "weekends — выходные (1 раз в неделю)"
            )
        },
        "branch_name": {
            "type": "string",
            "description": (
                "Название или адрес филиала для автоматического определения ценовой категории "
                "(например 'Чичерина', 'Копейск', 'ЧМЗ')"
            )
        }
    },
    "required": ["query_type"]
}

# Формат для Chat Completions API
PRICES_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": PRICES_FUNCTION_NAME,
        "description": PRICES_FUNCTION_DESCRIPTION,
        "parameters": PRICES_FUNCTION_PARAMETERS
    }
}


def get_prices_tool_for_responses_api() -> Dict[str, Any]:
    """Возвращает tool в формате для Responses API."""
    return {
        "type": "function",
        "name": PRICES_FUNCTION_NAME,
        "description": PRICES_FUNCTION_DESCRIPTION,
        "parameters": PRICES_FUNCTION_PARAMETERS
    }

