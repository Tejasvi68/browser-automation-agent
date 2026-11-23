from typing import Any, Dict, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from app.core.llm_factory import get_planner_llm
from app.agent.prompts import PlannedAction, build_planner_prompt
from app.agent.state import AgentState


class AgentPlanner:
    def __init__(self, llm: Optional[BaseChatModel] = None):
        base_llm = llm or get_planner_llm(temperature=0.0)
        self.structured_llm = base_llm.with_structured_output(PlannedAction)

    async def decide_next_action(self, state: AgentState, callbacks: Optional[list] = None) -> Dict[str, Any]:
        prompt = build_planner_prompt(
            task=state["task"],
            step_count=state["step_count"],
            max_steps=state["max_steps"],
            rag_context=state.get("rag_context", ""),
            available_credentials=state.get("available_credentials", []),
            formatted_dom=state.get("formatted_dom", ""),
            steps_history=state.get("steps_history", []),
            last_error=state.get("last_error"),
        )

        config = {"callbacks": callbacks} if callbacks else {}
        decision: PlannedAction = await self.structured_llm.ainvoke([HumanMessage(content=prompt)], config=config)
        return decision.model_dump()