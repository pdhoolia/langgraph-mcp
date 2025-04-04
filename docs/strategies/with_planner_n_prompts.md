# Strategy: With Planner and Multiple Prompts

This strategy enhances the basic planner by incorporating the ability to discover and utilize specific prompts offered by MCP servers (experts) to potentially improve task execution.

## Files

*   **Configuration (`config.py`):** Extends the base planner configuration with parameters for:
    *   LLMs and prompts for `prompt_discovery`, `task_assessment`, and final `generate_response` steps.
    *   `prompt_confidence_threshold`: For automatically selecting a discovered prompt.
    *   `prompt_suggestion_threshold`: For suggesting prompts to the user.
*   **State (`state.py`):** Extends the base planner state (`InputState`, `PlannerResult`, `Task`) with:
    *   `expert_prompts`: A list of `ExpertPrompt` objects discovered for the current task.
    *   `selected_prompt`: The `ExpertPrompt` chosen (automatically or by the user) for the current task.
    *   `task_completed`: A boolean flag indicating if the current task is considered complete.
*   **Graph (`graph.py`):** Implements the more complex LangGraph workflow.
*   **Prompts (`prompts.py`):** Contains system prompts for all LLM steps (planner, orchestrator, prompt discovery, task assessment, response generation).

## Graph Workflow (`graph.py`)

This workflow builds upon the basic planner by adding steps for prompt discovery, selection, and task assessment.

1.  **START -> `planner`:** Same as the basic planner strategy: generates/updates the plan (`PlannerResult`) based on conversation history and available experts. Adds `planner_result` to state.
2.  **`planner` -> `decide_planner_edge`:**
    *   If a plan exists (`state.planner_result.plan`), transitions to `discover_expert_prompts`.
    *   Otherwise, transitions to `END`.
3.  **`discover_expert_prompts`:**
    *   Identifies the `current_task` and `expert` from `state.planner_result`.
    *   Fetches the expert's MCP server configuration.
    *   Uses `mcp.GetPrompts()` via `mcp_wrapper.apply` to retrieve prompts offered by the expert server.
    *   Uses the `prompt_discovery_model` and `prompt_discovery_system_prompt` to evaluate the relevance (match confidence) of each fetched prompt to the `current_task.task`, considering recent messages.
    *   Stores the evaluated prompts (as `ExpertPrompt` objects, sorted by confidence) in `state.expert_prompts`.
4.  **`discover_expert_prompts` -> `select_prompt`:**
    *   Checks if any `expert_prompts` were found.
    *   Finds the prompt with the highest `match_confidence`.
    *   If the confidence exceeds `prompt_confidence_threshold`, automatically sets this prompt in `state.selected_prompt`.
    *   Otherwise, leaves `state.selected_prompt` as `None`.
5.  **`select_prompt` -> `decide_prompt_edge`:**
    *   If `state.selected_prompt` is set (auto-selected), transitions to `orchestrate_tools`.
    *   If no prompt is auto-selected, but there are prompts in `state.expert_prompts` exceeding `prompt_suggestion_threshold`, transitions to `ask_user_for_prompt`.
    *   Otherwise (no suitable prompts found/suggested), transitions to `orchestrate_tools` (labeled as `no_prompts` edge, but leads to the same node).
6.  **`ask_user_for_prompt`:**
    *   Filters `state.expert_prompts` based on `prompt_suggestion_threshold`.
    *   Constructs an `AIMessage` listing the filtered prompts with numbers, descriptions, and confidence scores, asking the user to choose one or reply 'none'.
    *   Adds this message to `state.messages`.
7.  **`ask_user_for_prompt` -> `process_user_prompt_choice`:** (Waits for user input)
    *   Parses the last `HumanMessage` from `state.messages`.
    *   If the user chose a valid number corresponding to a suggested prompt, sets that prompt in `state.selected_prompt`.
    *   If the user replied 'none' or gave an invalid response, leaves `state.selected_prompt` as `None`.
8.  **`process_user_prompt_choice` -> `orchestrate_tools`:** Always proceeds to orchestration after processing the user's choice (or lack thereof).
9.  **`orchestrate_tools`:**
    *   Similar to the basic planner's `orchestrate` node, but includes the `state.selected_prompt` (if any) in the context for the `orchestrate_model`.
    *   Fetches tools for the `current_task.expert` using `mcp.GetTools()`.
    *   Binds tools and invokes the `orchestrate_model` with the appropriate system prompt and context (including messages, plan, task, and selected prompt details).
    *   Adds the AI response (potentially including tool calls) to `state.messages`.
10. **`orchestrate_tools` -> `decide_orchestrate_tools_edge`:**
    *   If the last message contains `tool_calls`, transitions to `call_tool`.
    *   If the last message does *not* contain tool calls (meaning the orchestrator provided a response or finished its part of the task), transitions to `assess_task_completion`.
    *   (Includes an `END` transition, although the logic seems to favor `assess_task_completion` when no tool call is made).
11. **`call_tool`:**
    *   Same as the basic planner: executes the tool specified in the last AI message using `mcp.RunTool()` via `mcp_wrapper.apply`.
    *   Adds the `ToolMessage` result to `state.messages`.
12. **`call_tool` -> `assess_task_completion`:** After a tool is called, proceeds to assess if the task is now complete.
13. **`assess_task_completion`:**
    *   Uses the `task_assessment_model` and `task_assessment_system_prompt`.
    *   Provides the `current_task.task` and recent messages as context.
    *   The model outputs a `TaskAssessmentResult` (boolean `is_completed`, `explanation`, `confidence`).
    *   Sets the `state.task_completed` flag based on the model's assessment.
14. **`assess_task_completion` -> `decide_task_assessment_edge`:**
    *   If `state.task_completed` is `True`, transitions to `advance_to_next_task`.
    *   If `state.task_completed` is `False`, transitions back to `orchestrate_tools` to continue working on the current task (potentially using the tool result from the previous step).
15. **`advance_to_next_task`:**
    *   Increments the `next_task` index in `state.planner_result`.
    *   Resets `state.task_completed` to `False`.
    *   Clears `state.expert_prompts` and `state.selected_prompt` for the next task.
16. **`advance_to_next_task` -> `decide_next_task_edge`:**
    *   Checks if `state.planner_result.next_task` is still within the bounds of the `plan`.
    *   If there is a next task, transitions back to `discover_expert_prompts` to start the process for the new task.
    *   If all tasks in the plan are completed, transitions to `generate_response`.
17. **`generate_response`:**
    *   Uses the `generate_response_model` and `generate_response_system_prompt`.
    *   Provides the full message history and the completed plan as context.
    *   Generates a final summary response for the user.
    *   Adds this final `AIMessage` to `state.messages`.
    *   Resets `state.planner_result` to `None`.
18. **`generate_response` -> `END`:** The workflow concludes. 