"""MOH heading rejectors: every string below is a real line from the corpus."""

from cdi_kb.moh_chunker import _is_moh_heading

# Junk that the CHI predicate accepts as a heading and MOH must reject. Each is
# a verbatim line from MOH_Protocols/ (occurrence counts across the curated 31:
# bullet-led 110, abbreviation-gloss 49, datestamp 7).
MUST_REJECT = [
    "• Perform ECG",
    "• Enoxaparin 40mg SC once daily If CrCl < 30ml/min,",
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
    "Assessment: Patient’s Profiling",
    "Setup: Inpatient setting",
    "Level of Evidence:",
    "Aim and Scope:",
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
