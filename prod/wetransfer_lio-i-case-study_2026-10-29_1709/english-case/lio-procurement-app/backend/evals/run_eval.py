"""Field-level extraction eval against the running API.

Uploads each labelled quote exactly as the frontend does, scores the response
against ``labels.json``, and writes the raw responses + run metadata to
``evals/out/`` (or ``--out``). Needs a running stack (``docker compose up``)
with OPENAI_API_KEY set.

Saved runs can be re-scored offline against the current labels, so tightening
the labels never requires re-running old code or paying for new API calls.

Usage:
    python backend/evals/run_eval.py [--runs 3] [--pipeline pdf|text] [--file QT-4120]
        [--tag NAME] [--model gpt-4o-mini] [--out FILE] [--api URL] [--quotes DIR]
    python backend/evals/run_eval.py --rescore backend/evals/results/baseline-legacy.json

Stdlib only, so it runs from the host without a virtualenv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
APP_DIR = EVAL_DIR.parent.parent
DEFAULT_QUOTES = APP_DIR.parent / "quotes"
LABELS_FILE = EVAL_DIR / "labels.json"

BASE_FIELDS = ["ok", "vendor", "vat_id", "grand_total", "lines", "commodity"]
# Scored only for quotes whose label has an ``extended`` block; n/a otherwise.
EXTENDED_FIELDS = ["department", "line_detail", "charges", "tax", "reconciles", "flagged"]
FIELDS = BASE_FIELDS + EXTENDED_FIELDS
MONEY_TOLERANCE = 0.01
QUANTITY_TOLERANCE = 0.001


# ---------------------------------------------------------------------------
# HTTP (stdlib)
# ---------------------------------------------------------------------------

def _request(method: str, url: str, *, token: str | None = None,
             body: bytes | None = None, content_type: str | None = None,
             timeout: float = 180) -> tuple[int, dict | str]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode(errors="replace")


def _post_json(url: str, payload: dict, token: str | None = None):
    return _request("POST", url, token=token, body=json.dumps(payload).encode(),
                    content_type="application/json")


def _post_file(url: str, path: Path, token: str):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return _request("POST", url, token=token, body=body,
                    content_type=f"multipart/form-data; boundary={boundary}")


def sign_in(api: str, email: str, password: str) -> str:
    status, body = _post_json(f"{api}/auth/signin", {"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"Sign-in failed ({status}): {body}")
    return body["access_token"]


# ---------------------------------------------------------------------------
# Pipelines: each returns the extraction envelope {success, data, error, ...}
# ---------------------------------------------------------------------------

def run_text(api: str, token: str, path: Path) -> dict:
    """Two-step text flow: /pdf/parse (plain text) then /extraction (no images).

    This was the original upload flow ("legacy" in the baseline); the endpoints
    now run the new checks too, so it no longer measures the original code.
    """
    status, body = _post_file(f"{api}/pdf/parse", path, token)
    if status != 200:
        return {"success": False, "error": f"/pdf/parse {status}: {body}"}
    status, body = _post_json(f"{api}/extraction", {"text": body["text"]}, token)
    if status != 200:
        return {"success": False, "error": f"/extraction {status}: {body}"}
    return body


def run_pdf(api: str, token: str, path: Path) -> dict:
    """Current upload flow: /extraction/pdf (layout text + page images + checks)."""
    status, body = _post_file(f"{api}/extraction/pdf", path, token)
    if status != 200:
        return {"success": False, "error": f"/extraction/pdf {status}: {body}"}
    return body


PIPELINES = {"pdf": run_pdf, "text": run_text}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _has_total(totals: list[float], target: float) -> bool:
    return any(abs(t - target) <= MONEY_TOLERANCE for t in totals)


def _close(actual: object, expected: float, tolerance: float = MONEY_TOLERANCE) -> bool:
    return abs(float(actual or 0) - expected) <= tolerance


def _line_detail_ok(expected_lines: list[dict], lines: list[dict]) -> bool:
    """Every expected line is present (matched by total) with the right quantity and unit price."""
    for expected in expected_lines:
        match = next((line for line in lines if _close(line.get("totalPrice"), expected["total"])),
                     None)
        if match is None:
            return False
        if not _close(match.get("amount"), expected["quantity"], QUANTITY_TOLERANCE):
            return False
        if not _close(match.get("unitPrice"), expected["unit_price"]):
            return False
    return True


def score(label: dict, envelope: dict) -> dict[str, bool | None]:
    """Per-field pass/fail. ``None`` means the field isn't labelled for this quote (n/a)."""
    extended = label.get("extended")
    applicable = BASE_FIELDS + (EXTENDED_FIELDS if extended else [])
    data = envelope.get("data") or {}
    if not envelope.get("success") or not data:
        return {f: (False if f in applicable else None) for f in FIELDS}

    vendor = (data.get("vendorName") or "").lower()
    lines = data.get("orderLines") or []
    line_totals = [float(line.get("totalPrice") or 0) for line in lines]
    expected_vat = label["vat_id"]
    scores: dict[str, bool | None] = {
        "ok": True,
        "vendor": any(alias.lower() in vendor for alias in label["vendor_aliases"]),
        "vat_id": (
            not _digits(data.get("vatId"))
            if expected_vat is None
            else _digits(data.get("vatId")) == _digits(expected_vat)
        ),
        "grand_total": abs(float(data.get("totalCost") or 0) - label["grand_total"])
        <= MONEY_TOLERANCE,
        "lines": all(_has_total(line_totals, t) for t in label["required_line_totals"])
        and not any(_has_total(line_totals, t) for t in label["forbidden_line_totals"]),
        "commodity": data.get("commodityGroupId") in label["commodity_group_ids"],
    }
    if not extended:
        return {**scores, **{f: None for f in EXTENDED_FIELDS}}

    department = (data.get("department") or "").strip()
    shipping = float(data.get("shippingAmount") or 0)
    fees = float(data.get("feesAmount") or 0)
    tax = float(data.get("taxAmount") or 0)
    scores["department"] = (
        not department
        if extended["department"] is None
        else extended["department"].lower() in department.lower()
    )
    scores["line_detail"] = _line_detail_ok(extended["lines"], lines)
    scores["charges"] = _close(shipping, extended["shipping"]) and _close(fees, extended["fees"])
    scores["tax"] = _close(tax, extended["tax"])
    # Internal consistency of the extraction itself: lines + shipping + fees + tax = total cost.
    scores["reconciles"] = _close(sum(line_totals) + shipping + fees + tax,
                                  float(data.get("totalCost") or 0))
    # No silent errors: either everything above is right, or the response carries a warning.
    # (Legacy responses only have missingFields; the new pipeline returns warnings.)
    warned = bool(envelope.get("warnings") or envelope.get("missingFields"))
    scores["flagged"] = all(scores.values()) or warned
    return scores


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report(results: list[dict], labels: list[dict]) -> dict:
    """Print per-quote x per-field pass counts and overall accuracy; return the summary.

    Fields that are n/a for a quote (``None``) are shown as "-" and left out of the totals.
    """
    def scored(rows: list[dict], field: str) -> list[bool]:
        return [r["scores"].get(field) for r in rows if r["scores"].get(field) is not None]

    width = max(len(f) for f in FIELDS) + 1
    per_quote = {}
    print(f"\n{'quote':40} " + " ".join(f"{f:>{width}}" for f in FIELDS))
    for label in labels:
        rows = [r for r in results if r["file"] == label["file"]]
        if not rows:
            continue
        cells, counts = [], {}
        for f in FIELDS:
            values = scored(rows, f)
            counts[f] = f"{sum(values)}/{len(values)}" if values else None
            cells.append(counts[f] or "-")
        per_quote[label["file"]] = {"runs": len(rows), **counts}
        print(f"{label['file'][:40]:40} " + " ".join(f"{c:>{width}}" for c in cells))

    overall = {}
    for f in FIELDS:
        values = scored(results, f)
        overall[f] = round(100 * sum(values) / len(values)) if values else None
    print(f"{'ALL':40} " + " ".join(
        f"{(f'{overall[f]}%' if overall[f] is not None else '-'):>{width}}" for f in FIELDS))

    seconds = sorted(r["seconds"] for r in results)
    latency = {"p50": seconds[len(seconds) // 2], "max": seconds[-1]}
    print(f"\nlatency p50 {latency['p50']}s, max {latency['max']}s")
    return {"overall_pct": overall, "per_quote": per_quote, "latency_s": latency}


# ---------------------------------------------------------------------------
# Run metadata + persistence
# ---------------------------------------------------------------------------

def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=APP_DIR, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _configured_model() -> str:
    """OPENAI_MODEL from the app's .env (what docker compose passes the backend)."""
    env_file = APP_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "OPENAI_MODEL" and value.strip():
                return value.strip()
    return "gpt-4o-mini"  # docker-compose.yml default


def _labels_sha256() -> str:
    return hashlib.sha256(LABELS_FILE.read_bytes()).hexdigest()[:12]


def load_run(path: Path) -> dict:
    """Load a saved run. Older runs were a bare list of results with no metadata."""
    data = json.loads(path.read_text())
    return {"meta": {}, "results": data} if isinstance(data, list) else data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:7200")
    parser.add_argument("--quotes", type=Path, default=DEFAULT_QUOTES)
    parser.add_argument("--pipeline", choices=sorted(PIPELINES), default="pdf")
    parser.add_argument("--file", default=None,
                        help="only run quotes whose file name contains this text")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model", default=None,
                        help="model the backend runs (default: OPENAI_MODEL from .env)")
    parser.add_argument("--tag", default=None, help="label for this run (default: pipeline-model)")
    parser.add_argument("--out", type=Path, default=None, help="where to save the run")
    parser.add_argument("--rescore", type=Path, default=None,
                        help="score a saved run against the current labels (no API calls)")
    parser.add_argument("--email", default="requester@acme.com")
    parser.add_argument("--password", default="demo1234")
    args = parser.parse_args()

    labels = json.loads(LABELS_FILE.read_text())["quotes"]
    labels_by_file = {label["file"]: label for label in labels}
    if args.file:
        labels = [label for label in labels if args.file in label["file"]]

    if args.rescore:
        run = load_run(args.rescore)
        for r in run["results"]:
            r["scores"] = score(labels_by_file[r["file"]], r["response"])
        meta = run["meta"]
        print(f"Re-scored {args.rescore} ({meta.get('tag', 'untagged')}, "
              f"model {meta.get('model', '?')}) against labels {_labels_sha256()}")
        report(run["results"], labels)
        return

    model = args.model or _configured_model()
    tag = args.tag or f"{args.pipeline}-{model}"
    started_at = datetime.now(timezone.utc)
    token = sign_in(args.api, args.email, args.password)
    pipeline = PIPELINES[args.pipeline]

    results = []
    for label in labels:
        for run_no in range(1, args.runs + 1):
            started = time.monotonic()
            envelope = pipeline(args.api, token, args.quotes / label["file"])
            elapsed = time.monotonic() - started
            scores = score(label, envelope)
            results.append({"file": label["file"], "run": run_no, "seconds": round(elapsed, 1),
                            "scores": scores, "response": envelope})
            failed = [f for f, passed in scores.items() if passed is False]  # None = n/a
            print(f"{label['file'][:40]:40} run {run_no}  {elapsed:5.1f}s  "
                  f"{'PASS' if not failed else 'fail: ' + ', '.join(failed)}"
                  + (f"  [{envelope.get('error')}]" if envelope.get("error") else ""))

    summary = report(results, labels)
    meta = {
        "tag": tag,
        "pipeline": args.pipeline,
        "model": model,
        "runs_per_quote": args.runs,
        "started_at": started_at.isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", ".")),
        "labels_sha256": _labels_sha256(),
        "summary": summary,
    }

    out_file = args.out or (
        EVAL_DIR / "out" / f"{tag}-{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({"meta": meta, "results": results}, indent=2) + "\n")
    print(f"saved: {out_file}")


if __name__ == "__main__":
    main()
