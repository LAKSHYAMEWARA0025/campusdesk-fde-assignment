"""
What-if sizing of candidate fixes on the modelled ticket journeys.

These are ESTIMATES, not predictions: each scenario removes or shrinks a
measured stage and re-scores the SLA. Assumptions are stated per row and must be
tested in a pilot before being promised to the client.

  python analysis/what_if.py      (reads output/latest/ticket_journey.csv)
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def scenarios(j: pd.DataFrame) -> pd.DataFrame:
    k = j[j.in_kpi_population].copy()
    target = k.sla_target_hours
    net = k.net_resolution_hours

    routing_saving = k.rerouting_hours + (k.triage_hours - 0.1).where(k.manual_triage, 0).clip(lower=0)
    priority_saving = (0.8 * k.first_response_wait_hours).where(k.priority == "High", 0)

    def early_escalation(x):
        point = 0.5 * target
        late = x > point
        y = x.copy()
        y[late] = point[late] + (x[late] - point[late]) * 0.6
        return y

    s1 = net - routing_saving
    s2 = net - priority_saving
    s3 = early_escalation(net)
    comb12 = net - routing_saving - priority_saving
    comb = early_escalation(comb12)
    rows = [
        ("Baseline (today)", net, "-", "measured"),
        ("S1  Fix intake routing", s1,
         "Email/'Other' tickets get a category at intake (portal form link + keyword suggestion); "
         "removes manual-triage wait and re-routing time", "removed time is not replaced by other waiting"),
        ("S2  Priority-first queue", s2,
         "High-priority tickets jump the department queue", "High first-response wait falls 80% (to ~3h)"),
        ("S3  Escalate at 50% of SLA", s3,
         "Replace 'open > 48h at 10:00 daily review' with an automatic alert at 50% of the ticket's SLA",
         "escalation cuts remaining time by 40% - NOT measured, must be piloted"),
        ("S1 + S2", comb12, "", "as above"),
        ("S1 + S2 + S3", comb, "", "as above"),
    ]
    out = pd.DataFrame([(n, round(100 * (x <= target).mean(), 1), d, a) for n, x, d, a in rows],
                       columns=["scenario", "est_sla_compliance_pct", "change", "key_assumption"])
    out["uplift_pp"] = (out.est_sla_compliance_pct - out.est_sla_compliance_pct.iloc[0]).round(1)
    high = k.priority == "High"
    out["est_high_priority_sla_pct"] = [round(100 * (x[high] <= target[high]).mean(), 1) for _, x, _, _ in rows]
    return out


if __name__ == "__main__":
    j = pd.read_csv(ROOT / "output" / "latest" / "ticket_journey.csv")
    res = scenarios(j)
    res.to_csv(ROOT / "output" / "latest" / "what_if.csv", index=False)
    print(res[["scenario", "est_sla_compliance_pct", "uplift_pp", "est_high_priority_sla_pct"]].to_string(index=False))
