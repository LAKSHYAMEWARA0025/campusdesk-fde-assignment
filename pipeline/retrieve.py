"""
Stage 1 - RETRIEVE.

Pulls every source into an immutable raw snapshot: data/raw/<run_id>/
Nothing is cleaned here. Raw is preserved exactly so any number we publish
can be traced back to what the source systems returned on that run.

Source types used: SQL (SQLite), CSV, JSON file, REST API (paginated).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import API_BASE, API_PAGE_SIZE, SOURCES, PipelineError, sha256, write_json

SQL_QUERIES = {
    "tickets": "SELECT * FROM tickets",
    "students": "SELECT student_id, program, year, hostel_block FROM students",   # no names/emails: not needed
    "agents": "SELECT agent_id, department, role, active FROM agents",
}

MAX_RETRIES = 6


def _manifest_entry(path: Path, source_type: str, origin: str, rows: int) -> dict:
    return {"file": path.name, "source_type": source_type, "origin": origin, "rows": rows,
            "sha256": sha256(path), "retrieved_at": datetime.now().isoformat(timespec="seconds")}


def retrieve_sql(raw: Path, log) -> list[dict]:
    db = SOURCES / "helpdesk.db"
    if not db.exists():
        raise PipelineError(f"SQL source missing: {db}")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)      # read-only: never touch the client system
    out = []
    for name, q in SQL_QUERIES.items():
        df = pd.read_sql(q, con)
        p = raw / f"sql_{name}.csv"
        df.to_csv(p, index=False)
        out.append(_manifest_entry(p, "SQL", f"helpdesk.db :: {q}", len(df)))
        log.info(f"SQL  {name:<9} {len(df):>6} rows  <- {q}")
    con.close()
    return out


def retrieve_files(raw: Path, log, simulate: str | None) -> list[dict]:
    out = []
    ev_src = SOURCES / "ticket_events.csv"
    ev_dst = raw / "csv_ticket_events.csv"
    if simulate == "truncated_events":
        # simulate a partial export (the export job died half-way)
        lines = ev_src.read_text().splitlines(keepends=True)
        ev_dst.write_text("".join(lines[: len(lines) // 2]))
        log.warning("SIMULATION: ticket_events.csv export truncated to 50%")
    else:
        shutil.copy2(ev_src, ev_dst)
    n = sum(1 for _ in open(ev_dst)) - 1
    out.append(_manifest_entry(ev_dst, "CSV", "ticketing tool audit-log export", n))
    log.info(f"CSV  events    {n:>6} rows  <- {ev_src.name}")

    for src, dst, key in [(SOURCES / "csat_survey_export.json", raw / "json_csat_survey_export.json", "responses"),
                          (SOURCES / "sla_policy.json", raw / "json_sla_policy.json", None)]:
        shutil.copy2(src, dst)
        obj = json.loads(dst.read_text())
        rows = len(obj[key]) if key else 1
        out.append(_manifest_entry(dst, "JSON", src.name, rows))
        log.info(f"JSON {src.stem[:9]:<9} {rows:>6} rows  <- {src.name}")
    return out


def _get(url: str, log) -> dict:
    """GET with retries: 5xx and 429 are retryable, 4xx is not."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = float(e.headers.get("Retry-After", 1))
            elif 500 <= e.code < 600:
                wait = 0.2 * 2 ** (attempt - 1)
            else:
                raise PipelineError(f"Non-retryable HTTP {e.code} for {url}")
            if attempt == MAX_RETRIES:
                log.error(f"API  HTTP {e.code} on attempt {attempt}/{MAX_RETRIES} -> giving up  ({url})")
                break
            log.warning(f"API  HTTP {e.code} on attempt {attempt}/{MAX_RETRIES} -> retry in {wait:.1f}s  ({url})")
            time.sleep(wait)
        except urllib.error.URLError as e:
            if attempt == MAX_RETRIES:
                log.error(f"API  connection error on attempt {attempt}/{MAX_RETRIES}: {e.reason} -> giving up")
                break
            wait = 0.2 * 2 ** (attempt - 1)
            log.warning(f"API  connection error on attempt {attempt}/{MAX_RETRIES}: {e.reason} -> retry in {wait:.1f}s")
            time.sleep(wait)
    raise PipelineError(f"API retries exhausted for {url}")


def retrieve_api(raw: Path, log) -> list[dict]:
    first = _get(f"{API_BASE}/api/v1/interactions?page=1&page_size={API_PAGE_SIZE}", log)
    total_pages, total_records = first["total_pages"], first["total_records"]
    pages = {1: first}
    for p in range(2, total_pages + 1):
        pages[p] = _get(f"{API_BASE}/api/v1/interactions?page={p}&page_size={API_PAGE_SIZE}", log)
    out, fetched, ids = [], 0, set()
    for p, body in pages.items():
        path = raw / f"api_interactions_page_{p:03d}.json"
        path.write_text(json.dumps(body))                         # raw page preserved as returned
        fetched += len(body["data"])
        ids.update(r["interaction_id"] for r in body["data"])
        out.append(_manifest_entry(path, "API", f"GET /api/v1/interactions?page={p}", len(body["data"])))
    log.info(f"API  {total_pages} pages, {fetched} records fetched, API reports total_records={total_records}")
    # Completeness proof: HTTP 200 on each page is not enough.
    if fetched != total_records or len(ids) != total_records:
        raise PipelineError(f"API ingestion incomplete: fetched={fetched}, unique={len(ids)}, expected={total_records}")
    return out


def run(raw: Path, log, simulate: str | None = None) -> list[dict]:
    raw.mkdir(parents=True, exist_ok=True)
    manifest = retrieve_sql(raw, log) + retrieve_files(raw, log, simulate) + retrieve_api(raw, log)
    write_json(raw / "_manifest.json", manifest)
    log.info(f"raw snapshot written to {raw.relative_to(raw.parents[2])} ({len(manifest)} files, manifest + checksums)")
    return manifest
