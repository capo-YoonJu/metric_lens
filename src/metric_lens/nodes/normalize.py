from __future__ import annotations

import ast as pyast

import json

from langfuse.openai import OpenAI

from metric_lens.models import AgentState, MetricDefinition
from metric_lens.registry import sqlite_store

_client: OpenAI | None = None

_TOOL = {
    "type": "function",
    "function": {
    "name": "create_metric_definition",
    "description": "금융 지표 정의를 표준 MetricDefinition 형식으로 변환합니다.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "지표 식별자 (영문 snake_case, 예: nim, delinquency_rate)",
            },
            "label": {"type": "string", "description": "표시 이름 (한국어 가능)"},
            "description": {"type": "string", "description": "지표 설명"},
            "formula_raw": {"type": "string", "description": "입력 원본 수식"},
            "formula_normalized": {
                "type": "string",
                "description": "표준 영문 변수명 수식 (예: net_interest_income / interest_earning_assets)",
            },
            "grain": {
                "type": "string",
                "enum": ["daily", "monthly", "quarterly", "annual"],
            },
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "enum": ["eq", "ne", "gt", "lt", "gte", "lte", "in", "not_in"],
                        },
                        "value": {},
                    },
                    "required": ["field", "operator", "value"],
                },
            },
            "numerator": {
                "type": "string",
                "description": "분자 개념 (한국어, 예: 연체채권, 순이자수익)",
            },
            "denominator": {
                "type": "string",
                "description": "분모 개념 (한국어, 예: 총여신, 여신잔액, 이자수익자산)",
            },
        },
        "required": ["name", "label", "formula_raw", "formula_normalized", "grain"],
    },
    },
}


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _parse_ast(formula: str) -> dict | None:
    try:
        tree = pyast.parse(formula, mode="eval")
        return _node_to_dict(tree.body)
    except SyntaxError:
        return None


def _node_to_dict(node: pyast.AST | list | object) -> object:
    if isinstance(node, pyast.AST):
        return {
            "_type": node.__class__.__name__,
            **{f: _node_to_dict(v) for f, v in pyast.iter_fields(node)},
        }
    if isinstance(node, list):
        return [_node_to_dict(n) for n in node]
    return node


def normalize_node(state: AgentState) -> dict:
    response = _get_client().chat.completions.create(
        model="gpt-4o",
        trace_id=state.get("langfuse_trace_id"),
        tools=[_TOOL],
        tool_choice={"type": "function", "function": {"name": "create_metric_definition"}},
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 금융 지표 정의 표준화 전문가입니다. "
                    "입력된 지표 정의를 분석하여 create_metric_definition 도구를 호출하세요. "
                    "formula_normalized는 반드시 영문 snake_case 변수명을 사용하세요. "
                    "numerator/denominator는 수식의 분자·분모 개념을 한국어로 명시하세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"부서: {state['department']}\n"
                    f"입력 형식: {state['source_type']}\n"
                    f"내용:\n{state['raw_input']}"
                ),
            },
        ],
    )

    tool_call = response.choices[0].message.tool_calls[0]
    fields: dict = json.loads(tool_call.function.arguments)

    metric = MetricDefinition(
        name=fields["name"],
        label=fields["label"],
        description=fields.get("description", ""),
        formula_raw=fields["formula_raw"],
        formula_normalized=fields["formula_normalized"],
        formula_ast=_parse_ast(fields["formula_normalized"]),
        grain=fields["grain"],
        dimensions=fields.get("dimensions", []),
        filters=fields.get("filters", []),
        numerator=fields.get("numerator"),
        denominator=fields.get("denominator"),
        department=state["department"],
        source_type=state["source_type"],
        source_raw=state["raw_input"],
    )
    sqlite_store.record_event(
        state["thread_id"], "normalize",
        f"LLM 정규화 완료 — {metric.name} ({metric.label}), grain={metric.grain}",
        detail={
            "formula_normalized": metric.formula_normalized,
            "numerator": metric.numerator,
            "denominator": metric.denominator,
            "grain": metric.grain,
            "dimensions": metric.dimensions,
        },
    )
    return {"metric": metric.model_dump()}
