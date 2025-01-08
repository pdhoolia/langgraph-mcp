from typing import Any
from langchain_core.tools import ToolException
from mcp import ClientSession, ListPromptsResult, ListResourcesResult, ListToolsResult, StdioServerParameters, stdio_client
import pydantic_core


class MCPServerWrapper:
    def __init__(self, server_name: str, session: ClientSession):
        self.server_name = server_name
        self.session = session
        self.tools: ListToolsResult | None = None
        self.prompts: ListPromptsResult | None = None
        self.resources: ListResourcesResult | None = None
        print(f"Constructed MCPServerWrapper for server '{server_name}'")

    async def __aenter__(self):
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    async def initialize_session(self) -> None:
        await self.session.initialize()
        try:
            self.tools = await self.session.list_tools()
        except Exception as e:
            print(f"Failed to fetch tools from server '{self.server_name}': {e}")
            self.tools = None
        
        try:
            self.prompts = await self.session.list_prompts()
        except Exception as e:
            print(f"Failed to fetch prompts from server '{self.server_name}': {e}")
            self.prompts = None

        try:
            self.resources = await self.session.list_resources()
        except Exception as e:
            print(f"Failed to fetch resources from server '{self.server_name}': {e}")
            self.resources = None

    def get_tools(self) -> list[dict[str, Any]]:
        if self.tools is None:
            raise RuntimeError("""
                Either missing a call to MCPServerWrapper.initialize_session()
                Or the server failed to fetch tools."""
            )
        return [
            {
                'type': 'function',
                'function': {
                    'name': tool.name,
                    'description': tool.description or "",
                    'parameters': tool.inputSchema or {}
                }
            }
            for tool in self.tools.tools
        ]
    
    async def run_tool(self, tool_name: str, **kwargs) -> Any:
        result = await self.session.call_tool(tool_name, arguments=kwargs)
        content = pydantic_core.to_json(result.content).decode()
        if result.isError:
            raise ToolException(content)
        return content
    
    def generate_routing_description(self) -> str:
        content = ""
        if self.tools:
            content += "Provides tools:\n"
            for tool in self.tools.tools:
                content += f"- {tool.name}: {tool.description}\n"
            content += "---\n"
        if self.prompts:
            content += "Provides prompts:\n"
            for prompt in self.prompts.prompts:
                content += f"- {prompt.name}: {prompt.description}\n"
            content += "---\n"
        if self.resources:
            content += "Provides resources:\n"
            for resource in self.resources.resources:
                content += f"- {resource.name}: {resource.description}\n"
            content += "---\n"
        return content
    
    @classmethod
    async def create(cls, server_name: str, server_config: dict) -> "MCPServerWrapper":
        """
        Factory method to create and initialize an MCPServerWrapper instance.

        Parameters:
            server_name (str): Name of the server.
            server_config (dict): Configuration for the server.

        Returns:
            MCPServerWrapper: The initialized MCPServerWrapper instance.
        """
        server_params = StdioServerParameters(
            command=server_config["command"],
            args=server_config["args"],
            env=server_config.get("env")  # Use None to let default_environment be built
        )
        print(f"Starting session. (server: {server_name})")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                instance = cls(server_name, session)
                await instance.initialize_session()
                return instance