# ADR-0008: 분자/분모 비교에 LLM 개념 판단 도입

## 상태
Accepted

## 맥락
같은 이름의 지표를 부서마다 다르게 등록해도 `denominator`/`numerator`는
`normalize` 노드가 원본 입력에서 그대로 뽑아낸 한국어 자유 텍스트다
([normalize.py](../../src/metric_lens/nodes/normalize.py)). 기존
`deterministic.py`는 이 필드를 문자열 `!=` 비교로 충돌 판정했는데, 그 결과
"총여신"과 "전체 여신 잔액"처럼 **표현만 다른 동의어**도 매번 `denominator_diff`로
플래그됐다. 정작 이 검사가 잡아야 하는 건 "총여신" vs "채권잔액"처럼 **범위 자체가
다른 개념**이다 (`CONTEXT.md` "분모 개념 구분" 참고).

같은 이름 지표는 `conflict_detect_node`에서 확률론적(임베딩+LLM) 경로를
건너뛰도록 되어 있어서 ([conflict_detect.py](../../src/metric_lens/nodes/conflict_detect.py)
`if meta["name"] == new.name: continue`), 이 동의어 문제가 LLM 판단을 아예
타지 못했다.

## 결정
`denominator`/`numerator` 비교를 새 모듈 `conflict/concept_compare.py`로
분리하고, 문자열이 다를 때만(동일 문자열은 LLM 호출 없이 스킵) LLM에게
"표현 차이인지 실제 개념 차이인지" 판단시킨다.

- `same_concept=true` → 충돌 아님 (판단 근거는 `run_events`에 감사 로그로 남음)
- `same_concept=false` → `denominator_diff`/`numerator_diff` 충돌 발생
- LLM 호출 실패 → **보수적으로 충돌 처리** (probabilistic.py의 "실패 시 스킵"과
  다른 정책). 이 검사가 대체한 기존 문자열 비교는 100% 안정적이었으므로, LLM
  실패라는 새 실패 모드가 탐지 신뢰도를 이전보다 낮추면 안 된다는 판단
- `numerator`는 기존엔 아예 비교 대상이 아니었음 — 이번에 같이 추가

`deterministic.py`는 구조적 필드(수식 AST, grain, filter)만 남기고
`denominator_diff` 체크를 제거했다.

## 결과
- 부서 간 표현 차이로 인한 오탐(false positive)이 줄어, HITL 검토 큐에 실제
  검토가 필요한 건만 올라옴
- `numerator_diff`가 새 `ConflictType`으로 추가되어 이전엔 전혀 감지되지
  않던 분자 개념 불일치도 잡을 수 있게 됨
- LLM 호출이 늘어 ingest당 지연시간·비용 증가 (부서당 비교 1건마다 최대 2회
  추가 호출) — 레지스트리가 수백 개 규모로 커지면 배치·캐싱 검토 필요
  (ADR-0004의 우려사항과 동일한 맥락)
- 트레이드오프: LLM이 실제로는 다른 개념을 "같다"고 오판하면 조용히 넘어갈
  위험이 생김 — 프롬프트에 "확신이 서지 않으면 보수적으로 판단"을 명시했지만,
  이건 완화일 뿐 완전한 해결은 아님
