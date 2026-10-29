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

---

## Hollis quote (QuoteA0492_23): labels extended + shipping-row fix

Labels `1929ec075603`: lines = the $1,560 panel only (the $320 transport row is now a forbidden
line), shipping $320, fees $0, tax $162.15, department empty. Code change: pure shipping rows
typed as items move to the cost breakdown (DECISIONS D42).

| Run | lines | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|---|
| After verdeform round, re-scored | 0/3 (transport as a line) | 0/3 (no group) | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 |
| Live, after D42 (3 runs, not kept) | **3/3** | 3/3 (15) | 2/3 | 3/3 | **3/3** | 3/3 | 3/3 | 2/3 |
| Live, D42 + person-title guard ([`results/hollis-pdf-gpt-4o-mini.json`](results/hollis-pdf-gpt-4o-mini.json), 5 runs) | 5/5 | 0/5 (9 ×4, none ×1) | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 | 1/5 |

After D42 the department was the contact person "Mr. Vladimir Keil" in 1/3 runs; with a guard
against personal titles it was the text "null" in 1/5. Department extraction was then dropped
(D43); see the next section. Hartwell re-run after D42: unchanged, "Delivery and installation"
still an order line 3/3.

---

## Department dropped from extraction (D43): all five quotes

Labels `f29590c94bec` (Hartwell department now expected empty). Schema and prompt no longer ask for a
department; it comes from the requester's profile only.

### Regression: all five quotes, 3 runs

File: [`results/after-hollis-pdf-gpt-4o-mini.json`](results/after-hollis-pdf-gpt-4o-mini.json)

| Quote | ok | vendor | vat_id | grand_total | lines | commodity | department | line_detail | charges | tax | reconciles | flagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QT-4120-Cust-14918 (Greenmantle) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| QT-OF2312380-Cust-57692 (verdeform) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 2/3 |
| QuoteA0492_23 (Hollis) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| Quote_1 MacBook Air (Apple) | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| Hartwell grinding machine | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| **All runs** | **100%** | **100%** | **100%** | **100%** | **100%** | **73%** | **100%** | **100%** | **100%** | **100%** | **100%** | **93%** |

Latency p50 7.1 s, max 10.3 s; no retries in 15 runs. First run where every extraction field
passes on every quote. Commodity: Hartwell 15 Office Equipment instead of 45 (3/3, silent;
`flagged` passes only via the unrelated "Tax ID" missing note, D5b), verdeform 9 once.

### Verdeform: 10 runs

File: [`results/verdeform-stability-10x-after-d43.json`](results/verdeform-stability-10x-after-d43.json)

| | Before D43 (verdeform round) | After D43 |
|---|---|---|
| vendor "Bloomcraft Interiors, Inc." | 2/10 | **8/10** (2/10 "verdeform") |
| vat_id 27-1073640 | 1/10 | **8/10** |
| commodity | 7/10 | 6/10 |
| retries | 9/10 | **3/10** |
| latency | p50 14.3 s, max 20.2 s | p50 7.5 s, max 16.4 s |

Dropping one ambiguous field from the schema left the model attention for the image-only
footer, consistent with the diagnosis in the verdeform round.

---

## Where extraction stands (after D43)

Every extraction field passes on all five quotes (3 runs each) except the commodity group
(73%); verdeform's legal name and tax ID are 8/10 over 10 runs (the other runs return the brand
"verdeform" and flag the tax ID as missing). No retries; ~7 s per upload.

Known limitations:
- **Commodity group** is unstable across prompt changes, and a wrong group is pre-selected
  without a warning (Hartwell: 15 Office Equipment instead of 45). Addressed in Task 3.
- **"Verified"** is shown even when the commodity group is missing or a guess.
- **Inferred legal names:** when a quote prints no legal entity, the vendor is the model's
  inferred legal name ("Apple Inc."); for an unknown vendor this could be invented.
- **Small benchmark:** five documents; title, units and estimated amounts aren't scored; the
  `flagged` metric credits any warning, even an unrelated one.
- **Not tested:** scanned PDFs without a text layer, quotes longer than four pages, non-USD
  currencies, instructions embedded in a document.
- **Not modeled:** fee names (stored as a single fees amount), estimated tax/shipping, quote
  validity dates.

---

## Catalog suggestions (Task 2)

Benchmark: [`matching_labels.json`](matching_labels.json), written before the matcher: nine
request lines against Acme's catalog (1,920 articles, 393 distinct items): the three moss-wall
quotes, the MacBook, Hartwell's grinding machine and installation, and typed "usb-c docking
station", "cyan toner" and "zip ties". Four must get *no* suggestion; a wrong suggestion is
worse than none.

| Metric | Passes when |
|---|---|
| hit | an expected catalog item is among the suggestions |
| top1 | the first suggestion is an expected item |
| clean | a "nothing fits" case gets no suggestion |

Reproduce: `python3 backend/evals/run_match_eval.py --runs 3`

| Iteration | Path | hit | top1 | clean | latency |
|---|---|---|---|---|---|
| First run (2 runs) | model-checked | 12/12 | 12/12 | 4/6 (zip ties → steel bolts, PET strapping) | p50 1.4 s |
| | typeahead | 12/12 | 12/12 | 2/6 | 0.1 s |
| Calibrated typeahead thresholds | typeahead | 18/18 | 18/18 | **9/9** | 0.1 s |
| | model-checked | 18/18 | 18/18 | 6/9 (zip ties → 8 "similar" items, every reason a rejection) | |
| Judge gets a `not_a_match` verdict ([`results/match-gpt-4o-mini.json`](results/match-gpt-4o-mini.json), 3 runs) | model-checked | **18/18** | **18/18** | **9/9** | p50 2.4 s, max 3.1 s |
| | typeahead | 18/18 | 18/18 | 9/9 | 0.1 s |

What the iterations showed:
- The typeahead has no model check, so it needs a threshold: correct items scored 0.51–0.75
  cosine, the best candidate for "nothing fits" cases 0.41–0.48; the cut is 0.50, plus a keyword
  rule that needs two shared words ("Delivery and installation" shares one with "Last-mile
  delivery"). A thin margin on a small sample.
- With only "equivalent | similar" to choose from, the model labelled its rejections "similar"
  ("Different product type (bolt vs zip ties) and purpose"). Giving it a "not_a_match" verdict
  fixed it.

End to end through the API (upload → match → use agreement → create request):
- verdeform: 13.78 sq ft of custom moss at $52.00 → Harborview Facility's negotiated $44.59/sq ft,
  saving $102.11; the edge-greening line matches too but is per linear foot, so no saving is
  computed; the acrylic logo gets no suggestion.
- MacBook Air at $1,409.06 → Granite Solutions' "Business laptop 14″ i5 / 16 GB / 512 GB" at
  $974 (similar: a different platform, for a person to decide), saving $435.06.
- The created requests use the supplier as vendor and store the article link and the negotiated
  price at the time.

Known limitations: nine cases on one synthetic catalog; the catalog's `quantity` column is shown
but not enforced (its meaning is unconfirmed); the typeahead threshold will need recalibrating on
a real catalog.

Using an agreement that switches the vendor resets shipping, fees and tax to $0 with a note:
the catalog has no shipping, fee or tax data, and the original quote's charges belong to another
vendor. Until someone enters them, the total understates the real cost.

### Badges: decided in code, now measured (work in progress)

The first Task 2 version had two badges, "equivalent" and "similar". "Similar" covered both a
near-identical dock and a Windows laptop for a MacBook, and the eval never checked badges. Now
the model answers a fixed checklist per candidate (product type, platform, size, key specs,
custom vs standard, material/variant); code sets `equivalent` (no differences), `close` (only
minor) or `alternative` (any major); and the UI shows the main difference in the badge
("Alternative · platform: Windows vs macOS"). The labels gained an expected badge per item;
the eval scores `label` (allowed badge) and `stable` (same badge every run).

| Version (9 cases × 3 runs) | hit | top1 | clean | allowed badge | stable | p50 |
|---|---|---|---|---|---|---|
| Equivalent / similar (committed Task 2) | 18/18 | 18/18 | 9/9 | not measured | not measured | 2.4 s |
| Free-form list of differences | 12/18 | 12/18 | 9/9 | 6/18 | 6/6 | 2.3 s |
| Fixed checklist | 15/18 | 13/18 | 9/9 | 23/32 | 12/12 | 5.1 s |
| + one model call per line | 15/18 | 12/18 | 9/9 | 22/28 | 10/10 | 5.7 s |
| + Windows laptops kept for a MacBook ([`results/match-labels-gpt-4o-mini.json`](results/match-labels-gpt-4o-mini.json)) | **18/18** | 15/18 | **9/9** | 36/45 | **15/15** | 6.5 s |

What this showed:
- A free-form list of differences is filled lazily (the MacBook got "13″ vs 14″" but never the
  platform). A checklist makes differences consistent, but the model then dropped items with
  major differences instead of labelling them alternatives; Windows laptops for a MacBook are
  now kept explicitly (a product decision).
- One model call for all lines hit the output-token limit at 5 lines with the checklist, which
  in the app silently falls back to unverified keywords; the eval missed it because each case
  is a single line. Each line now gets its own call, in parallel (6 lines verified in 7.7 s).
- Still wrong in the latest run: "cyan toner" also got yellow, magenta and black toner as
  "equivalent" (colour not treated as a difference; an earlier run was correct), so badge
  accuracy varies run to run with gpt-4o-mini. Next step under consideration: a stronger model
  for this small judge call only, measured on the same eval.
- Savings are still shown for alternatives ("save $435.06" against a Windows laptop).

## Model comparison

*Pending. Same pipeline and labels, `OPENAI_MODEL` varied. Default stays `gpt-4o-mini` unless a
model clearly beats it without hurting upload latency.*
