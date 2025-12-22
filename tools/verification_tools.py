"""
Инструменты для управления верификацией клиентов.
Хранят связки telegram_user_id → [client_logins] для предотвращения повторной верификации.
Поддержка нескольких детей у одного родителя (один telegram_id → много логинов).
"""

import json
import os
from typing import Optional, Dict, List
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
    if not os.path.exists(VERIFICATIONS_FILE):
        return {}
    
    try:
        with open(VERIFICATIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
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


# === Константы для функций ===
CHECK_VERIFICATION_FUNCTION_NAME = "check_verification"
SAVE_VERIFICATION_FUNCTION_NAME = "save_verification"


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
                "или после успешной проверки телефона + подтверждения ФИО."
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
                        "description": "Логин клиента (лицевой счёт), который клиент подтвердил"
                    }
                },
                "required": ["telegram_user_id", "client_login"]
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
