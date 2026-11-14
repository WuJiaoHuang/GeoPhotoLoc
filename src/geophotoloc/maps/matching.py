"""Explainable lexical/semantic retrieval and bounded geographic hypothesis checks.

No filenames, photographer coordinates, ground truth, city-name rules or model
calls enter this API. LEFT_OF/ABOVE remain image relations, never map axes.
"""

from itertools import combinations
from difflib import SequenceMatcher
import re

from pydantic import BaseModel, ConfigDict, Field

from geophotoloc.geometry.coordinates import horizontal_distance
from geophotoloc.models import RelationType, SpatialRelation, VisionExtractionResult
from geophotoloc.models.maps import (
    LandmarkMatch, MapMatchCandidate, MapMatchingResult, RegionHypothesis,
)

from .names import distinctive_words, is_specific_name, normalize_name
from .store import LandmarkStore


class MatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.68, ge=0, le=1)
    max_pair_distance_m: float = Field(default=15000, gt=0, le=100000)
    beam_width: int = Field(default=20, ge=1, le=100)
    max_hypotheses: int = Field(default=10, ge=1, le=100)


def deduplicate_relations(relations) -> list[SpatialRelation]:
    inverses = {
        RelationType.LEFT_OF: RelationType.RIGHT_OF, RelationType.RIGHT_OF: RelationType.LEFT_OF,
        RelationType.ABOVE: RelationType.BELOW, RelationType.BELOW: RelationType.ABOVE,
    }
    seen = {}
    for relation in relations:
        subject, obj, kind = relation.subject_id, relation.object_id, relation.relation_type
        if subject > obj:
            subject, obj, kind = obj, subject, inverses[kind]
        key = (subject, obj, kind.value)
        seen[key] = SpatialRelation(subject_id=subject, object_id=obj, relation_type=kind)
    return [seen[key] for key in sorted(seen)]


def image_category(landmark):
    # Name/evidence type words only; no landmark identity -> city mappings.
    text = " ".join([landmark.name, *landmark.visual_evidence]).casefold()
    for category, pattern in (
        ("bridge", r"\bbridge\b|桥"), ("island", r"\bisland\b|岛"),
        ("tower", r"\btower\b|塔"), ("building", r"\b(building|skyscraper|pyramid)\b|建筑|大厦|高楼"),
        ("water", r"\b(river|lake|waterway)\b|河流|湖泊"), ("road", r"\broad\b|道路"),
    ):
        if re.search(pattern, text):
            return category
    return "unknown"


def category_compatibility(image_type, map_type):
    if image_type == "unknown" or map_type in {"other", "attraction", "historic", "leisure"}:
        return 0.5
    if image_type == map_type:
        return 1.0
    if {image_type, map_type} <= {"tower", "building"}:
        return 0.8
    return 0.0


def same_physical_entity(a, b):
    if a.entity.identity_key == b.entity.identity_key:
        return True
    if a.entity.category in {"building", "tower"} and b.entity.category in {"building", "tower"}:
        names_a = {normalize_name(name) for name in [a.entity.name, *a.entity.aliases]}
        names_b = {normalize_name(name) for name in [b.entity.name, *b.entity.aliases]}
        if names_a & names_b and horizontal_distance(a.entity.location, b.entity.location) <= 30:
            return True
    return False


class MapMatcher:
    def __init__(self, store: LandmarkStore, config: MatchConfig | None = None):
        self.store, self.config = store, config or MatchConfig()

    def _retrieve(self, landmark, regions):
        queries = []
        if is_specific_name(landmark.name):
            queries.append((landmark.name, "primary", 0.85 if landmark.identity_uncertain else 1.0))
        for name in landmark.name_candidates:
            if is_specific_name(name) and name not in [query[0] for query in queries]:
                queries.append((name, "candidate", max(0.6, 0.8 - 0.03 * (len(landmark.name_candidates) - 1))))
        by_id = {}
        category = image_category(landmark)
        for query, source, identity_weight in queries:
            for hit in self.store.search_name(query, regions=regions):
                if hit.kind == "fuzzy_name":
                    query_words, map_words = distinctive_words(query), distinctive_words(hit.map_name)
                    if query_words and map_words and not query_words & map_words:
                        if max(SequenceMatcher(None, a, b).ratio() for a in query_words for b in map_words) < 0.65:
                            continue
                entity = self.store.get(hit.entity_id)
                type_score = category_compatibility(category, entity.category)
                score = 0.70 * hit.similarity + 0.15 * type_score + 0.15 * identity_weight
                # Clear type contradictions cannot be rescued by an exact name.
                if type_score == 0:
                    score -= 0.30
                if score < self.config.min_score:
                    continue
                candidate = MapMatchCandidate(
                    entity=entity, score=round(score, 6),
                    score_components={"name_similarity": hit.similarity,
                                      "category_compatibility": type_score,
                                      "identity_evidence_weight": identity_weight},
                    matched_query=query, matched_map_name=hit.map_name, query_source=source,
                    reasons=[hit.kind, f"image_category={category}; map_category={entity.category}",
                             "0.70*name + 0.15*category + 0.15*identity_evidence; type conflict penalty=0.30",
                             "Uncalibrated retrieval score; identity is not independently confirmed"],
                )
                if entity.id not in by_id or score > by_id[entity.id].score:
                    by_id[entity.id] = candidate
        # Representations explicitly linked by the same Wikidata identity are
        # alternatives for one physical object, not two separately assignable targets.
        groups = {}
        for candidate in by_id.values():
            groups.setdefault(candidate.entity.identity_key, []).append(candidate)
        candidates = []
        for group in groups.values():
            best = max(group, key=lambda item: (item.score, item.entity.complete_geometry,
                                                item.entity.geometry_precision == "complete_outline"))
            # Prefer a true outline at the same identity, while retaining best lexical evidence.
            geometry_rich = max(group, key=lambda item: (
                item.entity.geometry_precision == "complete_outline", item.entity.complete_geometry, item.score,
            ))
            if geometry_rich.entity.geometry_precision == "complete_outline":
                original_id = best.entity.id
                best = best.model_copy(deep=True)
                best.entity = geometry_rich.entity
                if best.entity.id != original_id:
                    best.reasons.append("Footprint retained from another OSM representation linked by the same Wikidata ID")
            best.equivalent_entity_ids = sorted({item.entity.id for item in group} - {best.entity.id})
            if best.equivalent_entity_ids:
                best.reasons.append("Equivalent Wikidata-linked OSM representations grouped, not counted as separate objects")
            candidates.append(best)
        candidates.sort(key=lambda item: (-item.score, item.entity.id))
        candidates = candidates[:self.config.top_k]
        if not candidates:
            reason = "No specific identity names or candidates" if not queries else "No compatible named entity in loaded map coverage"
            return LandmarkMatch(image_landmark_id=landmark.id, image_name=landmark.name,
                                 candidates=[], status="UNMATCHED", unmatched_reason=reason)
        return LandmarkMatch(
            image_landmark_id=landmark.id, image_name=landmark.name, candidates=candidates,
            status="AMBIGUOUS" if len(candidates) > 1 else "TENTATIVE",
        )

    def _hypotheses(self, matches, regions):
        hypotheses = []
        checks = {"duplicate_entity_assignments_rejected": 0, "distant_assignments_rejected": 0,
                  "candidate_regions": 0}
        possible = sorted({region for match in matches for candidate in match.candidates
                           for region in candidate.entity.region_ids if regions is None or region in regions})
        for region in possible:
            checks["candidate_regions"] += 1
            beams = [({}, 0.0, [])]
            for match in matches:
                choices = [item for item in match.candidates if region in item.entity.region_ids]
                expanded = list(beams)  # Leaving an image object unmatched is always allowed.
                for assignments, score, selected in beams:
                    for candidate in choices:
                        if any(same_physical_entity(candidate, item) for item in selected):
                            checks["duplicate_entity_assignments_rejected"] += 1
                            continue
                        if any(horizontal_distance(candidate.entity.location, item.entity.location)
                               > self.config.max_pair_distance_m for item in selected):
                            checks["distant_assignments_rejected"] += 1
                            continue
                        expanded.append(({**assignments, match.image_landmark_id: candidate.entity.id},
                                         score + candidate.score, [*selected, candidate]))
                unique = {}
                for beam in expanded:
                    key = tuple(sorted(beam[0].items()))
                    unique[key] = beam
                beams = sorted(unique.values(), key=lambda item: (-len(item[0]), -item[1], sorted(item[0].items())))[:self.config.beam_width]
            maximum_support = max(len(beam[0]) for beam in beams)
            for assignments, total, selected in beams:
                # Only maximal-coverage combinations in each region are useful;
                # lower-coverage regions remain visible as alternative hypotheses.
                if not assignments or len(assignments) < maximum_support:
                    continue
                distances = [horizontal_distance(a.entity.location, b.entity.location)
                             for a, b in combinations(selected, 2)]
                hypotheses.append(RegionHypothesis(
                    region_id=region, assignments=assignments,
                    score=round(total / max(len(matches), 1), 6), matched_objects=len(assignments),
                    max_pair_distance_m=max(distances, default=0),
                    reasons=["Entities share imported geographic coverage",
                             "Hypothesis score = sum(selected candidate scores) / total image objects; rank by support count first",
                             "No repeated OSM/Wikidata identity within this combination",
                             f"All entity pairs <= {self.config.max_pair_distance_m:g} metres",
                             "Image directions were not interpreted as geographic directions",
                             "This is landmark co-occurrence plausibility, not photographer localization"],
                ))
        hypotheses.sort(key=lambda item: (-item.matched_objects, -item.score, item.region_id, sorted(item.assignments.items())))
        leaders = []
        seen_regions = set()
        for hypothesis in hypotheses:
            if hypothesis.region_id not in seen_regions:
                leaders.append(hypothesis)
                seen_regions.add(hypothesis.region_id)
        selected = leaders[:self.config.max_hypotheses]
        selected.extend(item for item in hypotheses if item not in leaders)
        selected = selected[:self.config.max_hypotheses]
        selected.sort(key=lambda item: (-item.matched_objects, -item.score, item.region_id))
        checks["regions_omitted_by_output_limit"] = len(seen_regions) - len({item.region_id for item in selected})
        return selected, checks

    def match(self, vision: VisionExtractionResult, *, regions: list[str] | None = None) -> MapMatchingResult:
        coverage = self.store.coverage_regions()
        if regions is not None and not set(regions) <= set(coverage):
            raise ValueError("Requested region has not been imported")
        if not coverage:
            raise ValueError("Map database is empty; run map-import first")
        seeds = [self._retrieve(landmark, regions) for landmark in vision.landmarks]
        inferred_regions = sorted({region for match in seeds for candidate in match.candidates
                                   for region in candidate.entity.region_ids
                                   if regions is None or region in regions})
        # Re-query related image objects within data-derived region hypotheses.
        # Generic descriptions still cannot manufacture new named objects.
        matches = ([self._retrieve(landmark, inferred_regions) for landmark in vision.landmarks]
                   if inferred_regions else seeds)
        hypotheses, checks = self._hypotheses(matches, inferred_regions)
        checks["seed_name_candidates"] = sum(len(match.candidates) for match in seeds)
        relations = deduplicate_relations(vision.relations)
        warnings = [
            "Finite imported map coverage only; absence is not proof that a landmark does not exist",
            "All scores are uncalibrated heuristics; entity identities remain tentative",
            "Map entity coordinates and geometry representative points are not photographer locations",
            "Spatial consistency checks co-region, uniqueness and pair distance only; no camera pose is solved",
        ]
        checks.update(input_directed_relations=len(vision.relations), distinct_pair_axis_relations=len(relations))
        if not hypotheses:
            status = "NO_MATCH"
        elif len({item.region_id for item in hypotheses}) > 1 or len(hypotheses) > 1:
            status = "AMBIGUOUS"
        elif hypotheses[0].matched_objects < 2:
            status = "INSUFFICIENT_EVIDENCE"
        else:
            status = "TENTATIVE"
        if hypotheses and hypotheses[0].matched_objects < 2:
            warnings.append("Only one distinct image object supports the leading region; region is not established")
        if len({item.region_id for item in hypotheses}) > 1:
            warnings.append("Multiple geographically separate region hypotheses remain")
        if checks["regions_omitted_by_output_limit"]:
            warnings.append("Output limit omitted region alternatives; do not interpret leading region as unique")
            status = "AMBIGUOUS"
        return MapMatchingResult(
            status=status, matches=matches, region_hypotheses=hypotheses,
            distinct_image_relations=relations, consistency_checks=checks,
            warnings=warnings, coverage_regions=coverage,
        )


def match_landmarks(vision: VisionExtractionResult, store: LandmarkStore, *, regions=None,
                    config: MatchConfig | None = None) -> MapMatchingResult:
    return MapMatcher(store, config).match(vision, regions=regions)
