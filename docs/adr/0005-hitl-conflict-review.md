# ADR-0005: 충돌 발견 시 HITL로 표준안 결정

## 상태
Accepted

## 맥락
충돌 탐지 후 표준안(어느 부서 정의를 채택할지)을 자동으로 결정하는 것은 금융 도메인에서 위험하다.
은행 지표 정의는 규제·회계 기준에 영향을 미치므로 사람이 최종 의사결정을 해야 한다.

ADR-0004의 실시간 탐지 설계를 유지하면서 의사결정 단계만 HITL로 분리한다.

## 결정
충돌이 탐지되면 LangGraph `interrupt()`로 그래프를 중단하고, 사람이 결정을 입력할 때까지 대기한다.

```
conflict_detect → [충돌 있음] → human_review (interrupt) → resolve → report
               → [충돌 없음] → report
```

- 중단 상태는 `langgraph-checkpoint-sqlite`가 thread_id별로 보존
- 재개: `POST /conflicts/{thread_id}/resume` + `{ resolution, note, resolved_by }`
- 충돌 없는 지표는 human_review를 건너뛰고 즉시 통과

## 결과
- 표준안 결정 권한이 사람에게 있음 (규제 감사 대응 가능)
- 그래프 실행이 사람 응답 전까지 멈추므로 FastAPI는 비동기(async) 처리 필요
- `thread_id`로 중단된 그래프를 식별하므로, `/conflicts` 목록에 thread_id 포함
- 충돌 없는 경우 latency 변화 없음
