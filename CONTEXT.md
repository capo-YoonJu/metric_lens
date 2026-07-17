# MetricLens — Domain Context

금융 지표의 시맨틱 레이어 정의를 표준화하고, 부서 간 지표 정의 충돌을 탐지·검토하는 에이전트.

## 핵심 개념 (Glossary)

### MetricDefinition (지표 정의)
에이전트 내부의 표준 표현. 자연어·SQL·Excel로 들어온 지표 정의를 정규화한 결과물.
Pydantic 모델로 구현. **동의어 금지: 지표 스펙, 지표 모델.**

필드:
- `name` — 지표 고유 식별자 (영문 snake_case)
- `label` — 표시 이름 (한국어 가능)
- `formula_raw` — 입력 원본 수식 문자열
- `formula_normalized` — 표준 변수명으로 치환한 수식 (`net_interest_income / interest_earning_assets`)
- `formula_ast` — 파싱된 AST (dict). 파싱 실패 시 None
- `grain` — 시간 집계 단위: `daily` | `monthly` | `quarterly` | `annual`
- `dimensions` — 분석 차원 목록
- `filters` — 필터 조건 목록
- `numerator` — 분자 개념 (예: `연체채권`)
- `denominator` — 분모 개념 (예: `총여신`, `여신잔액`, `채권잔액` — 충돌 탐지의 핵심)
- `department` — 정의 출처 부서
- `source_type` — 입력 형식: `natural_language` | `sql` | `excel`
- `source_raw` — 원본 입력 텍스트

### Metric Registry (지표 레지스트리)
등록된 모든 MetricDefinition의 저장소.
- SQLite: 메타데이터 전체 저장
- Chroma: `formula_normalized` + `description` 임베딩 저장 (의미 유사도 검색용)

### Conflict (충돌)
같은 지표 이름 또는 동일 의미를 가진 지표가 부서마다 다르게 정의된 상태.

세 가지 탐지 경로:
- **결정론적 충돌** — 구조적 필드 직접 비교 (수식 AST, grain, filter)
- **개념 비교** — 같은 이름 지표의 분자/분모 자유 텍스트를 LLM이 의미상 같은
  개념인지 판단 (ADR-0008). 문자열이 다를 때만 호출되며, "총여신" vs "전체
  여신 잔액"처럼 표현만 다른 경우는 충돌로 보지 않음
- **확률론적 충돌** — LLM 의미 비교 (이름이 다른 지표 간 동의어 탐지, 미묘한
  정의 불일치)

충돌 유형:
- `formula_mismatch` — 같은 이름, 다른 수식
- `grain_mismatch` — 집계 단위 불일치
- `filter_diff` — 필터 포함/제외 차이
- `denominator_diff` — 분모 개념 차이, LLM 판단 (예: `여신잔액` vs `채권잔액`).
  `총여신` vs `전체 여신 잔액`처럼 표현만 다른 동의어는 충돌 아님
- `numerator_diff` — 분자 개념 차이, LLM 판단 (denominator_diff와 동일한 방식)
- `synonym` — 이름은 다른데 같은 지표
- `semantic_diff` — 미묘한 정의 불일치 (LLM 탐지)

### Conflict Resolution (충돌 해결)
검토자가 충돌을 처리한 결과. 이력 추적 목적으로 감사 로그에 보존.

resolution 유형:
- `wontfix` — 해결 안 함 (부서별 정의 차이 허용) → 신규 등록 부서 + 비교
  대상이 된 기존 부서(들) 모두를 표준 집합에 **추가** (기존 표준 유지, ADR-0009)
- `adopted_a` — 첫 번째 부서 정의 채택 → 표준 집합을 해당 부서 하나로 **교체**
- `adopted_b` — 두 번째 부서 정의 채택 → 표준 집합을 해당 부서 하나로 **교체**
- `merged` — 두 정의를 통합한 새 정의 생성 → `표준(병합)`이라는 합성 부서에
  새 정의를 만들고 표준 집합을 그 부서 하나로 **교체**

### Standard Pointer (표준 포인터)
`resolve` 노드가 HITL 결정을 반영하는 방식. **부서별 `MetricDefinition` 원본은
절대 수정·삭제하지 않고**, `metric_standards` 테이블에 `지표 이름 → 부서` 포인터만
추가/이동한다 (ADR-0007). 지표 하나가 **여러 개의 표준 부서를 동시에** 가질 수
있다 (`wontfix`가 누적시키는 경우, ADR-0009) — `PRIMARY KEY (metric_name, department)`.
레지스트리 조회(`GET /metrics`)는 각 정의에 `is_standard` 플래그를 붙여 UI가
배지로 표시할 수 있게 한다.

- 이름이 같고 부서만 다른 충돌(`formula_mismatch`, `grain_mismatch`,
  `filter_diff`, `denominator_diff`, `numerator_diff`)에만 적용됨
- **표준이 이미 설정된 지표는, 새로 등록되는 정의를 표준 부서(들)와만
  비교한다** — 과거에 이미 검토·기각된 부서 정의와는 재비교하지 않음
  (ADR-0009). 표준이 아직 없는 지표 이름은 기존처럼 모든 부서 정의와 비교
- 이름이 다른 충돌(`synonym`, `semantic_diff`)은 포인터 대상 아님 — 결정은
  감사 로그에 기록되지만 레지스트리 포인터는 갱신되지 않음 (별도 별칭 설계 필요)

### HITL (Human-in-the-Loop) 검토
충돌이 탐지되면 그래프가 `human_review` 노드에서 일시 중단(interrupt)된다.
사람이 결정을 입력하면 그래프가 재개(resume)되어 `resolve → report` 노드로 진행한다.

- **중단 조건**: `conflict_detect` 노드에서 하나 이상의 충돌이 발견된 경우
- **통과 조건**: 충돌 없으면 `human_review` 건너뛰고 즉시 `report`로 진행
- **중단 상태 저장**: `langgraph-checkpoint-sqlite`가 thread_id별로 그래프 상태를 보존
- **재개 입력**: `{ "resolution": "adopted_a"|"adopted_b"|"merged"|"wontfix", "note": "...", "resolved_by": "..." }`
- **재개 API**: `POST /conflicts/{thread_id}/resume`

### Recommendation (추천안)
`recommend` 노드가 `human_review` 직전에 생성하는 LLM 제안. **자문(advisory)일 뿐
결정이 아니다** — 결정 권한은 항상 사람에게 있다 (ADR-0005, ADR-0006).

필드: `resolution`(Resolution Type과 동일한 값 집합), `rationale`(한국어 근거),
`confidence`(low/medium/high), `merged_definition`(resolution이 `merged`일 때만 초안 제공).

HITL 검토 폼에서 이 추천값이 기본 선택값으로 채워지지만, 검토자가 제출하기
전까지는 아무 것도 확정되지 않으며 언제든 다른 선택지로 바꿀 수 있다.

### Semantic Layer (시맨틱 레이어)
비즈니스 지표의 정의·계산식·차원을 코드로 표준화한 레이어.
이 프로젝트의 표준 출력 포맷은 **dbt MetricFlow YAML**.

### Grain (집계 단위)
지표가 의미를 갖는 최소 시간 단위. `daily` | `monthly` | `quarterly` | `annual`.
같은 지표라도 grain이 다르면 충돌로 탐지.

### 주요 은행 지표

| 지표 | 영문 | 분자 | 분모 | 일반적 grain |
|------|------|------|------|------|
| NIM (순이자마진) | Net Interest Margin | 이자수익 - 이자비용 | 이자수익자산 | quarterly |
| 연체율 | Delinquency Rate | 연체채권 | 총여신 | monthly |
| BIS비율 | BIS Capital Ratio | 자기자본 | 위험가중자산 | quarterly |
| LCR (유동성커버리지비율) | Liquidity Coverage Ratio | 고유동성자산 | 순현금유출액 | monthly |

### 분모 개념 구분 (충돌 탐지 핵심)
- `총여신` — 은행이 대출한 전체 여신 잔액
- `여신잔액` — 특정 시점의 대출 잔액 (총여신과 범위 다를 수 있음)
- `채권잔액` — 채권(bond) 포트폴리오 잔액. 여신과 다른 개념

**같은 지표에서 분모로 `총여신`을 쓰는 부서와 `채권잔액`을 쓰는 부서는 반드시 `denominator_diff` 충돌로 처리.**
(단, `총여신`을 `전체 여신 잔액`처럼 다르게 표현만 한 경우는 개념이 같으므로 충돌 아님 — ADR-0008)

## LangGraph 그래프 구조

```
                                    ┌─ [충돌 없음] ────────────────────────────┐
ingest → normalize → store → conflict_detect                                 report
                                    └─ [충돌 있음] → recommend → human_review* → resolve ┘
```

`*` human_review: LangGraph `interrupt()`로 그래프 일시 중단. 사람이 `POST /conflicts/{thread_id}/resume`으로 결정 입력 시 재개.

노드별 역할:
- `ingest` — 입력 파싱, source_type 감지
- `normalize` — LLM(Sonnet 4.6, tool_use)으로 MetricDefinition 추출
- `store` — SQLite + Chroma에 저장
- `conflict_detect` — 결정론적 → 개념 비교(분자/분모) → 확률론적 순서로 충돌 탐지. 충돌 유무로 분기
- `recommend` — LLM이 표준안을 제안 (자문용, ADR-0006). 실패해도 non-fatal
- `human_review` — `interrupt()`로 중단. 검토자 결정 대기 (추천안은 기본값일 뿐)
- `resolve` — 검토자 결정을 SQLite 충돌 이력에 반영
- `report` — 최종 응답 반환 (충돌 결과 + 해결 결과 포함)

API 엔드포인트:
```
POST /metrics/ingest                    # 지표 등록 (그래프 실행)
GET  /conflicts                         # 미해결 충돌 목록
POST /conflicts/{thread_id}/resume      # HITL 재개 (사람 결정 입력)
GET  /metrics                           # 등록된 전체 지표 목록
GET  /runs                              # 실행(thread) 이력 목록
GET  /runs/{thread_id}                  # 실행 상세 — 노드별 trace + 충돌 이력
```

### 테스트용 웹 UI
`src/metric_lens/static/`에 정적 페이지(바닐라 HTML/JS)가 있고 FastAPI가 `/`에 서빙한다.
지표 등록 · HITL 검토 · 실행 내역(노드별 trace, LLM 판단 detail 포함) 3개 탭으로 구성.
`run_events` 테이블(SQLite)에 각 노드 실행마다 `record_event()`로 감사 로그를 남겨 실행 내역 탭에서 조회한다.

## 기술 스택

- **그래프 프레임워크**: LangGraph
- **API**: FastAPI
- **LLM**: GPT-4o (`function calling`)
- **임베딩**: `all-MiniLM-L6-v2` (sentence-transformers, 로컬)
- **메타데이터 저장**: SQLite
- **벡터 저장**: Chroma
- **출력 포맷**: dbt MetricFlow YAML (온디맨드)
