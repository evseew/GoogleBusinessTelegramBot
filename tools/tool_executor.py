"""
Исполнитель функций для OpenAI Function Calling.
Централизованная обработка всех tool calls.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Callable

from .branch_tools import (
    get_branches, 
    BRANCHES_TOOL_DEFINITION,
    get_branches_tool_for_responses_api,
    BRANCHES_FUNCTION_NAME,
)
from .price_tools import (
    get_prices,
    PRICES_TOOL_DEFINITION,
    get_prices_tool_for_responses_api,
    PRICES_FUNCTION_NAME,
)
from .group_tools import (
    search_groups,
    GROUPS_TOOL_DEFINITION,
    get_groups_tool_for_responses_api,
    GROUPS_FUNCTION_NAME,
)
from .pyrus_tools import (
    create_pyrus_task,
    PYRUS_TOOL_DEFINITION,
    get_pyrus_tool_for_responses_api,
    PYRUS_FUNCTION_NAME,
)
from .client_tools import (
    search_client_by_name,
    find_clients_by_phone,
    get_client_balance,
    get_recent_transactions,
    calculate_next_month_payment,
    TOOLS as CLIENT_TOOLS_DEFINITIONS,
    get_search_client_tool_for_responses_api,
    get_find_by_phone_tool_for_responses_api,
    get_client_balance_tool_for_responses_api,
    get_recent_transactions_tool_for_responses_api,
    get_calculate_payment_tool_for_responses_api,
    SEARCH_CLIENT_FUNCTION_NAME,
    FIND_BY_PHONE_FUNCTION_NAME,
    GET_BALANCE_FUNCTION_NAME,
    GET_TRANSACTIONS_FUNCTION_NAME,
    CALCULATE_PAYMENT_FUNCTION_NAME,
)
from .verification_tools import (
    check_verification,
    save_verification,
    reset_verification,
    set_active_child,
    get_verified_login_with_context,
    is_client_verified,
    VERIFICATION_TOOLS,
    get_check_verification_tool_for_responses_api,
    get_save_verification_tool_for_responses_api,
    get_set_active_child_tool_for_responses_api,
    CHECK_VERIFICATION_FUNCTION_NAME,
    SAVE_VERIFICATION_FUNCTION_NAME,
    SET_ACTIVE_CHILD_FUNCTION_NAME,
)
from .conversation_tools import (
    set_conversation_topic,
    get_conversation_topic_tool_for_responses_api,
    CONVERSATION_TOPIC_FUNCTION_NAME,
)

logger = logging.getLogger(__name__)

# --- Регистрация всех доступных tools ---

# Для Chat Completions API
AVAILABLE_TOOLS_CHAT: List[Dict[str, Any]] = [
    BRANCHES_TOOL_DEFINITION,
    PRICES_TOOL_DEFINITION,
    GROUPS_TOOL_DEFINITION,
    PYRUS_TOOL_DEFINITION,
    *CLIENT_TOOLS_DEFINITIONS,  # Добавляем инструменты для работы с клиентами из 1С
    *VERIFICATION_TOOLS,  # Инструменты верификации клиентов
]

# Маппинг имён функций на реальные функции
TOOL_FUNCTIONS: Dict[str, Callable] = {
    "get_branches": get_branches,
    "get_prices": get_prices,
    "search_groups": search_groups,
    "create_pyrus_task": create_pyrus_task,
    # Функции для работы с данными клиентов из 1С
    "search_client_by_name": search_client_by_name,
    "find_clients_by_phone": find_clients_by_phone,
    "get_client_balance": get_client_balance,
    "get_recent_transactions": get_recent_transactions,
    "calculate_next_month_payment": calculate_next_month_payment,
    # Функции верификации клиентов
    "check_verification": check_verification,
    "save_verification": save_verification,
    "reset_verification": reset_verification,
    "set_active_child": set_active_child,
    # Функции управления контекстом диалога
    "set_conversation_topic": set_conversation_topic,
}


def get_tools_for_api(api_type: str = "responses") -> List[Dict[str, Any]]:
    """
    Возвращает список tools для передачи в OpenAI API.
    
    Args:
        api_type: "responses" для Responses API, "chat" для Chat Completions API
    """
    if api_type == "chat":
        return AVAILABLE_TOOLS_CHAT
    else:
        # Responses API использует другой формат
        return [
            get_branches_tool_for_responses_api(),
            get_prices_tool_for_responses_api(),
            get_groups_tool_for_responses_api(),
            get_pyrus_tool_for_responses_api(),
            # Инструменты для работы с клиентами
            get_find_by_phone_tool_for_responses_api(),
            get_search_client_tool_for_responses_api(),
            get_client_balance_tool_for_responses_api(),
            get_recent_transactions_tool_for_responses_api(),
            get_calculate_payment_tool_for_responses_api(),
            # Инструменты верификации
            get_check_verification_tool_for_responses_api(),
            get_save_verification_tool_for_responses_api(),
            get_set_active_child_tool_for_responses_api(),
            # Инструменты управления контекстом диалога
            get_conversation_topic_tool_for_responses_api(),
        ]


# Алиас для обратной совместимости
AVAILABLE_TOOLS = AVAILABLE_TOOLS_CHAT


# Список tools, требующих верификацию
REQUIRES_VERIFICATION_TOOLS = {
    "get_client_balance",
    "get_recent_transactions",
    "calculate_next_month_payment",
    "create_pyrus_task",
}


def execute_tool_call(
    tool_name: str, 
    arguments: Dict[str, Any],
    current_child_login: Optional[str] = None
) -> Dict[str, Any]:
    """
    Выполняет вызов функции с автоматической проверкой верификации.
    
    Args:
        tool_name: Имя функции (например "get_branches")
        arguments: Аргументы функции
        current_child_login: Текущий выбранный ребёнок (из контекста сессии)
    
    Returns:
        Результат выполнения функции
    """
    logger.info(f"Выполнение tool call: {tool_name} с аргументами: {arguments}")
    
    # === ПРОВЕРКА ВЕРИФИКАЦИИ ДЛЯ ЛИЧНЫХ ДАННЫХ ===
    if tool_name in REQUIRES_VERIFICATION_TOOLS:
        telegram_user_id = arguments.get("telegram_user_id")
        
        if telegram_user_id:
            logger.debug(f"Tool {tool_name} требует верификацию. Проверяем user_id={telegram_user_id}")
            
            result = get_verified_login_with_context(
                telegram_user_id, 
                current_child_login
            )
            
            if result["status"] == "ok":
                # ✅ Верифицирован — проверяем приоритет логина
                explicit_login = arguments.get("login", "").strip()
                
                if explicit_login:
                    # Логин явно указан LLM — валидируем его
                    if is_client_verified(telegram_user_id, explicit_login):
                        # Используем явно указанный логин (не перезаписываем)
                        logger.info(f"✅ Использован явный логин: {explicit_login} для user {telegram_user_id}")
                    else:
                        # Указанный логин не верифицирован — ошибка
                        logger.warning(f"❌ Логин {explicit_login} не найден среди верифицированных детей user {telegram_user_id}")
                        return {
                            "error": f"Логин {explicit_login} не найден среди верифицированных детей."
                        }
                else:
                    # Логин не указан — автоподстановка из контекста
                    arguments["login"] = result["login"]
                    logger.info(f"✅ Автоподстановка логина: {result['login']} для user {telegram_user_id}")
                
                # Удаляем служебный параметр, чтобы не передавать в бизнес-функцию
                arguments.pop("telegram_user_id", None)
                
            elif result["status"] == "select_child":
                # 🤔 Нужен выбор ребёнка
                children = result["children"]
                logger.info(f"Требуется выбор ребёнка. Найдено детей: {len(children)}")
                
                # Форматируем красивый ответ для GPT
                children_list = "\n".join([
                    f"{i+1}. {c['name']} (логин {c['login']})" 
                    for i, c in enumerate(children)
                ])
                
                return {
                    "requires_child_selection": True,
                    "children": children,
                    "formatted_message": (
                        f"У вас {len(children)} детей:\n{children_list}\n\n"
                        "О каком ребёнке вы хотите узнать? Назовите имя или номер."
                    ),
                    "message": result["message"]
                }
                
            else:  # not_verified
                # ❌ НЕ верифицирован
                logger.warning(f"User {telegram_user_id} не верифицирован. Требуется верификация.")
                return {
                    "requires_verification": True,
                    "message": result["message"]
                }
    
    # === ОБЫЧНОЕ ВЫПОЛНЕНИЕ ===
    if tool_name not in TOOL_FUNCTIONS:
        error_msg = f"Неизвестная функция: {tool_name}"
        logger.error(error_msg)
        return {"error": error_msg}
    
    try:
        func = TOOL_FUNCTIONS[tool_name]
        result = func(**arguments)
        logger.info(f"Tool call {tool_name} выполнен успешно")
        return result
    except TypeError as e:
        error_msg = f"Ошибка аргументов для {tool_name}: {e}"
        logger.error(error_msg)
        return {"error": error_msg}
    except Exception as e:
        error_msg = f"Ошибка выполнения {tool_name}: {e}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}


def parse_tool_calls_from_response(response) -> List[Dict[str, Any]]:
    """
    Извлекает tool calls из ответа OpenAI.
    
    Поддерживает разные форматы ответа (Responses API, Chat Completions).
    При ошибке парсинга создаёт error tool call для корректной обработки.
    
    Returns:
        Список словарей с tool calls: [{"id": ..., "name": ..., "arguments": {...}, "_error": ...}]
    """
    tool_calls = []
    
    # Responses API формат (output содержит список items)
    if hasattr(response, 'output'):
        for item in response.output:
            if hasattr(item, 'type') and item.type == 'function_call':
                try:
                    arguments = json.loads(item.arguments) if isinstance(item.arguments, str) else item.arguments
                    tool_calls.append({
                        "id": getattr(item, 'call_id', getattr(item, 'id', None)),
                        "name": item.name,
                        "arguments": arguments
                    })
                except json.JSONDecodeError as e:
                    # 🔧 ВАРИАНТ 4: Создаём error tool call для отправки в API
                    call_id = getattr(item, 'call_id', getattr(item, 'id', f"error_{id(item)}"))
                    error_message = f"JSON parsing error: {str(e)[:200]}. Аргументы слишком длинные или содержат невалидный JSON. Пожалуйста, сократите текст и попробуйте снова."
                    
                    logger.error(f"Ошибка парсинга аргументов tool call {call_id}: {e}")
                    logger.debug(f"Проблемные аргументы (первые 500 символов): {str(item.arguments)[:500] if hasattr(item, 'arguments') else 'N/A'}")
                    
                    # Создаём специальный error tool call
                    tool_calls.append({
                        "id": call_id,
                        "name": item.name,
                        "arguments": {},
                        "_error": error_message  # Специальный флаг для обработки ошибки
                    })
    
    # Chat Completions формат (choices[0].message.tool_calls)
    elif hasattr(response, 'choices'):
        message = response.choices[0].message
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": arguments
                    })
                except json.JSONDecodeError as e:
                    # 🔧 ВАРИАНТ 4: Создаём error tool call для отправки в API
                    error_message = f"JSON parsing error: {str(e)[:200]}. Аргументы слишком длинные или содержат невалидный JSON. Пожалуйста, сократите текст и попробуйте снова."
                    
                    logger.error(f"Ошибка парсинга аргументов tool call {tc.id}: {e}")
                    logger.debug(f"Проблемные аргументы (первые 500 символов): {tc.function.arguments[:500] if hasattr(tc.function, 'arguments') else 'N/A'}")
                    
                    # Создаём специальный error tool call
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": {},
                        "_error": error_message  # Специальный флаг для обработки ошибки
                    })
    
    return tool_calls


def format_tool_results_for_api(
    tool_calls: List[Dict[str, Any]], 
    results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Форматирует результаты выполнения tools для отправки обратно в API.
    
    ВАЖНО: Все tools теперь возвращают структурированный формат:
    {
        "success": bool,
        "data": {...},  # Структурированные данные для программной обработки
        "formatted_message": str,  # Готовый текст для отправки пользователю
        "error": str (optional)  # Код ошибки если success=False
    }
    
    LLM должен использовать "formatted_message" для ответа пользователю,
    а "data" — для программной логики (проверки условий, извлечения значений).
    
    Returns:
        Список сообщений с результатами для добавления в input
    """
    formatted = []
    
    for i, (tc, result) in enumerate(zip(tool_calls, results)):
        formatted.append({
            "type": "function_call_output",
            "call_id": tc.get("id"),
            "output": json.dumps(result, ensure_ascii=False)
        })
    
    return formatted


def has_tool_calls(response) -> bool:
    """Проверяет, содержит ли ответ tool calls."""
    # Responses API
    if hasattr(response, 'output'):
        for item in response.output:
            if hasattr(item, 'type') and item.type == 'function_call':
                return True
    
    # Chat Completions
    if hasattr(response, 'choices'):
        message = response.choices[0].message
        if hasattr(message, 'tool_calls') and message.tool_calls:
            return True
    
    return False


def get_text_from_response(response) -> Optional[str]:
    """Извлекает текстовый ответ из response."""
    # Responses API — output_text
    if hasattr(response, 'output_text') and response.output_text:
        return response.output_text
    
    # Responses API — ищем в output
    if hasattr(response, 'output'):
        for item in response.output:
            if hasattr(item, 'type') and item.type == 'message':
                if hasattr(item, 'content'):
                    for content_item in item.content:
                        if hasattr(content_item, 'text'):
                            return content_item.text
    
    # Chat Completions
    if hasattr(response, 'choices'):
        message = response.choices[0].message
        if hasattr(message, 'content') and message.content:
            return message.content
    
    return None


def extract_formatted_message(result: Dict[str, Any]) -> Optional[str]:
    """
    Извлекает готовое текстовое сообщение из результата tool call.
    
    Поддерживает разные форматы для обратной совместимости:
    - "formatted_message" (стандартный формат)
    - "message" (устаревший формат)
    - "summary" (для некоторых tools)
    
    Args:
        result: Результат выполнения tool call
    
    Returns:
        Готовое текстовое сообщение или None
    """
    if isinstance(result, dict):
        # Приоритет: formatted_message > message > summary
        return result.get('formatted_message') or result.get('message') or result.get('summary')
    elif isinstance(result, str):
        # Если результат — строка (старый формат), возвращаем как есть
        return result
    
    return None

