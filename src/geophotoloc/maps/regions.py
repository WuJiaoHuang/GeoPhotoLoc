"""Finite demo data coverage; these bounds are not photographer GPS priors."""

from geophotoloc.models.maps import GeoBounds

REGIONS = {
    "shanghai": GeoBounds(south=31.215, west=121.475, north=31.265, east=121.535),
    "beijing": GeoBounds(south=39.899, west=116.440, north=39.928, east=116.478),
    "guangzhou": GeoBounds(south=23.100, west=113.306, north=23.140, east=113.340),
}
