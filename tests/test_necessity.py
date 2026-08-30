from pathlib import Path

import pytest

from cdi_kb.audit import run_audit
from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.findings import compose_necessity_finding
from cdi_kb.necessity import find_necessity_gaps
from cdi_kb.requirements_model import Citation, NecessityRule, load_necessity_rules


def _rule(**overrides) -> NecessityRule:
    defaults = dict(
        order="hba1c",
        display_name="HbA1c testing",
        order_terms=["HbA1c"],
        context_cues=["check", "order", "ordered", "obtain"],
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


# --- schema ---

def test_necessity_rule_defaults_to_required_level() -> None:
    assert _rule().level == "required"


def test_load_necessity_rules_rejects_invalid_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "order: x\ndisplay_name: X\norder_terms: [x]\ncontext_cues: [check]\n"
        "valid_indication_terms: []\nrecommendation: r\ncitations: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bad.yaml"):
        load_necessity_rules(tmp_path)


# --- detection ---

def test_order_with_cue_and_no_indication_fires() -> None:
    gaps = find_necessity_gaps("Plan: check HbA1c today.", [_rule()])
    assert [g.order for g in gaps] == ["hba1c"]


def test_order_without_cue_is_silent() -> None:
    assert find_necessity_gaps("HbA1c 11.2% on admission bloods.", [_rule()]) == []


def test_order_with_cue_but_indication_present_is_silent() -> None:
    note = "T2DM follow-up. Plan: check HbA1c."
    assert find_necessity_gaps(note, [_rule()]) == []


def test_negated_order_is_silent() -> None:
    assert find_necessity_gaps("Plan: no need for HbA1c today.", [_rule()]) == []
    assert find_necessity_gaps("Not ordering HbA1c at this time.", [_rule()]) == []


def test_wrap_tolerant_multiword_order_term() -> None:
    # Regression: a note that line-wraps a multi-word order term (e.g. "glycated
    # haemoglobin" as "glycated\nhaemoglobin") must still be recognized -- same
    # whitespace-flexible matching gapcheck.term_pattern already provides.
    rule = _rule(order_terms=["glycated haemoglobin"])
    note = "Plan: check glycated\nhaemoglobin today."
    gaps = find_necessity_gaps(note, [rule])
    assert [g.order for g in gaps] == ["hba1c"]


# --- composer / firewall ---

def test_verified_citation_produces_necessity_finding(tmp_path: Path) -> None:
    clause = Clause(
        "CHI-NEC-HBA1C/pg3/p2", "Scope", 3,
        "This guidance focuses on testing hemoglobin A1c (HbA1c) levels for screening.",
    )
    rule = _rule(citations=[Citation(
        clause_id="CHI-NEC-HBA1C/pg3/p2", quote="This guidance focuses on testing hemoglobin A1c",
    )])
    finding = compose_necessity_finding(rule, _store(tmp_path, [clause]))
    assert finding is not None
    assert finding.finding_type == "necessity_mismatch"
    assert finding.condition == "hba1c"
    assert finding.axis == "indication"
    assert finding.severity == "required"
    assert finding.dedupe_key == "necessity|hba1c"
    assert finding.citations[0].clause_id == "CHI-NEC-HBA1C/pg3/p2"


def test_fabricated_quote_yields_no_necessity_finding(tmp_path: Path) -> None:
    clause = Clause("CHI-NEC-HBA1C/pg3/p2", "Scope", 3, "unrelated clause text entirely")
    rule = _rule(citations=[Citation(clause_id="CHI-NEC-HBA1C/pg3/p2", quote="fabricated quote text")])
    assert compose_necessity_finding(rule, _store(tmp_path, [clause])) is None


def test_unresolvable_clause_id_yields_no_necessity_finding(tmp_path: Path) -> None:
    assert compose_necessity_finding(_rule(), _store(tmp_path, [])) is None


# --- integration (real KB, real data/necessity/*.yaml) ---

def test_run_audit_flags_hba1c_without_indication() -> None:
    result = run_audit("Plan: check HbA1c today.")
    keys = {f.dedupe_key for f in result.findings}
    assert "necessity|hba1c" in keys
    finding = next(f for f in result.findings if f.dedupe_key == "necessity|hba1c")
    assert any(c.clause_id.startswith("CHI-NEC-HBA1C") for c in finding.citations)


def test_run_audit_does_not_flag_hba1c_with_indication() -> None:
    result = run_audit("T2DM follow-up. Plan: check HbA1c.")
    assert "necessity|hba1c" not in {f.dedupe_key for f in result.findings}
