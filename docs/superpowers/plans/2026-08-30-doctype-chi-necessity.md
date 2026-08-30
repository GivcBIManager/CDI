# Doc-Type Rules + CHI Authority + Necessity Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Doc-type-aware audit rules, CHI guidelines as a second citation authority (prose docs), and a medical-necessity validation stage — per the approved spec `docs/superpowers/specs/2026-08-30-doctype-chi-necessity-design.md`.

**Architecture:** Extends the merged KB demo. New modules `chi_chunker.py`, `doctype.py`, `necessity.py`; multi-source registry in `config.py`; two new Layer-3 rule types (`data/doc_requirements/`, `data/necessity/`) sharing the existing citation firewall via one refactored verification helper in `findings.py`; verification V1–V5 extended across sources and rule types.

**Tech Stack:** unchanged (Python 3.13, stdlib sqlite3/FTS5, pdfplumber, pydantic v2, FastAPI, pytest).

## Global Constraints

- All constraints from `docs/superpowers/plans/2026-08-27-cdi-kb-demo.md` Global Constraints remain in force (firewall, verbatim quotes, offline pytest, `/c/python/python`, git hygiene, style, model ID only in config).
- **One firewall path:** every new finding type routes through `findings.py` composers that share the single private `_verified_citations` helper. No second verification implementation anywhere.
- Quotes for ALL new YAML citations are copy-pasted from `/c/python/python -m cdi_kb.cli quote "<text>"` output — verbatim, including `�` artifacts. RULE A/B/C from the ledger applies: no governing clause → drop or downgrade the element/axis, with a YAML comment.
- New multi-word term matching uses the wrap-tolerant `\s+`-join pattern (import/reuse `gapcheck` helpers; do not re-implement).
- clause_id formats: booklet unchanged; CHI sources `{SOURCE_ID}/pg<page>/p<n>`.
- `dedupe_key` formats: diagnosis rules `<condition>|<axis>` (unchanged); doc-type elements `<doc_type>|<element>`; necessity `necessity|<order>`.
- First extraction of CHI-HF/CHI-CKD PDFs takes minutes — use `timeout: 600000` on those Bash steps; extraction is cached afterward.
- Test counts: the suite currently has 65 passed / 1 deselected. Each task states its expected delta; report actual numbers.

---

### Task 1: Multi-source registry + CHI prose chunker + multi-source build

**Files:**
- Modify: `src/cdi_kb/config.py`, `src/cdi_kb/cli.py` (build_kb), `src/cdi_kb/clauses.py` (make `_split_paragraphs` public as `split_paragraphs`, keep old name as alias used internally)
- Create: `src/cdi_kb/chi_chunker.py`
- Test: `tests/test_chi_chunker.py`, extend `tests/test_config.py`

**Interfaces:**
- Consumes: `extract_pages`, `Clause`, `ClauseStore`, `SearchIndex`
- Produces:
  - `config.SourceDoc` frozen dataclass: `source_id: str`, `path: Path`, `title: str`, `authority: str`, `genre: str` (`"booklet" | "chi_prose" | "necessity"`)
  - `config.SOURCES: dict[str, SourceDoc]` with exactly these entries (paths relative to REPO_ROOT):
    - `CDI-2021` → `CDI Course Booklet - Clinicians.pdf`, "CDI Course Booklet – Clinicians (2021)", "TCC", "booklet"
    - `CHI-HF` → `CHI_Guidelines/Heart Failure.pdf`, "CHI Heart Failure Guideline", "CHI", "chi_prose"
    - `CHI-CKD` → `CHI_Guidelines/Chronic Kidney Disease.pdf`, "CHI Chronic Kidney Disease Guideline", "CHI", "chi_prose"
    - `CHI-ANEMIA` → `CHI_Guidelines/Anemia.pdf`, "CHI Anemia Guideline", "CHI", "chi_prose"
    - `CHI-STROKE` → `CHI_Guidelines/Saudi Stroke Standards.pdf`, "Saudi Stroke Standards", "CHI", "chi_prose"
    - `CHI-NEC-HBA1C` → `CHI_Guidelines/Medical Necessity Criteria for HgA1c Testing.pdf`, "CHI Necessity Criteria: HbA1c", "CHI", "necessity"
    - `CHI-NEC-FBG` → `CHI_Guidelines/Medical Necessity Criteria for Fasting Blood Glucose Testing.pdf`, "CHI Necessity Criteria: Fasting Blood Glucose", "CHI", "necessity"
    - `CHI-NEC-UCULT` → `CHI_Guidelines/Medical Necessity Criteria for Urine Culture Testing in Pediatrics.pdf`, "CHI Necessity Criteria: Urine Culture (Pediatrics)", "CHI", "necessity"
    - `CHI-NEC-B12` → `CHI_Guidelines/Medical Necessity Criteria for Vitamin B12 Testing.pdf`, "CHI Necessity Criteria: Vitamin B12", "CHI", "necessity"
    - `CHI-NEC-LBPMRI` → `CHI_Guidelines/Low Back Pain MRI.pdf`, "CHI Necessity Criteria: Low Back Pain MRI", "CHI", "necessity"
  - `chi_chunker.chunk_chi(pages: list[PageText], source: SourceDoc) -> list[Clause]`
  - `cli.build_kb() -> tuple[int, int]` now builds ALL sources (booklet via `chunk_booklet`, others via `chunk_chi`), prints one `source_id: N clauses` line per source, and raises `ValueError` naming the source if any source yields < 5 clauses or < 1000 extracted chars (loud failure on unreadable PDFs).

- [ ] **Step 1: Failing tests.** `tests/test_config.py` additions: `SOURCES` has the 10 keys above; every `path.exists()`; `SOURCES["CDI-2021"].genre == "booklet"`. `tests/test_chi_chunker.py`:

```python
from cdi_kb import config
from cdi_kb.chi_chunker import chunk_chi
from cdi_kb.extract import extract_pages


def _clauses(source_id):
    source = config.SOURCES[source_id]
    return chunk_chi(extract_pages(source.path, config.RAW_TEXT_DIR), source)


def test_anemia_chunks_have_page_anchored_ids():
    clauses = _clauses("CHI-ANEMIA")
    assert len(clauses) > 10
    assert all(c.clause_id.startswith("CHI-ANEMIA/pg") for c in clauses)
    assert all("/p" in c.clause_id.rsplit("/", 1)[-0] or True for c in clauses)  # id shape checked below
    first = clauses[0].clause_id
    assert first.split("/")[1].startswith("pg") and first.split("/")[2].startswith("p")


def test_ids_unique_and_stable():
    clauses = _clauses("CHI-ANEMIA")
    ids = [c.clause_id for c in clauses]
    assert len(ids) == len(set(ids))
    assert ids == [c.clause_id for c in _clauses("CHI-ANEMIA")]


def test_heading_becomes_section_title():
    clauses = _clauses("CHI-STROKE")
    titles = {c.section_title for c in clauses}
    assert len(titles) > 3  # heading heuristic found real sections, not one blob


def test_necessity_doc_extracts():
    clauses = _clauses("CHI-NEC-HBA1C")
    assert len(clauses) >= 3
```

- [ ] **Step 2: Run to verify failure** (`ModuleNotFoundError` / missing SOURCES).
- [ ] **Step 3: Implement.** `config.py`: add `SourceDoc` + `SOURCES` (booklet entry reuses `BOOKLET_PDF`). `chi_chunker.py`:

```python
"""Heading-heuristic chunker for CHI prose guidelines (no dot-leader TOC).

clause_id is page-anchored ({SRC}/pg<page>/p<n>) so citation stability does not
depend on heading-detection quality; V1 guarantees verbatim fidelity either way.
"""

import re

from cdi_kb.clauses import Clause, split_paragraphs
from cdi_kb.config import SourceDoc
from cdi_kb.extract import PageText

_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\s+\S")


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) >= 70 or stripped.endswith("."):
        return False
    if _NUMBERED_HEADING.match(stripped):
        return True
    words = [w for w in stripped.split() if w[0].isalpha()]
    if len(words) >= 2:
        capitalized = sum(1 for w in words if w[0].isupper())
        return capitalized / len(words) >= 0.6
    return False


def chunk_chi(pages: list[PageText], source: SourceDoc) -> list[Clause]:
    clauses: list[Clause] = []
    current_heading = source.title
    for page in pages:
        body_lines: list[str] = []
        for line in page.text.splitlines():
            if _is_heading(line):
                current_heading = line.strip()
            else:
                body_lines.append(line)
        ordinal = 0
        for paragraph in split_paragraphs("\n".join(body_lines)):
            ordinal += 1
            clauses.append(Clause(
                clause_id=f"{source.source_id}/pg{page.page_number}/p{ordinal}",
                section_title=current_heading,
                page=page.page_number,
                text=paragraph,
            ))
    return clauses
```

(If `split_paragraphs` groups across the whole page rather than per blank line, reuse whatever `clauses.py`'s split produces — the contract is: paragraphs ≥ MIN_CLAUSE_CHARS, verbatim text.) `clauses.py`: rename `_split_paragraphs` → `split_paragraphs`, keep `_split_paragraphs = split_paragraphs` alias so existing tests still pass. `cli.build_kb`: loop `config.SOURCES.values()`, dispatch on genre, aggregate clauses, guard (`< 5 clauses or < 1000 chars` → `ValueError(source_id)`), print per-source counts, rebuild store + index once with the aggregate.

- [ ] **Step 4: Build and test.** Run `/c/python/python -m cdi_kb.cli build-kb` (timeout 600000 — first CHI-HF/CHI-CKD extraction is slow) then the new tests then the full suite. Expected: per-source lines, aggregate clause count well above 768; all tests pass (existing `test_clauses.py` untouched).
- [ ] **Step 5: Commit** `feat: multi-source KB — CHI prose sources and chunker` + trailer.

---

### Task 2: Per-source V1 + verify stats for sources

**Files:**
- Modify: `src/cdi_kb/verify.py`
- Test: extend `tests/test_kb_verification.py`

**Interfaces:**
- Consumes: `config.SOURCES`, existing `run_verification`
- Produces: V1 loops sources — for each source, clauses with that `source_id` prefix are checked against THAT source's normalized raw text; `stats` gains `"sources": <count>` and `"clauses_<source_id>": <count>` per source.

- [ ] **Step 1: Failing test additions:** `report.stats["sources"] == 10`; `report.stats["clauses_CHI-ANEMIA"] > 10`; existing tests keep passing (`clauses` stat becomes the aggregate).
- [ ] **Step 2: Implement.** In `run_verification`: build `full_source_by_id = {sid: normalize(" ".join(p.text for p in extract_pages(src.path, config.RAW_TEXT_DIR)))}`; group clauses by `clause_id.split("/", 1)[0]`; V1 checks each group against its own source text (unknown prefix → failure line). Stats as above.
- [ ] **Step 3: Run** `cli verify` (expect `VERIFICATION PASSED`, V3-INFO lines unchanged) + the test file + full suite.
- [ ] **Step 4: Commit** `feat: per-source V1 verification` + trailer.

---

### Task 3: Doc-type detection + applies_to filtering

**Files:**
- Create: `src/cdi_kb/doctype.py`
- Modify: `src/cdi_kb/requirements_model.py` (`DocType`, `AxisRule.applies_to`), `src/cdi_kb/gapcheck.py` (`find_gaps` doc-type filter), `src/cdi_kb/audit.py` (`doc_type` param + `active_doc_type`)
- Test: `tests/test_doctype.py`, extend `tests/test_gapcheck.py`, `tests/test_audit.py`

**Interfaces:**
- Produces:
  - `DocType` type alias in `requirements_model.py`: `Literal["discharge_summary", "admission_note", "progress_note", "emergency_note", "diagnosis_list", "any"]`; `DOC_TYPES: tuple[str, ...]` of the five concrete values
  - `AxisRule.applies_to: list[DocType] = ["any"]` (pydantic default — existing YAMLs load unchanged)
  - `doctype.detect_doc_type(note_text: str) -> DocType` per the spec heuristics (header regex on first 400 chars → SOAP-marker check (≥3 of `S:`/`O:`/`A:`/`P:` at line starts) → diagnosis-list shape (≥3 non-empty lines, ≥60% shorter than 60 chars, and no line ending in a sentence period followed by ≥2 more prose lines — implementer judgment within these bounds, locked by the tests) → `"any"`)
  - `gapcheck.rule_applies(rule: AxisRule, doc_type: str) -> bool` (`"any" in rule.applies_to or doc_type == "any" or doc_type in rule.applies_to`); `find_gaps(note_text, requirements, doc_type="any")` skips non-applying rules
  - `audit.run_audit(note_text, *, doc_type: DocType | None = None, use_llm: bool = False)`; auto-detect when `None`; `AuditResult.active_doc_type: str = "any"` set on every result; `_inferred_findings` gets the same doc-type filter treatment (pass doc_type through, filter axes with `rule_applies`)

- [ ] **Step 1: Failing tests.** `tests/test_doctype.py` (≥6 cases): "DISCHARGE SUMMARY\nAdmitted with..." → discharge_summary; "Progress Note\nS: ...\nO: ...\nA: ...\nP: ..." → progress_note; SOAP without title → progress_note; "1. CKD stage 4\n2. Anemia\n3. T2DM" → diagnosis_list; free prose → any; explicit "Emergency Department note" → emergency_note. `test_gapcheck.py`: an AxisRule with `applies_to: ["discharge_summary"]` fires under `doc_type="discharge_summary"` and `"any"`, not under `"progress_note"`. `test_audit.py`: `run_audit("Known CKD.", doc_type="progress_note").active_doc_type == "progress_note"`; auto-detect path returns the detected value.
- [ ] **Step 2–4:** RED → implement → GREEN → full suite.
- [ ] **Step 5: Commit** `feat: doc-type detection and applies_to rule filtering` + trailer.

---

### Task 4: Firewall refactor + doc-type completeness rules (schema, composer, 5 YAMLs)

**Files:**
- Modify: `src/cdi_kb/findings.py` (extract `_verified_citations`, add `compose_element_finding`), `src/cdi_kb/requirements_model.py` (`Element`, `DocTypeRequirement`, `load_doc_requirements`), `src/cdi_kb/audit.py` (element-gap stage)
- Create: `src/cdi_kb/doc_gaps.py` (`find_element_gaps(note_text, doc_req) -> list[Element]` — missing elements via wrap-tolerant term scan, reusing `gapcheck`'s public pattern helper; make `_term_pattern` public as `term_pattern` with alias), `data/doc_requirements/{discharge-summary,admission-note,progress-note,emergency-note,diagnosis-list}.yaml`
- Test: `tests/test_doc_requirements.py`

**Interfaces:**
- `Element(name: str, evidence_terms: list[str] min 1, level: Literal["required","recommended"], recommendation: str, citations: list[Citation] min 1)`
- `DocTypeRequirement(doc_type: DocType, elements: list[Element] min 1)`; `load_doc_requirements(directory: Path) -> dict[str, DocTypeRequirement]` keyed by doc_type, `ValueError` naming a bad file
- `findings._verified_citations(citations, store) -> list[VerifiedCitation]` — the ONLY citation-verification code path; `compose_finding` refactored onto it with behavior byte-identical (existing tests must pass unmodified)
- `compose_element_finding(doc_type: str, element: Element, store: ClauseStore) -> Finding | None` — `finding_type="completeness_gap"`, `condition=doc_type`, `axis=element.name`, `evidence_excerpt=f"{doc_type} (element not found)"`, `dedupe_key=f"{doc_type}|{element.name}"`, None without a verified citation
- `run_audit`: when `active_doc_type != "any"` and a DocTypeRequirement exists for it, element gaps are composed and appended (inside the existing try/finally)

**Data authoring (the RULE A/B/C step):** rebuild the KB first, then for each doc type mine the booklet with `cli quote` probes — discharge summary: "discharge summary" (booklet pp. 67–69, 81); admission: "admission note"; progress: "progress note", "SOAP"; emergency: "emergency note"; diagnosis list: "principal diagnosis", "additional diagnoses". Author 3–8 elements per file (e.g., discharge summary: principal diagnosis, procedures/operations, medications on discharge, follow-up plan — exactly what the quoted clauses support). Every element cites verbatim booklet text; unsupported planned elements are dropped with a comment. Report a per-file table: element → clause_id → level.

- [ ] Steps: failing schema/composer/detection tests (incl. one firewall test: element citation with a fabricated quote → `None`) → implement → author YAMLs → integration test: a note typed `discharge_summary` missing "follow-up" evidence yields `discharge_summary|follow_up_plan`-style finding with citations; the same note as `progress_note` yields none of those → full suite → commit `feat: doc-type completeness rules behind the shared firewall` + trailer.

---

### Task 5: Necessity rules (schema, detection, composer, 5 YAMLs)

**Files:**
- Modify: `src/cdi_kb/requirements_model.py` (`NecessityRule`, `load_necessity_rules`), `src/cdi_kb/findings.py` (`compose_necessity_finding`), `src/cdi_kb/audit.py` (necessity stage)
- Create: `src/cdi_kb/necessity.py`, `data/necessity/{hba1c,fasting-glucose,urine-culture,vitamin-b12,lumbar-mri}.yaml`
- Test: `tests/test_necessity.py`

**Interfaces:**
- `NecessityRule(order: str, display_name: str, order_terms: list[str] min 1, context_cues: list[str] min 1, valid_indication_terms: list[str] min 1, level: Literal["required","recommended"] = "required", recommendation: str, citations: list[Citation] min 1)`
- `load_necessity_rules(directory: Path) -> list[NecessityRule]`
- `necessity.find_necessity_gaps(note_text: str, rules: list[NecessityRule]) -> list[NecessityRule]` — a rule fires when: an order term matches (wrap-tolerant, word-boundary), a context cue occurs within ±60 chars of that match, the order-term match is not negated (reuse gapcheck's negation window), and NO valid-indication term matches anywhere in the note
- `compose_necessity_finding(rule, store) -> Finding | None` — `finding_type="necessity_mismatch"`, `condition=rule.order`, `axis="indication"`, `dedupe_key=f"necessity|{rule.order}"`, via `_verified_citations`
- `run_audit`: necessity stage after the diagnosis gap loop (all doc types), findings appended, unverifiable → `dropped_citations`

**Data authoring:** quotes mined from the CHI-NEC-* sources via `cli quote` (probe examples: "HbA1c", "fasting", "urine culture", "B12", "magnetic resonance"). Indication terms drawn from the criteria text itself (e.g., HbA1c: diabetes, prediabetes, impaired fasting glucose, metformin…). Non-leading recommendations ("An HbA1c order is documented without a supporting indication. Please document the indication, if applicable."). Same drop/downgrade discipline; note in the report if any of the five docs turns out unusable (flowchart-genre) — then ship the remaining rules and say so.

- [ ] Steps: failing tests (detection positives/negatives: order+cue+no indication → fires; order without cue → silent; order+indication present → silent; negated order "no need for MRI" → silent; firewall fabricated-quote → None) → implement → author YAMLs → integration: `run_audit("Plan: check HbA1c today.")` yields `necessity|hba1c` with CHI citation; `run_audit("T2DM follow-up. Plan: check HbA1c.")` does not → full suite → commit `feat: medical-necessity validation against CHI criteria` + trailer.

---

### Task 6: Requirement citation upgrades (heart failure, stroke, obesity, CKD, anemia)

**Files:**
- Modify: `data/requirements/{heart-failure,stroke,chronic-kidney-disease,anemia}.yaml` (+ `obesity.yaml` if supported), `tests/test_kb_verification.py` (mandate-set assertion)

**Procedure:**
1. `cli quote` against the new CHI sources: heart failure probes "heart failure", "ejection fraction", "HFrEF", "acute decompensated"; stroke probes "stroke", "ischemic", "documentation"; pick genuinely GOVERNING clauses (state a documentation/classification expectation). Replace the mandate-clause primary citation with the CHI condition-specific clause (keep the mandate clause as secondary); update the YAML comments (RULE A(i) now).
2. Obesity: test `CHI_Guidelines/Bariatric and Metabolic Surgery.pdf` extractability (pdftotext/pdfplumber char count + eyeball whether prose). If prose AND a governing obesity/BMI documentation clause exists → add as source in config.SOURCES (`CHI-BARIATRIC`), rebuild, re-anchor obesity. If flowchart-genre or no governing text → obesity stays mandate-anchored; document the evidence.
3. CKD + anemia: add one CHI secondary citation each (condition-specific governing text from CHI-CKD/CHI-ANEMIA).
4. Update `test_kb_verification.py`'s exact-set assertion to the observed post-upgrade mandate-anchored set (expected: `{"obesity"}` or `set()` — whatever the evidence produced) and the `mandate_anchored_entries` stat expectation; if the set becomes empty, keep Tier-2 logic covered by a unit test that fabricates a mandate-anchored requirement in a tmp store.

- [ ] Steps: rebuild KB → author → run `cli verify` until PASSED (V3-INFO lines now only for the remaining set) → update tests → full suite → commit `feat: CHI condition-specific citations replace mandate anchors` + trailer. Report table: entry → old anchor → new clause_id → evidence.

---

### Task 7: Verification extensions (V2/V3/V5 across all rule types)

**Files:**
- Modify: `src/cdi_kb/verify.py`, `tests/test_kb_verification.py`

**Interfaces:** V2 additionally verifies every `doc_requirements` element citation and every `necessity` rule citation (counted in `citations_checked`). V3 additions: per doc-type file, query `"<doc_type words> documentation requirements"` → a cited section of that file's elements in top-5; per necessity rule, query `"<display_name> criteria indications"` → a cited section top-5. V5: exactly 5 doc-type files (the DOC_TYPES set), exactly 5 necessity rules, every element/rule citation-bearing. Stats gain `doc_type_rules` (element count) and `necessity_rules`.

- [ ] Steps: failing stat/coverage tests → implement → `cli verify` PASSED → full suite → commit `feat: verification covers doc-type and necessity rule layers` + trailer.

---

### Task 8: CLI/Web doc-type UX + eval extension + runbook

**Files:**
- Modify: `src/cdi_kb/cli.py` (`--doc-type` choice arg, print active type), `src/cdi_kb/webapp.py` (dropdown Auto + 5 types, POST field `doc_type`, display `active_doc_type` in results), `tests/test_cli.py`, `tests/test_webapp.py`, `tests/test_eval_suite.py` (count 40 → 48), `README-DEMO.md`
- Create: 8 eval notes + `expected.yaml` entries — `discharge-summary-gap/control.txt` (typed via a "DISCHARGE SUMMARY" header so auto-detect exercises), `diagnosis-list-gap/control.txt`, `necessity-hba1c-gap/control.txt`, `necessity-b12-gap/control.txt`. Gap/control engineering rules identical to Task 12 of the prior plan (check the actual YAML evidence_terms; controls contain them, gaps don't; expected.yaml `must_find`/`must_not_find` with the new dedupe-key formats).

- [ ] Steps: author notes + expected → failing eval/UI tests → implement CLI/web changes → full suite → README-DEMO.md updates (new commands incl. `--doc-type`, new verify stats block pasted from a real run, CHI sources listed, honest limits: flowcharts pending API credits, obesity outcome as found in Task 6, pediatric-context limitation) → commit `feat: doc-type UX, extended eval suite, runbook` + trailer.

---

## Self-review notes (performed at plan time)

- Spec coverage: spec §1 → Tasks 3, 4, 8; §2 → Tasks 1, 2, 6; §3 → Task 5; §4 → Tasks 3, 5, 8; §5 → Tasks 2, 7, 8. Risks section honored (page-anchored ids Task 1, per-source V1 Task 2, override-wins Task 3/8).
- Type consistency: `DocType`/`DOC_TYPES` (Task 3) consumed by Tasks 4, 8; `_verified_citations` (Task 4) consumed by Task 5's composer; `SourceDoc`/`SOURCES` (Task 1) consumed by Tasks 2, 6; dedupe-key formats pinned in Global Constraints and used in Tasks 4, 5, 8.
- Deliberate execution-time decisions (not placeholders): obesity re-anchoring depends on Bariatric PDF genre (Task 6 defines both branches + evidence requirement); mandate-set test update depends on Task 6's outcome (both cases specified); necessity doc usability caveat (Task 5) has a defined degrade path.
