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

Extended fields, scored only for quotes whose label has an `extended` block (shown as "-"
otherwise and left out of the totals). Labels are extended quote by quote as each is reviewed.

| Field | Passes when |
|---|---|
| department | matches the expected department; stays empty when the quote names none |
| line_detail | every expected order line (items only) is present with the right quantity and net unit price |
| charges | `shippingAmount` and `feesAmount` match the quote |
| tax | `taxAmount` matches the quote's total tax |
| reconciles | the extraction is internally consistent: lines + shipping + fees + tax = total cost |
| flagged | no silent errors: either every field above passes, or the response carries a warning |

Reproduce:

```bash
python3 backend/evals/run_eval.py --runs 3                                        # live run
python3 backend/evals/run_eval.py --rescore backend/evals/results/baseline-legacy.json   # offline re-score
```

Saved runs keep the raw API responses, so any run can be re-scored when the labels change.
Numbers in this file are always computed against the labels hash shown in each section.

---

## Baseline: original pipeline

File: [`results/baseline-legacy.json`](results/baseline-legacy.json) · model `gpt-4o-mini`,
temperature 0.3 · code `4126767` (as delivered) · run 2026-10-29 · originally scored against labels
`d40bc2954450`, re-scored below against labels `2d6710a00232` (QT-4120 extended)

| Quote | ok | vendor | vat_id | grand_total | lines | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QT-4120-Cust-14918 (Greenmantle) | 3/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| QT-OF2312380-Cust-57692 (verdeform) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | - | - | - | - | - | - |
| QuoteA0492_23 (Hollis) | 3/3 | 0/3 | 3/3 | 1/3 | 0/3 | 3/3 | - | - | - | - | - | - |
| Quote_1 MacBook Air (Apple) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | - | - | - | - | - | - |
| Hartwell grinding machine | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | - | - | - | - | - | - |
| **All runs** | **60%** | **20%** | **60%** | **47%** | **20%** | **60%** | **0%** | **0%** | **0%** | **0%** | **0%** | **0%** |

Latency: p50 4.7 s, max 16.3 s. Extended-field percentages cover QT-4120 only so far.

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
- **QT-4120 extended fields, all 0/3:** department holds the vendor's name; the moss panel comes
  back as 2 × $894.08 = $715.26 (really 1 × $894.08 at −20%); shipping and tax aren't captured;
  the lines ($1,767.26) contradict the total ($1,686.14); and none of it is flagged
  (`missingFields` is empty, so the UI says "extracted successfully").

---

## After: new pipeline (QT-4120 fixes)

File: [`results/after-qt4120-pdf-gpt-4o-mini.json`](results/after-qt4120-pdf-gpt-4o-mini.json) ·
labels `2d6710a00232` (same as the re-scored baseline) · model `gpt-4o-mini`, temperature 0 ·
`POST /extraction/pdf` (layout text + page images + checks in code; order lines are items only,
shipping/fees/tax in the cost breakdown) · base `a8c6f46` + working tree · 2026-10-29

| Quote | ok | vendor | vat_id | grand_total | lines | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QT-4120-Cust-14918 (Greenmantle) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| QT-OF2312380-Cust-57692 (verdeform) | 3/3 | 0/3 | 0/3 | 3/3 | 3/3 | 0/3 | - | - | - | - | - | - |
| QuoteA0492_23 (Hollis) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 1/3 | - | - | - | - | - | - |
| Quote_1 MacBook Air (Apple) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | - | - | - | - | - | - |
| Hartwell grinding machine | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | - | - | - | - | - | - |
| **All runs** | **100%** | **80%** | **80%** | **100%** | **100%** | **47%** | **100%** | **100%** | **100%** | **100%** | **100%** | **100%** |

Latency: p50 5.6 s, max 8.6 s (baseline p50 4.7 s); no self-correction retry needed in any of
the 15 runs. ~77k prompt tokens per call: page images plus the full 2,000-group commodity list.

### QT-4120 stability: 10 runs

File: [`results/qt4120-stability-10x.json`](results/qt4120-stability-10x.json) · same code and
labels as above · 2026-10-29

All 12 fields passed 10/10; status "verified" every run; 0 self-correction retries; latency
p50 5.1 s, max 5.8 s.

### Before → after (all runs)

| | ok | vendor | vat_id | grand_total | lines | commodity | QT-4120 extended (6 fields) |
|---|---|---|---|---|---|---|---|
| Baseline | 60% | 20% | 60% | 47% | 20% | 60% | 0% each |
| After | **100%** | **80%** | **80%** | **100%** | **100%** | 47% | **100% each** |

What the iterations showed (each fix is a test in `tests/test_extraction.py`):
1. First version: shipping in the totals section was dropped in 2 of 3 runs (no slot for it).
2. Separate `charges` field: tax rows were filed as fees and the result looked "verified", a
   silent error that only the `flagged` metric caught.
3. One `totals` list mirroring the printed rows, plus a tax-label backstop: correct, but the first
   pass counted the $430 alternative in 5 of 5 runs and needed the retry (~12 s).
4. Code applies the printed cues (a priceless row is a heading; "Alternative…" headings and
   "(Alt.)" markers exclude rows): retry needed in 1 of 5 runs, p50 6.4 s on QT-4120.
5. Shipping and fees moved from order lines into the cost breakdown (product decision, D9):
   all QT-4120 extraction fields still 3/3, no retries.
6. Commodity prompt changed from "null if unsure" to "always pick the closest group": QT-4120
   back to 3/3 (Office Equipment); overall commodity 40% → 47%.

Open (next quotes to review / Task 3):
- **verdeform: vendor comes back as "Lio Technologies, Inc." with no warning**, and the tax ID as
  `C4185275` (the California corporation number). Was a crash before; now silently wrong.
- **Commodity is still weak (47%):** with "always pick the closest", verdeform (3/3) and Hollis
  (2/3) now fall back to the catch-all "9 Miscellaneous Services" instead of 15 Office Equipment,
  and Hartwell still returns no group (it should be 45 Production Machinery; no invalid ids were
  logged, so the model returns null despite the instruction). Picking 1 of 2,000 near-duplicate
  groups in one prompt is the root cause. Task 3 redesigns classification (shortlist, then pick).

## Model comparison

*Pending. Same pipeline and labels, `OPENAI_MODEL` varied. Default stays `gpt-4o-mini` unless a
model clearly beats it without hurting upload latency.*
