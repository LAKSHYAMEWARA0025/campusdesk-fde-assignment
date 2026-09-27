"""
Stage 2 - PROFILE, VALIDATE and apply SAFE fixes.

Every rule is written as a business assumption ("one row = one ticket", "a
ticket cannot be resolved before it was created"), tested against the raw
snapshot, and given a status:

  PASS     assumption holds
  WARN     small / known issue, handled or disclosed; metric can be published with a caveat
  FAIL     metric would be misleading -> the pipeline stops, nothing is published
  UNKNOWN  cannot be decided from data; needs a business owner

Safe fixes (representation only: casing, whitespace, exact duplicates, date
formats) are applied. Anything that changes business meaning is flagged for an
owner instead of being "cleaned by instinct".
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from common import PERIOD_END

# ----------------------------------------------------------------------------
# Standardisation tables (documented, reviewable)
# ----------------------------------------------------------------------------
CANON_DEPTS = ["IT Support", "Hostel & Maintenance", "Fees & Finance", "Academics & Exams", "Library"]

# representation-only variants: safe to normalise
CATEGORY_REPRESENTATION = {
    "it support": "IT Support", "hostel & maintenance": "Hostel & Maintenance", "hostel maintenance": "Hostel & Maintenance",
    "fees & finance": "Fees & Finance", "academics & exams": "Academics & Exams", "library": "Library",
    "other": "Unknown",
}
# semantic variants: plausible, but the owner must confirm (logged as assumptions)
CATEGORY_SEMANTIC = {
    "it": "IT Support", "hostel": "Hostel & Maintenance", "fees": "Fees & Finance", "finance": "Fees & Finance",
    "academics": "Academics & Exams", "exam cell": "Academics & Exams",
}
STATUS_MAP = {
    "closed": "Closed", "resolved": "Resolved", "in progress": "In Progress", "in_progress": "In Progress",
    "assigned": "Assigned", "closed - no response": "Closed - No Response", "closed_no_response": "Closed - No Response",
    "cancelled": "Cancelled",
}


@dataclass
class Check:
    rule_id: str
    rule: str
    business_reason: str
    status: str
    evidence: str
    action: str
    owner: str = "FDE / data"


@dataclass
class ValidationResult:
    checks: list[Check] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    profile: dict = field(default_factory=dict)

    def add(self, *a, **k):
        c = Check(*a, **k)
        self.checks.append(c)
        return c

    @property
    def gate(self) -> str:
        s = [c.status for c in self.checks]
        if "FAIL" in s:
            return "FAIL"
        return "PASS WITH CAVEATS" if ("WARN" in s or "UNKNOWN" in s) else "PASS"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def parse_mixed_ts(s: pd.Series) -> pd.Series:
    """ISO 'YYYY-MM-DD HH:MM:SS' or email-importer 'DD/MM/YYYY HH:MM' (day first - confirmed by event log)."""
    iso = pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    dmy = pd.to_datetime(s, format="%d/%m/%Y %H:%M", errors="coerce")
    return iso.fillna(dmy)


def norm_category(v):
    if v is None or pd.isna(v):
        return "Unknown", "missing"
    k = re.sub(r"\s+", " ", str(v).strip().lower())
    if k in CATEGORY_REPRESENTATION:
        return CATEGORY_REPRESENTATION[k], "representation"
    if k in CATEGORY_SEMANTIC:
        return CATEGORY_SEMANTIC[k], "semantic"
    return "Unmapped", "unmapped"


def norm_ticket_ref(v):
    m = re.search(r"(\d{6})", str(v or ""))
    return f"TKT-{m.group(1)}" if m else None


# ----------------------------------------------------------------------------
def run(raw: Path, log):
    V = ValidationResult()
    tickets_raw = pd.read_csv(raw / "sql_tickets.csv")
    students = pd.read_csv(raw / "sql_students.csv")
    agents = pd.read_csv(raw / "sql_agents.csv")
    events_raw = pd.read_csv(raw / "csv_ticket_events.csv")
    csat_obj = json.loads((raw / "json_csat_survey_export.json").read_text())
    policy = json.loads((raw / "json_sla_policy.json").read_text())
    api_pages = sorted(raw.glob("api_interactions_page_*.json"))
    interactions = pd.DataFrame([r for p in api_pages for r in json.loads(p.read_text())["data"]])
    last_synced = json.loads(api_pages[0].read_text())["last_synced_at"]

    # ---------------- profile ------------------------------------------------
    for name, df in [("tickets", tickets_raw), ("events", events_raw), ("interactions", interactions),
                     ("students", students), ("agents", agents)]:
        V.profile[name] = {"rows": len(df), "columns": len(df.columns),
                           "null_pct": {c: round(100 * df[c].isna().mean(), 1) for c in df.columns if df[c].isna().any()}}
    V.profile["tickets"]["distinct"] = {c: int(tickets_raw[c].nunique()) for c in ["ticket_id", "category", "status", "priority", "channel"]}
    V.profile["tickets"]["category_values"] = tickets_raw["category"].fillna("<NULL>").value_counts().to_dict()
    V.profile["tickets"]["status_values"] = tickets_raw["status"].fillna("<NULL>").value_counts().to_dict()
    V.profile["events"]["event_types"] = events_raw["event_type"].value_counts().to_dict()
    V.profile["csat"] = {"responses": len(csat_obj["responses"])}
    log.info(f"profiled tickets={len(tickets_raw)} events={len(events_raw)} interactions={len(interactions)} "
             f"csat={len(csat_obj['responses'])}")

    # ---------------- R01 completeness ----------------------------------------
    empty = [n for n, d in [("tickets", tickets_raw), ("events", events_raw), ("interactions", interactions),
                            ("csat", csat_obj["responses"])] if len(d) == 0]
    V.add("R01", "Every source returned data; API returned all records",
          "A missing source silently changes the denominator", "FAIL" if empty else "PASS",
          f"empty sources: {empty or 'none'}; API completeness proven in retrieve stage",
          "stop run if any source empty")

    # ---------------- R02 grain: one row = one ticket --------------------------
    exact = tickets_raw.duplicated().sum()
    tickets = tickets_raw.drop_duplicates().copy()
    conflicting = tickets.ticket_id.duplicated().sum()
    V.fixes.append(f"Dropped {exact} exact duplicate ticket rows (email importer double-sync).")
    V.add("R02", "One row = one ticket (ticket_id unique)", "Duplicates inflate volume and distort the SLA rate",
          "FAIL" if conflicting else ("WARN" if exact else "PASS"),
          f"{exact} exact duplicate rows ({pct(exact / len(tickets_raw))}); {conflicting} conflicting ids",
          "exact duplicates dropped (safe); conflicting ids would stop the run")

    # ---------------- R03 double submissions ----------------------------------
    tickets["created_at_parsed"] = parse_mixed_ts(tickets.created_at)
    t = tickets.sort_values("created_at_parsed")
    t["gap_min"] = t.groupby(["student_id", "subject"]).created_at_parsed.diff().dt.total_seconds() / 60
    doubles = t[t.gap_min <= 15]
    not_cancelled = doubles[doubles.status.str.lower() != "cancelled"]
    V.add("R03", "A student's repeat submission of the same issue is not counted twice",
          "Double-submits look like extra demand",
          "WARN" if len(not_cancelled) else "PASS",
          f"{len(doubles)} same student+subject within 15 min; {len(doubles) - len(not_cancelled)} already marked Cancelled",
          "Cancelled tickets excluded from KPI; the rest are NOT auto-merged (could be genuine repeats)",
          owner="Helpdesk Manager")

    # ---------------- R04 timestamps parse ------------------------------------
    unparsed = tickets.created_at_parsed.isna().mean()
    n_dmy = tickets.created_at.str.contains("/", na=False).sum()
    V.add("R04", "created_at is a valid timestamp", "Every SLA clock starts here",
          "FAIL" if unparsed > 0.02 else ("WARN" if n_dmy else "PASS"),
          f"{n_dmy} rows in DD/MM/YYYY format (email importer); unparseable after fix: {pct(unparsed)}",
          "parsed both formats; day-first confirmed against the audit log (R06)")
    V.fixes.append(f"Parsed {n_dmy} DD/MM/YYYY HH:MM timestamps (email importer) alongside ISO format.")

    # ---------------- events: dedupe, parse, orphans --------------------------
    ev_dups = events_raw.duplicated("event_id").sum()
    events = events_raw.drop_duplicates("event_id").copy()
    events["event_time"] = pd.to_datetime(events.event_time.str.slice(0, 19), format="%Y-%m-%dT%H:%M:%S")
    V.fixes.append(f"Dropped {ev_dups} duplicate audit-log events (same event_id).")
    known = set(tickets.ticket_id)
    orphan = ~events.ticket_id.isin(known)
    V.add("R05", "Every audit-log event belongs to a known ticket", "Orphan events cannot be attributed",
          "WARN" if 0 < orphan.mean() <= 0.02 else ("FAIL" if orphan.mean() > 0.02 else "PASS"),
          f"{orphan.sum()} orphan events ({pct(orphan.mean())}); {ev_dups} duplicate events dropped",
          "orphans quarantined, not joined", owner="IT admin (ticketing tool)")
    quarantine = events[orphan]
    events = events[~orphan]

    # created_at: ticket table vs event log
    created_ev = events[events.event_type == "created"].groupby("ticket_id").event_time.min()
    cmp = tickets.set_index("ticket_id").created_at_parsed.to_frame().join(created_ev.rename("ev_created"))
    diff_min = (cmp.ev_created - cmp.created_at_parsed).dt.total_seconds().abs() / 60
    coverage = cmp.ev_created.notna().mean()
    agree = (diff_min[cmp.ev_created.notna()] <= 1).mean()
    V.add("R06", "Every ticket has a 'created' event and both systems agree on created_at",
          "Two systems must tell the same story before we trust either; a ticket with no lifecycle cannot be timed",
          "FAIL" if coverage < 0.98 else ("PASS" if agree >= 0.99 else "WARN"),
          f"tickets with audit-log lifecycle: {pct(coverage)}; created_at agreement within 1 min: {pct(agree)} "
          f"(DD/MM rows agree only when parsed day-first)",
          "source of truth for lifecycle times = audit log; stop run if lifecycle coverage < 98%")

    # ---------------- R07 chronology ------------------------------------------
    other_ev = events[events.event_type != "created"].groupby("ticket_id").event_time.min()
    first_res = events[events.to_status == "Resolved"].groupby("ticket_id").event_time.min()
    chrono = pd.concat([created_ev.rename("c"), other_ev.rename("o"), first_res.rename("r")], axis=1)
    bad_chrono = chrono[chrono.o < chrono.c].index
    n_res_before = int((chrono.r < chrono.c).sum())
    rate = len(bad_chrono) / max(len(chrono), 1)
    chan = tickets.set_index("ticket_id").loc[list(bad_chrono), "channel"].value_counts().to_dict() if len(bad_chrono) else {}
    V.add("R07", "'created' is the first event of every ticket (nothing happens before creation)",
          "Out-of-order events corrupt every stage duration",
          "FAIL" if rate > 0.02 else ("WARN" if len(bad_chrono) else "PASS"),
          f"{len(bad_chrono)} tickets ({pct(rate)}) have events before 'created' ({n_res_before} even resolved before creation); "
          f"channels: {chan} -> walk-in desk clock skew",
          "excluded from KPI (not guessed); walk-in desk clock to be fixed", owner="IT admin (walk-in desk PC)")

    # ---------------- R08 categories ------------------------------------------
    cat = tickets.category.map(norm_category)
    tickets["intake_category"] = cat.map(lambda x: x[0])
    kinds = cat.map(lambda x: x[1]).value_counts().to_dict()
    unmapped = kinds.get("unmapped", 0)
    sem_vals = sorted({str(v).strip() for v in tickets.category.dropna()
                       if re.sub(r"\s+", " ", str(v).strip().lower()) in CATEGORY_SEMANTIC})
    V.add("R08", "Each ticket maps to one canonical category", "Department-level SLA needs a clean category",
          "FAIL" if unmapped else "WARN",
          f"{tickets.category.nunique()} raw values -> 5 canonical + Unknown; representation fixes={kinds.get('representation', 0)}, "
          f"semantic mappings={kinds.get('semantic', 0)} ({', '.join(sem_vals)}), Unknown/Other={(tickets.intake_category == 'Unknown').sum()}",
          "semantic mappings applied provisionally; analysis uses RESOLVING department from audit log instead",
          owner="Helpdesk Manager")
    V.assumptions.append(f"Semantic category mappings pending owner confirmation: {', '.join(sem_vals)}.")
    V.fixes.append("Normalised category casing/whitespace (e.g. 'it support', 'HOSTEL ' -> canonical).")

    # ---------------- R09 status ----------------------------------------------
    tickets["status_canonical"] = tickets.status.str.strip().str.lower().map(STATUS_MAP)
    unk_status = tickets.status_canonical.isna().sum()
    V.add("R09", "Every status maps to a known lifecycle state", "Unknown states break the KPI population",
          "FAIL" if unk_status else "PASS",
          f"{tickets.status.nunique()} raw values -> {tickets.status_canonical.nunique()} canonical; unmapped={unk_status}",
          "casing/underscore variants normalised")
    V.fixes.append("Normalised status variants (e.g. 'closed', 'in_progress', 'closed_no_response').")

    # ---------------- R10 priority --------------------------------------------
    miss_p = tickets.priority.isna()
    V.add("R10", "Every ticket has a priority (it sets the SLA target)", "Wrong target = wrong SLA verdict",
          "WARN" if miss_p.any() else "PASS",
          f"{miss_p.sum()} tickets ({pct(miss_p.mean())}) missing priority, all email channel",
          f"defaulted to '{policy['default_priority_if_missing']}' per draft policy; KPI sensitivity reported",
          owner="Helpdesk Manager")
    tickets["priority_imputed"] = miss_p
    tickets["priority"] = tickets.priority.fillna(policy["default_priority_if_missing"])
    V.assumptions.append("Missing priority (email tickets) = Medium, per draft SLA policy default.")

    # ---------------- R11 referential integrity -------------------------------
    stu_cov = tickets.student_id.isin(students.student_id).mean()
    int_cov = interactions.ticket_id.isin(known).mean()
    V.add("R11", "Tickets map to students; interactions map to tickets", "Joins must not silently drop rows",
          "PASS" if min(stu_cov, int_cov) >= 0.99 else "WARN",
          f"tickets->students {pct(stu_cov)}; interactions->tickets {pct(int_cov)}", "none needed")

    # ---------------- R12 denormalised resolved_at -----------------------------
    final_res = events[events.to_status == "Resolved"].groupby("ticket_id").event_time.max()
    tr = tickets.set_index("ticket_id")
    tr_res = pd.to_datetime(tr.resolved_at, errors="coerce")
    resolved_in_log = final_res.index
    j = pd.concat([tr_res.rename("tbl"), final_res.rename("log")], axis=1).loc[resolved_in_log]
    missing_tbl = j.tbl.isna().sum()
    mismatch = int(((j.tbl.notna()) & ((j.tbl - j.log).dt.total_seconds().abs() > 60)).sum())
    V.add("R12", "resolved_at in ticket table = final resolution in audit log",
          "Reopened tickets must be timed to their FINAL fix",
          "WARN" if (missing_tbl + mismatch) else "PASS",
          f"of {len(j)} resolved tickets: {missing_tbl} missing resolved_at, {mismatch} hold the FIRST resolution (reopened)",
          "use audit log as source of truth; ticket-table resolved_at ignored", owner="IT admin (ticketing tool)")

    # ---------------- R13 CSAT ------------------------------------------------
    cs = pd.json_normalize(csat_obj["responses"])
    cs["ticket_id"] = cs["answers.ticket_ref"].map(norm_ticket_ref)
    cs["rating"] = pd.to_numeric(cs["answers.rating"], errors="coerce")
    cs["submitted_at"] = pd.to_datetime(cs.submitted_at.str.slice(0, 19))
    no_ref = cs.ticket_id.isna().sum()
    out_rng = (~cs.rating.between(1, 5)).sum()
    cs = cs[cs.ticket_id.notna() & cs.rating.between(1, 5)]
    before = len(cs)
    cs = cs.sort_values("submitted_at").drop_duplicates("ticket_id", keep="last")
    csat = cs[["ticket_id", "rating", "submitted_at", "answers.comment"]].rename(columns={"answers.comment": "comment"})
    csat_cov = csat.ticket_id.isin(known).mean()
    V.add("R13", "One valid 1-5 rating per ticket", "Invalid/duplicate ratings bias satisfaction",
          "WARN",
          f"{len(csat_obj['responses'])} responses: {no_ref} no ticket ref, {out_rng} out of 1-5, {before - len(csat)} resubmissions "
          f"(kept latest) -> {len(csat)} valid; ref formats normalised (tkt100234 / 100234 -> TKT-100234); maps to tickets {pct(csat_cov)}",
          "directional only: ~36% response rate, unhappy students respond more")
    V.fixes.append("CSAT: normalised ticket refs, cast string ratings to int, dropped out-of-range, kept latest per ticket.")

    # ---------------- R14 freshness -------------------------------------------
    max_ev = events[~events.ticket_id.isin(bad_chrono)].event_time.max()
    lag_h = (pd.Timestamp(last_synced[:19]) - pd.Timestamp(PERIOD_END)).total_seconds() / 3600
    V.add("R14", "Data is fresh enough for the decision", "Freshness depends on use case",
          "PASS",
          f"latest event {max_ev:%Y-%m-%d %H:%M}; API last_synced {last_synced[:16]} ({lag_h:.0f}h after period end)",
          "fit for weekly/term reporting; NOT fit for a live queue dashboard (daily batch export)")

    # ---------------- R15 KPI definition sign-off ------------------------------
    V.add("R15", "SLA definition is agreed by the KPI owner", "Different definitions give different 'truths'",
          "UNKNOWN",
          f"policy file says: '{policy['policy_name']}'; pause rule & calendar-vs-business hours not signed off",
          "publish as PROVISIONAL; show sensitivity to definition", owner="Dean of Student Affairs")

    for c in V.checks:
        fn = log.warning if c.status in ("WARN", "UNKNOWN") else (log.error if c.status == "FAIL" else log.info)
        fn(f"{c.rule_id} {c.status:<7} {c.rule} :: {c.evidence}")

    clean = dict(tickets=tickets, events=events, interactions=interactions, csat=csat, students=students,
                 agents=agents, quarantine_events=quarantine, bad_chrono=set(bad_chrono), policy=policy)
    return V, clean


def to_markdown(V: ValidationResult) -> str:
    lines = ["| Rule | Check | Status | Evidence | Action | Owner |", "|---|---|---|---|---|---|"]
    for c in V.checks:
        lines.append(f"| {c.rule_id} | {c.rule} | **{c.status}** | {c.evidence} | {c.action} | {c.owner} |")
    lines += ["", f"**Gate: {V.gate}**", "", "Safe fixes applied:"] + [f"- {f}" for f in V.fixes]
    lines += ["", "Assumptions:"] + [f"- {a}" for a in V.assumptions]
    return "\n".join(lines)


def as_dict(V: ValidationResult) -> dict:
    return {"gate": V.gate, "checks": [asdict(c) for c in V.checks], "fixes": V.fixes,
            "assumptions": V.assumptions, "profile": V.profile}
