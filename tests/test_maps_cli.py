import json
import os
import subprocess
import sys

import httpx
import pytest

from geophotoloc import cli
from geophotoloc.maps import LandmarkStore, OverpassClient, parse_snapshot
from geophotoloc.maps.regions import REGIONS
from geophotoloc.models.maps import MapMatchingResult
from test_maps_matching import vision_input


def test_map_import_cli_repeat_and_cached(tmp_path, osm_snapshot, monkeypatch, capsys):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=osm_snapshot.payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = OverpassClient(tmp_path / "cache", client=http)
        monkeypatch.setattr(cli, "OverpassClient", lambda path: client)
        monkeypatch.setattr(cli.VisionConfig, "from_env", lambda: pytest.fail("Vision configuration must not be read"))
        args = ["map-import", "--region", "shanghai", "--db", str(tmp_path / "maps.sqlite3"), "--output", "-"]
        assert cli.main(args) == 0
        assert json.loads(capsys.readouterr().out)["stored_entities"] == 5
        assert cli.main(args) == 0
        assert json.loads(capsys.readouterr().out)["cache_hit"] is True
    assert len(requests) == 1


def test_map_match_cli_no_vision_calls(tmp_path, osm_snapshot, extraction, photo, monkeypatch, capsys):
    db = tmp_path / "maps.sqlite3"
    with LandmarkStore(db) as store:
        store.import_entities(parse_snapshot(osm_snapshot, "shanghai").entities, "shanghai", REGIONS["shanghai"], {})
    path, output = tmp_path / "renamed_input.json", tmp_path / "matches.json"
    path.write_text(vision_input(extraction, photo, ["Alpha Tower"]).model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli.VisionConfig, "from_env", lambda: pytest.fail("No vision API config read"))
    assert cli.main(["map-match", str(path), "--db", str(db), "--region", "shanghai", "--output", str(output)]) == 0
    result = MapMatchingResult.model_validate_json(output.read_text(encoding="utf-8"))
    assert result.matches[0].candidates[0].entity.id == "osm:node:1"
    assert "INSUFFICIENT_EVIDENCE" in capsys.readouterr().out


def test_bad_map_match_json(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    assert cli.main(["map-match", str(path), "--db", str(tmp_path / "maps.sqlite3")]) == 1
    assert "not a valid Stage 2" in capsys.readouterr().err


def test_map_match_empty_db(tmp_path, extraction, photo, capsys):
    path = tmp_path / "input.json"
    path.write_text(vision_input(extraction, photo, ["Alpha Tower"]).model_dump_json(), encoding="utf-8")
    assert cli.main(["map-match", str(path), "--db", str(tmp_path / "empty.sqlite3")]) == 1
    assert "database is empty" in capsys.readouterr().err


def test_map_output_cannot_overwrite_input(tmp_path, capsys):
    path = tmp_path / "input.json"
    path.write_text("original", encoding="utf-8")
    assert cli.main(["map-match", str(path), "--output", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == "original"
    assert "different from input" in capsys.readouterr().err


def test_offline_import_no_cache(tmp_path, capsys):
    assert cli.main(["map-import", "--region", "beijing", "--offline", "--cache-dir", str(tmp_path / "cache"),
                     "--db", str(tmp_path / "empty.sqlite3")]) == 1
    assert "No valid cached Overpass" in capsys.readouterr().err


def test_module_map_match_json_is_utf8_without_vision_key(tmp_path, osm_snapshot, extraction, photo):
    db = tmp_path / "maps.sqlite3"
    with LandmarkStore(db) as store:
        store.import_entities(parse_snapshot(osm_snapshot, "shanghai").entities, "shanghai", REGIONS["shanghai"], {})
    path = tmp_path / "anything.json"
    path.write_text(vision_input(extraction, photo, ["Alpha Tower"]).model_dump_json(), encoding="utf-8")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GEOPHOTOLOC_VLM_")}
    process = subprocess.run([sys.executable, "-m", "geophotoloc.cli", "map-match", str(path),
                              "--db", str(db), "--output", "-"],
                             cwd=tmp_path, env=environment, capture_output=True, encoding="utf-8", timeout=15)
    assert process.returncode == 0 and process.stderr == ""
    assert json.loads(process.stdout)["matches"][0]["candidates"][0]["entity"]["name"] == "测试甲塔"
