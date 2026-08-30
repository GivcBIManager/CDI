"""V1-V5: prove the KB matches the source documents. Requires `build-kb` run first."""

from cdi_kb import config
from cdi_kb.verify import run_verification


def test_kb_verification_all_checks_pass() -> None:
    report = run_verification()
    assert report.passed, "KB verification failures:\n" + "\n".join(report.failures)


def test_stats_are_reported() -> None:
    report = run_verification()
    assert report.stats["clauses"] > 200
    assert report.stats["requirements"] == 20
    assert report.stats["citations_checked"] >= 20


def test_stats_report_per_source_counts() -> None:
    report = run_verification()
    assert report.stats["sources"] == 9
    assert report.stats["clauses_CHI-ANEMIA"] > 10


def test_mandate_anchored_entries_are_named_in_notes() -> None:
    report = run_verification()
    assert report.stats["mandate_anchored_entries"] >= 1
    named = set()
    for note in report.notes:
        assert note.startswith("V3-INFO "), note
        condition = note[len("V3-INFO "):].split(":", 1)[0]
        named.add(condition)
    assert named == {"heart failure", "obesity", "stroke"}
