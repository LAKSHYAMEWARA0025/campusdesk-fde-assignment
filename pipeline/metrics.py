"""
Stage 4 - METRICS.

All metrics are computed with SQL (joins + aggregations) over the modelled
warehouse. A MEDIAN aggregate is registered on the SQLite connection.

Project KPI
  SLA compliance rate = resolved tickets meeting their priority SLA (net of
  waiting-on-student time) / resolved tickets in the KPI population

Supporting metrics
  M1 Median first-response time (h)            workflow driver
  M2 Median triage wait for manually-triaged tickets (h)   workflow driver
  M3 Reassignment rate (%)                     workflow driver (misrouting)
  M4 Reopen rate (%)                           quality outcome
  M5 Average CSAT (1-5) + response rate        student outcome
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


class Median:
    def __init__(self):
        self.v = []

    def step(self, x):
        if x is not None:
            self.v.append(x)

    def finalize(self):
        if not self.v:
            return None
        s = sorted(self.v)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.create_aggregate("MEDIAN", 1, Median)
    return con


KPI_SQL = """
SELECT COUNT(*)                                   AS resolved_tickets,
       SUM(sla_met)                               AS met_sla,
       ROUND(100.0 * AVG(sla_met), 1)             AS sla_compliance_pct
FROM ticket_journey WHERE in_kpi_population = 1
"""

SUPPORTING_SQL = {
    "M1_median_first_response_h": """
        SELECT ROUND(MEDIAN((julianday(first_response_at) - julianday(created_at)) * 24), 1)
        FROM ticket_journey WHERE in_kpi_population = 1""",
    "M2_median_manual_triage_wait_h": """
        SELECT ROUND(MEDIAN(triage_hours), 1) FROM ticket_journey
        WHERE in_kpi_population = 1 AND manual_triage = 1""",
    "M3_reassignment_rate_pct": """
        SELECT ROUND(100.0 * AVG(reassign_count > 0), 1) FROM ticket_journey WHERE in_kpi_population = 1""",
    "M4_reopen_rate_pct": """
        SELECT ROUND(100.0 * AVG(reopened), 1) FROM ticket_journey WHERE in_kpi_population = 1""",
    "M5_avg_csat": """
        SELECT ROUND(AVG(c.rating), 2) FROM fact_csat c
        JOIN ticket_journey j ON j.ticket_id = c.ticket_id WHERE j.in_kpi_population = 1""",
    "M5_csat_response_rate_pct": """
        SELECT ROUND(100.0 * COUNT(c.ticket_id) / COUNT(*), 1) FROM ticket_journey j
        LEFT JOIN fact_csat c ON c.ticket_id = j.ticket_id WHERE j.in_kpi_population = 1""",
}

SEGMENT_SQL = {
    "by_department": """
        SELECT resolving_department AS segment, COUNT(*) AS tickets,
               ROUND(100.0 * AVG(sla_met), 1) AS sla_pct,
               ROUND(MEDIAN(net_resolution_hours), 1) AS median_net_h,
               ROUND(100.0 * AVG(reassign_count > 0), 1) AS reassigned_pct
        FROM ticket_journey WHERE in_kpi_population = 1
        GROUP BY 1 ORDER BY sla_pct""",
    "by_priority": """
        SELECT priority AS segment, sla_target_hours AS target_h, COUNT(*) AS tickets,
               ROUND(100.0 * AVG(sla_met), 1) AS sla_pct,
               ROUND(MEDIAN(net_resolution_hours), 1) AS median_net_h,
               ROUND(MEDIAN((julianday(first_response_at) - julianday(created_at)) * 24), 1) AS median_first_resp_h
        FROM ticket_journey WHERE in_kpi_population = 1
        GROUP BY 1, 2 ORDER BY target_h""",
    "by_channel": """
        SELECT channel AS segment, COUNT(*) AS tickets, ROUND(100.0 * AVG(sla_met), 1) AS sla_pct,
               ROUND(100.0 * AVG(manual_triage), 1) AS manual_triage_pct,
               ROUND(MEDIAN(triage_hours), 1) AS median_triage_h
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1 ORDER BY sla_pct""",
    "by_reassignment": """
        SELECT CASE WHEN reassign_count = 0 THEN '0 (routed right first time)'
                    WHEN reassign_count = 1 THEN '1 reassignment' ELSE '2+ reassignments' END AS segment,
               COUNT(*) AS tickets, ROUND(100.0 * AVG(sla_met), 1) AS sla_pct,
               ROUND(MEDIAN(net_resolution_hours), 1) AS median_net_h,
               ROUND(AVG(followup_count), 2) AS avg_followups,
               ROUND(100.0 * AVG(reopened), 1) AS reopen_pct
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1 ORDER BY 1""",
    "by_triage_path": """
        SELECT CASE WHEN manual_triage = 1 THEN 'manual triage queue' ELSE 'auto-routed' END AS segment,
               COUNT(*) AS tickets, ROUND(100.0 * AVG(sla_met), 1) AS sla_pct,
               ROUND(MEDIAN(triage_hours), 1) AS median_triage_h,
               ROUND(100.0 * AVG(reassign_count > 0), 1) AS reassigned_pct
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1""",
    "by_weekend": """
        SELECT CASE WHEN created_weekday IN ('Saturday', 'Sunday') THEN 'weekend' ELSE 'weekday' END AS segment,
               COUNT(*) AS tickets, ROUND(100.0 * AVG(sla_met), 1) AS sla_pct,
               ROUND(MEDIAN(net_resolution_hours), 1) AS median_net_h
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1""",
    "interventions": """
        SELECT CASE WHEN escalated = 1 AND escalated_after_sla_breach = 1 THEN 'escalated AFTER SLA already breached'
                    WHEN escalated = 1 THEN 'escalated before breach'
                    ELSE 'not escalated' END AS segment,
               COUNT(*) AS tickets, ROUND(100.0 * AVG(sla_met), 1) AS sla_pct,
               ROUND(MEDIAN(escalated_after_hours), 1) AS median_escalated_after_h
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1 ORDER BY tickets DESC""",
    "reminders": """
        SELECT CASE WHEN reminder_sent = 1 THEN 'auto-reminder fired (no reply in 24h)' ELSE 'no reminder' END AS segment,
               COUNT(*) AS tickets, ROUND(100.0 * AVG(sla_met), 1) AS sla_pct
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1""",
    "followups_vs_outcome": """
        SELECT CASE WHEN sla_met = 1 THEN 'met SLA' ELSE 'breached SLA' END AS segment, COUNT(*) AS tickets,
               ROUND(AVG(followup_count), 2) AS avg_followups,
               ROUND(AVG(c.rating), 2) AS avg_csat, COUNT(c.rating) AS csat_n
        FROM ticket_journey j LEFT JOIN fact_csat c ON c.ticket_id = j.ticket_id
        WHERE in_kpi_population = 1 GROUP BY 1""",
    "stage_breakdown": """
        SELECT 'mean' AS stat,
               ROUND(AVG(triage_hours), 1) AS triage, ROUND(AVG(first_response_wait_hours), 1) AS first_response_wait,
               ROUND(AVG(rerouting_hours), 1) AS rerouting, ROUND(AVG(work_hours), 1) AS work,
               ROUND(AVG(pause_hours), 1) AS waiting_on_student, ROUND(AVG(reopen_cycle_hours), 1) AS reopen_cycle,
               ROUND(AVG(gross_resolution_hours), 1) AS gross_total
        FROM ticket_journey WHERE in_kpi_population = 1""",
    "stage_breakdown_breached": """
        SELECT CASE WHEN sla_met = 1 THEN 'met SLA' ELSE 'breached SLA' END AS segment,
               ROUND(AVG(triage_hours), 1) AS triage, ROUND(AVG(first_response_wait_hours), 1) AS first_response_wait,
               ROUND(AVG(rerouting_hours), 1) AS rerouting, ROUND(AVG(work_hours), 1) AS work,
               ROUND(AVG(pause_hours), 1) AS waiting_on_student, ROUND(AVG(reopen_cycle_hours), 1) AS reopen_cycle
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1""",
    "weekly_trend": """
        SELECT substr(created_week, 1, 10) AS week_start, COUNT(*) AS tickets,
               ROUND(100.0 * AVG(sla_met), 1) AS sla_pct
        FROM ticket_journey WHERE in_kpi_population = 1 GROUP BY 1 ORDER BY 1""",
    "population": """
        SELECT CASE WHEN kpi_exclusion_reason = '' THEN 'IN KPI: resolved in period' ELSE kpi_exclusion_reason END AS segment,
               COUNT(*) AS tickets
        FROM ticket_journey GROUP BY 1 ORDER BY tickets DESC""",
}


def sensitivity(con) -> pd.DataFrame:
    """Same data, different (defensible) KPI definitions -> why the owner must sign off."""
    q = {
        "A. Chosen: final resolution, net of waiting-on-student, missing priority = Medium":
            "SELECT AVG(sla_met) FROM ticket_journey WHERE in_kpi_population = 1",
        "B. Gross calendar hours (no pause for waiting-on-student)":
            "SELECT AVG(gross_resolution_hours <= sla_target_hours) FROM ticket_journey WHERE in_kpi_population = 1",
        "C. First resolution instead of final (ignores reopens)":
            "SELECT AVG(first_resolution_net_hours <= sla_target_hours) FROM ticket_journey WHERE in_kpi_population = 1",
        "D. Missing priority treated as High (24h)":
            """SELECT AVG(CASE WHEN priority_imputed = 1 THEN net_resolution_hours <= 24 ELSE sla_met END)
               FROM ticket_journey WHERE in_kpi_population = 1""",
        "E. Also count still-open tickets already past deadline as breaches":
            """SELECT SUM(CASE WHEN in_kpi_population = 1 THEN sla_met ELSE 0 END) * 1.0 /
                      SUM(in_kpi_population = 1 OR open_past_sla = 1) FROM ticket_journey""",
    }
    rows = [(k, round(100 * con.execute(v).fetchone()[0], 1)) for k, v in q.items()]
    return pd.DataFrame(rows, columns=["definition", "sla_compliance_pct"])


def run(db: Path, out_dir: Path, log) -> dict:
    con = connect(db)
    k = pd.read_sql(KPI_SQL, con).iloc[0]
    kpi = {"resolved_tickets": int(k.resolved_tickets), "met_sla": int(k.met_sla),
           "sla_compliance_pct": float(k.sla_compliance_pct)}
    supporting = {k: con.execute(v).fetchone()[0] for k, v in SUPPORTING_SQL.items()}
    segments = {k: pd.read_sql(v, con) for k, v in SEGMENT_SQL.items()}
    segments["sensitivity"] = sensitivity(con)
    con.close()
    seg_dir = out_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    for k, df in segments.items():
        df.to_csv(seg_dir / f"{k}.csv", index=False)
    log.info(f"KPI    SLA compliance = {kpi['sla_compliance_pct']}%  ({int(kpi['met_sla'])}/{int(kpi['resolved_tickets'])} resolved tickets)")
    for k, v in supporting.items():
        log.info(f"metric {k:<32} = {v}")
    return {"kpi": kpi, "supporting": supporting, "segments": segments}
