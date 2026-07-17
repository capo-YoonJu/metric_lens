from __future__ import annotations

import json

from langfuse.openai import OpenAI

from metric_lens.models import ConflictResult, MetricDefinition, Recommendation

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _format_conflicts(conflicts: list[ConflictResult]) -> str:
    lines = []
    for c in conflicts:
        lines.append(f"- [{c.conflict_type.value}] {c.detail}")
    return "\n".join(lines)


def _format_metric(m: MetricDefinition) -> str:
    return (
        f"- 부서: {m.department}\n"
        f"  이름: {m.name} ({m.label})\n"
        f"  수식: {m.formula_normalized}\n"
        f"  분자: {m.numerator or '미지정'} / 분모: {m.denominator or '미지정'}\n"
        f"  집계단위: {m.grain}\n"
        f"  설명: {m.description or '미지정'}"
    )


def generate(
    new: MetricDefinition,
    existing: list[MetricDefinition],
    conflicts: list[ConflictResult],
    trace_id: str | None = None,
) -> Recommendation:
    """Ask the LLM to propose ONE standard for this batch of conflicts.

    This is advisory only: the caller must still route through human_review's
    interrupt() (ADR-0005). Raises on LLM/parse failure — callers should treat
    that as "no recommendation available" and let HITL proceed unassisted."""
    prompt = f"""당신은 은행 데이터 거버넌스팀의 지표 표준화 보조 담당자입니다.
아래 지표 정의 충돌을 검토하고, 검토자(사람)에게 제안할 표준안을 하나 제시하세요.
최종 결정은 사람이 내리므로, 근거를 명확히 제시하는 것이 중요합니다.

신규 정의:
{_format_metric(new)}

기존 정의(들):
{chr(10).join(_format_metric(m) for m in existing)}

탐지된 충돌:
{_format_conflicts(conflicts)}

다음 중 하나를 추천하세요:
- "adopted_a" — 신규 정의({new.department})를 표준으로 채택
- "adopted_b" — 기존 정의를 표준으로 채택 (기존 정의가 여러 개면 가장 타당한 것 기준)
- "merged" — 두 정의를 통합한 새 표준 정의 생성
- "wontfix" — 부서별 정의 차이를 허용 (예: 규제 목적상 서로 다른 개념이 맞는 경우)

판단 시 규제·회계 기준과의 정합성(예: 분모 개념이 감독규정상 정의와 일치하는지)을 우선 고려하세요.
확신이 서지 않으면 confidence를 "low"로 낮추고 wontfix 또는 보수적인 선택을 하세요.

JSON만 응답하세요:
{{
  "resolution": "adopted_a"|"adopted_b"|"merged"|"wontfix",
  "rationale": "한국어 근거 설명 (2-4문장)",
  "confidence": "low"|"medium"|"high",
  "merged_definition": {{"formula_normalized": "...", "numerator": "...", "denominator": "...", "grain": "...", "description": "..."}} 또는 resolution이 "merged"가 아니면 null
}}"""

    msg = _get_client().chat.completions.create(
        model="gpt-4o",
        trace_id=trace_id,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.choices[0].message.content.strip()
    if "```" in text:
        text = text.split("```")[1].split("```")[0].removeprefix("json").strip()

    data = json.loads(text)
    return Recommendation(**data)
