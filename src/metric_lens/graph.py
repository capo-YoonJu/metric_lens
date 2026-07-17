from __future__ import annotations

from langgraph.graph import END, StateGraph

from metric_lens.models import AgentState
from metric_lens.nodes.conflict_detect import conflict_detect_node
from metric_lens.nodes.human_review import human_review_node
from metric_lens.nodes.ingest import ingest_node
from metric_lens.nodes.normalize import normalize_node
from metric_lens.nodes.recommend import recommend_node
from metric_lens.nodes.report import report_node
from metric_lens.nodes.resolve import resolve_node
from metric_lens.nodes.store import store_node


def _route_after_conflict(state: AgentState) -> str:
    return "recommend" if state.get("conflicts") else "report"


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("ingest", ingest_node)
    builder.add_node("normalize", normalize_node)
    builder.add_node("store", store_node)
    builder.add_node("conflict_detect", conflict_detect_node)
    builder.add_node("recommend", recommend_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("resolve", resolve_node)
    builder.add_node("report", report_node)

    builder.set_entry_point("ingest")
    builder.add_edge("ingest", "normalize")
    builder.add_edge("normalize", "store")
    builder.add_edge("store", "conflict_detect")
    builder.add_conditional_edges(
        "conflict_detect",
        _route_after_conflict,
        {"recommend": "recommend", "report": "report"},
    )
    builder.add_edge("recommend", "human_review")
    builder.add_edge("human_review", "resolve")
    builder.add_edge("resolve", "report")
    builder.add_edge("report", END)

    return builder.compile(checkpointer=checkpointer)
