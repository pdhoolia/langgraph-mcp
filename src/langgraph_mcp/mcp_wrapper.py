import os
from abc import ABC, abstractmethod
from typing import Any
from langchain_core.tools import ToolException
from mcp import ClientSession, ListPromptsResult, ListResourcesResult, ListToolsResult, StdioServerParameters, stdio_client
import mcp
from mcp.client.streamable_http import streamablehttp_client
import pydantic_core
import smithery


# Abstract base class for MCP session functions
class MCPSessionFunction(ABC):
    @abstractmethod
    async def __call__(self, server_name: str, session: ClientSession) -> Any:
        pass

class RoutingDescription(MCPSessionFunction):
    async def __call__(self, server_name: str, session: ClientSession) -> str:
        tools: ListToolsResult | None = None
        prompts: ListPromptsResult | None = None
        resources: ListResourcesResult | None = None
        content = ""
        try:
            tools = await session.list_tools()
            if tools:
                content += "Provides tools:\n"
                for tool in tools.tools:
                    content += f"- {tool.name}: {tool.description}\n"
                content += "---\n"
        except Exception as e:
            print(f"Failed to fetch tools from server '{server_name}': {e}")
        
        try:
            prompts = await session.list_prompts()
            if prompts:
                content += "Provides prompts:\n"
                for prompt in prompts.prompts:
                    content += f"- {prompt.name}: {prompt.description}\n"
                content += "---\n"
        except Exception as e:
            print(f"Failed to fetch prompts from server '{server_name}': {e}")

        try:
            resources = await session.list_resources()
            if resources:
                content += "Provides resources:\n"
                for resource in resources.resources:
                    content += f"- {resource.name}: {resource.description}\n"
                content += "---\n"
        except Exception as e:
            print(f"Failed to fetch resources from server '{server_name}': {e}")

        return server_name, content

class GetTools(MCPSessionFunction):
    async def __call__(self, server_name: str, session: ClientSession) -> list[dict[str, Any]]:
        tools = await session.list_tools()
        if tools is None:
            return []
        return [
            {
                'type': 'function',
                'function': {
                    'name': tool.name,
                    'description': tool.description or "",
                    'parameters': tool.inputSchema or {}
                }
            }
            for tool in tools.tools
        ]

class GetPrompts(MCPSessionFunction):
    async def __call__(self, server_name: str, session: ClientSession) -> dict[str, Any]:
        prompts = await session.list_prompts()
        if prompts is None:
            return {"prompts": []}
        return {
            "prompts": [
                {
                    "name": prompt.name,
                    "description": prompt.description or "",
                    "arguments": prompt.arguments or []
                }
                for prompt in prompts.prompts
            ]
        }

class RunTool(MCPSessionFunction):
    def __init__(self, tool_name: str, **kwargs):
        self.tool_name = tool_name
        self.kwargs = kwargs

    async def __call__(self, server_name: str, session: ClientSession) -> Any:
        result = await session.call_tool(self.tool_name, arguments=self.kwargs)
        content = pydantic_core.to_json(result.content).decode()
        if result.isError:
            raise ToolException(content)
        return content

async def apply(server_name: str, server_config: dict, fn: MCPSessionFunction) -> Any:
    """Apply a function to an MCP server session, handling both standard and Smithery servers.
    
    Args:
        server_name: Name of the server to connect to
        server_config: Configuration for the server
        fn: Function to apply to the server session
    """
    # Check if this is a Smithery server by looking for 'url' in config
    if 'url' in server_config:
        # Create Smithery URL with server endpoint and config
        env = {**os.environ, **(server_config.get("env") or {})}
        url = smithery.create_smithery_url(server_config['url'], env) + f"&api_key={env['SMITHERY_API_KEY']}"
        print(f"Starting Smithery session with (server: {server_name})")
        async with streamablehttp_client(url) as (read_stream, write_stream, _):
            async with mcp.ClientSession(read_stream, write_stream) as session:
                # Initialize the connection
                await session.initialize()
                return await fn(server_name, session)
    else:
        # Handle standard MCP server
        server_params = StdioServerParameters(
            command=server_config["command"],
            args=server_config["args"],
            env = {**os.environ, **(server_config.get("env") or {})}
        )
        print(f"Starting session with (server: {server_name})")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(server_name, session)
