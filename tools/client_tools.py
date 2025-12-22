"""
Инструменты для работы с данными клиентов из 1С
"""

import json
import os
import re
from typing import List, Dict, Optional
from datetime import datetime, timedelta


def load_clients() -> List[Dict]:
    """Загрузка данных клиентов из JSON"""
    clients_path = os.path.join('data', 'clients.json')
    
    if not os.path.exists(clients_path):
        return []
    
    with open(clients_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get('items', [])


def load_contracts() -> List[Dict]:
    """Загрузка данных контрактов из JSON"""
    contracts_path = os.path.join('data', 'contracts.json')
    
    if not os.path.exists(contracts_path):
        return []
    
    with open(contracts_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get('items', [])


def load_transactions() -> List[Dict]:
    """Загрузка данных транзакций из JSON"""
    transactions_path = os.path.join('data', 'transactions.json')
    
    if not os.path.exists(transactions_path):
        return []
    
    with open(transactions_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get('items', [])


def normalize_phone(phone: str) -> str:
    """
    Нормализация телефонного номера к формату +7XXXXXXXXXX
    
    Args:
        phone: Телефон в любом формате
    
    Returns:
        Нормализованный телефон в формате +7XXXXXXXXXX
    
    Examples:
        +79001234567 → +79001234567
        89001234567 → +79001234567
        9001234567 → +79001234567
        +7 900 123 45 67 → +79001234567
        8 (900) 123-45-67 → +79001234567
    """
    # Удаляем все символы кроме цифр и +
    cleaned = re.sub(r'[^\d+]', '', phone)
    
    # Удаляем + в начале (если есть)
    if cleaned.startswith('+'):
        cleaned = cleaned[1:]
    
    # Приводим к формату 7XXXXXXXXXX
    if cleaned.startswith('8') and len(cleaned) == 11:
        # 89001234567 → 79001234567
        cleaned = '7' + cleaned[1:]
    elif cleaned.startswith('9') and len(cleaned) == 10:
        # 9001234567 → 79001234567
        cleaned = '7' + cleaned
    elif not cleaned.startswith('7'):
        # Если не начинается с 7, добавляем 7 (для случаев когда только 10 цифр)
        if len(cleaned) == 10:
            cleaned = '7' + cleaned
    
    # Добавляем +
    return '+' + cleaned


def get_verified_client_data(login: str) -> Optional[Dict]:
    """
    Универсальная функция для получения данных верифицированного клиента.
    Используется для автозаполнения форм (обращения, заявки и т.д.)
    
    Args:
        login: Логин (лицевой счёт) клиента
    
    Returns:
        Словарь с данными клиента или None если не найден
        {
            'login': str,
            'client_name': str,  # ФИО родителя (из contacts)
            'client_phone': str,  # Телефон родителя
            'student_name': str,  # ФИО ребёнка (полное)
            'student_first_name': str,  # Имя ребёнка
            'student_last_name': str,  # Фамилия ребёнка
            'group_number': int,  # Номер группы (если есть)
            'branch_name': str,  # Название филиала
            'teacher': str  # ФИО преподавателя
        }
    """
    clients = load_clients()
    
    if not clients:
        return None
    
    # Ищем клиента по логину
    for client in clients:
        if client.get('login') == login:
            student = client.get('student', {})
            contacts = client.get('contacts', {})
            
            # Формируем полное ФИО ребёнка
            student_name = f"{student.get('last_name', '')} {student.get('first_name', '')} {student.get('middle_name', '')}".strip()
            
            # Формируем ФИО родителя из контактов
            parent_last = contacts.get('last_name', '')
            parent_first = contacts.get('first_name', '')
            parent_middle = contacts.get('middle_name', '')
            client_name = f"{parent_last} {parent_first} {parent_middle}".strip()
            
            # Если имя родителя не указано, берем из student (иногда родитель = ребёнок в базе)
            if not client_name or client_name == '  ':
                client_name = student_name
            
            # Парсим номер группы (может быть строкой вида "Группа 123" или просто "123")
            group_str = student.get('group', '')
            group_number = None
            if group_str:
                # Пытаемся извлечь число из строки
                import re
                match = re.search(r'\d+', str(group_str))
                if match:
                    try:
                        group_number = int(match.group())
                    except ValueError:
                        pass
            
            return {
                'login': client.get('login'),
                'client_name': client_name,
                'client_phone': contacts.get('phone', ''),
                'student_name': student_name,
                'student_first_name': student.get('first_name', ''),
                'student_last_name': student.get('last_name', ''),
                'group_number': group_number,
                'branch_name': student.get('branch', ''),
                'teacher': student.get('teacher', '')
            }
    
    return None


def find_clients_by_phone(phone: str) -> str:
    """
    Поиск клиентов по номеру телефона
    
    Args:
        phone: Номер телефона (в любом формате)
    
    Returns:
        Строка с результатами поиска или информацией о найденных клиентах
    """
    clients = load_clients()
    
    if not clients:
        return "❌ Данные клиентов не загружены. Запустите синхронизацию."
    
    # Нормализуем введённый телефон
    normalized_phone = normalize_phone(phone)
    
    # Ищем клиентов с таким телефоном
    results = []
    for client in clients:
        contacts = client.get('contacts', {})
        client_phone = contacts.get('phone', '')
        
        if client_phone:
            # Нормализуем телефон из базы
            normalized_client_phone = normalize_phone(client_phone)
            
            if normalized_client_phone == normalized_phone:
                results.append(client)
    
    if not results:
        return f"❌ Клиенты с телефоном {normalized_phone} не найдены в базе.\n\n💡 Возможно:\n• Телефон указан с ошибкой\n• Регистрация была на другой номер\n• Данные ещё не синхронизированы из 1С\n\nℹ️ Вы можете указать лицевой счёт (логин) для поиска."
    
    # Форматируем результаты
    if len(results) == 1:
        # Один ребёнок — показываем карточку для верификации
        client = results[0]
        student = client.get('student', {})
        
        output = []
        output.append("✅ Найден ученик по вашему телефону:\n")
        output.append(f"👤 {student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}")
        output.append(f"📱 Логин: {client.get('login')}")
        output.append(f"🏫 Филиал: {student.get('branch')}")
        output.append(f"👥 Группа: {student.get('group')}")
        output.append(f"👨‍🏫 Преподаватель: {student.get('teacher')}")
        
        # Возвращаем в формате для верификации
        return '\n'.join(output) + f"\n\nverify_candidate|{client.get('login')}"
    else:
        # Несколько детей — показываем список (на будущее, но по ТЗ должен быть 1 телефон = 1 ребёнок)
        output = [f"✅ Найдено учеников с телефоном {normalized_phone}: {len(results)}\n"]
        
        for i, client in enumerate(results, 1):
            student = client.get('student', {})
            output.append(f"\n{i}. {student.get('last_name')} {student.get('first_name')}")
            output.append(f"   📱 Логин: {client.get('login')}")
            output.append(f"   🏫 Филиал: {student.get('branch')}")
            output.append(f"   👥 Группа: {student.get('group')}")
        
        # Возвращаем все логины для верификации
        logins = [c.get('login') for c in results]
        return '\n'.join(output) + f"\n\nverify_candidates|{'|'.join(logins)}"


def search_client_by_name(last_name: str, first_name: str = None) -> str:
    """
    Поиск клиента по фамилии и имени
    
    Args:
        last_name: Фамилия для поиска
        first_name: Имя для поиска (опционально)
    
    Returns:
        Строка с результатами поиска
    """
    clients = load_clients()
    
    if not clients:
        return "❌ Данные клиентов не загружены. Запустите синхронизацию."
    
    # Приводим к нижнему регистру для поиска
    last_name_lower = last_name.lower()
    first_name_lower = first_name.lower() if first_name else None
    
    # Ищем совпадения
    results = []
    for client in clients:
        student = client.get('student', {})
        client_last = student.get('last_name', '').lower()
        client_first = student.get('first_name', '').lower()
        
        # Проверяем фамилию
        if last_name_lower in client_last:
            # Если указано имя, проверяем и его
            if first_name_lower:
                if first_name_lower in client_first:
                    results.append(client)
            else:
                results.append(client)
    
    if not results:
        return f"❌ Клиенты с фамилией '{last_name}'{' и именем ' + first_name if first_name else ''} не найдены."
    
    # Форматируем результаты
    output = [f"✅ Найдено клиентов: {len(results)}\n"]
    
    for i, client in enumerate(results[:10], 1):  # Ограничиваем 10 результатами
        student = client.get('student', {})
        contacts = client.get('contacts', {})
        
        output.append(f"\n{i}. {student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}")
        output.append(f"   📱 Логин: {client.get('login')}")
        output.append(f"   🏫 Филиал: {student.get('branch')}")
        output.append(f"   👥 Группа: {student.get('group')}")
        output.append(f"   👨‍🏫 Преподаватель: {student.get('teacher')}")
        output.append(f"   📞 Телефон: {contacts.get('phone')}")
        output.append(f"   📧 Email: {contacts.get('email')}")
        output.append(f"   🎁 Бонусы: {student.get('bonus')}")
    
    if len(results) > 10:
        output.append(f"\n... и еще {len(results) - 10} результатов")
    
    return '\n'.join(output)


def get_client_balance(login: str = None, last_name: str = None) -> str:
    """
    Получить баланс клиента по логину или фамилии
    
    Args:
        login: Логин (лицевой счет) клиента
        last_name: Фамилия клиента
    
    Returns:
        Строка с информацией о балансе
    """
    if not login and not last_name:
        return "❌ Укажите логин или фамилию клиента"
    
    clients = load_clients()
    contracts = load_contracts()
    
    if not clients or not contracts:
        return "❌ Данные не загружены. Запустите синхронизацию."
    
    # Находим клиента
    target_client = None
    
    if login:
        for client in clients:
            if client.get('login') == login:
                target_client = client
                break
    else:
        # Поиск по фамилии
        last_name_lower = last_name.lower()
        matches = [c for c in clients if last_name_lower in c.get('student', {}).get('last_name', '').lower()]
        
        if len(matches) == 0:
            return f"❌ Клиент с фамилией '{last_name}' не найден"
        elif len(matches) > 1:
            names = [f"{c.get('student', {}).get('last_name')} {c.get('student', {}).get('first_name')} (логин: {c.get('login')})" 
                    for c in matches[:5]]
            return f"❓ Найдено несколько клиентов с фамилией '{last_name}':\n" + '\n'.join(names) + "\n\nУкажите логин для точного поиска."
        else:
            target_client = matches[0]
    
    if not target_client:
        return "❌ Клиент не найден"
    
    # Находим контракт клиента
    client_id = target_client.get('id')
    client_contract = None
    
    for contract in contracts:
        if contract.get('client_id') == client_id:
            client_contract = contract
            break
    
    if not client_contract:
        return "❌ Контракт для данного клиента не найден"
    
    # Форматируем вывод
    student = target_client.get('student', {})
    output = []
    output.append(f"💰 Баланс клиента:")
    output.append(f"\n👤 {student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}")
    output.append(f"📱 Логин: {target_client.get('login')}")
    output.append(f"🏫 Филиал: {student.get('branch')}")
    output.append(f"👥 Группа: {student.get('group')}")
    
    balance = int(client_contract.get('balance', 0))
    bonuses = int(client_contract.get('bonuses', 0))
    
    balance_emoji = "✅" if balance >= 0 else "⚠️"
    output.append(f"\n{balance_emoji} Баланс: {balance} руб.")
    output.append(f"🎁 Бонусы: {bonuses}")
    
    return '\n'.join(output)


def get_recent_transactions(login: str = None, last_name: str = None, limit: int = 10, days: int = 31) -> str:
    """
    Получить последние транзакции клиента
    
    Args:
        login: Логин клиента
        last_name: Фамилия клиента
        limit: Количество последних транзакций для показа (по умолчанию 10)
        days: Показать транзакции за последние N дней (по умолчанию 31 день)
    
    Returns:
        Строка с историей транзакций
    """
    if not login and not last_name:
        return "❌ Укажите логин или фамилию клиента"
    
    clients = load_clients()
    contracts = load_contracts()
    transactions = load_transactions()
    
    if not clients or not contracts or not transactions:
        return "❌ Данные не загружены. Запустите синхронизацию."
    
    # Находим клиента
    target_client = None
    
    if login:
        for client in clients:
            if client.get('login') == login:
                target_client = client
                break
    else:
        last_name_lower = last_name.lower()
        matches = [c for c in clients if last_name_lower in c.get('student', {}).get('last_name', '').lower()]
        
        if len(matches) == 1:
            target_client = matches[0]
        elif len(matches) > 1:
            return "❓ Найдено несколько клиентов. Укажите логин для точного поиска."
        else:
            return f"❌ Клиент не найден"
    
    if not target_client:
        return "❌ Клиент не найден"
    
    # Находим контракт
    client_id = target_client.get('id')
    contract_id = None
    
    for contract in contracts:
        if contract.get('client_id') == client_id:
            contract_id = contract.get('id')
            break
    
    if not contract_id:
        return "❌ Контракт не найден"
    
    # Находим транзакции
    client_transactions = [t for t in transactions if t.get('contract_id') == contract_id]
    
    if not client_transactions:
        return "ℹ️ Транзакций не найдено"
    
    # Сортируем по дате (последние сначала)
    client_transactions.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    # Фильтруем по дате (за последние N дней)
    if days:
        cutoff_date = datetime.now() - timedelta(days=days)
        filtered_transactions = []
        
        for trans in client_transactions:
            trans_date_str = trans.get('date', '')
            if trans_date_str:
                try:
                    # Парсим дату в формате ISO (2024-12-22T10:30:00)
                    trans_date = datetime.fromisoformat(trans_date_str.replace('Z', '+00:00'))
                    if trans_date >= cutoff_date:
                        filtered_transactions.append(trans)
                except (ValueError, AttributeError):
                    # Если не удалось распарсить дату, пропускаем транзакцию
                    continue
        
        client_transactions = filtered_transactions
        
        if not client_transactions:
            return f"ℹ️ Транзакций за последние {days} дней не найдено"
    
    # Форматируем вывод
    student = target_client.get('student', {})
    output = []
    output.append(f"📜 История транзакций (за последние {days} дней):")
    output.append(f"\n👤 {student.get('last_name')} {student.get('first_name')}")
    output.append(f"📱 Логин: {target_client.get('login')}")
    output.append(f"💳 Всего транзакций: {len(client_transactions)}\n")
    
    for i, trans in enumerate(client_transactions[:limit], 1):
        amount = int(trans.get('amount', 0))
        description = trans.get('description', 'Операция')
        
        # Убираем минус из суммы для отображения
        abs_amount = abs(amount)
        
        # Определяем эмоджи и понятное описание по типу операции
        if amount > 0:
            # Поступление денег
            if 'платеж' in description.lower() or 'карт' in description.lower():
                emoji = "💳"
                readable_desc = "Оплата картой"
            elif 'бонус' in description.lower() and 'начисл' in description.lower():
                emoji = "🎁"
                readable_desc = "Начислены бонусы"
            elif 'касс' in description.lower():
                emoji = "💵"
                readable_desc = "Оплата в кассе"
            else:
                emoji = "➕"
                readable_desc = "Поступление"
            sign = "+"
        else:
            # Списание
            if 'расходная накладная' in description.lower() or 'занятие' in description.lower() or 'занятия' in description.lower():
                emoji = "📚"
                readable_desc = "Списание за занятие"
            elif 'бонус' in description.lower():
                emoji = "🎁"
                readable_desc = "Списание бонусов"
            elif 'абонемент' in description.lower():
                emoji = "📋"
                readable_desc = "Списание за абонемент"
            else:
                emoji = "➖"
                # Оставляем оригинальное описание для неизвестных операций
                readable_desc = description
            sign = "−"
        
        # Форматируем дату (dd.mm без года для компактности)
        date_str = trans.get('date', '')[:10]
        try:
            date_parts = date_str.split('-')
            if len(date_parts) == 3:
                date_formatted = f"{date_parts[2]}.{date_parts[1]}"
            else:
                date_formatted = date_str
        except:
            date_formatted = date_str
        
        output.append(f"\n{i}️⃣ {date_formatted} | {emoji} {readable_desc} {sign}{abs_amount} ₽")
    
    if len(client_transactions) > limit:
        output.append(f"\n⏬ ... и еще {len(client_transactions) - limit} транзакций")
    
    return '\n'.join(output)


# === Константы для функций ===
SEARCH_CLIENT_FUNCTION_NAME = "search_client_by_name"
FIND_BY_PHONE_FUNCTION_NAME = "find_clients_by_phone"
GET_BALANCE_FUNCTION_NAME = "get_client_balance"
GET_TRANSACTIONS_FUNCTION_NAME = "get_recent_transactions"


# Для интеграции с ботом
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_clients_by_phone",
            "description": (
                "Найти ученика по номеру телефона родителя (указанному при регистрации в 1С). "
                "Используй когда клиент спрашивает о балансе/транзакциях БЕЗ указания логина: "
                "'какой баланс?', 'сколько денег?', 'проверьте счёт', 'мой баланс' (без указания лицевого счёта). "
                "После вызова функция вернёт данные ученика для верификации. "
                "ВАЖНО: Сначала ВСЕГДА проверяй верификацию через check_verification! "
                "Если клиент УЖЕ верифицирован — НЕ спрашивай телефон, сразу показывай данные."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Номер телефона в любом формате: +79001234567, 89001234567, 9001234567"
                    }
                },
                "required": ["phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_client_by_name",
            "description": (
                "Найти ученика по фамилии или имени в базе данных 1С для получения общей информации "
                "(ФИО, филиал, группа, преподаватель, контакты). "
                "Используй когда клиент спрашивает: 'найдите ученика', 'покажите данные по фамилии', "
                "'есть ли у вас ученик', 'информация об ученике', 'ребёнок учится у вас?'. "
                "НЕ используй для запросов БАЛАНСА или ТРАНЗАКЦИЙ — для этого есть специальные функции get_client_balance и get_recent_transactions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "last_name": {
                        "type": "string",
                        "description": "Фамилия ученика для поиска (обязательно)"
                    },
                    "first_name": {
                        "type": "string",
                        "description": "Имя ученика для уточнения поиска (опционально, используй если клиент назвал имя)"
                    }
                },
                "required": ["last_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_client_balance",
            "description": (
                "Получить текущий баланс и бонусы ученика по логину (лицевой счёт) или фамилии. "
                "Используй когда клиент спрашивает о ФИНАНСАХ: 'какой баланс?', 'сколько на счету?', "
                "'мой лицевой счёт 46168', 'мой логин 12345', 'проверьте баланс', 'покажите бонусы', "
                "'сколько денег осталось?', 'задолженность'. "
                "ВАЖНО: Функция возвращает данные ученика + баланс. Перед показом баланса клиенту ОБЯЗАТЕЛЬНА верификация личности!"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "login": {
                        "type": "string",
                        "description": "Логин (лицевой счёт) ученика — число вида '46168', '12345'. Используй если клиент назвал логин."
                    },
                    "last_name": {
                        "type": "string",
                        "description": "Фамилия ученика — используй только если логин НЕ известен. Если найдено несколько учеников, функция вернёт список."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_transactions",
            "description": (
                "Получить историю последних платежей и списаний ученика (дата, сумма, описание операции). "
                "Используй когда клиент спрашивает об ИСТОРИИ ОПЕРАЦИЙ: 'покажите транзакции', "
                "'история платежей', 'когда был последний платёж?', 'что списано?', 'движения по счёту', "
                "'почему минус на балансе?', 'за что списали?', 'когда я платил?'. "
                "По умолчанию показывает транзакции за последние 31 день. "
                "Если клиент просит за другой период — используй параметр 'days': 'за неделю' → days=7, 'за месяц' → days=30, 'за 3 месяца' → days=90. "
                "Если клиент просит больше/меньше транзакций — используй параметр 'limit': 'покажи 20 транзакций' → limit=20. "
                "ВАЖНО: Перед показом транзакций клиенту ОБЯЗАТЕЛЬНА верификация личности!"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "login": {
                        "type": "string",
                        "description": "Логин (лицевой счёт) ученика. Используй если клиент назвал логин или он был получен ранее."
                    },
                    "last_name": {
                        "type": "string",
                        "description": "Фамилия ученика — используй только если логин НЕ известен."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Количество транзакций для показа (по умолчанию 10). Используй если клиент просит конкретное количество: 'покажи 20 транзакций' → limit=20",
                        "default": 10
                    },
                    "days": {
                        "type": "integer",
                        "description": "Период в днях для показа транзакций (по умолчанию 31 день). Используй когда клиент указывает период: 'за неделю' → days=7, 'за месяц' → days=30, 'за 3 месяца' → days=90, 'за полгода' → days=180",
                        "default": 31
                    }
                },
                "required": []
            }
        }
    }
]


# === Функции для Responses API ===

def get_find_by_phone_tool_for_responses_api():
    """Возвращает инструмент find_clients_by_phone в формате Responses API."""
    return {
        "type": "function",
        "name": FIND_BY_PHONE_FUNCTION_NAME,
        "description": TOOLS[0]["function"]["description"],
        "parameters": TOOLS[0]["function"]["parameters"]
    }


def get_search_client_tool_for_responses_api():
    """Возвращает инструмент search_client_by_name в формате Responses API."""
    return {
        "type": "function",
        "name": SEARCH_CLIENT_FUNCTION_NAME,
        "description": TOOLS[1]["function"]["description"],
        "parameters": TOOLS[1]["function"]["parameters"]
    }


def get_client_balance_tool_for_responses_api():
    """Возвращает инструмент get_client_balance в формате Responses API."""
    return {
        "type": "function",
        "name": GET_BALANCE_FUNCTION_NAME,
        "description": TOOLS[2]["function"]["description"],
        "parameters": TOOLS[2]["function"]["parameters"]
    }


def get_recent_transactions_tool_for_responses_api():
    """Возвращает инструмент get_recent_transactions в формате Responses API."""
    return {
        "type": "function",
        "name": GET_TRANSACTIONS_FUNCTION_NAME,
        "description": TOOLS[3]["function"]["description"],
        "parameters": TOOLS[3]["function"]["parameters"]
    }
