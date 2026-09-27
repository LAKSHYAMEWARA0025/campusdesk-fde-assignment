"""
Stage 3 - TRANSFORM / MODEL.

Re-organises source-shaped data around the business workflow:

  dim_student        1 row per student
  dim_agent          1 row per agent
  fact_ticket        1 row per business ticket (after dedupe)            PK ticket_id
  fact_ticket_event  1 row per lifecycle event (audit log, clean)        PK event_id,  FK ticket_id
  fact_interaction   1 row per portal message (student / agent)          PK interaction_id, FK ticket_id
  fact_intervention  1 row per helpdesk intervention (escalation, auto-reminder)   FK ticket_id
  fact_csat          1 row per rated ticket (latest valid response)       PK/FK ticket_id
  ticket_journey     1 row per ticket: stage durations, interaction counts, interventions, outcome

Written to output/runs/<run_id>/warehouse.db so the metrics stage can use SQL.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from common import PERIOD_END, PERIOD_START


def _hours(a, b):
    return (b - a).dt.total_seconds() / 3600


def build_journey(clean: dict) -> pd.DataFrame:
    tk = clean["tickets"].set_index("ticket_id")
    ev = clean["events"].sort_values(["ticket_id", "event_time"])
    it = clean["interactions"]
    sla = clean["policy"]["resolution_targets_hours"]

    g = ev.groupby("ticket_id")
    first = lambda mask: ev[mask].groupby("ticket_id").event_time.min()
    last = lambda mask: ev[mask].groupby("ticket_id").event_time.max()

    j = pd.DataFrame(index=tk.index)
    j["created_at"] = first(ev.event_type == "created")
    j["first_assigned_at"] = first(ev.event_type == "assigned")
    j["first_response_at"] = first(ev.event_type == "first_response")
    j["first_resolved_at"] = first(ev.to_status == "Resolved")
    j["final_resolved_at"] = last(ev.to_status == "Resolved")
    j["reassign_count"] = ev[ev.event_type == "reassigned"].groupby("ticket_id").size()
    j["reopened"] = ev[ev.to_status == "Reopened"].groupby("ticket_id").size() > 0
    j["escalated_at"] = first(ev.event_type == "escalated")
    j["reminder_at"] = first(ev.event_type == "reminder_sent")

    # resolving department = department on the last routing event
    routing = ev[ev.event_type.isin(["assigned", "reassigned"])]
    j["first_department"] = routing.groupby("ticket_id").department.first()
    j["resolving_department"] = routing.groupby("ticket_id").department.last()

    # response by the resolving department (last agent response before first resolution)
    resp = ev[ev.event_type.isin(["first_response", "agent_response"])].merge(
        j[["first_resolved_at"]], left_on="ticket_id", right_index=True, how="left")
    resp = resp[resp.first_resolved_at.isna() | (resp.event_time <= resp.first_resolved_at)]
    j["dept_response_at"] = resp.groupby("ticket_id").event_time.max()

    # waiting-on-student pause intervals (clock paused)
    w = ev[(ev.to_status == "Waiting on Student") | (ev.from_status == "Waiting on Student")].copy()
    w["start"] = w.to_status.eq("Waiting on Student")
    pauses = {}
    for tid, grp in w.groupby("ticket_id"):
        total, open_at = 0.0, None
        for _, r in grp.iterrows():
            if r.start:
                open_at = r.event_time
            elif open_at is not None and r.to_status == "In Progress":
                total += (r.event_time - open_at).total_seconds() / 3600
                open_at = None
        pauses[tid] = total
    j["pause_hours"] = pd.Series(pauses)

    # interactions (student follow-ups = frustration signal)
    it_counts = it.pivot_table(index="ticket_id", columns="kind", values="interaction_id", aggfunc="count")
    j["followup_count"] = it_counts.get("follow_up")
    j["agent_reply_count"] = it_counts.get("agent_reply")

    j = j.join(tk[["student_id", "channel", "priority", "priority_imputed", "intake_category", "status_canonical"]])
    j = j.join(clean["csat"].set_index("ticket_id")[["rating"]].rename(columns={"rating": "csat_rating"}))
    j["reassign_count"] = j.reassign_count.fillna(0).astype(int)
    j["reopened"] = j.reopened.fillna(False).astype(bool)
    j["pause_hours"] = j.pause_hours.fillna(0.0)
    j["followup_count"] = j.followup_count.fillna(0).astype(int)
    j["agent_reply_count"] = j.agent_reply_count.fillna(0).astype(int)
    j["manual_triage"] = j.first_assigned_at.sub(j.created_at).dt.total_seconds() > 30 * 60

    # stage durations (hours) - additive decomposition of the gross resolution time
    j["triage_hours"] = _hours(j.created_at, j.first_assigned_at)
    j["first_response_wait_hours"] = _hours(j.first_assigned_at, j.first_response_at)
    j["rerouting_hours"] = _hours(j.first_response_at, j.dept_response_at)
    j["work_hours"] = _hours(j.dept_response_at, j.first_resolved_at) - j.pause_hours
    j["reopen_cycle_hours"] = _hours(j.first_resolved_at, j.final_resolved_at)
    j["gross_resolution_hours"] = _hours(j.created_at, j.final_resolved_at)
    j["net_resolution_hours"] = j.gross_resolution_hours - j.pause_hours
    j["first_resolution_net_hours"] = _hours(j.created_at, j.first_resolved_at) - j.pause_hours
    j["sla_target_hours"] = j.priority.map(sla)
    j["sla_deadline"] = j.created_at + pd.to_timedelta(j.sla_target_hours, unit="h")
    j["sla_met"] = np.where(j.final_resolved_at.notna(), (j.net_resolution_hours <= j.sla_target_hours).astype(float), np.nan)
    j["escalated"] = j.escalated_at.notna()
    j["reminder_sent"] = j.reminder_at.notna()
    j["escalated_after_hours"] = _hours(j.created_at, j.escalated_at)
    j["escalated_after_sla_breach"] = j.escalated & (j.escalated_at > j.sla_deadline)
    j["created_weekday"] = j.created_at.dt.day_name()
    j["created_week"] = j.created_at.dt.to_period("W-SUN").dt.start_time

    # KPI population and exclusion reasons
    reason = pd.Series("", index=j.index)
    reason[j.status_canonical == "Cancelled"] = "cancelled / duplicate submission"
    reason[(reason == "") & (j.status_canonical == "Closed - No Response")] = "closed - student never replied"
    reason[(reason == "") & j.index.isin(clean["bad_chrono"])] = "chronology violation (clock skew)"
    still_open = j.final_resolved_at.isna() | j.status_canonical.isin(["Assigned", "In Progress"])  # e.g. reopened, not re-fixed
    reason[(reason == "") & still_open] = "still open at export"
    reason[(reason == "") & ~j.created_at.between(pd.Timestamp(PERIOD_START), pd.Timestamp(PERIOD_END))] = "outside period"
    j["kpi_exclusion_reason"] = reason
    j["in_kpi_population"] = reason.eq("")
    # open tickets already past their SLA deadline are *known* breaches (used in sensitivity)
    export_ts = clean["events"].event_time.max()
    j["open_past_sla"] = (reason == "still open at export") & (j.sla_deadline < export_ts)
    return j.reset_index().rename(columns={"index": "ticket_id"})


def run(clean: dict, out_dir: Path, log) -> tuple[pd.DataFrame, Path]:
    journey = build_journey(clean)
    ev = clean["events"]
    interventions = ev[ev.event_type.isin(["escalated", "reminder_sent"])][
        ["event_id", "ticket_id", "event_time", "event_type", "actor_id", "department"]
    ].rename(columns={"event_type": "intervention_type", "event_time": "intervention_at"})

    fact_ticket = clean["tickets"][["ticket_id", "student_id", "channel", "intake_category", "priority",
                                    "priority_imputed", "subject", "status_canonical"]].merge(
        journey[["ticket_id", "created_at", "resolving_department", "final_resolved_at"]], on="ticket_id", how="left")

    db = out_dir / "warehouse.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    tables = {"dim_student": clean["students"], "dim_agent": clean["agents"], "fact_ticket": fact_ticket,
              "fact_ticket_event": ev, "fact_interaction": clean["interactions"],
              "fact_intervention": interventions, "fact_csat": clean["csat"], "ticket_journey": journey}
    for name, df in tables.items():
        df2 = df.copy()
        for c in df2.columns:
            if pd.api.types.is_datetime64_any_dtype(df2[c]):
                df2[c] = df2[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        df2.to_sql(name, con, index=False)
        log.info(f"model  {name:<18} {len(df2):>6} rows")
    con.commit()
    con.close()

    # model integrity checks (post-transform)
    assert journey.ticket_id.is_unique, "ticket_journey grain broken"
    stage_sum = journey[["triage_hours", "first_response_wait_hours", "rerouting_hours", "work_hours",
                         "pause_hours", "reopen_cycle_hours"]].sum(axis=1)
    ok = journey.in_kpi_population
    gap = (stage_sum[ok] - journey.gross_resolution_hours[ok]).abs().max()
    log.info(f"check  ticket_journey grain unique; stage decomposition closes to gross time (max gap {gap:.4f}h)")
    if gap > 0.01:
        log.warning("stage decomposition does not close - check event ordering")
    return journey, db
