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

logger = logging.getLogger(__name__)

# --- Регистрация всех доступных tools ---

# Для Chat Completions API
AVAILABLE_TOOLS_CHAT: List[Dict[str, Any]] = [
    BRANCHES_TOOL_DEFINITION,
    PRICES_TOOL_DEFINITION,
    GROUPS_TOOL_DEFINITION,
    PYRUS_TOOL_DEFINITION,
]

# Маппинг имён функций на реальные функции
TOOL_FUNCTIONS: Dict[str, Callable] = {
    "get_branches": get_branches,
    "get_prices": get_prices,
    "search_groups": search_groups,
    "create_pyrus_task": create_pyrus_task,
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
        ]


# Алиас для обратной совместимости
AVAILABLE_TOOLS = AVAILABLE_TOOLS_CHAT


def execute_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполняет вызов функции по имени.
    
    Args:
        tool_name: Имя функции (например "get_branches")
        arguments: Аргументы функции
    
    Returns:
        Результат выполнения функции
    """
    logger.info(f"Выполнение tool call: {tool_name} с аргументами: {arguments}")
    
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
    
    Returns:
        Список словарей с tool calls: [{"id": ..., "name": ..., "arguments": {...}}]
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
                    logger.error(f"Ошибка парсинга аргументов tool call: {e}")
    
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
                    logger.error(f"Ошибка парсинга аргументов tool call: {e}")
    
    return tool_calls


def format_tool_results_for_api(
    tool_calls: List[Dict[str, Any]], 
    results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Форматирует результаты выполнения tools для отправки обратно в API.
    
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

