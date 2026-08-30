# Doc-Type-Aware Rules, CHI Second Authority & Medical-Necessity Validation — Design

**Date:** 2026-08-30 · **Status:** Approved by user (option 2 + doc-type default approach, 2026-08-30 conversation)
**Extends:** the merged KB demo (see `docs/superpowers/plans/2026-08-27-cdi-kb-demo.md`, proposal §2 contracts)

## Goals

1. Requirements differentiate by the note's location in the patient file (discharge summary, progress note, admission note, emergency note, diagnosis list).
2. CHI guidelines become a second citation authority for the 20 diagnoses (prose-extractable docs only), upgrading the mandate-anchored entries where CHI has condition-specific text.
3. A new CHI validation step: medical-necessity checks — orders mentioned in free text validated against CHI necessity-criteria documents.

## Non-Goals

CHI flowchart linearization (blocked: API account has no credits); ICD-10-AM/ACHI code validation (no licence); frequency/interval necessity rules (needs dates); management-conformance checking; Arabic notes; pediatric-context detection for the urine-culture rule (documented limitation).

## 1. Doc-type awareness

- `DocType` literal in `requirements_model.py`: `"discharge_summary" | "admission_note" | "progress_note" | "emergency_note" | "diagnosis_list" | "any"`.
- `detect_doc_type(note_text) -> DocType` (new module `doctype.py`): header regex over the first 400 chars (e.g. "discharge summary" → `discharge_summary`; "admission"/"clerking"/"history & physical" → `admission_note`; SOAP markers (`S:`/`O:`/`A:`/`P:` as line starts, ≥3 of 4) or "progress note" → `progress_note`; "emergency"/"ED note"/"triage" → `emergency_note`); `diagnosis_list` when the note has ≥3 non-empty lines, ≥60% of them shorter than 60 chars, and no sentence-terminated prose lines; fallback `"any"`. Manual override always wins (CLI `--doc-type`, web dropdown, API field).
- `AxisRule` gains `applies_to: list[DocType]` (default `["any"]` — the existing 20 YAMLs stay valid unchanged). A rule fires when `"any" in applies_to`, or the active doc type is in `applies_to`, or the active doc type is `"any"` (unknown → everything fires; recall over precision, preserves current behavior).
- **Per-location completeness rules** — new `data/doc_requirements/<doc_type>.yaml` (5 files), schema `DocTypeRequirement(doc_type, elements: list[Element])`, `Element(name, evidence_terms, level, recommendation, citations)`. Elements sourced ONLY where the booklet's "Different Types of Documentation" / "Documentation Concepts" chapters support them (discharge summary pp. 67–69 & 81, admission p. 70, progress/SOAP p. 71, emergency p. 69, principal/additional diagnosis pp. 56–58). Same RULE A/B/C discipline as diagnosis rules: no supporting clause → element dropped or `recommended`, with a YAML comment.
- Findings: `finding_type="completeness_gap"`, `condition=<doc_type>`, `axis=<element name>`, `dedupe_key="<doc_type>|<element>"`. Composed by a new firewalled composer in `findings.py` sharing one private citation-verification helper with `compose_finding` (single audited firewall path).

## 2. CHI second authority (multi-source KB)

- `config.SOURCES: dict[str, SourceDoc(path, title, authority)]` — registry replacing the implicit single booklet: `CDI-2021` (booklet) + prose CHI docs `CHI-HF` (Heart Failure.pdf, 838K chars), `CHI-CKD` (Chronic Kidney Disease.pdf, 813K), `CHI-ANEMIA` (Anemia.pdf, 50K), `CHI-STROKE` (Saudi Stroke Standards.pdf, 239K) + necessity docs `CHI-NEC-HBA1C`, `CHI-NEC-FBG`, `CHI-NEC-UCULT`, `CHI-NEC-B12`, `CHI-NEC-LBPMRI`. Extractability of each is asserted at build time; a source failing extraction fails the build loudly.
- CHI prose chunker (booklet keeps its TOC chunker): heading heuristic — a heading is a line matching `^\d+(\.\d+)*\s+\S` (numbered) or a short Title-Case line (<70 chars, no terminal period); paragraphs under the last seen heading; page-paragraph fallback when no headings detected. `clause_id = {SRC}/pg<page>/p<n>` (page-anchored — stable and honest for citation). `MIN_CLAUSE_CHARS` unchanged (120).
- Requirement upgrades (data work, `cli quote` procedure): heart failure and stroke get condition-specific CHI primary citations (clearing their V3-INFO status); CKD and anemia gain CHI secondary citations; obesity checked against `Bariatric and Metabolic Surgery.pdf` extractability at execution — if flowchart-genre, obesity honestly stays mandate-anchored. The verification test asserting the mandate-anchored set updates to the new expected set.

## 3. Medical-necessity validation

- New `data/necessity/<order>.yaml` (5 rules: hba1c, fasting-glucose, urine-culture, vitamin-b12, lumbar-mri), schema `NecessityRule(order, display_name, order_terms, context_cues, valid_indication_terms, level (default "required"), recommendation, citations)`.
- Detection (`necessity.py`): order term present (word-boundary, wrap-tolerant `\s+` joins — same discipline as gapcheck) **and** a context cue ("plan", "order(ed)", "request", "check", "send", "repeat") within ±60 chars of the order term **and** the order term not negated (reuse the negation window) **and** no valid-indication term anywhere in the note → `necessity_mismatch` finding, `dedupe_key="necessity|<order>"`, composed through the firewall, citing the CHI criteria clause.
- Documented limitations: text-mention detection only (no CPOE feed, proposal assumption A7); indication scan is note-wide; no frequency rules.

## 4. Audit / UI / CLI integration

- `run_audit(note_text, *, doc_type: DocType | None = None, use_llm: bool = False)`; `None` → auto-detect. `AuditResult` gains `active_doc_type: DocType` so callers can show what was detected. Necessity stage runs after the specificity loop; LLM stage unchanged.
- CLI `audit` gains `--doc-type {auto,discharge_summary,...}` (default auto) and prints the active type. Web UI gains a doc-type dropdown (Auto + 5 types) and displays the detected type with the results.

## 5. Verification & eval extensions

- **V1** runs per source (each clause verified against its own PDF's raw text). **V2** covers all three rule files' citations (diagnosis, doc-type, necessity). **V3** extends: doc-type rules queried as "<doc type words> documentation requirements"; necessity rules as "<order terms> criteria indications"; cited section top-5 as before (Tier-2 mandate path unchanged). **V5** coverage: 20 diagnoses + 5 doc-type files + 5 necessity rules present and citation-bearing. Stats gain `sources`, `doc_type_rules`, `necessity_rules`, and per-source clause counts.
- **Eval**: +8 notes — discharge-summary gap/control, diagnosis-list gap/control, hba1c gap/control, b12 gap/control — wired into `expected.yaml` and the existing eval test (which iterates whatever the YAML lists; only the 40-file count assertion updates to 48).
- Runbook updated: new commands, new stats block, CHI sources listed, limits honest (flowcharts pending credits; obesity outcome as found).

## Risks & mitigations

- CHI heading-chunker quality on 800K-char docs → page-anchored clause IDs make citations stable regardless of heading detection quality; V1 guarantees verbatim fidelity; V3 proves retrievability of the specific clauses we actually cite.
- First extraction of the two huge PDFs is slow (minutes) → cached like the booklet; build-kb prints per-source progress.
- Doc-type auto-detection is heuristic → override always wins; unknown falls back to current fire-everything behavior, so wrong detection can only *narrow* rules when it positively matches a type.
