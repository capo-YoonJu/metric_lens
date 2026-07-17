# ADR-0006: 충돌 표준안에 대한 LLM 추천을 자문(advisory)으로 추가

## 상태
Accepted

## 맥락
ADR-0005에 따라 표준안 결정 권한은 사람에게 있다. 그러나 지금까지 LLM은 충돌을
*탐지*만 할 뿐, 검토자가 무엇을 채택할지 판단하는 데는 아무 도움을 주지 않았다.
검토자는 매번 빈 폼에서 A/B/병합/보류를 스스로 처음부터 판단해야 했다.

## 결정
충돌이 탐지되면 `human_review`의 `interrupt()` 이전에 `recommend` 노드를 추가해
LLM이 표준안 하나를 제안하게 한다.

```
conflict_detect → [충돌 있음] → recommend → human_review (interrupt) → resolve → report
               → [충돌 없음] ────────────────────────────────────────→ report
```

- `recommend`는 `resolution`(adopted_a/adopted_b/merged/wontfix), `rationale`,
  `confidence`(low/medium/high), (병합 시) `merged_definition` 초안을 생성한다.
- 이 제안은 `conflicts` 테이블(`recommended_resolution`, `recommendation_rationale`)에
  저장되고, HITL 검토 폼에서 기본 선택값으로만 반영된다. 검토자는 자유롭게 다른
  선택지로 바꿀 수 있고, 제출 전까지는 아무 것도 확정되지 않는다.
- `resolve` 노드는 여전히 사람이 제출한 `HumanDecision`만 반영한다 — LLM의
  추천값을 직접 커밋하는 경로는 없다.
- LLM 호출 실패는 non-fatal: 추천 없이 HITL이 정상 진행된다 (기존 동작과 동일).

## 결과
- 검토자는 추천안 + 근거를 먼저 보고, 동의하면 그대로 제출하거나 다른 선택지로
  바꿔 제출한다 — 결정 권한은 그대로 사람에게 있음 (ADR-0005와 상충 없음)
- 감사 로그(`run_events`)에 추천 근거가 남아, 사람이 추천을 따랐는지 벗어났는지
  나중에 확인 가능
- 그래프에 노드가 하나 늘어 `recommend` 실패 시에도 그래프가 막히지 않도록
  non-fatal 처리 필요 (probabilistic 충돌 탐지와 동일한 패턴)
