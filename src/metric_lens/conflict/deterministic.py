from __future__ import annotations

import uuid

from metric_lens.models import ConflictResult, ConflictType, FilterCondition, MetricDefinition


def _filter_key(f: FilterCondition) -> str:
    return f"{f.field}__{f.operator}__{f.value}"


def detect(new: MetricDefinition, existing: MetricDefinition) -> list[ConflictResult]:
    """Compare two same-name metrics from different departments on
    structural fields only. numerator/denominator are free-text Korean and
    go through concept_compare.py's LLM judgment instead (ADR-0008) — exact
    string match there would flag every paraphrase as a conflict."""
    conflicts: list[ConflictResult] = []

    def _conflict(ctype: ConflictType, detail: str) -> ConflictResult:
        return ConflictResult(
            id=str(uuid.uuid4()),
            metric_name_a=new.name,
            metric_name_b=existing.name,
            department_a=new.department,
            department_b=existing.department,
            conflict_type=ctype,
            detail=detail,
        )

    # 1. Formula mismatch
    if new.formula_normalized != existing.formula_normalized:
        formula_differs = True
        if new.formula_ast and existing.formula_ast:
            formula_differs = new.formula_ast != existing.formula_ast
        if formula_differs:
            conflicts.append(_conflict(
                ConflictType.formula_mismatch,
                f"수식 불일치 — {new.department}: `{new.formula_normalized}` / "
                f"{existing.department}: `{existing.formula_normalized}`",
            ))

    # 2. Grain mismatch
    if new.grain != existing.grain:
        conflicts.append(_conflict(
            ConflictType.grain_mismatch,
            f"집계 단위 불일치 — {new.department}: `{new.grain}` / "
            f"{existing.department}: `{existing.grain}`",
        ))

    # 3. Filter diff
    new_filters = {_filter_key(f) for f in new.filters}
    old_filters = {_filter_key(f) for f in existing.filters}
    if new_filters != old_filters:
        only_new = new_filters - old_filters
        only_old = old_filters - new_filters
        parts = []
        if only_new:
            parts.append(f"{new.department}만 포함: {only_new}")
        if only_old:
            parts.append(f"{existing.department}만 포함: {only_old}")
        conflicts.append(_conflict(
            ConflictType.filter_diff,
            "필터 차이 — " + " / ".join(parts),
        ))

    return conflicts
