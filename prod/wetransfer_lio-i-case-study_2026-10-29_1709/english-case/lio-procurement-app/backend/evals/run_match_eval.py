"""Catalog-suggestion eval (Task 2) against the running API.

Sends each case in ``matching_labels.json`` to ``POST /articles/match`` (the
model-checked path used after a PDF upload) and ``GET /articles/suggest`` (the
typeahead path), and scores both against the labels:

- hit: an expected catalog item is among the suggestions
- top1: the first suggestion is an expected item
- clean: a must-be-none case gets no suggestion (a wrong suggestion is worse than none)

Usage:
    python backend/evals/run_match_eval.py [--runs 3] [--out FILE] [--api URL]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from run_eval import EVAL_DIR, _post_json, _request, sign_in

LABELS = EVAL_DIR / "matching_labels.json"


def score(case: dict, suggestions: list[dict]) -> dict[str, bool | None]:
    items = [s["item"] for s in suggestions]
    if case.get("must_be_none"):
        return {"hit": None, "top1": None, "clean": not items}
    expected = set(case["expected_items"])
    return {"hit": any(i in expected for i in items),
            "top1": bool(items) and items[0] in expected,
            "clean": None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:7200")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--email", default="requester@acme.com")
    parser.add_argument("--password", default="demo1234")
    args = parser.parse_args()

    cases = json.loads(LABELS.read_text())["cases"]
    token = sign_in(args.api, args.email, args.password)
    results = []
    for case in cases:
        line = {k: case[k] for k in ("description", "unit", "unit_price", "quantity")}
        for run in range(1, args.runs + 1):
            started = time.monotonic()
            status, body = _post_json(f"{args.api}/articles/match", {"lines": [line]}, token)
            match_s = time.monotonic() - started
            matched = body["lines"][0]["suggestions"] if status == 200 else []
            started = time.monotonic()
            q = urllib.parse.quote(case["description"][:200])
            status_s, typed = _request("GET", f"{args.api}/articles/suggest?q={q}", token=token)
            suggest_s = time.monotonic() - started
            typed = typed if status_s == 200 else []
            results.append({
                "id": case["id"], "run": run,
                "match": {"seconds": round(match_s, 1), "verified": body.get("verified"),
                          "scores": score(case, matched),
                          "suggestions": [(s["item"], s["quality"], s["reason"]) for s in matched]},
                "suggest": {"seconds": round(suggest_s, 1), "scores": score(case, typed),
                            "suggestions": [s["item"] for s in typed]},
            })
            m = results[-1]["match"]
            print(f"{case['id']:24} run {run}  match {match_s:4.1f}s {m['scores']} "
                  f"{[s[0][:38] + ' (' + s[1] + ')' for s in m['suggestions']]}")

    for path in ("match", "suggest"):
        print(f"\n{path}:")
        for metric in ("hit", "top1", "clean"):
            values = [r[path]["scores"][metric] for r in results
                      if r[path]["scores"][metric] is not None]
            if values:
                print(f"  {metric:5} {sum(values)}/{len(values)}")
        seconds = sorted(r[path]["seconds"] for r in results)
        print(f"  latency p50 {seconds[len(seconds) // 2]}s, max {seconds[-1]}s")

    out = args.out or EVAL_DIR / "out" / (
        f"match-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
