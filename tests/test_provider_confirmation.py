"""Provider-confirmation findings: a diagnosis recorded only by allied health.

Authority (CDI-2021/allied-health/p2, p.130) is conditional, and the condition
is exactly what this check tests:

    "Allied Health professionals whose documentation supports the classification
     of specific clinical diagnoses are considered 'clinicians' ... as long as
     they add further specificity to an already documented condition that was
     originally recorded by the treating doctor."

So allied-health documentation counts as clinician documentation only when the
treating doctor already recorded the condition. When nothing outside the
allied-health segment names it, that precondition fails and the note needs a
query -- the single strongest finding available on a note whose dietitian
documented severe malnutrition while the physician's plan said only
"Nutrition - dietitian following".
"""

import pytest

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.requirements_model import load_provider_rules, load_requirements

_DIETITIAN_ONLY = """PROGRESS NOTE

SUBJECTIVE:
72 y/o male, poor oral intake.

Dietitian note (08-27):
  Assessment: Severe protein-calorie malnutrition. BMI 16.3.

ASSESSMENT / PLAN:
1. Nutrition — dietitian following.
"""

_ALSO_IN_THE_PLAN = """PROGRESS NOTE

SUBJECTIVE:
72 y/o male, poor oral intake.

Dietitian note (08-27):
  Assessment: Severe protein-calorie malnutrition. BMI 16.3.

ASSESSMENT / PLAN:
1. Severe malnutrition — high-protein supplements commenced.
"""

_NURSING_ONLY = """PROGRESS NOTE

SUBJECTIVE:
72 y/o male, drowsy.

Nursing documentation (08-27):
  Sacral wound assessed — Stage 3 pressure injury, present on admission.

ASSESSMENT / PLAN:
1. Continue current management.
"""


def test_provider_rules_load_with_verifiable_citations() -> None:
    rules = load_provider_rules(config.PROVIDER_RULES_DIR)
    assert rules, "at least the allied-health rule must be authored"
    for rule in rules:
        assert rule.citations, f"{rule.role} rule has no citation"


def test_condition_recorded_only_by_allied_health_raises_a_confirmation_finding() -> None:
    result = run_audit(_DIETITIAN_ONLY)
    finding = [f for f in result.findings if f.dedupe_key == "malnutrition|provider_confirmation"]
    assert finding, [f.dedupe_key for f in result.findings]
    assert finding[0].finding_type == "provider_confirmation"
    assert finding[0].citations, "the finding must carry a verified citation"


def test_no_confirmation_finding_when_the_condition_also_appears_outside_allied_health() -> None:
    result = run_audit(_ALSO_IN_THE_PLAN)
    assert "malnutrition|provider_confirmation" not in {f.dedupe_key for f in result.findings}


def test_nursing_only_condition_raises_no_confirmation_finding() -> None:
    """RULE B, pinned as an executable gap.

    The booklet's allied-health definition (CDI-2021/allied-health-request-and-
    allied-health-note/p1) lists dietetics, physiotherapy, occupational therapy,
    speech therapy, podiatry, social work, pastoral care, orthotics and pharmacy
    -- nursing is not among them, and no clause in this KB makes physician
    confirmation of a nursing-recorded diagnosis a documentation requirement.
    Authoring one anyway would mean citing authority the documents do not carry.
    A nursing-only pressure injury therefore raises nothing here, which is a real
    coverage gap, not a passing behaviour to be satisfied with.
    """
    result = run_audit(_NURSING_ONLY)
    assert "pressure injury|provider_confirmation" not in {f.dedupe_key for f in result.findings}


def test_confirmation_finding_is_not_raised_for_a_negated_condition() -> None:
    note = ("PROGRESS NOTE\n\nSUBJECTIVE:\nReviewed.\n\n"
            "Dietitian note (08-27):\n  No evidence of malnutrition. Intake adequate.\n")
    result = run_audit(note)
    assert "malnutrition|provider_confirmation" not in {f.dedupe_key for f in result.findings}


@pytest.mark.parametrize("doc_type", ["progress_note", "discharge_summary", None])
def test_confirmation_finding_is_doc_type_independent(doc_type) -> None:
    # The governing clause is in the general Allied Health chapter, not a
    # doc-type section, so the check applies to any note shape.
    result = run_audit(_DIETITIAN_ONLY, doc_type=doc_type)
    assert "malnutrition|provider_confirmation" in {f.dedupe_key for f in result.findings}


def test_every_requirement_condition_is_reachable_by_the_confirmation_check() -> None:
    # The check keys off detect_conditions, so it covers the whole requirement
    # model rather than a hand-listed subset.
    from cdi_kb.audit import _unconfirmed_conditions
    from cdi_kb.segments import segment_note

    requirements = load_requirements(config.REQUIREMENTS_DIR)
    note = ("PROGRESS NOTE\n\nS: reviewed.\n\n"
            "Physiotherapy note (08-27):\n  Marked deconditioning after prolonged bed rest.\n")
    unconfirmed = _unconfirmed_conditions(note, requirements, segment_note(note))
    assert "deconditioning" in {c for c, _ in unconfirmed}
