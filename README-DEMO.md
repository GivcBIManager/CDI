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

    284 passed, 2 deselected in 61.03s

Live LLM inference test: **verified**, not pending — `.env` is wired
(`ANTHROPIC_API_KEY=sk-ant-...`, template in `.env.example`; loaded
automatically, an exported environment variable or `ant auth login` also
works and takes precedence) and the account has credits:

    /c/python/python -m pytest -m live -v
    tests/test_llm_infer.py::test_live_stage_infers_respiratory_failure_and_validates_it_against_the_kb PASSED
    tests/test_llm_infer.py::test_live_stage_never_cites_a_clause_outside_the_retrieved_candidates PASSED
    2 passed, 284 deselected

## The `--llm` stage: the KB is the validation authority
`--llm` is a two-pass, retrieval-backed pipeline, not a one-shot classifier.
The rule it implements: the model first infers, understands and analyzes the
note; every observation is then **validated against the provided documents**
before it may be reported; and if nothing in the documentation relates to it,
the finding is still reported, marked **`no reference in the KB`**.

    Pass A  analyze     note + condition/axis catalogue -> observations
                        (no KB text is sent; this pass is pure clinical reading)
    ------  note-side firewall: the observation's evidence must be VERBATIM note
            text (normalize.find_quote, threshold 0.95) or it is discarded
    ------  retrieve     SearchIndex BM25 -> CANDIDATE_LIMIT clauses, from a query
                         built ONLY from KB-side vocabulary (condition, axis,
                         synonyms) so the candidate set never depends on the
                         model's phrasing
    Pass B  validate     retrieved clause TEXT -> which clauses actually govern
                         this observation, quoted verbatim
    ------  KB-side firewall: clause_id must be in the retrieved candidate set,
            must exist in the store, and its quote must match the clause verbatim
            (findings._verified_citations — the same single audited path every
            other finding type uses)

Nothing survives that the documents did not support, and nothing is dropped for
lacking support — it is labelled. There is deliberately **no fallback** to the
requirement YAML's own pre-authored citations: those were never validated
against this particular observation, and using them would defeat the rule.

The axis decision is the model's, not `gapcheck.scan_axes`'. That matters: the
deterministic scanner searches the whole note, so an organism named in a culture
result marked sepsis's `agent` axis satisfied and suppressed the single highest
-value query in the note. The model judges the axis against the statement that
actually concerns the condition.

It judges conditions the note **names**, too. An earlier design skipped any
condition mentioned anywhere in the note, which locked the model out of exactly
the axes the scanner gets wrong. That blanket gate is now two narrower ones:
never contradict an explicit negation (`_fully_negated_conditions` — every
mention negated, not any, so "no sepsis on admission ... now in septic shock"
still raises), and never duplicate a `condition|axis` the deterministic pass
already emitted. A *dropped* citation is not a duplicate: the deterministic pass
raised nothing there, so the LLM re-reaching that axis by retrieval is new
authority.

Lifting the gate took a real progress note from 3 observations to 10, i.e. ten
Pass B round trips. They are independent, so they run concurrently
(`VALIDATION_CONCURRENCY`), and the client is a module singleton rather than
rebuilt per call — that note went from timing out past ten minutes to 91
seconds. A validator that raises fails the whole batch rather than being
swallowed into an empty support list: an empty list means "the documents carry
nothing on this point" and is shown to a clinician as such, so a transport
failure must never be laundered into that claim.

An inference failure can no longer take an audit down. The stage is wrapped;
`AuditResult.llm_error` carries the reason and the deterministic findings are
still returned (CLI prints `llm stage unavailable (...) — deterministic findings
only`; the web UI shows the same line).

Example on a 5-day internal-medicine progress note that names none of them:

    [required]    sepsis — missing agent          supported (CDI-2021/sepsis/p1)
    [required]    acute kidney injury — missing onset
                                                  supported (CDI-2021/renal-failure-impairment/p1)
    [required]    diabetes mellitus — missing type
                                                  supported (CDI-2021/cataracts/p1)
    [recommended] acute kidney injury — missing type
                                                  no reference in the KB

That last line is the rule working, not failing: `acute-kidney-injury.yaml`'s own
`# DEVIATION` comment records that the booklet carries no pre-renal/intrinsic/
post-renal classification text. The validation pass reached the same conclusion
from the documents, independently of the comment.

## Author attribution: who wrote the diagnosis
`segments.py` splits a note into role-tagged spans — `physician`, `nursing`,
`allied_health`, `unattributed` — because a ward note is not one document by one
author. A segment opens on a heading that names an author role ("Dietitian note
(08-27):") and closes at the next author heading **or** at the next structural
heading of the note's own body ("ASSESSMENT / PLAN:"), which returns the note to
its own writer.

That second boundary is not cosmetic. Without it a trailing plan after an inline
consult inherits the consultant's role, and a diagnosis the treating doctor *did*
record raises a false finding — on the commonest note shape there is.

Text before any author heading is `unattributed`, never `physician`. The body
usually is the doctor's, but nothing in the text says so, and the check below
treats unattributed as possibly-physician — so a wrong guess suppresses a finding
rather than inventing one.

This powers a fourth finding type, `provider_confirmation`. Its authority
(`CDI-2021/allied-health/p2`, p.130) is a conditional, and the check tests
exactly its condition:

> Allied Health professionals whose documentation supports the classification of
> specific clinical diagnoses are considered 'clinicians' … **as long as they add
> further specificity to an already documented condition that was originally
> recorded by the treating doctor.**

So when every mention of a condition falls inside an allied-health segment, that
precondition fails:

    [recommended] malnutrition — not confirmed by the treating doctor
                  (documented in the allied_health note)
      source: CDI-2021/allied-health/p2 (p.130)
      source: CDI-2021/allied-health-request-and-allied-health-note/p13 (p.74)

Authored at `recommended`, not `required`: a single-note audit cannot rule out
that the doctor recorded the condition elsewhere in the chart — the same
reasoning that keeps the pediatric urine-culture necessity rule at
`recommended`.

## What this demo proves / does not prove
Proves: a 3-layer KB (booklet + 6 CHI condition-specific guidelines + 4 CHI
necessity-criteria docs, 11 sources / 2,746 clauses) with citation-verified
findings across four finding types — diagnosis-specificity gaps (20
conditions), doc-type completeness gaps (5 doc types, 19 elements),
order-necessity mismatches (4 rules), and provider-confirmation gaps
(allied-health-only diagnoses, via author-role segmentation); every finding traceable to verbatim
source text; deterministic core; retrieval-backed LLM inference (live-verified,
see above) in which the KB is the validation authority — every inferred finding
is checked against retrieved clause text through the same citation firewall, and
one the documents do not support is reported as `no reference in the KB` rather
than dropped or given borrowed authority. Doc-type auto-detection lets the
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
- **Retrieval reaches 31 of 37 requirement axes.** Measured and pinned by
  `test_retrieval_reach_across_every_requirement_axis`: for 31 axes the
  candidate set can surface at least one clause that requirement itself names
  as governing. The six it cannot — `heart failure|type`, `heart failure|onset`,
  `obesity|type`, `obesity|stage`, `stroke|type`, `stroke|onset` — are the
  `mixed_authority_entries` above, and their CHI clauses extract as
  space-stripped runs (`TheclassificationforbaselineandsubsequentLVEFisshown`)
  that tokenize as a single term matching no condition or axis word. For those
  axes the `--llm` path will report `no reference in the KB`. That is a
  chunking problem in the CHI PDFs, not a retrieval-tuning one: widening the
  candidate window plateaus (29/37 at limit 8, 31/37 from 16 onward, no further
  gain out to 40), which is why `CANDIDATE_LIMIT` is 16.
- **The validation verdict is model-judged, so it is not bit-stable.** Across
  repeated `--llm` runs on the same note, an observation whose only governing
  clause is a weak or generic one can come back `supported` on one run and
  `no reference in the KB` on the next (observed on `acute kidney injury|onset`,
  whose sole authority is the acuity sentence in `renal-failure-impairment/p1`).
  The firewalls are deterministic; the judgment in front of them is not. Where
  the authority is unambiguous the verdict is stable across runs.
- **The LLM stage adds findings; it does not correct deterministic ones.**
  Four deterministic defects found by auditing a real progress note have been
  fixed at the source instead (see `tests/test_deterministic_fixes.py`):
  the `ARF` abbreviation collision, now cue-disambiguated
  (`requirements_model.AmbiguousSynonym` — `ARF` is claimed by acute kidney
  injury or acute respiratory failure only when a renal or respiratory cue sits
  within 200 characters, and by neither when nothing disambiguates it);
  `pressure injury|site` firing on "Sacral" against a `sacrum`-only term list;
  the condition-level `recommendation` printing *agent* advice under a
  `missing site` heading (axes may now carry their own `recommendation`); and
  `presenting_complaint_management` matching only booklet vocabulary, so a
  twelve-item assessment/plan still read as missing. On that note the
  deterministic pass went from 7 findings (two false positives, one condition
  mis-assigned, one misleading query text) to 5, all defensible.
- **`presenting_complaint_management` still needs a Plan heading.** A note
  documenting management purely in narrative ("Continued meropenem, held
  antihypertensives") with no `Plan:` heading and none of the element's phrases
  still reports it missing. Treatment verbs were considered and rejected:
  `ALLOWED_SINGLE_WORD_TERMS`' convention admits clinical acronyms only, never
  ordinary English words, and widening it would trade a false positive for
  silent suppression of real gaps. Closing this needs note structure, not more
  terms.
- **No nursing provider-confirmation rule.** The booklet defines allied health
  (`CDI-2021/allied-health-request-and-allied-health-note/p1`, p.74) as
  dietetics, physiotherapy, occupational therapy, speech therapy, podiatry,
  social work, pastoral care, orthotics and pharmacy — nursing is not among
  them, and no clause in this KB makes physician confirmation of a
  nursing-recorded diagnosis a documentation requirement. A nursing-only Stage 3
  pressure injury therefore raises nothing. Authoring the rule anyway would mean
  citing authority the documents do not carry; the gap is pinned instead by
  `test_nursing_only_condition_raises_no_confirmation_finding`.
- **Segmentation is heading-based.** A note that resumes the doctor's voice with
  no heading at all, or under a structural heading not in `_BODY_HEADINGS`,
  carries the previous author's role forward. Closing that needs real authorship
  metadata from the EMR, not more heading patterns.
- **The LLM can add findings but cannot retract deterministic ones.** It now
  judges axes for conditions the note names (see below), so it closes the string
  scanner's false *negatives* — but a deterministic false positive still stands
  even when the model would disagree. Suppression is a separate feature and
  carries its own risk (a model retracting a true finding), so it was not built
  here.
- **Negation is still a fixed 40-character pre-mention window.** The
  `_fully_negated_conditions` guard is only as good as `gapcheck._is_negated`
  underneath it, so an affirmation packed within 40 characters of a negation
  ("No sepsis on admission. Day 3: now in septic shock") reads as negated and
  suppresses the finding. Ordinary note spacing clears it; dense shorthand may
  not.

Does not include (per proposal): dense/hybrid retrieval + reranking, the
browser extension, de-identification, Arabic notes.
