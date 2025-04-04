# Strategy: With Retriever

This strategy uses a retriever to find the most relevant MCP server for a given user query based on indexed descriptions of the servers' capabilities.

## Files

*   **Configuration (`config.py`):** Defines configuration for embedding models, retriever provider (e.g., Milvus), search parameters, MCP servers, and LLMs/prompts for query generation, routing, and orchestration.
*   **State (`state.py`):** Defines two state classes:
    *   `BuilderState`: Used by the `index_builder` graph (contains just a `status` field).
    *   `State`: Used by the main assistant graph, extending `InputState` with `queries` (list of generated search queries), `retrieved_docs` (documents retrieved from the index), and `current_mcp_server` (the server selected by the router).
*   **Graph (`graph.py`):** Implements the main LangGraph assistant workflow for this strategy.
*   **Index Builder (`index_builder.py`):** Implements a separate LangGraph graph responsible for fetching MCP server descriptions and building the vector index used by the retriever.
*   **Retriever (`retriever.py`):** Contains factory functions (`make_text_encoder`, `make_milvus_retriever`, `make_retriever`) to create the embedding model and the vector store retriever (currently supports Milvus) based on the configuration.
*   **Prompts (`prompts.py`):** Contains system prompts for routing query generation, routing response generation, and MCP orchestration.
*   **Utils (`utils.py`):** Contains utility functions specific to this strategy (e.g., `format_docs`).

## Index Builder Workflow (`index_builder.py`)

This graph is typically run once or periodically to update the retriever's index.

1.  **START -> `build_router`:**
    *   Reads `mcp_server_config` from the configuration.
    *   Uses `asyncio.gather` and the `mcp_wrapper.apply` function with `mcp.RoutingDescription` to fetch descriptions (tools, prompts, resources) from all configured MCP servers concurrently.
    *   Creates `langchain_core.documents.Document` objects for each server, storing the description in `page_content` and the server name in `metadata["id"]`.
    *   Uses the `make_retriever` factory function to get an instance of the configured retriever (e.g., Milvus).
    *   Adds the created documents to the retriever's vector store, using the server name as the ID (important for potential updates/deletions).
    *   Updates the `BuilderState` status to `success` or `failure`.

## Main Assistant Graph Workflow (`graph.py`)

This graph handles user interaction.

1.  **START -> `decide_subgraph`:** Determines the initial routing based on whether `current_mcp_server` is set in the state. Initially, it's not set, so it routes to the **MCP Server Router** sub-graph.

**MCP Server Router Sub-graph:**

2.  **`generate_routing_query`:**
    *   If it's the first message, uses the user input directly as the query.
    *   Otherwise, uses the `routing_query_model` and `routing_query_system_prompt` to generate a refined search query based on the conversation history.
    *   Adds the generated query to `state.queries`.
3.  **`generate_routing_query` -> `retrieve`:**
    *   Uses the latest query from `state.queries`.
    *   Calls the `make_retriever` factory to get the retriever.
    *   Invokes the retriever (`ainvoke`) with the query and configured `search_kwargs`.
    *   Stores the retrieved documents (containing MCP server descriptions) in `state.retrieved_docs`.
4.  **`retrieve` -> `route`:**
    *   Uses the `routing_response_model` and `routing_response_system_prompt`.
    *   Provides the message history and the formatted `retrieved_docs` to the model.
    *   The prompt instructs the model to identify the single most relevant MCP server based on the retrieved docs or state if no server is relevant (`NOTHING_RELEVANT`) or if clarification is needed (`AMBIGUITY_PREFIX`).
    *   If a relevant server is identified, updates `state.current_mcp_server` with its name.
    *   If no server is relevant or clarification is needed, adds the model's response to `state.messages`.
5.  **`route` -> `decide_mcp_or_not`:**
    *   If `state.current_mcp_server` was set (a server was chosen), transitions to the **MCP Orchestrator** sub-graph (`mcp_orchestrator` node).
    *   Otherwise (no server chosen or ambiguity), transitions to `END`.

**MCP Orchestrator Sub-graph:**

6.  **`mcp_orchestrator`:**
    *   Gets the `current_mcp_server` name from the state.
    *   Fetches the server's configuration.
    *   Uses `mcp.GetTools()` via `mcp_wrapper.apply` to get the tools offered by this server.
    *   Uses the `mcp_orchestrator_model` and `mcp_orchestrator_system_prompt`.
    *   The prompt includes message history and descriptions of *other* available MCP servers.
    *   The prompt instructs the model to use the tools of the *current* server if appropriate, respond that the current server cannot help (`IDK_RESPONSE`), or indicate that other servers are more relevant (`OTHER_SERVERS_MORE_RELEVANT`).
    *   Binds the fetched tools to the model.
    *   Invokes the model.
    *   If the response is `IDK_RESPONSE` or `OTHER_SERVERS_MORE_RELEVANT` (and not immediately after a tool call), it resets `state.current_mcp_server` to `None` to trigger re-routing via the **MCP Server Router** sub-graph on the next turn.
    *   Otherwise, adds the AI response (which might contain tool calls) to `state.messages`.
7.  **`mcp_orchestrator` -> `route_tools`:**
    *   If the last message was a `HumanMessage` or a `ToolMessage`, routes back to `generate_routing_query` to potentially re-route based on the new input or tool result.
    *   If the last AI message contains `tool_calls`, routes to `mcp_tool_call`.
    *   Otherwise, routes to `END`.
8.  **`mcp_tool_call`:**
    *   Gets the `current_mcp_server` name and config.
    *   Extracts the tool call details from the last AI message.
    *   Uses `mcp.RunTool()` via `mcp_wrapper.apply` to execute the tool.
    *   Adds the `ToolMessage` result to `state.messages`.
9.  **`mcp_tool_call` -> `route_tools`:** Always routes back to `route_tools` after a tool call to handle the result (which will typically lead back to `generate_routing_query`). 