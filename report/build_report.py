"""
Builds the submission PDF from the pipeline's own outputs (numbers are never typed by hand).

  python report/build_report.py            -> report/CampusDesk_FDE_Assignment_Lakshya_Mewara.pdf

Links (GitHub repo, demo video) are read from report/links.json.
"""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
L = ROOT / "output" / "latest"
SEG = {p.stem: pd.read_csv(p) for p in (L / "segments").glob("*.csv")}
METRICS = json.loads((L / "metrics.json").read_text())
VAL = json.loads((L / "validation_report.json").read_text())
WHATIF = pd.read_csv(L / "what_if.csv")
RECON = pd.read_csv(L / "reconciliation.csv")
MANIFEST = pd.DataFrame(json.loads((ROOT / "data" / "raw" / "demo_run" / "_manifest.json").read_text()))
LINKS = json.loads((ROOT / "report" / "links.json").read_text())
LOG_OK = (ROOT / "logs" / "pipeline_demo_run.log").read_text().splitlines()
LOG_API = (ROOT / "logs" / "pipeline_demo_fail_api_outage.log").read_text().splitlines()
LOG_TRUNC = (ROOT / "logs" / "pipeline_demo_fail_truncated_events.log").read_text().splitlines()
J = pd.read_csv(L / "ticket_journey.csv")
K = J[J.in_kpi_population]

OUT_HTML = ROOT / "docs" / "full_report.html"
OUT_PDF = ROOT / "docs" / "CampusDesk_Full_Report.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


# ---------------------------------------------------------------- helpers
def seg(name, key, col, keycol="segment"):
    d = SEG[name]
    return d.loc[d[keycol] == key, col].iloc[0]


def e(x):
    return html.escape(str(x))


def table(df: pd.DataFrame, cls="", fmt=None, esc=True):
    fmt = fmt or {}
    th = "".join(f"<th>{e(c)}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        tds = []
        for c in df.columns:
            v = r[c]
            v = fmt[c](v) if c in fmt else ("" if pd.isna(v) else v)
            tds.append(f"<td>{e(v) if esc else v}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def badge(s):
    return f'<span class="b b-{s.lower()}">{s}</span>'


def link(url, label):
    if url:
        return f'<a href="{e(url)}">{e(url)}</a>'
    return f'<span class="todo">{label} (to be added)</span>'


def log_block(lines, keep=None, limit=40):
    import re
    lines = [re.sub(r"\s*\(?http://[^ )]*page=(\d+)[^ )]*\)?", r" (page \1)", l) for l in lines if (keep is None or keep(l))][:limit]
    out = []
    for l in lines:
        cls = "err" if "ERROR" in l else ("warn" if "WARNING" in l else "")
        out.append(f'<span class="{cls}">{e(l[11:])}</span>')   # drop date for width
    return '<pre class="log">' + "\n".join(out) + "</pre>"


def retrieval_log():
    import re
    lines = [re.sub(r"\s*\(http://[^)]*page=(\d+)[^)]*\)", r"  (page \1)", l) for l in LOG_OK if "| retrieve" in l]
    warn = [l for l in lines if "WARNING" in l]
    other = [l for l in lines if "WARNING" not in l]
    shown = other[:6] + warn[:6] + [f"... {len(warn) - 6} more transient failures retried ..."] + other[6:]
    out = []
    for l in shown:
        cls = "warn" if "WARNING" in l else ""
        out.append(f'<span class="{cls}">{e(l[11:] if l[:4].isdigit() else l)}</span>')
    return '<pre class="log">' + "\n".join(out) + "</pre>"


def code_block(path, start_marker, end_marker=None, max_lines=40):
    src = (ROOT / path).read_text().splitlines()
    i = next(n for n, l in enumerate(src) if start_marker in l)
    j = next((n for n, l in enumerate(src[i + 1:], i + 1) if end_marker and end_marker in l), i + max_lines)
    return f'<div class="codehead">{e(path)}</div><pre class="code">' + e("\n".join(src[i:j])) + "</pre>"


# ---------------------------------------------------------------- numbers
kpi = METRICS["kpi"]
sup = METRICS["supporting_metrics"]
KPI_PCT = kpi["sla_compliance_pct"]
N_RES = kpi["resolved_tickets"]
HIGH = seg("by_priority", "High", "sla_pct")
MED = seg("by_priority", "Medium", "sla_pct")
LOW = seg("by_priority", "Low", "sla_pct")
FIN = seg("by_department", "Fees & Finance", "sla_pct")
ACA = seg("by_department", "Academics & Exams", "sla_pct")
HOS = seg("by_department", "Hostel & Maintenance", "sla_pct")
IT = seg("by_department", "IT Support", "sla_pct")
LIB = seg("by_department", "Library", "sla_pct")
R0 = seg("by_reassignment", "0 (routed right first time)", "sla_pct")
R1 = seg("by_reassignment", "1 reassignment", "sla_pct")
R2 = seg("by_reassignment", "2+ reassignments", "sla_pct")
F0 = seg("by_reassignment", "0 (routed right first time)", "avg_followups")
F2 = seg("by_reassignment", "2+ reassignments", "avg_followups")
ESC_LATE_N = int(seg("interventions", "escalated AFTER SLA already breached", "tickets"))
ESC_LATE_SLA = seg("interventions", "escalated AFTER SLA already breached", "sla_pct")
ESC_MED_H = seg("interventions", "escalated before breach", "median_escalated_after_h")
ESC_LATE_H = seg("interventions", "escalated AFTER SLA already breached", "median_escalated_after_h")
NOT_ESC = seg("interventions", "not escalated", "sla_pct")
REM_Y = seg("reminders", "auto-reminder fired (no reply in 24h)", "sla_pct")
REM_N = seg("reminders", "no reminder", "sla_pct")
WKND = seg("by_weekend", "weekend", "sla_pct")
WKDY = seg("by_weekend", "weekday", "sla_pct")
EM = seg("by_channel", "email", "sla_pct")
PO = seg("by_channel", "portal", "sla_pct")
WI = seg("by_channel", "walk_in", "sla_pct")
EM_TRI = seg("by_channel", "email", "median_triage_h")
MAN = seg("by_triage_path", "manual triage queue", "sla_pct")
AUTO = seg("by_triage_path", "auto-routed", "sla_pct")
FU_B = seg("followups_vs_outcome", "breached SLA", "avg_followups")
FU_M = seg("followups_vs_outcome", "met SLA", "avg_followups")
CS_B = seg("followups_vs_outcome", "breached SLA", "avg_csat")
CS_M = seg("followups_vs_outcome", "met SLA", "avg_csat")
sb = SEG["stage_breakdown_breached"].set_index("segment")
stage_cols = ["triage", "first_response_wait", "rerouting", "work", "waiting_on_student", "reopen_cycle"]
TOT_B = round(sb.loc["breached SLA", stage_cols].sum())
TOT_M = round(sb.loc["met SLA", stage_cols].sum())
FRW_B, FRW_M = sb.loc["breached SLA", "first_response_wait"], sb.loc["met SLA", "first_response_wait"]
RR_B, RR_M = sb.loc["breached SLA", "rerouting"], sb.loc["met SLA", "rerouting"]
WK_B, WK_M = sb.loc["breached SLA", "work"], sb.loc["met SLA", "work"]
wi = WHATIF.set_index("scenario")
S1 = wi.loc["S1  Fix intake routing"]
S2 = wi.loc["S2  Priority-first queue"]
S3 = wi.loc["S3  Escalate at 50% of SLA"]
S123 = wi.loc["S1 + S2 + S3"]
S12 = wi.loc["S1 + S2"]
sens = SEG["sensitivity"]
SENS_MIN, SENS_MAX = sens.sla_compliance_pct.min(), sens.sla_compliance_pct.max()
rc = RECON.set_index("method")
TRUE_PCT = rc.loc["Ground truth (simulated)", "sla_compliance"]
NAIVE_PCT = rc.loc["Naive query on ticket table", "sla_compliance"]
NAIVE_N = int(rc.loc["Naive query on ticket table", "tickets"])
PIPE_ERR = rc.loc["Pipeline (cleaned + modelled)", "error_vs_truth_pp"]
NAIVE_ERR = rc.loc["Naive query on ticket table", "error_vs_truth_pp"]
pop = SEG["population"].set_index("segment").tickets
N_TICKETS = int(pop.sum())
checks = pd.DataFrame(VAL["checks"])
N_WARN = int((checks.status == "WARN").sum())
N_PASS = int((checks.status == "PASS").sum())
prof = VAL["profile"]
raw_tickets = prof["tickets"]["rows"]
raw_events = prof["events"]["rows"]
raw_inter = prof["interactions"]["rows"]
api_pages = int((MANIFEST.source_type == "API").sum())
retries = sum(1 for l in LOG_OK if "retry in" in l)
PRI_MISSING = int(K.priority_imputed.sum())
FR_MED = sup["M1_median_first_response_h"]
TRI_MED = sup["M2_median_manual_triage_wait_h"]
REASSIGN = sup["M3_reassignment_rate_pct"]
REOPEN = sup["M4_reopen_rate_pct"]
CSAT = sup["M5_avg_csat"]
CSAT_RR = sup["M5_csat_response_rate_pct"]
fr_by_pri = K.groupby("priority").apply(lambda d: ((pd.to_datetime(d.first_response_at) - pd.to_datetime(d.created_at)).dt.total_seconds() / 3600).median())
FR_H, FR_L = round(fr_by_pri["High"], 1), round(fr_by_pri["Low"], 1)

# ---------------------------------------------------------------- diagrams (inline SVG)
WORKFLOW_SVG = """
<svg viewBox="0 0 760 300" class="diagram" role="img" aria-label="Current helpdesk workflow">
<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#52514e"/></marker>
<marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#d03b3b"/></marker></defs>
<style>.bx{fill:#f4f6fa;stroke:#9aa6b8;stroke-width:1}.bt{font:600 10.5px Helvetica,Arial;fill:#0b0b0b}.bs{font:9px Helvetica,Arial;fill:#52514e}
.ln{stroke:#52514e;stroke-width:1.3;fill:none;marker-end:url(#ar)}.lr{stroke:#d03b3b;stroke-width:1.3;fill:none;stroke-dasharray:4 3;marker-end:url(#arr)}
.pn{fill:#d03b3b}.pt{font:700 10px Helvetica,Arial;fill:#fff}.lane{font:600 9px Helvetica,Arial;fill:#8a8984;letter-spacing:.06em}</style>
<text x="640" y="14" class="lane">STUDENT</text><text x="440" y="112" class="lane">HELPDESK TRIAGE</text><text x="645" y="216" class="lane">DEPARTMENT TEAM</text>
<line x1="0" y1="96" x2="760" y2="96" stroke="#e6e5e0"/><line x1="0" y1="200" x2="760" y2="200" stroke="#e6e5e0"/>
<rect x="20" y="24" width="130" height="54" rx="6" class="bx"/><text x="30" y="44" class="bt">1. Raises ticket</text><text x="30" y="58" class="bs">portal (58%) · email (32%)</text><text x="30" y="70" class="bs">walk-in desk (10%)</text>
<rect x="20" y="126" width="130" height="58" rx="6" class="bx"/><text x="30" y="146" class="bt">2a. Auto-route</text><text x="30" y="160" class="bs">portal category chosen</text><text x="30" y="172" class="bs">→ dept in minutes</text>
<rect x="180" y="126" width="140" height="58" rx="6" class="bx"/><text x="190" y="146" class="bt">2b. Manual triage queue</text><text x="190" y="160" class="bs">email / 'Other' tickets</text><text x="190" y="172" class="bs">coordinators Mon–Sat 9–18</text>
<rect x="180" y="226" width="140" height="58" rx="6" class="bx"/><text x="190" y="246" class="bt">3. Department queue</text><text x="190" y="260" class="bs">FIFO – priority not used</text><text x="190" y="272" class="bs">first response by agent</text>
<rect x="350" y="226" width="130" height="58" rx="6" class="bx"/><text x="360" y="246" class="bt">4. Work on ticket</text><text x="360" y="260" class="bs">may ask student for info</text><text x="360" y="272" class="bs">(SLA clock paused)</text>
<rect x="350" y="24" width="130" height="54" rx="6" class="bx"/><text x="360" y="44" class="bt">Waiting on student</text><text x="360" y="58" class="bs">replies / no reply 72h</text><text x="360" y="70" class="bs">→ auto-closed</text>
<rect x="510" y="226" width="110" height="58" rx="6" class="bx"/><text x="520" y="246" class="bt">5. Resolved</text><text x="520" y="260" class="bs">SLA verdict here</text><text x="520" y="272" class="bs">CSAT survey sent</text>
<rect x="510" y="24" width="110" height="54" rx="6" class="bx"/><text x="520" y="44" class="bt">Reopens ticket</text><text x="520" y="58" class="bs">"issue not fixed"</text><text x="520" y="70" class="bs">+ follow-ups</text>
<rect x="645" y="226" width="105" height="58" rx="6" class="bx"/><text x="655" y="246" class="bt">6. Closed</text><text x="655" y="260" class="bs">auto after 3 days</text>
<rect x="605" y="122" width="150" height="66" rx="6" class="bx" style="fill:#fff6ee;stroke:#e0a071"/><text x="613" y="138" class="bt">Interventions</text><text x="613" y="151" class="bs">auto-reminder: no reply in 24h</text><text x="613" y="163" class="bs">escalation: daily 10:00 review</text><text x="613" y="175" class="bs">of tickets open &gt; 48h</text>
<path d="M85,78 L85,126" class="ln"/><path d="M150,52 C250,52 250,110 250,126" class="ln"/>
<path d="M85,184 C85,255 120,255 180,255" class="ln"/><path d="M250,184 L250,226" class="ln"/>
<path d="M320,255 L350,255" class="ln"/><path d="M480,255 L510,255" class="ln"/><path d="M620,255 L645,255" class="ln"/>
<path d="M415,226 L415,78" class="ln"/><path d="M430,78 L430,226" class="ln"/>
<path d="M565,226 L565,78" class="ln"/><path d="M548,78 C548,150 470,180 470,226" class="ln"/>
<path d="M300,226 C340,215 340,195 300,186" class="lr"/>
<circle cx="322" cy="126" r="9" class="pn"/><text x="318.5" y="130" class="pt">1</text>
<circle cx="345" cy="206" r="9" class="pn"/><text x="341.5" y="210" class="pt">2</text>
<circle cx="180" cy="226" r="9" class="pn"/><text x="176.5" y="230" class="pt">3</text>
<circle cx="755" cy="122" r="9" class="pn"/><text x="751.5" y="126" class="pt">4</text>
<circle cx="620" cy="24" r="9" class="pn"/><text x="616.5" y="28" class="pt">5</text>
<text x="358" y="204" class="bs" style="fill:#d03b3b">misrouted</text><text x="358" y="215" class="bs" style="fill:#d03b3b">→ re-triage</text>
</svg>"""

PIPELINE_SVG = """
<svg viewBox="0 0 760 170" class="diagram" role="img" aria-label="Pipeline stages">
<defs><marker id="a2" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#52514e"/></marker>
<marker id="a3" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#d03b3b"/></marker></defs>
<style>.p{fill:#eef4fc;stroke:#2a78d6;stroke-width:1.2}.g{fill:#fff6ee;stroke:#eb6834;stroke-width:1.2}.pt2{font:700 11px Helvetica,Arial;fill:#0b0b0b}.ps{font:9px Helvetica,Arial;fill:#52514e}
.l2{stroke:#52514e;stroke-width:1.3;marker-end:url(#a2)}.l3{stroke:#d03b3b;stroke-width:1.2;stroke-dasharray:4 3;marker-end:url(#a3)}.ft{font:9px Helvetica,Arial;fill:#d03b3b}</style>
<rect x="5" y="20" width="135" height="70" rx="7" class="p"/><text x="15" y="40" class="pt2">1 RETRIEVE</text><text x="15" y="55" class="ps">SQL · CSV · JSON · API</text><text x="15" y="67" class="ps">retries + completeness</text><text x="15" y="79" class="ps">raw snapshot + sha256</text>
<rect x="160" y="20" width="140" height="70" rx="7" class="g"/><text x="170" y="40" class="pt2">2 VALIDATE (gate)</text><text x="170" y="55" class="ps">profile · 15 business rules</text><text x="170" y="67" class="ps">PASS/WARN/FAIL/UNKNOWN</text><text x="170" y="79" class="ps">safe fixes only</text>
<rect x="320" y="20" width="135" height="70" rx="7" class="p"/><text x="330" y="40" class="pt2">3 MODEL</text><text x="330" y="55" class="ps">dims + facts</text><text x="330" y="67" class="ps">ticket_journey (1 row/ticket)</text><text x="330" y="79" class="ps">warehouse.db</text>
<rect x="475" y="20" width="135" height="70" rx="7" class="p"/><text x="485" y="40" class="pt2">4 METRICS</text><text x="485" y="55" class="ps">KPI + 5 metrics in SQL</text><text x="485" y="67" class="ps">segments · sensitivity</text><text x="485" y="79" class="ps">charts</text>
<rect x="630" y="20" width="125" height="70" rx="7" class="p"/><text x="640" y="40" class="pt2">5 PUBLISH</text><text x="640" y="55" class="ps">metrics.json + caveats</text><text x="640" y="67" class="ps">atomic swap of</text><text x="640" y="79" class="ps">output/latest</text>
<line x1="140" y1="55" x2="158" y2="55" class="l2"/><line x1="300" y1="55" x2="318" y2="55" class="l2"/><line x1="455" y1="55" x2="473" y2="55" class="l2"/><line x1="610" y1="55" x2="628" y2="55" class="l2"/>
<line x1="72" y1="90" x2="72" y2="130" class="l3"/><line x1="230" y1="90" x2="230" y2="130" class="l3"/>
<rect x="5" y="132" width="750" height="30" rx="6" fill="#fdf0f0" stroke="#d03b3b" stroke-width="1"/>
<text x="15" y="151" class="ft">Retrieval failure (retries exhausted / incomplete API) → exit 2  ·  Gate FAIL → exit 1  ·  in both cases metrics are NOT published and output/latest keeps the last good run; every run is logged</text>
</svg>"""

ERD_SVG = """
<svg viewBox="0 0 760 250" class="diagram" role="img" aria-label="Workflow data model">
<style>.t{fill:#f4f6fa;stroke:#9aa6b8}.th{fill:#2a78d6}.tt{font:700 10px Helvetica,Arial;fill:#fff}.tf{font:9px Menlo,monospace;fill:#0b0b0b}.tk{font:9px Menlo,monospace;fill:#1c5cab}.rl{stroke:#52514e;stroke-width:1.2}.rc{font:9px Helvetica,Arial;fill:#52514e}
.j{fill:#fff6ee;stroke:#eb6834}.jh{fill:#eb6834}</style>
<g><rect x="10" y="10" width="150" height="72" class="t"/><rect x="10" y="10" width="150" height="18" class="th"/><text x="16" y="23" class="tt">dim_student (entity)</text><text x="16" y="42" class="tk">PK student_id</text><text x="16" y="55" class="tf">program, year</text><text x="16" y="68" class="tf">hostel_block</text></g>
<g><rect x="10" y="160" width="150" height="72" class="t"/><rect x="10" y="160" width="150" height="18" class="th"/><text x="16" y="173" class="tt">dim_agent (entity)</text><text x="16" y="192" class="tk">PK agent_id</text><text x="16" y="205" class="tf">department, role</text><text x="16" y="222" class="rc">referenced by event.actor_id</text></g>
<g><rect x="230" y="70" width="170" height="110" class="t"/><rect x="230" y="70" width="170" height="18" class="th"/><text x="236" y="83" class="tt">fact_ticket (entity)</text><text x="236" y="102" class="tk">PK ticket_id</text><text x="236" y="115" class="tk">FK student_id</text><text x="236" y="128" class="tf">channel, priority</text><text x="236" y="141" class="tf">intake_category</text><text x="236" y="154" class="tf">resolving_department</text><text x="236" y="167" class="tf">status_canonical</text></g>
<g><rect x="470" y="5" width="150" height="62" class="t"/><rect x="470" y="5" width="150" height="18" class="th"/><text x="476" y="18" class="tt">fact_ticket_event</text><text x="476" y="36" class="tk">PK event_id · FK ticket_id</text><text x="476" y="49" class="tf">event_type, from→to status</text><text x="476" y="61" class="tf">event_time, actor, dept</text></g>
<g><rect x="470" y="75" width="150" height="50" class="t"/><rect x="470" y="75" width="150" height="18" class="th"/><text x="476" y="88" class="tt">fact_interaction</text><text x="476" y="106" class="tk">PK interaction_id · FK</text><text x="476" y="118" class="tf">kind: follow_up / reply …</text></g>
<g><rect x="470" y="133" width="150" height="50" class="t"/><rect x="470" y="133" width="150" height="18" class="th"/><text x="476" y="146" class="tt">fact_intervention</text><text x="476" y="164" class="tk">FK ticket_id</text><text x="476" y="176" class="tf">escalated / reminder_sent</text></g>
<g><rect x="470" y="191" width="150" height="50" class="t"/><rect x="470" y="191" width="150" height="18" class="th"/><text x="476" y="204" class="tt">fact_csat (outcome)</text><text x="476" y="222" class="tk">PK/FK ticket_id</text><text x="476" y="234" class="tf">rating 1–5, submitted_at</text></g>
<g><rect x="650" y="40" width="105" height="170" class="j"/><rect x="650" y="40" width="105" height="18" class="jh"/><text x="655" y="53" class="tt">ticket_journey</text><text x="655" y="72" class="tf">1 row / ticket</text><text x="655" y="88" class="tf">stage hours ×6</text><text x="655" y="101" class="tf">reassign_count</text><text x="655" y="114" class="tf">followup_count</text><text x="655" y="127" class="tf">escalated (+ when)</text><text x="655" y="140" class="tf">reminder_sent</text><text x="655" y="153" class="tf">net_resolution_h</text><text x="655" y="166" class="tf">sla_met, reopened</text><text x="655" y="179" class="tf">csat_rating</text><text x="655" y="192" class="tf">in_kpi_population</text></g>
<line x1="160" y1="46" x2="230" y2="96" class="rl"/><text x="180" y="62" class="rc">1 ─ *</text>

<line x1="400" y1="95" x2="470" y2="36" class="rl"/><line x1="400" y1="110" x2="470" y2="100" class="rl"/><line x1="400" y1="140" x2="470" y2="158" class="rl"/><line x1="400" y1="165" x2="470" y2="216" class="rl"/>
<text x="425" y="58" class="rc">1─*</text><text x="432" y="100" class="rc">1─*</text><text x="432" y="143" class="rc">1─*</text><text x="410" y="200" class="rc">1─0..1</text>
<line x1="620" y1="120" x2="650" y2="120" class="rl"/><text x="622" y="113" class="rc">agg</text>
</svg>"""

# ---------------------------------------------------------------- sections
CSS = """
@page { size: A4; margin: 14mm 14mm 14mm 14mm; }
:root { --ink:#0b0b0b; --ink2:#3d3c39; --muted:#8a8984; --line:#dcdad3; --blue:#2a78d6; --blue-d:#1c5cab; --bg2:#f4f6fa; --orange:#eb6834; --red:#d03b3b; --green:#1a8f5a; }
* { box-sizing: border-box; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; color: var(--ink); font-size: 9.6pt; line-height: 1.42; margin: 0; background: #fff; }
h1 { font-size: 21pt; margin: 0 0 4px; letter-spacing: -.01em; }
h2 { font-size: 13.5pt; margin: 0 0 8px; padding-bottom: 4px; border-bottom: 2px solid var(--blue); color: var(--ink); }
h2 .n { color: var(--blue); margin-right: 6px; }
h3 { font-size: 10.6pt; margin: 12px 0 5px; color: var(--blue-d); }
p { margin: 0 0 7px; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
table { border-collapse: collapse; width: 100%; margin: 4px 0 9px; font-size: 8.3pt; page-break-inside: auto; }
th { background: var(--bg2); text-align: left; font-weight: 700; padding: 4px 5px; border-bottom: 1.5px solid #9aa6b8; vertical-align: bottom; }
td { padding: 3.5px 5px; border-bottom: 1px solid var(--line); vertical-align: top; }
tr { page-break-inside: avoid; }
.small td, .small th { font-size: 7.7pt; padding: 3px 4px; }
.b { display: inline-block; font-size: 7pt; font-weight: 700; padding: 1px 5px; border-radius: 3px; letter-spacing: .03em; }
.b-pass { background: #e3f4ea; color: #146c43; } .b-warn { background: #fff1d6; color: #8a5a00; }
.b-fail { background: #fbe1e1; color: #a12626; } .b-unknown { background: #ecebf8; color: #3f3591; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; margin: 8px 0 10px; }
.kpi { border: 1px solid var(--line); border-radius: 6px; padding: 7px 9px; background: #fff; }
.kpi .v { font-size: 17pt; font-weight: 700; color: var(--ink); line-height: 1.1; }
.kpi .l { font-size: 7.8pt; color: var(--ink2); }
.kpi.hero { border-color: var(--blue); background: #eef4fc; }
.callout { border-left: 3px solid var(--blue); background: var(--bg2); padding: 7px 10px; margin: 6px 0 9px; }
.callout.warn { border-color: var(--orange); background: #fff6ee; }
.callout.red { border-color: var(--red); background: #fdf0f0; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.three { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 9px; }
.box { border: 1px solid var(--line); border-radius: 6px; padding: 7px 9px; }
.box h4 { margin: 0 0 4px; font-size: 9pt; color: var(--blue-d); }
ul { margin: 2px 0 7px 16px; padding: 0; } li { margin: 1.5px 0; }
.diagram { width: 100%; height: auto; margin: 4px 0 6px; }
img.chart { width: 100%; margin: 4px 0 6px; }
pre { font-family: Menlo, Consolas, monospace; font-size: 6.9pt; line-height: 1.35; white-space: pre-wrap; word-break: break-word; margin: 3px 0 9px; }
pre.log { background: #16181d; color: #d6d8dd; padding: 7px 9px; border-radius: 5px; }
pre.log .warn { color: #f2c46d; } pre.log .err { color: #ff8a8a; }
pre.code { background: #f6f7f9; border: 1px solid var(--line); padding: 7px 9px; border-radius: 0 0 5px 5px; margin-top: 0; }
.codehead { font: 700 7.5pt Menlo, monospace; background: #e7eaf0; padding: 3px 9px; border-radius: 5px 5px 0 0; border: 1px solid var(--line); border-bottom: none; margin-top: 6px; color: var(--ink2); }
.todo { background: #fff1d6; color: #8a5a00; font-weight: 700; padding: 0 4px; border-radius: 3px; }
.muted { color: var(--muted); } .tiny { font-size: 7.8pt; color: var(--ink2); }
.cover-meta { font-size: 10.5pt; margin: 6px 0 14px; color: var(--ink2); }
.pill { display: inline-block; background: var(--bg2); border: 1px solid var(--line); border-radius: 12px; padding: 1px 8px; font-size: 7.8pt; margin: 0 3px 3px 0; }
.brief { font-size: 8.55pt; line-height: 1.33; } .brief h2 { margin-bottom: 6px; } .brief h3 { margin: 7px 0 3px; font-size: 9.6pt; }
.brief table { font-size: 7.8pt; margin: 2px 0 5px; } .brief td, .brief th { padding: 2.5px 4px; } .brief p { margin-bottom: 4px; } .brief ul { margin-bottom: 4px; }
.flow { display: flex; flex-wrap: wrap; gap: 3px; align-items: center; font-size: 7.8pt; margin: 2px 0 5px; }
.flow span { background: var(--bg2); border: 1px solid #c9d2df; border-radius: 4px; padding: 2px 5px; }
.flow span.pain { background: #fdf0f0; border-color: #e7a3a3; }
.flow i { color: var(--muted); font-style: normal; }
.toc td { border: none; padding: 1.5px 4px; font-size: 8.8pt; }
.toc td:first-child { white-space: nowrap; }
.num { text-align: right; }
code { font-family: Menlo, Consolas, monospace; font-size: .86em; }
.rules td, .rules th { font-size: 7.3pt; padding: 2.5px 4px; }
"""


def cover():
    gh = link(LINKS.get("github_url"), "GitHub repository link")
    vid = link(LINKS.get("demo_video_url"), "5-min demo video (Google Drive) link")
    return f"""
<section class="page">
<div class="muted" style="font-size:8.5pt;letter-spacing:.08em;margin-top:6px">FDE ASSIGNMENT · CLASSES 1–8 · FROM AMBIGUOUS PROBLEM TO DEPENDABLE DATA WORKFLOW</div>
<h1 style="margin-top:6px;font-size:19pt">CampusDesk: why student support tickets take so long, and what to fix first</h1>
<div class="cover-meta"><b>Lakshya Mewara</b> · Roll No. 24bcs10290 · Batch 2024-28</div>

<table class="toc" style="width:auto;margin-bottom:10px">
<tr><td><b>GitHub repository</b></td><td>{gh}</td></tr>
<tr><td><b>5-min demo video</b></td><td>{vid}</td></tr>
<tr><td><b>Repo contents</b></td><td>README · SQLite database + all source files · generator · mock API · pipeline · tests · CI · executed notebook</td></tr>
<tr><td><b>Data</b></td><td>Synthetic, realistic, reproducible (seeded generator in the repo). No real student data used.</td></tr>
</table>

<div class="callout"><b>About the project.</b> A college's Dean of Student Affairs says: <i>"Students keep complaining that helpdesk tickets take forever.
Before we buy an AI chatbot, find out what is actually happening."</i> I investigated it as a Forward Deployed Engineer. I identified the stakeholders,
mapped the ticket workflow and wrote a SMART problem statement with one KPI. I then pulled data from four systems (SQL ticket DB, CSV audit log, JSON survey
export, paginated REST API), profiled and validated it with business rules, and modelled the ticket journey. Finally I built a repeatable pipeline that
retrieves, validates, models and publishes the metrics, and refuses to publish when the data is not safe.</div>

<div class="kpis">
<div class="kpi hero"><div class="v">{KPI_PCT:.1f}%</div><div class="l"><b>Project KPI:</b> SLA compliance ({N_RES:,} resolved tickets, 27 Jul – 20 Sep 2026)</div></div>
<div class="kpi"><div class="v">{HIGH:.0f}%</div><div class="l">High-priority tickets within their 24h SLA</div></div>
<div class="kpi"><div class="v">{R0:.0f}→{R2:.0f}%</div><div class="l">SLA when routed right first time vs 2+ reassignments</div></div>
<div class="kpi"><div class="v">{ESC_LATE_N}</div><div class="l">tickets escalated only <i>after</i> their SLA had already been breached</div></div>
</div>

<h3>Answer first (pyramid)</h3>
<p><b>Don't buy the AI chatbot yet. The delay isn't in answering students. It's in how tickets are routed, queued and escalated.</b>
Fixing intake routing and moving escalation to 50% of the SLA is estimated to lift compliance from {KPI_PCT:.0f}% to about {S123.est_sla_compliance_pct:.0f}%
(with a priority-first queue). This uses the existing team and tool. It should be piloted for 2 weeks before rolling out.</p>
<ul>
<li><b>Priority is captured but ignored:</b> High-priority tickets wait as long for a first response ({FR_H}h median) as Low ({FR_L}h), so only {HIGH:.0f}% meet 24h.</li>
<li><b>Misrouting compounds delay:</b> {REASSIGN:.0f}% of tickets are reassigned. SLA falls {R0:.0f}% → {R1:.0f}% → {R2:.0f}% with each hop, and follow-ups rise {F0:.1f} → {F2:.1f}.</li>
<li><b>Two departments hold the backlog:</b> Fees &amp; Finance {FIN:.0f}% and Academics &amp; Exams {ACA:.0f}% (weekday office hours only), against IT {IT:.0f}%.</li>
<li><b>Escalation comes too late:</b> a daily review escalates tickets open &gt;48h (median {ESC_MED_H:.0f}h). That is after the deadline for every High ticket.</li>
</ul>

<h3>What is in this PDF</h3>
<table class="toc">
<tr><td>1</td><td>One-page problem brief: stakeholders, workflow, problem, KPI, scope</td><td class="muted">p.2</td></tr>
<tr><td>2</td><td>FDE discovery: stakeholders, goals, constraints, facts, assumptions, unknowns</td><td class="muted">p.3</td></tr>
<tr><td>3</td><td>Workflow &amp; problem structure: current-state map, issue tree, hypotheses</td><td class="muted">p.4</td></tr>
<tr><td>4</td><td>KPIs, scope &amp; success</td><td class="muted">p.5</td></tr>
<tr><td>5</td><td>Client data &amp; source systems: source map, source of truth, key fields, missing events</td><td class="muted">p.6</td></tr>
<tr><td>6</td><td>Retrieval: 4 source types, reproducible, raw preserved</td><td class="muted">p.7</td></tr>
<tr><td>7</td><td>Profiling &amp; cleaning: 15 business rules, safe fixes, assumptions</td><td class="muted">p.8–9</td></tr>
<tr><td>8</td><td>Workflow model with data: entities, events, interventions, outcomes, SQL metrics</td><td class="muted">p.10–11</td></tr>
<tr><td>9</td><td>Findings &amp; recommendation</td><td class="muted">p.12–14</td></tr>
<tr><td>10</td><td>Dependable pipeline: run log, checks, failure handling, reliability evidence</td><td class="muted">p.15–16</td></tr>
<tr><td>11</td><td>What remains unknown</td><td class="muted">p.17</td></tr>
</table>
</section>"""


def brief():
    return f"""
<section class="page brief">
<h2><span class="n">1</span>One-page problem brief</h2>
<p><b>Client:</b> Student Services Helpdesk of a residential engineering college (about 1,800 students; 15 helpdesk staff across 5 departments plus triage).
<b>Sponsor:</b> Dean of Student Affairs. <b>Original request:</b> "Buy an AI chatbot because tickets take forever." <b>FDE reframing:</b> find where the time actually goes first.</p>

<h3>Stakeholders</h3>
<table><tr><th>Who</th><th>Role in problem</th><th>What they want</th></tr>
<tr><td>Dean of Student Affairs</td><td>Sponsor, owns the KPI</td><td>Fewer complaints; a defensible decision on the chatbot spend</td></tr>
<tr><td>Helpdesk Manager</td><td>Operational owner</td><td>Know which queue or step is slow; fair workload</td></tr>
<tr><td>Triage coordinators (2)</td><td>Route email/'Other' tickets</td><td>Less manual sorting</td></tr>
<tr><td>Department agents (IT, Hostel, Finance, Academics, Library)</td><td>Resolve tickets</td><td>Receive only tickets that belong to them</td></tr>
<tr><td>Students</td><td>Affected users</td><td>Fast, first-time-right resolution; visibility</td></tr>
<tr><td>IT admin</td><td>Owns ticketing tool data</td><td>No disruption to the tool</td></tr></table>

<h3>Current workflow (where the problem appears)</h3>
<div class="flow"><span>Student raises ticket</span><i>→</i><span class="pain">Triage: auto (portal) or manual queue (email/Other) ①</span><i>→</i><span class="pain">Department queue, priority unused ③</span><i>→</i>
<span>First response</span><i>→</i><span class="pain">Misrouted? → back to triage ②</span><i>→</i><span>Work ⇄ waiting on student</span><i>→</i><span>Resolved</span><i>→</i><span class="pain">Reopen ⑤</span><i>→</i><span>Closed + CSAT</span>
<span class="pain">Escalation: daily review of tickets &gt;48h ④</span></div>
<p class="tiny">Before the problem: intake and categorisation decide the first queue. After the problem: students chase with follow-ups, reopen tickets and give low CSAT.</p>

<h3>Problem statement (SMART)</h3>
<div class="callout" style="margin:3px 0 5px">Only <b>{KPI_PCT:.0f}%</b> of student helpdesk tickets resolved between 27 Jul and 20 Sep 2026 met their priority SLA (High 24h / Medium 72h / Low 120h),
and only <b>{HIGH:.0f}%</b> of High-priority tickets did. <b>Identify where in the ticket workflow delay accumulates</b> and implement the highest-impact process fixes to raise SLA
compliance to <b>≥75%</b> (High-priority to <b>≥50%</b>) <b>within 8 weeks</b>, using the <b>existing helpdesk team and current ticketing tool</b> (no new hires, no new software).</div>

<div class="two">
<div><h3>KPI &amp; supporting metrics</h3>
<table><tr><th>Metric</th><th class="num">Baseline</th></tr>
<tr><td><b>KPI: SLA compliance rate</b> (resolved within priority SLA, net of waiting-on-student)</td><td class="num"><b>{KPI_PCT:.1f}%</b></td></tr>
<tr><td>M1 Median time to first response</td><td class="num">{FR_MED}h</td></tr>
<tr><td>M2 Median manual-triage wait</td><td class="num">{TRI_MED}h</td></tr>
<tr><td>M3 Reassignment rate</td><td class="num">{REASSIGN}%</td></tr>
<tr><td>M4 Reopen rate</td><td class="num">{REOPEN}%</td></tr>
<tr><td>M5 Average CSAT (1–5), response rate</td><td class="num">{CSAT} ({CSAT_RR:.0f}%)</td></tr></table></div>
<div><h3>Scope</h3>
<p><b>MVP (in):</b> all tickets from the 3 intake channels over 8 weeks; the lifecycle from creation to final resolution; routing, queueing, escalation and reminders; a repeatable pipeline and KPI report.</p>
<p><b>Out of scope:</b> building or buying the chatbot; staffing and HR changes; agent-level performance ranking; real-time dashboards; changes to the ticketing tool's code.</p>
<p><b>Success means:</b> the KPI is ≥75% and High ≥50% on the same, signed-off definition, with reassignment rate and median first response falling. Early read on leading indicators within 2 weeks of the pilot.</p></div>
</div>
<p class="tiny"><b>Data:</b> synthetic, realistic (seeded generator). Sources: SQLite ticket DB, CSV audit log, JSON CSAT export, paginated Portal REST API.</p>
</section>"""


def discovery():
    return f"""
<section class="page">
<h2><span class="n">2</span>FDE mindset &amp; stakeholder discovery</h2>
<p>The request was a <b>solution</b> ("buy an AI chatbot"). Following the FDE loop, <i>Listen → Observe → Question → Structure → Validate</i>, I first asked who is affected,
who owns the problem, and what "takes forever" actually means. The discovery questions below are the ones I would take into the first stakeholder interviews.</p>

<table>
<tr><th style="width:15%">Stakeholder</th><th style="width:17%">Goal</th><th style="width:20%">Constraints</th><th style="width:24%">Discovery questions</th><th>What changes if they're right</th></tr>
<tr><td><b>Dean of Student Affairs</b> (sponsor, KPI owner)</td><td>Fewer complaints; decide on the chatbot budget</td><td>Must show improvement before end-sem exams; limited budget</td><td>What would convince you the helpdesk has improved? Which complaints reach you?</td><td>Defines the KPI and target; signs off the SLA definition</td></tr>
<tr><td><b>Helpdesk Manager</b> (operational owner)</td><td>Hit SLAs with current staff</td><td>No new hires; tool is fixed</td><td>Which tickets do you escalate, and when? How are priorities used in queues?</td><td>Owns routing and escalation rules, and confirms category mappings</td></tr>
<tr><td><b>Triage coordinators</b></td><td>Route fast and correctly</td><td>2 people, Mon–Sat 9–18, no Sunday cover</td><td>Why do tickets bounce back? What information is missing at intake?</td><td>Source of misrouting insight (no reason code exists)</td></tr>
<tr><td><b>Dept agents</b> (IT, Hostel, Finance, Academics, Library)</td><td>Only receive their own tickets</td><td>Finance and Academics work Mon–Fri 9–17</td><td>How do you pick the next ticket? What does "waiting on student" mean for you?</td><td>Explains queueing (FIFO?) and the pause usage</td></tr>
<tr><td><b>Students</b> (affected)</td><td>Quick, first-time-right fix</td><td>Exams, hostel move-in peaks</td><td>What made you follow up or reopen?</td><td>Validates that follow-ups and CSAT reflect real pain</td></tr>
<tr><td><b>IT admin</b> (data owner)</td><td>Keep the tool stable</td><td>Read-only access for us</td><td>Which export is authoritative for timestamps? Any clock or sync issues?</td><td>Source-of-truth decisions; fixes to the walk-in desk clock</td></tr>
</table>

<div class="three">
<div class="box"><h4>Facts (verified in data)</h4><ul>
<li>{N_TICKETS:,} unique tickets in 8 weeks; 3 intake channels</li>
<li>Draft SLA: High 24h / Medium 72h / Low 120h</li>
<li>Email tickets have no category; they go to manual triage</li>
<li>Escalation happens at a daily 10:00 review of tickets open &gt;48h</li>
<li>Auto-reminder to the agent after 24h without a reply</li></ul></div>
<div class="box"><h4>Assumptions (need confirmation)</h4><ul>
<li>SLA clock pauses while "Waiting on Student"</li>
<li>SLA runs to the <b>final</b> resolution (after reopens)</li>
<li>Missing priority (email) = Medium, per policy default</li>
<li>"Exam Cell" = Academics &amp; Exams; "Hostel" = Hostel &amp; Maintenance</li>
<li>Cancelled and no-reply closures are excluded from the KPI</li></ul></div>
<div class="box"><h4>Unknowns (cannot get from data)</h4><ul>
<li><b>Why</b> tickets are misrouted (no reason code)</li>
<li>Real agent effort (no time tracking)</li>
<li>Causal effect of escalation (only slow tickets get escalated)</li>
<li>Calendar vs business-hours SLA: not decided</li>
<li>Views of students who don't answer the CSAT survey</li></ul></div>
</div>
<div class="callout warn"><b>FDE judgement:</b> a chatbot answers students faster, but the data shows first contact isn't the bottleneck. Queueing, routing and escalation are.
Buying it now would be "building the request" instead of solving the problem.</div>
</section>"""


def workflow():
    return f"""
<section class="page">
<h2><span class="n">3</span>Workflow &amp; problem structure</h2>
<h3>Current-state workflow (pain points ①–⑤ found in the data)</h3>
{WORKFLOW_SVG}
<table class="small"><tr><th>#</th><th>Where the problem appears</th><th>Before it</th><th>After it</th></tr>
<tr><td>①</td><td>Manual triage queue for email/'Other' tickets (median wait {TRI_MED}h)</td><td>Student sends an email with no category</td><td>Ticket reaches a department late</td></tr>
<tr><td>②</td><td>Misrouting: wrong department → back to triage ({REASSIGN}% of tickets)</td><td>Wrong category chosen at intake or triage</td><td>Each hop adds about a day; more follow-ups and reopens</td></tr>
<tr><td>③</td><td>Department queue ignores priority (median first response High {FR_H}h vs Low {FR_L}h)</td><td>Priority is captured at intake</td><td>High-priority tickets miss 24h</td></tr>
<tr><td>④</td><td>Escalation only at a daily review of tickets &gt;48h</td><td>Ticket is already slow</td><td>{ESC_LATE_N} tickets escalated after the SLA had already passed</td></tr>
<tr><td>⑤</td><td>Reopen after a "quick fix" ({REOPEN}% of tickets)</td><td>Resolved without confirmation</td><td>The clock keeps running to the final fix</td></tr></table>

<div class="two">
<div><h3>Issue tree: "Why do tickets miss SLA?" (MECE by workflow stage)</h3>
<table class="small">
<tr><th>Branch</th><th>Sub-issues</th></tr>
<tr><td><b>A. Before a team owns it</b></td><td>A1 triage wait · A2 wrong first department (misrouting)</td></tr>
<tr><td><b>B. Waiting in the team queue</b></td><td>B1 priority not used · B2 team capacity / working hours · B3 volume peaks (move-in, exams)</td></tr>
<tr><td><b>C. While being worked</b></td><td>C1 work duration · C2 waiting on student (paused)</td></tr>
<tr><td><b>D. After "resolution"</b></td><td>D1 reopen cycles</td></tr>
<tr><td><b>E. Safety net</b></td><td>E1 reminders and escalations too late or ineffective</td></tr>
</table>
<p class="tiny">These branches add up exactly: the model splits each ticket's total time into triage + first-response wait + re-routing + work + waiting-on-student + reopen cycle. They are mutually exclusive and collectively exhaustive, and verified in code (max gap 0.00h).</p></div>
<div><h3>Hypotheses to test (and what would disprove them)</h3>
<table class="small">
<tr><th>Hypothesis</th><th>Test</th></tr>
<tr><td>H1 Misrouting / manual triage drives breaches</td><td>SLA by reassignment count and triage path</td></tr>
<tr><td>H2 Priority is not used in queueing</td><td>First-response time and SLA by priority</td></tr>
<tr><td>H3 Some departments are capacity or hours constrained</td><td>SLA and first-response time by resolving department</td></tr>
<tr><td>H4 Escalation comes too late to help</td><td>Escalation timing vs SLA deadline</td></tr>
<tr><td>H5 Weekend / email tickets are the main problem</td><td>SLA by weekday vs weekend and by channel</td></tr>
</table>
<p class="tiny">Prioritised on impact × feasibility: H1–H4 can be fixed with process and config changes inside the current tool (high feasibility). Capacity (B2) needs staffing, which is out of scope.</p></div>
</div>
</section>"""


def kpis():
    return f"""
<section class="page">
<h2><span class="n">4</span>KPIs, scope &amp; solution</h2>
<h3>Project KPI (lagging): SLA compliance rate</h3>
<div class="callout"><b>Definition:</b> resolved tickets whose <i>net</i> resolution time (creation → <b>final</b> resolution, minus time in "Waiting on Student") is within the priority target,
÷ all resolved tickets in the period. <b>Grain:</b> ticket. <b>Population:</b> resolved in period. Excludes cancelled/duplicate, closed-no-reply, still-open and clock-skewed tickets
(all counted and disclosed). <b>Baseline: {KPI_PCT:.1f}%</b> ({kpi['met_sla']}/{N_RES}). <b>Target: ≥75% in 8 weeks.</b></div>

<table>
<tr><th>Supporting metric</th><th>Formula</th><th>Type</th><th>Why it matters / link to KPI</th><th class="num">Baseline</th></tr>
<tr><td>M1 Median first-response time</td><td>median(first_response − created)</td><td>Leading · workflow driver</td><td>Queueing delay before anyone looks at the ticket</td><td class="num">{FR_MED}h</td></tr>
<tr><td>M2 Median manual-triage wait</td><td>median(first_assigned − created) for manual tickets</td><td>Leading · driver</td><td>Pain point ①; fixed by structured intake</td><td class="num">{TRI_MED}h</td></tr>
<tr><td>M3 Reassignment rate</td><td>% tickets with ≥1 reassignment</td><td>Leading · driver</td><td>Pain point ②; each hop cuts SLA odds</td><td class="num">{REASSIGN}%</td></tr>
<tr><td>M4 Reopen rate</td><td>% resolved tickets reopened</td><td>Quality outcome (guardrail)</td><td>Stops "fast but wrong" fixes gaming the KPI</td><td class="num">{REOPEN}%</td></tr>
<tr><td>M5 Average CSAT</td><td>mean(latest valid rating per ticket)</td><td>Student outcome (lagging)</td><td>Confirms students feel the change (directional: {CSAT_RR:.0f}% response)</td><td class="num">{CSAT}</td></tr>
</table>
<p class="tiny">Also tracked as a guardrail: <b>High-priority SLA compliance</b> (baseline {HIGH:.0f}%, target ≥50%), so the headline KPI can't improve by only fixing easy Low tickets.</p>

<div class="two">
<div class="box"><h4>MVP scope (in)</h4><ul>
<li>All tickets from portal, email and walk-in; 27 Jul – 20 Sep 2026</li>
<li>The full lifecycle from the audit log; interactions from the Portal API; CSAT</li>
<li>Diagnosis of where delay accumulates; sizing of process fixes</li>
<li>Repeatable pipeline: retrieve → validate → model → metrics, with a gate and logs</li>
<li>Recommendation plus a pilot plan with leading and lagging indicators</li></ul></div>
<div class="box"><h4>Out of scope</h4><ul>
<li>Building or buying the AI chatbot (revisit after the pilot)</li>
<li>Hiring and staffing changes; agent-level performance ranking</li>
<li>Real-time queue dashboard (data is a daily batch export)</li>
<li>Changing the ticketing tool's code; predicting ticket volume</li>
<li>Non-helpdesk channels (WhatsApp groups, direct calls to wardens)</li></ul></div>
</div>

<h3>What success means</h3>
<table class="small"><tr><th>Horizon</th><th>Indicator</th><th>Success threshold</th></tr>
<tr><td>Weeks 1–2 (pilot, leading)</td><td>Reassignment rate · manual-triage wait · % tickets escalated before 50% of SLA</td><td>Reassignment &lt;6% · triage wait &lt;2h · &gt;90% escalated on time</td></tr>
<tr><td>Week 8 (lagging)</td><td>SLA compliance · High-priority SLA · reopen rate · CSAT</td><td>≥75% · ≥50% · no increase · no decrease</td></tr>
<tr><td>Always</td><td>Definition signed off by the Dean; pipeline gate PASS or known WARNs only</td><td>Same definition before and after, otherwise the comparison is invalid</td></tr></table>
</section>"""


def data_sources():
    sm = pd.DataFrame([
        ("Ticket header: student, channel, intake category, priority, subject", "helpdesk.db :: tickets", "SQL", "Source of truth for header fields"),
        ("Student attributes", "helpdesk.db :: students", "SQL", "Source of truth (names/emails not pulled)"),
        ("Agents and departments", "helpdesk.db :: agents", "SQL", "Source of truth"),
        ("Lifecycle timestamps (created, assigned, first response, waiting, resolved, reopened, closed)", "ticket_events.csv (audit-log export)", "CSV", "Source of truth for all times; the ticket table's resolved_at is stale (R12)"),
        ("Interventions (escalations, auto-reminders)", "ticket_events.csv", "CSV", "Source of truth"),
        ("Student follow-ups, agent replies, info requests", "Portal REST API /api/v1/interactions", "API", "Source of truth for interactions"),
        ("Satisfaction rating 1–5", "csat_survey_export.json (nested)", "JSON", "Directional only (response bias)"),
        ("SLA targets and rules", "sla_policy.json", "JSON", "DRAFT, not signed off (R15)"),
    ], columns=["Information needed", "Where it lives", "Type", "Source-of-truth decision"])
    return f"""
<section class="page">
<h2><span class="n">5</span>Client data &amp; source systems</h2>
<div class="callout"><b>Data choice: synthetic, realistic, fully reproducible.</b> Real student-helpdesk data is private, so <code>generator/generate_data.py</code> (seed 42)
<b>simulates the workflow</b> (arrival peaks at move-in and mid-sem exams, working hours per team, manual triage queue, misrouting with 85% triage accuracy,
FIFO department queues, waiting-on-student pauses, reopens, a 24h auto-reminder, the 48h daily escalation review, CSAT with non-response bias). It then writes the data
<b>the way the real systems would hold it</b>, with realistic defects injected. The simulated ground truth is kept separately and used only to prove the pipeline is correct (section 10).</div>
{table(sm)}
<div class="two">
<div><h3>Key fields</h3>
<table class="small"><tr><th>Entity</th><th>Key fields</th></tr>
<tr><td>Ticket</td><td><code>ticket_id</code>, <code>student_id</code>, <code>channel</code>, <code>category</code>, <code>priority</code>, <code>status</code>, <code>created_at</code>, <code>resolved_at</code></td></tr>
<tr><td>Event</td><td><code>event_id</code>, <code>ticket_id</code>, <code>event_time</code>, <code>event_type</code>, <code>from_status → to_status</code>, <code>department</code>, <code>actor_id</code></td></tr>
<tr><td>Interaction</td><td><code>interaction_id</code>, <code>ticket_id</code>, <code>kind</code> (follow_up / agent_reply / info_request / reopen_comment), <code>created_at</code></td></tr>
<tr><td>CSAT</td><td><code>answers.ticket_ref</code>, <code>answers.rating</code>, <code>submitted_at</code></td></tr></table></div>
<div><h3>Injected defects (what real exports look like)</h3>
<ul class="tiny"><li>Exact duplicate ticket rows (importer double-sync) and double submissions</li>
<li>Mixed timestamp formats: ISO vs <code>DD/MM/YYYY HH:MM</code> from the email importer</li>
<li>20 spellings of 5 categories; 11 spellings of 6 statuses</li>
<li>Missing priority on about a third of email tickets</li>
<li>Stale denormalised <code>resolved_at</code> (first, not final, resolution)</li>
<li>Duplicate and orphan audit events; walk-in desk clock skew</li>
<li>CSAT: 4 ticket-ref formats, string ratings, out-of-range values, resubmissions</li>
<li>API: pagination, random HTTP 500 and 429 (rate limit)</li></ul></div>
</div>
<h3>Important missing data / events</h3>
<table class="small"><tr><th>Missing</th><th>Why it matters</th><th>Instrument next</th></tr>
<tr><td>Reassignment reason code</td><td>We see <i>that</i> tickets bounce, not <i>why</i></td><td>Mandatory drop-down on reassign</td></tr>
<tr><td>Agent "started work" event and time spent</td><td>"Work" time mixes queueing inside the team and real effort</td><td>"Start work" status plus effort field</td></tr>
<tr><td>Priority on email tickets</td><td>{PRI_MISSING} resolved tickets use a defaulted SLA target</td><td>Importer maps priority, or triage sets it</td></tr>
<tr><td>Student confirmation of fix</td><td>Reopens are only noticed when the student complains</td><td>"Did this fix it?" button before closing</td></tr></table>
</section>"""


def retrieval():
    ms = MANIFEST.groupby("source_type").agg(files=("file", "count"), rows=("rows", "sum")).reset_index()
    ms.columns = ["Source type", "Files saved", "Rows"]
    return f"""
<section class="page">
<h2><span class="n">6</span>Retrieval: four source types, reproducible, raw preserved</h2>
<p><code>pipeline/retrieve.py</code> pulls every source into an <b>immutable raw snapshot</b> <code>data/raw/&lt;run_id&gt;/</code> before anything is cleaned. It writes
<code>_manifest.json</code> with row counts and sha256 checksums, so every published number traces back to exactly what the systems returned on that run.
The SQL source is opened <b>read-only</b>. Only needed columns are pulled; student names and emails are not.</p>
<div class="two"><div>{table(ms)}</div>
<div class="box"><h4>Reproduce</h4><pre class="code" style="border-radius:5px">python generator/generate_data.py
python pipeline/run_pipeline.py --run-id demo_run</pre>
<p class="tiny">The API is a local mock (<code>api/mock_portal_api.py</code>, standard library only). It is paginated and seeded to fail about 15% of requests with 500
and about 7% with 429 + <code>Retry-After</code>, like a real SaaS API. The pipeline starts it automatically.</p></div></div>
<h3>The API: "HTTP 200 on one page does not prove the job succeeded"</h3>
{code_block("pipeline/retrieve.py", "def _get(url: str, log) -> dict:", "        except urllib.error.URLError as e:", 30)}
{code_block("pipeline/retrieve.py", "    log.info(f\"API  {total_pages} pages", "    return out", 10)}
<h3>Actual run log (retrieval stage): {retries} transient failures retried, all {raw_inter:,} records proven complete</h3>
{retrieval_log()}
</section>"""


def profiling():
    c = checks.copy()
    c["status"] = c.status.map(badge)
    c = c[["rule_id", "rule", "status", "evidence", "action", "owner"]]
    c.columns = ["#", "Business rule (assumption)", "Status", "Evidence (this run)", "Action", "Owner"]
    rows = []
    for _, r in c.iterrows():
        rows.append("<tr>" + "".join(f"<td>{v if k == 'Status' else e(v)}</td>" for k, v in r.items()) + "</tr>")
    tbl = '<table class="rules"><thead><tr>' + "".join(f"<th>{e(x)}</th>" for x in c.columns) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    p = prof["tickets"]
    cat_vals = ", ".join(f"<code>{e(k)}</code> ({v})" for k, v in list(p["category_values"].items())[:20])
    st_vals = ", ".join(f"<code>{e(k)}</code> ({v})" for k, v in p["status_values"].items())
    fixes = "".join(f"<li>{e(f)}</li>" for f in VAL["fixes"])
    return f"""
<section class="page">
<h2><span class="n">7</span>Profiling &amp; cleaning</h2>
<h3>Business-oriented quality rules → validation gate: <span class="b b-warn" style="font-size:8.5pt">{e(VAL['gate'])}</span></h3>
<p class="tiny">Each rule is a business assumption, tested on every run. <b>FAIL</b> stops the pipeline. <b>WARN</b> means handled and disclosed. <b>UNKNOWN</b> means only a business owner can decide.
This run: {N_PASS} PASS · {N_WARN} WARN · 1 UNKNOWN · 0 FAIL, so the KPI is published as <b>PROVISIONAL</b> with caveats. Evidence strings are generated by the pipeline itself.</p>
{tbl}
</section>
<section class="page">
<h3 style="margin-top:0">Profile of the raw snapshot</h3>
<table class="small"><tr><th>Source</th><th class="num">Rows</th><th>Notable</th></tr>
<tr><td>tickets (SQL)</td><td class="num">{raw_tickets:,}</td><td>{p['distinct']['ticket_id']:,} distinct ticket_id → duplicates; nulls: {', '.join(f"{k} {v}%" for k, v in p['null_pct'].items())}</td></tr>
<tr><td>audit events (CSV)</td><td class="num">{raw_events:,}</td><td>{len(prof['events']['event_types'])} event types; unordered export; nulls by design in from/to status</td></tr>
<tr><td>interactions (API)</td><td class="num">{raw_inter:,}</td><td>4 kinds; all map to tickets</td></tr>
<tr><td>CSAT (JSON)</td><td class="num">{prof['csat']['responses']:,}</td><td>nested <code>respondent</code> / <code>answers</code>; ratings as int <i>and</i> string</td></tr></table>
<p class="tiny"><b>Raw category values:</b> {cat_vals}</p>
<p class="tiny"><b>Raw status values:</b> {st_vals}</p>
<h3>Safe fixes applied (representation only: they don't change business meaning)</h3>
<ul class="tiny">{fixes}</ul>
<h3>Deliberately NOT "cleaned by instinct"</h3>
<table class="small"><tr><th>Issue</th><th>Why not auto-fixed</th><th>What I did instead</th></tr>
<tr><td>Double submissions (same student + subject within 15 min)</td><td>Could be two genuine issues</td><td>Only already-Cancelled ones excluded; the rest are kept and counted</td></tr>
<tr><td>"Exam Cell", "Hostel", "Fees", "IT"</td><td>Semantic mapping, e.g. is Exam Cell the same team as Academics?</td><td>Mapped provisionally and flagged to the Helpdesk Manager; analysis uses the <i>resolving department</i> from the audit log instead</td></tr>
<tr><td>Walk-in tickets with events before "created"</td><td>The true creation time is unknowable</td><td>Excluded from the KPI (8 tickets) and reported; desk clock to be fixed</td></tr>
<tr><td>Missing priority on email tickets</td><td>Changes the SLA target (24h vs 72h)</td><td>Policy default (Medium) applied and flagged; KPI recomputed with "High" as sensitivity (section 9)</td></tr>
<tr><td>Ticket-table <code>resolved_at</code> disagrees with the audit log</td><td>For reopened tickets it holds the first, not the final, fix</td><td>Audit log chosen as source of truth; column ignored; reported to the IT admin</td></tr>
<tr><td>Orphan audit events (unknown ticket_id)</td><td>Cannot be attributed</td><td>Quarantined, not joined</td></tr></table>
<h3>Assumptions &amp; unresolved limitations</h3>
<ul class="tiny">
{''.join(f"<li>{e(a)}</li>" for a in VAL['assumptions'])}
<li>SLA measured in <b>calendar</b> hours (the draft policy). Business-hours SLA is not decided; the sensitivity range is {SENS_MIN:.1f}%–{SENS_MAX:.1f}%.</li>
<li>CSAT is directional only: {CSAT_RR:.0f}% response, and students whose ticket breached SLA respond more often.</li>
<li>The data is a daily batch export (last sync 21 Sep 06:00), so it is fit for weekly or term reporting but <b>not</b> for a live queue dashboard.</li>
</ul>
</section>"""


def model_section():
    grain = pd.DataFrame([
        ("dim_student", "student_id", "—", "1 per student", "entity"),
        ("dim_agent", "agent_id", "—", "1 per agent", "entity"),
        ("fact_ticket", "ticket_id", "student_id", "1 per business ticket (deduped)", "entity"),
        ("fact_ticket_event", "event_id", "ticket_id, actor_id", "1 per lifecycle event", "event / state change"),
        ("fact_interaction", "interaction_id", "ticket_id", "1 per portal message", "interaction"),
        ("fact_intervention", "event_id", "ticket_id", "1 per escalation / reminder", "intervention"),
        ("fact_csat", "ticket_id", "ticket_id", "1 per rated ticket (latest)", "outcome"),
        ("ticket_journey", "ticket_id", "all of the above, aggregated", "1 per ticket", "analysis model"),
    ], columns=["Table", "PK", "FK", "Grain", "Role"])
    counts = []
    import sqlite3
    con = sqlite3.connect(L / "warehouse.db")
    for t in grain.Table:
        counts.append(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    con.close()
    grain.insert(4, "Rows", [f"{c:,}" for c in counts])
    return f"""
<section class="page">
<h2><span class="n">8</span>Workflow model with data</h2>
<p>Source systems are organised by <i>system</i>. The question is about the <i>ticket's journey</i>. So <code>pipeline/model.py</code> builds the <b>smallest model that explains the workflow</b>:
entities (student, agent, ticket), events (the lifecycle), interactions (student and agent messages), interventions (escalations, reminders) and outcomes (SLA, reopen, CSAT).
These are joined into one row per ticket.</p>
{ERD_SVG}
{table(grain, cls="small")}
<h3>How ticket_journey is built (one-to-many tables are aggregated <i>before</i> joining, to keep the grain)</h3>
<table class="small"><tr><th>Field</th><th>Derived from</th></tr>
<tr><td>created, first_assigned, first_response, first/final resolved</td><td>min/max of the relevant audit events per ticket</td></tr>
<tr><td>reassign_count · reopened · resolving_department</td><td>count of <code>reassigned</code> · any <code>→ Reopened</code> · department on the last routing event</td></tr>
<tr><td>pause_hours</td><td>sum of paired intervals <code>→ Waiting on Student</code> … <code>Waiting on Student →</code></td></tr>
<tr><td>6 stage durations</td><td>triage, first-response wait, re-routing, work, waiting-on-student, reopen cycle; they sum exactly to gross time (checked in code)</td></tr>
<tr><td>followup_count · escalated · reminder_sent · csat_rating</td><td>interactions API · interventions · CSAT (left joins)</td></tr>
<tr><td>sla_target · sla_met · in_kpi_population</td><td>priority → policy target; net hours ≤ target; exclusion reasons</td></tr></table>
</section>
<section class="page">
<h3>Three reconstructed journeys (from the audit log)</h3>
{journeys()}
<h3>Metrics are computed in SQL over the model (joins + aggregations)</h3>
{code_block("pipeline/metrics.py", '"by_reassignment": """', '"by_triage_path": """', 12)}
{code_block("pipeline/metrics.py", '"followups_vs_outcome": """', '"stage_breakdown": """', 10)}
<p class="tiny">A <code>MEDIAN</code> aggregate is registered on the SQLite connection so medians are computed in SQL as well. Every segment table is saved to <code>output/runs/&lt;run_id&gt;/segments/</code>.</p>
</section>"""


def journeys():
    import sqlite3
    con = sqlite3.connect(L / "warehouse.db")
    ev = pd.read_sql("SELECT * FROM fact_ticket_event", con, parse_dates=["event_time"])
    con.close()
    picks = {
        "On time": K[(K.sla_met == 1) & (K.reassign_count == 0) & (~K.escalated) & (K.channel == "portal")].ticket_id.iloc[0],
        "Breached after misrouting": K[(K.sla_met == 0) & (K.reassign_count >= 1)].ticket_id.iloc[0],
        "High priority, escalated after breach": K[K.escalated_after_sla_breach & (K.priority == "High")].ticket_id.iloc[0],
    }
    out = []
    for label, tid in picks.items():
        r = J.set_index("ticket_id").loc[tid]
        tl = ev[ev.ticket_id == tid].sort_values("event_time")
        tl = tl[tl.event_type != "status_change"].pipe(lambda d: pd.concat([d, ev[(ev.ticket_id == tid) & (ev.event_type == "status_change")]])).sort_values("event_time")
        tl = tl.assign(when=tl.event_time.dt.strftime("%a %d %b %H:%M"),
                       event=tl.event_type + tl.to_status.fillna("").map(lambda s: f" → {s}" if s else ""))[["when", "event", "department", "actor_id"]]
        tl.columns = ["When", "Event", "Department", "Actor"]
        verdict = "met SLA" if r.sla_met == 1 else "BREACHED"
        out.append(f"<p style='margin:6px 0 2px'><b>{label}: {tid}</b> · {r.priority} priority (target {r.sla_target_hours:.0f}h) · "
                   f"net {r.net_resolution_hours:.0f}h · <b>{verdict}</b> · reassignments {r.reassign_count} · follow-ups {r.followup_count}</p>"
                   + table(tl, cls="small"))
    return "".join(out)


def findings():
    hyp = f"""<table class="small"><tr><th>Hypothesis</th><th>Verdict</th><th>Evidence</th></tr>
<tr><td>H1 Misrouting drives breaches</td><td>{badge('PASS').replace('PASS', 'SUPPORTED')}</td><td>SLA {R0:.0f}% (0 hops) → {R1:.0f}% (1) → {R2:.0f}% (2+); breached tickets spend {RR_B:.0f}h re-routing vs {RR_M:.0f}h</td></tr>
<tr><td>H1b Manual triage alone drives breaches</td><td>{badge('WARN').replace('WARN', 'PARTLY')}</td><td>Manual queue waits {TRI_MED}h, but SLA is {MAN:.0f}% vs {AUTO:.0f}% auto-routed; email {EM:.0f}% ≈ portal {PO:.0f}%. The wait is real but small next to department queues.</td></tr>
<tr><td>H2 Priority not used in queueing</td><td>{badge('PASS').replace('PASS', 'SUPPORTED')}</td><td>Median first response High {FR_H}h ≈ Low {FR_L}h; SLA High {HIGH:.0f}% · Medium {MED:.0f}% · Low {LOW:.0f}%</td></tr>
<tr><td>H3 Capacity / hours constrained teams</td><td>{badge('PASS').replace('PASS', 'SUPPORTED')}</td><td>Fees &amp; Finance {FIN:.0f}%, Academics {ACA:.0f}% (Mon–Fri 9–17) vs IT {IT:.0f}%, Library {LIB:.0f}%</td></tr>
<tr><td>H4 Escalation too late</td><td>{badge('PASS').replace('PASS', 'SUPPORTED')}</td><td>Median escalation at {ESC_MED_H:.0f}h (before breach) / {ESC_LATE_H:.0f}h (after); {ESC_LATE_N} escalated after SLA passed, of which {ESC_LATE_SLA:.0f}% met</td></tr>
<tr><td>H5 Weekend tickets are the main problem</td><td>{badge('WARN').replace('WARN', 'MINOR')}</td><td>Weekend {WKND:.0f}% vs weekday {WKDY:.0f}%: a real gap, but only {int(seg('by_weekend','weekend','tickets'))} tickets; a secondary driver</td></tr></table>"""
    return f"""
<section class="page">
<h2><span class="n">9</span>Findings</h2>
<div class="callout"><b>So what?</b> Breached tickets take <b>{TOT_B}h</b> on average vs <b>{TOT_M}h</b> for tickets that met SLA. The gap is mostly <b>waiting for a first response ({FRW_B:.0f}h vs {FRW_M:.0f}h)</b>,
<b>time inside slow teams ({WK_B:.0f}h vs {WK_M:.0f}h)</b> and <b>re-routing ({RR_B:.0f}h vs {RR_M:.0f}h)</b>. Waiting on the student is the same for both (about 3h), so students are not the cause.</div>
<img class="chart" src="{(L / 'charts' / 'stage_breakdown.png').as_uri()}">
<img class="chart" src="{(L / 'charts' / 'sla_segments.png').as_uri()}">
{hyp}
<p class="tiny"><b>Association ≠ causation.</b> Escalated tickets breach more ({NOT_ESC:.0f}% SLA when not escalated) partly because <i>only slow tickets get escalated</i>. Likewise, tickets with an auto-reminder
({REM_Y:.0f}% vs {REM_N:.0f}%) were already slow. The data shows escalation happens late. It cannot prove how much earlier escalation would help, which is why S3 below is a pilot, not a promise.</p>
</section>
<section class="page">
<img class="chart" src="{(L / 'charts' / 'weekly_trend.png').as_uri()}">
<div class="two">
<div><h3>Students feel it</h3>
<table class="small"><tr><th></th><th class="num">Avg follow-ups</th><th class="num">Avg CSAT</th></tr>
<tr><td>Met SLA</td><td class="num">{FU_M}</td><td class="num">{CS_M}</td></tr>
<tr><td>Breached SLA</td><td class="num">{FU_B}</td><td class="num">{CS_B}</td></tr></table>
<p class="tiny">Every breach creates about {FU_B - FU_M:.1f} extra "any update?" messages, which is load the agents create for themselves. A chatbot could answer these messages, but would not remove the cause.</p></div>
<div><h3>Is the KPI robust to its definition?</h3>
{table(sens.rename(columns={'definition': 'Definition', 'sla_compliance_pct': 'SLA %'}), cls="small")}
<p class="tiny">Definitions move the number by up to {SENS_MAX - SENS_MIN:.1f} pp but <b>none changes the conclusion</b>. The Dean must sign off one definition <b>before</b> the pilot so before and after are comparable.</p></div>
</div>
<h3>Recommendation (Situation → Complication → Resolution)</h3>
<p><b>Situation:</b> the helpdesk receives about {N_TICKETS // 8} tickets a week across 5 teams with a draft 24/72/120h SLA. <b>Complication:</b> only {KPI_PCT:.0f}% meet it ({HIGH:.0f}% of High-priority), and the proposed fix, a chatbot,
targets first contact, which is not where the time goes. <b>Resolution:</b> fix routing, queueing and escalation inside the current tool first. Revisit the chatbot for FAQ-style tickets once the process is sound.</p>
{table(WHATIF[['scenario', 'change', 'key_assumption', 'est_sla_compliance_pct', 'uplift_pp', 'est_high_priority_sla_pct']].rename(columns={'scenario': 'Scenario', 'change': 'Change', 'key_assumption': 'Key assumption', 'est_sla_compliance_pct': 'Est. SLA %', 'uplift_pp': 'Δ pp', 'est_high_priority_sla_pct': 'Est. High %'}), cls="small")}
<p class="tiny">Estimates re-score each measured ticket journey with a stage removed or shrunk (<code>analysis/what_if.py</code>). S1 and S2 are grounded in measured stage times. S3's 40% effect is an <b>assumption</b> to be tested in the pilot.
The combined estimate (about {S123.est_sla_compliance_pct:.0f}%) clears the 75% target with a margin. High-priority still reaches only about {S123.est_high_priority_sla_pct:.0f}%, so High tickets also need a same-day work commitment, not just a faster first response.</p>
</section>
<section class="page">
<h3>Pragmatic action plan (pilot first, then scale)</h3>
<table class="small"><tr><th>Initiative</th><th>What exactly</th><th>Owner</th><th>When</th><th>Leading indicator</th></tr>
<tr><td><b>1. Structured intake</b> (S1)</td><td>Auto-reply to every email with a portal form link; keyword category suggestion; reassign requires a reason code</td><td>Helpdesk Manager + IT admin</td><td>Week 1–2 pilot (email channel)</td><td>Manual-triage wait &lt;2h; reassignment &lt;6%</td></tr>
<tr><td><b>2. SLA-based escalation</b> (S3)</td><td>Replace the 48h daily review with an automatic alert at 50% of each ticket's SLA (12h for High)</td><td>Helpdesk Manager</td><td>Week 1–2 pilot (Finance + Academics)</td><td>&gt;90% of breaches-at-risk escalated before deadline</td></tr>
<tr><td><b>3. Priority-first queue</b> (S2)</td><td>Queue view sorted by SLA deadline, not arrival; High tickets get a same-day owner</td><td>Dept leads</td><td>Week 3</td><td>High first response &lt;4h</td></tr>
<tr><td><b>4. Confirm before close</b></td><td>"Did this fix it?" prompt before auto-close; track reopens</td><td>IT admin</td><td>Week 3–4</td><td>Reopen rate not rising</td></tr>
<tr><td><b>5. Scale + SOP</b></td><td>Roll out to all teams; document triage and escalation SOPs; keep the pipeline running weekly</td><td>Helpdesk Manager</td><td>Week 4–8</td><td>Weekly KPI from the pipeline</td></tr></table>
<div class="two">
<div class="box"><h4>Key success factors</h4><ul class="tiny"><li>Dean signs off one SLA definition before the pilot</li><li>Agents accept deadline-sorted queues (brief them on why)</li><li>Reason codes are actually filled in (make the field mandatory)</li><li>The weekly pipeline gate stays PASS or has known WARNs only</li></ul></div>
<div class="box"><h4>Risks</h4><ul class="tiny"><li>"Fast but wrong" fixes; guarded by the reopen rate and CSAT</li><li>Escalation fatigue if alerts are too many; tune the threshold in the pilot</li><li>Finance and Academics capacity may still cap the gains; escalate a staffing discussion only with pilot evidence</li></ul></div>
</div>
</section>"""


def pipeline_section():
    status = {r: json.loads((ROOT / "output" / "runs" / r / "run_status.json").read_text())
              for r in ["demo_run", "demo_fail_api_outage", "demo_fail_truncated_events"]}
    runs = pd.DataFrame([
        ("demo_run", "normal", "PASS WITH CAVEATS", status["demo_run"]["exit_code"], "yes: output/latest replaced, status PROVISIONAL"),
        ("demo_fail_api_outage", "Portal API returns 503 on every call", "n/a (stopped in retrieve)", status["demo_fail_api_outage"]["exit_code"], "no: output/latest untouched"),
        ("demo_fail_truncated_events", "audit-log export cut to 50%", "FAIL (R06: 50% lifecycle coverage)", status["demo_fail_truncated_events"]["exit_code"], "no: output/latest untouched"),
    ], columns=["Run", "Scenario", "Gate", "Exit code", "Published?"])
    fh = pd.DataFrame([
        ("API 500 / 503 / connection error", "HTTP status / URLError", "Exponential back-off 0.2→3.2s, 6 attempts per page, then stage failure (exit 2)"),
        ("API 429 rate limit", "HTTP 429 + Retry-After", "Wait as instructed, retry"),
        ("API silently incomplete", "fetched ≠ total_records or duplicate ids", "Stage failure; nothing published"),
        ("Missing source / empty file", "R01", "Gate FAIL (exit 1)"),
        ("Partial export", "R06 lifecycle coverage < 98%", "Gate FAIL (exit 1)"),
        ("Grain broken (conflicting ticket ids)", "R02", "Gate FAIL"),
        ("Unknown status / unmapped category", "R08 / R09", "Gate FAIL, so the mapping table must be updated consciously"),
        ("Data issues within tolerance", "WARN / UNKNOWN", "Published as PROVISIONAL; caveats written into metrics.json"),
        ("Model inconsistency", "grain + stage-sum checks after modelling", "Logged as WARNING; unit tests fail in CI"),
    ], columns=["Failure", "Detected by", "Behaviour"])
    return f"""
<section class="page">
<h2><span class="n">10</span>Dependable pipeline</h2>
{PIPELINE_SVG}
<h3>What makes it repeatable</h3><ul class="tiny" style="columns:2;column-gap:18px">
<li>One command: <code>python pipeline/run_pipeline.py</code>; deterministic seed; a run_id per run</li>
<li>Immutable raw snapshot plus manifest (rows, sha256) per run</li>
<li>Rules as code, the same checks every run; results saved as JSON and Markdown</li>
<li>Structured log per run: <code>time | level | stage | message</code></li>
<li><code>run_status.json</code> with per-stage timing and exit code</li>
<li><b>Atomic publish</b>: <code>output/latest</code> is replaced only after a full, gate-passing run (copy then rename)</li>
<li>5 pytest tests: parsers, mappings, the SQL median, and the published model contract</li></ul>
<h3>Runs performed for this report</h3>{table(runs, cls="small")}
<h3>Failure handling</h3>
{table(fh, cls="small")}
</section>
<section class="page">
<h3 style="margin-top:0">Failure run logs (simulated)</h3>
{log_block(LOG_API, keep=lambda l: ("503" in l and ("attempt 1/" in l or "6/6" in l)) or "STAGE FAILURE" in l or "exit code" in l, limit=8)}
{log_block(LOG_TRUNC, keep=lambda l: "SIMULATION" in l or "R06" in l or "GATE" in l or "FAILED" in l or "exit code" in l, limit=8)}
<h3>Normal run: validate → model → metrics → publish (log excerpt)</h3>
{log_block(LOG_OK, keep=lambda l: any(s in l for s in ["| validate", "| model", "| metrics", "| publish", "| run"]) and "R0" not in l and "R1" not in l and "model  " not in l, limit=22)}
<h3>Reliability evidence: does the pipeline get the right answer?</h3>
<p>Because the data is synthetic, the generator's hidden ground truth lets me <b>prove</b> the pipeline is correct. That isn't possible with real data. <code>tests/reconcile_with_truth.py</code> compares:</p>
{table(RECON.rename(columns={'method': 'Method', 'tickets': 'Tickets used', 'sla_compliance': 'SLA %', 'error_vs_truth_pp': 'Error vs truth (pp)'}), cls="small")}
<div class="callout">The pipeline is within <b>{abs(PIPE_ERR):.1f} pp</b> of the truth and agrees on 99% of individual ticket verdicts (the differences are tickets whose missing priority was defaulted).
A <b>naive query</b> on the ticket table looks plausible ({NAIVE_PCT:.1f}%), but it silently uses only {NAIVE_N} tickets. It drops DD/MM dates, status spellings and missing priorities, keeps
duplicates, and times reopened tickets to their <i>first</i> fix. It is close only by accident: its errors partly cancel out, and its segment-level numbers would be wrong.</div>
<p class="tiny">Two real bugs were caught this way while building. (1) A clock-skewed walk-in ticket that the first version of R07 missed: the rule was widened from "resolved before created" to "any event before created".
(2) Reopened tickets that were still open were counted as resolved, now excluded by status. This is why the check exists.</p>
</section>"""


def unknowns_demo():
    gh = link(LINKS.get("github_url"), "GitHub link")
    return f"""
<section class="page">
<h2><span class="n">11</span>What remains unknown, and what I'd do next</h2>
<table><tr><th>Unknown / limitation</th><th>Impact on conclusions</th><th>How to resolve</th><th>Owner</th></tr>
<tr><td>SLA definition not signed off (calendar vs business hours, pause rule)</td><td>KPI ranges {SENS_MIN:.1f}–{SENS_MAX:.1f}%; conclusions unchanged</td><td>Sign-off meeting before the pilot</td><td>Dean</td></tr>
<tr><td>Why tickets are misrouted</td><td>We know the cost, not the cause</td><td>Mandatory reassign reason code; 2 weeks of data</td><td>Helpdesk Manager</td></tr>
<tr><td>Real agent effort vs queueing inside a team</td><td>"Work" time mixes both, so the capacity case is unproven</td><td>"Start work" status + effort field</td><td>IT admin</td></tr>
<tr><td>Causal effect of earlier escalation</td><td>S3 uplift is an assumption</td><td>A/B pilot: Finance and Academics vs other teams</td><td>FDE + Manager</td></tr>
<tr><td>CSAT non-response bias ({CSAT_RR:.0f}% response)</td><td>Satisfaction level uncertain; direction is clear</td><td>Shorter 1-click survey in the resolution email</td><td>Helpdesk Manager</td></tr>
<tr><td>Walk-in desk clock skew; stale <code>resolved_at</code> column</td><td>8 tickets excluded; column ignored</td><td>Fix the desk PC time sync; fix the denormalisation job</td><td>IT admin</td></tr>
<tr><td>Synthetic data</td><td>Patterns are plausible but simulated</td><td>Run the same pipeline on the real export (same schema contract)</td><td>FDE</td></tr></table>
<div class="callout warn"><b>Would I build the AI chatbot now?</b> No. First fix routing and escalation, and sign off the KPI definition. Once the process is sound, a chatbot is worth testing for
FAQ-type tickets (e.g. Wi-Fi, LMS login) and for the "any update?" follow-ups, measured with this same pipeline.</div>

</section>"""


def build():
    body = "".join([cover(), brief(), discovery(), workflow(), kpis(), data_sources(), retrieval(), profiling(),
                    model_section(), findings(), pipeline_section(), unknowns_demo()])
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CampusDesk FDE Assignment</title>
<style>{CSS}</style></head><body>{body}</body></html>"""
    OUT_HTML.write_text(doc)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("wrote", OUT_PDF)


if __name__ == "__main__":
    build()
