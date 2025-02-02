from datetime import datetime, timezone
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from langgraph_mcp import mcp_wrapper as mcp
from langgraph_mcp.state import InputState
from langgraph_mcp.utils import load_chat_model

from langgraph_mcp.with_planner.config import Configuration
from langgraph_mcp.with_planner.state import State, PlannerResult


CONTINUE_WITH_PLAN_TAG = "[::CONTINUE WITH PLAN::]"
IDK_TAG = "[::IDK::]"

async def planner(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    # get configurations
    configuration = Configuration.from_runnable_config(config)
    # build a chat prompt template with instructions for the plan evaluation task and messages in the memory
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", configuration.planner_system_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    # load the chat model configured for the planning task
    model = load_chat_model(configuration.planner_model)
    # let's get the current plan from the state
    current_plan = state.planner_result.plan if state.planner_result else []
    # let's build the experts list available for the planning task
    experts = configuration.build_experts_context()
    # let's build the final prompt with all the context and memory
    context = await prompt.ainvoke(
        {
            "messages": state.messages,
            "experts": experts,
            "plan": current_plan,
            "system_time": datetime.now(tz=timezone.utc).isoformat(),
        },
        config,
    )
    # lets convey the output structure desired and call the model
    response = await model.with_structured_output(PlannerResult).ainvoke(context, config)
    result = {"planner_result": response}
    # if the model asks for clarification, we'll add the clarification seeking message to the state as well
    if response.clarification:
        result["messages"] = [AIMessage(content=response.clarification)]
    # add planner result to state
    return result

def decide_planner_edge(state: State) -> str:
    if state.planner_result.plan:
        return "orchestrate"
    return END

async def orchestrate(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    # get configurations
    configuration = Configuration.from_runnable_config(config)
    # build a chat prompt template with instructions for orchestrating across expert tools
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", configuration.orchestrate_system_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    # load the chat model configured for the task of orchestrating across expert tools
    model = load_chat_model(configuration.orchestrate_model)
    # get the current plan from the state
    current_plan = state.planner_result.plan
    # get the current task from the plan
    current_task = state.planner_result.get_current_task()
    # build the final prompt with all the context and memory
    context = await prompt.ainvoke(
        {
            "messages": state.messages,
            "plan": current_plan,
            "task": current_task.task if current_task else "",
            "continue_with_plan_tag": CONTINUE_WITH_PLAN_TAG,
            "idk_tag": IDK_TAG,
            "system_time": datetime.now(tz=timezone.utc).isoformat(),
        },
        config,
    )
    # get the tools for the current expert using our MCP wrapper and bind them to the model
    if current_task:
        current_expert = current_task.expert
        mcp_servers = configuration.mcp_server_config["mcpServers"]
        server_config = mcp_servers[current_expert]
        tools = await mcp.apply(current_expert, server_config, mcp.GetTools())
        model = model.bind_tools(tools)
    # call the model
    response = await model.ainvoke(context, config)
    return {"messages": [response]}

def decide_orchestrate_edge(state: State) -> str:
    last_message = state.messages[-1]

    if last_message.model_dump().get('tool_calls'):
        return "call_tool"
    if CONTINUE_WITH_PLAN_TAG in last_message.content:
        return "planner"
    return END

async def call_tool(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    # Get the current task
    current_task = state.planner_result.get_current_task()

    # Fetch mcp server config
    configuration = Configuration.from_runnable_config(config)
    mcp_servers = configuration.mcp_server_config["mcpServers"]
    server_config = mcp_servers[current_task.expert]

    # Execute MCP server Tool
    tool_call = state.messages[-1].tool_calls[0]
    try :
        tool_output = await mcp.apply(
            current_task.expert, 
            server_config, 
            mcp.RunTool(tool_call['name'],**tool_call['args'])
        )
    except Exception as e:
        tool_output = f"Error: {e}"
    return {"messages": [ToolMessage(content=tool_output, tool_call_id=tool_call['id'])]}


builder = StateGraph(State, input=InputState, config_schema=Configuration)

builder.add_node(planner)
builder.add_node(orchestrate)
builder.add_node(call_tool)

builder.add_edge(START, "planner")
builder.add_conditional_edges(
    source="planner",
    path=decide_planner_edge,
    path_map={
        "orchestrate": "orchestrate",
        END: END,
    }
)
builder.add_conditional_edges(
    source="orchestrate",
    path=decide_orchestrate_edge,
    path_map={
        "call_tool": "call_tool",
        "planner": "planner",
        END: END,
    }
)
builder.add_edge("call_tool", "orchestrate")
graph = builder.compile(
    interrupt_before=[],  # if you want to update the state before calling the tools
    interrupt_after=[],
)
graph.name = "AssistantGraphWithPlanner"