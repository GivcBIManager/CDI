from cdi_kb import config


def test_booklet_pdf_exists() -> None:
    assert config.BOOKLET_PDF.exists(), f"missing source PDF: {config.BOOKLET_PDF}"


def test_source_id_prefix() -> None:
    assert config.SOURCE_ID == "CDI-2021"


def test_load_dotenv_sets_missing_and_never_overrides(tmp_path):
    import os

    envfile = tmp_path / ".env"
    envfile.write_text(
        "# comment\n\nCDI_TEST_NEW_KEY=abc\nCDI_TEST_EXISTING=from_file\nBAD LINE NO EQUALS\n",
        encoding="utf-8",
    )
    os.environ.pop("CDI_TEST_NEW_KEY", None)
    os.environ["CDI_TEST_EXISTING"] = "from_env"
    try:
        config._load_dotenv(envfile)
        assert os.environ["CDI_TEST_NEW_KEY"] == "abc"
        assert os.environ["CDI_TEST_EXISTING"] == "from_env"
    finally:
        os.environ.pop("CDI_TEST_NEW_KEY", None)
        os.environ.pop("CDI_TEST_EXISTING", None)


def test_load_dotenv_missing_file_is_noop(tmp_path):
    config._load_dotenv(tmp_path / "does-not-exist.env")


MOH_SOURCE_IDS = {
    "MOH-DM", "MOH-SEPSIS-MAT", "MOH-PN-ADULT", "MOH-MENINGITIS", "MOH-IAI",
    "MOH-HD", "MOH-LRTI", "MOH-SEPSIS-PED", "MOH-UTI", "MOH-SSI", "MOH-SSTI",
    "MOH-DKA", "MOH-DKA-PED", "MOH-VTE", "MOH-FH", "MOH-RA", "MOH-HIE",
    "MOH-MDD", "MOH-HYPOGLYCEMIA", "MOH-HEADACHE", "MOH-DVT", "MOH-PE",
    "MOH-GAS", "MOH-ANAPHYLAXIS", "MOH-CONTRAST", "MOH-WARFARIN",
    "MOH-TDM-VANCO", "MOH-ANTICOAG-REV", "MOH-ABX-PROPH", "MOH-ALBUMIN",
    "MOH-SUP",
}


def test_sources_registry_has_expected_keys() -> None:
    expected = {
        "CDI-2021",
        "CHI-HF",
        "CHI-CKD",
        "CHI-ANEMIA",
        "CHI-STROKE",
        "CHI-BARIATRIC",
        "CHI-LRTI",
        "CHI-NEC-HBA1C",
        "CHI-NEC-FBG",
        "CHI-NEC-UCULT",
        "CHI-NEC-B12",
    } | MOH_SOURCE_IDS
    assert set(config.SOURCES.keys()) == expected
    assert len(expected) == 42


def test_moh_sources_carry_moh_authority_and_genre() -> None:
    for source_id in MOH_SOURCE_IDS:
        source = config.SOURCES[source_id]
        assert source.authority == "MOH", source_id
        assert source.genre == "moh_protocol", source_id


def test_moh_source_ids_do_not_collide_with_chi() -> None:
    # CHI-LRTI and MOH-LRTI are different documents on the same topic. The
    # prefix is what keeps their clause_ids apart, so a bare "LRTI" id would
    # silently merge two authorities' clauses under one V1 source check.
    #
    # Reads config.SOURCES directly rather than this test's own MOH_SOURCE_IDS
    # literal: asserting a hard-coded set starts with "MOH-" proves nothing
    # about the registry and cannot catch a real collision there.
    moh_ids = {sid for sid, source in config.SOURCES.items() if source.authority == "MOH"}
    non_moh_ids = {sid for sid, source in config.SOURCES.items() if source.authority != "MOH"}
    assert moh_ids, "no MOH-authority sources registered"
    for source_id in moh_ids:
        assert source_id.startswith("MOH-"), source_id
    assert not (moh_ids & non_moh_ids), moh_ids & non_moh_ids


def test_sources_paths_exist() -> None:
    for source_id, source in config.SOURCES.items():
        assert source.path.exists(), f"missing source PDF for {source_id}: {source.path}"


def test_booklet_source_genre() -> None:
    assert config.SOURCES["CDI-2021"].genre == "booklet"
