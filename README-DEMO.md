# CDI Audit KB — Demo Runbook

## One-time setup
    /c/python/python -m pip install -e ".[dev]"
    /c/python/python -m cdi_kb.cli build-kb

## Sources in the KB (11)
| source_id | title | authority | genre |
|---|---|---|---|
| CDI-2021 | CDI Course Booklet – Clinicians (2021) | TCC | booklet |
| CHI-HF | CHI Heart Failure Guideline | CHI | chi_prose |
| CHI-CKD | CHI Chronic Kidney Disease Guideline | CHI | chi_prose |
| CHI-ANEMIA | CHI Anemia Guideline | CHI | chi_prose |
| CHI-STROKE | Saudi Stroke Standards | CHI | chi_prose |
| CHI-BARIATRIC | CHI Bariatric and Metabolic Surgery Guidelines | CHI | chi_prose |
| CHI-LRTI | CHI Lower Respiratory Tract Infections Management Protocol | CHI | chi_prose |
| CHI-NEC-HBA1C | CHI Necessity Criteria: HbA1c | CHI | necessity |
| CHI-NEC-FBG | CHI Necessity Criteria: Fasting Blood Glucose | CHI | necessity |
| CHI-NEC-UCULT | CHI Necessity Criteria: Urine Culture (Pediatrics) | CHI | necessity |
| CHI-NEC-B12 | CHI Necessity Criteria: Vitamin B12 | CHI | necessity |

## Prove the KB matches the source documents
    /c/python/python -m cdi_kb.cli verify
Latest run (all 11 INFO lines):

    INFO  V3-INFO acute kidney injury: retains generic-authority citation (mandate clause) alongside condition-specific clauses — at least one axis may rest on generic authority only
    INFO  V3-INFO acute kidney injury: cited section reachable by title query only (index diluted by multi-source content)
    INFO  V3-INFO chronic kidney disease: retains generic-authority citation (mandate clause) alongside condition-specific clauses — at least one axis may rest on generic authority only
    INFO  V3-INFO diabetes mellitus: cited section reachable by title query only (index diluted by multi-source content)
    INFO  V3-INFO heart failure: retains generic-authority citation (mandate clause) alongside condition-specific clauses — at least one axis may rest on generic authority only
    INFO  V3-INFO heart failure: cited section reachable by title query only (index diluted by multi-source content)
    INFO  V3-INFO obesity: retains generic-authority citation (mandate clause) alongside condition-specific clauses — at least one axis may rest on generic authority only
    INFO  V3-INFO stroke: retains generic-authority citation (mandate clause) alongside condition-specific clauses — at least one axis may rest on generic authority only
    INFO  V3-INFO stroke: cited section reachable by title query only (index diluted by multi-source content)
    INFO  V3-INFO surgical wound infection: retains generic-authority citation (mandate clause) alongside condition-specific clauses — at least one axis may rest on generic authority only
    INFO  V3-INFO doc:diagnosis_list: cited section reachable by title query only (index diluted by multi-source content)
    stats: {'clauses': 2746, 'requirements': 20, 'citations_checked': 68, 'mandate_anchored_entries': 0, 'title_reachable_entries': 5, 'mixed_authority_entries': 6, 'doc_type_rules': 19, 'necessity_rules': 4, 'sources': 11, 'clauses_CDI-2021': 768, 'clauses_CHI-HF': 721, 'clauses_CHI-CKD': 591, 'clauses_CHI-ANEMIA': 110, 'clauses_CHI-STROKE': 443, 'clauses_CHI-BARIATRIC': 54, 'clauses_CHI-LRTI': 18, 'clauses_CHI-NEC-HBA1C': 9, 'clauses_CHI-NEC-FBG': 8, 'clauses_CHI-NEC-UCULT': 15, 'clauses_CHI-NEC-B12': 9}
    VERIFICATION PASSED

(On a cp1252 Windows console the em dash in the INFO lines above can render
as `�`; the underlying UTF-8 text is correct — confirmed via a direct
`encoding="utf-8"` file dump, not a data bug.)

## Run the demo
    /c/python/python -m cdi_kb.cli demo --port 8000
Open http://localhost:8000 — paste any note from `data/eval/notes/`.

The page has a **Document type** dropdown: *Auto* (the default — the note's
own shape decides) plus the 5 concrete types (Discharge summary, Admission
note, Progress note, Emergency note, Diagnosis list). It is sent as `doc_type`
in the `POST /api/audit` body (omitted/`null` for Auto). The response echoes
`active_doc_type`, and the results panel shows **"Detected/selected type: X"**
above the finding count.

## CLI audit
    /c/python/python -m cdi_kb.cli audit <note_file> [--doc-type auto|discharge_summary|admission_note|progress_note|emergency_note|diagnosis_list] [--llm] [--json]

`--doc-type` defaults to `auto` (note-shape auto-detection); any other choice
overrides detection, exactly like the web dropdown. Human output always
prints the resolved type as its first line: `doc type: <active_doc_type>`.
JSON output already carries `active_doc_type` at the top level (it's a field
on `AuditResult`, serialized by `dataclasses.asdict`).

Auto-detected discharge summary:

    /c/python/python -m cdi_kb.cli audit data/eval/notes/sepsis-gap.txt
Latest run:

    doc type: any
    [required] sepsis — missing agent
      Sepsis is documented without the causative organism or without specifying whether it is severe sepsis or septic shock. Please document the infective agent and the severity classification of the sepsis, if known.
      source: CDI-2021/sepsis/p1 (p.118) — "The infective agent should be documented and confirmed by the clinician, including any ant..."
    [required] sepsis — missing type
      Sepsis is documented without the causative organism or without specifying whether it is severe sepsis or septic shock. Please document the infective agent and the severity classification of the sepsis, if known.
      source: CDI-2021/sepsis/p1 (p.118) — "The infective agent should be documented and confirmed by the clinician, including any ant..."
    2 finding(s)

`--doc-type` overriding a discharge-shaped note (completeness-gap findings,
`doc_type|element` dedupe keys):

    /c/python/python -m cdi_kb.cli audit data/eval/notes/discharge-summary-gap.txt --doc-type discharge_summary
Latest run:

    doc type: discharge_summary
    [required] pneumonia — missing agent
      ...
    [recommended] discharge_summary — missing medications_on_discharge
      The discharge summary does not list medications on discharge. ...
    [required] discharge_summary — missing follow_up_plan
      The discharge summary does not document follow-up care. Please document the follow-up plan, including appointment dates/times or who is responsible for booking them.
      source: CDI-2021/discharge-summary/p9 (p.67) — "Documentation of follow-up care is mandatory. This includes dates and times of appointment..."
    3 finding(s)

A necessity-mismatch finding (`necessity|<order>` dedupe key):

    /c/python/python -m cdi_kb.cli audit data/eval/notes/necessity-hba1c-gap.txt
Latest run:

    doc type: any
    [required] hba1c — missing indication
      An HbA1c order is documented without a supporting indication. Please document the indication, if applicable (e.g. diabetes risk factors, signs/symptoms of diabetes, or known diabetes/prediabetes follow-up).
      source: CHI-NEC-HBA1C/pg3/p2 (p.3) — "This guidance focuses on testing hemoglobin A1c (HbA1c) levels for screening, diagnosis an..."
      source: CHI-NEC-HBA1C/pg4/p2 (p.4) — "HbA1c testing is indicated in patients presenting with signs or symptoms of diabetes melli..."
    1 finding(s)

## Test suites
    /c/python/python -m pytest            # offline suite (KB verification V1-V5, doc-type/necessity rules, 48-note eval)
    /c/python/python -m pytest -m live    # LLM inference tests (needs ANTHROPIC credentials)
Latest offline run:

    209 passed, 1 deselected in 44.46s

Live LLM inference test: **verified**, not pending — `.env` is wired
(`ANTHROPIC_API_KEY=sk-ant-...`, template in `.env.example`; loaded
automatically, an exported environment variable or `ant auth login` also
works and takes precedence) and the account has credits:

    /c/python/python -m pytest -m live -v
    tests/test_llm_infer.py::test_live_inference_names_respiratory_failure PASSED
    1 passed, 209 deselected

End-to-end confirmation of implicit-condition inference:

    /c/python/python -m cdi_kb.cli audit data/eval/notes/chronic-kidney-disease-gap.txt --llm
returns the deterministic CKD findings plus an inferred `heart failure` finding
(oxygen/diuretic treatment implies HF without the word ever appearing in the
note), each still routed through the same citation firewall as every other
finding.

## What this demo proves / does not prove
Proves: a 3-layer KB (booklet + 6 CHI condition-specific guidelines + 4 CHI
necessity-criteria docs, 11 sources / 2,746 clauses) with citation-verified
findings across three finding types — diagnosis-specificity gaps (20
conditions), doc-type completeness gaps (5 doc types, 19 elements), and
order-necessity mismatches (4 rules); every finding traceable to verbatim
source text; deterministic core; LLM inference (now live-verified, see above)
contained behind the same citation firewall. Doc-type auto-detection lets the
CLI/web UI pick the right completeness rules from the note's own shape, with
an explicit override always available.

### Honest limits
- **Flowchart CPGs pending API credits.** Three CHI guidelines are
  flowchart-genre PDFs (Diabetes Mellitus, Urinary Tract Infection, Low Back
  Pain MRI) — no linear prose to chunk and cite. They need VLM (vision-model)
  linearization before they can enter the KB as sources; that step needs API
  credits for the vision calls and has not been run. Not a text-extraction
  bug — these PDFs are diagrams, not paragraphs. (The Lower Respiratory Tract
  Infection protocol was previously assumed to be in this group; it extracts
  as prose and is now source `CHI-LRTI` — page 3 is clean paragraphs, page 6
  opens with clean HAP/VAP bullets before degrading into a dosing table, and
  the dosing tables on pages 4–5 and 7 extract garbled-but-verbatim; only the
  clean sentences are quoted.)
- **Obesity's `type` axis is generic-authority only.** Obesity's `stage`
  (BMI) axis cites the CHI Bariatric guideline directly (`CHI-BARIATRIC/pg9`).
  Its `type` axis still cites only the generic specificity mandate
  (`CDI-2021/documenting-for-specificity`): the guideline's own BMI-class
  table (Class I/II/III) exists but is structurally lost by the chunker's
  heading heuristic (each class-label line reads as a heading, so no body
  text ever accumulates under it) — not stretched into a quote, left honest
  instead (see `.superpowers/sdd/task-6-report.md` for the full evidence).
- **Urine-culture necessity rule is pediatric-scoped and level "recommended."**
  The CHI source's own scope is healthy children 3 months–14 years with a
  first UTI, excluding hospitalized patients — population/setting can't be
  verified from note text alone, so the rule is authored at "recommended"
  rather than "required" (see `data/necessity/urine-culture.yaml`).
- **Necessity detection is a text heuristic, not an order feed.** All 4
  necessity rules (HbA1c, fasting glucose, urine culture, vitamin B12) detect
  an order from nearby verb phrasing ("ordered", "will obtain", a bare
  "Plan:" line, etc.) — there is no real order/CPOE integration. Documented
  residual risk in `src/cdi_kb/necessity.py`: phrasing outside the tested word
  lists can still misfire (e.g. "Requested HbA1c printout" or "Please check
  HbA1c copy" would still fire — "printout"/"copy" name a result but aren't in
  either guard word list). New false positives get closed by tightening a
  guard, never by weakening it past what its positive-control tests require.
- **Doc-type auto-detection needs the title within the first 2 non-empty
  lines.** `detect_doc_type`'s header check only looks at a note's first two
  non-empty lines (e.g. "DISCHARGE SUMMARY" or "## Admission Note"); a title
  buried deeper, or a note with no title at all relying on SOAP markers /
  numbered-list shape, may fall back to "any" or misdetect. The `--doc-type`
  flag (CLI) and the dropdown (web) always override detection — use them when
  the note's shape is ambiguous or the title isn't near the top.
- Three of the 20 diagnosis-specificity conditions — heart failure, obesity,
  and stroke — retain a generic-authority (mandate) citation *alongside* a
  condition-specific one (`mixed_authority_entries`, visible as V3-INFO
  above); acute kidney injury, chronic kidney disease, and surgical wound
  infection share the same pattern.

Does not include (per proposal): dense/hybrid retrieval + reranking, the
browser extension, de-identification, Arabic notes.
