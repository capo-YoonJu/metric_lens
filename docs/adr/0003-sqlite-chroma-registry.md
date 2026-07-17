# ADR-0003: 레지스트리를 SQLite + Chroma 이중 저장소로 구성

## 상태
Accepted

## 맥락
확률론적 충돌 탐지는 의미 유사도 기반 후보 선별이 필요하다.
추가 인프라 없이 로컬에서 실행 가능해야 한다.

## 결정
- SQLite: MetricDefinition 전체 메타데이터 저장
- Chroma: `formula_normalized` + `description` 임베딩 저장
- 임베딩 모델: `all-MiniLM-L6-v2` (sentence-transformers, 로컬 실행)

## 결과
- 확률론적 탐지 패턴: Chroma에서 코사인 유사도 상위 후보 추린 뒤 LLM 검증 (비용·속도 효율)
- OpenAI 의존성 없음
- 팀 공유 필요 시 PostgreSQL + pgvector로 마이그레이션 가능
