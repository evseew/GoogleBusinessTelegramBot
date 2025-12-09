#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы Function Calling tools.
Запуск: python test_tools.py
"""

import json
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import get_branches, get_tools_for_api


def test_get_all_branches():
    """Тест: получить все филиалы."""
    print("\n" + "="*60)
    print("ТЕСТ: Все филиалы (query_type='all')")
    print("="*60)
    
    result = get_branches(query_type="all")
    print(f"✅ Успех: {result.get('success')}")
    print(f"📍 Челябинск: {result.get('total_chelyabinsk')} филиалов")
    print(f"📍 Копейск: {result.get('total_kopeysk')} филиала")
    print(f"💬 {result.get('summary')}")
    print("\nПо районам:")
    for district, branches in result.get('branches_by_district', {}).items():
        print(f"  {district}:")
        for b in branches:
            print(f"    • {b['name']}: {b['address']}")


def test_find_by_district():
    """Тест: поиск по району."""
    print("\n" + "="*60)
    print("ТЕСТ: Поиск по району 'Центр'")
    print("="*60)
    
    result = get_branches(query_type="by_district", district="центр")
    print(f"✅ Найдено: {result.get('found')}")
    print(f"📍 Район: {result.get('district')}")
    print(f"🔢 Количество: {result.get('count')}")
    if result.get('note'):
        print(f"📝 Примечание: {result.get('note')}")
    for b in result.get('branches', []):
        print(f"  • {b['name']}: {b['address']}")


def test_find_by_district_alias():
    """Тест: поиск по алиасу района."""
    print("\n" + "="*60)
    print("ТЕСТ: Поиск по алиасу 'калининский'")
    print("="*60)
    
    result = get_branches(query_type="by_district", district="калининский")
    print(f"✅ Найдено: {result.get('found')}")
    print(f"📍 Район: {result.get('district')}")
    print(f"🔢 Количество: {result.get('count')}")
    for b in result.get('branches', []):
        print(f"  • {b['name']}: {b['address']}")


def test_find_by_name():
    """Тест: поиск по названию."""
    print("\n" + "="*60)
    print("ТЕСТ: Поиск по названию 'чтз'")
    print("="*60)
    
    result = get_branches(query_type="by_name", search_query="чтз")
    print(f"✅ Найдено: {result.get('found')}")
    print(f"🎯 Точное совпадение: {result.get('exact_match')}")
    if result.get('exact_match'):
        b = result.get('branch', {})
        print(f"  📍 {b.get('name')}: {b.get('address')}")
        print(f"  🏙️ {b.get('district')}, {b.get('city')}")
    else:
        for b in result.get('branches', []):
            print(f"  • {b['name']}: {b['address']}")


def test_find_by_name_multiple():
    """Тест: поиск с несколькими результатами."""
    print("\n" + "="*60)
    print("ТЕСТ: Поиск по названию 'кашириных' (несколько результатов)")
    print("="*60)
    
    result = get_branches(query_type="by_name", search_query="кашириных")
    print(f"✅ Найдено: {result.get('found')}")
    print(f"🎯 Точное совпадение: {result.get('exact_match')}")
    print(f"🔢 Количество: {result.get('count')}")
    for b in result.get('branches', []):
        print(f"  • {b['name']}: {b['address']}")


def test_find_by_city():
    """Тест: поиск по городу."""
    print("\n" + "="*60)
    print("ТЕСТ: Поиск по городу 'Копейск'")
    print("="*60)
    
    result = get_branches(query_type="by_city", city="Копейск")
    print(f"✅ Найдено: {result.get('found')}")
    print(f"🏙️ Город: {result.get('city')}")
    print(f"🔢 Количество: {result.get('count')}")
    for b in result.get('branches', []):
        print(f"  • {b['name']}: {b['address']} ({b['district']})")


def test_not_found():
    """Тест: район не найден."""
    print("\n" + "="*60)
    print("ТЕСТ: Несуществующий район 'Марс'")
    print("="*60)
    
    result = get_branches(query_type="by_district", district="Марс")
    print(f"✅ Найдено: {result.get('found')}")
    print(f"💬 Сообщение: {result.get('message')}")
    print(f"💡 Подсказка: {result.get('suggestion')}")


def test_tools_definition():
    """Тест: проверка определения tools для API."""
    print("\n" + "="*60)
    print("ТЕСТ: Определение tools для OpenAI API")
    print("="*60)
    
    tools = get_tools_for_api()
    print(f"🔧 Количество tools: {len(tools)}")
    for tool in tools:
        func = tool.get('function', {})
        print(f"  • {func.get('name')}: {func.get('description', '')[:50]}...")
        params = func.get('parameters', {}).get('properties', {})
        print(f"    Параметры: {list(params.keys())}")


if __name__ == "__main__":
    print("🧪 ТЕСТИРОВАНИЕ FUNCTION CALLING TOOLS")
    print("="*60)
    
    test_tools_definition()
    test_get_all_branches()
    test_find_by_district()
    test_find_by_district_alias()
    test_find_by_name()
    test_find_by_name_multiple()
    test_find_by_city()
    test_not_found()
    
    print("\n" + "="*60)
    print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
    print("="*60)

