# CDI Audit KB — Demo Runbook

## One-time setup
    /c/python/python -m pip install -e ".[dev]"
    /c/python/python -m cdi_kb.cli build-kb

## Prove the KB matches the source documents
    /c/python/python -m cdi_kb.cli verify
Latest run:

    INFO  V3-INFO heart failure: generic authority only — no condition-specific clause exists in source; retrieval verified at axis level
    INFO  V3-INFO obesity: generic authority only — no condition-specific clause exists in source; retrieval verified at axis level
    INFO  V3-INFO stroke: generic authority only — no condition-specific clause exists in source; retrieval verified at axis level
    stats: {'clauses': 768, 'requirements': 20, 'citations_checked': 33, 'mandate_anchored_entries': 3}
    VERIFICATION PASSED

## Run the demo
    /c/python/python -m cdi_kb.cli demo --port 8000
Open http://localhost:8000 — paste any note from data/eval/notes/.

## CLI audit
    /c/python/python -m cdi_kb.cli audit data/eval/notes/sepsis-gap.txt
Latest run:

    [required] sepsis — missing agent
      Sepsis is documented without the causative organism or without specifying whether it is severe sepsis or septic shock. Please document the infective agent and the severity classification of the sepsis, if known.
      source: CDI-2021/sepsis/p1 (p.118) — "The infective agent should be documented and confirmed by the clinician, including any ant..."
    [required] sepsis — missing type
      Sepsis is documented without the causative organism or without specifying whether it is severe sepsis or septic shock. Please document the infective agent and the severity classification of the sepsis, if known.
      source: CDI-2021/sepsis/p1 (p.118) — "The infective agent should be documented and confirmed by the clinician, including any ant..."
    2 finding(s)

## Test suites
    /c/python/python -m pytest            # offline suite (KB verification V1-V5 + 40-note eval)
    /c/python/python -m pytest -m live    # LLM inference tests (needs ANTHROPIC credentials)
Latest offline run:

    58 passed, 1 deselected in 16.49s

Live LLM inference test: pending — requires ANTHROPIC_API_KEY (or `ant auth login`); run
`/c/python/python -m pytest -m live -v` once available.

## What this demo proves / does not prove
Proves: 3-layer KB with citation-verified findings for 20 diagnoses; every
finding traceable to verbatim booklet text; deterministic core; LLM inference
contained behind the citation firewall.

Three of those 20 conditions — heart failure, obesity, and stroke — have no
condition-specific clause in the source booklet; their findings cite the
generic specificity mandate instead, and retrieval for them was verified at
axis level rather than condition level (V3 Tier 2, see the V3-INFO lines
above).

Does not include (per proposal): CHI flowchart linearization, dense/hybrid
retrieval + reranking, the browser extension, de-identification, Arabic notes,
live LLM inference verification (pending credentials).
