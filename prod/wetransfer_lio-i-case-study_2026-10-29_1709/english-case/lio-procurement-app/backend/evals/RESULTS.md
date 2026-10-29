# Extraction eval results

Benchmark: Acme's five vendor quotes (`../quotes/`), ground truth in [`labels.json`](labels.json).
Each quote is uploaded through the running API exactly like the frontend, 3 runs per quote.

| Field | Passes when |
|---|---|
| ok | the upload returns an extraction instead of an error |
| vendor | the vendor name contains one of the expected aliases |
| vat_id | the vendor tax ID matches (digits only); stays empty when the quote has none |
| grand_total | the total is within $0.01 of the grand total |
| lines | every required line total is present and no alternative/optional line is |
| commodity | the commodity group is one of the acceptable ids (soft metric) |

Reproduce:

```bash
python3 backend/evals/run_eval.py --runs 3                                        # live run
python3 backend/evals/run_eval.py --rescore backend/evals/results/baseline-legacy.json   # offline re-score
```

Saved runs keep the raw API responses, so any run can be re-scored when the labels change.
Numbers in this file are always computed against the labels hash shown in each section.

---

## Baseline: original pipeline

File: [`results/baseline-legacy.json`](results/baseline-legacy.json) · labels `d40bc2954450` ·
model `gpt-4o-mini`, temperature 0.3 · code `4126767` (as delivered) · 2026-10-29

| Quote | ok | vendor | vat_id | grand_total | lines | commodity |
|---|---|---|---|---|---|---|
| QT-4120-Cust-14918 (Greenmantle) | 3/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 |
| QT-OF2312380-Cust-57692 (verdeform) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| QuoteA0492_23 (Hollis) | 3/3 | 0/3 | 3/3 | 1/3 | 0/3 | 3/3 |
| Quote_1 MacBook Air (Apple) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| Hartwell grinding machine | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| **All runs** | **60%** | **20%** | **60%** | **47%** | **20%** | **60%** |

Latency: p50 4.7 s, max 16.3 s.

What failed and why:
- **verdeform, Hartwell: upload errors out (0/3).** The model correctly returns `null` for a tax ID
  that isn't readable (verdeform: only in the page image) or doesn't exist (Hartwell), and the
  `vat_id: str` schema rejects it, failing the whole extraction.
- **Vendor/customer swapped (Greenmantle, Hollis).** Vendor comes back as the recipient,
  "Lio Technologies, Inc."; the real vendor lands in `department`, which the prompt defines as
  "Customer/Bill To".
- **Alternatives counted as lines (Greenmantle, Hollis).** The $430 vertical-logo alternative and
  Hollis's $2,090 / $1,830 alternatives are extracted as order lines; Hollis's total comes back as
  $4,020 in 2 of 3 runs.
- Not yet scored (labels to be extended): department, quantities, discounts, subtotal, shipping,
  tax. Example: Greenmantle's moss panel comes back as 2 × $894.08 = $715.26 (really 1 × $894.08
  at −20%).

---

## After: new pipeline

*Pending.*

## Model comparison

*Pending. Same pipeline and labels, `OPENAI_MODEL` varied. Default stays `gpt-4o-mini` unless a
model clearly beats it without hurting upload latency.*
