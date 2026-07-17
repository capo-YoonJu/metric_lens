# 📐 MetricLens

금융 지표(NIM, 연체율, BIS비율 등)의 정의를 부서별 자유 입력(자연어/SQL/Excel)에서 표준 형식으로 정규화하고,
부서 간 지표 정의 충돌을 탐지해 **사람이 최종 결정을 내리는(HITL)** LangGraph 에이전트입니다.

> 도메인 용어(지표 정의, 충돌 유형, 분모/분자 개념 구분 등)의 전체 정의는 [CONTEXT.md](CONTEXT.md) 참고.

## 🤔 왜 필요한가

같은 이름의 지표라도 부서마다 분모 개념(`총여신` vs `채권잔액`)이나 집계 단위(`monthly` vs `quarterly`)를
다르게 정의하는 경우가 있습니다. MetricLens는 이런 불일치를 등록 시점에 잡아내고, LLM이 표준안을 제안하되
최종 채택 여부는 항상 사람이 결정하도록 강제합니다.

## 🔀 아키텍처: LangGraph 흐름

```
ingest → normalize → store → conflict_detect ─[충돌 없음]───────────────┐
                                    │                                    │
                              [충돌 있음]                                │
                                    ▼                                    ▼
                                recommend → human_review*(interrupt) → resolve → report → END
```

`*` `human_review`는 `langgraph.types.interrupt()`로 그래프를 일시 정지시킵니다. 사람이
`POST /conflicts/{thread_id}/resume`으로 결정을 입력하면 `AsyncSqliteSaver` 체크포인트(`checkpoints.db`)에서
정확히 멈춘 지점부터 재개됩니다.

### 노드별 역할

| 노드 | 파일 | 역할 |
|---|---|---|
| `ingest` | [ingest.py](src/metric_lens/nodes/ingest.py) | 상태 초기화 |
| `normalize` | [normalize.py](src/metric_lens/nodes/normalize.py) | GPT-4o `tool_choice`로 원본 입력을 `MetricDefinition`으로 추출, 수식은 Python AST로 파싱 |
| `store` | [store.py](src/metric_lens/nodes/store.py) | SQLite(메타데이터) + Chroma(임베딩)에 저장 |
| `conflict_detect` | [conflict_detect.py](src/metric_lens/nodes/conflict_detect.py) | 결정론적(수식/grain/filter) + 개념 비교(분자·분모 LLM 판단) + 확률론적(이름 다른 유사 지표 LLM 비교) 3단계로 충돌 탐지 |
| `recommend` | [recommend.py](src/metric_lens/nodes/recommend.py) | 탐지된 충돌에 대해 LLM이 표준안(`adopted_a`/`adopted_b`/`merged`/`wontfix`)을 자문 제안 (자동 반영 아님) |
| `human_review` | [human_review.py](src/metric_lens/nodes/human_review.py) | `interrupt()`로 중단, 사람의 결정 대기 |
| `resolve` | [resolve.py](src/metric_lens/nodes/resolve.py) | 사람 결정을 충돌 이력에 반영하고, 지표 레지스트리의 "표준" 포인터를 갱신 |
| `report` | [report.py](src/metric_lens/nodes/report.py) | 최종 응답 조립, 실행 상태(`runs`)를 `completed`로 기록 |

충돌이 없으면 `recommend`/`human_review`/`resolve`를 건너뛰고 바로 `report`로 갑니다.

## 🔍 충돌 탐지 3단계

1. **결정론적** ([conflict/deterministic.py](src/metric_lens/conflict/deterministic.py)) — 같은 이름·다른 부서 지표를 수식 AST, grain, filter로 직접 비교
2. **개념 비교** ([conflict/concept_compare.py](src/metric_lens/conflict/concept_compare.py)) — 분자/분모 자유 텍스트가 다를 때, 단순 표현 차이인지 실제 범위가 다른 개념인지 LLM이 판단 (`denominator_diff`/`numerator_diff`)
3. **확률론적** ([conflict/probabilistic.py](src/metric_lens/conflict/probabilistic.py)) — Chroma 임베딩으로 찾은, 이름은 다르지만 의미가 유사한 지표를 LLM이 비교 (`synonym`/`semantic_diff`)

지표 이름에 이미 "표준" 부서가 지정돼 있으면, 새 등록은 과거 전체 이력이 아니라 **현재 표준 부서와만** 비교합니다 (ADR-0009).

## HITL 결정이 레지스트리에 반영되는 방식

`resolve` 노드는 원본 `MetricDefinition`을 수정하지 않고, `metric_standards` 테이블에 "이 지표는 어느 부서 정의가
표준인지"를 가리키는 포인터만 갱신합니다 (ADR-0007).

- `adopted_a` / `adopted_b` — 한쪽 부서 정의를 표준으로 교체
- `merged` — LLM 추천의 `merged_definition`을 반영한 새 레코드를 합성 부서(`표준(병합)`)로 저장 후 표준 지정
- `wontfix` — 표준을 교체하지 않고 관련 부서 전부를 표준 집합에 누적 (부서별 정의 차이를 허용)

## 🔌 API 엔드포인트

| 메서드/경로 | 설명 |
|---|---|
| `POST /metrics/ingest` | 지표 등록 (그래프 실행, 충돌 있으면 `awaiting_review` 반환) |
| `POST /conflicts/{thread_id}/resume` | HITL 재개 — 사람의 결정 입력 |
| `GET /conflicts` | 충돌 목록 (상태 필터 가능) |
| `GET /metrics` | 등록된 전체 지표 (표준 여부 포함) |
| `GET /runs` | 실행 이력 목록 |
| `GET /runs/{thread_id}` | 실행 상세 (이벤트 로그 + 관련 충돌) |
| `/` | 정적 테스트 UI ([static/](src/metric_lens/static)) |

## 🗄️ 저장소 구조

- **SQLite** (`metric_lens.db`) — `metrics`, `conflicts`, `runs`, `run_events`(노드별 감사 로그), `metric_standards`
- **Chroma** (`chroma_db/`) — `formula_normalized` + `description` 임베딩, 의미 유사도 검색용
- **Langfuse** — 그래프 실행(`thread_id`)과 1:1로 매핑되는 트레이스에 모든 LLM 호출 기록 ([observability.py](src/metric_lens/observability.py))

## 🛠️ 기술 스택

LangGraph · FastAPI · OpenAI(GPT-4o, function calling) · sentence-transformers(`all-MiniLM-L6-v2`) · ChromaDB · Pydantic · Langfuse

## 🚀 실행 방법

```bash
# 의존성 설치
uv pip install -e ".[dev]"   # 또는 pip install -e ".[dev]"

# 환경변수 설정
cp .env.example .env
# .env에 OPENAI_API_KEY, (선택) LANGFUSE_* 값 채우기

# 서버 실행
uvicorn metric_lens.main:app --reload
```

`http://localhost:8000/` 에서 정적 테스트 UI로 지표 등록·충돌 검토 흐름을 바로 확인할 수 있습니다.

## 📚 문서

- [CONTEXT.md](CONTEXT.md) — 도메인 용어집 (지표 정의, 충돌 유형, 은행 지표 예시)
- [docs/adr/](docs/adr/) — 아키텍처 결정 기록 (0001~0009)
- [docs/agents/](docs/agents/) — 에이전트용 운영 가이드 (이슈 트래커, 트리아지 라벨, 도메인 문서 규칙)
