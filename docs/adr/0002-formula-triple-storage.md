# ADR-0002: 수식을 raw·normalized·AST 세 필드로 저장

## 상태
Accepted

## 맥락
결정론적 충돌 탐지는 수식 비교에 의존한다.
입력 수식은 자연어·SQL·Excel 형식이 혼재하며, 파싱이 항상 성공하지 않는다.

## 결정
`formula_raw` (원본), `formula_normalized` (표준 변수명 치환), `formula_ast` (파싱 AST, 실패 시 None) 세 필드를 모두 저장한다.

## 결과
- 결정론적 비교: `formula_normalized` 문자열 비교 우선, AST 있으면 구조 비교
- 파싱 실패 시: LLM 확률론적 비교로 graceful degradation
- `numerator`/`denominator` 별도 필드: 분모 개념 차이를 LLM 없이 탐지 가능
