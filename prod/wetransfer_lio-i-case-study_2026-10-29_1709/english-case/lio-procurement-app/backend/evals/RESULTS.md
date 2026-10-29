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
`d40bc2954450`, re-scored below against labels `582e12d1a29c` (QT-4120 and verdeform extended)

| Quote | ok | vendor | vat_id | grand_total | lines | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QT-4120-Cust-14918 (Greenmantle) | 3/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| QT-OF2312380-Cust-57692 (verdeform) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| QuoteA0492_23 (Hollis) | 3/3 | 0/3 | 3/3 | 1/3 | 0/3 | 3/3 | - | - | - | - | - | - |
| Quote_1 MacBook Air (Apple) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | - | - | - | - | - | - |
| Hartwell grinding machine | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | - | - | - | - | - | - |
| **All runs** | **60%** | **20%** | **60%** | **47%** | **20%** | **60%** | **0%** | **0%** | **0%** | **0%** | **0%** | **0%** |

Latency: p50 4.7 s, max 16.3 s. Extended-field percentages cover QT-4120 and verdeform.

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

At the time of this run, open items were the verdeform vendor (silently "Lio Technologies, Inc.")
and commodity (47%). See the verdeform round below for the current state.

---

## Verdeform round (QT-OF2312380)

Changes: verdeform labels extended (legal-entity vendor name, fractional quantities, shipping,
tax, the $79 "Moss Duo" upsell as a forbidden line); buyer identities in the prompt and a
`vendor_is_buyer` guard (D29/D30); tax ID chosen by printed label from `registration_ids` (D32);
an evidence-first schema field (D33, see below). Labels `582e12d1a29c`.

### Verdeform: 10 runs

File: [`results/verdeform-stability-10x.json`](results/verdeform-stability-10x.json) · 2026-10-29

| | Before (latest QT-4120 run) | After |
|---|---|---|
| vendor (legal entity) | 0/3: "Lio Technologies, Inc." (the buyer), **silently** | 2/10 "Bloomcraft Interiors, Inc."; 8/10 "verdeform" (right company, brand name); 0/10 the buyer |
| vat_id | 0/3 | 1/10; otherwise empty and listed as missing |
| department, lines (fractional qty), charges, tax, reconciles | not scored | 10/10 each |
| flagged (no silent errors) | not scored | 10/10 |
| commodity | 0/3 | 7/10 |
| retries | 0 | 9/10 (first pass names the buyer as vendor; the guard catches it) |
| latency | p50 5.6 s | p50 14.3 s, max 20.2 s |

### Regression: all five quotes, 3 runs

File: [`results/after-verdeform-pdf-gpt-4o-mini.json`](results/after-verdeform-pdf-gpt-4o-mini.json)
· base `8645bfc` + working tree

| Quote | ok | vendor | vat_id | grand_total | lines | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QT-4120-Cust-14918 (Greenmantle) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| QT-OF2312380-Cust-57692 (verdeform) | 3/3 | 0/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| QuoteA0492_23 (Hollis) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | - | - | - | - | - | - |
| Quote_1 MacBook Air (Apple) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | - | - | - | - | - | - |
| Hartwell grinding machine | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | - | - | - | - | - | - |
| **All runs** | **100%** | **80%** | **80%** | **100%** | **100%** | **20%** | **100%** | **100%** | **100%** | **100%** | **100%** | **100%** |

Latency p50 7.9 s, max 20.9 s; 3 retries in 15 runs (all verdeform). QT-4120 unchanged at 3/3.
Commodity dropped again (MacBook 29 Hardware → 30 IT Services; Hollis and Hartwell mostly no
group): it varies with any prompt change, which is the Task 3 problem.

### Diagnosis (probes, no code change)

1. *Can the model read the footer?* Yes: asked only "who issued this, and what's the EIN?" on
   the same 150 DPI page image, it answered "Bloomcraft Interiors, Inc., EIN 27-1073640" (also
   with zoomed, contrast-enhanced header/footer crops at ~3× the tokens).
2. *Is the 2,000-group commodity list crowding it out?* No: with a 4-group list the first pass
   still named the buyer as vendor, 3/3.
3. *Does reading first help (evidence field before `vendor`)?* Not reliably: 3/3 in the first
   probe, then 0/8 in the service and 1/10 in the eval. The evidence field copies the text layer
   (plus the image-only sender line) and stops before the footer, and even when it contains
   "Bloomcraft Interiors, Inc." the model still sets vendor = the buyer.
4. **Conclusion:** in the large extraction call, gpt-4o-mini doesn't attend to image-only footer
   text. A focused question on the same image works. Proposed next step: a separate, parallel
   issuer call (DECISIONS D35, open).

Open:
- **verdeform tax ID and legal name** (D35).
- **Commodity (20–47%, unstable):** Task 3 redesigns classification (shortlist, then pick).

---

## MacBook Air quote (Quote_1): labels extended

Labels `9afdc4ca0758`: vendor must be "Apple Inc" (inferred legal name, DECISIONS D37; was any
name containing "Apple"), plus department, the one line, shipping $0, fees $4.00, tax $121.53.
No code change; saved runs re-scored offline.

| Saved run | vendor | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|---|
| Baseline | 0/3 ("Apple Business Team") | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| After QT-4120 fixes | 0/3 ("Apple") | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 |
| After verdeform round | **3/3** ("Apple Inc.") | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 |

`flagged` is 0/3 in every run because one field is wrong without a warning: the vendor name
before D37, the commodity group (30 IT Services instead of 29 Hardware) after. Commodity errors
are silent today (Task 3).

---

## Hartwell grinding machine: labels extended + department fix

Labels `8e25d0bef460`: department "Purchasing / Engineering" (exact match now), both lines
incl. "Delivery and installation" as an order line (D38), shipping $0, fees $0, tax $1,402.50.
Code change: department = requester's profile first, then the "Attn:" line with the prefix
stripped (D39).

| Run | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|
| After verdeform round, re-scored | 0/3 | 0/3 ("Attn: Purchasing / Engineering") | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| Live, after D39 ([`results/hartwell-pdf-gpt-4o-mini.json`](results/hartwell-pdf-gpt-4o-mini.json)) | 0/3 (15 Office Equipment) | **3/3** | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |

All base fields 3/3; latency 5.0 s; no retries. Caveat: `flagged` passes only because an
unrelated missing-field note ("Tax ID", correctly absent) is present while the commodity group is
silently wrong (DECISIONS D5b, known limitation).

## Model comparison

*Pending. Same pipeline and labels, `OPENAI_MODEL` varied. Default stays `gpt-4o-mini` unless a
model clearly beats it without hurting upload latency.*
