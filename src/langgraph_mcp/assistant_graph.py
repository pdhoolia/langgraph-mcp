from datetime import datetime, timezone
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel
from typing import cast

from langgraph_mcp.configuration import Configuration
from langgraph_mcp import mcp_wrapper as mcp
from langgraph_mcp.retriever import make_retriever
from langgraph_mcp.state import InputState, State
from langgraph_mcp.utils import get_message_text, load_chat_model, format_docs


IDK_RESPONSE = "Unable to assist with this query."  # Default response where the current MCP Server can't help

##################  MCP Server Router: Sub-graph Components  ###################

class SearchQuery(BaseModel):
    """Search the indexed documents for a query."""

    query: str

async def generate_routing_query(
    state: State, *, config: RunnableConfig
) -> dict[str, list[str]]:
    """Generate a routing query based on the current state and configuration.

    This function analyzes the messages in the state and generates an appropriate
    search query. For the first message, it uses the user's input directly.
    For subsequent messages, it uses a language model to generate a refined query.

    Args:
        state (State): The current state containing messages and other information.
        config (RunnableConfig | None, optional): Configuration for the query generation process.

    Returns:
        dict[str, list[str]]: A dictionary with a 'queries' key containing a list of generated queries.

    Behavior:
        - If there's only one message (first user input), it uses that as the query.
        - For subsequent messages, it uses a language model to generate a refined query.
        - The function uses the configuration to set up the prompt and model for query generation.
    """
    messages = state.messages
    if len(messages) == 1:
        # It's the first user question. We will use the input directly to search.
        human_input = get_message_text(messages[-1])
        return {"queries": [human_input]}
    else:
        configuration = Configuration.from_runnable_config(config)
        # Feel free to customize the prompt, model, and other logic!
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", configuration.routing_query_system_prompt),
                ("placeholder", "{messages}"),
            ]
        )
        model = load_chat_model(configuration.routing_query_model).with_structured_output(
            SearchQuery
        )

        message_value = await prompt.ainvoke(
            {
                "messages": state.messages,
                "queries": "\n- ".join(state.queries),
                "system_time": datetime.now(tz=timezone.utc).isoformat(),
            },
            config,
        )
        generated = cast(SearchQuery, await model.ainvoke(message_value, config))
        return {
            "queries": [generated.query],
        }

async def retrieve(
    state: State, *, config: RunnableConfig
) -> dict[str, list[Document]]:
    """Retrieve documents based on the latest query in the state.

    This function takes the current state and configuration, uses the latest query
    from the state to retrieve relevant documents using the retriever, and returns
    the retrieved documents.

    Args:
        state (State): The current state containing queries and the retriever.
        config (RunnableConfig | None, optional): Configuration for the retrieval process.

    Returns:
        dict[str, list[Document]]: A dictionary with a single key "retrieved_docs"
        containing a list of retrieved Document objects.
    """
    with make_retriever(config) as retriever:
        response = await retriever.ainvoke(state.queries[-1], config)
        return {"retrieved_docs": response}

async def route(
    state: State, *, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """Call the LLM powering our "agent"."""
    configuration = Configuration.from_runnable_config(config)
    # Feel free to customize the prompt, model, and other logic!
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", configuration.routing_response_system_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    model = load_chat_model(configuration.routing_response_model)

    retrieved_docs = format_docs(state.retrieved_docs)
    message_value = await prompt.ainvoke(
        {
            "messages": state.messages,
            "retrieved_docs": retrieved_docs,
            "system_time": datetime.now(tz=timezone.utc).isoformat(),
        },
        config,
    )
    response = await model.ainvoke(message_value, config)
    return {"current_mcp_server": response.content}


##################  MCP Server Router: Sub-graph Components  ###################

async def mcp_orchestrator(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    """ Orchestrates MCP server processing. """
    # Fetch the current MCP server from state
    server_name = state.current_mcp_server

    # Fetch mcp server config
    configuration = Configuration.from_runnable_config(config)
    mcp_servers = configuration.mcp_server_config["mcpServers"]
    server_config = mcp_servers[server_name]

    # Fetch tools from the MCP server
    tools = await mcp.apply(server_name, server_config, mcp.GetTools())

    # Prepare the LLM
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", configuration.mcp_orchestrator_system_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    model = load_chat_model(configuration.mcp_orchestrator_model)
    message_value = await prompt.ainvoke(
        {
            "messages": state.messages,
            "idk_response": IDK_RESPONSE,
            "system_time": datetime.now(tz=timezone.utc).isoformat(),
        },
        config,
    )
    
    # Bind tools to model and invoke
    response = await model.bind_tools(tools).ainvoke(message_value, config)

    if response.content == IDK_RESPONSE:
        # If the response is IDK_RESPONSE, we will generate a new routing query.
        return {"current_mcp_server": None}

    return {"messages": [response]}


async def mcp_tool_call(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    """ Call the MCP server tool."""
    # Fetch the current MCP server from state
    server_name = state.current_mcp_server

    # Fetch mcp server config
    configuration = Configuration.from_runnable_config(config)
    mcp_servers = configuration.mcp_server_config["mcpServers"]
    server_config = mcp_servers[server_name]

    # Execute MCP server Tool
    tool_call = state.messages[-1].tool_calls[0]
    tool_output = await mcp.apply(server_name, server_config, mcp.RunTool(tool_call['name'], **tool_call['args']))
    return {"messages": [ToolMessage(content=tool_output, tool_call_id=tool_call['id'])]}

def route_tools(state: State) -> str:
    """
    Route to the mcp_tool_call if last message has tool calls.
    Otherwise, route to the END.
    """
    if state.messages[-1].__class__ == HumanMessage:
        return "generate_routing_query"
    if state.messages[-1].tool_calls:
        return "mcp_tool_call"
    return END


#############################  Subgraph decider  ###############################
def decide_subgraph(state: State) -> str:
    """
    Route to MCP Server Router sub-graph if there is no state.current_mcp_server
    else route to MCP Server processing sub-graph.
    """
    if not state.current_mcp_server:
        return "generate_routing_query"
    return "mcp_orchestrator"


##################################  Wiring  ####################################

builder = StateGraph(State, input=InputState, config_schema=Configuration)

builder.add_node(generate_routing_query)
builder.add_node(retrieve)
builder.add_node(route)
builder.add_node(mcp_orchestrator)
builder.add_node(mcp_tool_call)

builder.add_conditional_edges(
    START,
    decide_subgraph,
    {
        "generate_routing_query": "generate_routing_query",
        "mcp_orchestrator": "mcp_orchestrator",
    }
)
builder.add_edge("generate_routing_query", "retrieve")
builder.add_edge("retrieve", "route")
builder.add_edge("route", "mcp_orchestrator")
builder.add_conditional_edges(
    "mcp_orchestrator",
    route_tools,
    {
        "mcp_tool_call": "mcp_tool_call",
        "generate_routing_query": "generate_routing_query",
        END: END,
    }
)
builder.add_edge("mcp_tool_call", "mcp_orchestrator")
graph = builder.compile(
    interrupt_before=[],  # if you want to update the state before calling the tools
    interrupt_after=[],
)
graph.name = "AssistantGraph"