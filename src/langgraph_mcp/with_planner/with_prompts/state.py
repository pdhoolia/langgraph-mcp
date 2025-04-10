from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from pydantic import BaseModel

from langgraph_mcp.with_planner.state import State as BaseState


class ExpertPrompt(BaseModel):
    """Represents a prompt from an expert MCP server."""
    
    name: str
    """The name of the prompt."""
    
    description: str
    """Description of what the prompt does."""
    
    match_confidence: float
    """Confidence score for how well this prompt matches the current task (0-1)."""
    
    arguments: Optional[List[Dict[str, Any]]] = None
    """Optional arguments required by the prompt."""


@dataclass(kw_only=True)
class State(BaseState):
    """Extends the base planner State to include expert prompts.

    This state variant inherits planner_result and task_completed fields
    from the base State and adds fields to track expert prompts and selections.
    """
    
    expert_prompts: List[ExpertPrompt] = field(default_factory=list)
    """List of available prompts from the current expert that may be relevant to the task."""
    
    selected_prompt: Optional[ExpertPrompt] = field(default=None)
    """The prompt selected for use with the current task, if any.""" 