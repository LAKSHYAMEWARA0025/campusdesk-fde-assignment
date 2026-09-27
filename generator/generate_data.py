"""
CampusDesk synthetic data generator.

Simulates 8 weeks (27 Jul - 20 Sep 2026) of a college Student Services
Helpdesk and writes the data the way the real source systems would hold it:

  source_systems/helpdesk.db              SQLite  - ticketing tool (tickets, students, agents)
  source_systems/ticket_events.csv        CSV     - status / assignment audit log export
  source_systems/csat_survey_export.json  JSON    - nested survey-form export
  source_systems/portal_api_data.json     backing store for the mock Portal REST API
                                                    (student follow-ups & agent replies)
  source_systems/sla_policy.json          JSON    - SLA policy config

Realistic *workflow* behaviour is simulated first (triage queue, working hours,
department backlogs, misrouting, waiting-on-student pauses, reopen cycles,
escalations, reminders, CSAT). Realistic *data problems* are then injected so
that profiling and cleaning have something real to find.

The simulated ground truth is written to synthetic_truth/ ONLY so we can
later prove the pipeline recovers the true KPI. The pipeline never reads it.

Run:  python generator/generate_data.py            (seed 42, deterministic)
"""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "source_systems"
TRUTH = ROOT / "synthetic_truth"

START = datetime(2026, 7, 27)          # Monday
END = datetime(2026, 9, 20, 23, 59)    # Sunday (8 weeks)
EXPORT_TIME = datetime(2026, 9, 21, 6, 0)

rng = np.random.default_rng(SEED)
random.seed(SEED)

# ----------------------------------------------------------------------------
# Reference data
# ----------------------------------------------------------------------------
DEPTS = {
    #            agents  first-response mean (working h)  work median (h)  working hours (days, start, end)
    "IT Support":          dict(n=4, fr=3.0,  work=5.0,  days=range(0, 6), start=8, end=20),
    "Hostel & Maintenance": dict(n=3, fr=9.0,  work=18.0, days=range(0, 6), start=8, end=20),
    "Fees & Finance":      dict(n=2, fr=12.0, work=14.0, days=range(0, 5), start=9, end=17),
    "Academics & Exams":   dict(n=2, fr=7.0,  work=12.0, days=range(0, 5), start=9, end=17),
    "Library":             dict(n=1, fr=4.0,  work=3.0,  days=range(0, 6), start=9, end=18),
}
TRIAGE_DAYS, TRIAGE_START, TRIAGE_END = range(0, 6), 9, 18   # Mon-Sat, no Sunday triage
SLA_HOURS = {"High": 24, "Medium": 72, "Low": 120}

SUBJECTS = {
    "IT Support": ["Wi-Fi not working in room", "Cannot log in to LMS", "Email account locked",
                   "Laptop not connecting to campus network", "VPN access request", "Printer quota issue"],
    "Hostel & Maintenance": ["Fan not working", "Water leakage in bathroom", "Room lock broken",
                             "No hot water", "AC not cooling", "Mess food complaint", "Pest issue in room"],
    "Fees & Finance": ["Fee receipt not generated", "Scholarship amount not credited", "Refund of caution deposit",
                       "Late fee charged wrongly", "Installment plan request"],
    "Academics & Exams": ["Hall ticket not generated", "Wrong marks uploaded", "Course registration error",
                          "Attendance shortage query", "Re-evaluation request", "Exam clash"],
    "Library": ["Book renewal failed", "Library fine dispute", "E-resource access issue"],
}
FIRST = ["Aarav", "Vivaan", "Aditya", "Ananya", "Diya", "Ishaan", "Kavya", "Rohan", "Saanvi", "Arjun",
         "Meera", "Kabir", "Nisha", "Rahul", "Priya", "Tanvi", "Yash", "Zoya", "Dev", "Riya"]
LAST = ["Sharma", "Verma", "Iyer", "Reddy", "Nair", "Gupta", "Khan", "Das", "Patel", "Singh", "Rao", "Mehta"]


def in_working(dt: datetime, days, start, end) -> bool:
    return dt.weekday() in days and start <= dt.hour < end


def add_working_hours(dt: datetime, hours: float, days, start, end) -> datetime:
    """Advance dt by `hours` of working time (the clock only runs inside working windows)."""
    remaining = hours * 3600.0
    cur = dt
    while True:
        if cur.weekday() not in days or cur.hour >= end:
            cur = (cur + timedelta(days=1)).replace(hour=start, minute=0, second=0, microsecond=0)
            continue
        if cur.hour < start:
            cur = cur.replace(hour=start, minute=0, second=0, microsecond=0)
            continue
        window_end = cur.replace(hour=end, minute=0, second=0, microsecond=0)
        avail = (window_end - cur).total_seconds()
        if remaining <= avail:
            return cur + timedelta(seconds=remaining)
        remaining -= avail
        cur = window_end


def lognormal(median: float, sigma: float = 0.7) -> float:
    return float(rng.lognormal(np.log(median), sigma))


# ----------------------------------------------------------------------------
# Students & agents
# ----------------------------------------------------------------------------
N_STUDENTS = 1800
students = []
for i in range(N_STUDENTS):
    yr = int(rng.choice([1, 2, 3, 4], p=[0.3, 0.27, 0.23, 0.2]))
    students.append(dict(
        student_id=f"STU{24000 + i}",
        full_name=f"{random.choice(FIRST)} {random.choice(LAST)}",
        program=str(rng.choice(["B.Tech CSE", "B.Tech ECE", "B.Tech ME", "BBA", "B.Des"], p=[0.45, 0.2, 0.15, 0.12, 0.08])),
        year=yr,
        hostel_block=str(rng.choice(["A", "B", "C", "D", "E", "Day scholar"], p=[0.18, 0.18, 0.18, 0.16, 0.15, 0.15])),
        email=f"stu{24000 + i}@campus.example.edu",
    ))
students_df = pd.DataFrame(students)

agents = []
aid = 1
for dept, cfg in DEPTS.items():
    for k in range(cfg["n"]):
        agents.append(dict(agent_id=f"AGT{aid:03d}", agent_name=f"{random.choice(FIRST)} {random.choice(LAST)}",
                           department=dept, role="Agent", active=1))
        aid += 1
for k in range(2):
    agents.append(dict(agent_id=f"AGT{aid:03d}", agent_name=f"{random.choice(FIRST)} {random.choice(LAST)}",
                       department="Helpdesk Triage", role="Coordinator", active=1))
    aid += 1
agents.append(dict(agent_id=f"AGT{aid:03d}", agent_name="Helpdesk Manager", department="Helpdesk Triage",
                   role="Manager", active=1))
agents_df = pd.DataFrame(agents)
AGENTS_BY_DEPT = {d: agents_df[agents_df.department == d].agent_id.tolist() for d in DEPTS}
COORDS = agents_df[agents_df.role == "Coordinator"].agent_id.tolist()
MANAGER = agents_df[agents_df.role == "Manager"].agent_id.iloc[0]

# ----------------------------------------------------------------------------
# Ticket arrivals
# ----------------------------------------------------------------------------
def category_mix(day: datetime):
    week = (day - START).days // 7
    mix = {"IT Support": 0.34, "Hostel & Maintenance": 0.26, "Fees & Finance": 0.14,
           "Academics & Exams": 0.18, "Library": 0.08}
    if week <= 1:                      # move-in weeks: hostel + fees spike
        mix["Hostel & Maintenance"] += 0.10
        mix["Fees & Finance"] += 0.06
    if week in (6, 7):                 # mid-sem exams: academics spike
        mix["Academics & Exams"] += 0.14
    tot = sum(mix.values())
    return {k: v / tot for k, v in mix.items()}


def daily_volume(day: datetime) -> int:
    week = (day - START).days // 7
    base = 26 if week <= 1 else 21
    if week in (6, 7):
        base += 5
    if day.weekday() == 6:
        base *= 0.55
    elif day.weekday() == 5:
        base *= 0.75
    return int(rng.poisson(base))


HOUR_P = np.array([0.2, 0.1, 0.05, 0.05, 0.05, 0.1, 0.3, 0.8, 1.5, 2.5, 3.0, 3.0,
                   2.6, 2.6, 2.8, 2.8, 2.6, 2.4, 2.2, 2.2, 2.4, 2.4, 1.6, 0.8])
HOUR_P = HOUR_P / HOUR_P.sum()

tickets, events, interactions, csat_truth, truth_rows = [], [], [], [], []
tid = 100001
eid = 1
iid = 1


def ev(ticket_id, ts, etype, actor, from_status=None, to_status=None, dept=None, note=None):
    global eid
    events.append(dict(event_id=f"EV{eid:06d}", ticket_id=ticket_id, event_time=ts, event_type=etype,
                       actor_id=actor, from_status=from_status, to_status=to_status,
                       department=dept, note=note))
    eid += 1


def inter(ticket_id, ts, author_type, author_id, kind, text):
    global iid
    interactions.append(dict(interaction_id=f"INT{iid:06d}", ticket_id=ticket_id, created_at=ts,
                             author_type=author_type, author_id=author_id, kind=kind, message=text))
    iid += 1


ALL_DEPTS = list(DEPTS.keys())
day = START
while day <= END:
    for _ in range(daily_volume(day)):
        hour = int(rng.choice(24, p=HOUR_P))
        created = day.replace(hour=hour, minute=int(rng.integers(0, 60)), second=int(rng.integers(0, 60)))
        if created > END:
            continue
        mix = category_mix(day)
        true_cat = str(rng.choice(list(mix), p=list(mix.values())))
        channel = str(rng.choice(["portal", "email", "walk_in"], p=[0.58, 0.32, 0.10]))
        if channel == "walk_in" and not in_working(created, range(0, 6), 9, 18):
            channel = "portal"
        priority = str(rng.choice(["High", "Medium", "Low"], p=[0.15, 0.60, 0.25]))
        stu = students_df.sample(1, random_state=int(rng.integers(0, 1e9))).iloc[0]
        ticket_id = f"TKT-{tid}"
        tid += 1

        # --- how is it categorised at intake? ---------------------------------
        if channel == "portal":
            r = rng.random()
            filed = true_cat if r < 0.78 else ("Other" if r < 0.88 else str(rng.choice([d for d in ALL_DEPTS if d != true_cat])))
        elif channel == "email":
            filed = None                 # emails have no category -> manual triage
        else:
            filed = true_cat if rng.random() < 0.95 else "Other"

        ev(ticket_id, created, "created", stu.student_id, None, "New", None, f"channel={channel}")
        t = created
        needs_manual_triage = filed in (None, "Other")

        # --- triage -----------------------------------------------------------
        if needs_manual_triage:
            wait = rng.exponential(2.5)
            t = add_working_hours(t, wait, TRIAGE_DAYS, TRIAGE_START, TRIAGE_END)
            # coordinators get it right 85% of the time
            first_dept = true_cat if rng.random() < 0.85 else str(rng.choice([d for d in ALL_DEPTS if d != true_cat]))
            triager = random.choice(COORDS)
        else:
            t = t + timedelta(minutes=float(rng.uniform(1, 15)))   # auto-routing rule
            first_dept = filed
            triager = "SYSTEM"
        triage_done = t
        agent = random.choice(AGENTS_BY_DEPT[first_dept])
        ev(ticket_id, t, "assigned", triager, "New", "Assigned", first_dept, f"assigned_to={agent}")

        # --- routing hops (misrouted tickets bounce) ---------------------------
        cur_dept = first_dept
        reassign_count = 0
        first_response = None
        reminder_sent = False
        escalated = False
        escalated_at = None
        sla_deadline_gross = created + timedelta(hours=SLA_HOURS[priority])
        while True:
            cfg = DEPTS[cur_dept]
            fr_wait = rng.exponential(cfg["fr"])
            fr_time = add_working_hours(t, fr_wait, cfg["days"], cfg["start"], cfg["end"])
            # auto-reminder to agent after 24h without first response (portal feature)
            if first_response is None and not reminder_sent and (fr_time - t).total_seconds() > 24 * 3600:
                ev(ticket_id, t + timedelta(hours=24), "reminder_sent", "SYSTEM", None, None, cur_dept,
                   "auto-reminder: no response in 24h")
                reminder_sent = True
                fr_time = t + timedelta(hours=24) + (fr_time - t - timedelta(hours=24)) * 0.7
            t = fr_time
            if first_response is None:
                first_response = t
            ev(ticket_id, t, "first_response" if reassign_count == 0 else "agent_response", agent,
               "Assigned", "In Progress", cur_dept, None)
            inter(ticket_id, t + timedelta(minutes=2), "agent", agent, "agent_reply",
                  "Hi, we are looking into this." if cur_dept == true_cat else "This does not belong to our team, routing it.")
            if cur_dept == true_cat:
                break
            # misrouted -> reassign (back via triage queue)
            reassign_count += 1
            hop = rng.exponential(3.0)
            t = add_working_hours(t, hop, TRIAGE_DAYS, TRIAGE_START, TRIAGE_END)
            nxt = true_cat if rng.random() < 0.8 else str(rng.choice([d for d in ALL_DEPTS if d not in (true_cat, cur_dept)]))
            agent = random.choice(AGENTS_BY_DEPT[nxt])
            ev(ticket_id, t, "reassigned", random.choice(COORDS), "In Progress", "Assigned", nxt,
               f"from={cur_dept}; assigned_to={agent}")
            cur_dept = nxt

        # --- work, optional waiting-on-student pause ---------------------------
        cfg = DEPTS[cur_dept]
        work = lognormal(cfg["work"], 0.8)
        pause_hours = 0.0
        no_response_close = False
        if rng.random() < 0.28:
            ask_at = add_working_hours(t, work * 0.3, cfg["days"], cfg["start"], cfg["end"])
            ev(ticket_id, ask_at, "status_change", agent, "In Progress", "Waiting on Student", cur_dept,
               "asked student for details")
            inter(ticket_id, ask_at + timedelta(minutes=1), "agent", agent, "info_request",
                  "Could you share more details / a screenshot?")
            if rng.random() < 0.09:
                no_response_close = True
                closed = ask_at + timedelta(hours=72)
                ev(ticket_id, closed, "status_change", "SYSTEM", "Waiting on Student", "Closed - No Response",
                   cur_dept, "auto-closed after 72h without student reply")
                final_status = "Closed - No Response"
                resolved_final = None
                t = closed
            else:
                reply = lognormal(8.0, 0.9)
                back = ask_at + timedelta(hours=reply)
                pause_hours = reply
                inter(ticket_id, back, "student", stu.student_id, "student_reply", "Sharing the details requested.")
                ev(ticket_id, back, "status_change", stu.student_id, "Waiting on Student", "In Progress", cur_dept,
                   "student replied")
                t = add_working_hours(back, work * 0.7, cfg["days"], cfg["start"], cfg["end"])
        else:
            t = add_working_hours(t, work, cfg["days"], cfg["start"], cfg["end"])

        reopened = False
        first_resolved = None
        if not no_response_close:
            # escalation: manager reviews daily at 10:00 on weekdays, escalates tickets open > 48h
            chk = created.replace(hour=10, minute=0, second=0) + timedelta(days=1)
            while chk < t:
                if chk.weekday() < 5 and (chk - created).total_seconds() > 48 * 3600:
                    escalated, escalated_at = True, chk
                    routed = [e for e in events if e["ticket_id"] == ticket_id
                              and e["event_type"] in ("assigned", "reassigned") and e["event_time"] <= chk]
                    esc_dept = routed[-1]["department"] if routed else cur_dept
                    ev(ticket_id, chk, "escalated", MANAGER, None, None, esc_dept, "open > 48h in daily review")
                    # escalation speeds up the work remaining after the latest recorded activity
                    last_ev = max(e["event_time"] for e in events if e["ticket_id"] == ticket_id)
                    base = max(chk, last_ev)
                    t = add_working_hours(base + (t - base) * 0.6, 0, cfg["days"], cfg["start"], cfg["end"])
                    break
                chk += timedelta(days=1)
            first_resolved = t
            ev(ticket_id, t, "status_change", agent, "In Progress", "Resolved", cur_dept, "resolution provided")
            # reopen: quick hostel fixes + misrouted tickets reopen more often
            p_reopen = 0.06 + (0.08 if cur_dept == "Hostel & Maintenance" else 0) + 0.04 * reassign_count
            if rng.random() < p_reopen:
                reopened = True
                ro = t + timedelta(hours=lognormal(20, 0.6))
                ev(ticket_id, ro, "status_change", stu.student_id, "Resolved", "Reopened", cur_dept,
                   "student: issue not fixed")
                inter(ticket_id, ro, "student", stu.student_id, "reopen_comment", "The issue is back / not fixed.")
                t = add_working_hours(ro, lognormal(cfg["work"] * 0.6, 0.6), cfg["days"], cfg["start"], cfg["end"])
                ev(ticket_id, t, "status_change", agent, "Reopened", "Resolved", cur_dept, "resolved after reopen")
            resolved_final = t
            final_status = "Resolved"
            # auto-close 3 days after resolution
            if t + timedelta(days=3) < EXPORT_TIME:
                ev(ticket_id, t + timedelta(days=3), "status_change", "SYSTEM", "Resolved", "Closed", cur_dept,
                   "auto-closed 3 days after resolution")
                final_status = "Closed"

        # tickets still open at export time: truncate lifecycle
        end_time = resolved_final or t
        if end_time > EXPORT_TIME:
            # drop events after the export time -> still open
            events[:] = [e for e in events if not (e["ticket_id"] == ticket_id and e["event_time"] > EXPORT_TIME)]
            interactions[:] = [x for x in interactions if not (x["ticket_id"] == ticket_id and x["created_at"] > EXPORT_TIME)]
            final_status = "In Progress" if first_response and first_response < EXPORT_TIME else "Assigned"
            resolved_final = None
            first_resolved = first_resolved if (first_resolved and first_resolved <= EXPORT_TIME) else None

        # --- student follow-ups ("any update?") grow with waiting time --------
        horizon = (resolved_final or min(end_time, EXPORT_TIME)) - created
        exp_followups = max(horizon.total_seconds() / 3600 - 12, 0) / 30.0
        for k in range(int(rng.poisson(exp_followups))):
            ts = created + timedelta(hours=float(rng.uniform(12, max(horizon.total_seconds() / 3600, 12.1))))
            if ts <= EXPORT_TIME:
                inter(ticket_id, ts, "student", stu.student_id, "follow_up",
                      random.choice(["Any update on this?", "It has been days, please help.",
                                     "Still waiting for a response.", "Please escalate this."]))

        # --- truth row ---------------------------------------------------------
        net_hours = None
        sla_met = None
        if resolved_final is not None:
            net_hours = (resolved_final - created).total_seconds() / 3600 - pause_hours
            sla_met = net_hours <= SLA_HOURS[priority]
        truth_rows.append(dict(ticket_id=ticket_id, true_category=true_cat, channel=channel, priority=priority,
                               created_at=created, first_dept=first_dept, reassign_count=reassign_count,
                               manual_triage=needs_manual_triage, triage_hours=(triage_done - created).total_seconds() / 3600,
                               pause_hours=pause_hours, reopened=reopened, escalated=escalated,
                               reminder_sent=reminder_sent, final_status=final_status,
                               resolved_final=resolved_final, net_resolution_hours=net_hours, sla_met=sla_met))

        # --- CSAT (sent on resolution; breached tickets respond more) ----------
        if resolved_final is not None and resolved_final + timedelta(hours=6) < EXPORT_TIME:
            p_resp = 0.44 if sla_met is False else 0.30
            if rng.random() < p_resp:
                score = 4.5 - (1.4 if not sla_met else 0) - 0.6 * reassign_count - (0.9 if reopened else 0) \
                        + rng.normal(0, 0.6)
                csat_truth.append(dict(ticket_id=ticket_id, rating=int(np.clip(round(score), 1, 5)),
                                       submitted_at=resolved_final + timedelta(hours=float(rng.uniform(1, 40))),
                                       email=stu.email))

        tickets.append(dict(ticket_id=ticket_id, student_id=stu.student_id, channel=channel,
                            category=filed if filed else None, priority=priority,
                            subject=random.choice(SUBJECTS[true_cat]), created_at=created,
                            status=final_status, current_department=cur_dept,
                            resolved_at=resolved_final, last_updated_at=min(end_time, EXPORT_TIME)))
    day += timedelta(days=1)

# For tickets triaged manually the coordinator writes the department they chose
# back into the category field (this is how the real tool behaves).
first_dept_by_ticket = {r["ticket_id"]: r["first_dept"] for r in truth_rows}
for tk in tickets:
    if tk["category"] in (None, "Other") and tk["channel"] != "portal":
        tk["category"] = first_dept_by_ticket[tk["ticket_id"]]
    elif tk["category"] == "Other" and rng.random() < 0.6:
        tk["category"] = first_dept_by_ticket[tk["ticket_id"]]

truth_df = pd.DataFrame(truth_rows)

# ============================================================================
# DATA-QUALITY INJECTION (what real exports look like)
# ============================================================================
tk_df = pd.DataFrame(tickets)
ev_df = pd.DataFrame(events).sort_values("event_time").reset_index(drop=True)
int_df = pd.DataFrame(interactions).sort_values("created_at").reset_index(drop=True)
dq_log = {}

# 1. Category spelling variants (representation) + semantic variants ("Exam Cell")
variants = {
    "IT Support": ["IT Support", "it support", "IT support ", "IT"],
    "Hostel & Maintenance": ["Hostel & Maintenance", "hostel maintenance", "Hostel", "HOSTEL "],
    "Fees & Finance": ["Fees & Finance", "Fees", "Finance", "fees & finance"],
    "Academics & Exams": ["Academics & Exams", "Academics", "Exam Cell", "academics & exams"],
    "Library": ["Library", "library", "Library "],
}
def vary(c):
    if c is None or c == "Other":
        return c
    return c if rng.random() < 0.7 else str(rng.choice(variants[c]))
tk_df["category"] = tk_df["category"].map(vary)

# 2. Status variants
status_var = {"Closed": ["Closed", "closed", "CLOSED"], "Resolved": ["Resolved", "resolved"],
              "In Progress": ["In Progress", "in_progress"], "Assigned": ["Assigned"],
              "Closed - No Response": ["Closed - No Response", "closed_no_response"]}
tk_df["status"] = tk_df["status"].map(lambda s: s if rng.random() < 0.8 else str(rng.choice(status_var[s])))

# 3. Priority missing for many email tickets (importer does not map it)
email_mask = (tk_df.channel == "email") & (rng.random(len(tk_df)) < 0.35)
tk_df.loc[email_mask, "priority"] = None
dq_log["priority_missing"] = int(email_mask.sum())

# 4. Mixed timestamp formats: email importer writes DD/MM/YYYY HH:MM
def fmt_ts(x, email):
    if pd.isna(x):
        return None
    return x.strftime("%d/%m/%Y %H:%M") if email else x.strftime("%Y-%m-%d %H:%M:%S")
emails = tk_df.channel.eq("email")
tk_df["created_at"] = [fmt_ts(x, e and rng.random() < 0.5) for x, e in zip(tk_df.created_at, emails)]
tk_df["last_updated_at"] = [fmt_ts(x, False) for x in tk_df.last_updated_at]

# 5. Denormalised resolved_at in the ticket table is unreliable:
#    missing for ~3% of resolved tickets, and for reopened tickets it still holds the FIRST resolution time
res = []
reopened_ids = set(truth_df.loc[truth_df.reopened, "ticket_id"])
first_res = {}
for e in events:
    if e["to_status"] == "Resolved" and e["ticket_id"] not in first_res:
        first_res[e["ticket_id"]] = e["event_time"]
for _, r in tk_df.iterrows():
    v = r.resolved_at
    if pd.notna(v) and r.ticket_id in reopened_ids:
        v = first_res.get(r.ticket_id, v)
    if pd.notna(v) and rng.random() < 0.03:
        v = None
    res.append(None if v is None or pd.isna(v) else v.strftime("%Y-%m-%d %H:%M:%S"))
tk_df["resolved_at"] = res

# 6. Exact duplicate rows (email importer double-sync) ~2%
dups = tk_df.sample(frac=0.02, random_state=SEED)
tk_df = pd.concat([tk_df, dups]).reset_index(drop=True)
dq_log["exact_duplicate_rows"] = len(dups)

# 7. Student double-submissions: same student + subject within 10 min, new ticket id
doubles = tk_df.drop_duplicates("ticket_id").sample(n=22, random_state=7).copy()
new_ids, dbl_events = [], []
for _, r in doubles.iterrows():
    nid = f"TKT-{tid}"
    tid += 1
    new_ids.append(nid)
doubles["ticket_id"] = new_ids
doubles["created_at"] = [
    ((datetime.strptime(c, "%d/%m/%Y %H:%M") if "/" in c else datetime.strptime(c, "%Y-%m-%d %H:%M:%S"))
     + timedelta(minutes=int(rng.integers(1, 9)))).strftime("%Y-%m-%d %H:%M:%S")
    for c in doubles.created_at]
doubles["status"] = "Cancelled"
doubles["resolved_at"] = None
for _, r in doubles.iterrows():
    ev_df.loc[len(ev_df)] = dict(event_id=f"EV{eid:06d}", ticket_id=r.ticket_id,
                                 event_time=pd.to_datetime(r.created_at), event_type="created",
                                 actor_id=r.student_id, from_status=None, to_status="New", department=None,
                                 note=f"channel={r.channel}")
    eid += 1
    ev_df.loc[len(ev_df)] = dict(event_id=f"EV{eid:06d}", ticket_id=r.ticket_id,
                                 event_time=pd.to_datetime(r.created_at) + timedelta(hours=2),
                                 event_type="status_change", actor_id=COORDS[0], from_status="New",
                                 to_status="Cancelled", department=None, note="duplicate of earlier ticket")
    eid += 1
tk_df = pd.concat([tk_df, doubles]).reset_index(drop=True)
dq_log["double_submissions_cancelled"] = len(doubles)

# 8. Event log problems: duplicate events, orphans, clock-skewed walk-in desk events
dup_ev = ev_df.sample(frac=0.01, random_state=3)
ev_df = pd.concat([ev_df, dup_ev]).reset_index(drop=True)
dq_log["duplicate_events"] = len(dup_ev)
orph = ev_df.sample(n=40, random_state=4).copy()
orph["ticket_id"] = [f"TKT-{9000000 + i}" for i in range(len(orph))]
orph["event_id"] = [f"EV{eid + i:06d}" for i in range(len(orph))]
eid += len(orph)
ev_df = pd.concat([ev_df, orph]).reset_index(drop=True)
dq_log["orphan_events"] = len(orph)
walkin_ids = truth_df[(truth_df.channel == "walk_in") & truth_df.resolved_final.notna()].ticket_id.sample(8, random_state=5)
skew_mask = ev_df.ticket_id.isin(walkin_ids) & ev_df.event_type.eq("created")
ev_df.loc[skew_mask, "event_time"] = ev_df.loc[skew_mask, "event_time"] + timedelta(days=5)
dq_log["clock_skewed_created_events"] = int(skew_mask.sum())
ev_df["event_time"] = pd.to_datetime(ev_df.event_time).dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
ev_df = ev_df.sample(frac=1, random_state=11).reset_index(drop=True)   # exports are not ordered

# ----------------------------------------------------------------------------
# Write source systems
# ----------------------------------------------------------------------------
OUT.mkdir(parents=True, exist_ok=True)
TRUTH.mkdir(parents=True, exist_ok=True)

db = OUT / "helpdesk.db"
if db.exists():
    db.unlink()
con = sqlite3.connect(db)
con.executescript("""
CREATE TABLE students (student_id TEXT PRIMARY KEY, full_name TEXT, program TEXT, year INTEGER,
                       hostel_block TEXT, email TEXT);
CREATE TABLE agents   (agent_id TEXT PRIMARY KEY, agent_name TEXT, department TEXT, role TEXT, active INTEGER);
CREATE TABLE tickets  (ticket_id TEXT, student_id TEXT, channel TEXT, category TEXT, priority TEXT,
                       subject TEXT, created_at TEXT, status TEXT, current_department TEXT,
                       resolved_at TEXT, last_updated_at TEXT);  -- NOTE: no PK (legacy import table)
""")
students_df.to_sql("students", con, if_exists="append", index=False)
agents_df.to_sql("agents", con, if_exists="append", index=False)
tk_df.to_sql("tickets", con, if_exists="append", index=False)
con.commit()
con.close()

ev_df.to_csv(OUT / "ticket_events.csv", index=False)

# CSAT: nested survey export with messy refs, string ratings, out-of-range and duplicate responses
responses = []
for k, c in enumerate(csat_truth):
    num = c["ticket_id"].split("-")[1]
    ref = random.choice([c["ticket_id"]] * 6 + [f"tkt{num}", num, f"TKT {num}"])
    rating = c["rating"]
    rating_out = str(rating) if rng.random() < 0.3 else rating
    responses.append({"response_id": f"R{k + 1:05d}",
                      "submitted_at": c["submitted_at"].strftime("%Y-%m-%dT%H:%M:%S+05:30"),
                      "respondent": {"email": c["email"]},
                      "answers": {"ticket_ref": ref, "rating": rating_out,
                                  "comment": random.choice(["", "", "Thanks!", "Took too long.", "Resolved well.",
                                                            "Had to follow up many times.", "Good support."])}})
bad = []
for k in range(9):          # out of range (someone used a 10-point scale / 0)
    src = random.choice(responses)
    bad.append({**src, "response_id": f"R9{k:04d}",
                "answers": {**src["answers"], "rating": random.choice([0, 7, 9, 10])}})
dupe = [dict(r, response_id=r["response_id"] + "b") for r in random.sample(responses, 15)]
for d in dupe:              # resubmitted survey, later timestamp
    d["submitted_at"] = (pd.to_datetime(d["submitted_at"]) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
missing_ref = [{**random.choice(responses), "response_id": f"R8{k:04d}"} for k in range(6)]
for m in missing_ref:
    m["answers"] = {**m["answers"], "ticket_ref": ""}
all_resp = responses + bad + dupe + missing_ref
random.shuffle(all_resp)
survey = {"form_id": "CSAT-HELPDESK-2026", "form_title": "How did we do? (Helpdesk)",
          "exported_at": EXPORT_TIME.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
          "question_map": {"ticket_ref": "Ticket number", "rating": "Rate your experience (1-5)",
                           "comment": "Anything else?"},
          "responses": all_resp}
(OUT / "csat_survey_export.json").write_text(json.dumps(survey, indent=1))
dq_log["csat_out_of_range"] = len(bad)
dq_log["csat_duplicates"] = len(dupe)
dq_log["csat_missing_ref"] = len(missing_ref)

# Portal API backing data
int_df["created_at"] = pd.to_datetime(int_df.created_at).dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
(OUT / "portal_api_data.json").write_text(json.dumps({
    "last_synced_at": EXPORT_TIME.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
    "interactions": int_df.to_dict(orient="records")}))

(OUT / "sla_policy.json").write_text(json.dumps({
    "policy_name": "Student Helpdesk SLA v1 (draft, not formally signed off)",
    "resolution_targets_hours": SLA_HOURS,
    "clock": "calendar hours from ticket creation to FINAL resolution",
    "pause_states": ["Waiting on Student"],
    "excluded_final_states": ["Cancelled", "Closed - No Response"],
    "default_priority_if_missing": "Medium",
    "owner": "Dean of Student Affairs (sponsor) / Helpdesk Manager (operational owner)",
}, indent=2))

# Ground truth (NOT used by the pipeline)
truth_df.to_csv(TRUTH / "truth_tickets.csv", index=False)
(TRUTH / "injected_issues.json").write_text(json.dumps(dq_log, indent=2))

print("tickets (true):", len(truth_df))
print("ticket rows written:", len(tk_df))
print("events:", len(ev_df), "interactions:", len(int_df), "csat responses:", len(all_resp))
valid = truth_df[truth_df.sla_met.notna()]
print("TRUE SLA compliance: %.1f%%" % (100 * valid.sla_met.mean()))
print(truth_df.groupby("reassign_count").sla_met.agg(["count", "mean"]))
print("injected:", dq_log)
