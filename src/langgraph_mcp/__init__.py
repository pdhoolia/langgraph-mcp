"""MCP Router using LangGraph

This module routes user message to appropriate MCP server.
- build_router_graph: builds and indexes a document for each MCP (Model Context Protocol) server
- router_graph: uses the index to decide which MCP server to route the user message to

"""

from langgraph_mcp.build_router_graph import graph as build_router_graph
from langgraph_mcp.router_graph import graph as router_graph

__all__ = ["build_router_graph", "router_graph"]
