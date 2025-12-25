# Tools for OpenAI Function Calling
from .branch_tools import (
    get_branches, 
    load_branches_data, 
    BRANCHES_TOOL_DEFINITION,
    get_branches_tool_for_responses_api,
)
from .price_tools import (
    get_prices,
    load_prices_data,
    PRICES_TOOL_DEFINITION,
    get_prices_tool_for_responses_api,
)
from .group_tools import (
    search_groups,
    load_groups_data,
    GROUPS_TOOL_DEFINITION,
    get_groups_tool_for_responses_api,
)
from .pyrus_tools import (
    create_pyrus_task,
    PYRUS_TOOL_DEFINITION,
    get_pyrus_tool_for_responses_api,
    get_available_branches_for_pyrus,
)
from .client_tools import (
    search_client_by_name,
    find_clients_by_phone,
    get_client_balance,
    get_recent_transactions,
    calculate_next_month_payment,
    get_verified_client_data,
    normalize_phone,
    TOOLS as CLIENT_TOOLS_DEFINITIONS,
    get_search_client_tool_for_responses_api,
    get_find_by_phone_tool_for_responses_api,
    get_client_balance_tool_for_responses_api,
    get_recent_transactions_tool_for_responses_api,
    get_calculate_payment_tool_for_responses_api,
)
from .verification_tools import (
    reset_verification,
    get_all_verifications,
    check_verification,
    save_verification,
    get_check_verification_tool_for_responses_api,
    get_save_verification_tool_for_responses_api,
)
from .conversation_tools import (
    set_conversation_topic,
    get_conversation_topic,
    clear_conversation_topic,
    get_all_topics,
    set_current_user_id,
    get_conversation_topic_tool_for_responses_api,
    CONVERSATION_TOPIC_FUNCTION_NAME,
    _conversation_topics as conversation_topics_storage,
)
from .tool_executor import (
    get_tools_for_api,
    execute_tool_call,
    parse_tool_calls_from_response,
    format_tool_results_for_api,
    has_tool_calls,
    get_text_from_response,
    extract_formatted_message,
    AVAILABLE_TOOLS,
    TOOL_FUNCTIONS,
)

__all__ = [
    # Branch tools
    "get_branches",
    "load_branches_data", 
    "BRANCHES_TOOL_DEFINITION",
    "get_branches_tool_for_responses_api",
    # Price tools
    "get_prices",
    "load_prices_data",
    "PRICES_TOOL_DEFINITION",
    "get_prices_tool_for_responses_api",
    # Group tools
    "search_groups",
    "load_groups_data",
    "GROUPS_TOOL_DEFINITION",
    "get_groups_tool_for_responses_api",
    # Pyrus tools
    "create_pyrus_task",
    "PYRUS_TOOL_DEFINITION",
    "get_pyrus_tool_for_responses_api",
    "get_available_branches_for_pyrus",
    # Client tools
    "search_client_by_name",
    "find_clients_by_phone",
    "get_verified_client_data",
    "normalize_phone",
    "get_client_balance",
    "get_recent_transactions",
    "calculate_next_month_payment",
    "CLIENT_TOOLS_DEFINITIONS",
    "get_search_client_tool_for_responses_api",
    "get_find_by_phone_tool_for_responses_api",
    "get_client_balance_tool_for_responses_api",
    "get_recent_transactions_tool_for_responses_api",
    "get_calculate_payment_tool_for_responses_api",
    # Verification tools
    "reset_verification",
    "get_all_verifications",
    "check_verification",
    "save_verification",
    "get_check_verification_tool_for_responses_api",
    "get_save_verification_tool_for_responses_api",
    # Conversation context tools
    "set_conversation_topic",
    "get_conversation_topic",
    "clear_conversation_topic",
    "get_all_topics",
    "set_current_user_id",
    "get_conversation_topic_tool_for_responses_api",
    "CONVERSATION_TOPIC_FUNCTION_NAME",
    "conversation_topics_storage",
    # Tool executor
    "get_tools_for_api",
    "execute_tool_call",
    "parse_tool_calls_from_response",
    "format_tool_results_for_api",
    "has_tool_calls",
    "get_text_from_response",
    "extract_formatted_message",
    "AVAILABLE_TOOLS",
    "TOOL_FUNCTIONS",
]

