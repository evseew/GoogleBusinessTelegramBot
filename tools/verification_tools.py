"""
Инструменты для управления верификацией клиентов.
Хранят связки telegram_user_id → [client_logins] для предотвращения повторной верификации.
Поддержка нескольких детей у одного родителя (один telegram_id → много логинов).
"""

import json
import os
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Путь к файлу с верификациями
VERIFICATIONS_FILE = os.path.join('data', 'verified_clients.json')

# Срок действия верификации (дни). None = бессрочно
VERIFICATION_EXPIRY_DAYS = 90  # 3 месяца


def _migrate_old_format(data: Dict) -> Dict:
    """
    Миграция старого формата в новый.
    
    Старый формат:
    {
      "123456789": {
        "login": "46168",
        "verified_at": "2025-12-22T16:30:00"
      }
    }
    
    Новый формат:
    {
      "123456789": {
        "logins": ["46168"],
        "verifications": {
          "46168": {"verified_at": "2025-12-22T16:30:00"}
        }
      }
    }
    """
    migrated = {}
    
    for user_id, user_data in data.items():
        # Проверяем, является ли user_id валидным telegram_id
        # Telegram ID обычно > 1000000
        try:
            user_id_int = int(user_id)
            if user_id_int < 100000:
                # Это скорее всего логин, а не telegram_id - пропускаем
                logger.warning(f"Пропускаем некорректную запись с ключом {user_id} (похоже на логин, а не telegram_id)")
                continue
        except ValueError:
            logger.warning(f"Пропускаем запись с некорректным ключом: {user_id}")
            continue
        
        # Проверяем формат данных
        if 'logins' in user_data and 'verifications' in user_data:
            # Уже новый формат
            migrated[user_id] = user_data
        elif 'login' in user_data:
            # Старый формат - конвертируем
            login = user_data['login']
            verified_at = user_data.get('verified_at')
            
            migrated[user_id] = {
                'logins': [login],
                'verifications': {
                    login: {'verified_at': verified_at}
                }
            }
            logger.info(f"Мигрирована запись: telegram_id={user_id}, login={login}")
        else:
            logger.warning(f"Неизвестный формат данных для user_id={user_id}: {user_data}")
    
    return migrated


def _load_verifications() -> Dict:
    """Загрузить верификации из файла с автоматической миграцией"""
    # Создаём директорию, если не существует
    os.makedirs(os.path.dirname(VERIFICATIONS_FILE), exist_ok=True)
    
    if not os.path.exists(VERIFICATIONS_FILE):
        logger.info(f"Файл верификаций {VERIFICATIONS_FILE} не найден, создаём пустой")
        # Инициализируем пустой файл
        _save_verifications({})
        return {}
    
    try:
        with open(VERIFICATIONS_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
            # Если файл пустой — инициализируем
            if not content:
                logger.info(f"Файл верификаций {VERIFICATIONS_FILE} пустой, инициализируем")
                _save_verifications({})
                return {}
            
            data = json.loads(content)
        
        # Проверяем, нужна ли миграция
        needs_migration = False
        for user_data in data.values():
            if 'login' in user_data or ('logins' not in user_data):
                needs_migration = True
                break
        
        if needs_migration:
            logger.info("Обнаружен старый формат верификаций, выполняется миграция...")
            data = _migrate_old_format(data)
            # Сохраняем мигрированные данные
            _save_verifications(data)
            logger.info("Миграция верификаций завершена успешно")
        
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON верификаций: {e}. Создаём новый файл.")
        # Если файл повреждён — создаём новый
        _save_verifications({})
        return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки верификаций: {e}")
        return {}


def _save_verifications(verifications: Dict) -> bool:
    """Сохранить верификации в файл"""
    try:
        os.makedirs(os.path.dirname(VERIFICATIONS_FILE), exist_ok=True)
        with open(VERIFICATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(verifications, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения верификаций: {e}")
        return False


def save_verification(telegram_user_id: int, client_login: str) -> str:
    """
    Сохранить верификацию клиента. Добавляет логин в список, если его там ещё нет.
    
    Args:
        telegram_user_id: ID пользователя в Telegram
        client_login: Логин клиента (лицевой счёт)
    
    Returns:
        Сообщение о результате
    """
    # 🔒 ВАЛИДАЦИЯ: Проверяем, что это логин, а не телефон
    if not client_login or not isinstance(client_login, str):
        error_msg = f"❌ ОШИБКА: Некорректный логин '{client_login}'. Логин должен быть строкой."
        logger.error(f"save_verification: {error_msg} telegram_user={telegram_user_id}")
        return error_msg
    
    # Логин должен быть числовым (может содержать только цифры) и короче 10 символов
    # Телефоны обычно 11+ символов, логины — 4-6 символов
    if len(client_login) > 10:
        error_msg = (
            f"❌ ОШИБКА: '{client_login}' похоже на телефон (слишком длинный для логина). "
            f"Логин — это короткий числовой лицевой счёт (например '26643'). "
            f"Используйте поле 'login' из результата find_clients_by_phone!"
        )
        logger.error(f"save_verification: {error_msg} telegram_user={telegram_user_id}")
        return error_msg
    
    # Проверяем, что это число
    if not client_login.isdigit():
        error_msg = (
            f"❌ ОШИБКА: Логин '{client_login}' должен содержать только цифры. "
            f"Проверьте, что вы используете поле 'login' из результата find_clients_by_phone."
        )
        logger.error(f"save_verification: {error_msg} telegram_user={telegram_user_id}")
        return error_msg
    
    verifications = _load_verifications()
    user_key = str(telegram_user_id)
    
    # Получаем или создаём запись пользователя
    if user_key not in verifications:
        verifications[user_key] = {
            'logins': [],
            'verifications': {}
        }
    
    user_data = verifications[user_key]
    
    # Добавляем логин в список, если его там ещё нет
    if client_login not in user_data['logins']:
        user_data['logins'].append(client_login)
        logger.info(f"✅ Добавлен новый логин: telegram_user={telegram_user_id}, login={client_login}")
    else:
        logger.info(f"ℹ️ Логин уже в списке: telegram_user={telegram_user_id}, login={client_login}")
    
    # Сохраняем/обновляем timestamp верификации
    user_data['verifications'][client_login] = {
        'verified_at': datetime.now().isoformat()
    }
    
    if _save_verifications(verifications):
        logins_count = len(user_data['logins'])
        if logins_count > 1:
            return f"✅ Верификация сохранена для логина {client_login} (всего детей: {logins_count})"
        else:
            return f"✅ Верификация сохранена для логина {client_login}"
    else:
        return "❌ Ошибка сохранения верификации"


def is_client_verified(telegram_user_id: int, client_login: str) -> bool:
    """
    Проверить, верифицирован ли клиент.
    
    Args:
        telegram_user_id: ID пользователя в Telegram
        client_login: Логин клиента (лицевой счёт)
    
    Returns:
        True если верификация актуальна, False иначе
    """
    verifications = _load_verifications()
    user_key = str(telegram_user_id)
    
    if user_key not in verifications:
        logger.debug(f"Верификация НЕ найдена для telegram_user={telegram_user_id}")
        return False
    
    user_data = verifications[user_key]
    
    # Проверяем наличие логина в списке
    if client_login not in user_data.get('logins', []):
        logger.debug(f"Логин {client_login} НЕ найден в списке верифицированных для telegram_user={telegram_user_id}")
        return False
    
    # Проверяем срок действия (если установлен)
    if VERIFICATION_EXPIRY_DAYS is not None:
        verification_info = user_data.get('verifications', {}).get(client_login, {})
        verified_at_str = verification_info.get('verified_at')
        
        if verified_at_str:
            try:
                verified_at = datetime.fromisoformat(verified_at_str)
                expiry_date = verified_at + timedelta(days=VERIFICATION_EXPIRY_DAYS)
                
                if datetime.now() > expiry_date:
                    logger.info(f"Верификация истекла для telegram_user={telegram_user_id}, login={client_login}")
                    # Удаляем устаревшую верификацию конкретного логина
                    user_data['logins'].remove(client_login)
                    del user_data['verifications'][client_login]
                    
                    # Если у пользователя не осталось верификаций, удаляем всю запись
                    if not user_data['logins']:
                        del verifications[user_key]
                    
                    _save_verifications(verifications)
                    return False
            except ValueError:
                logger.warning(f"Некорректная дата верификации: {verified_at_str}")
    
    logger.info(f"✅ Верификация найдена и актуальна: telegram_user={telegram_user_id}, login={client_login}")
    return True


def check_verification(telegram_user_id: int, client_login: str) -> str:
    """
    Функция для бота: проверить статус верификации клиента.
    
    Args:
        telegram_user_id: ID пользователя в Telegram
        client_login: Логин клиента (лицевой счёт)
    
    Returns:
        Строка с результатом проверки
    """
    if is_client_verified(telegram_user_id, client_login):
        return f"verified|{client_login}"
    else:
        return f"not_verified|{client_login}"


def reset_verification(telegram_user_id: int, client_login: Optional[str] = None) -> str:
    """
    Сбросить верификацию для пользователя.
    
    Args:
        telegram_user_id: ID пользователя в Telegram
        client_login: (опционально) Логин конкретного клиента для сброса.
                     Если не указан - сбрасываются ВСЕ верификации пользователя.
    
    Returns:
        Сообщение о результате
    """
    verifications = _load_verifications()
    user_key = str(telegram_user_id)
    
    if user_key not in verifications:
        return "ℹ️ Верификация не найдена"
    
    user_data = verifications[user_key]
    
    # Если указан конкретный логин - удаляем только его
    if client_login:
        if client_login in user_data.get('logins', []):
            user_data['logins'].remove(client_login)
            if client_login in user_data.get('verifications', {}):
                del user_data['verifications'][client_login]
            
            # Если это был последний логин - удаляем всю запись пользователя
            if not user_data['logins']:
                del verifications[user_key]
                logger.info(f"Верификация сброшена полностью для telegram_user={telegram_user_id} (последний логин {client_login})")
                result_msg = f"✅ Верификация сброшена для логина {client_login}"
            else:
                logger.info(f"Верификация сброшена для telegram_user={telegram_user_id}, login={client_login} (осталось логинов: {len(user_data['logins'])})")
                result_msg = f"✅ Верификация сброшена для логина {client_login} (осталось детей: {len(user_data['logins'])})"
        else:
            return f"ℹ️ Логин {client_login} не найден в списке верификаций"
    else:
        # Удаляем все верификации пользователя
        logins_count = len(user_data.get('logins', []))
        del verifications[user_key]
        logger.info(f"Все верификации сброшены для telegram_user={telegram_user_id} (было логинов: {logins_count})")
        result_msg = f"✅ Все верификации сброшены (было детей: {logins_count})"
    
    if _save_verifications(verifications):
        return result_msg
    else:
        return "❌ Ошибка сброса верификации"


def get_all_verifications() -> str:
    """
    Получить список всех верификаций (для отладки, только для админа).
    
    Returns:
        Строка со списком верификаций
    """
    verifications = _load_verifications()
    
    if not verifications:
        return "📋 Верификации отсутствуют"
    
    total_users = len(verifications)
    total_logins = sum(len(data.get('logins', [])) for data in verifications.values())
    
    lines = [f"📋 Всего пользователей: {total_users}"]
    lines.append(f"📋 Всего верифицированных логинов: {total_logins}\n")
    
    for telegram_id, data in verifications.items():
        logins = data.get('logins', [])
        verifications_data = data.get('verifications', {})
        
        lines.append(f"👤 Telegram ID: {telegram_id}")
        lines.append(f"   👶 Детей: {len(logins)}")
        
        for login in logins:
            verification_info = verifications_data.get(login, {})
            verified_at = verification_info.get('verified_at', 'N/A')
            
            if verified_at != 'N/A':
                try:
                    dt = datetime.fromisoformat(verified_at)
                    verified_at_str = dt.strftime('%d.%m.%Y %H:%M')
                except:
                    verified_at_str = verified_at
            else:
                verified_at_str = 'N/A'
            
            lines.append(f"   • Логин: {login}")
            lines.append(f"     Дата: {verified_at_str}")
        
        lines.append("")  # Пустая строка между пользователями
    
    return '\n'.join(lines)


# === Новые функции для автоматического определения логина ===

def get_verified_login_with_context(
    telegram_user_id: int, 
    current_child_login: Optional[str] = None
) -> Dict[str, Any]:
    """
    Получить логин верифицированного клиента с учётом контекста.
    
    Args:
        telegram_user_id: ID пользователя в Telegram
        current_child_login: Текущий выбранный ребёнок (если есть)
    
    Returns:
        {
            "status": "ok" | "not_verified" | "select_child",
            "login": str,  # Если status == "ok"
            "children": List[Dict],  # Если status == "select_child"
            "message": str
        }
    """
    verifications = _load_verifications()
    user_key = str(telegram_user_id)
    
    # Проверка 1: Есть ли верификация?
    if user_key not in verifications:
        return {
            "status": "not_verified",
            "message": "Необходимо пройти верификацию по номеру телефона."
        }
    
    logins = verifications[user_key].get('logins', [])
    
    if not logins:
        return {
            "status": "not_verified",
            "message": "Верификация не найдена."
        }
    
    # Проверка 2: Один ребёнок — сразу возвращаем
    if len(logins) == 1:
        login = logins[0]
        if is_client_verified(telegram_user_id, login):
            return {
                "status": "ok",
                "login": login,
                "message": f"Используется логин: {login}"
            }
        else:
            return {
                "status": "not_verified",
                "message": "Срок верификации истёк."
            }
    
    # Проверка 3: Несколько детей
    # Если уже выбран ребёнок в контексте — используем его
    if current_child_login and current_child_login in logins:
        if is_client_verified(telegram_user_id, current_child_login):
            return {
                "status": "ok",
                "login": current_child_login,
                "message": f"Используется логин: {current_child_login}"
            }
    
    # Проверка 4: Нужен выбор ребёнка — загружаем имена
    from .client_tools import load_clients
    clients = load_clients()
    
    children = []
    for login in logins:
        if is_client_verified(telegram_user_id, login):
            client = next((c for c in clients if c.get('login') == login), None)
            if client:
                student = client.get('student', {})
                children.append({
                    "login": login,
                    "name": f"{student.get('last_name', '')} {student.get('first_name', '')}".strip(),
                    "phone": client.get('contacts', {}).get('phone', '')
                })
    
    return {
        "status": "select_child",
        "children": children,
        "message": f"У вас {len(children)} детей. О каком ребёнке вы хотите узнать?"
    }


def get_client_context(telegram_user_id: int) -> Dict[str, Any]:
    """
    Получить полный контекст верифицированного клиента для персонализации.
    
    ВАЖНО: Вызывай КАЖДЫЙ РАЗ при формировании ответа!
    Данные всегда свежие (группа, преподаватель, филиал могут меняться).
    
    Функция автоматически:
    1. Проверяет верификацию клиента
    2. Загружает актуальные данные из базы (ФИО, филиал, группу, преподавателя)
    3. Возвращает готовый контекст для персонализированного общения
    
    НЕ ВОЗВРАЩАЕТ: баланс и транзакции (они запрашиваются отдельно через get_client_balance и get_recent_transactions)
    
    Args:
        telegram_user_id: ID пользователя в Telegram
    
    Returns:
        {
            "is_verified": bool,
            "login": str | None,
            "client_name": str | None,        # ФИО родителя (Имя Отчество)
            "student_name": str | None,       # ФИО ребенка
            "student_age": int | None,
            "branch": str | None,             # Филиал обучения
            "group": str | None,              # Группа (номер + программа)
            "teacher": str | None,            # ФИО преподавателя
            "phone": str | None,              # Телефон родителя
            "message": str
        }
    """
    verifications = _load_verifications()
    user_key = str(telegram_user_id)
    
    # Шаг 1: Проверка верификации
    if user_key not in verifications:
        return {
            "is_verified": False,
            "message": "Клиент не верифицирован. Предложите верификацию по номеру телефона или логину."
        }
    
    user_data = verifications[user_key]
    logins = user_data.get('logins', [])
    
    if not logins:
        return {
            "is_verified": False,
            "message": "Верификация не найдена."
        }
    
    # Если несколько детей — берём первого (или можно добавить логику выбора через set_active_child)
    login = logins[0]
    
    # Шаг 2: Проверка срока действия верификации
    if not is_client_verified(telegram_user_id, login):
        return {
            "is_verified": False,
            "message": "Срок верификации истёк. Требуется повторная верификация."
        }
    
    # Шаг 3: Загрузка актуальных данных клиента
    from .client_tools import get_verified_client_data
    
    client_data = get_verified_client_data(login)
    
    if not client_data:
        return {
            "is_verified": True,
            "login": login,
            "message": f"Верификация OK, но данные не найдены для логина {login}"
        }
    
    # Шаг 4: Возврат полного контекста для персонализации
    return {
        "is_verified": True,
        "login": login,
        "client_name": client_data.get('client_name'),
        "student_name": client_data.get('student_name'),
        "student_age": client_data.get('student_age'),
        "branch": client_data.get('branch_name'),  # Исправлено: было 'branch'
        "group": client_data.get('group_number'),
        "teacher": client_data.get('teacher'),  # Исправлено: было 'teacher_name'
        "phone": client_data.get('client_phone'),
        "message": "Клиент верифицирован. Используйте персонализацию: обращайтесь по имени-отчеству к родителю, упоминайте имя ребенка, филиал, группу и преподавателя в ответах."
    }


def set_active_child(telegram_user_id: int, child_identifier: str) -> Dict[str, Any]:
    """
    Устанавливает активного ребёнка для пользователя.
    
    Args:
        telegram_user_id: ID пользователя
        child_identifier: Имя, логин или номер ребёнка
    
    Returns:
        Результат установки
    """
    verifications = _load_verifications()
    user_key = str(telegram_user_id)
    
    if user_key not in verifications:
        return {
            "success": False,
            "message": "Верификация не найдена"
        }
    
    logins = verifications[user_key].get('logins', [])
    
    if not logins:
        return {
            "success": False,
            "message": "Нет верифицированных детей"
        }
    
    from .client_tools import load_clients
    clients = load_clients()
    
    # Пытаемся найти ребёнка по идентификатору
    selected_login = None
    
    # Вариант 1: Это номер (1, 2, 3...)
    if child_identifier.strip().isdigit():
        index = int(child_identifier.strip()) - 1
        if 0 <= index < len(logins):
            selected_login = logins[index]
    
    # Вариант 2: Это логин
    elif child_identifier in logins:
        selected_login = child_identifier
    
    # Вариант 3: Это имя ребёнка (поиск по имени)
    else:
        for login in logins:
            client = next((c for c in clients if c.get('login') == login), None)
            if client:
                student = client.get('student', {})
                # Полное ФИО
                full_name = f"{student.get('last_name', '')} {student.get('first_name', '')} {student.get('middle_name', '')}".strip().lower()
                # Только имя
                first_name = student.get('first_name', '').lower()
                
                if child_identifier.lower() in full_name or child_identifier.lower() == first_name:
                    selected_login = login
                    break
    
    if selected_login:
        # Находим имя для подтверждения
        client = next((c for c in clients if c.get('login') == selected_login), None)
        if client:
            student = client.get('student', {})
            child_name = f"{student.get('last_name', '')} {student.get('first_name', '')}".strip()
        else:
            child_name = selected_login
        
        return {
            "success": True,
            "login": selected_login,
            "name": child_name,
            "message": f"Выбран ребёнок: {child_name} (логин {selected_login})"
        }
    else:
        return {
            "success": False,
            "message": f"Ребёнок '{child_identifier}' не найден среди верифицированных"
        }


# === Константы для функций ===
CHECK_VERIFICATION_FUNCTION_NAME = "check_verification"
SAVE_VERIFICATION_FUNCTION_NAME = "save_verification"
SET_ACTIVE_CHILD_FUNCTION_NAME = "set_active_child"


# Определения инструментов для OpenAI Function Calling
VERIFICATION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_verification",
            "description": (
                "ОБЯЗАТЕЛЬНО вызывай ПЕРЕД запросом баланса или транзакций! "
                "Проверяет, верифицирован ли клиент (подтверждал ли он ранее, что это его ребёнок). "
                "Если верифицирован — пропускаешь шаги верификации и СРАЗУ показываешь данные. "
                "Если НЕ верифицирован — показываешь карточку и просишь подтверждение."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "telegram_user_id": {
                        "type": "integer",
                        "description": "ID пользователя в Telegram (получи из контекста диалога)"
                    },
                    "client_login": {
                        "type": "string",
                        "description": "Логин клиента (лицевой счёт), например '46168'"
                    }
                },
                "required": ["telegram_user_id", "client_login"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_verification",
            "description": (
                "Сохраняет верификацию клиента ПОСЛЕ успешного подтверждения. "
                "Вызывай СРАЗУ ПОСЛЕ того, как клиент подтвердил 'Да' на вопрос 'Это данные вашего ребёнка?' "
                "или после успешной проверки телефона + подтверждения ФИО. "
                "\n\n⚠️ КРИТИЧЕСКИ ВАЖНО - КАК НАЙТИ ПРАВИЛЬНЫЙ ЛОГИН:\n"
                "1. ПОСМОТРИ В ИСТОРИЮ ДИАЛОГА - найди сообщение с результатом find_clients_by_phone\n"
                "2. ИЗВЛЕКИ ЛОГИН из строки '📱 *Логин: XXXXX*' (где XXXXX - это нужный логин)\n"
                "3. ИСПОЛЬЗУЙ ИМЕННО ЭТОТ ЛОГИН для сохранения верификации\n\n"
                "ПРАВИЛЬНЫЙ АЛГОРИТМ:\n"
                "- Пользователь дал телефон → find_clients_by_phone вернул данные с логином\n"
                "- Ты показал: '👤 Иванов Иван / 📱 Логин: 26643'\n"
                "- Пользователь подтвердил: 'Да'\n"
                "- ТЫ ВЫЗЫВАЕШЬ: save_verification(telegram_user_id=123, client_login='26643')\n\n"
                "⛔ ЗАПРЕЩЕНО:\n"
                "- Использовать номер телефона вместо логина\n"
                "- Придумывать логин\n"
                "- Брать логин из старого контекста\n"
                "- Использовать логин другого ребёнка\n\n"
                "✅ ЛОГИН = числовой код из строки '📱 *Логин: XXXXX*' в ПРЕДЫДУЩЕМ сообщении бота!"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "telegram_user_id": {
                        "type": "integer",
                        "description": "ID пользователя в Telegram"
                    },
                    "client_login": {
                        "type": "string",
                        "description": "Логин клиента (лицевой счёт) — ОБЯЗАТЕЛЬНО бери из поля 'login' результата find_clients_by_phone! Это числовой код, например '26643', НЕ телефон!"
                    }
                },
                "required": ["telegram_user_id", "client_login"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_active_child",
            "description": (
                "Устанавливает активного ребёнка, о котором идёт речь в диалоге. "
                "Вызывай, когда родитель называет имя ребёнка или выбирает из списка. "
                "После установки все последующие запросы (баланс, транзакции) будут автоматически "
                "использовать данные выбранного ребёнка. "
                "Примеры: 'про Машу', 'первого', '1', 'логин 44741', 'Иванова Мария'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "telegram_user_id": {
                        "type": "integer",
                        "description": "ID пользователя в Telegram"
                    },
                    "child_identifier": {
                        "type": "string",
                        "description": "Имя ребёнка, логин или номер из списка (1, 2, 3...)"
                    }
                },
                "required": ["telegram_user_id", "child_identifier"]
            }
        }
    }
]


# === Функции для Responses API ===

def get_check_verification_tool_for_responses_api():
    """Возвращает инструмент check_verification в формате Responses API."""
    return {
        "type": "function",
        "name": CHECK_VERIFICATION_FUNCTION_NAME,
        "description": VERIFICATION_TOOLS[0]["function"]["description"],
        "parameters": VERIFICATION_TOOLS[0]["function"]["parameters"]
    }


def get_save_verification_tool_for_responses_api():
    """Возвращает инструмент save_verification в формате Responses API."""
    return {
        "type": "function",
        "name": SAVE_VERIFICATION_FUNCTION_NAME,
        "description": VERIFICATION_TOOLS[1]["function"]["description"],
        "parameters": VERIFICATION_TOOLS[1]["function"]["parameters"]
    }


def get_set_active_child_tool_for_responses_api():
    """Возвращает инструмент set_active_child в формате Responses API."""
    return {
        "type": "function",
        "name": SET_ACTIVE_CHILD_FUNCTION_NAME,
        "description": VERIFICATION_TOOLS[2]["function"]["description"],
        "parameters": VERIFICATION_TOOLS[2]["function"]["parameters"]
    }


