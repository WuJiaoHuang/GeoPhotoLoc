from datetime import datetime, timezone
import json

import pytest

from geophotoloc.maps import LandmarkStore, MapMatcher, MatchConfig
from geophotoloc.maps.matching import deduplicate_relations
from geophotoloc.maps.regions import REGIONS
from geophotoloc.models import GeoPoint, VisionExtractionResult
from geophotoloc.models.maps import MapLandmark
from geophotoloc.models.vision import VisionResponse
from geophotoloc.vision import prepare_image
from geophotoloc.vision.relations import extract_relations


def entity(identifier, name, *, english=None, latitude=31.24, longitude=121.50,
           category="tower", wikidata=None):
    names = {"name": name}
    if english:
        names["name:en"] = english
    return MapLandmark(
        id=f"osm:node:{identifier}", osm_type="node", osm_id=identifier,
        name=name, names=names, aliases=list(names.values()), category=category,
        location=GeoPoint(latitude=latitude, longitude=longitude),
        geometry={"type": "Point", "coordinates": [longitude, latitude]},
        geometry_precision="node", complete_geometry=True, coordinate_meaning="actual_osm_node",
        tags={**names, **({"wikidata": wikidata} if wikidata else {})},
        source="https://example.test/osm", fetched_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


def vision_input(extraction, photo, names):
    extraction["landmarks"] = extraction["landmarks"][:len(names)]
    for landmark, name in zip(extraction["landmarks"], names):
        landmark["name"] = name
    parsed = VisionResponse.model_validate_json(json.dumps(extraction))
    return VisionExtractionResult(
        landmarks=parsed.landmarks, scene_features=[], warnings=[], image=prepare_image(photo).metadata,
        relations=extract_relations(parsed.landmarks),
    )


@pytest.mark.parametrize("name", ["测试甲塔", "Alpha Tower", "ALPHA-TOWER", "Alfa Tower"])
def test_chinese_english_normalized_fuzzy_names(extraction, photo, name):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "测试甲塔", english="Alpha Tower")], "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, [name]))
    assert result.matches[0].candidates[0].entity.id == "osm:node:1"
    assert result.matches[0].candidates[0].identity_certain is False
    assert result.status == "INSUFFICIENT_EVIDENCE"


def test_candidate_names_and_ambiguity_no_filling_missing_objects(extraction, photo):
    vision = vision_input(extraction, photo, ["Tall rectangular skyscraper", "Unknown building"])
    vision.landmarks[0].name_candidates = ["Alpha Tower", "Beta Tower"]
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower"), entity(2, "Beta Tower", longitude=121.51)],
                              "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision)
    assert {candidate.entity.id for candidate in result.matches[0].candidates} == {"osm:node:1", "osm:node:2"}
    assert result.matches[0].status == "AMBIGUOUS"
    assert result.matches[1].candidates == [] and result.matches[1].status == "UNMATCHED"
    assert all(len(item.assignments) == 1 for item in result.region_hypotheses)


def test_unknown_and_generic_landmarks_do_not_return_catalogue(extraction, photo):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower")], "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, ["Unidentified glass building", "Nonexistent XYZ Monument"]))
    assert result.status == "NO_MATCH"
    assert all(match.candidates == [] for match in result.matches)


def test_duplicate_assignments_rejected_and_inverse_relations_not_double_counted(extraction, photo):
    vision = vision_input(extraction, photo, ["Alpha Tower", "Alpha Tower"])
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower")], "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision)
    assert result.consistency_checks["duplicate_entity_assignments_rejected"] > 0
    assert all(len(item.assignments) == 1 for item in result.region_hypotheses)
    assert len(vision.relations) == 4 and len(result.distinct_image_relations) == 2


def test_distinct_osm_records_same_wikidata_cannot_support_two_objects(extraction, photo):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower", wikidata="Q123"),
                               entity(2, "Beta Tower", wikidata="Q123")], "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, ["Alpha Tower", "Beta Tower"]))
    assert all(len(item.assignments) == 1 for item in result.region_hypotheses)


def test_multiregion_hypotheses_are_not_hardcoded_by_name(extraction, photo):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower")], "shanghai", REGIONS["shanghai"], {})
        store.import_entities([entity(2, "Alpha Tower", latitude=39.91, longitude=116.46)], "beijing", REGIONS["beijing"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, ["Alpha Tower"]))
    assert result.status == "AMBIGUOUS"
    assert {item.region_id for item in result.region_hypotheses} == {"shanghai", "beijing"}
    assert all(len(item.assignments) == 1 for item in result.region_hypotheses)


def test_joint_support_ranks_coherent_region_and_keeps_alternatives(extraction, photo):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower"), entity(2, "Beta Tower", longitude=121.51)],
                              "shanghai", REGIONS["shanghai"], {})
        store.import_entities([entity(3, "Alpha Tower", latitude=39.91, longitude=116.46)],
                              "beijing", REGIONS["beijing"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, ["Alpha Tower", "Beta Tower"]))
    assert result.region_hypotheses[0].region_id == "shanghai"
    assert result.region_hypotheses[0].matched_objects == 2
    assert any(hypothesis.region_id == "beijing" for hypothesis in result.region_hypotheses)


def test_distant_combinations_rejected(extraction, photo):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower"), entity(2, "Beta Tower", latitude=31.42)],
                              "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, ["Alpha Tower", "Beta Tower"]))
    assert result.consistency_checks["distant_assignments_rejected"] > 0
    assert all(item.matched_objects == 1 for item in result.region_hypotheses)


def test_category_contradiction_filters_exact_name(extraction, photo):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower", category="water")], "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, ["Alpha Tower"]))
    assert result.matches[0].candidates == []


def test_explicit_scope_and_unimported_region(extraction, photo):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower")], "shanghai", REGIONS["shanghai"], {})
        vision = vision_input(extraction, photo, ["Alpha Tower"])
        with pytest.raises(ValueError, match="not been imported"):
            MapMatcher(store).match(vision, regions=["beijing"])
        assert len(MapMatcher(store).match(vision, regions=["shanghai"]).matches[0].candidates) == 1


def test_empty_database_rejected(extraction, photo):
    with LandmarkStore(":memory:") as store:
        with pytest.raises(ValueError, match="empty"):
            MapMatcher(store).match(vision_input(extraction, photo, ["Alpha Tower"]))


@pytest.mark.parametrize("category", ["transport", "shop", "service", "hotel", "viewpoint"])
def test_transport_station_cannot_match_tower_name(extraction, photo, category):
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower", category=category)], "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision_input(extraction, photo, ["Alpha Tower"]))
    assert result.matches[0].candidates == []


def test_common_financial_type_words_do_not_establish_identity(extraction, photo):
    vision = vision_input(extraction, photo, ["Unknown building"])
    vision.landmarks[0].name_candidates = ["Fortune Financial Center"]
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Oriental Financial Centre", category="building")], "shanghai", REGIONS["shanghai"], {})
        result = MapMatcher(store).match(vision)
    assert result.matches[0].candidates == []


def test_input_file_identity_is_not_part_of_matching(extraction, photo):
    vision = vision_input(extraction, photo, ["Alpha Tower"])
    with LandmarkStore(":memory:") as store:
        store.import_entities([entity(1, "Alpha Tower")], "shanghai", REGIONS["shanghai"], {})
        one = MapMatcher(store).match(vision)
        two = MapMatcher(store).match(VisionExtractionResult.model_validate_json(vision.model_dump_json()))
    assert one == two
