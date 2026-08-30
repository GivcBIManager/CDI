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


def test_sources_registry_has_expected_keys() -> None:
    expected = {
        "CDI-2021",
        "CHI-HF",
        "CHI-CKD",
        "CHI-ANEMIA",
        "CHI-STROKE",
        "CHI-NEC-HBA1C",
        "CHI-NEC-FBG",
        "CHI-NEC-UCULT",
        "CHI-NEC-B12",
        "CHI-NEC-LBPMRI",
    }
    assert set(config.SOURCES.keys()) == expected


def test_sources_paths_exist() -> None:
    for source_id, source in config.SOURCES.items():
        assert source.path.exists(), f"missing source PDF for {source_id}: {source.path}"


def test_booklet_source_genre() -> None:
    assert config.SOURCES["CDI-2021"].genre == "booklet"
