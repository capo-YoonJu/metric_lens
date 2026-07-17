from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from typing_extensions import TypedDict

from pydantic import BaseModel, Field

# Synthetic department tag for the MetricDefinition row created by a
# "merged" HITL resolution. Not a real department — excluded from
# conflict_detect's cross-department comparison. See ADR-0007.
MERGED_STANDARD_DEPARTMENT = "표준(병합)"


class FilterCondition(BaseModel):
    field: str
    operator: Literal["eq", "ne", "gt", "lt", "gte", "lte", "in", "not_in"]
    value: str | int | float | bool | list


class MetricDefinition(BaseModel):
    name: str
    label: str
    description: str = ""
    formula_raw: str
    formula_normalized: str
    formula_ast: dict[str, Any] | None = None
    grain: Literal["daily", "monthly", "quarterly", "annual"]
    dimensions: list[str] = Field(default_factory=list)
    filters: list[FilterCondition] = Field(default_factory=list)
    numerator: str | None = None
    denominator: str | None = None
    department: str
    source_type: Literal["natural_language", "sql", "excel"]
    source_raw: str


class ConflictType(str, Enum):
    formula_mismatch = "formula_mismatch"
    grain_mismatch = "grain_mismatch"
    filter_diff = "filter_diff"
    denominator_diff = "denominator_diff"
    numerator_diff = "numerator_diff"
    synonym = "synonym"
    semantic_diff = "semantic_diff"


class ConflictStatus(str, Enum):
    unresolved = "unresolved"
    resolved = "resolved"


class ResolutionType(str, Enum):
    wontfix = "wontfix"
    adopted_a = "adopted_a"
    adopted_b = "adopted_b"
    merged = "merged"


class ConflictResult(BaseModel):
    id: str
    thread_id: str | None = None
    metric_name_a: str
    metric_name_b: str
    department_a: str
    department_b: str
    conflict_type: ConflictType
    detail: str
    status: ConflictStatus = ConflictStatus.unresolved
    resolution: ResolutionType | None = None
    note: str | None = None
    resolved_by: str | None = None
    # LLM-proposed standard — advisory only, never auto-applied. See ADR-0006.
    recommended_resolution: ResolutionType | None = None
    recommendation_rationale: str | None = None


class HumanDecision(BaseModel):
    resolution: ResolutionType
    note: str = ""
    resolved_by: str


class Recommendation(BaseModel):
    """LLM's proposed standard for a set of conflicts in one HITL review.

    Advisory only — human_review still gates every decision (ADR-0005);
    this just gives the reviewer a starting point instead of a blank form."""
    resolution: ResolutionType
    rationale: str
    confidence: Literal["low", "medium", "high"]
    merged_definition: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    department: str
    source_type: Literal["natural_language", "sql", "excel"]
    content: str


# LangGraph state — dicts for checkpointer-safe serialization
class AgentState(TypedDict, total=False):
    thread_id: str
    raw_input: str
    source_type: str
    department: str
    metric: dict | None          # MetricDefinition.model_dump()
    conflicts: list[dict]        # list[ConflictResult.model_dump()]
    recommendation: dict | None  # Recommendation.model_dump()
    human_decision: dict | None  # HumanDecision.model_dump()
    response: dict[str, Any]
    langfuse_trace_id: str       # links raw OpenAI calls to this run's Langfuse trace
