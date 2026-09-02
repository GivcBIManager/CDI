# MOH_Protocols as a Third KB Authority — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest 31 curated MOH-KSA protocol PDFs into the CDI audit KB as a third citation authority, with V1–V5 verification green and the retrieval dilution measured.

**Architecture:** A new `moh_protocol` source genre. `chunk_chi` gains an injectable heading predicate (additive, default unchanged); `moh_chunker.chunk_moh` supplies a stricter predicate that rejects three MOH-specific furniture genres — bullet list items, abbreviation-glossary lines, and date stamps — that would otherwise become `section_title`s and be weighted 5× by FTS. The citation firewall in `findings.py` sorts verified citations MOH → CHI → CDI-2021.

**Tech Stack:** Python 3.13, pdfplumber, pydantic v2, SQLite FTS5, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-moh-protocols-kb-source-design.md`

## Global Constraints

- Python `>=3.13`. Run everything from the repo root `d:\CDI`.
- Tests: `python -m pytest` (config in `pyproject.toml`: `-m 'not live' --basetemp=var/pytest-tmp`, `testpaths = ["tests"]`).
- **Never hand-edit a citation quote.** Not applicable in this slice — no rule YAMLs are authored here (spec §6).
- **`clause_id` stays page-anchored**: `{SRC}/pg<page>/p<n>`. Never change an existing clause_id scheme.
- **Other sessions edit this working tree concurrently.** Use targeted line edits. Never rewrite a whole shared file (`chi_chunker.py`, `config.py`, `findings.py`, `cli.py`). Re-read a file immediately before editing it.
- `MOH_Protocols/` is gitignored (`*.pdf` in `.gitignore`). Never `git add` a PDF. The tracked provenance artifacts are `moh_download.py`, `links.tsv`, and `MOH_Protocols/manifest.csv`.
- Baseline before this work (from `python -m cdi_kb.cli verify`, 2026-09-01): `clauses: 3017`, `sources: 11`, `title_reachable_entries: 5`, `mandate_anchored_entries: 0`, `mixed_authority_entries: 6`, VERIFICATION PASSED.

---

## File Structure

| File | Responsibility | Action |
| --- | --- | --- |
| `src/cdi_kb/moh_chunker.py` | The three MOH heading rejectors + `chunk_moh` | Create |
| `src/cdi_kb/chi_chunker.py` | Gains injectable `is_heading` param (2 lines) | Modify |
| `src/cdi_kb/config.py` | `_MOH_DIR`, the 31-source table, `AUTHORITY_RANK` | Modify |
| `src/cdi_kb/cli.py` | Genre dispatch in `build_kb`; authority label in `format_finding` | Modify |
| `src/cdi_kb/findings.py` | `VerifiedCitation.authority`; authority sort in the firewall | Modify |
| `src/cdi_kb/webapp.py` | Authority label in the citation line (1 line) | Modify |
| `tests/test_moh_chunker.py` | Predicate unit tests + corpus junk-title guard | Create |
| `tests/test_chi_chunker.py` | Byte-identity pin for the `chunk_chi` change | Modify |
| `tests/test_config.py` | 42-source registry, MOH authority/genre | Modify |
| `tests/test_findings.py` | Authority ordering | Modify |
| `tests/test_cli.py` | 3 `VerifiedCitation(...)` sites gain `authority=` | Modify |
| `tests/test_kb_verification.py` | `sources == 42`, MOH counts, dilution guard | Modify |

---

### Task 1: Injectable heading predicate in `chunk_chi`

Make the heading rule swappable so `chunk_moh` can reuse the proven segment loop rather than copy it. Strictly additive — the default is the current predicate, so every existing CHI source must chunk **byte-identically**.

**Files:**
- Modify: `src/cdi_kb/chi_chunker.py:106` (signature), `src/cdi_kb/chi_chunker.py:114` (call site), `src/cdi_kb/chi_chunker.py:16-17` (import)
- Test: `tests/test_chi_chunker.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `chunk_chi(pages: list[PageText], source: SourceDoc, *, is_heading: Callable[[str, frozenset[str]], bool] = _is_heading) -> list[Clause]`. Task 2 calls it with a custom `is_heading`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chi_chunker.py`:

```python
def test_default_is_heading_arg_leaves_every_chi_source_byte_identical():
    # chunk_chi gained a keyword-only `is_heading` so chunk_moh can reuse this
    # segment loop. Passing the module default explicitly must reproduce the
    # implicit-default output exactly, for every prose source -- otherwise the
    # "additive, no behaviour change" claim is unverified and CHI citations
    # could silently move.
    from cdi_kb.chi_chunker import _is_heading

    prose = [sid for sid, s in config.SOURCES.items() if s.genre == "chi_prose"]
    assert prose, "no chi_prose sources registered"
    for source_id in prose:
        source = config.SOURCES[source_id]
        pages = extract_pages(source.path, config.RAW_TEXT_DIR)
        implicit = chunk_chi(pages, source)
        explicit = chunk_chi(pages, source, is_heading=_is_heading)
        assert implicit == explicit, source_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chi_chunker.py::test_default_is_heading_arg_leaves_every_chi_source_byte_identical -v`

Expected: FAIL with `TypeError: chunk_chi() got an unexpected keyword argument 'is_heading'`

- [ ] **Step 3: Add the import**

In `src/cdi_kb/chi_chunker.py`, after line 16 (`import re`), add the `collections.abc` import so the block reads:

```python
import re
from collections import Counter
from collections.abc import Callable
```

- [ ] **Step 4: Change the signature and the call site**

`src/cdi_kb/chi_chunker.py:106` — replace:

```python
def chunk_chi(pages: list[PageText], source: SourceDoc) -> list[Clause]:
```

with:

```python
def chunk_chi(
    pages: list[PageText],
    source: SourceDoc,
    *,
    is_heading: Callable[[str, frozenset[str]], bool] = _is_heading,
) -> list[Clause]:
    """Chunk a prose guideline into page-anchored clauses.

    `is_heading` is injectable so a source genre with different page furniture
    (see moh_chunker) can reuse this segment loop instead of copying it. The
    default is this module's own predicate, so CHI sources are unaffected --
    test_default_is_heading_arg_leaves_every_chi_source_byte_identical pins that.
    """
```

`src/cdi_kb/chi_chunker.py:114` — replace `if _is_heading(line, furniture):` with:

```python
            if is_heading(line, furniture):
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_chi_chunker.py -v`

Expected: PASS, all tests in the file green.

- [ ] **Step 6: Run the full suite — nothing else may move**

Run: `python -m pytest`

Expected: same pass/fail counts as before this task (all green).

- [ ] **Step 7: Commit**

```bash
git add src/cdi_kb/chi_chunker.py tests/test_chi_chunker.py
git commit -m "refactor: make chunk_chi's heading predicate injectable

Additive keyword-only param, default unchanged. Pinned byte-identical
against every chi_prose source so the MOH genre can reuse the segment
loop instead of copying it."
```

---

### Task 2: The MOH chunker genre

Three heading rejectors, each measured against the real corpus. The **accept** assertions matter as much as the reject ones: a naive `^[^:]{1,28}:\s+\S` glossary pattern also swallows `Table 10:`, `Figure 1:`, `Assessment:`, and `Setup:`, which are real section titles. The uppercase-ratio condition is what separates them.

**Files:**
- Create: `src/cdi_kb/moh_chunker.py`
- Test: `tests/test_moh_chunker.py` (create)

**Interfaces:**
- Consumes: `chunk_chi(..., is_heading=...)` from Task 1; `chi_chunker._is_heading`, `chi_chunker.repeating_lines`.
- Produces: `chunk_moh(pages: list[PageText], source: SourceDoc) -> list[Clause]`, and the module-private predicates `_is_bullet_item(line: str) -> bool`, `_is_abbreviation_gloss(line: str) -> bool`, `_is_datestamp(line: str) -> bool`, `_is_moh_heading(line: str, furniture: frozenset[str]) -> bool`. Task 3 calls `chunk_moh`; Task 4 imports the predicates.

- [ ] **Step 1: Write the failing test**

Create `tests/test_moh_chunker.py`:

```python
"""MOH heading rejectors: every string below is a real line from the corpus."""

from cdi_kb.moh_chunker import _is_moh_heading

# Junk that the CHI predicate accepts as a heading and MOH must reject. Each is
# a verbatim line from MOH_Protocols/ (occurrence counts across the curated 31:
# bullet-led 110, abbreviation-gloss 49, datestamp 7).
MUST_REJECT = [
    "\u2022 Perform ECG",
    "\u2022 Enoxaparin 40mg SC once daily If CrCl < 30ml/min,",
    "TMP/SMZ SS: Trimethoprim-sulfamethoxazole single strength",
    "IV: Intravenous",
    "GI: Gastrointestinal",
    "MRSA: Methicillin-resistant Staphylococcus aureus",
    "SC, SQ: subcutaneous",
    "4.2 EN: Enteral nutrition",
    "ISSUED DATE: 30/12/2021 update date 23/11/2023 SN",
    "City -Riyadh 15 Feb 2026",
    "Accessed 1 November 2019. Available from",
    "18 September 2024",
]

# Real headings that MUST survive. This half is the point: a bare
# "^[^:]{1,28}:\\s+\\S" glossary pattern rejects the first four of these, which
# would lose a real section title permanently. Requiring an abbreviation-shaped
# (>=60% uppercase) left-hand side is what keeps them.
MUST_ACCEPT = [
    "Table 10: Treatment of Hypertriglyceridemia",
    "Figure 1: Classification of DM",
    "Assessment: Patient\u2019s Profiling",
    "Setup: Inpatient setting",
    "Level of Evidence:",
    "Aim and scope:",
    "Medication Related Information",
    "STAGING OF CKD",
    "Classification of HF by LVEF",
]


def test_moh_heading_rejects_corpus_furniture():
    for line in MUST_REJECT:
        assert not _is_moh_heading(line, frozenset()), line


def test_moh_heading_accepts_real_headings():
    for line in MUST_ACCEPT:
        assert _is_moh_heading(line, frozenset()), line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_moh_chunker.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.moh_chunker'`

- [ ] **Step 3: Write the implementation**

Create `src/cdi_kb/moh_chunker.py`:

```python
"""Chunker for MOH-KSA national protocols (genre "moh_protocol").

Same page-anchored segment loop as the CHI prose chunker -- only the heading
predicate differs. MOH protocols carry three furniture genres the CHI heuristic
accepts as headings, and a bad heading is not cosmetic: index.py weights
section_title 5x body in BM25, so junk titles displace real clauses from
retrieval. Measured over the curated 31 MOH sources, 270 of 1,616 clauses
(16.7%) carried a bullet-, glossary-, or date-shaped title before this fix,
concentrated in the highest-value protocols (SSTI 60%, surgical prophylaxis
53%, GAS 47%, SSI 47%, LRTI 37%, UTI 35%).

Each rejector was tuned against the corpus and verified to reject ONLY junk.
Residual, accepted: 88 colon-bearing heading occurrences survive, a minority of
them table-cell or form-field fragments ("CV effects: ASCVD Neutral Potential
benefit: Neutral", "Vital Signs: STAT Then every__________"). Separating those
from real headings needs layout geometry the text layer does not carry. They
are left in deliberately: an over-broad rejector loses a real section title
permanently, while a surviving table fragment only adds noise to one clause's
title. V1 fidelity and citation stability are unaffected either way, because
clause_id is page-anchored.
"""

import re

from cdi_kb.chi_chunker import _is_heading, chunk_chi
from cdi_kb.clauses import Clause
from cdi_kb.config import SourceDoc
from cdi_kb.extract import PageText

# Bullet list items. Includes U+FFFD and U+F0B7 because the Wingdings bullets
# these PDFs use decode to those, not to U+2022.
_BULLET = re.compile("^[\u2022\u25cf\u25aa\u25e6\ufffd\uf0b7]")

# "<abbrev>: <expansion>" from the abbreviation table every MOH protocol opens
# with. The uppercase-ratio test below is load-bearing: this pattern ALONE also
# matches "Table 10: Treatment of Hypertriglyceridemia", "Figure 1:
# Classification of DM", "Assessment: Patient's Profiling" and "Setup: Inpatient
# setting", which are real headings. Requiring an abbreviation-shaped left-hand
# side separates "IV:" and "MRSA:" from "Assessment:" and "Table 10:" with no
# false rejection observed across the curated 31.
_GLOSS = re.compile(r"^(?P<lhs>[^:]{1,28}):\s+\S")
_GLOSS_MIN_UPPER = 0.6

# Publication/revision stamps and reference-list access dates.
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_DATESTAMP = re.compile(
    rf"\b\d{{1,2}}\s+{_MONTH}\s+(?:19|20)\d{{2}}\b"
    rf"|\b{_MONTH}\s+\d{{1,2}},?\s+(?:19|20)\d{{2}}\b"
    rf"|\b\d{{1,2}}/\d{{1,2}}/(?:19|20)\d{{2}}\b",
    re.IGNORECASE,
)


def _upper_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if c.isupper()) / len(letters) if letters else 0.0


def _is_bullet_item(line: str) -> bool:
    return bool(_BULLET.match(line.strip()))


def _is_abbreviation_gloss(line: str) -> bool:
    match = _GLOSS.match(line.strip())
    return bool(match) and _upper_ratio(match.group("lhs")) >= _GLOSS_MIN_UPPER


def _is_datestamp(line: str) -> bool:
    return bool(_DATESTAMP.search(line))


def _is_moh_heading(line: str, furniture: frozenset[str] = frozenset()) -> bool:
    """The CHI heading rule, minus the three MOH furniture genres."""
    if not _is_heading(line, furniture):
        return False
    return not (_is_bullet_item(line) or _is_abbreviation_gloss(line) or _is_datestamp(line))


def chunk_moh(pages: list[PageText], source: SourceDoc) -> list[Clause]:
    return chunk_chi(pages, source, is_heading=_is_moh_heading)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_moh_chunker.py -v`

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/moh_chunker.py tests/test_moh_chunker.py
git commit -m "feat: MOH protocol chunker genre

Rejects three furniture genres the CHI heuristic accepts as headings:
bullet list items, abbreviation-glossary lines, and date stamps. The
uppercase-ratio condition on the glossary rejector keeps real headings
(Table 10:, Figure 1:, Assessment:, Setup:) that a bare colon pattern
would lose."
```

---

### Task 3: Register the 31 MOH sources and dispatch on genre

**Files:**
- Modify: `src/cdi_kb/config.py:46` (add `_MOH_DIR` and the table), `src/cdi_kb/config.py:58-119` (extend the `SOURCES` comprehension)
- Modify: `src/cdi_kb/cli.py:29` (genre dispatch)
- Test: `tests/test_config.py:35-49`

**Interfaces:**
- Consumes: `chunk_moh` from Task 2.
- Produces: `config.SOURCES` with 42 entries; the 31 MOH ones have `authority="MOH"`, `genre="moh_protocol"`. Tasks 4, 5, 6 all read this.

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, replace the body of `test_sources_registry_has_expected_keys` (currently lines 35-49) so the expected set covers both families, and append two MOH tests:

```python
MOH_SOURCE_IDS = {
    "MOH-DM", "MOH-SEPSIS-MAT", "MOH-PN-ADULT", "MOH-MENINGITIS", "MOH-IAI",
    "MOH-HD", "MOH-LRTI", "MOH-SEPSIS-PED", "MOH-UTI", "MOH-SSI", "MOH-SSTI",
    "MOH-DKA", "MOH-DKA-PED", "MOH-VTE", "MOH-FH", "MOH-RA", "MOH-HIE",
    "MOH-MDD", "MOH-HYPOGLYCEMIA", "MOH-HEADACHE", "MOH-DVT", "MOH-PE",
    "MOH-GAS", "MOH-ANAPHYLAXIS", "MOH-CONTRAST", "MOH-WARFARIN",
    "MOH-TDM-VANCO", "MOH-ANTICOAG-REV", "MOH-ABX-PROPH", "MOH-ALBUMIN",
    "MOH-SUP",
}


def test_sources_registry_has_expected_keys() -> None:
    expected = {
        "CDI-2021",
        "CHI-HF",
        "CHI-CKD",
        "CHI-ANEMIA",
        "CHI-STROKE",
        "CHI-BARIATRIC",
        "CHI-LRTI",
        "CHI-NEC-HBA1C",
        "CHI-NEC-FBG",
        "CHI-NEC-UCULT",
        "CHI-NEC-B12",
    } | MOH_SOURCE_IDS
    assert set(config.SOURCES.keys()) == expected
    assert len(expected) == 42


def test_moh_sources_carry_moh_authority_and_genre() -> None:
    for source_id in MOH_SOURCE_IDS:
        source = config.SOURCES[source_id]
        assert source.authority == "MOH", source_id
        assert source.genre == "moh_protocol", source_id


def test_moh_source_ids_do_not_collide_with_chi() -> None:
    # CHI-LRTI and MOH-LRTI are different documents on the same topic. The
    # prefix is what keeps their clause_ids apart, so a bare "LRTI" id would
    # silently merge two authorities' clauses under one V1 source check.
    for source_id in MOH_SOURCE_IDS:
        assert source_id.startswith("MOH-"), source_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`

Expected: FAIL — `test_sources_registry_has_expected_keys` reports the 31 MOH ids missing from `config.SOURCES`.

- [ ] **Step 3: Add the MOH directory and source table to `config.py`**

In `src/cdi_kb/config.py`, immediately after line 46 (`_CHI_DIR = REPO_ROOT / "CHI_Guidelines"`), add:

```python
_MOH_DIR = REPO_ROOT / "MOH_Protocols"

# MOH-KSA national clinical protocols: 31 of the 93 downloaded (see
# MOH_Protocols/manifest.csv and moh_download.py). Curated, not exhaustive --
# excluded are 4 image-only PDFs (0 extracted chars, need OCR), 2 pure inventory
# tables below MIN_SOURCE_CLAUSES, and the administrative/out-of-scope
# remainder. A (id, filename, title) table rather than 31 SourceDoc calls: the
# authority and genre are identical for every one, so repeating them 31 times
# would only invite one of them to drift.
_MOH_PROTOCOLS: tuple[tuple[str, str, str], ...] = (
    # Role A -- third authority for existing requirement entries
    ("MOH-DM", "Saudi-Diabetes-Clinical-Practice-Guidelines.pdf", "MOH Saudi Diabetes Clinical Practice Guidelines"),
    ("MOH-SEPSIS-MAT", "Maternal-Sepsis-Management.pdf", "MOH Maternal Sepsis Management"),
    ("MOH-PN-ADULT", "Adult-Parenteral-Nutrition-CPG.pdf", "MOH Adult Parenteral Nutrition CPG"),
    ("MOH-MENINGITIS", "Acute-CNS-Infections-Meningitis-Adults.pdf", "MOH Acute CNS Infections Meningitis Adults"),
    ("MOH-IAI", "Intra-abdominal-Infections-Treatment.pdf", "MOH Intra-abdominal Infections Treatment"),
    ("MOH-HD", "Home-Hemodialysis-Complications.pdf", "MOH Home Hemodialysis Complications"),
    ("MOH-LRTI", "Lower-Respiratory-Tract-Infections.pdf", "MOH Lower Respiratory Tract Infections"),
    ("MOH-SEPSIS-PED", "Pediatric-Sepsis-Management.pdf", "MOH Pediatric Sepsis Management"),
    ("MOH-UTI", "Urinary-Tract-Infection.pdf", "MOH Urinary Tract Infection"),
    ("MOH-SSI", "Surgical-Site-Infections-Guidelines.pdf", "MOH Surgical Site Infections Guidelines"),
    ("MOH-SSTI", "Skin-and-Soft-Tissue-Infection.pdf", "MOH Skin and Soft Tissue Infection"),
    # Role B -- candidates for new condition entries (slice 2)
    ("MOH-DKA", "DKA-HHS-Protocol.pdf", "MOH DKA/HHS Protocol"),
    ("MOH-DKA-PED", "Pediatric-DKA-HHS-Protocol.pdf", "MOH Pediatric DKA/HHS Protocol"),
    ("MOH-VTE", "VTE-Prevention-Adults-v1.7.pdf", "MOH VTE Prevention in Adults"),
    ("MOH-FH", "Familial-Hypercholesterolemia.pdf", "MOH Familial Hypercholesterolemia"),
    ("MOH-RA", "Rheumatoid-Arthritis-Adults.pdf", "MOH Rheumatoid Arthritis in Adults"),
    ("MOH-HIE", "Neonatal-Hypoxic-Ischemic-Encephalopathy.pdf", "MOH Neonatal Hypoxic Ischemic Encephalopathy"),
    ("MOH-MDD", "Major-Depressive-Disorder.pdf", "MOH Major Depressive Disorder"),
    ("MOH-HYPOGLYCEMIA", "Inpatient-Hypoglycemia-Management.pdf", "MOH Inpatient Hypoglycemia Management"),
    ("MOH-HEADACHE", "Headache-Disorder.pdf", "MOH Headache Disorder"),
    ("MOH-DVT", "DVT-Treatment-Adults-2024.pdf", "MOH DVT Treatment in Adults"),
    ("MOH-PE", "Pulmonary-Embolism-Adults.pdf", "MOH Pulmonary Embolism in Adults"),
    ("MOH-GAS", "Group-A-Streptococcal-Pharyngitis.pdf", "MOH Group A Streptococcal Pharyngitis"),
    ("MOH-ANAPHYLAXIS", "Anaphylaxis-Management-Adults-Pediatrics.pdf", "MOH Anaphylaxis Management"),
    # Role C -- candidates for necessity / order rules (slice 2)
    ("MOH-CONTRAST", "Safe-Use-of-Contrast-Media-Radiology.pdf", "MOH Safe Use of Contrast Media in Radiology"),
    ("MOH-WARFARIN", "Warfarin-Monitoring-Adults.pdf", "MOH Warfarin Monitoring in Adults"),
    ("MOH-TDM-VANCO", "Adult-TDM-Protocol-Vancomycin-and-Aminoglycosides.pdf",
     "MOH Adult TDM Protocol: Vancomycin and Aminoglycosides"),
    ("MOH-ANTICOAG-REV", "Anticoagulation-Reversal-Strategies.pdf", "MOH Anticoagulation Reversal Strategies"),
    ("MOH-ABX-PROPH", "Antibiotic-Surgical-Prophylaxis.pdf", "MOH Antibiotic Surgical Prophylaxis"),
    ("MOH-ALBUMIN", "Prescribing-Albumin-Protocol-Dec2024.pdf", "MOH Prescribing Albumin Protocol"),
    ("MOH-SUP", "Stress-Ulcer-Prophylaxis-ICU-and-non-ICU.pdf", "MOH Stress Ulcer Prophylaxis (ICU and non-ICU)"),
)
```

- [ ] **Step 4: Extend the `SOURCES` registry**

In `src/cdi_kb/config.py`, the registry currently ends at line 119 with:

```python
        # CHI-NEC-LBPMRI (Low Back Pain MRI.pdf): flowchart genre — excluded until VLM
        # linearization; see task-1-report
    )
}
```

Replace those three lines with:

```python
        # CHI-NEC-LBPMRI (Low Back Pain MRI.pdf): flowchart genre — excluded until VLM
        # linearization; see task-1-report
        *(
            SourceDoc(source_id, _MOH_DIR / filename, title, "MOH", "moh_protocol")
            for source_id, filename, title in _MOH_PROTOCOLS
        ),
    )
}
```

- [ ] **Step 5: Dispatch on genre in `build_kb`**

In `src/cdi_kb/cli.py`, add the import next to the existing chunker imports:

```python
from cdi_kb.moh_chunker import chunk_moh
```

Then replace line 29:

```python
        clauses = chunk_booklet(pages) if source.genre == "booklet" else chunk_chi(pages, source)
```

with:

```python
        if source.genre == "booklet":
            clauses = chunk_booklet(pages)
        elif source.genre == "moh_protocol":
            clauses = chunk_moh(pages, source)
        else:
            clauses = chunk_chi(pages, source)
```

- [ ] **Step 6: Run the config tests**

Run: `python -m pytest tests/test_config.py -v`

Expected: PASS — 42 sources, all paths exist, MOH authority/genre correct.

- [ ] **Step 7: Rebuild the KB**

Run: `python -m cdi_kb.cli build-kb`

Expected: 42 per-source lines printed. The 11 existing sources must print their baseline counts unchanged (`CDI-2021: 768`, `CHI-HF: 948`, `CHI-CKD: 634`, `CHI-ANEMIA: 110`, `CHI-STROKE: 443`, `CHI-BARIATRIC: 54`, `CHI-LRTI: 19`, `CHI-NEC-HBA1C: 9`, `CHI-NEC-FBG: 8`, `CHI-NEC-UCULT: 15`, `CHI-NEC-B12: 9`). Every MOH source must print ≥5 clauses (no `ValueError` from the build floor). Final line: `clauses stored: <N>, indexed: <N>` with N ≈ 4600.

If any MOH source raises the `below the minimum` ValueError, STOP and report — do not lower `MIN_SOURCE_CLAUSES`. That floor is what catches an unreadable PDF.

- [ ] **Step 8: Commit**

```bash
git add src/cdi_kb/config.py src/cdi_kb/cli.py tests/test_config.py
git commit -m "feat: register 31 curated MOH-KSA protocols as KB sources

Third authority alongside CDI-2021 and CHI. build_kb dispatches
moh_protocol to the new chunker. 1,616 clauses; index 3,017 -> ~4,633."
```

---

### Task 4: Corpus-level junk-title regression guard

Task 2 tested the predicates on hand-picked strings. This tests the outcome on the **built corpus**, which is what actually protects retrieval.

**Files:**
- Test: `tests/test_moh_chunker.py` (append)

**Interfaces:**
- Consumes: `config.SOURCES` (Task 3), the predicates from Task 2.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_moh_chunker.py`:

```python
from cdi_kb import config
from cdi_kb.extract import extract_pages
from cdi_kb.moh_chunker import (
    _is_abbreviation_gloss, _is_bullet_item, _is_datestamp, chunk_moh,
)


def test_no_moh_clause_carries_furniture_as_its_section_title():
    # The guard for the whole chunker fix. index.py weights section_title 5x, so
    # a regression here degrades retrieval while every other test stays green.
    #
    # The metric is the three NAMED classes, not "no junk titles". Table-cell
    # fragments ("CV effects: ASCVD Neutral...") survive by design -- see the
    # module docstring -- and asserting an unachievable 0 would only invite this
    # assertion to be loosened later.
    moh = [s for s in config.SOURCES.values() if s.genre == "moh_protocol"]
    assert len(moh) == 31

    offenders = []
    for source in moh:
        pages = extract_pages(source.path, config.RAW_TEXT_DIR)
        for clause in chunk_moh(pages, source):
            title = clause.section_title
            if _is_bullet_item(title) or _is_abbreviation_gloss(title) or _is_datestamp(title):
                offenders.append((clause.clause_id, title))
    assert offenders == [], offenders[:10]
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_moh_chunker.py::test_no_moh_clause_carries_furniture_as_its_section_title -v`

Expected: PASS. (It exercises Task 2's fix over all 31 sources; it is written after the fix rather than before because the predicates it depends on are already committed and independently tested.)

If it FAILS, the printed offenders name a furniture genre the predicates miss. Fix the predicate in `moh_chunker.py` and re-run — do not weaken the assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/test_moh_chunker.py
git commit -m "test: guard MOH section_titles against furniture across the corpus"
```

---

### Task 5: Authority ordering in the citation firewall

A finding that draws on more than one authority lists MOH first, then CHI, then CDI-2021. The sort goes in `_verified_citations` — already the single audited citation path — so every composer inherits it.

**Files:**
- Modify: `src/cdi_kb/config.py` (add `AUTHORITY_RANK` after `SOURCE_ID`, near line 44)
- Modify: `src/cdi_kb/findings.py` (`VerifiedCitation`, `_verified_citations`)
- Modify: `src/cdi_kb/cli.py:87` (label), `src/cdi_kb/webapp.py:258` (label)
- Test: `tests/test_findings.py` (append), `tests/test_cli.py:98,133,160` (add the new field)

**Interfaces:**
- Consumes: `config.SOURCES` (Task 3).
- Produces: `VerifiedCitation(clause_id, section_title, page, quote, authority)` — `authority` is required, no default.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_findings.py`:

```python
def test_citations_are_ordered_moh_then_chi_then_booklet(tmp_path) -> None:
    # MOH is the national regulator, CHI the insurance/quality authority, and
    # CDI-2021 the coding-education booklet. A clinician reading a finding
    # should meet the strongest authority first.
    clauses = [
        Clause("CDI-2021/staging/p1", "Staging", 62, "A disease may be described as Stage 1 through to 5."),
        Clause("CHI-CKD/pg9/p2", "Staging of CKD", 9, "CKD is staged by GFR category G1 to G5."),
        Clause("MOH-HD/pg4/p1", "Staging", 4, "Document the CKD stage at every dialysis review."),
    ]
    requirement = DiagnosisRequirement(
        condition="chronic kidney disease", synonyms=["CKD"],
        axes=[AxisRule(axis="stage", level="required", evidence_terms=["stage 4"])],
        recommendation="Please document the stage, if known.",
        citations=[
            Citation(clause_id="CDI-2021/staging/p1", quote="Stage 1 through to 5"),
            Citation(clause_id="CHI-CKD/pg9/p2", quote="staged by GFR category"),
            Citation(clause_id="MOH-HD/pg4/p1", quote="Document the CKD stage"),
        ],
    )
    finding = compose_finding(GAP, requirement, _store(tmp_path, clauses))
    assert finding is not None
    assert [c.authority for c in finding.citations] == ["MOH", "CHI", "TCC"]
    assert [c.clause_id for c in finding.citations] == [
        "MOH-HD/pg4/p1", "CHI-CKD/pg9/p2", "CDI-2021/staging/p1",
    ]


def test_same_authority_citations_keep_their_authored_order(tmp_path) -> None:
    # Stable sort on rank alone: an author who lists a primary quote first must
    # see it stay first.
    clauses = [
        Clause("CHI-CKD/pg9/p2", "Staging of CKD", 9, "CKD is staged by GFR category G1 to G5."),
        Clause("CHI-CKD/pg9/p3", "Staging of CKD", 9, "Albuminuria categories A1 to A3 refine the stage."),
    ]
    requirement = DiagnosisRequirement(
        condition="chronic kidney disease", synonyms=["CKD"],
        axes=[AxisRule(axis="stage", level="required", evidence_terms=["stage 4"])],
        recommendation="Please document the stage, if known.",
        citations=[
            Citation(clause_id="CHI-CKD/pg9/p3", quote="Albuminuria categories A1 to A3"),
            Citation(clause_id="CHI-CKD/pg9/p2", quote="staged by GFR category"),
        ],
    )
    finding = compose_finding(GAP, requirement, _store(tmp_path, clauses))
    assert finding is not None
    assert [c.clause_id for c in finding.citations] == ["CHI-CKD/pg9/p3", "CHI-CKD/pg9/p2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_findings.py -v`

Expected: FAIL with `AttributeError: 'VerifiedCitation' object has no attribute 'authority'`

- [ ] **Step 3: Add `AUTHORITY_RANK` to `config.py`**

In `src/cdi_kb/config.py`, append to the **end of the file** (after the `SOURCES` dict's closing `}`). `authority_of` reads `SOURCES`, so it cannot be defined above it:

```python
# Citation display order. MOH-KSA is the national health ministry, CHI the
# insurance/quality authority, TCC the coding-education booklet publisher; a
# clinician reading a finding should meet the strongest authority first. An
# authority absent from this map sorts last rather than raising -- a new source
# family must never be able to break finding composition.
AUTHORITY_RANK: dict[str, int] = {"MOH": 0, "CHI": 1, "TCC": 2}
_UNRANKED_AUTHORITY = len(AUTHORITY_RANK)


def authority_of(clause_id: str) -> str:
    """The authority that published the clause, from its source-id prefix."""
    source = SOURCES.get(clause_id.split("/", 1)[0])
    return source.authority if source else ""


def authority_rank(clause_id: str) -> int:
    return AUTHORITY_RANK.get(authority_of(clause_id), _UNRANKED_AUTHORITY)
```

Note: `authority_of` and `authority_rank` reference `SOURCES`, so they must be placed **after** the `SOURCES` dict (i.e. at the end of `config.py`, after line 119's closing `}`), while `AUTHORITY_RANK` and `_UNRANKED_AUTHORITY` may sit near `SOURCE_ID`. Put all five at the end of the file to keep them together.

- [ ] **Step 4: Add the field and the sort in `findings.py`**

In `src/cdi_kb/findings.py`, add to the imports:

```python
from cdi_kb.config import QUOTE_MATCH_THRESHOLD, authority_of, authority_rank
```

(replacing the existing `from cdi_kb.config import QUOTE_MATCH_THRESHOLD`).

Extend the dataclass:

```python
@dataclass(frozen=True)
class VerifiedCitation:
    clause_id: str
    section_title: str
    page: int
    quote: str
    authority: str
```

Replace the body of `_verified_citations` after the loop so it sorts before returning:

```python
def _verified_citations(citations: list[Citation], store: ClauseStore) -> list[VerifiedCitation]:
    """THE only citation-verification code path: every Finding-producing
    composer (diagnosis-gap, doc-type-element-gap, and any future finding
    type) must route through this to keep a single audited firewall.

    Verified citations are returned ordered by publishing authority (MOH ->
    CHI -> CDI-2021). The sort is stable and keys on rank alone, so two
    citations from the same authority keep the order the YAML author gave
    them."""
    verified: list[VerifiedCitation] = []
    for citation in citations:
        clause = store.get(citation.clause_id)
        if clause is None:
            continue
        if find_quote(citation.quote, clause.text, QUOTE_MATCH_THRESHOLD).found:
            verified.append(VerifiedCitation(
                clause_id=clause.clause_id, section_title=clause.section_title,
                page=clause.page, quote=citation.quote,
                authority=authority_of(clause.clause_id),
            ))
    verified.sort(key=lambda c: authority_rank(c.clause_id))
    return verified
```

- [ ] **Step 5: Update the three `VerifiedCitation(...)` sites in `tests/test_cli.py`**

Line ~98: add `authority="TCC"` to the `CDI-2021/sepsis/p1` citation.
Line ~133: add `authority="TCC"` to the `CDI-2021/allied-health/p2` citation.
Line ~160: add `authority="TCC"` to the `CDI-2021/x/p1` citation.

Example for the first:

```python
        citations=(VerifiedCitation(clause_id="CDI-2021/sepsis/p1", section_title="Sepsis",
                                    page=118, quote="The infective agent should be documented",
                                    authority="TCC"),),
```

- [ ] **Step 6: Label the authority in CLI and web output**

`src/cdi_kb/cli.py:87` — replace:

```python
        lines.append(f"  source: {cite.clause_id} (p.{cite.page}) — \"{cite.quote[:90]}...\"")
```

with:

```python
        lines.append(
            f"  source: [{cite.authority}] {cite.clause_id} (p.{cite.page}) — \"{cite.quote[:90]}...\""
        )
```

`src/cdi_kb/webapp.py:258` — replace `'<div class="cite">source: '+esc(c.clause_id)` with:

```javascript
    +f.citations.map(c=>'<div class="cite">source: ['+esc(c.authority)+'] '+esc(c.clause_id)+' (p.'+esc(c.page)+') — "'+esc(c.quote)+'"</div>').join('');
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_findings.py tests/test_cli.py tests/test_webapp.py -v`

Expected: PASS. If a `test_cli` assertion like `assert "source: CDI-2021/sepsis/p1 (p.118)" in rendered` now fails, update that expected string to `"source: [TCC] CDI-2021/sepsis/p1 (p.118)"` — the label is the intended change.

- [ ] **Step 8: Commit**

```bash
git add src/cdi_kb/config.py src/cdi_kb/findings.py src/cdi_kb/cli.py src/cdi_kb/webapp.py tests/test_findings.py tests/test_cli.py
git commit -m "feat: order finding citations MOH -> CHI -> CDI-2021

Sort lives in _verified_citations, the single audited citation path, so
every composer inherits it. VerifiedCitation gains an authority label
surfaced in CLI and web output."
```

---

### Task 6: Verification stats and the retrieval-dilution guard

The honest risk of a +54% index is not a red test — it is MOH clauses displacing cited CHI/booklet sections out of top-5 while `title_reachable_entries` silently absorbs it.

**Files:**
- Modify: `tests/test_kb_verification.py:58-66`
- Test: full suite + `cli verify`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Update the source-count test and add the dilution guard**

In `tests/test_kb_verification.py`, replace `test_stats_report_per_source_counts` (currently lines 58-66) with:

```python
def test_stats_report_per_source_counts() -> None:
    report = run_verification()
    assert report.stats["sources"] == 42
    # 18 -> 19 after step 4: the page-furniture filter changes where segment
    # boundaries fall, so this source re-paragraphs by one clause. Extraction
    # itself is byte-identical for CHI-LRTI (it had no fused words).
    assert report.stats["clauses_CHI-LRTI"] == 19
    assert report.stats["clauses_CHI-ANEMIA"] > 10
    # Every MOH source must clear the build floor; a source that quietly drops
    # to zero clauses would still pass V1-V5 (nothing to check) while silently
    # leaving an authority out of the KB.
    moh = [sid for sid, s in config.SOURCES.items() if s.genre == "moh_protocol"]
    assert len(moh) == 31
    for source_id in moh:
        assert report.stats[f"clauses_{source_id}"] >= 5, source_id


def test_moh_ingestion_does_not_worsen_retrieval_fallbacks() -> None:
    # The dilution guard. Baseline measured on 2026-09-01 with 11 sources /
    # 3,017 clauses, BEFORE the 31 MOH sources landed:
    #     title_reachable_entries = 5, mandate_anchored_entries = 0
    # Adding 1,616 MOH clauses is exactly the operation that can push a cited
    # CHI/booklet section out of the top-5 for its own condition query. V3 would
    # then quietly fall back to the title query and stay green.
    #
    # If this fails, an entry's citation has become unreachable by its natural
    # query. Investigate and fix retrieval (or narrow the source set) -- do NOT
    # re-baseline these numbers to make it pass.
    report = run_verification()
    assert report.stats["title_reachable_entries"] <= 5
    assert report.stats["mandate_anchored_entries"] == 0
```

`from cdi_kb import config` is already imported at the top of this file (line 6) — no import change needed.

- [ ] **Step 2: Run the verification tests**

Run: `python -m pytest tests/test_kb_verification.py -v`

Expected: PASS.

If `test_moh_ingestion_does_not_worsen_retrieval_fallbacks` fails, report the offending entries (`report.notes` names each `V3-INFO ... reachable by title query only`) before changing anything.

- [ ] **Step 3: Run the full verification command**

Run: `python -m cdi_kb.cli verify`

Expected: `VERIFICATION PASSED`, `'sources': 42`, `'clauses'` ≈ 4633, `'title_reachable_entries': 5` or lower, and 31 new `clauses_MOH-*` entries in the stats dict.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest`

Expected: all green, no skips other than the pre-existing `live`-marked ones.

- [ ] **Step 5: Confirm no PDF was staged**

Run: `git status --porcelain`

Expected: no `MOH_Protocols/*.pdf` entries (they are gitignored). If any appear, do not commit them.

- [ ] **Step 6: Commit**

```bash
git add tests/test_kb_verification.py
git commit -m "test: 42-source stats and the MOH retrieval-dilution guard

Asserts title_reachable_entries does not grow past its 11-source baseline
of 5, so MOH clauses displacing a cited section out of top-5 surfaces as a
failure instead of being absorbed by the V3 title fallback."
```

---

## Self-Review Notes (performed at plan time)

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| §1 curated 31 sources | Task 3 |
| §2 chunker genre + 3 rejectors | Tasks 1, 2 |
| §2 residual/limitations documented | Task 2 (module docstring) |
| §3 authority ordering | Task 5 |
| §4 V1/V2/V3 unchanged | verified by Task 6 Step 3 |
| §4 V5 `sources == 42` | Task 6 |
| §4 new tests 1–6 | Task 3 (1), Task 2 (2), Task 4 (3), Task 1 (4), Task 6 (5), Task 5 (6) |
| §5 dilution guard | Task 6 |
| §6 no rule YAMLs | enforced by omission; no task creates `data/**` |

**Type consistency:** `chunk_moh(pages, source)` matches `chunk_chi`'s shape and is called that way in `cli.py`. `_is_moh_heading(line, furniture)` matches the `Callable[[str, frozenset[str]], bool]` the Task 1 signature declares. `authority_of` / `authority_rank` are defined in `config.py` and imported by name in `findings.py`. `VerifiedCitation.authority` is required in Task 5 and supplied at the one firewall construction site plus the three test sites.

**Deviation from the spec, deliberate:** the spec's §4 test 3 is implemented in Task 4 as a corpus-level test written *after* the fix rather than before it. The predicates it depends on are already covered test-first in Task 2; writing Task 4's assertion first would only restate Task 2's failure. Noted rather than silently reordered.

**Known ordering constraint:** Task 3 Step 7 (`build-kb`) must run before Tasks 4 and 6, which read the built store and the registry.
