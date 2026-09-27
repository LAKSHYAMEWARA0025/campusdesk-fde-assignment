| Rule | Check | Status | Evidence | Action | Owner |
|---|---|---|---|---|---|
| R01 | Every source returned data; API returned all records | **PASS** | empty sources: none; API completeness proven in retrieve stage | stop run if any source empty | FDE / data |
| R02 | One row = one ticket (ticket_id unique) | **WARN** | 24 exact duplicate rows (1.9%); 0 conflicting ids | exact duplicates dropped (safe); conflicting ids would stop the run | FDE / data |
| R03 | A student's repeat submission of the same issue is not counted twice | **PASS** | 22 same student+subject within 15 min; 22 already marked Cancelled | Cancelled tickets excluded from KPI; the rest are NOT auto-merged (could be genuine repeats) | Helpdesk Manager |
| R04 | created_at is a valid timestamp | **WARN** | 200 rows in DD/MM/YYYY format (email importer); unparseable after fix: 0.0% | parsed both formats; day-first confirmed against the audit log (R06) | FDE / data |
| R05 | Every audit-log event belongs to a known ticket | **WARN** | 25 orphan events (0.6%); 15 duplicate events dropped | orphans quarantined, not joined | IT admin (ticketing tool) |
| R06 | Every ticket has a 'created' event and both systems agree on created_at | **FAIL** | tickets with audit-log lifecycle: 50.0%; created_at agreement within 1 min: 99.5% (DD/MM rows agree only when parsed day-first) | source of truth for lifecycle times = audit log; stop run if lifecycle coverage < 98% | FDE / data |
| R07 | 'created' is the first event of every ticket (nothing happens before creation) | **WARN** | 3 tickets (0.3%) have events before 'created' (0 even resolved before creation); channels: {'walk_in': 3} -> walk-in desk clock skew | excluded from KPI (not guessed); walk-in desk clock to be fixed | IT admin (walk-in desk PC) |
| R08 | Each ticket maps to one canonical category | **WARN** | 20 raw values -> 5 canonical + Unknown; representation fixes=1088, semantic mappings=142 (Academics, Exam Cell, Fees, Finance, HOSTEL, Hostel, IT), Unknown/Other=41 | semantic mappings applied provisionally; analysis uses RESOLVING department from audit log instead | Helpdesk Manager |
| R09 | Every status maps to a known lifecycle state | **PASS** | 11 raw values -> 6 canonical; unmapped=0 | casing/underscore variants normalised | FDE / data |
| R10 | Every ticket has a priority (it sets the SLA target) | **WARN** | 145 tickets (11.8%) missing priority, all email channel | defaulted to 'Medium' per draft policy; KPI sensitivity reported | Helpdesk Manager |
| R11 | Tickets map to students; interactions map to tickets | **PASS** | tickets->students 100.0%; interactions->tickets 100.0% | none needed | FDE / data |
| R12 | resolved_at in ticket table = final resolution in audit log | **WARN** | of 565 resolved tickets: 20 missing resolved_at, 48 hold the FIRST resolution (reopened) | use audit log as source of truth; ticket-table resolved_at ignored | IT admin (ticketing tool) |
| R13 | One valid 1-5 rating per ticket | **WARN** | 424 responses: 6 no ticket ref, 9 out of 1-5, 15 resubmissions (kept latest) -> 394 valid; ref formats normalised (tkt100234 / 100234 -> TKT-100234); maps to tickets 100.0% | directional only: ~36% response rate, unhappy students respond more | FDE / data |
| R14 | Data is fresh enough for the decision | **PASS** | latest event 2026-09-21 04:21; API last_synced 2026-09-21T06:00 (6h after period end) | fit for weekly/term reporting; NOT fit for a live queue dashboard (daily batch export) | FDE / data |
| R15 | SLA definition is agreed by the KPI owner | **UNKNOWN** | policy file says: 'Student Helpdesk SLA v1 (draft, not formally signed off)'; pause rule & calendar-vs-business hours not signed off | publish as PROVISIONAL; show sensitivity to definition | Dean of Student Affairs |

**Gate: FAIL**

Safe fixes applied:
- Dropped 24 exact duplicate ticket rows (email importer double-sync).
- Parsed 200 DD/MM/YYYY HH:MM timestamps (email importer) alongside ISO format.
- Dropped 15 duplicate audit-log events (same event_id).
- Normalised category casing/whitespace (e.g. 'it support', 'HOSTEL ' -> canonical).
- Normalised status variants (e.g. 'closed', 'in_progress', 'closed_no_response').
- CSAT: normalised ticket refs, cast string ratings to int, dropped out-of-range, kept latest per ticket.

Assumptions:
- Semantic category mappings pending owner confirmation: Academics, Exam Cell, Fees, Finance, HOSTEL, Hostel, IT.
- Missing priority (email tickets) = Medium, per draft SLA policy default.