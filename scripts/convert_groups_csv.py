#!/usr/bin/env python3
"""
Скрипт для конвертации CSV файла с группами в JSON.

Использование:
    python scripts/convert_groups_csv.py /path/to/groups.csv

Скрипт автоматически:
1. Парсит CSV файл с группами
2. Нормализует данные (классы, дни, время)
3. Определяет категорию и тип группы
4. Сохраняет в data/groups.json

Автор: Planet English Bot System
"""

import csv
import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple


# Путь к выходному JSON файлу
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_FILE = os.path.join(PROJECT_DIR, "data", "groups.json")


# === МАППИНГИ И КОНСТАНТЫ ===

# Маппинг дней недели
DAYS_MAPPING = {
    "пн": "пн",
    "вт": "вт",
    "ср": "ср",
    "чт": "чт",
    "пт": "пт",
    "сб": "сб",
    "вс": "вс",
    "вт.": "вт",
    "вскр": "вс",
}

# Маппинг категорий
CATEGORY_MAPPING = {
    "A (лучший выбор!)": "A",
    "В (можно звать)": "B",
    "С (когда нет вариантов)": "C",
    "Х (закрыт набор!)": "X",
}

# Типы групп для продвинутых
ADVANCED_GROUP_TYPES = ["Старая для умных"]

# Маппинг коротких названий филиалов
BRANCH_SHORT_NAMES = {
    "ЧМЗ": "ЧМЗ",
    "Парковый": "Парковый",
    "Северо-Запад": "Северо-Запад",
    "Академ": "Академ",
    "Тополинка": "Тополинка",
    "Ленинский": "Ленинский",
    "Центр": "Центр",
    "ЧТЗ": "ЧТЗ",
    "Чурилово": "Чурилово",
    "Копейск": "Копейск",
    "Online": "Online",
}


def parse_branch_short(branch_full: str) -> str:
    """Извлекает короткое название филиала."""
    if branch_full.lower().startswith("online"):
        return "Online"
    
    for short_name in BRANCH_SHORT_NAMES:
        if short_name.lower() in branch_full.lower():
            return short_name
    
    # Если не нашли, берём первую часть до двоеточия
    if ":" in branch_full:
        return branch_full.split(":")[0].strip()
    return branch_full


def parse_days(days_str: str) -> List[str]:
    """Парсит строку с днями недели в список."""
    if not days_str or days_str.strip() == "":
        return []
    
    days_str = days_str.strip().lower()
    
    # Убираем точки в конце
    days_str = days_str.rstrip(".")
    
    # Разделители: /, пробел
    parts = re.split(r'[/\s]+', days_str)
    
    result = []
    for part in parts:
        part = part.strip().rstrip(".")
        if part in DAYS_MAPPING:
            result.append(DAYS_MAPPING[part])
        elif part:
            # Пробуем найти частичное совпадение
            for key, value in DAYS_MAPPING.items():
                if key in part or part in key:
                    result.append(value)
                    break
    
    return result


def parse_grades(grades_str: str) -> Tuple[List[str], Optional[int], Optional[int]]:
    """
    Парсит строку с классами в список и min/max.
    
    Returns:
        (список классов, min_grade, max_grade)
    """
    if not grades_str or grades_str.strip() == "":
        return [], None, None
    
    grades_str = grades_str.strip()
    
    # Для дошкольников (4-5 лет, 5-6 лет)
    age_match = re.search(r'(\d+)[-–]?(\d*)\s*лет', grades_str)
    if age_match:
        age_from = int(age_match.group(1))
        age_to = int(age_match.group(2)) if age_match.group(2) else age_from
        return [grades_str], age_from - 7, age_to - 7  # Примерно: возраст - 7 = класс
    
    # Для взрослых
    if "18+" in grades_str:
        return ["18+"], 18, 99
    
    # Стандартный парсинг классов
    # Ищем все числа с "кл" или без
    grade_pattern = re.findall(r'(\d+)\s*(?:кл|класс)?', grades_str.lower())
    
    if not grade_pattern:
        return [grades_str], None, None
    
    grades_int = [int(g) for g in grade_pattern]
    
    # Формируем список строк вида "5кл"
    grades_list = [f"{g}кл" for g in sorted(set(grades_int))]
    
    return grades_list, min(grades_int), max(grades_int)


def parse_time(time_str: str) -> str:
    """Нормализует время в формат HH:MM."""
    if not time_str:
        return ""
    
    time_str = time_str.strip()
    
    # Заменяем точку на двоеточие (9.00 -> 9:00)
    time_str = time_str.replace(".", ":")
    
    # Убираем пробелы
    time_str = time_str.replace(" ", "")
    
    # Проверяем формат
    match = re.match(r'^(\d{1,2}):?(\d{2})$', time_str)
    if match:
        hours = int(match.group(1))
        minutes = match.group(2)
        return f"{hours:02d}:{minutes}"
    
    return time_str


def parse_date(date_str: str) -> str:
    """Парсит дату в формат YYYY-MM-DD."""
    if not date_str:
        return ""
    
    date_str = date_str.strip()
    
    # Формат DD.MM.YYYY
    match = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', date_str)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month}-{day}"
    
    return date_str


def calculate_duration(time_start: str, time_end: str) -> int:
    """Вычисляет продолжительность в минутах."""
    try:
        start_parts = time_start.split(":")
        end_parts = time_end.split(":")
        
        start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
        end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
        
        return end_minutes - start_minutes
    except (ValueError, IndexError):
        return 0


def generate_group_id(row: Dict[str, str], index: int) -> str:
    """Генерирует уникальный ID группы."""
    branch_short = parse_branch_short(row.get("Филиал", ""))
    program = row.get("Программа", "").replace(" ", "-").replace("(", "").replace(")", "")
    group_num = row.get("№ группы ", "").strip()
    
    if branch_short == "Online":
        return f"Online-{group_num}"
    
    return f"{branch_short}-{program}-{group_num}"


def parse_category(category_str: str) -> str:
    """Парсит категорию группы."""
    if not category_str:
        return "C"
    
    category_str = category_str.strip()
    
    for pattern, code in CATEGORY_MAPPING.items():
        if pattern in category_str:
            return code
    
    # Пробуем найти по первой букве
    first_char = category_str[0].upper() if category_str else "C"
    if first_char in ["A", "B", "C", "X"]:
        return first_char
    
    return "C"


def is_for_advanced_only(group_type: str) -> bool:
    """Определяет, только для продвинутых ли группа."""
    if not group_type:
        return False
    return group_type.strip() in ADVANCED_GROUP_TYPES


def parse_current_students(value: str) -> int:
    """Парсит количество учеников."""
    if not value:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0


def convert_row_to_group(row: Dict[str, str], index: int) -> Optional[Dict[str, Any]]:
    """Конвертирует строку CSV в объект группы."""
    
    # Пропускаем пустые строки
    branch = row.get("Филиал", "").strip()
    if not branch:
        return None
    
    # Парсим данные
    branch_short = parse_branch_short(branch)
    is_online = branch_short == "Online"
    
    days = parse_days(row.get("Дни недели", ""))
    grades_list, grade_min, grade_max = parse_grades(row.get("Классы", ""))
    
    time_start = parse_time(row.get("Время начала", ""))
    time_end = parse_time(row.get("Время окон.", ""))
    
    category = parse_category(row.get("Категория", ""))
    group_type = row.get("Старая для умных", "").strip()
    
    # Генерируем ID
    group_id = generate_group_id(row, index)
    
    # Собираем объект
    group = {
        "id": group_id,
        "branch": branch,
        "branch_short": branch_short,
        "is_online": is_online,
        "course": row.get("Курс", "").strip(),
        "program": row.get("Программа", "").strip(),
        "grades": grades_list,
        "grade_min": grade_min,
        "grade_max": grade_max,
        "days": days,
        "time_start": time_start,
        "time_end": time_end,
        "duration_minutes": calculate_duration(time_start, time_end),
        "group_number": row.get("№ группы ", "").strip(),
        "start_date": parse_date(row.get("Дата старта", "")),
        "category": category,
        "group_type": group_type,
        "for_advanced_only": is_for_advanced_only(group_type),
        "current_students": parse_current_students(row.get("УЧАТСЯ", "")),
        "room_theme": row.get("Кабинет", "").strip() or None,
        "teacher_initials": row.get("Информация о преподавателе (ФИО, регалии и пр)", "").strip() or None,
        "price_note": row.get("Стоимость обучения", "").strip() or None,
    }
    
    return group


def convert_csv_to_json(csv_path: str) -> Dict[str, Any]:
    """
    Конвертирует CSV файл в структуру JSON.
    
    Returns:
        Словарь с группами и метаданными
    """
    groups = []
    errors = []
    
    # Определяем кодировку
    encodings = ['utf-8', 'cp1251', 'latin-1']
    content = None
    used_encoding = None
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding) as f:
                content = f.read()
                used_encoding = encoding
                break
        except UnicodeDecodeError:
            continue
    
    if content is None:
        raise ValueError(f"Не удалось прочитать файл с кодировками: {encodings}")
    
    print(f"✓ Файл прочитан с кодировкой: {used_encoding}")
    
    # Парсим CSV
    reader = csv.DictReader(content.splitlines())
    
    for index, row in enumerate(reader, start=1):
        try:
            group = convert_row_to_group(row, index)
            if group:
                groups.append(group)
        except Exception as e:
            errors.append(f"Строка {index}: {e}")
    
    # Собираем статистику
    stats = {
        "total_groups": len(groups),
        "online_groups": sum(1 for g in groups if g["is_online"]),
        "offline_groups": sum(1 for g in groups if not g["is_online"]),
        "by_category": {
            "A": sum(1 for g in groups if g["category"] == "A"),
            "B": sum(1 for g in groups if g["category"] == "B"),
            "C": sum(1 for g in groups if g["category"] == "C"),
            "X": sum(1 for g in groups if g["category"] == "X"),
        },
        "by_course": {},
        "by_branch": {},
    }
    
    # Группировка по курсам
    for g in groups:
        course = g["course"]
        if course not in stats["by_course"]:
            stats["by_course"][course] = 0
        stats["by_course"][course] += 1
    
    # Группировка по филиалам
    for g in groups:
        branch = g["branch_short"]
        if branch not in stats["by_branch"]:
            stats["by_branch"][branch] = 0
        stats["by_branch"][branch] += 1
    
    result = {
        "meta": {
            "version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "source_file": os.path.basename(csv_path),
            "encoding_used": used_encoding,
        },
        "stats": stats,
        "groups": groups,
    }
    
    if errors:
        result["meta"]["conversion_errors"] = errors
        print(f"\n⚠️  Ошибки при конвертации ({len(errors)}):")
        for err in errors[:10]:
            print(f"   - {err}")
        if len(errors) > 10:
            print(f"   ... и ещё {len(errors) - 10} ошибок")
    
    return result


def print_stats(data: Dict[str, Any]) -> None:
    """Выводит статистику конвертации."""
    stats = data["stats"]
    
    print("\n" + "=" * 50)
    print("📊 СТАТИСТИКА КОНВЕРТАЦИИ")
    print("=" * 50)
    
    print(f"\n📌 Всего групп: {stats['total_groups']}")
    print(f"   • Офлайн: {stats['offline_groups']}")
    print(f"   • Онлайн: {stats['online_groups']}")
    
    print(f"\n🏷️  По категориям:")
    print(f"   • A (лучший выбор): {stats['by_category']['A']}")
    print(f"   • B (можно звать): {stats['by_category']['B']}")
    print(f"   • C (когда нет вариантов): {stats['by_category']['C']}")
    print(f"   • X (закрыт набор): {stats['by_category']['X']}")
    
    print(f"\n📚 По курсам:")
    for course, count in sorted(stats["by_course"].items(), key=lambda x: -x[1]):
        print(f"   • {course}: {count}")
    
    print(f"\n🏢 По филиалам:")
    for branch, count in sorted(stats["by_branch"].items(), key=lambda x: -x[1]):
        print(f"   • {branch}: {count}")
    
    print("=" * 50)


def main():
    """Основная функция."""
    if len(sys.argv) < 2:
        print("❌ Укажите путь к CSV файлу")
        print(f"   Использование: python {sys.argv[0]} /path/to/groups.csv")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    
    if not os.path.exists(csv_path):
        print(f"❌ Файл не найден: {csv_path}")
        sys.exit(1)
    
    print(f"📂 Конвертация файла: {csv_path}")
    print(f"📝 Выходной файл: {OUTPUT_FILE}")
    
    # Конвертируем
    data = convert_csv_to_json(csv_path)
    
    # Создаём директорию если нужно
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Сохраняем JSON
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ JSON файл сохранён: {OUTPUT_FILE}")
    
    # Выводим статистику
    print_stats(data)
    
    # Проверяем доступные группы (не X)
    available = sum(1 for g in data["groups"] if g["category"] != "X")
    print(f"\n🎯 Доступно для записи: {available} групп")


if __name__ == "__main__":
    main()

