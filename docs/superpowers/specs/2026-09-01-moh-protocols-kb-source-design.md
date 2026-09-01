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

31 sources · **1,638 clauses** (measured on the shipped `chunk_moh`, four heading rules
included) · index grows 3,017 → 4,655 (**+54%**). Every source clears `MIN_SOURCE_CLAUSES=5`
and `MIN_SOURCE_CHARS=1000`, so `build_kb` stays loud-on-failure with no floor changes.

### Role A — third authority for existing requirement entries (11)

| `source_id` | File | Clauses | Maps to |
| --- | --- | --- | --- |
| `MOH-DM` | `Saudi-Diabetes-Clinical-Practice-Guidelines.pdf` | 389 | `diabetes-mellitus` |
| `MOH-SEPSIS-MAT` | `Maternal-Sepsis-Management.pdf` | 71 | `sepsis` |
| `MOH-PN-ADULT` | `Adult-Parenteral-Nutrition-CPG.pdf` | 52 | `malnutrition` |
| `MOH-MENINGITIS` | `Acute-CNS-Infections-Meningitis-Adults.pdf` | 30 | `meningitis` |
| `MOH-IAI` | `Intra-abdominal-Infections-Treatment.pdf` | 27 | `appendicitis` (adjacent) |
| `MOH-HD` | `Home-Hemodialysis-Complications.pdf` | 27 | `chronic-kidney-disease` |
| `MOH-LRTI` | `Lower-Respiratory-Tract-Infections.pdf` | 19 | `pneumonia` |
| `MOH-SEPSIS-PED` | `Pediatric-Sepsis-Management.pdf` | 19 | `sepsis` |
| `MOH-UTI` | `Urinary-Tract-Infection.pdf` | 17 | `urinary-tract-infection` |
| `MOH-SSI` | `Surgical-Site-Infections-Guidelines.pdf` | 16 | `surgical-wound-infection` |
| `MOH-SSTI` | `Skin-and-Soft-Tissue-Infection.pdf` | 12 | new (`skin and soft tissue infection`) |

### Role B — candidates for new condition entries (13)

`MOH-DKA` (84), `MOH-DKA-PED` (81), `MOH-VTE` (71), `MOH-FH` (57), `MOH-RA` (63),
`MOH-HIE` (43), `MOH-MDD` (37), `MOH-HYPOGLYCEMIA` (30), `MOH-HEADACHE` (29),
`MOH-DVT` (27), `MOH-PE` (21), `MOH-GAS` (18), `MOH-ANAPHYLAXIS` (16).

### Role C — candidates for necessity / order rules (7)

`MOH-CONTRAST` (200), `MOH-WARFARIN` (61), `MOH-TDM-VANCO` (51), `MOH-ANTICOAG-REV` (20),
`MOH-ABX-PROPH` (22), `MOH-ALBUMIN` (14), `MOH-SUP` (14).

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

Measured (re-measured 2026-09-01, applying vanilla `chunk_chi` — no MOH rules at all — to
the curated 31): **161 / 1,616 clauses (10.0%)** carry a bullet-, glossary-, or date-shaped
title. The damage still concentrates unevenly across protocols, topped by `MOH-SSI` (46.7%),
`MOH-ANAPHYLAXIS` (37.5%), `MOH-LRTI` (31.6%), `MOH-IAI` (28.6%) and `MOH-DKA` (28.0%). (The
original survey's 270/16.7% and per-protocol figures do not reproduce against the current
extraction cache and curated-31 registration; treat the numbers above as authoritative.)

### The fix

New module `src/cdi_kb/moh_chunker.py` exposing `chunk_moh(pages, source) -> list[Clause]`,
which adds three heading rejectors (below) plus one narrow acceptor (§2a) and otherwise
reuses the proven CHI segment loop. Each rejector was tuned against the real corpus and
**verified to reject only junk** (occurrence counts across the curated 31, restricted to
lines the base CHI `_is_heading` gate would otherwise have accepted as a title — i.e. the
candidates each rejector is actually saving from becoming a 5×-weighted `section_title`):

- `_is_bullet_item(line)` — line begins with a bullet glyph (`•`, `●`, `▪`),
  the `�` (U+FFFD) fallback some Wingdings bullets decode to, or any codepoint in the
  Wingdings/Symbol Private Use Area block **U+F000–U+F0FF** (enumerating individual glyphs
  missed others from the same font-private block, so the rejector covers the whole block
  rather than a fixed list). **122 occurrences, all list items**, no real heading among them.
- `_is_abbreviation_gloss(line)` — matches `^(?P<lhs>[^:]{1,28}):\s+\S` **and** `lhs` is
  ≥60% uppercase. **68 occurrences.** Most are genuine abbreviation definitions, but the
  set also contains a handful of cover-page and table fragments (a document-control stamp
  line, a PICO-table's `P:`/`I:`/`O:`/`H:` row labels, a bilingual `GENDER:` form field) —
  all correctly dropped, and no real section heading is among them either way.
- `_is_datestamp(line)` — contains a `D Month YYYY`, `Month D, YYYY`, or `D/M/YYYY` date.
  **17 occurrences, all stamps or reference access-dates.**

The uppercase-ratio condition on the glossary rejector is load-bearing and was added after
measurement: a bare `^[^:]{1,28}:\s+\S` pattern also rejects **real** headings the corpus
depends on — `Table 10: Treatment of Hypertriglyceridemia`, `Figure 1: Classification of DM`,
`Assessment: Patient's Profiling`, `Setup: Inpatient setting`. Requiring an
abbreviation-shaped left-hand side separates `IV:` and `MRSA:` from `Assessment:` and
`Table 10:` cleanly, with no false rejection observed.

### 2a. The narrow acceptor — `_is_colon_heading`

The three rejectors above only ever turn an `_is_heading`-accepted line into a rejection. MOH
protocols also favor short, mostly-lowercase-word, colon-terminated section labels ("Aim and
scope:", "Targeted population:", "References:") that the CHI capitalization gate (≥60% of
words capitalized) never accepts as a heading in the first place — a 1-of-3-capitalized label
like "Aim and scope:" fails that gate outright, so no rejector could ever touch it either; it
would fall permanently into the *previous* section's body text instead. `_is_colon_heading` is
an acceptor, not a rejector: it runs only when `_is_heading` has already said no, and only
admits a line that ends with `:`, is ≤60 characters, is not furniture or letter-spaced, and
starts with an uppercase letter.

That last check — `stripped[0].isupper()` — is the real discriminator, not a word-count
minimum. `_COLON_HEADING_MIN_WORDS` shipped at 2, from a measurement that could not see what
it excluded: its candidate population required ≥2 alphabetic words *by construction*, so
single-word labels like "References:" never entered the sample. Corrected to 1, re-measured
against the curated 31 (colon-terminated, ≤60-char lines not already accepted by
`_is_heading`): population 500 occurrences / 367 distinct, of which the acceptor admits 328 /
214 and still drops 172 / 153 — dominated by mid-sentence and list-continuation fragments
("fluoroquinolone prophylaxis:", "the following:", "1st line:", "- Pediatric:",
"2.Monitoring:") whose lowercase, dash-, or digit-led first character keeps them out
regardless of the word-count minimum. The cost of dropping the minimum to 1 is 4 occurrences
of form-field junk ("Patient:" ×2, "MRN:" ×2) admitted alongside ~149 real single-word labels
("References:", "Methodology:", "Introduction:", "Funding:", "Investigations:", "Purpose:",
and others) that the width-2 minimum had been discarding.

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

The three rejectors do **not** clear every bad title. This population is the one admitted via
the base CHI `_is_heading` gate specifically (not via the §2a colon acceptor, which is a
separate admission stream measured on its own terms above) — on the shipped `chunk_moh` output,
**209 colon-terminated `section_title`s** are admitted this way, and a minority of those are
table-cell or form-field fragments rather than headings — e.g. `Patient: MRN:` (2 occurrences,
still reproduces verbatim on the current corpus; the original survey's other two examples,
`CV effects: ASCVD Neutral Potential benefit: Neutral` and `Vital Signs: STAT Then
every__________`, no longer appear verbatim after re-segmentation and are presumed superseded
by similar fragments elsewhere). They come from tables that `pdfplumber` linearizes row-wise,
and separating them from real headings needs layout geometry the text layer does not carry.
They are left in deliberately rather than removed by a broader pattern that would take real
headings with them: an over-broad rejector loses a real section title permanently, while a
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
- **`llm_infer.CANDIDATE_LIMIT`** — silent in the original draft, but ingestion required a code
  change here too. Same-condition MOH clauses (MOH-UTI, MOH-SSI, MOH-SEPSIS-MAT, MOH-ABX-PROPH,
  MOH-IAI) share enough infection/agent/site vocabulary with the CDI-2021 booklet's own
  specificity clauses to push the previously-cited clause out of the fixed-size top-K BM25
  window, so `retrieve_candidates` stopped reaching 3 requirement axes. `CANDIDATE_LIMIT` was
  doubled from 16 to 32 to restore them; reachability was swept at 8/16/24/32/40/48/64 and
  plateaus at 57/65 axes from 32 onward (48/65 at 8, 54/65 at 16, 56/65 at 24, no further gain
  past 32) — 32 is the measured plateau, not a round-number guess.

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

### Outcome (recorded post-ingestion)

The guard tripped: `title_reachable_entries` moved 5 → 7 and `mandate_anchored_entries` moved
0 → 1. Diagnosis, not silent absorption: `cli verify` still reports `VERIFICATION PASSED`
throughout, because both stats are V3's own *named* fallback tiers (title-query reachability,
mandate-clause anchoring) doing exactly what they exist for — the larger, richer index pushed
a handful of cited CHI/booklet sections out of the standard query's top-5, and V3 fell back to
a named, visible query to keep confirming those citations are real, rather than either failing
loudly or absorbing the movement invisibly. No citation went unverified; the *route* to
verifying it changed.

Per the "not something to re-baseline silently" line above, this was **not** re-baselined
silently: it was surfaced, and the thresholds in
`test_moh_ingestion_does_not_worsen_retrieval_fallbacks` were explicitly re-baselined to
`title_reachable_entries <= 7` / `mandate_anchored_entries <= 1` by user decision, once. That
test's own comment records the before/after numbers and states plainly that the guard's
purpose is to catch *future* growth beyond this one approved movement — a second trip is a
real finding to investigate, not a second re-baseline.

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
| Retrieval dilution from +54% index growth | Explicit before/after guard on `title_reachable_entries` (§5); the guard tripped (5→7, mandate-anchored 0→1), was diagnosed as V3's own named fallback tiers absorbing the richer index with `cli verify` still PASSING throughout, and the thresholds were re-baselined to `<=7`/`<=1` once, by explicit user decision, not silently |
| Heading heuristic still imperfect on unseen MOH layouts | `clause_id` is page-anchored, so citations stay stable regardless; V1 guarantees verbatim fidelity either way; a false-positive heading can only over-split a paragraph, never splice text (existing `chi_chunker` invariant, inherited) |
| The shared-code edit to `chi_chunker.py` collides with concurrent sessions | Single keyword-only signature line, applied as an assert-guarded line edit, plus test #4 pinning byte-identical CHI output |
| First extraction of 31 PDFs is slow | Cached under `var/raw_text/` by the existing settings-keyed cache; already warmed by the survey probes; `build_kb` prints per-source progress |
| 31 new sources make `config.py` unwieldy | MOH sources built by a comprehension over a `(source_id, filename, title)` table rather than 31 hand-written `SourceDoc(...)` calls, keeping the registry readable |
| `MOH_Protocols/` is gitignored (`*.pdf`) | Same posture as `CHI_Guidelines/`: the tracked artifacts are `moh_download.py`, `links.tsv`, and `manifest.csv` (with per-file SHA-256), so the corpus is reproducible from a clean checkout |
