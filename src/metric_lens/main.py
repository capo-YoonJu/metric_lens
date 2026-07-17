from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from metric_lens import observability
from metric_lens.graph import build_graph
from metric_lens.models import ConflictStatus, HumanDecision, IngestRequest
from metric_lens.registry import sqlite_store

DB_PATH = Path("metric_lens.db")
CHECKPOINT_DB = Path("checkpoints.db")
STATIC_DIR = Path(__file__).parent / "static"

_graph = None
_checkpointer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _checkpointer
    sqlite_store.init_db(DB_PATH)
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as checkpointer:
        _checkpointer = checkpointer
        _graph = build_graph(checkpointer=checkpointer)
        yield
    observability.flush_langfuse()


app = FastAPI(title="MetricLens", version="0.1.0", lifespan=lifespan)


@app.post("/metrics/ingest")
async def ingest_metric(request: IngestRequest):
    thread_id = str(uuid4())
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [observability.get_langfuse_handler(thread_id)],
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_tags": ["metric-lens", "ingest", request.department],
        },
    }
    state_input = {
        "thread_id": thread_id,
        "raw_input": request.content,
        "source_type": request.source_type,
        "department": request.department,
        "langfuse_trace_id": observability.trace_id_for_thread(thread_id),
    }

    try:
        result = await _graph.ainvoke(state_input, config=config)
    except GraphInterrupt:
        result = {}

    # Detect HITL pause
    snapshot = await _graph.aget_state(config)
    if snapshot.next:
        conflicts = result.get("conflicts") or []
        return {
            "status": "awaiting_review",
            "thread_id": thread_id,
            "metric": result.get("metric"),
            "conflicts": conflicts,
            "recommendation": result.get("recommendation"),
            "message": (
                f"충돌 {len(conflicts)}건 발견. "
                f"POST /conflicts/{thread_id}/resume 으로 결정을 입력하세요."
            ),
        }

    return {"status": "completed", "thread_id": thread_id, **result.get("response", {})}


@app.post("/conflicts/{thread_id}/resume")
async def resume_conflict(thread_id: str, decision: HumanDecision):
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [observability.get_langfuse_handler(thread_id)],
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_tags": ["metric-lens", "resume"],
        },
    }

    snapshot = await _graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(
            status_code=404,
            detail=f"thread_id '{thread_id}'에 대기 중인 충돌 검토가 없습니다.",
        )

    try:
        result = await _graph.ainvoke(Command(resume=decision.model_dump(mode="json")), config=config)
    except GraphInterrupt:
        raise HTTPException(status_code=500, detail="그래프 재개 중 오류가 발생했습니다.")

    return {"status": "resolved", "thread_id": thread_id, **result.get("response", {})}


@app.get("/conflicts")
async def list_conflicts(status: str | None = None):
    conflict_status = ConflictStatus(status) if status else None
    return sqlite_store.get_conflicts(status=conflict_status)


@app.get("/metrics")
async def list_metrics():
    standards = sqlite_store.get_all_standards()
    result = []
    for m in sqlite_store.get_all_metrics():
        d = m.model_dump()
        standard_departments = {s["department"] for s in standards.get(m.name, [])}
        d["is_standard"] = m.department in standard_departments
        result.append(d)
    return result


@app.get("/runs")
async def list_runs(limit: int = 100):
    return sqlite_store.get_runs(limit=limit)


@app.get("/runs/{thread_id}")
async def get_run_detail(thread_id: str):
    run = sqlite_store.get_run(thread_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"thread_id '{thread_id}'를 찾을 수 없습니다.")
    return {
        "run": run,
        "events": sqlite_store.get_run_events(thread_id),
        "conflicts": sqlite_store.get_conflicts_by_thread(thread_id),
    }


# Static test UI — mounted last so it only catches paths not matched above.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
