import json
import os
import subprocess
import sys

import pytest

from geophotoloc import cli
from geophotoloc.models import VisionExtractionResult


@pytest.fixture
def isolated_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("GEOPHOTOLOC_VLM_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GEOPHOTOLOC_VLM_API_KEY", "test-dummy-key")


def test_cli_summary_and_json(isolated_cli, mock_api, extraction, photo, tmp_path, monkeypatch, capsys):
    analyzer, requests = mock_api(extraction)
    monkeypatch.setattr(cli, "VisionAnalyzer", lambda config: analyzer)
    output = tmp_path / "result.json"
    assert cli.main(["analyze", str(photo), "--output", str(output)]) == 0
    captured = capsys.readouterr()
    assert "Landmarks: 2; spatial relations: 4" in captured.out
    assert "lm_1: Tower" in captured.out
    assert captured.err == ""
    result = VisionExtractionResult.model_validate_json(output.read_text(encoding="utf-8"))
    assert len(result.landmarks) == 2
    assert len(requests) == 1


def test_cli_stdout_json(isolated_cli, mock_api, extraction, photo, monkeypatch, capsys):
    analyzer, _ = mock_api(extraction)
    monkeypatch.setattr(cli, "VisionAnalyzer", lambda config: analyzer)
    assert cli.main(["analyze", str(photo), "--output", "-"]) == 0
    assert len(json.loads(capsys.readouterr().out)["relations"]) == 4


def test_cli_no_key(isolated_cli, photo, monkeypatch, capsys):
    monkeypatch.delenv("GEOPHOTOLOC_VLM_API_KEY")
    assert cli.main(["analyze", str(photo)]) == 1
    assert "Missing GEOPHOTOLOC_VLM_API_KEY" in capsys.readouterr().err


def test_cli_invalid_image_no_api(isolated_cli, mock_api, extraction, tmp_path, monkeypatch, capsys):
    analyzer, requests = mock_api(extraction)
    monkeypatch.setattr(cli, "VisionAnalyzer", lambda config: analyzer)
    assert cli.main(["analyze", str(tmp_path / "missing.jpg")]) == 1
    assert requests == []
    assert "Cannot read image" in capsys.readouterr().err


def test_cli_remote_failure_preserves_output(isolated_cli, mock_api, photo, tmp_path, monkeypatch, capsys):
    import httpx
    analyzer, _ = mock_api(handler=lambda request: httpx.Response(429, json={"error": {"message": "limit"}}))
    monkeypatch.setattr(cli, "VisionAnalyzer", lambda config: analyzer)
    output = tmp_path / "existing.json"
    output.write_text("original", encoding="utf-8")
    assert cli.main(["analyze", str(photo), "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "original"
    assert "rate limit" in capsys.readouterr().err


def test_cli_invalid_output(isolated_cli, photo, capsys):
    before = photo.read_bytes()
    assert cli.main(["analyze", str(photo), "--output", str(photo)]) == 1
    assert photo.read_bytes() == before
    assert "Output must be" in capsys.readouterr().err


def test_cli_output_io_failure(isolated_cli, mock_api, extraction, photo, tmp_path, monkeypatch, capsys):
    analyzer, _ = mock_api(extraction)
    monkeypatch.setattr(cli, "VisionAnalyzer", lambda config: analyzer)
    assert cli.main(["analyze", str(photo), "--output", str(tmp_path / "absent" / "out.json")]) == 1
    assert "cannot access input or write JSON" in capsys.readouterr().err


def test_module_entrypoint_missing_key(isolated_cli, photo, monkeypatch):
    monkeypatch.delenv("GEOPHOTOLOC_VLM_API_KEY")
    process = subprocess.run(
        [sys.executable, "-m", "geophotoloc.cli", "analyze", str(photo)],
        capture_output=True, text=True, timeout=10,
    )
    assert process.returncode == 1
    assert "Missing GEOPHOTOLOC_VLM_API_KEY" in process.stderr
    assert "Traceback" not in process.stderr
