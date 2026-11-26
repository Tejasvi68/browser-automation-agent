from typing import Optional

from langchain_core.messages import HumanMessage

from app.agent.prompts import PlannedAction, build_planner_prompt
from app.core.llm_factory import get_planner_llm


class AgentPlanner:
    def __init__(self):
        # Bind the LLM to always return a PlannedAction JSON object
        base_llm = get_planner_llm(temperature=0.0)
        self.llm = base_llm.with_structured_output(PlannedAction, method="json_mode")

    async def decide_next_action(self, state: dict, callbacks: Optional[list] = None) -> dict:
        """
        Builds a prompt from the current agent state, calls the LLM,
        and returns the planned action as a plain dict.
        """
        prompt_text = build_planner_prompt(
            task=state["task"],
            step_count=state["step_count"],
            max_steps=state["max_steps"],
            rag_context=state.get("rag_context", ""),
            available_credentials=state.get("available_credentials", []),
            formatted_dom=state.get("formatted_dom", ""),
            steps_history=state.get("steps_history", []),
            last_error=state.get("last_error"),
            extracted_data=state.get("extracted_data", []),
        )

        invoke_config = {"callbacks": callbacks} if callbacks else {}

        planned: PlannedAction = await self.llm.ainvoke(
            [HumanMessage(content=str(prompt_text))],
            config=invoke_config,
        )

        return planned.model_dump()
