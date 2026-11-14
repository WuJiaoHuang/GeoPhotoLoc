import numpy as np
import pytest
from shapely.geometry import Point,box
from geophotoloc.localization.extent import adaptive_search_extent,within_observation_distance,distance_batches
from geophotoloc.models.pose import PoseSearchConfig


def test_distance_intersection_and_outline_not_center():
    geometries=[box(-100,900,100,1100),Point(200,1000)]
    xy=[(0,0),(0,1000),(200,0),(0,-100)]
    assert within_observation_distance(xy,geometries,1000).tolist()==[False,True,True,False]
    assert within_observation_distance([(0,0)],[geometries[0]],950).tolist()==[True]
    assert within_observation_distance([(0,0)],[Point(0,1000)],950).tolist()==[False]
    assert adaptive_search_extent(geometries,1000).bounds==(-1100,-100,1200,2100)
    assert list(distance_batches(iter(xy),geometries,1000,2))==list(zip(xy,[False,True,True,False]))


@pytest.mark.parametrize('radius',[0,-1,10001])
def test_invalid_radius(radius):
    with pytest.raises(ValueError):
        adaptive_search_extent([Point(0,0)],radius)
    with pytest.raises(ValueError):
        within_observation_distance([(0,0)],[Point(0,0)],radius)


def test_grid_defaults_and_nonfinite():
    assert PoseSearchConfig().coarse_spacing_m==180
    assert PoseSearchConfig(adaptive_extent=True).coarse_spacing_m==250
    assert PoseSearchConfig(adaptive_extent=True,coarse_spacing_m=300).coarse_spacing_m==300
    assert not within_observation_distance([(np.nan,0)],[Point(0,0)],5000)[0]
    with pytest.raises(ValueError):
        PoseSearchConfig(max_observation_distance_m=10001)
