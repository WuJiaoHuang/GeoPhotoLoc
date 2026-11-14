import pytest
from shapely.geometry import box,Point,Polygon,MultiPolygon
from geophotoloc.localization.footprints import angular_footprint,shortest_arc,footprint_order,local_interval


def test_max_gap_wrap_and_all_vertices():
    assert shortest_arc([350,355,5,10])==pytest.approx((350,10,20,0))
    fp=angular_footprint((0,0),box(-100,800,100,1000))
    assert fp.valid and fp.center_bearing_deg==pytest.approx(0)
    assert fp.angular_width_deg==pytest.approx(14.2500326978)
    assert fp.distance_m==800
    assert local_interval(fp,0)==pytest.approx((-7.1250163489,7.1250163489))


def test_order_both_sides_and_overlap():
    a,b=box(-200,800,-100,1000),box(100,800,200,1000)
    assert footprint_order(angular_footprint((0,0),a),angular_footprint((0,0),b),0)=='SATISFIED'
    assert footprint_order(angular_footprint((0,1800),a),angular_footprint((0,1800),b),180)=='CONFLICT'
    assert footprint_order(angular_footprint((0,0),a),angular_footprint((0,0),a),0)=='INDETERMINATE'


def test_big_building_multipolygon_and_no_subsampling():
    small=angular_footprint((0,0),box(-10,800,10,1000))
    large=angular_footprint((0,0),box(-500,800,500,1000))
    multi=angular_footprint((0,0),MultiPolygon([box(-500,800,-400,1000),box(400,800,500,1000)]))
    assert large.angular_width_deg>small.angular_width_deg*20
    assert multi.angular_width_deg==pytest.approx(large.angular_width_deg)


def test_inside_hole_invalid_and_point_downgrade():
    assert not angular_footprint((0,0),box(-10,-10,10,10)).valid
    assert not angular_footprint((0,0),Polygon([(0,10),(10,0),(0,0),(10,10)])).valid
    hole=Polygon(box(-20,-20,20,20).exterior,[box(-5,-5,5,5).exterior])
    fp=angular_footprint((0,0),hole)
    assert fp.valid and fp.angular_width_deg==360 and local_interval(fp,0) is None
    point=angular_footprint((0,0),Point(0,100))
    assert point.valid and point.geometry_quality=='POINT_DOWNGRADE'
    assert footprint_order(point,point,0)=='INDETERMINATE'
    assert not angular_footprint((0,100),Point(0,100)).valid
    partial=angular_footprint((0,0),box(-100,800,100,1000),complete=False)
    assert partial.geometry_quality=='POINT_DOWNGRADE' and partial.distance_m==900


def test_opposing_directions_are_indeterminate():
    west=angular_footprint((0,0),box(-1000,-10,-900,10))
    east=angular_footprint((0,0),box(900,-10,1000,10))
    assert footprint_order(west,east,0)=='INDETERMINATE'
    assert local_interval(west,90) is None
