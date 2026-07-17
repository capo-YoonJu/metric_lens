from metric_lens.models import AgentState
from metric_lens.registry import sqlite_store


def ingest_node(state: AgentState) -> dict:
    sqlite_store.create_run(
        thread_id=state["thread_id"],
        department=state["department"],
        source_type=state["source_type"],
        raw_input=state["raw_input"],
    )
    sqlite_store.record_event(
        state["thread_id"], "ingest",
        f"입력 수신 — 부서: {state['department']}, 형식: {state['source_type']}",
    )
    return {
        "metric": None,
        "conflicts": [],
        "human_decision": None,
        "response": {},
    }
