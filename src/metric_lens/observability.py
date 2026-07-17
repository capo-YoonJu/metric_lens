from __future__ import annotations

from dotenv import load_dotenv
from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

load_dotenv()


def trace_id_for_thread(thread_id: str) -> str:
    """Deterministic Langfuse trace id derived from a graph thread_id.

    LangGraph runs sync nodes off the event-loop thread, which breaks OTel
    contextvar propagation into plain (non-LangChain) calls like the raw
    OpenAI SDK. Nodes must pass this id explicitly as `trace_id=` on OpenAI
    calls (see langfuse.openai) so generations land in the same trace as the
    graph run instead of spawning their own orphan trace.
    """
    return Langfuse.create_trace_id(seed=thread_id)


def get_langfuse_handler(thread_id: str) -> CallbackHandler:
    return CallbackHandler(trace_context={"trace_id": trace_id_for_thread(thread_id)})


def flush_langfuse() -> None:
    get_client().flush()
