"""
Builds the lightweight 2-page submission PDF (numbers come from the pipeline outputs).

  python report/build_submission.py   -> report/CampusDesk_FDE_Submission_Lakshya_Mewara.pdf

Page 1: one-page problem brief.  Page 2: what I found / built / what remains unknown + links.
Code, flowcharts and full evidence live in the GitHub README; the long-form report is docs/CampusDesk_Full_Report.pdf.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_report as br  # noqa: E402  (loads all numbers + helpers)
from build_report import e  # noqa: E402

ROOT = br.ROOT
OUT_HTML = ROOT / "report" / "submission.html"
OUT_PDF = ROOT / "report" / "CampusDesk_FDE_Submission_Lakshya_Mewara.pdf"
REPO = br.LINKS.get("github_url") or "https://github.com/LAKSHYAMEWARA0025/campusdesk-fde-assignment"
VIDEO = br.LINKS.get("demo_video_url", "")
BLOB = f"{REPO}/blob/main"


def a(url, label=None):
    return f'<a href="{e(url)}">{e(label or url)}</a>'


EXTRA_CSS = """
@page { size: A4; margin: 11mm 12mm; }
body { font-size: 8.6pt; line-height: 1.33; }
.head { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 2px solid var(--blue); padding-bottom: 4px; margin-bottom: 7px; }
.head .t { font-size: 13.5pt; font-weight: 700; }
.head .m { font-size: 8.3pt; color: var(--ink2); text-align: right; }
h2 { font-size: 11pt; border-bottom: 1.5px solid var(--blue); margin: 0 0 5px; padding-bottom: 2px; }
h3 { font-size: 9.4pt; margin: 7px 0 3px; }
table { font-size: 7.8pt; margin: 2px 0 5px; } td, th { padding: 2.5px 4px; }
p { margin: 0 0 4px; } ul { margin: 1px 0 4px 15px; } li { margin: 1px 0; }
.brief h2 { display: none; }
.links td { border: none; padding: 1.5px 4px; font-size: 8.3pt; } .links td:first-child { white-space: nowrap; font-weight: 700; width: 1%; }
.video { border: 2px solid var(--blue); background: #eef4fc; border-radius: 6px; padding: 7px 10px; margin-top: 6px; font-size: 9.2pt; }
.kpis { gap: 5px; margin: 3px 0 5px; } .kpi { padding: 5px 7px; } .kpi .v { font-size: 13.5pt; } .kpi .l { font-size: 7.3pt; }
img.chart { display: block; width: 84%; margin: 0 auto 2px; }
"""


def header():
    return f"""<div class="head"><div class="t">CampusDesk · FDE Assignment</div>
<div class="m"><b>Lakshya Mewara</b> · Roll No. 24bcs10290 · Batch 2024-28</div></div>"""


def page1():
    # reuse the one-page brief, dropping its section heading and the trailing data line
    b = br.brief().replace('<section class="page brief">', '<section class="page brief">' + header() +
                           '<h2 style="display:block">1 · One-page problem brief</h2>', 1)
    return b


def page2():
    rows = [
        ("1 FDE mindset & stakeholders", "Stakeholders, goals, constraints, facts / assumptions / unknowns; chatbot request reframed", "README §1"),
        ("2 Workflow & problem structure", "Current-state workflow flowchart, 5 pain points, MECE issue tree, 5 hypotheses, SMART statement", "README §2"),
        ("3 KPIs, scope & solution", f"KPI = SLA compliance ({br.KPI_PCT:.1f}%), 5 supporting metrics, MVP / out-of-scope, success criteria", "Page 1 · README §3"),
        ("4 Client data & sources", "Source map with source-of-truth choices, key fields, missing events; synthetic data generation logic", "README §4 · source_systems/"),
        ("5 Retrieval (4 types)", f"SQL (SQLite) · CSV audit log · nested JSON · paginated REST API with retries; completeness proven "
                                 f"({br.raw_inter:,}/{br.raw_inter:,} records); raw snapshot + sha256 manifest", "README §5 · retrieve.py"),
        ("6 Profiling & cleaning", f"Profiling + 15 business rules → PASS/WARN/FAIL/UNKNOWN gate ({br.N_PASS} PASS, {br.N_WARN} WARN, 1 UNKNOWN); "
                                   "safe fixes only, semantic issues flagged to owners", "README §6 · validate.py"),
        ("7 Workflow model", "Entities, events, interactions, interventions, outcomes → ticket_journey (1 row/ticket); all metrics in SQL joins/aggregations", "README §7 · model.py, metrics.py"),
        ("8 Dependable pipeline", "retrieve → validate → model → metrics → publish; per-run logs, exit codes, atomic publish; API outage → exit 2, "
                                  "truncated export → gate FAIL, nothing published; CI re-runs all on every push", "README §8 · logs/ · CI"),
    ]
    built = "".join(f"<tr><td><b>{e(x)}</b></td><td>{e(y)}</td><td><code>{e(z)}</code></td></tr>" for x, y, z in rows)
    video = (a(VIDEO) if VIDEO else '<span class="todo">Google Drive link to be added</span>')
    return f"""
<section class="page">
{header()}
<h2>2 · What I found</h2>
<div class="kpis">
<div class="kpi hero"><div class="v">{br.KPI_PCT:.1f}%</div><div class="l">SLA compliance (KPI), {br.N_RES:,} resolved tickets · target 75%</div></div>
<div class="kpi"><div class="v">{br.HIGH:.0f}%</div><div class="l">High-priority tickets within 24h</div></div>
<div class="kpi"><div class="v">{br.R0:.0f}→{br.R2:.0f}%</div><div class="l">SLA: routed right first time → 2+ reassignments</div></div>
<div class="kpi"><div class="v">{br.TOT_B}h vs {br.TOT_M}h</div><div class="l">avg time, breached vs on-time tickets</div></div>
</div>
<img class="chart" src="{(br.L / 'charts' / 'sla_segments.png').as_uri()}">
<ul>
<li><b>Priority is captured but ignored:</b> High tickets wait as long for a first response ({br.FR_H}h median) as Low ({br.FR_L}h).</li>
<li><b>Misrouting compounds delay:</b> {br.REASSIGN:.0f}% of tickets are reassigned, and each hop cuts the SLA odds ({br.R0:.0f}% → {br.R1:.0f}% → {br.R2:.0f}%).</li>
<li><b>Two teams hold the backlog:</b> Fees &amp; Finance {br.FIN:.0f}% and Academics {br.ACA:.0f}% (weekday office hours) vs IT {br.IT:.0f}%.</li>
<li><b>Escalation is too late:</b> a daily review of tickets open &gt;48h (median {br.ESC_MED_H:.0f}h); {br.ESC_LATE_N} tickets escalated only after breaching. Students aren't the cause (about 3h waiting on them either way).</li>
</ul>
<p><b>Recommendation:</b> don't buy the chatbot yet. Fix intake routing, escalate at 50% of each ticket's SLA, and sort queues by deadline.
The estimate is about <b>{br.S123.est_sla_compliance_pct:.0f}%</b> (above the 75% target). Pilot for 2 weeks with leading indicators (reassignment rate, triage wait, on-time escalations) before scaling.</p>

<h2 style="margin-top:6px">3 · What I built (evidence in the repo)</h2>
<table><tr><th style="width:21%">Skill area</th><th>Evidence</th><th style="width:25%">Where</th></tr>{built}</table>
<p><b>Reliability:</b> against the generator's hidden ground truth ({br.TRUE_PCT}%), the pipeline gives {br.KPI_PCT}% ({br.PIPE_ERR:+.1f} pp, 99% per-ticket agreement).
A naive query silently drops {100 - round(100 * br.NAIVE_N / br.N_TICKETS)}% of tickets.</p>

<h2 style="margin-top:6px">4 · What remains unknown</h2>
<ul>
<li><b>Why</b> tickets are misrouted: there's no reassignment reason code, so instrument one.</li>
<li>Causal effect of earlier escalation (only slow tickets get escalated, so the pilot must test it); real agent effort (no "start work" event); CSAT bias ({br.CSAT_RR:.0f}% response).</li>
<li>The SLA definition isn't signed off by the Dean (the KPI is {br.SENS_MIN:.1f}–{br.SENS_MAX:.1f}% across definitions, and the conclusion holds under all of them).</li>
</ul>

<table class="links">
<tr><td>GitHub repo</td><td>{a(REPO)} (README explains every stage, with flowcharts)</td></tr>
<tr><td>Notebook · pipeline</td><td>{a(BLOB + '/notebooks/CampusDesk_FDE_Walkthrough.ipynb', 'walkthrough notebook')} · {a(REPO + '/tree/main/logs', 'logs/')} · {a(BLOB + '/output/latest/validation_report.md', 'validation_report.md')} · {a(REPO + '/actions', 'CI runs')} · {a(BLOB + '/docs/CampusDesk_Full_Report.pdf', 'detailed report (optional)')}</td></tr>
</table>
<div class="video"><b>5-min demo video:</b> {video}</div>
</section>"""


def build():
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CampusDesk FDE Submission - Lakshya Mewara</title>
<style>{br.CSS}{EXTRA_CSS}</style></head><body>{page1()}{page2()}</body></html>"""
    OUT_HTML.write_text(doc)
    subprocess.run([br.CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["xattr", "-d", "com.apple.quarantine", str(OUT_PDF)], stderr=subprocess.DEVNULL)
    print("wrote", OUT_PDF)


if __name__ == "__main__":
    build()
