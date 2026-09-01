# MOH_Protocols as a Third KB Authority — Design

**Date:** 2026-09-01 · **Status:** Approved by user (curated-31 scope + authority ordering + ingestion-only first slice, 2026-09-01 conversation)
**Extends:** `docs/superpowers/specs/2026-08-30-doctype-chi-necessity-design.md` (multi-source registry, CHI prose chunker, V1–V5 contracts)

## Goals

1. MOH-KSA national clinical protocols become a **third citation authority** in the KB, alongside `CDI-2021` (TCC booklet) and the CHI guidelines.
2. Findings that draw on more than one authority cite **all** of them, ordered MOH → CHI → CDI-2021.
3. The ingestion is **verifiably faithful**: the full V1–V5 suite passes with MOH sources registered, and the retrieval dilution the new corpus causes is measured rather than absorbed silently.

## Non-Goals (this slice)

- **No rule YAMLs.** No `data/requirements`, `data/necessity`, or `data/doc_requirements` entries are authored here. See §6.
- OCR of the 4 image-only protocols; ingestion of the ~56 admin/policy and out-of-scope clinical PDFs; Arabic-language protocols; source-scoped or authority-weighted retrieval in `index.py` (not needed at the measured +54% growth — see §5).

## Corpus survey (measured, 2026-09-01)

Probes run over all 93 downloaded protocols using the current extraction settings
(`TEXT_EXTRACTION_KWARGS = {"x_tolerance_ratio": 0.15}`) and the current CHI prose chunker:

| Measure | Value |
| --- | --- |
| PDFs downloaded (`MOH_Protocols/manifest.csv`) | 93, all `status=downloaded`, 78.2 MB |
| Extract text successfully | 89 (4 yield 0 chars — image-only, need OCR) |
| Total pages | 2,172 |
| Clauses if all 93 were ingested | 6,201 |
| **V1 failures (clause text not verbatim in its own source)** | **0** |
| Median clauses/file | 33 |
| Median clause length | 344 chars |
| Files below `MIN_SOURCE_CLAUSES=5` (would hard-fail `build_kb`) | 6 |

The zero V1 failure count is the load-bearing result: the existing segment machinery is
already verbatim-safe on this corpus, so the ingestion work is about **retrieval quality**,
not extraction fidelity.

### Excluded, with reasons

- **Image-only (0 extracted chars)** — `High-Flow-Oxygen-Therapy-Adults`, `Respiratory-Equipment-Dispensing`, `Saudi-National-Malaria-Management`, `Saudi-Vestibular-Rehabilitation-Protocol`. Scanned; blocked pending OCR, exactly as `CHI-NEC-LBPMRI` is blocked pending VLM linearization.
- **Pure inventory tables** — `Emergency-Cart-Contents-Adults-Pediatrics` (3 clauses), `Crash-Cart-Items-2024` (4 clauses). Below the build floor, and no note-level documentation rule can cite a stock list.
- **Administrative / non-clinical-documentation policy** — compliance program, DNR policy, circumcision policy, breast-milk substitution, preventive home dental care, extemporaneous preparations, preprinted chemotherapy orders, and similar. They govern institutions, not the content of a clinical note.
- **Out-of-scope clinical** — remaining protocols (rehabilitation, ophthalmology, dermatology, most psychiatry) that neither map to an existing requirement entry nor are strong candidates for a near-term new one. Excluded from *this* pass only; nothing about the design prevents adding them later.

## 1. The curated 31 sources

31 sources · **1,616 clauses** · index grows 3,017 → 4,633 (**+54%**). Every source clears
`MIN_SOURCE_CLAUSES=5` and `MIN_SOURCE_CHARS=1000`, so `build_kb` stays loud-on-failure with
no floor changes.

### Role A — third authority for existing requirement entries (11)

| `source_id` | File | Clauses | Maps to |
| --- | --- | --- | --- |
| `MOH-DM` | `Saudi-Diabetes-Clinical-Practice-Guidelines.pdf` | 376 | `diabetes-mellitus` |
| `MOH-SEPSIS-MAT` | `Maternal-Sepsis-Management.pdf` | 73 | `sepsis` |
| `MOH-PN-ADULT` | `Adult-Parenteral-Nutrition-CPG.pdf` | 51 | `malnutrition` |
| `MOH-MENINGITIS` | `Acute-CNS-Infections-Meningitis-Adults.pdf` | 30 | `meningitis` |
| `MOH-IAI` | `Intra-abdominal-Infections-Treatment.pdf` | 28 | `appendicitis` (adjacent) |
| `MOH-HD` | `Home-Hemodialysis-Complications.pdf` | 26 | `chronic-kidney-disease` |
| `MOH-LRTI` | `Lower-Respiratory-Tract-Infections.pdf` | 19 | `pneumonia` |
| `MOH-SEPSIS-PED` | `Pediatric-Sepsis-Management.pdf` | 19 | `sepsis` |
| `MOH-UTI` | `Urinary-Tract-Infection.pdf` | 17 | `urinary-tract-infection` |
| `MOH-SSI` | `Surgical-Site-Infections-Guidelines.pdf` | 15 | `surgical-wound-infection` |
| `MOH-SSTI` | `Skin-and-Soft-Tissue-Infection.pdf` | 10 | new (`skin and soft tissue infection`) |

### Role B — candidates for new condition entries (13)

`MOH-DKA` (82), `MOH-DKA-PED` (82), `MOH-VTE` (69), `MOH-FH` (57), `MOH-RA` (55),
`MOH-HIE` (45), `MOH-MDD` (38), `MOH-HYPOGLYCEMIA` (30), `MOH-HEADACHE` (29),
`MOH-DVT` (27), `MOH-PE` (24), `MOH-GAS` (19), `MOH-ANAPHYLAXIS` (16).

### Role C — candidates for necessity / order rules (7)

`MOH-CONTRAST` (203), `MOH-WARFARIN` (60), `MOH-TDM-VANCO` (53), `MOH-ANTICOAG-REV` (19),
`MOH-ABX-PROPH` (15), `MOH-ALBUMIN` (15), `MOH-SUP` (14).

The role labels are **authoring intent for slice 2**, not a structural property. In
`config.SOURCES` every one of the 31 is an ordinary `SourceDoc` with `authority="MOH"` and
`genre="moh_protocol"`; nothing in the code branches on role.

## 2. Ingestion — the `moh_protocol` chunker genre

### The defect

V1 passes, but `section_title` quality does not — and `index.py` weights `section_title`
**5× body** in BM25. A junk title is therefore not cosmetic: it is a retrieval regression of
exactly the kind the CHI work already fixed once for journal running-headers (see the
`repeating_lines` comment in `chi_chunker.py`).

MOH protocols introduce three furniture genres the CHI heuristic does not reject:

1. **Bullet list items.** A bullet glyph followed by a short capitalised phrase
   (`• Perform ECG`, `• Enoxaparin 40mg SC once daily If CrCl < 30ml/min,`) is short,
   Title-Case, and has no terminal period, so `_is_heading` accepts it.
2. **Abbreviation glossary front matter.** Protocols open with an abbreviation table. Lines
   like `TMP/SMZ SS: Trimethoprim-sulfamethoxazole single strength`, `IV: Intravenous`, and
   `4.2 EN: Enteral nutrition` are accepted for the same reason. In `MOH-UTI` this makes an
   abbreviation the `section_title` of the *Introduction* paragraph.
3. **Date stamps.** Publication and revision stamps (`ISSUED DATE: 30/12/2021 update date
   23/11/2023 SN`, `City -Riyadh 15 Feb 2026`) and reference-list access dates
   (`Accessed 1 November 2019. Available from`). They escape `repeating_lines` because they
   are not reliably within the 2-line page edge the furniture detector samples.

Measured over the curated 31: **270 / 1,616 clauses (16.7%)** carry a bullet-, glossary-, or
date-shaped title, and the damage concentrates in the highest-value protocols — SSTI 60%,
`MOH-ABX-PROPH` 53%, GAS 47%, SSI 47%, LRTI 37%, UTI 35%.

### The fix

New module `src/cdi_kb/moh_chunker.py` exposing `chunk_moh(pages, source) -> list[Clause]`,
which adds three heading rejectors and otherwise reuses the proven CHI segment loop. Each was
tuned against the real corpus and **verified to reject only junk** (occurrence counts across
the curated 31):

- `_is_bullet_item(line)` — line begins with a bullet glyph (`•`, `●`, `▪`, and the
  `` / `�` forms the Wingdings bullets decode to). **110 occurrences, all list
  items**, no real heading among them.
- `_is_abbreviation_gloss(line)` — matches `^(?P<lhs>[^:]{1,28}):\s+\S` **and** `lhs` is
  ≥60% uppercase. **49 occurrences, all genuine abbreviation definitions.**
- `_is_datestamp(line)` — contains a `D Month YYYY`, `Month D, YYYY`, or `D/M/YYYY` date.
  **7 occurrences, all stamps or reference access-dates.**

The uppercase-ratio condition on the glossary rejector is load-bearing and was added after
measurement: a bare `^[^:]{1,28}:\s+\S` pattern also rejects **real** headings the corpus
depends on — `Table 10: Treatment of Hypertriglyceridemia`, `Figure 1: Classification of DM`,
`Assessment: Patient's Profiling`, `Setup: Inpatient setting`. Requiring an
abbreviation-shaped left-hand side separates `IV:` and `MRSA:` from `Assessment:` and
`Table 10:` cleanly, with no false rejection observed.

To reuse rather than duplicate the segment loop, `chi_chunker.chunk_chi` gains one
**additive, keyword-only** parameter:

```python
def chunk_chi(pages, source, *, is_heading=_is_heading) -> list[Clause]:
```

The default is the existing predicate, so every existing CHI source chunks bit-identically.
`chunk_moh` is then `chunk_chi(pages, source, is_heading=_is_moh_heading)`. This keeps the
edit to shared code to a single signature line — deliberate, because other sessions edit this
working tree concurrently and whole-file rewrites of shared modules lose their work.

`cli.build_kb` dispatches on `source.genre`: `"booklet"` → `chunk_booklet`,
`"moh_protocol"` → `chunk_moh`, everything else → `chunk_chi` (unchanged fallback).

`clause_id` stays page-anchored — `{SRC}/pg<page>/p<n>` — for the same reason it is for CHI:
citation stability must not depend on heading-detection quality.

### Residual, accepted — table fragments

The three rejectors do **not** clear every bad title. 88 colon-bearing heading occurrences
survive, and a minority of those are table-cell or form-field fragments rather than headings
— `CV effects: ASCVD Neutral Potential benefit: Neutral`, `Vital Signs: STAT Then
every__________`, `Patient: MRN:`. They come from tables that `pdfplumber` linearizes
row-wise, and separating them from real headings needs layout geometry the text layer does not
carry. They are left in deliberately rather than removed by a broader pattern that would take
real headings with them: an over-broad rejector loses a real section title permanently, while a
surviving table fragment only adds noise to one clause's 5×-weighted title. V1 fidelity and
citation stability are unaffected either way, because `clause_id` is page-anchored.

### Accepted limitation — undecoded bullet glyphs

2.3% of MOH clauses contain `�` where a Wingdings-style bullet glyph failed to decode.
It is confined to bullet markers, it is V1-safe (the clause text and the source text carry the
identical byte sequence, so the substring check holds), and quotes authored in slice 2 can
simply avoid those lines. `normalize()` is deliberately **not** changed: it is the comparison
function V1 and V2 both depend on, and altering it to paper over a cosmetic glyph would put the
entire fidelity guarantee at risk for no real gain.

## 3. Authority ordering

`config.py` gains:

```python
AUTHORITY_RANK: dict[str, int] = {"MOH": 0, "CHI": 1, "TCC": 2}
```

`findings._verified_citations()` — already documented as *"THE only citation-verification code
path"* — sorts its verified output by `AUTHORITY_RANK[SOURCES[source_id].authority]`, resolving
`source_id` from the clause_id prefix. Every composer (diagnosis, doc-type element, provider,
integrity, necessity, inferred) inherits the ordering with no per-composer change; the single
audited firewall stays single.

`VerifiedCitation` gains `authority: str` so CLI and web output can label which body a quote
comes from. It is a new field on a frozen dataclass, set at the one construction site inside the
firewall.

Sort must be **stable** on rank alone, so citations from the same authority keep their authored
YAML order — an author who lists a primary quote first should see it stay first.

## 4. Verification

- **V1** — no change needed. It is already per-source and already passes on all 6,201 probed clauses.
- **V2** — no change needed. MOH citations route through the same quote-match code as CHI once registered.
- **V3** — no change to the pass/fail contract. See §5 for the dilution guard.
- **V5** — the existing `sources` stat becomes 42 (11 + 31); per-source clause counts are emitted for MOH as they already are for CHI, via the existing `for source_id in config.SOURCES` loop (no code change; the stats dict grows automatically).

### New tests

1. **`test_config`** — the SOURCES registry contains exactly the expected 42 ids; every MOH path exists; every MOH source has `authority="MOH"` and `genre="moh_protocol"`.
2. **`test_moh_chunker`** — each of the three predicates rejects the real corpus lines it was written for (`• Perform ECG`, `TMP/SMZ SS: Trimethoprim-sulfamethoxazole single strength`, `ISSUED DATE: 30/12/2021 update date 23/11/2023 SN`) **and accepts the real headings that must survive** (`Table 10: Treatment of Hypertriglyceridemia`, `Figure 1: Classification of DM`, `Assessment: Patient's Profiling`, `Setup: Inpatient setting`, `Level of Evidence:`, `Medication Related Information`). The accept half is the half that matters: it pins the uppercase-ratio refinement that a naive glossary regex would have lost.
3. **`test_moh_chunker`** — across the curated MOH sources, **zero** clause `section_title`s are bullet-led, abbreviation-gloss, or date-stamped. Note the metric is the three *named* classes, not "no junk titles": the surviving table-cell fragments described under *Residual, accepted* are not covered, and asserting an unachievable 0 would only invite the assertion to be loosened later. This is the regression guard for the §2 fix; without it a heuristic change silently degrades 5×-weighted retrieval with every other test still green.
4. **`test_chi_chunker`** — chunking every existing CHI source through the new default-argument signature produces byte-identical clauses to the old call. Pins the "additive, no behaviour change" claim rather than asserting it.
5. **`test_kb_verification`** — `stats["sources"] == 42`; MOH per-source clause counts present and above the build floor.
6. **`test_findings`** — a finding whose requirement cites MOH, CHI, and CDI-2021 clauses returns them in that order; two citations from the same authority retain their authored order.

## 5. The retrieval-dilution risk, made visible

`verify.py` already reports a `title_reachable_entries` fallback tier whose stated cause is
*"index diluted by multi-source content"*. Growing the index +54% is precisely the operation
that grows that number. The honest failure mode is not a red test — it is MOH clauses quietly
displacing cited CHI/booklet sections out of top-5 while the fallback absorbs it and the suite
stays green.

Guard: capture `title_reachable_entries` and `mandate_anchored_entries` **before** the MOH
sources are registered, and assert after registration that neither has grown. If either does,
that is a real finding to report and resolve — by tuning retrieval or by narrowing the source
set — not something to re-baseline silently.

This is also why source-scoped retrieval is a non-goal: at +54% with this guard in place there
is no evidence it is needed. If the guard trips, that is the evidence, and it becomes slice 1b.

## 6. Why no rule YAMLs in this slice

The V2 contract requires every citation quote to string-match its clause at
`QUOTE_MATCH_THRESHOLD = 0.95`, and `requirements_model.py` states the rule directly: *"Never
hand-edit a quote: copy it from `cli.py quote` output so it is verbatim source text."*

`cli quote` reads the clause store. Until MOH clauses are **in** that store, authoring MOH-cited
rules means typing quotes by hand from a PDF viewer — the exact practice the discipline forbids,
and the one most likely to produce V2 failures that then get "fixed" by loosening the quote
rather than correcting it.

So slice 1 ends with MOH clauses stored, indexed, verified, and quotable. Slice 2 authors Role
A/B/C rules against real `cli quote` output, and gets its own plan.

## Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Retrieval dilution from +54% index growth | Explicit before/after guard on `title_reachable_entries` (§5); trips loudly rather than being absorbed |
| Heading heuristic still imperfect on unseen MOH layouts | `clause_id` is page-anchored, so citations stay stable regardless; V1 guarantees verbatim fidelity either way; a false-positive heading can only over-split a paragraph, never splice text (existing `chi_chunker` invariant, inherited) |
| The shared-code edit to `chi_chunker.py` collides with concurrent sessions | Single keyword-only signature line, applied as an assert-guarded line edit, plus test #4 pinning byte-identical CHI output |
| First extraction of 31 PDFs is slow | Cached under `var/raw_text/` by the existing settings-keyed cache; already warmed by the survey probes; `build_kb` prints per-source progress |
| 31 new sources make `config.py` unwieldy | MOH sources built by a comprehension over a `(source_id, filename, title)` table rather than 31 hand-written `SourceDoc(...)` calls, keeping the registry readable |
| `MOH_Protocols/` is gitignored (`*.pdf`) | Same posture as `CHI_Guidelines/`: the tracked artifacts are `moh_download.py`, `links.tsv`, and `manifest.csv` (with per-file SHA-256), so the corpus is reproducible from a clean checkout |
