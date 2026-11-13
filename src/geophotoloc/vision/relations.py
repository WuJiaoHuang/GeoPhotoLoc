"""Deterministic image-space relations; no map directions or depth inference."""

from itertools import combinations
from math import isfinite

from geophotoloc.models import RelationType, VisionLandmark
from geophotoloc.models.vision import VisionSpatialRelation


def extract_relations(
    landmarks: list[VisionLandmark], min_gap: float = 0.03,
) -> list[VisionSpatialRelation]:
    """Emit reciprocal relations only for reliable centers separated by > min_gap.

    Identity confidence is not a coordinate reliability measure and is not used
    as a calibrated probability. Neither box size nor relative object size is
    used to infer real-world distance. Occlusion is intentionally not inferred.
    """
    if not isfinite(min_gap) or not 0 < min_gap < 1:
        raise ValueError("Minimum coordinate gap must be between 0 and 1")
    if len({item.id for item in landmarks}) != len(landmarks):
        raise ValueError("Landmark IDs must be unique")
    relations = []
    for a, b in combinations(landmarks, 2):
        if not (a.coordinates_reliable and b.coordinates_reliable):
            continue
        for delta, forward, inverse in (
            (b.x - a.x, RelationType.LEFT_OF, RelationType.RIGHT_OF),
            (b.y - a.y, RelationType.ABOVE, RelationType.BELOW),
        ):
            if abs(delta) <= min_gap + 1e-12:
                continue
            relation, opposite = (forward, inverse) if delta > 0 else (inverse, forward)
            relations.extend([
                VisionSpatialRelation(subject_id=a.id, object_id=b.id, relation_type=relation),
                VisionSpatialRelation(subject_id=b.id, object_id=a.id, relation_type=opposite),
            ])
    return relations
