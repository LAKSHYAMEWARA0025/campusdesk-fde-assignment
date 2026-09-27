# CampusDesk: from an ambiguous problem to a dependable data workflow

[![pipeline](https://github.com/LAKSHYAMEWARA0025/campusdesk-fde-assignment/actions/workflows/pipeline.yml/badge.svg)](https://github.com/LAKSHYAMEWARA0025/campusdesk-fde-assignment/actions/workflows/pipeline.yml)

**FDE Assignment (Classes 1–8) · Lakshya Mewara · Roll No. 24bcs10290 · Batch 2024-28**

📄 **Submission report (PDF):** [`report/CampusDesk_FDE_Assignment_Lakshya_Mewara.pdf`](report/CampusDesk_FDE_Assignment_Lakshya_Mewara.pdf)
📓 **Executed walkthrough notebook:** [`notebooks/CampusDesk_FDE_Walkthrough.ipynb`](notebooks/CampusDesk_FDE_Walkthrough.ipynb)
🎬 **5-min demo video:** *link in the PDF cover* · script: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)

---

## 1. The problem

> *"Students keep complaining that helpdesk tickets take forever. Before we buy an AI chatbot for the helpdesk, find out what is actually happening."*
> (Dean of Student Affairs, residential engineering college)

As an FDE, I **didn't build the request (a chatbot)**. I went looking for where the time actually goes.

**SMART problem statement:** only **63%** of student helpdesk tickets resolved between 27 Jul and 20 Sep 2026 met their priority SLA (High 24h / Medium 72h / Low 120h), and only **21%** of High-priority tickets did.
The goal is to identify where delay accumulates in the ticket workflow and implement the highest-impact process fixes, raising SLA compliance to **≥75%** (High ≥50%) **within 8 weeks**, with the **existing team and ticketing tool**.

| Stakeholder | Role |
|---|---|
| Dean of Student Affairs | Sponsor, owns the KPI and the SLA definition |
| Helpdesk Manager | Operational owner: routing, escalation, category mappings |
| Triage coordinators (2) | Route email / "Other" tickets by hand |
| Department agents (IT, Hostel, Finance, Academics, Library) | Resolve tickets |
| Students | Affected users |
| IT admin | Owns the ticketing tool and its data exports |

## 2. Results (published run `demo_run`)

| | |
|---|---|
| **Project KPI: SLA compliance** | **63.1%** (675 / 1,069 resolved tickets). Target: 75% in 8 weeks |
| M1 median first response | 17.9 h |
| M2 median manual-triage wait | 13.2 h |
| M3 reassignment rate | 12.4 % |
| M4 reopen rate | 9.4 % |
| M5 average CSAT (1–5) | 3.69 (36.5% response rate) |

**What the data shows**
- **Priority is captured but ignored.** High-priority tickets wait as long for a first response as Low ones, so only **21%** meet 24h.
- **Misrouting compounds.** SLA is **66%** when routed right first time, **51%** after 1 reassignment, and **18%** after 2 or more.
- **Two teams hold the backlog.** Fees & Finance **28%** and Academics & Exams **45%** (weekday office hours only), against IT at **87%**.
- **Escalation comes too late.** It happens at a daily 10:00 review of tickets open more than 48h (median **65h**). **132** tickets were escalated after their SLA had already passed.
- Breached tickets take **126h** on average vs **42h** for on-time ones. Waiting on the student is about 3h for both, so students are not the cause.

**Recommendation:** don't buy the chatbot yet. Fix intake routing, escalate at 50% of each ticket's SLA, and sort queues by deadline. The estimated result is **about 79%** (`analysis/what_if.py`). Pilot these for 2 weeks with leading indicators before rolling out.

## 3. Data: synthetic, realistic, reproducible

Real helpdesk data is private, so [`generator/generate_data.py`](generator/generate_data.py) (seed 42) **simulates the workflow**: arrival peaks at move-in and mid-sem exams, team working hours, a manual triage queue, misrouting, FIFO queues, waiting-on-student pauses, reopens, a 24h auto-reminder, the 48h escalation review, and CSAT with non-response bias.
It then writes the data **the way real systems would hold it**, with realistic defects injected: duplicate rows, `DD/MM/YYYY` vs ISO dates, 20 spellings of 5 categories, missing priorities, a stale denormalised `resolved_at`, orphan and duplicate audit events, walk-in desk clock skew, a messy nested survey export, and a flaky paginated API.

The simulated ground truth is written to `synthetic_truth/`. **The pipeline never reads it.** Only [`tests/reconcile_with_truth.py`](tests/reconcile_with_truth.py) does, to prove the pipeline gets the right answer.

### Source systems (`source_systems/`)

| Source | Type | Contents | Source-of-truth decision |
|---|---|---|---|
| `helpdesk.db` → `tickets` (1,254 rows), `students` (1,800), `agents` (15) | **SQL** (SQLite) | ticket header: student, channel, category, priority, subject, status | SoT for header fields |
| `ticket_events.csv` (7,849 rows) | **CSV** | audit log: created, assigned, first_response, reassigned, waiting, resolved, reopened, closed, escalated, reminder_sent | **SoT for all timestamps** |
| Portal API `GET /api/v1/interactions` (4,550 records, 23 pages) | **REST API** | student follow-ups, agent replies, info requests | SoT for interactions |
| `csat_survey_export.json` (424 responses) | **JSON** (nested) | ratings 1–5 + comments | directional only |
| `sla_policy.json` | **JSON** | SLA targets and rules (**draft, not signed off**) | policy input |

The API is served by [`api/mock_portal_api.py`](api/mock_portal_api.py) (standard library only). It is seeded to return about 15% HTTP 500s and 7% HTTP 429s with `Retry-After`. The pipeline starts it automatically.

### Modelled warehouse (`output/latest/warehouse.db`)

| Table | Grain | PK / FK | Rows |
|---|---|---|---:|
| `dim_student` | 1 per student | PK `student_id` | 1,800 |
| `dim_agent` | 1 per agent | PK `agent_id` | 15 |
| `fact_ticket` | 1 per business ticket (deduped) | PK `ticket_id`, FK `student_id` | 1,230 |
| `fact_ticket_event` | 1 per lifecycle event | PK `event_id`, FK `ticket_id` | 7,732 |
| `fact_interaction` | 1 per portal message | PK `interaction_id`, FK `ticket_id` | 4,550 |
| `fact_intervention` | 1 per escalation / reminder | FK `ticket_id` | 853 |
| `fact_csat` | 1 per rated ticket (latest valid) | PK/FK `ticket_id` | 394 |
| **`ticket_journey`** | **1 per ticket**: 6 stage durations (sum exactly to total time), reassignments, follow-ups, interventions, SLA outcome, CSAT | PK `ticket_id` | 1,230 |

## 4. The pipeline

```
retrieve ──► validate (gate) ──► model ──► metrics ──► publish
  │              │                                      │
  │ SQL·CSV·     │ 15 business rules                    │ output/latest replaced
  │ JSON·API     │ PASS / WARN / FAIL / UNKNOWN         │ ONLY after a full,
  │ retries +    │ safe fixes only                      │ gate-passing run
  │ completeness │                                      │ (atomic copy + rename)
  ▼              ▼
 exit 2         exit 1      ← nothing published, last good run kept
```

| Stage | File | What it does |
|---|---|---|
| Retrieve | [`pipeline/retrieve.py`](pipeline/retrieve.py) | Read-only SQL, file copies, paginated API with back-off and `Retry-After`; **proves completeness** (fetched = `total_records`, ids unique); raw snapshot + `_manifest.json` (rows, sha256) in `data/raw/<run_id>/` |
| Validate | [`pipeline/validate.py`](pipeline/validate.py) | Profiling and 15 business rules (grain, chronology, source agreement, category/status mapping, priority, referential integrity, CSAT validity, freshness, KPI sign-off). Only representation fixes are applied automatically; semantic ones are flagged to an owner |
| Model | [`pipeline/model.py`](pipeline/model.py) | Dims, facts and `ticket_journey`, written to `warehouse.db`; grain and stage-sum checks |
| Metrics | [`pipeline/metrics.py`](pipeline/metrics.py) | KPI, 5 supporting metrics, segments and definition sensitivity, **all in SQL** (a custom `MEDIAN` aggregate) |
| Charts | [`pipeline/charts.py`](pipeline/charts.py) | Report charts |
| Orchestrator | [`pipeline/run_pipeline.py`](pipeline/run_pipeline.py) | run_id, per-run log `logs/pipeline_<run_id>.log`, `run_status.json`, exit codes, atomic publish |

### Validation rules (latest run: gate = PASS WITH CAVEATS)
R01 sources complete · R02 one row = one ticket · R03 double submissions · R04 timestamps parse · R05 events belong to known tickets · R06 lifecycle coverage + created_at agreement · R07 nothing before "created" · R08 category mapping · R09 status mapping · R10 priority present · R11 referential integrity · R12 `resolved_at` vs audit log · R13 CSAT validity · R14 freshness · R15 SLA definition signed off (UNKNOWN). Full evidence: [`output/latest/validation_report.md`](output/latest/validation_report.md).

### Failure handling

| Failure | Detected by | Behaviour |
|---|---|---|
| API 500 / 503 / connection error | HTTP status | Exponential back-off, 6 attempts per page, then exit 2 |
| API 429 | HTTP 429 + `Retry-After` | Wait as instructed, retry |
| API silently incomplete | count / unique-id check | Exit 2, nothing published |
| Partial export | R06 lifecycle coverage < 98% | Gate FAIL, exit 1 |
| Rule breach above threshold | any rule = FAIL | Gate FAIL, exit 1 |
| Known, disclosed issues | WARN / UNKNOWN | Published as **PROVISIONAL** with caveats in `metrics.json` |

Evidence from the committed runs: `logs/pipeline_demo_run.log` (exit 0), `logs/pipeline_demo_fail_api_outage.log` (exit 2), `logs/pipeline_demo_fail_truncated_events.log` (exit 1). CI re-runs all three on every push.

### Reliability check

| Method | Tickets used | SLA % | Error vs truth |
|---|---:|---:|---:|
| Ground truth (simulated) | 1,077 | 63.5 | – |
| **Pipeline** | 1,069 | **63.1** | **−0.4 pp** (99.1% per-ticket agreement; all differences are defaulted priorities) |
| Naive query on ticket table | 714 | 64.6 | +1.1 pp, but it silently drops 42% of tickets |

## 5. Run it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python generator/generate_data.py                      # optional: regenerate source systems (deterministic)
python pipeline/run_pipeline.py --run-id demo_run      # normal run -> exit 0, publishes output/latest
python pipeline/run_pipeline.py --run-id demo_fail_api_outage --simulate api_outage             # -> exit 2
python pipeline/run_pipeline.py --run-id demo_fail_truncated_events --simulate truncated_events # -> exit 1

python tests/reconcile_with_truth.py                   # pipeline vs ground truth vs naive query
python analysis/what_if.py                             # sizing of recommended fixes
python -m pytest -q tests                              # unit + contract tests
python report/build_report.py                          # rebuild the PDF from outputs (needs Google Chrome)
```

## 6. Repository layout

```
generator/generate_data.py        synthetic data generator (workflow simulation + injected defects)
source_systems/                   the "client systems": helpdesk.db, ticket_events.csv, csat_survey_export.json,
                                  sla_policy.json, portal_api_data.json (API backing store)
api/mock_portal_api.py            mock Portal REST API (paginated, flaky)
pipeline/                         retrieve.py · validate.py · model.py · metrics.py · charts.py · run_pipeline.py · common.py
analysis/what_if.py               scenario sizing (assumptions stated)
tests/                            test_pipeline.py (pytest) · reconcile_with_truth.py
notebooks/                        executed walkthrough (.ipynb + .html)
data/raw/<run_id>/                immutable raw snapshots + manifest, per run
output/latest/                    last published run: warehouse.db, metrics.json, validation report, segments/, charts/
output/runs/<run_id>/             every run, including failed ones (run_status.json)
logs/                             one log per run
report/                           submission PDF + the script that builds it from outputs
docs/DEMO_SCRIPT.md               5-minute demo script
synthetic_truth/                  hidden ground truth (used only by the reliability check)
```

## 7. What remains unknown
- **Why** tickets are misrouted: there is no reassignment reason code, so instrument one.
- Real agent effort vs queueing inside a team: no "start work" event.
- The causal effect of earlier escalation: only slow tickets get escalated, so this needs a pilot.
- The SLA definition (calendar vs business hours, pause rule) is not signed off. The KPI ranges from 57.5% to 65.9% across definitions, and none of them changes the conclusion.
- CSAT non-response bias (36% response rate).
- The data is synthetic. The same pipeline runs on a real export with the same schema.
