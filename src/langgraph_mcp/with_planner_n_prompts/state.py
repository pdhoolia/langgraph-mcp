from dataclasses import dataclass, field
from typing import Optional, Literal, List, Dict, Any

from pydantic import BaseModel

from langgraph_mcp.state import InputState


class Task(BaseModel):
    """Represents a task assigned to an expert for execution."""
    
    expert: str
    """The name of the expert responsible for executing the task."""
    
    task: str
    """A brief description of the task to be performed."""


class PlannerResult(BaseModel):
    """Represents the output of the planner when determining the next course of action."""

    decision: Literal["continue", "replace"]
    """Indicates whether to continue with the existing plan or replace it with a new one."""

    plan: list[Task]
    """Ordered list of tasks to be executed, assigned to available experts."""

    next_task: int
    """Index of the next task to execute within the `tasks` list."""

    clarification: Optional[str] = None
    """Optional clarification message if user input requires further disambiguation."""

    def get_current_task(self) -> Optional[Task]:
        """Returns the current task based on next_task index, or None if out of bounds."""
        if 0 <= self.next_task < len(self.plan):
            return self.plan[self.next_task]
        return None


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
class State(InputState):
    """Extends InputState to include planner results and expert prompts.

    This state variant maintains the planner's decision and task plan, 
    allowing the agent to track and adjust its execution accordingly.
    It also tracks available expert prompts and their relevance to the current task.
    """

    planner_result: Optional[PlannerResult] = field(default=None)
    """The result from the planner, including task assignments and execution decisions."""
    
    expert_prompts: List[ExpertPrompt] = field(default_factory=list)
    """List of available prompts from the current expert that may be relevant to the task."""
    
    selected_prompt: Optional[ExpertPrompt] = field(default=None)
    """The prompt selected for use with the current task, if any."""
    
    task_completed: bool = field(default=False)
    """Flag indicating if the current task has been completed.""" 