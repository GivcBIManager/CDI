from cdi_kb import config


def test_booklet_pdf_exists() -> None:
    assert config.BOOKLET_PDF.exists(), f"missing source PDF: {config.BOOKLET_PDF}"


def test_source_id_prefix() -> None:
    assert config.SOURCE_ID == "CDI-2021"
