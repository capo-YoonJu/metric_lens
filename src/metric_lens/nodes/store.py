from metric_lens.models import AgentState, MetricDefinition
from metric_lens.registry import chroma_store, sqlite_store


def store_node(state: AgentState) -> dict:
    metric = MetricDefinition(**state["metric"])
    sqlite_store.save_metric(metric)
    chroma_store.add_metric(metric)
    sqlite_store.record_event(
        state["thread_id"], "store",
        f"레지스트리 저장 완료 — {metric.name} ({metric.department})",
    )
    return {}
