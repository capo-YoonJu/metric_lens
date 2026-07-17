from __future__ import annotations

import json
import uuid

from langfuse.openai import OpenAI

from metric_lens.models import ConflictResult, ConflictType, MetricDefinition

_client: OpenAI | None = None

_FIELDS: tuple[tuple[str, str, ConflictType], ...] = (
    ("분모", "denominator", ConflictType.denominator_diff),
    ("분자", "numerator", ConflictType.numerator_diff),
)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _judge(field_label: str, a: str, b: str, trace_id: str | None) -> dict:
    prompt = f"""두 부서가 같은 지표의 {field_label} 개념을 각각 다음과 같이 표현했습니다.
표현이 다를 뿐 실질적으로 같은 개념인지, 범위나 정의 자체가 다른 개념인지 판단하세요.

A: "{a}"
B: "{b}"

같은 개념이면 (예: '총여신'과 '전체 여신 잔액'처럼 단어만 다른 경우) same_concept=true.
다른 개념이면 (예: '총여신'과 '채권잔액'처럼 포함 범위 자체가 다른 경우) same_concept=false.
확신이 서지 않으면 은행 감독규정 관점에서 보수적으로(같지 않다고) 판단하세요.

JSON만 응답하세요:
{{"same_concept": true|false, "detail": "한국어 근거 (1-2문장)"}}"""

    msg = _get_client().chat.completions.create(
        model="gpt-4o",
        trace_id=trace_id,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.choices[0].message.content.strip()
    if "```" in text:
        text = text.split("```")[1].split("```")[0].removeprefix("json").strip()
    return json.loads(text)


def detect(
    new: MetricDefinition, existing: MetricDefinition, trace_id: str | None = None
) -> tuple[list[ConflictResult], list[dict]]:
    """Same-name, cross-department comparison of the free-text 분자/분모
    fields (ADR-0008). Only called when the two strings actually differ —
    identical text never reaches the LLM. Unlike probabilistic.detect()'s
    non-fatal failure mode, an LLM error here still raises a conflict
    (flagged for human review) rather than silently passing: denominator_diff
    is the "must never miss" signal called out in CONTEXT.md, and this check
    replaced a 100%-reliable string comparison, so a new LLM failure mode
    shouldn't silently make detection less reliable than before.

    Returns (conflicts, judgments) — judgments is the audit trail of every
    field comparison the LLM made, including ones judged as the same concept."""
    conflicts: list[ConflictResult] = []
    judgments: list[dict] = []

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

    for field_label, field_name, ctype in _FIELDS:
        a, b = getattr(new, field_name), getattr(existing, field_name)
        if not a or not b or a == b:
            continue

        try:
            judgment = _judge(field_label, a, b, trace_id)
        except Exception as e:
            judgments.append({"field": field_name, "a": a, "b": b, "error": str(e)})
            conflicts.append(_conflict(
                ctype,
                f"{field_label} 개념 비교 실패(LLM 오류) — 표현 차이만으로 잠정 충돌 처리, 검토 필요: "
                f"{new.department}: `{a}` / {existing.department}: `{b}`",
            ))
            continue

        judgments.append({"field": field_name, "a": a, "b": b, **judgment})
        if not judgment.get("same_concept", False):
            conflicts.append(_conflict(
                ctype,
                f"{field_label} 개념 불일치 — {new.department}: `{a}` / "
                f"{existing.department}: `{b}` — {judgment.get('detail', '')}",
            ))

    return conflicts, judgments
