# ADR-0004: 충돌 탐지를 ingest 시점에 실시간으로 실행

## 상태
Accepted

## 맥락
"검토용으로 올려주는" 에이전트 목적에서 ingest와 충돌 탐지는 연결된 흐름이어야 한다.

## 결정
단일 LangGraph 그래프 `ingest → normalize → store → conflict_detect → report`로 구성.
새 지표 등록 시마다 전체 레지스트리와 즉시 비교한다.

## 결과
- ingest 요청자가 응답에서 즉시 충돌 결과 확인 가능
- 충돌 이력은 SQLite에 별도 저장, `GET /conflicts`로 조회
- 레지스트리 규모가 수백 개 이상으로 커지면 배치 전환 검토 필요
