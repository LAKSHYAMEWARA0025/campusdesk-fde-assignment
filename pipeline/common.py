"""Shared paths, logging and small helpers for the CampusDesk pipeline."""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "source_systems"
RAW_ROOT = ROOT / "data" / "raw"
OUTPUT_ROOT = ROOT / "output"
LOG_DIR = ROOT / "logs"

API_BASE = "http://127.0.0.1:8765"
API_PAGE_SIZE = 200

# Reporting period this run is meant to describe (weekly/term report use case)
PERIOD_START = "2026-07-27 00:00:00"
PERIOD_END = "2026-09-20 23:59:59"


class PipelineError(Exception):
    """A stage failed in a way that makes publishing metrics unsafe."""


def get_logger(run_id: str) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("campusdesk")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(stage)-9s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / f"pipeline_{run_id}.log")):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def stage_logger(log: logging.Logger, stage: str) -> logging.LoggerAdapter:
    return logging.LoggerAdapter(log, {"stage": stage})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))
