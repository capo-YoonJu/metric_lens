from langgraph.types import interrupt

from metric_lens.models import AgentState
from metric_lens.registry import sqlite_store


def human_review_node(state: AgentState) -> dict:
    thread_id = state["thread_id"]
    # LangGraph replays node code preceding interrupt() on every resume, so
    # guard this side effect to only fire once (on the initial, pre-pause pass).
    run = sqlite_store.get_run(thread_id)
    if not run or run["status"] != "awaiting_review":
        sqlite_store.record_event(
            thread_id, "human_review",
            f"HITL 대기 시작 — 충돌 {len(state['conflicts'])}건, 사람 결정 대기",
        )
        sqlite_store.update_run_status(thread_id, "awaiting_review", metric_name=state["metric"]["name"])

    decision = interrupt({
        "message": "충돌이 발견됐습니다. POST /conflicts/{thread_id}/resume 으로 결정을 입력해주세요.",
        "conflicts": state["conflicts"],
        "metric": state["metric"],
        # Advisory only — human_review still blocks until a person submits
        # a decision regardless of what the LLM proposed here (ADR-0006).
        "recommendation": state.get("recommendation"),
    })

    sqlite_store.record_event(
        thread_id, "human_review",
        f"사람 결정 입력 — resolution={decision.get('resolution')}, by={decision.get('resolved_by')}",
        detail=decision,
    )
    return {"human_decision": decision}
