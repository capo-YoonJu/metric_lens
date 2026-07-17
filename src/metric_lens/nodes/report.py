from metric_lens.models import AgentState
from metric_lens.registry import sqlite_store


def report_node(state: AgentState) -> dict:
    # conflict_detect_node persists unresolved conflicts as soon as they're
    # found, and resolve_node re-saves them with the human decision applied —
    # nothing left to persist here.
    response: dict = {
        "metric": state.get("metric"),
        "conflicts_detected": len(state.get("conflicts", [])),
        "conflicts": state.get("conflicts", []),
        "status": "completed",
    }
    if state.get("human_decision"):
        response["resolution"] = state["human_decision"]

    metric = state.get("metric")
    sqlite_store.update_run_status(
        state["thread_id"], "completed", metric_name=metric["name"] if metric else None
    )
    sqlite_store.record_event(state["thread_id"], "report", "워크플로우 완료")

    return {"response": response}
