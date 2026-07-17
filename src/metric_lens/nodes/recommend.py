from metric_lens.conflict import recommend
from metric_lens.models import AgentState, ConflictResult, MetricDefinition
from metric_lens.registry import sqlite_store


def recommend_node(state: AgentState) -> dict:
    """Proposes a standard for the conflicts just detected. Advisory only —
    runs before human_review's interrupt() and never writes a resolution
    itself; the reviewer sees this as a starting point, not a decision."""
    thread_id = state["thread_id"]
    new = MetricDefinition(**state["metric"])
    conflicts = [ConflictResult(**c) for c in state["conflicts"]]

    existing: list[MetricDefinition] = []
    seen = {(new.name, new.department)}
    for c in conflicts:
        key = (c.metric_name_b, c.department_b)
        if key in seen:
            continue
        seen.add(key)
        for m in sqlite_store.get_metrics_by_name(c.metric_name_b):
            if m.department == c.department_b:
                existing.append(m)
                break

    if not existing:
        return {}

    try:
        rec = recommend.generate(new, existing, conflicts, trace_id=state.get("langfuse_trace_id"))
    except Exception as e:
        sqlite_store.record_event(
            thread_id, "recommend",
            f"추천안 생성 실패 — HITL은 추천 없이 진행됩니다: {e}",
        )
        return {}

    updated_conflicts = []
    for c in conflicts:
        c = c.model_copy(update={
            "recommended_resolution": rec.resolution,
            "recommendation_rationale": rec.rationale,
        })
        sqlite_store.save_conflict(c)
        updated_conflicts.append(c.model_dump())

    sqlite_store.record_event(
        thread_id, "recommend",
        f"추천안 생성 완료 — resolution={rec.resolution.value}, confidence={rec.confidence}",
        detail=rec.model_dump(),
    )

    return {"conflicts": updated_conflicts, "recommendation": rec.model_dump()}
