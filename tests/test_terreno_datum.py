# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Terrain plugin, G1: the UTM projection and the datum shift, pure.

The reference values come from PROJ 9.5.1 (pyproj 3.7.2): EPSG:32719 for
WGS84 / UTM 19 S, EPSG:32619 for 19 N, and for PSAD56 the UTM on the
International 1924 ellipsoid with EPSG:1208's shift (-279, 175, -379).
"""
from __future__ import annotations

import math

import pytest

from core.georef import Georef
from plugins.terreno import datum

# (lat, lon) -> (easting, northing) on WGS84 / UTM 19 S, from PROJ
CONTROL_19S = [
    ((-16.398889, -71.536944), (229038.4878, 8185246.5211)),   # Plaza de Armas, Arequipa
    ((-16.4, -71.5), (232987.9904, 8185172.5502)),
    ((-16.0, -69.0), (500000.0000, 8231064.6240)),             # the central meridian
    ((-18.0, -72.0), (182293.8864, 8007242.5272)),             # the zone's west edge
    ((-12.0, -66.0), (826714.5914, 8671666.8165)),             # the east edge
    ((-0.5, -70.2), (366465.2676, 9944722.7586)),              # near the equator
    ((-10.3, -71.9), (182341.0452, 8859979.8298)),
]
# PSAD56 / UTM 19 S drawing coordinates -> WGS84 (lat, lon), from PROJ.
# This direction (the plan is in PSAD56, the height taken as zero THERE)
# is the one the plugin defines; the way back is its exact inverse. PROJ's
# own way back is not: it takes the height as zero on the WGS84 side and
# lands 7 mm away, which is nothing against the datum's 16 m -- but a
# round trip that moves a lot corner by 7 mm is a bug a surveyor notices.
CONTROL_PSAD56 = [
    ((229231.9975, 8185613.5026), (-16.39888894, -71.53694397)),
    ((233181.5606, 8185539.5203), (-16.39999994, -71.49999997)),
    ((500197.6784, 8231431.9517), (-15.99999995, -68.99999997)),
    ((182486.1343, 8007606.7314), (-17.99999994, -71.99999996)),
]


def _ground_mm(lat, lon, lat2, lon2) -> float:
    m = 111320.0
    return math.hypot((lat - lat2) * m, (lon - lon2) * m * math.cos(math.radians(lat))) * 1000.0


def test_wgs84_utm_matches_proj_under_a_millimetre_and_round_trips():
    for (lat, lon), (e, n) in CONTROL_19S:
        e2, n2 = datum.utm_forward(lat, lon, 19, northern=False)
        assert math.hypot(e - e2, n - n2) < 0.001, (lat, lon)
        lat2, lon2 = datum.utm_inverse(e2, n2, 19, northern=False)
        assert _ground_mm(lat, lon, lat2, lon2) < 1.0


def test_the_northern_hemisphere_has_no_false_northing():
    e, n = datum.utm_forward(5.0, -70.0, 19, northern=True)
    assert (e, n) == pytest.approx((389140.0730, 552748.6209), abs=0.001)
    assert datum.utm_forward(5.0, -70.0, 19)[1] == pytest.approx(n)           # sign of lat decides
    # a southern drawing keeps its false northing even a step north of the equator
    assert datum.utm_forward(0.01, -69.0, 19, northern=False)[1] > 10_000_000


def test_zones_and_central_meridians():
    assert datum.zone_for_lon(-71.5) == 19 and datum.zone_for_lon(-75.1) == 18
    assert datum.zone_for_lon(-72.0) == 19 and datum.zone_for_lon(-66.0) == 20
    assert datum.zone_for_lon(-180.0) == 1 and datum.zone_for_lon(180.0) == 60
    assert datum.central_meridian(19) == -69.0 and datum.central_meridian(31) == 3.0


def test_the_ellipsoids_are_the_published_ones():
    assert datum.WGS84.a == 6378137.0 and datum.WGS84.inverse_flattening == 298.257223563
    assert datum.INTERNATIONAL_1924.a == 6378388.0 and datum.INTERNATIONAL_1924.inverse_flattening == 297.0
    assert datum.ELLIPSOIDS["PSAD56"] is datum.INTERNATIONAL_1924
    assert datum.PSAD56_PERU_SHIFT == (-279.0, 175.0, -379.0)


def test_geocentric_conversion_round_trips_exactly():
    for lat, lon, h in [(-16.4, -71.5, 2335.0), (0.0, 0.0, 0.0), (89.9, 10.0, 10.0), (-45.0, 170.0, -50.0)]:
        x, y, z = datum.geodetic_to_geocentric(lat, lon, h, datum.WGS84)
        lat2, lon2, h2 = datum.geocentric_to_geodetic(x, y, z, datum.WGS84)
        assert (lat2, lon2) == pytest.approx((lat, lon), abs=1e-10)
        assert h2 == pytest.approx(h, abs=1e-6)


def test_psad56_drawing_to_wgs84_matches_proj_and_the_way_back_is_exact():
    georef = Georef(19, False, "PSAD56", datum.PSAD56_PERU_SHIFT)
    for (e, n), (lat, lon) in CONTROL_PSAD56:
        lat2, lon2 = datum.drawing_to_latlon(georef, e, n)
        assert _ground_mm(lat, lon, lat2, lon2) < 1.0, (e, n)
        e2, n2 = datum.latlon_to_drawing(georef, lat2, lon2)
        assert math.hypot(e - e2, n - n2) < 0.001
    # and the shift is the right way round: in Peru a PSAD56 plan's
    # coordinates run some 200 m east and 370 m north of WGS84's
    (lat, lon), (e_wgs, n_wgs) = CONTROL_19S[0]
    e_psad, n_psad = datum.latlon_to_drawing(georef, lat, lon)
    assert 150 < e_psad - e_wgs < 250 and 300 < n_psad - n_wgs < 420


def test_wgs84_needs_no_shift():
    georef = Georef(19, False)
    (lat, lon), (e, n) = CONTROL_19S[0]
    assert datum.latlon_to_drawing(georef, lat, lon) == pytest.approx((e, n), abs=0.001)
    assert datum.to_wgs84(lat, lon, "WGS84", (0, 0, 0)) == (lat, lon)


@pytest.mark.parametrize("text", [
    "-16.398889, -71.536944",
    "-16.398889 -71.536944",
    "16.398889 S 71.536944 W",
    "16.398889S,71.536944O",                 # Oeste
    "16°23'56.0\" S, 71°32'13.0\" W",
    "16 23 56 S 71 32 13 W",
    "-16 23 56 -71 32 13",
    "16d23'56\"S 71d32'13\"W",
    "71°32'13\" W 16°23'56\" S",            # longitude first, letters decide
    "16°23.9333' S 71°32.2167' W",          # degrees and decimal minutes
])
def test_typed_coordinates_in_every_habit(text):
    lat, lon = datum.parse_latlon(text)
    assert lat == pytest.approx(-16.398889, abs=2e-5)
    assert lon == pytest.approx(-71.536944, abs=2e-5)


@pytest.mark.parametrize("text", ["hola", "1,2,3", "16 S", "95, 10", "", "16 23 56 S", "10, 190"])
def test_what_is_not_a_coordinate_is_refused(text):
    with pytest.raises(ValueError):
        datum.parse_latlon(text)


def test_formatting_carries_the_seconds_instead_of_printing_sixty():
    assert datum.format_dms(-16.398889, -71.536944) == "16°23'56.00\" S, 71°32'13.00\" W"
    assert datum.format_dms(-16.99999999, 5.0) == "17°00'00.00\" S, 5°00'00.00\" E"
    assert datum.format_decimal(-16.398889, -71.536944) == "-16.398889, -71.536944"
    lat, lon = datum.parse_latlon(datum.format_dms(-16.398889, -71.536944))
    assert (lat, lon) == pytest.approx((-16.398889, -71.536944), abs=2e-6)
