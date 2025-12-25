"""
Инструменты для работы с данными клиентов из 1С
"""

import json
import os
import re
from typing import List, Dict, Optional, Any
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
            
            # Извлекаем ФИО родителя из поля contact_person
            # Формат: "Фамилия Имя Отчество" → извлекаем "Имя Отчество" для обращения
            contact_person = contacts.get('contact_person', '').strip()
            
            if contact_person:
                # Разделяем на части
                name_parts = contact_person.split()
                
                if len(name_parts) >= 3:
                    # Стандартный формат "Фамилия Имя Отчество" → берём "Имя Отчество"
                    client_name = f"{name_parts[1]} {name_parts[2]}"
                elif len(name_parts) == 2:
                    # "Имя Отчество" (без фамилии)
                    client_name = f"{name_parts[0]} {name_parts[1]}"
                else:
                    # Одно слово (например, "Ольга")
                    client_name = name_parts[0]
            else:
                # Fallback: если контактное лицо не указано, берём ФИО ребёнка
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


def find_clients_by_phone(phone: str) -> Dict[str, Any]:
    """
    Поиск клиентов по номеру телефона
    
    Args:
        phone: Номер телефона (в любом формате)
    
    Returns:
        Словарь с результатами поиска в стандартном формате:
        {
            "success": bool,
            "data": {
                "found": bool,
                "login": str,  # Логин найденного ученика (ВАЖНО: используй этот логин для save_verification!)
                "student_name": str,
                "branch": str,
                "group": str,
                "teacher": str,
                "requires_verification": bool,
                "multiple_children": bool,  # Если найдено несколько детей
                "children": List[Dict]  # Список детей если их несколько
            },
            "formatted_message": str
        }
    """
    clients = load_clients()
    
    if not clients:
        return {
            "success": False,
            "data": {"found": False},
            "formatted_message": "❌ Данные клиентов не загружены. Запустите синхронизацию.",
            "error": "no_data"
        }
    
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
        return {
            "success": False,
            "data": {"found": False, "phone": normalized_phone},
            "formatted_message": (
                f"❌ Клиенты с телефоном {normalized_phone} не найдены в базе.\n\n"
                "💡 Возможно:\n"
                "• Телефон указан с ошибкой\n"
                "• Регистрация была на другой номер\n"
                "• Данные ещё не синхронизированы из 1С\n\n"
                "ℹ️ Вы можете указать лицевой счёт (логин) для поиска."
            ),
            "error": "not_found"
        }
    
    # Форматируем результаты
    if len(results) == 1:
        # Один ребёнок — возвращаем структурированные данные
        client = results[0]
        student = client.get('student', {})
        login = client.get('login')
        
        # Формируем человекочитаемое сообщение
        # ВАЖНО: Показываем логин явно, чтобы LLM его видел в истории диалога
        message_parts = [
            "✅ Нашла вашего ребёнка:\n",
            f"👤 *{student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}*",
            f"📱 *Логин: {login}*",  # ← Показываем логин явно
            f"🏫 *Филиал:* {student.get('branch')}",
            f"👥 *Группа:* {student.get('group')}",
            f"👩‍🏫 *Преподаватель:* {student.get('teacher')}",
            "",
            "Это данные вашего ребёнка? Подтвердите, пожалуйста, чтобы я показала сумму к оплате 💰"
        ]
        
        return {
            "success": True,
            "data": {
                "found": True,
                "login": login,  # ← ВАЖНО: Этот логин должен использоваться для save_verification!
                "student_name": f"{student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}".strip(),
                "first_name": student.get('first_name'),
                "last_name": student.get('last_name'),
                "branch": student.get('branch'),
                "group": student.get('group'),
                "teacher": student.get('teacher'),
                "requires_verification": True,
                "multiple_children": False
            },
            "formatted_message": '\n'.join(message_parts)
        }
    else:
        # Несколько детей — возвращаем список
        children_list = []
        for client in results:
            student = client.get('student', {})
            children_list.append({
                "login": client.get('login'),
                "student_name": f"{student.get('last_name')} {student.get('first_name')}".strip(),
                "branch": student.get('branch'),
                "group": student.get('group')
            })
        
        # Формируем сообщение
        message_parts = [f"✅ Найдено учеников с телефоном {normalized_phone}: {len(results)}\n"]
        for i, child in enumerate(children_list, 1):
            message_parts.append(f"\n{i}. {child['student_name']}")
            message_parts.append(f"   📱 Логин: {child['login']}")
            message_parts.append(f"   🏫 Филиал: {child['branch']}")
            message_parts.append(f"   👥 Группа: {child['group']}")
        
        return {
            "success": True,
            "data": {
                "found": True,
                "multiple_children": True,
                "children": children_list,
                "requires_verification": True
            },
            "formatted_message": '\n'.join(message_parts)
        }


def search_client_by_name(last_name: str, first_name: str = None) -> Dict[str, Any]:
    """
    Поиск клиента по фамилии и имени
    
    Args:
        last_name: Фамилия для поиска
        first_name: Имя для поиска (опционально)
    
    Returns:
        Словарь с результатами поиска в стандартном формате:
        {
            "success": bool,
            "data": {
                "clients": List[Dict],
                "total_found": int,
                "query": str
            },
            "formatted_message": str
        }
    """
    clients = load_clients()
    
    if not clients:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Данные клиентов не загружены. Запустите синхронизацию.",
            "error": "no_data"
        }
    
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
        query_str = f"фамилией '{last_name}'" + (f" и именем '{first_name}'" if first_name else "")
        return {
            "success": False,
            "data": {
                "clients": [],
                "total_found": 0,
                "query": {"last_name": last_name, "first_name": first_name}
            },
            "formatted_message": f"❌ Клиенты с {query_str} не найдены.",
            "error": "not_found"
        }
    
    # Форматируем структурированные данные
    clients_data = []
    for client in results[:10]:  # Ограничиваем 10 результатами
        student = client.get('student', {})
        contacts = client.get('contacts', {})
        
        clients_data.append({
            "login": client.get('login'),
            "full_name": f"{student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}".strip(),
            "first_name": student.get('first_name'),
            "last_name": student.get('last_name'),
            "middle_name": student.get('middle_name'),
            "branch": student.get('branch'),
            "group": student.get('group'),
            "teacher": student.get('teacher'),
            "phone": contacts.get('phone'),
            "email": contacts.get('email'),
            "bonus": student.get('bonus')
        })
    
    # Форматируем текстовое сообщение
    output = [f"✅ Найдено клиентов: {len(results)}\n"]
    
    for i, client_info in enumerate(clients_data, 1):
        output.append(f"\n{i}. {client_info['full_name']}")
        output.append(f"   📱 Логин: {client_info['login']}")
        output.append(f"   🏫 Филиал: {client_info['branch']}")
        output.append(f"   👥 Группа: {client_info['group']}")
        output.append(f"   👨‍🏫 Преподаватель: {client_info['teacher']}")
        output.append(f"   📞 Телефон: {client_info['phone']}")
        output.append(f"   📧 Email: {client_info['email']}")
        output.append(f"   🎁 Бонусы: {client_info['bonus']}")
    
    if len(results) > 10:
        output.append(f"\n... и еще {len(results) - 10} результатов")
    
    return {
        "success": True,
        "data": {
            "clients": clients_data,
            "total_found": len(results),
            "showing": len(clients_data),
            "query": {"last_name": last_name, "first_name": first_name}
        },
        "formatted_message": '\n'.join(output)
    }


def get_client_balance(login: str = None, last_name: str = None) -> Dict[str, Any]:
    """
    Получить баланс клиента по логину или фамилии
    
    Args:
        login: Логин (лицевой счет) клиента
        last_name: Фамилия клиента
    
    Returns:
        Словарь с информацией о балансе в стандартном формате:
        {
            "success": bool,
            "data": {
                "login": str,
                "student_name": str,
                "balance": int,
                "bonuses": int,
                "branch": str,
                "group": str
            },
            "formatted_message": str
        }
    """
    if not login and not last_name:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Укажите логин или фамилию клиента",
            "error": "missing_parameters"
        }
    
    clients = load_clients()
    contracts = load_contracts()
    
    if not clients or not contracts:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Данные не загружены. Запустите синхронизацию.",
            "error": "no_data"
        }
    
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
            return {
                "success": False,
                "data": {},
                "formatted_message": f"❌ Клиент с фамилией '{last_name}' не найден",
                "error": "not_found"
            }
        elif len(matches) > 1:
            # Несколько клиентов — нужно уточнение
            matches_data = []
            for c in matches[:5]:
                student = c.get('student', {})
                matches_data.append({
                    "login": c.get('login'),
                    "full_name": f"{student.get('last_name')} {student.get('first_name')}"
                })
            
            names = [f"{m['full_name']} (логин: {m['login']})" for m in matches_data]
            
            return {
                "success": False,
                "data": {
                    "multiple_matches": matches_data,
                    "query": last_name
                },
                "formatted_message": f"❓ Найдено несколько клиентов с фамилией '{last_name}':\n" + '\n'.join(names) + "\n\nУкажите логин для точного поиска.",
                "error": "multiple_matches"
            }
        else:
            target_client = matches[0]
    
    if not target_client:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Клиент не найден",
            "error": "not_found"
        }
    
    # Находим контракт клиента
    client_id = target_client.get('id')
    client_contract = None
    
    for contract in contracts:
        if contract.get('client_id') == client_id:
            client_contract = contract
            break
    
    if not client_contract:
        return {
            "success": False,
            "data": {
                "login": target_client.get('login'),
                "student_name": f"{target_client.get('student', {}).get('last_name')} {target_client.get('student', {}).get('first_name')}"
            },
            "formatted_message": "❌ Контракт для данного клиента не найден",
            "error": "no_contract"
        }
    
    # Форматируем структурированные данные
    student = target_client.get('student', {})
    balance = int(client_contract.get('balance', 0))
    bonuses = int(client_contract.get('bonuses', 0))
    
    data = {
        "login": target_client.get('login'),
        "student_name": f"{student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}".strip(),
        "first_name": student.get('first_name'),
        "balance": balance,
        "bonuses": bonuses,
        "branch": student.get('branch'),
        "group": student.get('group'),
        "is_positive": balance >= 0
    }
    
    # Форматируем текстовое сообщение
    output = []
    output.append(f"💰 Баланс клиента:")
    output.append(f"\n👤 {data['student_name']}")
    output.append(f"📱 Логин: {data['login']}")
    output.append(f"🏫 Филиал: {data['branch']}")
    output.append(f"👥 Группа: {data['group']}")
    
    balance_emoji = "✅" if balance >= 0 else "⚠️"
    output.append(f"\n{balance_emoji} Баланс: {balance} руб.")
    output.append(f"🎁 Бонусы: {bonuses}")
    
    return {
        "success": True,
        "data": data,
        "formatted_message": '\n'.join(output)
    }


def get_recent_transactions(login: str = None, last_name: str = None, limit: int = 10, days: int = 31) -> Dict[str, Any]:
    """
    Получить последние транзакции клиента
    
    Args:
        login: Логин клиента
        last_name: Фамилия клиента
        limit: Количество последних транзакций для показа (по умолчанию 10)
        days: Показать транзакции за последние N дней (по умолчанию 31 день)
    
    Returns:
        Словарь с историей транзакций в стандартном формате:
        {
            "success": bool,
            "data": {
                "login": str,
                "student_name": str,
                "transactions": List[Dict],
                "total_count": int,
                "showing_count": int,
                "period_days": int
            },
            "formatted_message": str
        }
    """
    if not login and not last_name:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Укажите логин или фамилию клиента",
            "error": "missing_parameters"
        }
    
    clients = load_clients()
    contracts = load_contracts()
    transactions = load_transactions()
    
    if not clients or not contracts or not transactions:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Данные не загружены. Запустите синхронизацию.",
            "error": "no_data"
        }
    
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
            return {
                "success": False,
                "data": {},
                "formatted_message": "❓ Найдено несколько клиентов. Укажите логин для точного поиска.",
                "error": "multiple_matches"
            }
        else:
            return {
                "success": False,
                "data": {},
                "formatted_message": "❌ Клиент не найден",
                "error": "not_found"
            }
    
    if not target_client:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Клиент не найден",
            "error": "not_found"
        }
    
    # Находим контракт
    client_id = target_client.get('id')
    contract_id = None
    
    for contract in contracts:
        if contract.get('client_id') == client_id:
            contract_id = contract.get('id')
            break
    
    if not contract_id:
        return {
            "success": False,
            "data": {
                "login": target_client.get('login')
            },
            "formatted_message": "❌ Контракт не найден",
            "error": "no_contract"
        }
    
    # Находим транзакции
    client_transactions = [t for t in transactions if t.get('contract_id') == contract_id]
    
    if not client_transactions:
        return {
            "success": True,
            "data": {
                "login": target_client.get('login'),
                "student_name": f"{target_client.get('student', {}).get('last_name')} {target_client.get('student', {}).get('first_name')}",
                "transactions": [],
                "total_count": 0,
                "showing_count": 0,
                "period_days": days
            },
            "formatted_message": "ℹ️ Транзакций не найдено"
        }
    
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
            return {
                "success": True,
                "data": {
                    "login": target_client.get('login'),
                    "student_name": f"{target_client.get('student', {}).get('last_name')} {target_client.get('student', {}).get('first_name')}",
                    "transactions": [],
                    "total_count": 0,
                    "showing_count": 0,
                    "period_days": days
                },
                "formatted_message": f"ℹ️ Транзакций за последние {days} дней не найдено"
            }
    
    # Форматируем структурированные данные транзакций
    transactions_data = []
    for trans in client_transactions[:limit]:
        amount = int(trans.get('amount', 0))
        description = trans.get('description', 'Операция')
        date_str = trans.get('date', '')
        
        # Определяем тип операции
        if amount > 0:
            if 'платеж' in description.lower() or 'карт' in description.lower():
                trans_type = "card_payment"
                readable_desc = "Оплата картой"
            elif 'бонус' in description.lower() and 'начисл' in description.lower():
                trans_type = "bonus_accrual"
                readable_desc = "Начислены бонусы"
            elif 'касс' in description.lower():
                trans_type = "cash_payment"
                readable_desc = "Оплата в кассе"
            else:
                trans_type = "income"
                readable_desc = "Поступление"
        else:
            if 'расходная накладная' in description.lower() or 'занятие' in description.lower() or 'занятия' in description.lower():
                trans_type = "lesson_charge"
                readable_desc = "Списание за занятие"
            elif 'бонус' in description.lower():
                trans_type = "bonus_usage"
                readable_desc = "Списание бонусов"
            elif 'абонемент' in description.lower():
                trans_type = "subscription_charge"
                readable_desc = "Списание за абонемент"
            else:
                trans_type = "expense"
                readable_desc = description
        
        transactions_data.append({
            "date": date_str,
            "amount": amount,
            "description": description,
            "readable_description": readable_desc,
            "type": trans_type,
            "is_income": amount > 0
        })
    
    # Форматируем текстовое сообщение
    student = target_client.get('student', {})
    output = []
    output.append(f"📜 История транзакций (за последние {days} дней):")
    output.append(f"\n👤 {student.get('last_name')} {student.get('first_name')}")
    output.append(f"📱 Логин: {target_client.get('login')}")
    output.append(f"💳 Всего транзакций: {len(client_transactions)}\n")
    
    for i, trans_data in enumerate(transactions_data, 1):
        amount = trans_data['amount']
        readable_desc = trans_data['readable_description']
        abs_amount = abs(amount)
        sign = "+" if amount > 0 else "−"
        
        # Эмоджи по типу операции
        emoji_map = {
            "card_payment": "💳",
            "bonus_accrual": "🎁",
            "cash_payment": "💵",
            "income": "➕",
            "lesson_charge": "📚",
            "bonus_usage": "🎁",
            "subscription_charge": "📋",
            "expense": "➖"
        }
        emoji = emoji_map.get(trans_data['type'], "💳")
        
        # Форматируем дату (dd.mm без года для компактности)
        date_str = trans_data['date'][:10]
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
    
    return {
        "success": True,
        "data": {
            "login": target_client.get('login'),
            "student_name": f"{student.get('last_name')} {student.get('first_name')}",
            "transactions": transactions_data,
            "total_count": len(client_transactions),
            "showing_count": len(transactions_data),
            "period_days": days
        },
        "formatted_message": '\n'.join(output)
    }


def calculate_next_month_payment(login: str = None, last_name: str = None) -> Dict[str, Any]:
    """
    Рассчитать сумму для оплаты на следующий календарный месяц
    с учетом реального расписания группы и текущего баланса.
    
    Добавляет буфер 1000₽ на случай задержки оплаты.
    
    Args:
        login: Логин (лицевой счет) клиента
        last_name: Фамилия клиента
    
    Returns:
        Словарь с расчетом суммы в стандартном формате:
        {
            "success": bool,
            "data": {
                "login": str,
                "student_name": str,
                "current_balance": int,
                "lessons_count": int,
                "lesson_price": int,
                "total_cost": int,
                "buffer": int,
                "required_payment": int,
                "next_month": str,
                "breakdown": {...}
            },
            "formatted_message": str
        }
    """
    from calendar import monthrange
    from datetime import datetime, timedelta
    import json
    
    if not login and not last_name:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Укажите логин или фамилию клиента",
            "error": "missing_parameters"
        }
    
    clients = load_clients()
    contracts = load_contracts()
    
    if not clients or not contracts:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Данные не загружены. Запустите синхронизацию.",
            "error": "no_data"
        }
    
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
            return {
                "success": False,
                "data": {},
                "formatted_message": f"❌ Клиент с фамилией '{last_name}' не найден",
                "error": "not_found"
            }
        elif len(matches) > 1:
            matches_data = []
            for c in matches[:5]:
                student = c.get('student', {})
                matches_data.append({
                    "login": c.get('login'),
                    "full_name": f"{student.get('last_name')} {student.get('first_name')}"
                })
            
            names = [f"{m['full_name']} (логин: {m['login']})" for m in matches_data]
            
            return {
                "success": False,
                "data": {
                    "multiple_matches": matches_data,
                    "query": last_name
                },
                "formatted_message": f"❓ Найдено несколько клиентов с фамилией '{last_name}':\n" + '\n'.join(names) + "\n\nУкажите логин для точного поиска.",
                "error": "multiple_matches"
            }
        else:
            target_client = matches[0]
    
    if not target_client:
        return {
            "success": False,
            "data": {},
            "formatted_message": "❌ Клиент не найден",
            "error": "not_found"
        }
    
    # Получаем баланс
    client_id = target_client.get('id')
    client_contract = None
    
    for contract in contracts:
        if contract.get('client_id') == client_id:
            client_contract = contract
            break
    
    if not client_contract:
        return {
            "success": False,
            "data": {
                "login": target_client.get('login')
            },
            "formatted_message": "❌ Контракт для данного клиента не найден",
            "error": "no_contract"
        }
    
    current_balance = int(client_contract.get('balance', 0))
    student = target_client.get('student', {})
    
    # Пытаемся загрузить расписание группы
    group_str = student.get('group', '')
    branch_str = student.get('branch', '')
    program = student.get('program', '')
    
    # Загружаем данные групп и цен
    groups_data = None
    prices_data = None
    
    try:
        groups_path = os.path.join('data', 'groups.json')
        if os.path.exists(groups_path):
            with open(groups_path, 'r', encoding='utf-8') as f:
                groups_data = json.load(f)
        
        prices_path = os.path.join('data', 'prices.json')
        if os.path.exists(prices_path):
            with open(prices_path, 'r', encoding='utf-8') as f:
                prices_data = json.load(f)
    except Exception as e:
        pass
    
    # Извлекаем номер группы (например, "№190" из "№190 ОМ Pr4 вт/чт Чичерина 25-26")
    group_number = None
    if group_str:
        match = re.search(r'№(\d+)', group_str)
        if match:
            group_number = match.group(1)
    
    # Ищем группу в groups.json
    group_info = None
    if groups_data and group_number:
        for group in groups_data.get('groups', []):
            if group.get('group_number') == group_number:
                group_info = group
                break
    
    # Определяем следующий месяц
    now = datetime.now()
    if now.month == 12:
        next_month = 1
        next_year = now.year + 1
    else:
        next_month = now.month + 1
        next_year = now.year
    
    # Название месяца в предложном падеже (в январе, в феврале...)
    month_names_prep = {
        1: 'январе', 2: 'феврале', 3: 'марте', 4: 'апреле',
        5: 'мае', 6: 'июне', 7: 'июле', 8: 'августе',
        9: 'сентябре', 10: 'октябре', 11: 'ноябре', 12: 'декабре'
    }
    next_month_name = month_names_prep[next_month]
    
    # Считаем количество занятий
    lessons_count = None
    lesson_price = None
    is_weekend_schedule = False
    
    if group_info:
        days = group_info.get('days', [])
        is_online = group_info.get('is_online', False)
        
        # Определяем, это выходное или будничное расписание
        is_weekend_schedule = any(d in ['сб', 'вс'] for d in days)
        
        # Считаем количество дней по расписанию в следующем месяце
        lessons_count = 0
        days_ru_to_en = {
            'пн': 0, 'вт': 1, 'ср': 2, 'чт': 3, 'пт': 4, 'сб': 5, 'вс': 6
        }
        
        # Проходим по всем дням следующего месяца
        num_days = monthrange(next_year, next_month)[1]
        for day in range(1, num_days + 1):
            date = datetime(next_year, next_month, day)
            weekday = date.weekday()  # 0 = понедельник, 6 = воскресенье
            
            # Проверяем, есть ли занятие в этот день
            for schedule_day in days:
                if days_ru_to_en.get(schedule_day) == weekday:
                    lessons_count += 1
                    break
    
    # Если не удалось определить по расписанию — используем стандарт
    if lessons_count is None:
        # Стандартное количество занятий
        lessons_count = 8  # По умолчанию будни (2 раза в неделю × 4 недели)
        
        # Пытаемся определить по названию группы
        if 'сб' in group_str.lower() or 'вс' in group_str.lower():
            lessons_count = 4
            is_weekend_schedule = True
    
    # Определяем стоимость занятия
    if prices_data:
        # Нормализуем филиал для определения тарифа
        branch_lower = branch_str.lower()
        
        # Определяем, reduced или standard тариф
        reduced_districts = ['чмз', 'хмельницкого', 'чурилово', 'зальцмана', 'копейск']
        is_reduced = any(district in branch_lower for district in reduced_districts)
        tier = 'reduced' if is_reduced else 'standard'
        
        # Определяем курс
        course_key = None
        program_lower = program.lower()
        
        if 'китайск' in program_lower:
            course_key = 'chinese'
        elif 'stem' in program_lower or 'математ' in program_lower:
            course_key = 'stem_math'
        elif any(p in program_lower for p in ['огэ', 'егэ']):
            course_key = 'oge_ege'
        elif any(p in program_lower for p in ['pestart', 'pe start', 'start']):
            course_key = 'pe_start'
        elif any(p in program_lower for p in ['pekids', 'pe kids', 'kids']):
            course_key = 'pe_kids'
        elif any(p in program_lower for p in ['pe5', 'pefive', 'pe five']):
            course_key = 'pe_five'
        elif 'online' in branch_lower:
            course_key = 'pe_online'
        else:
            # По умолчанию PE Future для остальных программ
            course_key = 'pe_future'
        
        # Получаем цену
        try:
            course_data = prices_data.get('courses', {}).get(course_key, {})
            pricing = course_data.get('pricing', {})
            
            # Определяем тариф (unified, standard или reduced)
            if 'unified' in pricing:
                tier_pricing = pricing['unified']
            else:
                tier_pricing = pricing.get(tier, pricing.get('standard', {}))
            
            # Выбираем будни или выходные
            schedule_type = 'weekends' if is_weekend_schedule else 'weekdays'
            schedule_pricing = tier_pricing.get(schedule_type, tier_pricing.get('weekdays', {}))
            
            lesson_price = schedule_pricing.get('price_per_lesson')
        except:
            pass
    
    # Если не удалось определить цену — используем среднюю
    if lesson_price is None:
        if is_weekend_schedule:
            lesson_price = 1200  # Средняя цена выходного занятия
        else:
            lesson_price = 800  # Средняя цена будничного занятия
    
    # Рассчитываем необходимую сумму
    total_cost = lessons_count * lesson_price
    buffer = 1000  # Буфер на случай задержки
    
    # Если баланс положительный — вычитаем, если отрицательный — добавляем долг
    required_payment = total_cost - current_balance + buffer
    
    # Функция для склонения слова "занятие"
    def get_lessons_word(count):
        if count % 10 == 1 and count % 100 != 11:
            return "занятие"
        elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
            return "занятия"
        else:
            return "занятий"
    
    # Форматируем структурированные данные
    data = {
        "login": target_client.get('login'),
        "student_name": f"{student.get('last_name')} {student.get('first_name')} {student.get('middle_name')}".strip(),
        "first_name": student.get('first_name'),
        "group": group_str,
        "branch": branch_str,
        "current_balance": current_balance,
        "lessons_count": lessons_count,
        "lesson_price": lesson_price,
        "total_cost": total_cost,
        "buffer": buffer,
        "required_payment": required_payment,
        "next_month": next_month_name,
        "is_weekend_schedule": is_weekend_schedule,
        "breakdown": {
            "lessons_cost": total_cost,
            "balance_adjustment": -current_balance if current_balance > 0 else abs(current_balance),
            "buffer": buffer,
            "total": required_payment
        }
    }
    
    # Форматируем текстовое сообщение
    output = []
    
    # Строка 1: Имя ребенка + группа
    first_name = student.get('first_name', '')
    output.append(f"👩 {first_name}, {group_str}")
    output.append("")  # Пустая строка
    
    # Строка 2: СНАЧАЛА показываем текущий баланс
    balance_emoji = "💰" if current_balance >= 0 else "💰"
    output.append(f"{balance_emoji} Текущий баланс: {current_balance} ₽")
    output.append("")  # Пустая строка
    
    # Строка 3: Информация о занятиях
    lessons_word = get_lessons_word(lessons_count)
    output.append(f"📆 В {next_month_name} запланировано {lessons_count} {lessons_word} по {lesson_price} ₽")
    output.append(f"📊 Стоимость месяца: {lessons_count} × {lesson_price} ₽ = {total_cost} ₽")
    output.append("")  # Пустая строка
    
    # Строка 4: Рекомендация
    if current_balance < 0:
        output.append(f"⚠️ С учётом текущего минуса {abs(current_balance)} ₽ и небольшого запаса, рекомендуем оплатить {required_payment} ₽.")
    elif current_balance > 0:
        output.append(f"✅ С учётом вашего баланса {current_balance} ₽ и небольшого запаса, рекомендуем оплатить {required_payment} ₽.")
    else:
        output.append(f"✅ С учётом небольшого запаса, рекомендуем оплатить {required_payment} ₽.")
    
    output.append("")  # Пустая строка
    
    # Строка 5: ПОДРОБНЫЙ РАСЧЕТ
    output.append("📝 Как получилась сумма:")
    output.append(f"• Занятия: {total_cost} ₽")
    
    if current_balance < 0:
        output.append(f"• Погасить долг: +{abs(current_balance)} ₽")
    elif current_balance > 0:
        output.append(f"• Вычесть баланс: -{current_balance} ₽")
    
    output.append(f"• Запас на случай задержки: +{buffer} ₽")
    output.append("━━━━━━━━━━━━━━━━━━━")
    output.append(f"Итого к оплате: {required_payment} ₽")
    output.append("")  # Пустая строка
    
    # Строка 6: Итоговое пояснение
    output.append(f"✅ После оплаты на счёте останется около {buffer} ₽ — хватит с запасом 😊")
    
    return {
        "success": True,
        "data": data,
        "formatted_message": '\n'.join(output)
    }


# === Константы для функций ===
SEARCH_CLIENT_FUNCTION_NAME = "search_client_by_name"
FIND_BY_PHONE_FUNCTION_NAME = "find_clients_by_phone"
GET_BALANCE_FUNCTION_NAME = "get_client_balance"
GET_TRANSACTIONS_FUNCTION_NAME = "get_recent_transactions"
CALCULATE_PAYMENT_FUNCTION_NAME = "calculate_next_month_payment"


# Для интеграции с ботом
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_clients_by_phone",
            "description": (
                "⚠️ ВЫЗЫВАЙ ВСЕГДА когда клиент НАЗЫВАЕТ номер телефона! "
                "Автоматически ищет ученика по телефону родителя из базы 1С. "
                "Примеры когда вызывать: "
                "- 'мой номер 79123...', 'тел 8912...', 'моф номер 7912...' (даже с опечатками!) "
                "- Клиент написал последовательность из 10-11 цифр "
                "- 'нет. мой номер 79049359313' (даже если отказался от чего-то другого!) "
                "- Клиент просто написал '89123456789' без слов "
                "НЕ спрашивай имя/филиал если клиент дал телефон — СРАЗУ ищи по телефону! "
                "\n\nВОЗВРАЩАЕТ: Структурированный JSON с полями found, login, student_name, branch, group, teacher, message. "
                "Функция АВТОМАТИЧЕСКИ показывает пользователю карточку с данными ребёнка, включая строку '📱 *Логин: XXXXX*'.\n\n"
                "⚠️ КРИТИЧЕСКИ ВАЖНО ДЛЯ save_verification:\n"
                "- После того как пользователь подтвердит 'Да', ты ДОЛЖЕН вызвать save_verification\n"
                "- ЛОГИН для save_verification находится в строке '📱 *Логин: XXXXX*' в сообщении, которое ты только что показал пользователю\n"
                "- ИЗВЛЕКИ этот логин из ИСТОРИИ ДИАЛОГА (из твоего предыдущего сообщения)\n"
                "- НЕ ИСПОЛЬЗУЙ телефон! НЕ ПРИДУМЫВАЙ логин! НЕ БЕРИ из старого контекста!\n"
                "- ПРАВИЛЬНО: Найди в своём предыдущем сообщении '📱 *Логин: 26643*' → используй '26643'"
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
                "Получить текущий баланс и бонусы ученика. "
                "Используй когда клиент спрашивает о ФИНАНСАХ: 'какой баланс?', 'сколько на счету?', "
                "'проверьте баланс', 'покажите бонусы', 'сколько денег осталось?', 'задолженность'. "
                "ВАЖНО: Функция АВТОМАТИЧЕСКИ проверяет верификацию по telegram_user_id и определяет логин клиента. "
                "Если клиент не верифицирован — вернёт requires_verification=true. "
                "Если несколько детей — вернёт requires_child_selection=true со списком детей."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "telegram_user_id": {
                        "type": "integer",
                        "description": "ID пользователя в Telegram (ОБЯЗАТЕЛЬНО для автоопределения логина и верификации)"
                    },
                    "login": {
                        "type": "string",
                        "description": "Логин (лицевой счёт) ученика. ОПЦИОНАЛЬНО — автоматически определяется из верификации. Указывай только если клиент явно назвал логин."
                    },
                    "last_name": {
                        "type": "string",
                        "description": "Фамилия ученика — используй только если telegram_user_id не доступен."
                    }
                },
                "required": ["telegram_user_id"]
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
                "ВАЖНО: Функция АВТОМАТИЧЕСКИ проверяет верификацию и определяет логин клиента."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "telegram_user_id": {
                        "type": "integer",
                        "description": "ID пользователя в Telegram (ОБЯЗАТЕЛЬНО для автоопределения логина и верификации)"
                    },
                    "login": {
                        "type": "string",
                        "description": "Логин (лицевой счёт) ученика. ОПЦИОНАЛЬНО — автоматически определяется из верификации."
                    },
                    "last_name": {
                        "type": "string",
                        "description": "Фамилия ученика — используй только если telegram_user_id не доступен."
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
                "required": ["telegram_user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_next_month_payment",
            "description": (
                "Рассчитать необходимую сумму для оплаты на следующий календарный месяц. "
                "Используй когда клиент спрашивает: 'сколько нужно заплатить?', 'сколько платить в следующем месяце?', "
                "'какую сумму внести?', 'сколько будет стоить следующий месяц?', 'рассчитайте оплату'. "
                "Функция АВТОМАТИЧЕСКИ: "
                "1. Получает текущий баланс клиента "
                "2. Определяет расписание группы (количество занятий в следующем месяце) "
                "3. Рассчитывает стоимость занятий "
                "4. Добавляет буфер 1000₽ на случай задержки оплаты "
                "5. Учитывает текущий баланс (долг или остаток). "
                "ВАЖНО: Функция АВТОМАТИЧЕСКИ проверяет верификацию и определяет логин клиента."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "telegram_user_id": {
                        "type": "integer",
                        "description": "ID пользователя в Telegram (ОБЯЗАТЕЛЬНО для автоопределения логина и верификации)"
                    },
                    "login": {
                        "type": "string",
                        "description": "Логин (лицевой счёт) ученика. ОПЦИОНАЛЬНО — автоматически определяется из верификации."
                    },
                    "last_name": {
                        "type": "string",
                        "description": "Фамилия ученика — используй только если telegram_user_id не доступен."
                    }
                },
                "required": ["telegram_user_id"]
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
    """Возвращает инструмент get_client_balance в формате Responses API с поддержкой автоверификации."""
    return {
        "type": "function",
        "name": GET_BALANCE_FUNCTION_NAME,
        "description": TOOLS[2]["function"]["description"],
        "parameters": TOOLS[2]["function"]["parameters"]
    }


def get_recent_transactions_tool_for_responses_api():
    """Возвращает инструмент get_recent_transactions в формате Responses API с поддержкой автоверификации."""
    return {
        "type": "function",
        "name": GET_TRANSACTIONS_FUNCTION_NAME,
        "description": TOOLS[3]["function"]["description"],
        "parameters": TOOLS[3]["function"]["parameters"]
    }


def get_calculate_payment_tool_for_responses_api():
    """Возвращает инструмент calculate_next_month_payment в формате Responses API с поддержкой автоверификации."""
    return {
        "type": "function",
        "name": CALCULATE_PAYMENT_FUNCTION_NAME,
        "description": TOOLS[4]["function"]["description"],
        "parameters": TOOLS[4]["function"]["parameters"]
    }
