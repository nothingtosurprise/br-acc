from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from icarus_etl.pipelines.dou import DouPipeline

FIXTURES = Path(__file__).parent / "fixtures"


def _make_pipeline() -> DouPipeline:
    driver = MagicMock()
    return DouPipeline(driver, data_dir=str(FIXTURES))


def test_pipeline_name_and_source_id() -> None:
    pipeline = _make_pipeline()
    assert pipeline.name == "dou"
    assert pipeline.source_id == "querido_diario"


def test_extract_raises_when_dir_missing() -> None:
    driver = MagicMock()
    pipeline = DouPipeline(driver, data_dir="/nonexistent/path")
    try:
        pipeline.extract()
        raise AssertionError("Expected FileNotFoundError")
    except FileNotFoundError:
        pass


def test_extract_reads_json_fixture() -> None:
    pipeline = _make_pipeline()
    pipeline.extract()
    # JSON has 4 gazette records, CSV has 2 -> JSON takes priority, so 4
    assert len(pipeline._raw_rows) == 4


def test_extract_json_querido_diario_format() -> None:
    """JSON with 'gazettes' wrapper (Querido Diario API format) should parse correctly."""
    pipeline = _make_pipeline()
    pipeline.extract()

    first = pipeline._raw_rows[0]
    assert first["date"] == "2024-01-15"
    assert first["territory_id"] == "3550308"
    assert first["territory_name"] == "Sao Paulo"
    assert first["edition"] == "123"
    assert "queridodiario.ok.org.br" in first["url"]


def test_extract_json_list_format(tmp_path: Path) -> None:
    """JSON as a plain list (no 'gazettes' wrapper) should also parse."""
    dou_dir = tmp_path / "dou"
    dou_dir.mkdir()
    data = [
        {
            "date": "2024-05-01",
            "territory_id": "1234567",
            "territory_name": "Test City",
            "edition": "1",
            "is_extra_edition": False,
            "url": "https://example.com/test",
        }
    ]
    (dou_dir / "test.json").write_text(json.dumps(data))

    driver = MagicMock()
    pipeline = DouPipeline(driver, data_dir=str(tmp_path))
    pipeline.extract()

    assert len(pipeline._raw_rows) == 1
    assert pipeline._raw_rows[0]["territory_name"] == "Test City"


def test_extract_csv_fallback(tmp_path: Path) -> None:
    """When no JSON files exist, CSV files should be used."""
    dou_dir = tmp_path / "dou"
    dou_dir.mkdir()
    csv_content = (
        "date,territory_id,territory_name,edition,is_extra_edition,url,excerpt\n"
        "2024-06-01,9999999,CSV City,10,false,https://example.com/csv,Test excerpt\n"
    )
    (dou_dir / "data.csv").write_text(csv_content)

    driver = MagicMock()
    pipeline = DouPipeline(driver, data_dir=str(tmp_path))
    pipeline.extract()

    assert len(pipeline._raw_rows) == 1
    assert pipeline._raw_rows[0]["territory_name"] == "CSV City"


def test_transform_creates_gazettes() -> None:
    """4 raw rows: 2 valid, 1 empty date (skip), 1 empty territory_id (skip) = 2 gazettes."""
    pipeline = _make_pipeline()
    pipeline.extract()
    pipeline.transform()

    assert len(pipeline.gazettes) == 2


def test_transform_gazette_fields() -> None:
    """Verify correct fields on first gazette (Sao Paulo)."""
    pipeline = _make_pipeline()
    pipeline.extract()
    pipeline.transform()

    sp = pipeline.gazettes[0]
    assert sp["gazette_id"] == "dou_3550308_2024-01-15_123"
    assert sp["date"] == "2024-01-15"
    assert sp["territory_id"] == "3550308"
    assert sp["territory_name"] == "Sao Paulo"
    assert sp["edition"] == "123"
    assert sp["is_extra_edition"] is False
    assert sp["source"] == "querido_diario"


def test_transform_is_extra_edition() -> None:
    """Second gazette (Rio de Janeiro) has is_extra_edition=true."""
    pipeline = _make_pipeline()
    pipeline.extract()
    pipeline.transform()

    rj = pipeline.gazettes[1]
    assert rj["territory_name"] == "Rio de Janeiro"
    assert rj["is_extra_edition"] is True


def test_transform_skips_empty_date() -> None:
    """Row with empty date should be skipped."""
    pipeline = _make_pipeline()
    pipeline.extract()
    pipeline.transform()

    territory_names = {g["territory_name"] for g in pipeline.gazettes}
    assert "Porto Velho" not in territory_names


def test_transform_skips_empty_territory_id() -> None:
    """Row with empty territory_id should be skipped."""
    pipeline = _make_pipeline()
    pipeline.extract()
    pipeline.transform()

    territory_names = {g["territory_name"] for g in pipeline.gazettes}
    assert "Sem Territorio" not in territory_names


def test_transform_extracts_cnpj_from_excerpt() -> None:
    """First gazette excerpt contains a formatted CNPJ — should produce an entity link."""
    pipeline = _make_pipeline()
    pipeline.extract()
    pipeline.transform()

    assert len(pipeline.gazette_entity_links) == 1
    link = pipeline.gazette_entity_links[0]
    assert link["source_key"] == "11.222.333/0001-81"
    assert link["target_key"] == "dou_3550308_2024-01-15_123"


def test_extract_cnpjs_raw_digits() -> None:
    """_extract_cnpjs should also match raw 14-digit CNPJs."""
    pipeline = _make_pipeline()
    text = "Empresa com CNPJ 44555666000199 contratada"
    result = pipeline._extract_cnpjs(text)
    assert len(result) == 1
    assert result[0] == "44.555.666/0001-99"


def test_extract_cnpjs_no_match() -> None:
    """_extract_cnpjs returns empty list when no CNPJ found."""
    pipeline = _make_pipeline()
    text = "Nenhum CNPJ neste texto"
    result = pipeline._extract_cnpjs(text)
    assert result == []


def test_load_calls_batch_loader() -> None:
    pipeline = _make_pipeline()
    pipeline.extract()
    pipeline.transform()
    pipeline.load()

    driver = pipeline.driver
    session = driver.session.return_value.__enter__.return_value
    # Should have called session.run for:
    # Gazette nodes + MENCIONADA_EM rels = 2 calls minimum
    assert session.run.call_count >= 2


def test_load_no_links_when_no_cnpjs(tmp_path: Path) -> None:
    """When gazettes have no CNPJ mentions, only node load should run."""
    dou_dir = tmp_path / "dou"
    dou_dir.mkdir()
    data = [
        {
            "date": "2024-07-01",
            "territory_id": "1111111",
            "territory_name": "No CNPJ City",
            "edition": "1",
            "url": "https://example.com",
        }
    ]
    (dou_dir / "data.json").write_text(json.dumps(data))

    driver = MagicMock()
    pipeline = DouPipeline(driver, data_dir=str(tmp_path))
    pipeline.extract()
    pipeline.transform()

    assert len(pipeline.gazette_entity_links) == 0

    pipeline.load()
    session = driver.session.return_value.__enter__.return_value
    # Only Gazette node load, no relationship load
    assert session.run.call_count >= 1
