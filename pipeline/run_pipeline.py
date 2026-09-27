"""
CampusDesk pipeline:  retrieve -> validate -> transform/model -> metrics -> publish

  python pipeline/run_pipeline.py                         # normal run
  python pipeline/run_pipeline.py --simulate api_outage   # API down  -> run fails safely, nothing published
  python pipeline/run_pipeline.py --simulate truncated_events   # partial CSV export -> gate FAILs

Every run gets a run_id. Outputs:
  data/raw/<run_id>/            immutable raw snapshot + manifest (row counts, sha256)
  output/runs/<run_id>/         warehouse.db, validation report, metrics.json, segments/, charts/
  output/latest/                ONLY replaced when the run passes the validation gate
  logs/pipeline_<run_id>.log    full log

Exit codes: 0 = published, 1 = stopped by validation gate, 2 = stage failure (e.g. retrieval)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import charts  # noqa: E402
import metrics  # noqa: E402
import model  # noqa: E402
import retrieve  # noqa: E402
import validate  # noqa: E402
from common import API_BASE, OUTPUT_ROOT, RAW_ROOT, ROOT, PipelineError, get_logger, stage_logger, write_json  # noqa: E402


def api_up() -> bool:
    try:
        with urllib.request.urlopen(f"{API_BASE}/api/v1/health", timeout=2) as r:
            return json.loads(r.read())["status"] == "ok"
    except Exception:
        return False


def start_api(mode: str):
    proc = subprocess.Popen([sys.executable, str(ROOT / "api" / "mock_portal_api.py"), "--mode", mode],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.2)
        try:
            urllib.request.urlopen(f"{API_BASE}/api/v1/health", timeout=1)
            return proc
        except Exception:
            continue
    return proc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", choices=["api_outage", "truncated_events"], default=None)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    run_id = args.run_id or datetime.now().strftime("%Y%m%dT%H%M%S") + (f"_{args.simulate}" if args.simulate else "")
    log = get_logger(run_id)
    L = lambda s: stage_logger(log, s)
    raw_dir, out_dir = RAW_ROOT / run_id, OUTPUT_ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    status = {"run_id": run_id, "started_at": datetime.now().isoformat(timespec="seconds"),
              "simulate": args.simulate, "stages": {}}
    L("run").info(f"=== CampusDesk pipeline run {run_id} ===")

    api_proc = None
    if args.simulate == "api_outage" or not api_up():
        api_proc = start_api("outage" if args.simulate == "api_outage" else "normal")
        L("run").info(f"started mock Portal API ({'outage' if args.simulate == 'api_outage' else 'normal'} mode)")

    code = 0
    try:
        t0 = time.time()
        manifest = retrieve.run(raw_dir, L("retrieve"), args.simulate)
        status["stages"]["retrieve"] = {"ok": True, "files": len(manifest), "secs": round(time.time() - t0, 1)}

        t0 = time.time()
        V, clean = validate.run(raw_dir, L("validate"))
        (out_dir / "validation_report.md").write_text(validate.to_markdown(V))
        write_json(out_dir / "validation_report.json", validate.as_dict(V))
        status["stages"]["validate"] = {"ok": V.gate != "FAIL", "gate": V.gate, "secs": round(time.time() - t0, 1)}
        L("validate").info(f"VALIDATION GATE: {V.gate}")
        if V.gate == "FAIL":
            failed = [c.rule_id for c in V.checks if c.status == "FAIL"]
            L("validate").error(f"gate FAILED on {failed} -> metrics NOT published; output/latest left unchanged")
            code = 1
            return code

        t0 = time.time()
        journey, db = model.run(clean, out_dir, L("model"))
        journey.to_csv(out_dir / "ticket_journey.csv", index=False)
        status["stages"]["model"] = {"ok": True, "tickets": len(journey), "secs": round(time.time() - t0, 1)}

        t0 = time.time()
        M = metrics.run(db, out_dir, L("metrics"))
        chart_paths = charts.make_all(M["segments"], out_dir / "charts")
        publish = {
            "run_id": run_id, "status": "PROVISIONAL" if V.gate != "PASS" else "FINAL",
            "caveats": [f"{c.rule_id}: {c.evidence}" for c in V.checks if c.status in ("WARN", "UNKNOWN")],
            "kpi": {"name": "SLA compliance rate", **M["kpi"]},
            "supporting_metrics": M["supporting"],
        }
        write_json(out_dir / "metrics.json", publish)
        status["stages"]["metrics"] = {"ok": True, "charts": len(chart_paths), "secs": round(time.time() - t0, 1)}

        # publish atomically: only a fully successful, gate-passing run replaces 'latest'
        latest = OUTPUT_ROOT / "latest"
        tmp = OUTPUT_ROOT / f".latest_tmp_{run_id}"
        shutil.copytree(out_dir, tmp)
        if latest.exists():
            shutil.rmtree(latest)
        tmp.rename(latest)
        L("publish").info(f"published run {run_id} to output/latest (status={publish['status']})")
    except PipelineError as e:
        L("run").error(f"STAGE FAILURE: {e} -> run aborted, metrics NOT published, output/latest left unchanged")
        status["error"] = str(e)
        code = 2
    finally:
        status["finished_at"] = datetime.now().isoformat(timespec="seconds")
        status["exit_code"] = code
        write_json(out_dir / "run_status.json", status)
        if api_proc:
            api_proc.terminate()
        L("run").info(f"=== run finished, exit code {code} ===")
    return code


if __name__ == "__main__":
    sys.exit(main())
