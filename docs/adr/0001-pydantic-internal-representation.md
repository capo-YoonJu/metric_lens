# ADR-0001: 내부 표현으로 커스텀 Pydantic 모델 사용

## 상태
Accepted

## 맥락
입력이 자연어·SQL·Excel 세 가지 형식으로 들어오고, 출력은 dbt MetricFlow YAML이어야 한다.
충돌 탐지는 입력 형식에 무관하게 동일한 필드를 비교해야 한다.

## 결정
에이전트 내부 표준 표현으로 커스텀 Pydantic 모델(`MetricDefinition`)을 사용한다.
dbt MetricFlow YAML과 기타 포맷은 렌더링 출력으로만 취급한다.

## 결과
- 충돌 탐지 로직이 입력 형식에 독립적이다
- 렌더 타겟(MetricFlow, Cube 등)을 나중에 추가해도 탐지 로직을 수정하지 않아도 된다
- LLM이 `tool_use`로 Pydantic 스키마를 직접 채운다
