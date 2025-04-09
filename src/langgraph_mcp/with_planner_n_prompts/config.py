from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, TypeVar

from langgraph_mcp.with_planner.config import Configuration as BaseConfiguration
from langgraph_mcp.with_planner_n_prompts import prompts

@dataclass(kw_only=True)
class Configuration(BaseConfiguration):
    """Configuration for with_planner_n_prompts strategy.
    
    Extends the base with_planner Configuration with additional settings for 
    prompt discovery and selection functionality.
    """
    
    # Additional fields specific to n_prompts strategy
    prompt_discovery_system_prompt: str = field(
        default=prompts.PROMPT_DISCOVERY_SYSTEM_PROMPT,
        metadata={"description": "The system prompt used for discovering and evaluating prompts from the expert MCP server."},
    )

    prompt_discovery_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="openai/gpt-4o",
        metadata={
            "description": "The language model used for prompt discovery. Should be in the form: provider/model-name."
        },
    )
    
    prompt_confidence_threshold: float = field(
        default=0.7,
        metadata={"description": "The confidence threshold (between 0 and 1) for automatically selecting a prompt without user confirmation."},
    )
    
    prompt_suggestion_threshold: float = field(
        default=0.4,
        metadata={"description": "The minimum confidence threshold for suggesting a prompt to the user (between 0 and 1)."},
    )

T = TypeVar("T", bound=Configuration) 