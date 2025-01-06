import asyncio
import json
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langgraph_mcp.configuration import Configuration
from langgraph_mcp.routing_utils import generate_routing_instructions
from langgraph_mcp.retriever import make_retriever
from langgraph_mcp.state import BuilderState

async def collect_server_info(name: str, config: dict, server_infos: dict):
    """
    Collect information about a single MCP server.

    Parameters:
        name (str): The name of the server.
        config (dict): The server's configuration.
        server_infos (dict): Shared dictionary to store information about all servers.
    """
    server_params = StdioServerParameters(
        command=config["command"],
        args=config["args"],
        env=config.get("env")  # Use None to let default_environment be built
    )
    print(f"Starting session. (server: {name})")
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the connection
                await session.initialize()
                print(f"Session initialized: {name}")

                # Collect information from the server
                try:
                    tools = await session.list_tools()
                except Exception as e:
                    print(f"Failed to fetch tools from server '{name}': {e}")
                    tools = None

                try:
                    prompts = await session.list_prompts()
                except Exception as e:
                    print(f"Failed to fetch prompts from server '{name}': {e}")
                    prompts = None

                try:
                    resources = await session.list_resources()
                except Exception as e:
                    print(f"Failed to fetch resources from server '{name}': {e}")
                    resources = None

                # Store collected data in the shared dictionary
                server_infos[name] = {
                    "tools": tools,
                    "prompts": prompts,
                    "resources": resources,
                }
    except asyncio.CancelledError:
        print(f"Shutting down session. (server: {name})")
    except Exception as e:
        print(f"Exception: {e} (server: {name})")

async def build_router(state: BuilderState, *, config: RunnableConfig):
    status = "failure"
    configuration = Configuration.from_runnable_config(config)
    mcp_servers = configuration.mcp_server_config["mcpServers"]
    
    # Shared dictionary to collect information about all the MCP servers
    server_infos = {}

    # Create tasks for each server
    tasks = [
        asyncio.create_task(collect_server_info(name, server_config, server_infos))
        for name, server_config in mcp_servers.items()
    ]
    print("All server tasks created. Starting asyncio.gather...")
    try:
        # Wait for all tasks to complete
        await asyncio.gather(*tasks)

        # Build a router using the collected server information
        print("Building a router...")
        # Generate routing instructions from MCP server information (prompts, tools, resources)
        routing_instructions = generate_routing_instructions(server_infos)
        # Create documents from the routing instructions
        documents = [
            Document(page_content=content, metadata={"id": server_name})
            for server_name, content in routing_instructions.items()
        ]
        with make_retriever(config) as retriever:
            if configuration.retriever_provider == "milvus":
                retriever.add_documents(documents)
            else:
                await retriever.aadd_documents(documents)
        status = "success"
    except Exception as e:
        print(f"Exception in run: {e}")
    finally:
        print(f"MCP Servers Info: {json.dumps(routing_instructions, indent=2)}")
    
    return {"status": status}


builder = StateGraph(state_schema=BuilderState, config_schema=Configuration)
builder.add_node(build_router)
builder.add_edge("__start__", "build_router")
graph = builder.compile()
graph.name = "BuildRouterGraph"