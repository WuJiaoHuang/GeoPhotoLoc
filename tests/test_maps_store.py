from datetime import timedelta

from geophotoloc.maps import LandmarkStore, parse_snapshot
from geophotoloc.maps.regions import REGIONS
from geophotoloc.models.maps import GeoBounds


def test_persistence_indices_aliases_repeat_import(tmp_path, osm_snapshot):
    path = tmp_path / "landmarks.sqlite3"
    entities = parse_snapshot(osm_snapshot, "shanghai").entities
    with LandmarkStore(path) as store:
        for _ in range(2):
            store.import_entities(entities, "shanghai", REGIONS["shanghai"], {"source": "test"})
        assert len(store.list_entities()) == 5
        assert store.coverage_regions() == ["shanghai"]
        assert store.get_by_osm("node", 1).location.latitude == 31.24
        assert store.search_name("ALPHA-TOWER")[0].entity_id == "osm:node:1"
        assert store.search_name("甲塔")[0].entity_id == "osm:node:1"
        assert store.search_name("Alpha Spire")[0].kind == "exact_name_or_alias"
        assert store.search_name("Alfa Tower")[0].kind == "fuzzy_name"
        assert len(store.list_entities(category="building")) == 3
        small = GeoBounds(south=31.2399, north=31.2401, west=121.4999, east=121.5001)
        assert [entity.id for entity in store.list_entities(bounds=small)] == ["osm:node:1"]
        assert store.search_name("No Such Landmark") == []
    with LandmarkStore(path) as store:
        assert len(store.list_entities()) == 5
        assert store.get("osm:way:2").geometry["type"] == "Polygon"


def test_overlapping_coverage_does_not_duplicate_entities_or_erase_newer_data(osm_snapshot):
    entities = parse_snapshot(osm_snapshot, "shanghai").entities
    with LandmarkStore(":memory:") as store:
        store.import_entities(entities, "shanghai", REGIONS["shanghai"], {})
        older = entities[0].model_copy(deep=True)
        older.fetched_at -= timedelta(days=1)
        older.name = "Old name"
        store.import_entities([older], "second", REGIONS["shanghai"], {})
        assert len(store.list_entities()) == 5
        assert store.get(older.id).name == "测试甲塔"
        assert store.get(older.id).region_ids == ["second", "shanghai"]
        assert len(store.list_entities(regions=["second"])) == 1
        assert store.list_entities(regions=[]) == []


def test_refresh_removes_stale_region_memberships(osm_snapshot):
    entities = parse_snapshot(osm_snapshot, "shanghai").entities
    with LandmarkStore(":memory:") as store:
        store.import_entities(entities, "shanghai", REGIONS["shanghai"], {})
        store.import_entities(entities[:1], "shanghai", REGIONS["shanghai"], {})
        assert len(store.list_entities()) == 1
        assert store.search_name("Beta Tower") == []


def test_failed_import_rolls_back_memberships(osm_snapshot):
    import pytest
    entities = parse_snapshot(osm_snapshot, "shanghai").entities
    with LandmarkStore(":memory:") as store:
        store.import_entities(entities, "shanghai", REGIONS["shanghai"], {})
        invalid = entities[0].model_copy(deep=True)
        invalid.fetched_at = invalid.fetched_at.replace(tzinfo=None)
        with pytest.raises(ValueError, match="timezone-aware"):
            store.import_entities([invalid], "shanghai", REGIONS["shanghai"], {})
        assert len(store.list_entities()) == 5
