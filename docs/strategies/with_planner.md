# Strategy: With Planner

This strategy uses a dedicated "planner" agent to analyze the conversation history and decide the next steps, including which MCP server (expert) and tool to invoke.

## Files

*   **Configuration (`config.py`):** Defines configurable parameters for this strategy.
*   **State (`state.py`):** Defines the specific state managed by this graph, extending the common `InputState`.
*   **Graph (`graph.py`):** Implements the LangGraph workflow for this strategy.
*   **Prompts (`prompts.py`):** Contains the system prompts used by the planner and orchestrator LLMs.

## Configuration (`config.py`)

Key configurable aspects:

*   `mcp_server_config`: Dictionary holding configurations for all available MCP servers.
*   `planner_system_prompt`: System prompt guiding the planner LLM.
*   `planner_model`: LLM used for the planning step (e.g., `openai/gpt-4o`).
*   `orchestrate_system_prompt`: System prompt guiding the orchestrator LLM.
*   `orchestrate_model`: LLM used for the orchestration/tool-calling step (e.g., `openai/gpt-4o`).
*   Includes methods (`get_mcp_server_descriptions`, `build_experts_context`) to format MCP server info for the planner prompt.

## State (`state.py`)

Extends the base `InputState` (which contains `messages`) with:

*   `planner_result`: An optional `PlannerResult` object containing:
    *   `decision`: Whether to `continue` the current plan or `replace` it.
    *   `plan`: A list of `Task` objects (each with `expert` name and `task` description).
    *   `next_task`: Index of the task to execute next.
    *   `clarification`: Optional message if the planner needs more info.

## Graph Workflow (`graph.py`)

1.  **START -> `planner`:**
    *   Receives the current `State` (messages).
    *   Uses the `planner_model` and `planner_system_prompt`.
    *   Considers the message history, available MCP servers (`experts`), and any existing plan.
    *   Generates a `PlannerResult` (plan, next task, decision, optional clarification).
    *   Updates the state with the `planner_result` and any clarification message.
2.  **`planner` -> `decide_planner_edge`:**
    *   If the `planner_result` contains a plan (`plan` list is not empty), transitions to `orchestrate`.
    *   Otherwise (no plan generated or planner decided to end), transitions to `END`.
3.  **`orchestrate`:**
    *   Receives the `State` including the `planner_result`.
    *   Identifies the `current_task` based on `planner_result.next_task`.
    *   Uses the `orchestrate_model` and `orchestrate_system_prompt`.
    *   Formats a prompt including message history, the full plan, and the specific `current_task` description.
    *   Fetches available tools for the `current_task.expert` (MCP server) using `mcp.GetTools()` via the `mcp_wrapper.apply` function.
    *   Binds these tools to the `orchestrate_model`.
    *   Invokes the model. The model might:
        *   Respond directly to the user.
        *   Decide to call one of the bound tools.
        *   Indicate the plan should continue (`CONTINUE_WITH_PLAN_TAG`).
    *   Updates the `messages` in the state with the AI response (which might include tool calls).
4.  **`orchestrate` -> `decide_orchestrate_edge`:**
    *   If the last message contains `tool_calls`, transitions to `call_tool`.
    *   If the last message contains `CONTINUE_WITH_PLAN_TAG`, transitions back to `planner` to potentially revise or continue the plan.
    *   Otherwise, transitions to `END`.
5.  **`call_tool`:**
    *   Identifies the `current_task.expert` (MCP server).
    *   Extracts the `tool_call` details from the last AI message.
    *   Uses `mcp.RunTool()` via the `mcp_wrapper.apply` function to execute the tool on the specified MCP server.
    *   Adds the `ToolMessage` (containing the result or error) to the state.
6.  **`call_tool` -> `orchestrate`:** After executing the tool, always transitions back to `orchestrate` to process the tool result. 