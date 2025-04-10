# Implemented Assistant Strategies

This project includes several distinct strategies for implementing the LangGraph-based universal assistant. Each strategy represents a different approach to orchestrating the interaction between the user, the assistant, and the MCP servers.

Below are links to the detailed documentation for each strategy:

*   **[With Planner](./with_planner.md):** This strategy utilizes a planning agent to decide which MCP server and tool to use based on the user query and available MCP capabilities.
*   **[With Retriever](./with_retriever.md):** This strategy employs a retriever component. It first builds an index of MCP server capabilities (tools, prompts, resources) using the `index_builder` graph. The main `assist_with_retriever` graph then uses this index to find the relevant MCP server and tool for the user query before invoking it.
*   **[With Planner and Prompts](./with_prompts.md):** An enhanced version of the planner strategy that utilizes specialized prompts from MCP servers to guide tool selection and execution. This strategy is implemented as a sub-package within the `with_planner` strategy. 