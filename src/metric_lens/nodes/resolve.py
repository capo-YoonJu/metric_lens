from metric_lens.models import (
    MERGED_STANDARD_DEPARTMENT,
    AgentState,
    ConflictResult,
    ConflictStatus,
    HumanDecision,
    MetricDefinition,
    ResolutionType,
)
from metric_lens.registry import sqlite_store


def _apply_standard(state: AgentState, decision: HumanDecision, conflicts: list[ConflictResult]) -> None:
    """Points metric_registry lookups (registry badge, conflict-detect
    scoping) at the department(s) a human just approved. Every department's
    own MetricDefinition row is left untouched — this only adds/moves
    pointers in metric_standards. See ADR-0007/0009.

    Only handles same-name, cross-department conflicts (metric_name_a ==
    metric_name_b == the ingested metric's name) — that's the case the
    registry UI actually renders as "same metric, different department".
    Cross-name conflicts (synonym/semantic_diff) still get their resolution
    recorded on the conflict row above, just no registry pointer, since
    "which of two differently-named metrics is canonical" needs its own
    design (aliasing) rather than a single-department pointer.

    adopted_a/adopted_b/merged each pick ONE winner and supersede whatever
    was standard before (replace_standards). wontfix explicitly means "don't
    force a single winner" — it adds every department in this conflict batch
    to the standard set instead of replacing it, so a prior standard and this
    newly-accepted department both count as standard going forward, and
    future registrations get compared against both (ADR-0009).
    """
    new_metric = MetricDefinition(**state["metric"])
    if any(c.metric_name_a != new_metric.name or c.metric_name_b != new_metric.name for c in conflicts):
        sqlite_store.record_event(
            state["thread_id"], "resolve",
            f"표준 포인터 갱신 생략 — {new_metric.name}: 서로 다른 이름의 지표 간 충돌은 "
            "자동 포인터 지정 대상이 아닙니다 (수동 검토 필요)",
        )
        return

    if decision.resolution == ResolutionType.wontfix:
        departments = {new_metric.department} | {c.department_b for c in conflicts}
        for department in departments:
            sqlite_store.set_standard(
                metric_name=new_metric.name,
                department=department,
                resolution=decision.resolution.value,
                note=decision.note,
                set_by=decision.resolved_by,
                thread_id=state["thread_id"],
            )
        return

    if decision.resolution == ResolutionType.adopted_a:
        department = new_metric.department
    elif decision.resolution == ResolutionType.adopted_b:
        department = conflicts[0].department_b
    else:  # merged
        draft = (state.get("recommendation") or {}).get("merged_definition") or {}
        merged = new_metric.model_copy(update={
            **{k: v for k, v in draft.items() if v and k in MetricDefinition.model_fields},
            "department": MERGED_STANDARD_DEPARTMENT,
        })
        sqlite_store.save_metric(merged)
        department = MERGED_STANDARD_DEPARTMENT

    sqlite_store.replace_standards(
        metric_name=new_metric.name,
        department=department,
        resolution=decision.resolution.value,
        note=decision.note,
        set_by=decision.resolved_by,
        thread_id=state["thread_id"],
    )


def resolve_node(state: AgentState) -> dict:
    raw = state["human_decision"]
    decision = HumanDecision(**raw) if isinstance(raw, dict) else raw

    resolved: list[dict] = []
    conflicts: list[ConflictResult] = []
    for c_dict in state["conflicts"]:
        conflict = ConflictResult(**c_dict)
        conflict = conflict.model_copy(update={
            "status": ConflictStatus.resolved,
            "resolution": decision.resolution,
            "note": decision.note,
            "resolved_by": decision.resolved_by,
        })
        sqlite_store.save_conflict(conflict)
        conflicts.append(conflict)
        resolved.append(conflict.model_dump())

    _apply_standard(state, decision, conflicts)

    sqlite_store.record_event(
        state["thread_id"], "resolve",
        f"충돌 해결 반영 완료 — {len(resolved)}건, resolution={decision.resolution.value}",
    )

    return {"conflicts": resolved, "human_decision": decision.model_dump()}
