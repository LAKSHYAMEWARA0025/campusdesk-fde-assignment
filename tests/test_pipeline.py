"""Unit + contract tests.  Run:  python -m pytest -q"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from metrics import Median  # noqa: E402
from validate import norm_category, norm_ticket_ref, parse_mixed_ts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_mixed_timestamps_parse_day_first():
    s = pd.Series(["2026-08-03 14:22:05", "03/08/2026 14:22", "garbage"])
    out = parse_mixed_ts(s)
    assert out[0] == datetime(2026, 8, 3, 14, 22, 5)
    assert out[1] == datetime(2026, 8, 3, 14, 22)      # 3 August, not 8 March
    assert pd.isna(out[2])


def test_category_representation_vs_semantic():
    assert norm_category("  it support ") == ("IT Support", "representation")
    assert norm_category("HOSTEL ") == ("Hostel & Maintenance", "semantic")
    assert norm_category("Exam Cell") == ("Academics & Exams", "semantic")
    assert norm_category(None) == ("Unknown", "missing")
    assert norm_category("Canteen")[0] == "Unmapped"


def test_ticket_ref_normalisation():
    assert norm_ticket_ref("tkt100234") == "TKT-100234"
    assert norm_ticket_ref("TKT 100234") == "TKT-100234"
    assert norm_ticket_ref("100234") == "TKT-100234"
    assert norm_ticket_ref("") is None


def test_median_aggregate():
    m = Median()
    for x in [5, 1, None, 3, 9]:
        m.step(x)
    assert m.finalize() == 4


def test_published_model_contract():
    j = pd.read_csv(ROOT / "output" / "latest" / "ticket_journey.csv")
    assert j.ticket_id.is_unique
    k = j[j.in_kpi_population]
    assert (k.net_resolution_hours >= 0).all()
    assert k.sla_met.isin([0, 1]).all()
    stages = k[["triage_hours", "first_response_wait_hours", "rerouting_hours", "work_hours",
                "pause_hours", "reopen_cycle_hours"]].sum(axis=1)
    assert (stages - k.gross_resolution_hours).abs().max() < 0.01
