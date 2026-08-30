from pathlib import Path

import pytest

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.findings import compose_necessity_finding
from cdi_kb.necessity import NecessityGap, find_necessity_gaps
from cdi_kb.requirements_model import Citation, NecessityRule, load_necessity_rules


def _rule(**overrides) -> NecessityRule:
    defaults = dict(
        order="hba1c",
        display_name="HbA1c testing",
        order_terms=["HbA1c"],
        context_cues=["order", "requested", "will obtain", "plan:"],
        valid_indication_terms=["diabetes", "prediabetes", "T2DM"],
        recommendation=(
            "An HbA1c order is documented without a supporting indication. "
            "Please document the indication, if applicable."
        ),
        citations=[Citation(clause_id="CHI-NEC-HBA1C/pg3/p2", quote="q")],
    )
    defaults.update(overrides)
    return NecessityRule(**defaults)


def _store(tmp_path: Path, clauses: list[Clause]) -> ClauseStore:
    store = ClauseStore(tmp_path / "kb.sqlite")
    store.rebuild(clauses)
    return store


def _real_rules() -> list[NecessityRule]:
    return load_necessity_rules(config.NECESSITY_DIR)


# --- schema ---

def test_necessity_rule_defaults_to_required_level() -> None:
    assert _rule().level == "required"


def test_load_necessity_rules_rejects_invalid_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "order: x\ndisplay_name: X\norder_terms: [x]\ncontext_cues: [order]\n"
        "valid_indication_terms: []\nrecommendation: r\ncitations: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bad.yaml"):
        load_necessity_rules(tmp_path)


# --- detection ---

def test_order_with_cue_and_no_indication_fires() -> None:
    gaps = find_necessity_gaps("Plan: order HbA1c today.", [_rule()])
    assert [g.rule.order for g in gaps] == ["hba1c"]


def test_order_without_cue_is_silent() -> None:
    assert find_necessity_gaps("HbA1c mentioned in passing on admission bloods.", [_rule()]) == []


def test_order_with_cue_but_indication_present_is_silent() -> None:
    note = "T2DM follow-up. Plan: order HbA1c."
    assert find_necessity_gaps(note, [_rule()]) == []


def test_negated_order_is_silent() -> None:
    assert find_necessity_gaps("Plan: no need for HbA1c today.", [_rule()]) == []
    assert find_necessity_gaps("Not ordering HbA1c at this time.", [_rule()]) == []


def test_wrap_tolerant_multiword_order_term() -> None:
    # Regression: a note that line-wraps a multi-word order term (e.g. "glycated
    # haemoglobin" as "glycated\nhaemoglobin") must still be recognized -- same
    # whitespace-flexible matching gapcheck.term_pattern already provides.
    rule = _rule(order_terms=["glycated haemoglobin"])
    note = "Plan: order glycated\nhaemoglobin today."
    gaps = find_necessity_gaps(note, [rule])
    assert [g.rule.order for g in gaps] == ["hba1c"]


def test_evidence_excerpt_is_the_matched_note_snippet() -> None:
    # Fix: evidence_excerpt must reflect the actual matched text (order-term
    # match +/- ~40 chars), not a static rule-derived template.
    note = "Background stable. Plan: order HbA1c for routine review today please."
    gaps = find_necessity_gaps(note, [_rule()])
    assert len(gaps) == 1
    assert "HbA1c" in gaps[0].evidence_excerpt
    assert gaps[0].evidence_excerpt != _rule().display_name


# --- reviewer regression: result-reporting text must not fire as a false order ---

def test_hba1c_result_value_is_not_a_false_order() -> None:
    gaps = find_necessity_gaps("HbA1c 8.1% today. Plan: continue home meds.", _real_rules())
    assert gaps == []


def test_fasting_glucose_result_value_is_not_a_false_order() -> None:
    gaps = find_necessity_gaps("Labs: fasting glucose 126. Plan: continue management.", _real_rules())
    assert gaps == []


def test_urine_culture_result_report_is_not_a_false_order() -> None:
    gaps = find_necessity_gaps("Urine culture negative from last admission. Check vitals q4h.", _real_rules())
    assert gaps == []


def test_vitamin_b12_result_value_is_not_a_false_order() -> None:
    # Constructed analogously to the reviewer's HbA1c/FBG examples -- the bug
    # was flagged as "reproduced on all 4 rules" and illustrated with the
    # numeric-result pattern "B12 250" without a full B12 note; this exercises
    # the same numeric-immediately-after guard for the 4th rule.
    gaps = find_necessity_gaps("Vitamin B12 250 pg/mL. Plan: continue current management.", _real_rules())
    assert gaps == []


# --- positive controls: order-specific phrasing must still fire ---

def test_order_verb_still_fires_for_hba1c() -> None:
    gaps = find_necessity_gaps("Plan: order HbA1c.", _real_rules())
    assert [g.rule.order for g in gaps] == ["hba1c"]


def test_requested_still_fires_for_fasting_glucose() -> None:
    gaps = find_necessity_gaps("Requested fasting glucose for tomorrow.", _real_rules())
    assert [g.rule.order for g in gaps] == ["fasting-glucose"]


def test_bare_sent_does_not_fire_for_urine_culture() -> None:
    # "sent" alone is result-adjacent/ambiguous (a completed action can be
    # background for a result report just as easily as it can announce a
    # fresh order) -- deliberately excluded from the cue list in favour of
    # "send for"/"sent for", which unambiguously names an order destination.
    assert find_necessity_gaps("Urine culture sent.", _real_rules()) == []


def test_sent_for_still_fires_for_urine_culture() -> None:
    gaps = find_necessity_gaps("Urine culture sent for analysis; will follow up on results.", _real_rules())
    assert [g.rule.order for g in gaps] == ["urine-culture"]


def test_will_obtain_still_fires_for_vitamin_b12_despite_level_word() -> None:
    # "level" is a result-word candidate, but the result-exclusion guard only
    # checks for it PRECEDING the match (see necessity.py); here it follows,
    # and a strong order-verb cue ("will obtain") precedes the match -- must
    # still fire.
    gaps = find_necessity_gaps("Will obtain vitamin B12 level.", _real_rules())
    assert [g.rule.order for g in gaps] == ["vitamin-b12"]


# --- reviewer re-review regression: result-word AFTER the term (plan-line path) ---

def test_plan_review_b12_result_is_silent() -> None:
    assert find_necessity_gaps("Plan: review B12 result", _real_rules()) == []


def test_plan_discuss_hba1c_results_is_silent() -> None:
    assert find_necessity_gaps("Plan: discuss HbA1c results with patient", _real_rules()) == []


def test_plan_review_fasting_glucose_findings_is_silent() -> None:
    assert find_necessity_gaps("Plan: review fasting glucose findings", _real_rules()) == []


def test_plan_go_over_urine_culture_result_is_silent() -> None:
    assert find_necessity_gaps("Plan: go over urine culture result with parents", _real_rules()) == []


def test_plan_discuss_elevated_hba1c_is_silent() -> None:
    note = "Plan: discuss the elevated HbA1c with patient and adjust insulin"
    assert find_necessity_gaps(note, _real_rules()) == []


def test_plan_order_verb_with_timeframe_still_fires() -> None:
    gaps = find_necessity_gaps("Plan: order HbA1c in 3 months.", _real_rules())
    assert [g.rule.order for g in gaps] == ["hba1c"]


def test_plan_bare_listed_test_still_fires() -> None:
    # No verb at all precedes the term on the "Plan:" line -- a bare listed
    # test is itself an order.
    gaps = find_necessity_gaps("Plan: HbA1c, lipids.", _real_rules())
    assert [g.rule.order for g in gaps] == ["hba1c"]


def test_plan_repeat_still_fires() -> None:
    gaps = find_necessity_gaps("Plan: repeat fasting glucose next visit.", _real_rules())
    assert [g.rule.order for g in gaps] == ["fasting-glucose"]


def test_requested_urine_culture_still_fires() -> None:
    gaps = find_necessity_gaps("Requested urine culture.", _real_rules())
    assert [g.rule.order for g in gaps] == ["urine-culture"]


def test_will_obtain_b12_level_still_fires_not_plan_line() -> None:
    # Not a "plan:" note at all -- the window cue "will obtain" justifies the
    # match directly, so the plan-line-only AFTER-word guard never applies
    # and the trailing "level" does not suppress it.
    gaps = find_necessity_gaps("Will obtain vitamin B12 level.", _real_rules())
    assert [g.rule.order for g in gaps] == ["vitamin-b12"]


# --- reviewer wave-3 regression: result-word AFTER the term on window-cue path ---

def test_requested_hba1c_result_to_be_faxed_is_silent() -> None:
    assert find_necessity_gaps("Requested HbA1c result to be faxed.", _real_rules()) == []


def test_please_check_hba1c_result_before_discharge_is_silent() -> None:
    assert find_necessity_gaps("Please check HbA1c result before discharge.", _real_rules()) == []


def test_nurse_to_obtain_hba1c_result_before_rounds_is_silent() -> None:
    assert find_necessity_gaps("Nurse to obtain HbA1c result before rounds.", _real_rules()) == []


def test_requested_urine_culture_result_be_sent_is_silent() -> None:
    note = "Requested urine culture result be sent to the outside lab."
    assert find_necessity_gaps(note, _real_rules()) == []


def test_sent_for_fasting_glucose_result_from_previous_facility_is_silent() -> None:
    note = "Sent for the fasting glucose result from the previous facility."
    assert find_necessity_gaps(note, _real_rules()) == []


def test_will_obtain_b12_level_still_fires_wave3() -> None:
    # Order-object AFTER-words (level/levels/value/values/reading/readings)
    # are scoped to the plan-line-only path -- a genuine window cue like
    # "will obtain" is not defeated by its own object's trailing attribute.
    gaps = find_necessity_gaps("Will obtain vitamin B12 level.", _real_rules())
    assert [g.rule.order for g in gaps] == ["vitamin-b12"]


def test_requested_fasting_glucose_in_weeks_still_fires() -> None:
    gaps = find_necessity_gaps("Requested fasting glucose in 6 weeks.", _real_rules())
    assert [g.rule.order for g in gaps] == ["fasting-glucose"]


def test_plan_order_hba1c_in_months_still_fires_wave3() -> None:
    gaps = find_necessity_gaps("Plan: order HbA1c in 3 months.", _real_rules())
    assert [g.rule.order for g in gaps] == ["hba1c"]


def test_plan_bare_listed_test_still_fires_wave3() -> None:
    gaps = find_necessity_gaps("Plan: HbA1c, lipids.", _real_rules())
    assert [g.rule.order for g in gaps] == ["hba1c"]


def test_requested_urine_culture_still_fires_wave3() -> None:
    gaps = find_necessity_gaps("Requested urine culture.", _real_rules())
    assert [g.rule.order for g in gaps] == ["urine-culture"]


def test_please_check_hba1c_next_visit_still_fires() -> None:
    gaps = find_necessity_gaps("Please check HbA1c next visit.", _real_rules())
    assert [g.rule.order for g in gaps] == ["hba1c"]


# --- cue matching precision (hyphen boundary, "in order to" idiom) ---

def test_hyphenated_word_does_not_match_bare_cue() -> None:
    # "order-set" must not satisfy the "order" cue (hyphen counts as a
    # boundary for cue words).
    rule = _rule(context_cues=["order"])
    note = "Reviewed the HbA1c order-set today; no changes made."
    assert find_necessity_gaps(note, [rule]) == []


def test_in_order_to_idiom_does_not_match_bare_order_cue() -> None:
    rule = _rule(context_cues=["order"])
    note = "In order to proceed, HbA1c will need review; no action required today."
    assert find_necessity_gaps(note, [rule]) == []


# --- composer / firewall ---

def test_verified_citation_produces_necessity_finding(tmp_path: Path) -> None:
    clause = Clause(
        "CHI-NEC-HBA1C/pg3/p2", "Scope", 3,
        "This guidance focuses on testing hemoglobin A1c (HbA1c) levels for screening.",
    )
    rule = _rule(citations=[Citation(
        clause_id="CHI-NEC-HBA1C/pg3/p2", quote="This guidance focuses on testing hemoglobin A1c",
    )])
    gap = NecessityGap(rule=rule, evidence_excerpt="Plan: order HbA1c today.")
    finding = compose_necessity_finding(gap, _store(tmp_path, [clause]))
    assert finding is not None
    assert finding.finding_type == "necessity_mismatch"
    assert finding.condition == "hba1c"
    assert finding.axis == "indication"
    assert finding.severity == "required"
    assert finding.dedupe_key == "necessity|hba1c"
    assert finding.citations[0].clause_id == "CHI-NEC-HBA1C/pg3/p2"
    assert finding.evidence_excerpt == "Plan: order HbA1c today."


def test_fabricated_quote_yields_no_necessity_finding(tmp_path: Path) -> None:
    clause = Clause("CHI-NEC-HBA1C/pg3/p2", "Scope", 3, "unrelated clause text entirely")
    rule = _rule(citations=[Citation(clause_id="CHI-NEC-HBA1C/pg3/p2", quote="fabricated quote text")])
    gap = NecessityGap(rule=rule, evidence_excerpt="Plan: order HbA1c today.")
    assert compose_necessity_finding(gap, _store(tmp_path, [clause])) is None


def test_unresolvable_clause_id_yields_no_necessity_finding(tmp_path: Path) -> None:
    gap = NecessityGap(rule=_rule(), evidence_excerpt="Plan: order HbA1c today.")
    assert compose_necessity_finding(gap, _store(tmp_path, [])) is None


# --- integration (real KB, real data/necessity/*.yaml) ---

def test_run_audit_flags_hba1c_without_indication() -> None:
    result = run_audit("Plan: order HbA1c today.")
    keys = {f.dedupe_key for f in result.findings}
    assert "necessity|hba1c" in keys
    finding = next(f for f in result.findings if f.dedupe_key == "necessity|hba1c")
    assert any(c.clause_id.startswith("CHI-NEC-HBA1C") for c in finding.citations)


def test_run_audit_does_not_flag_hba1c_with_indication() -> None:
    result = run_audit("T2DM follow-up. Plan: order HbA1c.")
    assert "necessity|hba1c" not in {f.dedupe_key for f in result.findings}


def test_run_audit_does_not_flag_hba1c_result_reporting() -> None:
    result = run_audit("HbA1c 8.1% today. Plan: continue home meds.")
    assert "necessity|hba1c" not in {f.dedupe_key for f in result.findings}
