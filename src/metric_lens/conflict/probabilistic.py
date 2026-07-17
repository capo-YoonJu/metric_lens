from __future__ import annotations

import json
import uuid

from langfuse.openai import OpenAI

from metric_lens.models import ConflictResult, ConflictType, MetricDefinition

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _compare_pair(new: MetricDefinition, candidate: MetricDefinition, trace_id: str | None) -> dict:
    prompt = f"""두 금융 지표 정의를 비교하세요.

지표 A ({new.department}):
- 이름: {new.name} ({new.label})
- 수식: {new.formula_normalized}
- 분자: {new.numerator or '미지정'}
- 분모: {new.denominator or '미지정'}
- 설명: {new.description}

지표 B ({candidate.department}):
- 이름: {candidate.name} ({candidate.label})
- 수식: {candidate.formula_normalized}
- 분자: {candidate.numerator or '미지정'}
- 분모: {candidate.denominator or '미지정'}
- 설명: {candidate.description}

다음 중 하나를 판단하세요:
1. "synonym" — 이름은 다르지만 실질적으로 동일한 지표
2. "semantic_diff" — 이름은 같거나 유사하지만 미묘하게 다른 개념
3. "none" — 충돌 없음

JSON만 응답하세요:
{{"conflict_type": "synonym"|"semantic_diff"|"none", "detail": "한국어 설명"}}"""

    msg = _get_client().chat.completions.create(
        model="gpt-4o",
        trace_id=trace_id,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.choices[0].message.content.strip()
    if "```" in text:
        text = text.split("```")[1].split("```")[0].removeprefix("json").strip()

    data = json.loads(text)
    return {
        "candidate_name": candidate.name,
        "candidate_department": candidate.department,
        "conflict_type": data["conflict_type"],
        "detail": data["detail"],
    }


def detect(
    new: MetricDefinition, candidates: list[MetricDefinition], trace_id: str | None = None
) -> tuple[list[ConflictResult], list[dict]]:
    """Returns (conflicts, llm_judgments). llm_judgments includes every
    comparison the LLM made, even ones it judged as "none" — this is the
    audit trail of the LLM's reasoning, independent of whether it produced
    a conflict."""
    conflicts: list[ConflictResult] = []
    judgments: list[dict] = []
    for candidate in candidates:
        if candidate.department == new.department and candidate.name == new.name:
            continue
        try:
            judgment = _compare_pair(new, candidate, trace_id)
        except Exception as e:
            judgments.append({
                "candidate_name": candidate.name,
                "candidate_department": candidate.department,
                "conflict_type": "error",
                "detail": str(e),
            })
            continue  # LLM failure is non-fatal

        judgments.append(judgment)
        if judgment["conflict_type"] != "none":
            ctype = (
                ConflictType.synonym
                if judgment["conflict_type"] == "synonym"
                else ConflictType.semantic_diff
            )
            conflicts.append(ConflictResult(
                id=str(uuid.uuid4()),
                metric_name_a=new.name,
                metric_name_b=candidate.name,
                department_a=new.department,
                department_b=candidate.department,
                conflict_type=ctype,
                detail=judgment["detail"],
            ))
    return conflicts, judgments
