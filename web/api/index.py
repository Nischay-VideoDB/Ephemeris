"""Production Ephemeris API for Vercel.

The prepared journeys remain static.  New questions run the real VideoDB
research agent, and finished (or failed) runs are recorded in Azure Postgres
instead of a process-local directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND / "src"))

import agent  # noqa: E402
import manifest  # noqa: E402
import reel  # noqa: E402
import videodb_client as vc  # noqa: E402

app = FastAPI(title="Ephemeris live research API")


class AskInput(BaseModel):
    question: str = Field(min_length=3, max_length=400)
    idempotency_key: str | None = Field(default=None, max_length=120)


def _database_url() -> str:
    value = os.getenv("EPHEMERIS_DATABASE_URL")
    if not value:
        raise RuntimeError("EPHEMERIS_DATABASE_URL is not configured")
    return value.replace("sslmode=no-verify", "sslmode=require")


def _connect():
    return psycopg.connect(_database_url(), row_factory=dict_row)


def _init() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ephemeris_run (
                id uuid PRIMARY KEY,
                idempotency_key text UNIQUE NOT NULL,
                actor_hash text NOT NULL,
                question text NOT NULL,
                state text NOT NULL CHECK (state IN ('running','succeeded','failed')),
                result jsonb,
                error text,
                created_at timestamptz NOT NULL DEFAULT now(),
                finished_at timestamptz
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ephemeris_rate (
                actor_hash text NOT NULL,
                bucket timestamptz NOT NULL,
                requests integer NOT NULL,
                PRIMARY KEY (actor_hash, bucket)
            )
            """
        )


def _actor(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")
    secret = os.getenv("EPHEMERIS_RATE_SECRET", "ephemeris-public")
    return hashlib.sha256(f"{secret}:{ip}".encode()).hexdigest()


def _reserve(actor_hash: str) -> None:
    per_hour = int(os.getenv("EPHEMERIS_RUNS_PER_HOUR", "3"))
    daily = int(os.getenv("EPHEMERIS_RUNS_PER_DAY", "30"))
    with _connect() as conn:
        today = conn.execute(
            "SELECT count(*) AS n FROM ephemeris_run WHERE created_at >= date_trunc('day', now())"
        ).fetchone()["n"]
        if today >= daily:
            raise HTTPException(429, "Today's public live-run budget is full. Prepared journeys remain available.")
        row = conn.execute(
            """
            INSERT INTO ephemeris_rate(actor_hash, bucket, requests)
            VALUES (%s, date_trunc('hour', now()), 1)
            ON CONFLICT(actor_hash, bucket) DO UPDATE
              SET requests = ephemeris_rate.requests + 1
              WHERE ephemeris_rate.requests < %s
            RETURNING requests
            """,
            (actor_hash, per_hour),
        ).fetchone()
        if row is None:
            raise HTTPException(429, "Live research is limited to three runs per hour. Prepared journeys remain available.")


def _summary(row: dict) -> dict:
    result = row.get("result") or {}
    return {
        "id": str(row["id"]),
        "question": row["question"],
        "saved": row["created_at"].isoformat(),
        "moments": len(result.get("evidence") or []),
        "shots": len((result.get("reel") or {}).get("shots") or []),
        "answered": bool((result.get("answer") or {}).get("answer")),
        "failed": row["state"] == "failed",
    }


def _browser_safe_url(value: str) -> str:
    """Percent-encode NASA path/query text without double-encoding escapes."""
    parsed = urlsplit(value)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            quote(parsed.path, safe="/%:@"),
            quote(parsed.query, safe="=&%:@/?+"),
            quote(parsed.fragment, safe="%:@/?+"),
        )
    )


def _enrich_sources(result: dict) -> dict:
    """Attach the public NASA master to every timestamped evidence item.

    The shared VideoDB collection is intentionally borrowed read-only.  That
    means a live public run can research it but cannot always compile a new
    VideoDB reel.  The original NASA media remains public and durable, so every
    live evidence row links to the exact source time as an honest playback
    fallback rather than hiding the completed research.
    """
    sources = manifest.load()
    for item in result.get("evidence") or []:
        source = sources.get(item.get("nasa_id")) or {}
        if source.get("mp4_url"):
            item["source_url"] = _browser_safe_url(source["mp4_url"])
            item["source_title"] = source.get("title") or item.get("title")
    return result


@app.on_event("startup")
def startup() -> None:
    _init()


@app.get("/api/health")
def health() -> dict:
    with _connect() as conn:
        conn.execute("SELECT 1")
    return {
        "ok": True,
        "database": "azure-postgres",
        "videodb_configured": bool(os.getenv("VIDEO_DB_API_KEY")),
        "collection_configured": bool(os.getenv("VIDEODB_COLLECTION_ID")),
    }


@app.get("/api/answers")
def list_answers(limit: int = 12) -> dict:
    limit = max(1, min(limit, 100))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, question, state, result, created_at FROM ephemeris_run "
            "WHERE state IN ('succeeded','failed') ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        total = conn.execute(
            "SELECT count(*) AS n FROM ephemeris_run WHERE state IN ('succeeded','failed')"
        ).fetchone()["n"]
    return {"answers": [_summary(row) for row in rows], "total": total}


@app.get("/api/answers/{run_id}")
def get_answer(run_id: uuid.UUID) -> dict:
    with _connect() as conn:
        row = conn.execute(
            "SELECT state, result, error FROM ephemeris_run WHERE id=%s", (run_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found")
    if row["state"] == "running":
        raise HTTPException(409, "Run is still in progress")
    if row["state"] == "failed":
        raise HTTPException(422, row["error"] or "Run failed")
    return _enrich_sources(row["result"])


@app.post("/api/ask")
def ask(payload: AskInput, request: Request) -> dict:
    question = " ".join(payload.question.split())
    actor_hash = _actor(request)
    raw_key = payload.idempotency_key or f"{actor_hash}:{question.casefold()}:{datetime.now(UTC).date()}"
    key = hashlib.sha256(raw_key.encode()).hexdigest()

    with _connect() as conn:
        existing = conn.execute(
            "SELECT id, state, result, error FROM ephemeris_run WHERE idempotency_key=%s", (key,)
        ).fetchone()
    if existing:
        if existing["state"] == "succeeded":
            return {
                **_enrich_sources(existing["result"]),
                "saved_id": str(existing["id"]),
                "idempotent_replay": True,
            }
        if existing["state"] == "running":
            raise HTTPException(409, "An identical run is already in progress")
        raise HTTPException(422, existing["error"] or "The identical run failed")

    _reserve(actor_hash)
    run_id = uuid.uuid4()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO ephemeris_run(id,idempotency_key,actor_hash,question,state) "
            "VALUES (%s,%s,%s,%s,'running')",
            (run_id, key, actor_hash, question),
        )

    try:
        coll = vc.get_collection()
        id_by_video = {
            entry["video_id"]: nasa_id
            for nasa_id, entry in manifest.load().items()
            if entry.get("video_id")
        }
        result = agent.ask(question, coll=coll, id_by_video=id_by_video)
        _enrich_sources(result)
        try:
            result["reel"] = reel.build(vc.connect(), coll, result["evidence"])
        except Exception as exc:  # the public corpus can be borrowed read-only
            result["reel"] = {
                "stream_url": None,
                "shots": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        result["saved_id"] = str(run_id)
        with _connect() as conn:
            conn.execute(
                "UPDATE ephemeris_run SET state='succeeded', result=%s::jsonb, finished_at=now() "
                "WHERE id=%s",
                (json.dumps(result), run_id),
            )
        return result
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:1200]
        with _connect() as conn:
            conn.execute(
                "UPDATE ephemeris_run SET state='failed', error=%s, finished_at=now() WHERE id=%s",
                (detail, run_id),
            )
        raise HTTPException(502, f"Research run failed: {detail}") from exc
