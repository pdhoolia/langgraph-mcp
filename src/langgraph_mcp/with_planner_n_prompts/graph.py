from datetime import datetime, timezone
import json
from typing import Literal, List, Dict, Any, Optional, Union

from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.graph import StateGraph, START, END

from langgraph_mcp import mcp_wrapper as mcp
from langgraph_mcp.state import InputState
from langgraph_mcp.utils import load_chat_model

from langgraph_mcp.with_planner_n_prompts.config import Configuration
from langgraph_mcp.with_planner_n_prompts.state import State, PlannerResult, ExpertPrompt


# Tags for special message responses
IDK_TAG = "[::IDK::]"


class TaskAssessmentResult(BaseModel):
    """Output schema for task assessment LLM evaluation."""
    
    is_completed: bool = Field(description="Boolean indicating if the task is complete")
    explanation: str = Field(description="Explanation for the assessment")
    confidence: float = Field(description="Confidence score between 0 and 1")


async def planner(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    """Generate a plan for the conversation based on available experts."""
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
    """Decide where to go after planning stage."""
    if state.planner_result.plan:
        return "select_expert"
    return END


async def select_expert(state: State, *, config: RunnableConfig) -> dict[str, Any]:
    """Select the current expert based on the active task in the plan."""
    # Reset task completion status and expert prompts when selecting a new expert
    result = {
        "task_completed": False,
        "expert_prompts": [],
        "selected_prompt": None
    }
    
    # Check if we have a valid plan with a current task
    if not state.planner_result or not state.planner_result.get_current_task():
        return result
    
    # Get the current task from the plan
    current_task = state.planner_result.get_current_task()
    
    # Return the selected expert
    return result


async def discover_expert_prompts(state: State, *, config: RunnableConfig) -> dict[str, Any]:
    """Discover and evaluate prompts available from the expert MCP server."""
    # Get configurations
    configuration = Configuration.from_runnable_config(config)
    
    # Get the current task from the state
    current_task = state.planner_result.get_current_task()
    if not current_task:
        return {"expert_prompts": []}
    
    # Fetch MCP server config for the current expert
    mcp_servers = configuration.mcp_server_config["mcpServers"]
    server_config = mcp_servers[current_task.expert]
    
    # Fetch available prompts from the MCP server
    try:
        prompts_response = await mcp.apply(
            current_task.expert, 
            server_config, 
            mcp.GetPrompts()
        )
        
        # If no prompts are available, return empty list
        if not prompts_response or not prompts_response.get("prompts"):
            return {"expert_prompts": []}
        
        # Build the prompt for the LLM to evaluate prompt relevance
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", configuration.prompt_discovery_system_prompt),
                ("placeholder", "{messages}"),
            ]
        )
        
        # Load the chat model for prompt discovery
        model = load_chat_model(configuration.prompt_discovery_model)
        
        # Get the context
        context = await prompt.ainvoke(
            {
                "task": current_task.task,
                "prompts": json.dumps(prompts_response["prompts"]),
                "messages": state.messages[-5:],  # Pass the 5 most recent messages for context
                "system_time": datetime.now(tz=timezone.utc).isoformat(),
            },
            config,
        )
        
        # Call the model to evaluate prompt relevance
        output_parser = PydanticOutputParser(pydantic_object=List[ExpertPrompt])
        result = await model.with_structured_output(List[ExpertPrompt]).ainvoke(context, config)
        
        # Sort expert prompts by confidence score (descending)
        sorted_prompts = sorted(result, key=lambda x: x.match_confidence, reverse=True)
        
        return {"expert_prompts": sorted_prompts}
        
    except Exception as e:
        print(f"Error fetching prompts from {current_task.expert}: {e}")
        return {"expert_prompts": []}


def select_prompt(state: State) -> dict[str, Optional[ExpertPrompt]]:
    """Automatically select a prompt if confidence is above threshold."""
    # If no expert prompts were found, return None
    if not state.expert_prompts:
        return {"selected_prompt": None}
    
    # Use default configuration values
    configuration = Configuration()
    
    # Find the prompt with the highest confidence
    best_prompt = max(state.expert_prompts, key=lambda p: p.match_confidence)
    
    # If confidence is above threshold, automatically select it
    if best_prompt.match_confidence >= configuration.prompt_confidence_threshold:
        return {"selected_prompt": best_prompt}
    
    # Otherwise, return None (will be handled in decide_prompt_edge)
    return {"selected_prompt": None}


def decide_prompt_edge(state: State) -> Literal["ask_user", "orchestrate", "no_prompts"]:
    """Decide whether to ask user for prompt selection or proceed to orchestration."""
    # Use default configuration values
    configuration = Configuration()
    
    # If a prompt is already selected (high confidence), go directly to orchestrate
    if state.selected_prompt:
        return "orchestrate"
    
    # If we have prompts above the suggestion threshold, ask user to choose
    if any(p.match_confidence >= configuration.prompt_suggestion_threshold for p in state.expert_prompts):
        return "ask_user"
    
    # If no suitable prompts, proceed without prompt selection
    return "no_prompts"


async def ask_user_for_prompt(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    """Ask the user to choose from relevant prompts."""
    # Filter prompts by the suggestion threshold
    configuration = Configuration.from_runnable_config(config)
    relevant_prompts = [p for p in state.expert_prompts 
                       if p.match_confidence >= configuration.prompt_suggestion_threshold]
    
    # Prepare message content with prompt options
    content = "I found a few specialized prompt templates that might help with your task.\n\nPlease choose one by replying with its number:\n\n"
    
    for i, prompt in enumerate(relevant_prompts, 1):
        content += f"{i}. {prompt.name}: {prompt.description} (confidence: {prompt.match_confidence:.2f})\n"
    
    content += "\nOr reply 'none' if you'd prefer not to use any of these."
    
    # Return message asking user to select
    return {"messages": [AIMessage(content=content)]}


def process_user_prompt_choice(state: State) -> dict[str, Optional[ExpertPrompt]]:
    """Process the user's prompt selection choice."""
    # Get the user's response (should be the last message)
    if not state.messages or not isinstance(state.messages[-1], HumanMessage):
        return {"selected_prompt": None}
    
    user_response = state.messages[-1].content.strip().lower()
    
    # Use default configuration values
    configuration = Configuration()
    
    # Filter prompts by the suggestion threshold
    relevant_prompts = [p for p in state.expert_prompts 
                       if p.match_confidence >= configuration.prompt_suggestion_threshold]
    
    # If user said "none", don't select any prompt
    if user_response == "none":
        return {"selected_prompt": None}
    
    # Try to parse the user's choice as a number
    try:
        choice = int(user_response.split()[0])
        if 1 <= choice <= len(relevant_prompts):
            return {"selected_prompt": relevant_prompts[choice - 1]}
    except:
        pass
    
    # If we couldn't parse the choice or it was invalid, don't select any prompt
    return {"selected_prompt": None}


async def orchestrate_tools(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    """Orchestrate expert tools using the selected prompt and handle tool selection and execution."""
    # Get configurations
    configuration = Configuration.from_runnable_config(config)
    
    # Build a chat prompt template for orchestration
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", configuration.orchestrate_system_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    
    # Load the chat model for orchestration
    model = load_chat_model(configuration.orchestrate_model)
    
    # Get the current plan and task
    current_plan = state.planner_result.plan
    current_task = state.planner_result.get_current_task()
    
    # Prepare selected prompt info if available
    selected_prompt_json = "None" 
    if state.selected_prompt:
        selected_prompt_json = json.dumps({
            "name": state.selected_prompt.name,
            "description": state.selected_prompt.description,
            "arguments": state.selected_prompt.arguments
        })
    
    # Build the final prompt with all context
    context = await prompt.ainvoke(
        {
            "messages": state.messages,
            "plan": current_plan,
            "task": current_task.task if current_task else "",
            "selected_prompt": selected_prompt_json,
            "idk_tag": IDK_TAG,
            "system_time": datetime.now(tz=timezone.utc).isoformat(),
        },
        config,
    )
    
    # Get the tools for the current expert and bind them to the model
    if current_task:
        current_expert = current_task.expert
        mcp_servers = configuration.mcp_server_config["mcpServers"]
        server_config = mcp_servers[current_expert]
        tools = await mcp.apply(current_expert, server_config, mcp.GetTools())
        model = model.bind_tools(tools)
    
    # Call the model
    response = await model.ainvoke(context, config)
    return {"messages": [response]}


def decide_orchestrate_tools_edge(state: State) -> Literal["call_tool", "assess_task", "end"]:
    """Decide the next step after orchestration."""
    last_message = state.messages[-1]
    
    # If the last message contains tool calls, execute them
    if last_message.model_dump().get('tool_calls'):
        return "call_tool"
    
    # If the message indicates expert doesn't know how to proceed, end the flow
    if IDK_TAG in last_message.content:
        return "end"
        
    # If the message is asking for human input, end the current flow
    if "I need more information from you" in last_message.content:
        return "end"
    
    # Otherwise, assess if the current task is complete
    return "assess_task"


async def call_tool(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    """Execute a tool call on the MCP server."""
    # Get the current task
    current_task = state.planner_result.get_current_task()
    if not current_task:
        return {"messages": [AIMessage(content="Error: No current task available for tool execution.")]}

    # Fetch MCP server config
    configuration = Configuration.from_runnable_config(config)
    mcp_servers = configuration.mcp_server_config["mcpServers"]
    server_config = mcp_servers[current_task.expert]

    # Execute MCP server Tool
    tool_call = state.messages[-1].tool_calls[0]
    try:
        tool_output = await mcp.apply(
            current_task.expert, 
            server_config, 
            mcp.RunTool(tool_call['name'], **tool_call['args'])
        )
    except Exception as e:
        tool_output = f"Error: {e}"
        
    return {"messages": [ToolMessage(content=tool_output, tool_call_id=tool_call['id'])]}


async def assess_task_completion(state: State, *, config: RunnableConfig) -> dict[str, bool]:
    """Assess whether the current task has been completed."""
    # Get configurations
    configuration = Configuration.from_runnable_config(config)
    
    # Get the current task
    current_task = state.planner_result.get_current_task()
    if not current_task:
        return {"task_completed": True}  # If no task, consider it completed
    
    # Build a chat prompt for task assessment
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", configuration.task_assessment_system_prompt),
            ("placeholder", "{recent_messages}"),
        ]
    )
    
    # Load the chat model for task assessment
    model = load_chat_model(configuration.task_assessment_model)
    
    # Get recent conversation (last 5 messages)
    recent_messages = state.messages[-5:] if len(state.messages) >= 5 else state.messages
    
    # Build the context
    context = await prompt.ainvoke(
        {
            "task": current_task.task,
            "recent_messages": recent_messages,
            "system_time": datetime.now(tz=timezone.utc).isoformat(),
        },
        config,
    )
    
    # Call the model with the structured output parser
    result = await model.with_structured_output(TaskAssessmentResult).ainvoke(context, config)
    
    # Return the task completion status
    return {"task_completed": result.is_completed and result.confidence >= 0.7}


def decide_task_assessment_edge(state: State) -> Literal["next_task", "orchestrate_tools"]:
    """Decide whether to move to the next task or continue with the current one."""
    if state.task_completed:
        return "next_task"
    return "orchestrate_tools"


def advance_to_next_task(state: State) -> dict[str, Union[PlannerResult, bool, List, None]]:
    """Advance to the next task in the plan."""
    if not state.planner_result:
        return {}
        
    # Create a copy of the current planner result
    planner_result = state.planner_result.model_copy()
    
    # Advance to the next task
    planner_result.next_task += 1
    
    # Reset task-related state
    result = {
        "planner_result": planner_result,
        "task_completed": False,
        "expert_prompts": [],
        "selected_prompt": None
    }
    
    return result


def decide_next_task_edge(state: State) -> Literal["select_expert", "end"]:
    """Decide whether there are more tasks or the plan is complete."""
    if (state.planner_result and 
        state.planner_result.next_task < len(state.planner_result.plan)):
        return "select_expert"
    return "end"


# Define the state graph
builder = StateGraph(State, input=InputState, config_schema=Configuration)

# Add all the nodes
builder.add_node("planner", planner)
builder.add_node("select_expert", select_expert)
builder.add_node("discover_expert_prompts", discover_expert_prompts)
builder.add_node("select_prompt", select_prompt)
builder.add_node("ask_user_for_prompt", ask_user_for_prompt)
builder.add_node("process_user_prompt_choice", process_user_prompt_choice)
builder.add_node("orchestrate_tools", orchestrate_tools)
builder.add_node("call_tool", call_tool)
builder.add_node("assess_task_completion", assess_task_completion)
builder.add_node("advance_to_next_task", advance_to_next_task)

# Add the edges
builder.add_edge(START, "planner")
builder.add_conditional_edges(
    "planner",
    decide_planner_edge,
    {
        "select_expert": "select_expert",
        END: END,
    }
)
builder.add_edge("select_expert", "discover_expert_prompts")
builder.add_edge("discover_expert_prompts", "select_prompt")
builder.add_conditional_edges(
    "select_prompt",
    decide_prompt_edge,
    {
        "ask_user": "ask_user_for_prompt",
        "orchestrate": "orchestrate_tools",
        "no_prompts": "orchestrate_tools",
    }
)
builder.add_edge("ask_user_for_prompt", "process_user_prompt_choice")
builder.add_edge("process_user_prompt_choice", "orchestrate_tools")
builder.add_conditional_edges(
    "orchestrate_tools",
    decide_orchestrate_tools_edge,
    {
        "call_tool": "call_tool",
        "assess_task": "assess_task_completion",
        "end": END,
    }
)
builder.add_edge("call_tool", "assess_task_completion")
builder.add_conditional_edges(
    "assess_task_completion",
    decide_task_assessment_edge,
    {
        "next_task": "advance_to_next_task",
        "orchestrate_tools": "orchestrate_tools",
    }
)
builder.add_conditional_edges(
    "advance_to_next_task",
    decide_next_task_edge,
    {
        "select_expert": "select_expert",
        "end": END,
    }
)

# Compile the graph
graph = builder.compile()
graph.name = "AssistantGraphWithPlannerAndPrompts" 