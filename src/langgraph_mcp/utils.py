from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage
from typing import Dict, Any


def get_message_text(msg: AnyMessage) -> str:
    """Get the text content of a message.

    This function extracts the text content from various message formats.

    Args:
        msg (AnyMessage): The message object to extract text from.

    Returns:
        str: The extracted text content of the message.

    Examples:
        >>> from langchain_core.messages import HumanMessage
        >>> get_message_text(HumanMessage(content="Hello"))
        'Hello'
        >>> get_message_text(HumanMessage(content={"text": "World"}))
        'World'
        >>> get_message_text(HumanMessage(content=[{"text": "Hello"}, " ", {"text": "World"}]))
        'Hello World'
    """
    content = msg.content
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        return content.get("text", "")
    else:
        txts = [c if isinstance(c, str) else (c.get("text") or "") for c in content]
        return "".join(txts).strip()


def load_chat_model(fully_specified_name: str) -> BaseChatModel:
    """Load a chat model from a fully specified name.

    Args:
        fully_specified_name (str): String in the format 'provider/model'.
    """
    if "/" in fully_specified_name:
        provider, model = fully_specified_name.split("/", maxsplit=1)
    else:
        provider = ""
        model = fully_specified_name
    return init_chat_model(model, model_provider=provider)


def get_server_config(server_name: str, mcp_server_config: Dict[str, Any]) -> Dict[str, Any]:
    """Get server configuration for any MCP server type.
    
    This function handles both standard MCP servers (in mcpServers) and Smithery servers (in smithery).
    
    Args:
        server_name (str): Name of the server to get configuration for
        mcp_server_config (Dict[str, Any]): The MCP server configuration dictionary
        
    Returns:
        Dict[str, Any]: Server configuration for the specified server
        
    Raises:
        KeyError: If server_name is not found in either mcpServers or smithery sections
    """
    # Check if this is a Smithery server
    if server_name in mcp_server_config.get("smithery", {}):
        return mcp_server_config["smithery"][server_name]
    # Check if this is a standard MCP server
    elif server_name in mcp_server_config.get("mcpServers", {}):
        return mcp_server_config["mcpServers"][server_name]
    else:
        raise KeyError(f"Server '{server_name}' not found in either mcpServers or smithery configurations")
