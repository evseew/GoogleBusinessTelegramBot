"""
Инструменты для подбора групп Planet English.
Используются для OpenAI Function Calling.
"""

import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

# Путь к файлу данных
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")

# Кэш данных (загружается один раз)
_groups_cache: Optional[dict] = None


def load_groups_data() -> dict:
    """Загружает данные о группах из JSON-файла."""
    global _groups_cache
    if _groups_cache is None:
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            _groups_cache = json.load(f)
    return _groups_cache


def reload_groups_data() -> dict:
    """Принудительно перезагружает данные (если файл обновился)."""
    global _groups_cache
    _groups_cache = None
    return load_groups_data()


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def _normalize_branch_name(branch: str) -> str:
    """Нормализует название филиала для поиска."""
    if not branch:
        return ""
    
    branch_lower = branch.lower().strip()
    
    # Маппинг алиасов
    aliases = {
        "северо-запад": ["чичерина", "с-з", "сз", "северо запад", "кашириных"],
        "центр": ["свердловский", "коммуны"],
        "парковый": ["краснопольский"],
        "академ": ["кашириных"],
        "тополинка": ["макеева"],
        "ленинский": ["дзержинского"],
        "чмз": ["хмельницкого", "б.хмельницкого"],
        "чтз": ["комарова"],
        "чурилово": ["зальцмана"],
        "копейск": ["коммунистический", "славы"],
    }
    
    for standard_name, alias_list in aliases.items():
        if standard_name in branch_lower:
            return standard_name
        for alias in alias_list:
            if alias in branch_lower:
                return standard_name
    
    return branch_lower


def _time_to_minutes(time_str: str) -> int:
    """Конвертирует время HH:MM в минуты от полуночи."""
    try:
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return 0


def _get_time_period(time_str: str) -> str:
    """Определяет период дня по времени начала."""
    minutes = _time_to_minutes(time_str)
    
    if minutes < 12 * 60:  # до 12:00
        return "утро"
    elif minutes < 17 * 60:  # 12:00 - 17:00
        return "день"
    else:  # после 17:00
        return "вечер"


def _normalize_days(days: List[str]) -> List[str]:
    """Нормализует список дней."""
    day_mapping = {
        "понедельник": "пн",
        "вторник": "вт",
        "среда": "ср",
        "четверг": "чт",
        "пятница": "пт",
        "суббота": "сб",
        "воскресенье": "вс",
    }
    
    result = []
    for day in days:
        day_lower = day.lower().strip()
        if day_lower in day_mapping:
            result.append(day_mapping[day_lower])
        elif day_lower in day_mapping.values():
            result.append(day_lower)
    
    return result


def _is_weekday(days: List[str]) -> bool:
    """Проверяет, являются ли дни буднями."""
    weekdays = {"пн", "вт", "ср", "чт", "пт"}
    return any(d in weekdays for d in days)


def _is_weekend(days: List[str]) -> bool:
    """Проверяет, являются ли дни выходными."""
    weekends = {"сб", "вс"}
    return any(d in weekends for d in days)


def _format_days(days: List[str]) -> str:
    """Форматирует дни для отображения."""
    day_names = {
        "пн": "понедельник",
        "вт": "вторник",
        "ср": "среда",
        "чт": "четверг",
        "пт": "пятница",
        "сб": "суббота",
        "вс": "воскресенье",
    }
    
    if len(days) == 1:
        return day_names.get(days[0], days[0])
    elif len(days) == 2:
        return f"{days[0]}/{days[1]}"
    else:
        return "/".join(days)


def _format_schedule(group: dict) -> str:
    """Форматирует расписание группы."""
    days_str = _format_days(group.get("days", []))
    time_start = group.get("time_start", "")
    time_end = group.get("time_end", "")
    
    if days_str and time_start and time_end:
        return f"{days_str} {time_start}-{time_end}"
    elif days_str and time_start:
        return f"{days_str} {time_start}"
    elif days_str:
        return days_str
    
    return "расписание уточняется"


def _parse_start_date(date_str: str) -> Optional[datetime]:
    """Парсит дату старта группы."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


# === ОСНОВНАЯ ФУНКЦИЯ ПОИСКА ===

def search_groups(
    program: str,
    branch: Optional[str] = None,
    is_advanced: bool = False,
    has_problems: bool = False,
    preferred_days: Optional[List[str]] = None,
    preferred_time: Optional[str] = None,
    mid_year_join: bool = False
) -> Dict[str, Any]:
    """
    Поиск подходящих групп для клиента.
    
    Args:
        program: Программа обучения (Sol2, Pr3, ОГЭ, PE5 и т.д.)
        branch: Предпочтительный филиал (None = любой)
        is_advanced: Ребёнок с хорошим уровнем (можно в "Старая для умных")
        has_problems: Есть проблемы с английским
        preferred_days: Предпочтительные дни ["пн", "ср"] или ["выходные"]
        preferred_time: Предпочтительное время ("утро", "день", "вечер")
        mid_year_join: Присоединяется в середине учебного года
    
    Returns:
        Словарь с подобранными группами
    """
    data = load_groups_data()
    all_groups = data["groups"]
    
    # Нормализуем входные данные
    program_lower = program.lower().strip() if program else ""
    branch_normalized = _normalize_branch_name(branch) if branch else None
    
    if preferred_days:
        # Обработка "выходные" / "будни"
        if any("выход" in d.lower() for d in preferred_days):
            preferred_days = ["сб", "вс"]
        elif any("будн" in d.lower() for d in preferred_days):
            preferred_days = ["пн", "вт", "ср", "чт", "пт"]
        else:
            preferred_days = _normalize_days(preferred_days)
    
    # === ШАГ 1: Фильтрация по программе ===
    filtered = []
    for g in all_groups:
        g_program = (g.get("program") or "").lower()
        g_course = (g.get("course") or "").lower()
        
        # Сопоставление программы
        if program_lower in g_program or program_lower in g_course:
            filtered.append(g)
        # Также проверяем частичное совпадение
        elif program_lower.replace(" ", "") in g_program.replace(" ", ""):
            filtered.append(g)
    
    if not filtered:
        return {
            "success": False,
            "message": f"Группы по программе '{program}' не найдены",
            "suggestion": "Уточните программу или курс обучения"
        }
    
    # === ШАГ 2: Исключаем закрытые группы (категория X) ===
    filtered = [g for g in filtered if g.get("category") != "X"]
    
    # === ШАГ 3: Фильтр по типу группы (уровень ребёнка) ===
    if not is_advanced:
        # Исключаем "Старая для умных" для начинающих
        filtered = [g for g in filtered if not g.get("for_advanced_only", False)]
    
    # === ШАГ 4: Разделяем на ОФЛАЙН и ONLINE ===
    offline_groups = []
    online_groups = []
    
    for g in filtered:
        if g.get("is_online"):
            online_groups.append(g)
        else:
            offline_groups.append(g)
    
    # === ШАГ 5: Фильтр офлайн по филиалу ===
    if branch_normalized:
        offline_filtered = []
        for g in offline_groups:
            g_branch = _normalize_branch_name(g.get("branch_short", ""))
            if branch_normalized in g_branch or g_branch in branch_normalized:
                offline_filtered.append(g)
        offline_groups = offline_filtered
    
    # === ШАГ 6: Фильтр офлайн по дням/времени ===
    if preferred_days:
        days_matched = []
        for g in offline_groups:
            g_days = g.get("days", [])
            # Хотя бы один день совпадает
            if any(d in g_days for d in preferred_days):
                days_matched.append(g)
        if days_matched:  # Если есть совпадения, используем их
            offline_groups = days_matched
    
    if preferred_time:
        time_matched = []
        for g in offline_groups:
            g_time_period = _get_time_period(g.get("time_start", ""))
            if preferred_time.lower() == g_time_period:
                time_matched.append(g)
        if time_matched:  # Если есть совпадения, используем их
            offline_groups = time_matched
    
    # === ШАГ 7: Сортировка ===
    def sort_key(g):
        # Приоритет категории: A=0, B=1, C=2
        category_priority = {"A": 0, "B": 1, "C": 2}.get(g.get("category", "C"), 2)
        
        # Для mid_year_join + has_problems: приоритет поздней дате старта
        start_date = _parse_start_date(g.get("start_date", ""))
        date_score = 0
        if mid_year_join and has_problems and start_date:
            # Чем позже дата, тем лучше (инвертируем)
            date_score = -start_date.timestamp()
        
        # Количество учеников (меньше = лучше)
        students = g.get("current_students", 0)
        
        return (category_priority, date_score, students)
    
    offline_groups.sort(key=sort_key)
    online_groups.sort(key=sort_key)
    
    # === ШАГ 8: Выбираем до 3 офлайн и 1-2 онлайн ===
    selected_offline = offline_groups[:3]
    selected_online = online_groups[:2]
    
    # === ШАГ 9: Форматируем результат ===
    def format_group(g, include_online_note=False):
        result = {
            "group_id": g.get("id"),
            "branch": g.get("branch") if not g.get("is_online") else "Online",
            "branch_short": g.get("branch_short"),
            "program": g.get("program"),
            "course": g.get("course"),
            "schedule": _format_schedule(g),
            "grades": ", ".join(g.get("grades", [])),
            "start_date": g.get("start_date"),
        }
        
        # Примечание о цене если есть
        if g.get("price_note"):
            result["price_note"] = g["price_note"]
        
        # Для онлайн добавляем примечание
        if include_online_note and g.get("is_online"):
            result["online_advantage"] = (
                "🌐 Онлайн — удобная альтернатива! "
                "Не нужно возить ребёнка, занятия из дома."
            )
        
        return result
    
    offline_formatted = [format_group(g) for g in selected_offline]
    online_formatted = [format_group(g, include_online_note=True) for g in selected_online]
    
    # === ШАГ 10: Формируем ответ ===
    result = {
        "success": True,
        "program": program,
        "branch_filter": branch or "любой",
        "offline_groups": offline_formatted,
        "online_groups": online_formatted,
        "total_offline_found": len(offline_groups),
        "total_online_found": len(online_groups),
    }
    
    # Добавляем примечание для присоединения в середине года
    if mid_year_join:
        result["mid_year_note"] = (
            "💡 Присоединиться к группе в середине года — это нормально и даже хорошо! "
            "Многие родители так делают. Группы, которые стартовали позже, "
            "прошли меньше материала — догнать будет легче."
        )
    
    # Формируем сообщение
    messages = []
    if offline_formatted:
        messages.append(f"Найдено {len(offline_groups)} офлайн групп" + 
                       (f" в филиале {branch}" if branch else ""))
    if online_formatted:
        messages.append(f"Также доступно {len(online_groups)} онлайн групп")
    
    if not offline_formatted and not online_formatted:
        result["success"] = False
        result["message"] = "К сожалению, подходящих групп не найдено"
        result["suggestion"] = "Попробуйте изменить филиал или дни занятий"
    else:
        result["message"] = ". ".join(messages)
    
    return result


def get_group_details(group_id: str) -> Dict[str, Any]:
    """
    Получает детальную информацию о конкретной группе.
    
    Args:
        group_id: ID группы
    
    Returns:
        Словарь с деталями группы
    """
    data = load_groups_data()
    
    for g in data["groups"]:
        if g.get("id") == group_id:
            return {
                "success": True,
                "group": {
                    "id": g["id"],
                    "branch": g.get("branch"),
                    "branch_short": g.get("branch_short"),
                    "is_online": g.get("is_online"),
                    "course": g.get("course"),
                    "program": g.get("program"),
                    "grades": g.get("grades"),
                    "schedule": _format_schedule(g),
                    "days": g.get("days"),
                    "time_start": g.get("time_start"),
                    "time_end": g.get("time_end"),
                    "duration_minutes": g.get("duration_minutes"),
                    "start_date": g.get("start_date"),
                    "category": g.get("category"),
                    "group_type": g.get("group_type"),
                    "room_theme": g.get("room_theme"),
                    "price_note": g.get("price_note"),
                }
            }
    
    return {
        "success": False,
        "message": f"Группа с ID '{group_id}' не найдена"
    }


def get_available_programs() -> Dict[str, Any]:
    """
    Возвращает список всех доступных программ.
    """
    data = load_groups_data()
    
    programs = {}
    for g in data["groups"]:
        if g.get("category") == "X":
            continue
        
        program = g.get("program", "")
        course = g.get("course", "")
        
        key = f"{course} / {program}" if course else program
        if key not in programs:
            programs[key] = {
                "program": program,
                "course": course,
                "count": 0,
                "grades": set(),
            }
        
        programs[key]["count"] += 1
        for grade in g.get("grades", []):
            programs[key]["grades"].add(grade)
    
    # Конвертируем set в list
    for key in programs:
        programs[key]["grades"] = sorted(list(programs[key]["grades"]))
    
    return {
        "success": True,
        "programs": list(programs.values())
    }


# === ОПРЕДЕЛЕНИЕ ФУНКЦИИ ДЛЯ OPENAI TOOLS ===

GROUPS_FUNCTION_PARAMETERS = {
    "type": "object",
    "properties": {
        "program": {
            "type": "string",
            "description": (
                "Программа обучения. Примеры: "
                "Sol2, Sol3, Sol4, Pr1, Pr2, Pr3, Pr4, "
                "PEStart, PE5, HH1, HH2, NEF0, NEF1, "
                "ОГЭ, ЕГЭ, Китайский. "
                "Обязательный параметр."
            )
        },
        "branch": {
            "type": "string",
            "description": (
                "Предпочтительный филиал. Примеры: "
                "Северо-Запад, Центр, Парковый, ЧТЗ, ЧМЗ, "
                "Ленинский, Академ, Тополинка, Чурилово, Копейск. "
                "Если не указан — поиск по всем филиалам."
            )
        },
        "is_advanced": {
            "type": "boolean",
            "description": (
                "True — ребёнок с хорошим уровнем английского "
                "(учился раньше, языковая школа, нет проблем). "
                "False — начинающий или есть сложности."
            )
        },
        "has_problems": {
            "type": "boolean",
            "description": (
                "True — у ребёнка есть проблемы с английским в школе. "
                "Влияет на рекомендации при присоединении в середине года."
            )
        },
        "preferred_days": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Предпочтительные дни занятий. "
                "Примеры: ['пн', 'ср'], ['сб'], ['выходные'], ['будни']. "
                "Если не указаны — любые дни."
            )
        },
        "preferred_time": {
            "type": "string",
            "enum": ["утро", "день", "вечер"],
            "description": (
                "Предпочтительное время: "
                "утро (до 12:00), день (12:00-17:00), вечер (после 17:00)."
            )
        },
        "mid_year_join": {
            "type": "boolean",
            "description": (
                "True — клиент присоединяется в середине учебного года "
                "(декабрь-февраль). Влияет на подбор групп и рекомендации."
            )
        }
    },
    "required": ["program"]
}

GROUPS_FUNCTION_NAME = "search_groups"
GROUPS_FUNCTION_DESCRIPTION = (
    "Подбор подходящих групп для клиента по программе, филиалу, уровню и расписанию. "
    "Используй после определения программы обучения и сбора пожеланий клиента. "
    "Возвращает до 3 офлайн групп + онлайн альтернативы."
)

# Формат для Chat Completions API
GROUPS_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": GROUPS_FUNCTION_NAME,
        "description": GROUPS_FUNCTION_DESCRIPTION,
        "parameters": GROUPS_FUNCTION_PARAMETERS
    }
}


def get_groups_tool_for_responses_api():
    """Возвращает tool в формате для Responses API."""
    return {
        "type": "function",
        "name": GROUPS_FUNCTION_NAME,
        "description": GROUPS_FUNCTION_DESCRIPTION,
        "parameters": GROUPS_FUNCTION_PARAMETERS
    }

