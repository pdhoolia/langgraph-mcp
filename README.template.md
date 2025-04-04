# Building our own Universal Assistant: with LangGraph and Model Context Protocol (MCP)

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) is an open protocol that enables seamless integration between LLM applications and external data sources and tools. Whether you're building an AI-powered IDE, enhancing a chat interface, or creating custom AI workflows, MCP provides a standardized way to connect LLMs with the context they need. Think of MCP like a USB-C port for AI applications. Just as USB-C provides a standardized way to connect your devices to various peripherals and accessories, MCP provides a standardized way to connect AI models to different data sources and tools.

[LangGraph](https://langchain-ai.github.io/langgraph/) is a framework designed to enable seamless integration of language models into complex workflows and applications. It emphasizes modularity and flexibility. Workflows are represented as graphs. Nodes correspond to actions, tools, or model queries. Edges define the flow of information between them. LangGraph provides a structured yet dynamic way to execute tasks, making it ideal for writing AI applications involving natural language understanding, automation, and decision-making.

This project provides multiple LangGraph framework based implementations (strategies) for a universal assistant powered by MCP (Model Context Protocol) servers. It aims to showcase how LangGraph and MCP can be combined to build modular and extensible AI agents capable of interacting with various tools and data sources.

## Setting it up

1.  Create and activate a virtual environment
    ```bash
    git clone {{REPO_URL}}
    cd langgraph-mcp
    python3 -m venv .venv
    source .venv/bin/activate
    ```

2.  Install Langgraph CLI
    ```bash
    pip install -U "langgraph-cli[inmem]"
    ```
    Note: "inmem" extra(s) are needed to run LangGraph API server in development mode (without requiring Docker installation)

3.  Install the dependencies
    ```bash
    pip install -e .
    ```

4.  Configure environment variables
    ```bash
    cp env.example .env
    ```

## Detailed documentation
[llms.txt](llms.txt)
