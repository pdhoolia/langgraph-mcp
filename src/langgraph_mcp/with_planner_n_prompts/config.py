from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Annotated, Any, Optional, Type, TypeVar
from langchain_core.runnables import RunnableConfig, ensure_config

from langgraph_mcp.with_planner_n_prompts import prompts

@dataclass(kw_only=True)
class Configuration:

    mcp_server_config: dict[str, Any] = field(
        default_factory=dict,
        metadata={"description": "MCP server configurations."},
    )

    planner_system_prompt: str = field(
        default=prompts.PLANNER_SYSTEM_PROMPT,
        metadata={"description": "The system prompt used for forming the plan to address the current state of conversation with experts."},
    )

    planner_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="openai/gpt-4o",
        metadata={
            "description": "The language model used for planning. Should be in the form: provider/model-name."
        },
    )

    orchestrate_system_prompt: str = field(
        default=prompts.ORCHESTRATE_SYSTEM_PROMPT,
        metadata={"description": "The system prompt used for orchestrating across expert tools."},
    )

    orchestrate_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="openai/gpt-4o",
        metadata={
            "description": "The language model used orchestrating across expert tools. Should be in the form: provider/model-name."
        },
    )
    
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
    
    task_assessment_system_prompt: str = field(
        default=prompts.TASK_ASSESSMENT_SYSTEM_PROMPT,
        metadata={"description": "The system prompt used for assessing whether the current task is completed."},
    )

    task_assessment_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="openai/gpt-4o",
        metadata={
            "description": "The language model used for task completion assessment. Should be in the form: provider/model-name."
        },
    )

    generate_response_system_prompt: str = field(
        default=prompts.GENERATE_RESPONSE_SYSTEM_PROMPT,
        metadata={"description": "The system prompt used for generating the final response after plan completion."},
    )

    generate_response_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="openai/gpt-4o",
        metadata={
            "description": "The language model used for generating the final response. Should be in the form: provider/model-name."
        },
    )

    @classmethod
    def from_runnable_config(
        cls: Type[T], config: Optional[RunnableConfig] = None
    ) -> T:
        """Create an Configuration instance from a RunnableConfig object.

        Args:
            cls (Type[T]): The class itself.
            config (Optional[RunnableConfig]): The configuration object to use.

        Returns:
            T: An instance of Configuration with the specified configuration.
        """
        config = ensure_config(config)
        configurable = config.get("configurable") or {}
        _fields = {f.name for f in fields(cls) if f.init}
        return cls(**{k: v for k, v in configurable.items() if k in _fields})
    
    def get_mcp_server_descriptions(self) -> list[tuple[str, str]]:
        """Get a list of descriptions of the MCP servers in the specified configuration."""
        return [(server_name, server_config['description']) for server_name, server_config in self.mcp_server_config["mcpServers"].items()]
    
    def build_experts_context(self) -> str:
        """Build the experts part of the prompt for the planning task.
        
        Here's the format to use:
        - <server_name>: <server_description>
        - <server_name>: <server_description>
        ...

        Returns:
            str: The experts part of the prompt.
        """
        return "\n".join([f"- {server_name}: {server_description}" for server_name, server_description in self.get_mcp_server_descriptions()])
        

T = TypeVar("T", bound=Configuration) 