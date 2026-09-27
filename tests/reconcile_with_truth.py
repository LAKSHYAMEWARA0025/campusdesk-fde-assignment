"""
Reliability evidence: does the pipeline recover the TRUE KPI that the
generator simulated, and how wrong would a naive calculation be?

The pipeline never reads synthetic_truth/. This script is the only place it is used.

  python tests/reconcile_with_truth.py
"""
import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SLA = {"High": 24, "Medium": 72, "Low": 120}

truth = pd.read_csv(ROOT / "synthetic_truth" / "truth_tickets.csv")
t = truth[truth.sla_met.notna()]
true_rate = t.sla_met.astype(bool).mean()

metrics = json.loads((ROOT / "output" / "latest" / "metrics.json").read_text())
pipe_rate = metrics["kpi"]["sla_compliance_pct"] / 100

# Naive: query the ticket table directly, the way a quick dashboard would
con = sqlite3.connect(ROOT / "source_systems" / "helpdesk.db")
raw = pd.read_sql("SELECT * FROM tickets", con)
raw["c"] = pd.to_datetime(raw.created_at, errors="coerce", format="%Y-%m-%d %H:%M:%S")  # DD/MM rows silently lost
raw["r"] = pd.to_datetime(raw.resolved_at, errors="coerce")
naive = raw[raw.status.isin(["Closed", "Resolved"]) & raw.c.notna() & raw.r.notna() & raw.priority.notna()]
naive_rate = ((naive.r - naive.c).dt.total_seconds() / 3600 <= naive.priority.map(SLA)).mean()

pipe_j = pd.read_csv(ROOT / "output" / "latest" / "ticket_journey.csv")
pj = pipe_j[pipe_j.in_kpi_population].merge(truth[["ticket_id", "reassign_count", "sla_met"]], on="ticket_id",
                                             suffixes=("", "_true"))
rows = [
    ("Ground truth (simulated)", len(t), true_rate),
    ("Pipeline (cleaned + modelled)", metrics["kpi"]["resolved_tickets"], pipe_rate),
    ("Naive query on ticket table", len(naive), naive_rate),
]
out = pd.DataFrame(rows, columns=["method", "tickets", "sla_compliance"])
out["sla_compliance"] = (100 * out.sla_compliance).round(1)
out["error_vs_truth_pp"] = (out.sla_compliance - round(100 * true_rate, 1)).round(1)
print(out.to_string(index=False))
print(f"\nPer-ticket agreement pipeline vs truth: SLA verdict {100 * (pj.sla_met == pj.sla_met_true).mean():.1f}%, "
      f"reassign count {100 * (pj.reassign_count == pj.reassign_count_true).mean():.1f}%")
print(f"Naive query silently used {len(naive)} of {raw.ticket_id.nunique()} tickets "
      f"(dropped DD/MM dates, status variants, missing priority; kept duplicates; timed reopens to first fix)")
(ROOT / "output" / "latest" / "reconciliation.csv").write_text(out.to_csv(index=False))
