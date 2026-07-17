from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from metric_lens.models import ConflictResult, ConflictStatus, HumanDecision, MetricDefinition

DB_PATH = Path("metric_lens.db")

_COLS = [
    "id", "thread_id", "metric_name_a", "metric_name_b",
    "department_a", "department_b", "conflict_type", "detail",
    "status", "resolution", "note", "resolved_by",
    "created_at", "resolved_at",
    # Appended after the original columns (rather than inlined) so that
    # `ALTER TABLE ... ADD COLUMN` on pre-existing DBs — which always
    # appends physically — keeps this list in sync with `SELECT *` order.
    "recommended_resolution", "recommendation_rationale",
]

_RUN_COLS = [
    "thread_id", "department", "source_type", "raw_input",
    "metric_name", "status", "created_at", "updated_at",
]

_EVENT_COLS = ["id", "thread_id", "node", "summary", "detail", "created_at"]


def init_db(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metrics (
            name        TEXT NOT NULL,
            department  TEXT NOT NULL,
            data        TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (name, department)
        );
        CREATE TABLE IF NOT EXISTS conflicts (
            id              TEXT PRIMARY KEY,
            thread_id       TEXT,
            metric_name_a   TEXT NOT NULL,
            metric_name_b   TEXT NOT NULL,
            department_a    TEXT NOT NULL,
            department_b    TEXT NOT NULL,
            conflict_type   TEXT NOT NULL,
            detail          TEXT NOT NULL,
            status          TEXT DEFAULT 'unresolved',
            resolution      TEXT,
            note            TEXT,
            resolved_by     TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at     TIMESTAMP,
            recommended_resolution   TEXT,
            recommendation_rationale TEXT
        );
        CREATE TABLE IF NOT EXISTS runs (
            thread_id   TEXT PRIMARY KEY,
            department  TEXT NOT NULL,
            source_type TEXT NOT NULL,
            raw_input   TEXT NOT NULL,
            metric_name TEXT,
            status      TEXT NOT NULL DEFAULT 'running',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS run_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id   TEXT NOT NULL,
            node        TEXT NOT NULL,
            summary     TEXT NOT NULL,
            detail      TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS metric_standards (
            metric_name TEXT NOT NULL,
            department  TEXT NOT NULL,
            resolution  TEXT NOT NULL,
            note        TEXT,
            set_by      TEXT,
            thread_id   TEXT,
            set_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (metric_name, department)
        );
    """)
    # Migration for DBs created before recommendation columns existed —
    # CREATE TABLE IF NOT EXISTS above is a no-op on them.
    for col in ("recommended_resolution", "recommendation_rationale"):
        try:
            conn.execute(f"ALTER TABLE conflicts ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists

    # Migration for DBs created before ADR-0009 — metric_standards used to
    # have a single-column PK (one standard per metric name); wontfix now
    # needs multiple standards to coexist per metric name.
    pk_cols = [row[1] for row in conn.execute("PRAGMA table_info(metric_standards)") if row[5] > 0]
    if pk_cols == ["metric_name"]:
        conn.executescript("""
            ALTER TABLE metric_standards RENAME TO metric_standards_old;
            CREATE TABLE metric_standards (
                metric_name TEXT NOT NULL,
                department  TEXT NOT NULL,
                resolution  TEXT NOT NULL,
                note        TEXT,
                set_by      TEXT,
                thread_id   TEXT,
                set_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (metric_name, department)
            );
            INSERT INTO metric_standards
                (metric_name, department, resolution, note, set_by, thread_id, set_at)
                SELECT metric_name, department, resolution, note, set_by, thread_id, set_at
                FROM metric_standards_old;
            DROP TABLE metric_standards_old;
        """)
    conn.commit()
    conn.close()


def save_metric(metric: MetricDefinition, db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO metrics (name, department, data) VALUES (?, ?, ?)",
        (metric.name, metric.department, metric.model_dump_json()),
    )
    conn.commit()
    conn.close()


def get_all_metrics(db_path: Path = DB_PATH) -> list[MetricDefinition]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT data FROM metrics").fetchall()
    conn.close()
    return [MetricDefinition.model_validate_json(r[0]) for r in rows]


def get_metrics_by_name(name: str, db_path: Path = DB_PATH) -> list[MetricDefinition]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT data FROM metrics WHERE name = ?", (name,)).fetchall()
    conn.close()
    return [MetricDefinition.model_validate_json(r[0]) for r in rows]


def save_conflict(conflict: ConflictResult, db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO conflicts
           (id, thread_id, metric_name_a, metric_name_b, department_a, department_b,
            conflict_type, detail, status, resolution, note, resolved_by,
            recommended_resolution, recommendation_rationale)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            conflict.id, conflict.thread_id,
            conflict.metric_name_a, conflict.metric_name_b,
            conflict.department_a, conflict.department_b,
            conflict.conflict_type.value, conflict.detail,
            conflict.status.value,
            conflict.resolution.value if conflict.resolution else None,
            conflict.note, conflict.resolved_by,
            conflict.recommended_resolution.value if conflict.recommended_resolution else None,
            conflict.recommendation_rationale,
        ),
    )
    conn.commit()
    conn.close()


def get_conflicts(
    status: ConflictStatus | None = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    conn = sqlite3.connect(db_path)
    if status:
        rows = conn.execute(
            "SELECT * FROM conflicts WHERE status = ? ORDER BY created_at DESC",
            (status.value,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conflicts ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(zip(_COLS, r)) for r in rows]


def get_conflicts_by_thread(thread_id: str, db_path: Path = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT * FROM conflicts WHERE thread_id = ? ORDER BY created_at ASC",
        (thread_id,),
    ).fetchall()
    conn.close()
    return [dict(zip(_COLS, r)) for r in rows]


def create_run(
    thread_id: str,
    department: str,
    source_type: str,
    raw_input: str,
    db_path: Path = DB_PATH,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO runs (thread_id, department, source_type, raw_input, status)
           VALUES (?, ?, ?, ?, 'running')""",
        (thread_id, department, source_type, raw_input),
    )
    conn.commit()
    conn.close()


def update_run_status(
    thread_id: str,
    status: str,
    metric_name: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    conn = sqlite3.connect(db_path)
    if metric_name is not None:
        conn.execute(
            """UPDATE runs SET status = ?, metric_name = ?, updated_at = CURRENT_TIMESTAMP
               WHERE thread_id = ?""",
            (status, metric_name, thread_id),
        )
    else:
        conn.execute(
            "UPDATE runs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE thread_id = ?",
            (status, thread_id),
        )
    conn.commit()
    conn.close()


def record_event(
    thread_id: str,
    node: str,
    summary: str,
    detail: object | None = None,
    db_path: Path = DB_PATH,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO run_events (thread_id, node, summary, detail) VALUES (?, ?, ?, ?)",
        (thread_id, node, summary, json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None),
    )
    conn.commit()
    conn.close()


def get_runs(limit: int = 100, db_path: Path = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(zip(_RUN_COLS, r)) for r in rows]


def get_run(thread_id: str, db_path: Path = DB_PATH) -> dict | None:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT * FROM runs WHERE thread_id = ?", (thread_id,)).fetchone()
    conn.close()
    return dict(zip(_RUN_COLS, row)) if row else None


def get_run_events(thread_id: str, db_path: Path = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT * FROM run_events WHERE thread_id = ? ORDER BY id ASC", (thread_id,)
    ).fetchall()
    conn.close()
    events = [dict(zip(_EVENT_COLS, r)) for r in rows]
    for e in events:
        if e["detail"]:
            e["detail"] = json.loads(e["detail"])
    return events


_STANDARD_COLS = ["metric_name", "department", "resolution", "note", "set_by", "thread_id", "set_at"]


def set_standard(
    metric_name: str,
    department: str,
    resolution: str,
    note: str | None,
    set_by: str | None,
    thread_id: str | None,
    db_path: Path = DB_PATH,
) -> None:
    """Adds `department` to metric_name's standard set (ADR-0007/0009).
    Does not touch any MetricDefinition row or any other department's
    standard entry — this only adds/updates one (metric_name, department)
    pointer. A metric can have more than one standard at once (e.g. after a
    'wontfix' decision) — see replace_standards() for the exclusive case."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO metric_standards
           (metric_name, department, resolution, note, set_by, thread_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (metric_name, department, resolution, note, set_by, thread_id),
    )
    conn.commit()
    conn.close()


def clear_standards(metric_name: str, db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM metric_standards WHERE metric_name = ?", (metric_name,))
    conn.commit()
    conn.close()


def replace_standards(
    metric_name: str,
    department: str,
    resolution: str,
    note: str | None,
    set_by: str | None,
    thread_id: str | None,
    db_path: Path = DB_PATH,
) -> None:
    """Clears every existing standard for metric_name and sets exactly one —
    used by adopted_a/adopted_b/merged, which each pick a single winner and
    supersede whatever was standard before (ADR-0009)."""
    clear_standards(metric_name, db_path)
    set_standard(metric_name, department, resolution, note, set_by, thread_id, db_path)


def get_standards(metric_name: str, db_path: Path = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT * FROM metric_standards WHERE metric_name = ?", (metric_name,)
    ).fetchall()
    conn.close()
    return [dict(zip(_STANDARD_COLS, r)) for r in rows]


def get_all_standards(db_path: Path = DB_PATH) -> dict[str, list[dict]]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM metric_standards").fetchall()
    conn.close()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(zip(_STANDARD_COLS, r))
        grouped.setdefault(d["metric_name"], []).append(d)
    return grouped
