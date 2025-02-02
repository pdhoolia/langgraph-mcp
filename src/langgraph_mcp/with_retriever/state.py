from dataclasses import dataclass, field
from typing import Annotated, Sequence

from langchain_core.documents import Document

from langgraph_mcp.state import InputState

@dataclass(kw_only=True)
class BuilderState:
    status: str = field(
        default="refresh",
        metadata={
            "description": "The status of the builder state.",
        },
    )


def add_queries(existing: Sequence[str], new: Sequence[str]) -> Sequence[str]:
    """Combine existing queries with new queries.

    Args:
        existing (Sequence[str]): The current list of queries in the state.
        new (Sequence[str]): The new queries to be added.

    Returns:
        Sequence[str]: A new list containing all queries from both input sequences.
    """
    return list(existing) + list(new)


@dataclass(kw_only=True)
class State(InputState):
    """The state of your graph / agent."""

    queries: Annotated[list[str], add_queries] = field(default_factory=list)
    """A list of search queries that the agent has generated."""

    retrieved_docs: list[Document] = field(default_factory=list)
    """Populated by the retriever. This is a list of documents that the agent can reference."""

    current_mcp_server: str = field(default="")
