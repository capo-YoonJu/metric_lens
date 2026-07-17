from metric_lens.conflict import concept_compare, deterministic, probabilistic
from metric_lens.models import MERGED_STANDARD_DEPARTMENT, AgentState, ConflictResult, MetricDefinition
from metric_lens.registry import chroma_store, sqlite_store


def conflict_detect_node(state: AgentState) -> dict:
    new = MetricDefinition(**state["metric"])
    thread_id = state.get("thread_id")
    trace_id = state.get("langfuse_trace_id")

    all_metrics = sqlite_store.get_all_metrics()
    same_name = [
        m for m in all_metrics
        if m.name == new.name and m.department != new.department
    ]

    standards = sqlite_store.get_standards(new.name)
    standard_departments = {s["department"] for s in standards}
    if standard_departments:
        # A standard is already established for this metric name — only
        # compare the new registration against the currently-standard
        # department(s), not every historical definition (those were
        # already reviewed under a prior HITL decision). See ADR-0009.
        same_name_targets = [m for m in same_name if m.department in standard_departments]
    else:
        # No standard yet — fall back to comparing against every department,
        # excluding the synthetic merged-standard row (a governance artifact,
        # not a real department; only relevant once it's an active standard,
        # in which case it'd already be in standard_departments above).
        same_name_targets = [m for m in same_name if m.department != MERGED_STANDARD_DEPARTMENT]

    conflicts: list[ConflictResult] = []
    deterministic_count = 0
    concept_judgments: list[dict] = []

    # Deterministic: same name, different department, structural fields
    for existing in same_name_targets:
        det = deterministic.detect(new, existing)
        deterministic_count += len(det)
        conflicts.extend(det)

        # 분자/분모 free-text wording — LLM judges whether a string mismatch
        # is a real conceptual difference before flagging it (ADR-0008).
        concept_conflicts, judgments = concept_compare.detect(new, existing, trace_id=trace_id)
        concept_judgments.extend(judgments)
        conflicts.extend(concept_conflicts)

    # Probabilistic: semantically similar but different name
    similar_meta = chroma_store.find_similar(new, n_results=5)
    candidate_metrics: list[MetricDefinition] = []
    for meta in similar_meta:
        if meta["name"] == new.name:
            continue  # already handled by deterministic
        for m in sqlite_store.get_metrics_by_name(meta["name"]):
            if m.department == meta["department"]:
                candidate_metrics.append(m)
                break

    llm_judgments: list[dict] = []
    if candidate_metrics:
        seen = {
            (c.metric_name_a, c.metric_name_b, c.department_a, c.department_b, c.conflict_type)
            for c in conflicts
        }
        prob_conflicts, llm_judgments = probabilistic.detect(
            new, candidate_metrics, trace_id=trace_id
        )
        for pc in prob_conflicts:
            key = (pc.metric_name_a, pc.metric_name_b, pc.department_a, pc.department_b, pc.conflict_type)
            if key not in seen:
                conflicts.append(pc)

    # Attach thread_id for resume routing, and persist immediately so the
    # HITL review queue (GET /conflicts) can see them while the graph is
    # paused at human_review — resolve_node only re-saves them afterwards
    # with the human decision applied.
    conflict_dicts = []
    for c in conflicts:
        d = c.model_dump()
        d["thread_id"] = thread_id
        conflict_dicts.append(d)
        sqlite_store.save_conflict(c.model_copy(update={"thread_id": thread_id}))

    concept_conflict_count = sum(1 for j in concept_judgments if not j.get("same_concept", False))
    sqlite_store.record_event(
        thread_id, "conflict_detect",
        f"충돌 탐지 완료 — 구조적 {deterministic_count}건, "
        f"분자/분모 개념 비교 {len(concept_judgments)}건 중 충돌 {concept_conflict_count}건, "
        f"이름 다른 지표 LLM 비교 {len(llm_judgments)}건 중 충돌 "
        f"{len(conflicts) - deterministic_count - concept_conflict_count}건",
        detail={"conflicts": conflict_dicts, "concept_judgments": concept_judgments, "llm_judgments": llm_judgments},
    )

    return {"conflicts": conflict_dicts}
