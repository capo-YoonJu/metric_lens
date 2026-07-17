# ADR-0007: HITL 결정은 지표 레지스트리에 '표준 포인터'로만 반영

## 상태
Accepted — 표준이 지표당 하나만 존재한다는 전제는 [ADR-0009](0009-scope-conflict-detection-to-standard-set.md)가
대체함 (`wontfix`는 여러 표준을 누적시킬 수 있음). '원본 미변경' 원칙과
`adopted_a`/`adopted_b`/`merged`가 단일 승자로 교체하는 동작은 그대로 유효.

## 맥락
ADR-0005/0006까지 구현한 뒤에도 `resolve_node`는 `conflicts` 테이블(감사 로그)만
갱신하고 `metrics` 테이블은 전혀 건드리지 않았다. 그 결과 HITL에서 `adopted_a`를
선택해도 '등록된 지표 레지스트리'에는 부서 간 정의 차이가 그대로 남아, 검토자가
결정이 실제로 반영됐는지 확인할 방법이 없었다.

## 결정
`resolve_node`가 `metric_standards` 테이블(`metric_name` → `department` 포인터)을
갱신하도록 한다. **부서별 `MetricDefinition` 원본 행은 수정·삭제하지 않는다** —
표준 포인터만 추가/이동한다.

- `adopted_a` / `adopted_b` — 포인터를 신규/기존 정의의 `department`로 이동
- `merged` — `recommend` 노드가 만든 `merged_definition` 초안을 신규 정의의
  나머지 필드 위에 덮어써 `MERGED_STANDARD_DEPARTMENT`("표준(병합)")라는
  합성 부서 태그로 저장하고, 포인터를 거기로 이동
- `wontfix` — 포인터를 제거 (부서별 정의 차이를 명시적으로 허용하는 상태로 되돌림)
- 이름이 다른 지표 간 충돌(`synonym`/`semantic_diff`)은 포인터 대상에서 제외 —
  "서로 다른 이름의 지표 중 무엇을 표준으로 볼지"는 별도의 별칭(aliasing) 설계가
  필요한 문제라 이번 범위에 넣지 않음. 감사 로그(`conflicts` 테이블)에는 여전히
  기록됨

`conflict_detect_node`는 `MERGED_STANDARD_DEPARTMENT` 행을 비교 대상에서 제외한다 —
거버넌스가 만든 합성 표준 정의이지 실제 부서 정의가 아니므로, 새 지표 등록 시
이 행과 다시 충돌 처리되면 안 된다.

## 결과
- 부서별 이력이 100% 보존됨 — 감사·규제 대응 목적에 유리, 데이터 유실 위험 없음
- `GET /metrics` 응답에 `is_standard` 플래그가 추가되어, 레지스트리 UI가 어떤
  정의가 현재 표준인지 배지로 보여줄 수 있음
- 표준 결정을 번복해도(재검토) `metric_standards`는 `metric_name` 기준
  upsert이므로 최신 결정이 항상 이전 결정을 대체함
- 트레이드오프: `merged`는 완전히 새 `MetricDefinition` 행을 만들기 때문에
  "행을 건드리지 않는다"는 원칙에서 유일한 예외 — 다만 이 행은 어느 부서의
  것도 아닌 신규 합성 행이라 기존 부서 데이터는 영향받지 않음
