from datetime import datetime, timezone
import json
from typing import Literal, List, Any, Optional, Union

from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.graph import StateGraph, START, END

from langgraph_mcp import mcp_wrapper as mcp
from langgraph_mcp.state import InputState
from langgraph_mcp.utils import load_chat_model, get_server_config

# Import from with_planner
from langgraph_mcp.with_planner.graph import (
    IDK_TAG,
    advance_to_next_task as base_advance_to_next_task,
    assess_task_completion,
    call_tool,
    decide_orchestrate_tools_edge,
    decide_task_assessment_edge,
    generate_response as base_generate_response,
    orchestrate_tools as base_orchestrate_tools,
    planner
)

from langgraph_mcp.with_planner_n_prompts.config import Configuration
from langgraph_mcp.with_planner.state import PlannerResult
from langgraph_mcp.with_planner_n_prompts.state import State, ExpertPrompt


def decide_planner_edge(state: State) -> str:
    """Decide where to go after planning stage."""
    if state.planner_result.plan:
        return "discover_expert_prompts"
    return END


async def discover_expert_prompts(state: State, *, config: RunnableConfig) -> dict[str, Any]:
    """Discover and evaluate prompts available from the expert MCP server."""
    # Get configurations
    configuration = Configuration.from_runnable_config(config)
    
    # Get the current task from the state
    current_task = state.planner_result.get_current_task()
    if not current_task:
        return {"expert_prompts": []}
    
    # Fetch MCP server config for the current expert
    try:
        server_config = get_server_config(current_task.expert, configuration.mcp_server_config)
        
        # Fetch available prompts from the MCP server
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
    """Decide what to do with available prompts."""
    # If a prompt was automatically selected
    if state.selected_prompt:
        return "orchestrate"
    
    # If there are expert prompts worth suggesting
    configuration = Configuration()
    if state.expert_prompts and any(p.match_confidence >= configuration.prompt_suggestion_threshold for p in state.expert_prompts):
        return "ask_user"
    
    # If no suitable prompts found or prompts below threshold
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
    """Process the user's choice of prompt."""
    # Get the most recent message (user's response)
    if not state.messages or not isinstance(state.messages[-1], HumanMessage):
        return {"selected_prompt": None}
    
    user_response = state.messages[-1].content.strip().lower()
    
    # Check if the user chose "none"
    if user_response == "none":
        return {"selected_prompt": None}
    
    # Try to parse a number choice
    try:
        # Filter prompts by the suggestion threshold
        configuration = Configuration()
        relevant_prompts = [p for p in state.expert_prompts 
                          if p.match_confidence >= configuration.prompt_suggestion_threshold]
        
        # Parse the user's choice
        choice = int(user_response.split()[0])
        
        # Validate choice is in range
        if 1 <= choice <= len(relevant_prompts):
            return {"selected_prompt": relevant_prompts[choice - 1]}
    except (ValueError, IndexError):
        pass
    
    # If we couldn't parse a valid choice, return None
    return {"selected_prompt": None}


async def orchestrate_tools(state: State, *, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
    """Orchestrate tools based on the current task and selected prompt."""
    # Format selected prompt information
    selected_prompt = state.selected_prompt
    special_instructions = json.dumps({
        "name": selected_prompt.get("name"),
        "description": selected_prompt.get("description"),
        "arguments": selected_prompt.get("arguments")
    }) if selected_prompt else None

    # Reuse the base implementation
    return await base_orchestrate_tools(state, config=config, special_instructions=special_instructions)


def advance_to_next_task(state: State) -> dict[str, Union[PlannerResult, bool, List, None]]:
    """Advance to the next task in the plan."""
    # Reuse the base implementation
    result = base_advance_to_next_task(state)
    result["expert_prompts"] = []
    result["selected_prompt"] = None

    return result


def decide_next_task_edge(state: State) -> Literal["discover_expert_prompts", "generate_response"]:
    """Decide whether there are more tasks or the plan is complete."""
    if (state.planner_result and 
        state.planner_result.next_task < len(state.planner_result.plan)):
        return "discover_expert_prompts"
    return "generate_response"


async def generate_response(state: State, *, config: RunnableConfig) -> dict[str, Union[list[BaseMessage], PlannerResult]]:
    """Generate a final AI response at the end of plan execution."""
    # Reuse the base implementation
    return await base_generate_response(state, config=config)


# Define the state graph
builder = StateGraph(State, input=InputState, config_schema=Configuration)

# Add all the nodes
builder.add_node("planner", planner)
builder.add_node("discover_expert_prompts", discover_expert_prompts)
builder.add_node("select_prompt", select_prompt)
builder.add_node("ask_user_for_prompt", ask_user_for_prompt)
builder.add_node("process_user_prompt_choice", process_user_prompt_choice)
builder.add_node("orchestrate_tools", orchestrate_tools)
builder.add_node("call_tool", call_tool)
builder.add_node("assess_task_completion", assess_task_completion)
builder.add_node("advance_to_next_task", advance_to_next_task)
builder.add_node("generate_response", generate_response)

# Add the edges
builder.add_edge(START, "planner")
builder.add_conditional_edges(
    "planner",
    decide_planner_edge,
    {
        "discover_expert_prompts": "discover_expert_prompts",
        END: END,
    }
)
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
        "discover_expert_prompts": "discover_expert_prompts",
        "generate_response": "generate_response",
    }
)
builder.add_edge("generate_response", END)

# Compile the graph
graph = builder.compile()
graph.name = "AssistantGraphWithPlannerAndPrompts" 