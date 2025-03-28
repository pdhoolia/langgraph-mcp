"""Test for the planner-based assistant with prompts."""

import asyncio
import os
import json
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from langgraph_mcp.with_planner_n_prompts.graph import graph

# Load environment variables
load_dotenv()

async def test_assistant():
    """Test the assistant with a simple query."""
    # Load MCP server configuration
    mcp_server_config_path = os.environ.get("MCP_SERVER_CONFIG", "mcp-servers-config.json")
    with open(mcp_server_config_path, "r") as f:
        mcp_server_config = json.load(f)
    
    # Create the graph with configuration
    assistant = graph.with_config(
        {"configurable": {"mcp_server_config": mcp_server_config}}
    )
    
    # Test query
    messages = [
        HumanMessage(content="What's the weather like in New York today?"),
    ]
    
    # Enable streaming
    for chunk in await assistant.astream({"messages": messages}):
        if "messages" in chunk and chunk["messages"]:
            print(f"Response: {chunk['messages'][-1].content}")
        else:
            # Print other state updates
            state_update = {k: v for k, v in chunk.items() if k != "messages"}
            if state_update:
                print(f"State update: {state_update}")

if __name__ == "__main__":
    asyncio.run(test_assistant()) 