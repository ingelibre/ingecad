# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""UTM and datums without pyproj: Snyder's Transverse Mercator series on
any ellipsoid, the geocentric three-parameter shift between datums, and
geographic coordinates parsed and formatted the way an engineer types
them. A drawing that declares any other coordinate system (an EPSG code,
#27) goes through PROJ instead, grids included.

Ported from IngeTrazo's ``app/georef/datum.py`` (WGS84 only there) and
generalised to the International 1924 ellipsoid of PSAD56, the datum of
Peru's older plans. Checked in the tests against PROJ 9.5 (pyproj): under
a millimetre on WGS84, and on PSAD56 through EPSG:1208's shift.
"""
from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass

from core.georef import Georef


@dataclass(frozen=True)
class Ellipsoid:
    name: str
    a: float                       # semi-major axis, metres
    inverse_flattening: float

    @property
    def f(self) -> float:
        return 1.0 / self.inverse_flattening

    @property
    def e2(self) -> float:
        """First eccentricity squared."""
        return self.f * (2.0 - self.f)

    @property
    def ep2(self) -> float:
        """Second eccentricity squared."""
        return self.e2 / (1.0 - self.e2)


WGS84 = Ellipsoid("WGS84", 6378137.0, 298.257223563)
INTERNATIONAL_1924 = Ellipsoid("International 1924", 6378388.0, 297.0)

#: The ellipsoid each datum of :data:`core.georef.DATUMS` is measured on.
ELLIPSOIDS = {"WGS84": WGS84, "PSAD56": INTERNATIONAL_1924}

#: EPSG:1208 "PSAD56 to WGS 84 (8)", Peru onshore, ±16 m: the geocentric
#: translation (dX, dY, dZ) that takes PSAD56 coordinates to WGS84. The
#: continental EPSG:1201 (-288, 175, -376) is worse in Peru (±42 m).
PSAD56_PERU_SHIFT = (-279.0, 175.0, -379.0)

K0 = 0.9996
FALSE_EASTING = 500000.0
FALSE_NORTHING = 10000000.0        # southern hemisphere


# -- zones -------------------------------------------------------------------------

def zone_for_lon(lon: float) -> int:
    """UTM zone (1..60) holding longitude ``lon`` in degrees."""
    return min(60, max(1, int(math.floor((lon + 180.0) / 6.0)) + 1))


def central_meridian(zone: int) -> float:
    """Longitude of the zone's central meridian, degrees."""
    return (zone - 1) * 6.0 - 180.0 + 3.0


# -- the projection ------------------------------------------------------------------

def _meridian_arc(lat: float, ell: Ellipsoid) -> float:
    e2 = ell.e2
    return ell.a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * lat
                    - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * lat)
                    + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * lat)
                    - (35 * e2 ** 3 / 3072) * math.sin(6 * lat))


def utm_forward(lat: float, lon: float, zone: int, northern: bool | None = None,
                ellipsoid: Ellipsoid = WGS84) -> tuple[float, float]:
    """Geodetic degrees -> UTM ``(easting, northing)`` metres in ``zone``.

    The zone is given, never derived from ``lon``: a drawing that spills a
    little past its zone boundary stays continuous. ``northern`` decides
    the false northing; None takes it from the sign of ``lat``.
    """
    e2, ep2 = ellipsoid.e2, ellipsoid.ep2
    latr, lonr = math.radians(lat), math.radians(lon)
    n = ellipsoid.a / math.sqrt(1 - e2 * math.sin(latr) ** 2)
    t = math.tan(latr) ** 2
    c = ep2 * math.cos(latr) ** 2
    a = math.cos(latr) * (lonr - math.radians(central_meridian(zone)))
    m = _meridian_arc(latr, ellipsoid)
    easting = (K0 * n * (a + (1 - t + c) * a ** 3 / 6
               + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * a ** 5 / 120)
               + FALSE_EASTING)
    northing = K0 * (m + n * math.tan(latr) * (a ** 2 / 2
                     + (5 - t + 9 * c + 4 * c ** 2) * a ** 4 / 24
                     + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * a ** 6 / 720))
    if northern is None:
        northern = lat >= 0
    if not northern:
        northing += FALSE_NORTHING
    return easting, northing


def utm_inverse(easting: float, northing: float, zone: int, northern: bool,
                ellipsoid: Ellipsoid = WGS84) -> tuple[float, float]:
    """UTM metres -> geodetic ``(lat, lon)`` degrees; the inverse of
    :func:`utm_forward` to well under a millimetre."""
    e2, ep2 = ellipsoid.e2, ellipsoid.ep2
    x = easting - FALSE_EASTING
    y = northing if northern else northing - FALSE_NORTHING
    m = y / K0
    mu = m / (ellipsoid.a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = ellipsoid.a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = ellipsoid.a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * K0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = math.radians(central_meridian(zone)) + (
        d - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)


# -- datums ------------------------------------------------------------------------------

def geodetic_to_geocentric(lat: float, lon: float, h: float,
                           ellipsoid: Ellipsoid) -> tuple[float, float, float]:
    latr, lonr = math.radians(lat), math.radians(lon)
    n = ellipsoid.a / math.sqrt(1 - ellipsoid.e2 * math.sin(latr) ** 2)
    x = (n + h) * math.cos(latr) * math.cos(lonr)
    y = (n + h) * math.cos(latr) * math.sin(lonr)
    z = (n * (1 - ellipsoid.e2) + h) * math.sin(latr)
    return x, y, z


def geocentric_to_geodetic(x: float, y: float, z: float,
                           ellipsoid: Ellipsoid) -> tuple[float, float, float]:
    """``(lat, lon, h)``; the latitude converges in a few iterations to
    far below a micrometre."""
    e2 = ellipsoid.e2
    p = math.hypot(x, y)
    lon = math.atan2(y, x)
    lat = math.atan2(z, p * (1 - e2))
    h = 0.0
    for _ in range(20):
        n = ellipsoid.a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        # the height from whichever axis is better conditioned here: p and
        # cos near the equator, z and sin near the poles
        if abs(lat) < math.pi / 4:
            h = p / math.cos(lat) - n
        else:
            h = z / math.sin(lat) - n * (1 - e2)
        new = math.atan2(z, p * (1 - e2 * n / (n + h)))
        done = abs(new - lat) < 1e-14
        lat = new
        if done:
            break
    return math.degrees(lat), math.degrees(lon), h


def shift_datum(lat: float, lon: float, shift: tuple[float, float, float],
                source: Ellipsoid, target: Ellipsoid) -> tuple[float, float]:
    """Geographic coordinates on ``source`` -> on ``target``, through the
    geocentric translation ``shift`` (exact for three parameters; the
    ellipsoidal height is taken as zero and dropped)."""
    x, y, z = geodetic_to_geocentric(lat, lon, 0.0, source)
    lat2, lon2, _h = geocentric_to_geodetic(x + shift[0], y + shift[1], z + shift[2], target)
    return lat2, lon2


def to_wgs84(lat: float, lon: float, datum: str, shift) -> tuple[float, float]:
    if datum == "WGS84":
        return lat, lon
    return shift_datum(lat, lon, shift, ELLIPSOIDS[datum], WGS84)


def from_wgs84(lat: float, lon: float, datum: str, shift) -> tuple[float, float]:
    """The exact inverse of :func:`to_wgs84`.

    Shifting back with the negated translation is not it: each direction
    takes the ellipsoidal height as zero on ITS side, and the height the
    shift produces (a few hundred metres, the size of the translation)
    tilts the normal enough to leave 7 mm on the ground. So the guess is
    refined until the forward shift lands on the given point -- two or
    three rounds to a nanometre.
    """
    if datum == "WGS84":
        return lat, lon
    source = ELLIPSOIDS[datum]
    back = (-shift[0], -shift[1], -shift[2])
    guess = shift_datum(lat, lon, back, WGS84, source)
    for _ in range(8):
        lat2, lon2 = shift_datum(guess[0], guess[1], shift, source, WGS84)
        dlat, dlon = lat - lat2, lon - lon2
        guess = (guess[0] + dlat, guess[1] + dlon)
        if abs(dlat) < 1e-13 and abs(dlon) < 1e-13:
            break
    return guess


# -- the drawing's frame -----------------------------------------------------------------

def drawing_to_latlon(georef: Georef, east: float, north: float) -> tuple[float, float]:
    """A drawing point (UTM in the drawing's datum, or its declared
    coordinate system) -> WGS84 lat/lon, which is what GPS, Google Earth
    and a KML understand."""
    if georef.crs:
        lon, lat = _through_proj(georef.crs, east, north, inverse=False)
        return lat, lon
    lat, lon = utm_inverse(east, north, georef.zone, georef.northern, ELLIPSOIDS[georef.datum])
    return to_wgs84(lat, lon, georef.datum, georef.shift)


def latlon_to_drawing(georef: Georef, lat: float, lon: float) -> tuple[float, float]:
    """WGS84 lat/lon -> the drawing's coordinates (UTM in its datum, or
    its declared coordinate system)."""
    if georef.crs:
        return _through_proj(georef.crs, lon, lat, inverse=True)
    lat2, lon2 = from_wgs84(lat, lon, georef.datum, georef.shift)
    return utm_forward(lat2, lon2, georef.zone, georef.northern, ELLIPSOIDS[georef.datum])


# -- any other coordinate system: PROJ ---------------------------------------------------

class ProjUnavailable(RuntimeError):
    """pyproj is not installed (a source checkout without it)."""


def check_crs(code: str):
    """The pyproj CRS a user typed (``EPSG:27700``, ``27700``) if it is a
    projected system -- the drawing's coordinates are lengths -- else a
    ValueError that says why."""
    try:
        from pyproj import CRS
        from pyproj.exceptions import CRSError
    except ImportError as exc:                    # pragma: no cover
        raise ProjUnavailable("pyproj is not installed") from exc
    text = code.strip()
    if text.isdigit():
        text = f"EPSG:{text}"
    try:
        crs = CRS.from_user_input(text)
    except CRSError as exc:
        raise ValueError(f"unknown coordinate system {code!r}") from exc
    if not crs.is_projected:
        raise ValueError(f"{crs.name} is not a projected coordinate system")
    return crs


def crs_name(code: str) -> str:
    """``OSGB36 / British National Grid`` for ``EPSG:27700`` -- or the code
    itself when PROJ cannot say."""
    try:
        return check_crs(code).name
    except (ValueError, RuntimeError):
        return code


#: Datums whose best path to WGS84 goes through another geographic system:
#: France's old NTF reaches RGF93 v1 (EPSG:4171) through IGN's ntf_r93
#: grid (a few centimetres), while PROJ's own NTF -> WGS84 is a Helmert
#: shift (2 m). RGF93 is taken as WGS84, as PROJ does for Lambert-93
#: (1 m in EPSG's catalogue, the size of the ETRS89/ITRF drift).
PIVOTS = {"NTF": "EPSG:4171", "NTF (Paris)": "EPSG:4171"}


def _is_ballpark(transformer) -> bool:
    """PROJ's last resort when it knows no path: no shift at all, up to
    hundreds of metres off. Never taken when a real path exists."""
    accuracy = getattr(transformer, "accuracy", -1.0)
    return "ballpark" in str(getattr(transformer, "description", "")).lower() or accuracy is None \
        or accuracy < 0


@functools.lru_cache(maxsize=16)
def _candidates(code: str) -> tuple:
    """Every way PROJ knows from ``code`` to WGS84 lon/lat, most accurate
    first. The network stays on for PROJ: the best path for the British
    National Grid is the OSTN15 grid (1 m in EPSG's catalogue, mm in
    practice), fetched from cdn.proj.org on first use and cached; offline
    it cannot be read, and the next path -- a Helmert shift, metres -- still
    answers. A datum of :data:`PIVOTS` (France's NTF) tries its national
    grid first, through the pivot system."""
    try:
        import warnings

        from pyproj import CRS
        from pyproj.network import set_network_enabled
        from pyproj.transformer import TransformerGroup
    except ImportError as exc:                    # pragma: no cover
        raise ProjUnavailable("pyproj is not installed") from exc
    set_network_enabled(True)
    out: list = []
    with warnings.catch_warnings():               # "best not available": handled below
        warnings.simplefilter("ignore")
        try:
            geodetic = CRS.from_user_input(code).geodetic_crs.name
        except Exception:
            geodetic = ""
        pivot = PIVOTS.get(geodetic)
        if pivot:
            out += [t for t in TransformerGroup(code, pivot, always_xy=True).transformers
                    if not _is_ballpark(t)]
        group = TransformerGroup(code, "EPSG:4326", always_xy=True)
    out += list(group.transformers)
    return tuple(out)


@dataclass(frozen=True)
class Route:
    """How PROJ actually converts a coordinate system's points: the path
    it takes, its accuracy in metres (0 when unknown), and whether a more
    accurate path exists but cannot be read here (a grid, offline)."""

    description: str
    accuracy: float
    degraded: bool


def route(code: str, x: float | None = None, y: float | None = None) -> Route:
    """The path a point of ``code`` takes to WGS84 -- probed at ``(x, y)``,
    or at the centre of the system's area of use -- so GEOREF can say
    which conversion the drawing gets, and warn when it is not the best."""
    from pyproj import CRS, Transformer

    candidates = _candidates(code)
    if x is None or y is None:
        crs = CRS.from_user_input(code)
        area = crs.area_of_use
        if area is None:
            return Route(candidates[0].description if candidates else "", 0.0, False)
        lon = (area.west + area.east) / 2.0
        lat = (area.south + area.north) / 2.0
        # the projection alone, on the system's own datum: no grid involved
        x, y = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True).transform(lon, lat)
    for index, transformer in enumerate(candidates):
        a, b = transformer.transform(x, y)
        if math.isfinite(a) and math.isfinite(b):
            accuracy = transformer.accuracy if (transformer.accuracy or 0) > 0 else 0.0
            best = candidates[0].accuracy if (candidates[0].accuracy or 0) > 0 else accuracy
            return Route(transformer.description, float(accuracy),
                         index > 0 and float(accuracy) > float(best))
    return Route("", 0.0, False)


def _through_proj(code: str, x: float, y: float, inverse: bool) -> tuple[float, float]:
    from pyproj.enums import TransformDirection

    direction = TransformDirection.INVERSE if inverse else TransformDirection.FORWARD
    for transformer in _candidates(code):
        # a grid PROJ cannot fetch (offline) answers inf: take the next
        a, b = transformer.transform(x, y, direction=direction)
        if math.isfinite(a) and math.isfinite(b):
            return a, b
    raise ValueError(f"PROJ could not convert the point in {code}")


# -- France (IGN) -----------------------------------------------------------------------------

#: What a French surveyor types for the systems IGN publishes: Lambert-93,
#: the nine conic conformal zones CC42..CC50, the old NTF Lambert zones of
#: pre-2000 plans (II etendu is EPSG:27572), and the overseas departments.
FRENCH_SYSTEMS = {
    "L93": "EPSG:2154", "LAMBERT93": "EPSG:2154", "RGF93": "EPSG:2154",
    **{f"CC{n}": f"EPSG:{3900 + n}" for n in range(42, 51)},
    "LI": "EPSG:27571", "L1": "EPSG:27571",
    "LII": "EPSG:27572", "L2": "EPSG:27572", "LIIE": "EPSG:27572", "L2E": "EPSG:27572",
    "LIII": "EPSG:27573", "L3": "EPSG:27573",
    "LIV": "EPSG:27574", "L4": "EPSG:27574",
    "ANTILLES": "EPSG:5490", "GUADELOUPE": "EPSG:5490", "MARTINIQUE": "EPSG:5490",
    "GUYANE": "EPSG:2972", "REUNION": "EPSG:2975", "MAYOTTE": "EPSG:4471",
    "SPM": "EPSG:4467",
}


def cc_zone_for_lat(lat: float) -> int:
    """The conic conformal zone (42..50) for a latitude in degrees: zone n
    is centred on n degrees north, its standard parallels n +/- 0.75."""
    return min(50, max(42, int(math.floor(lat + 0.5))))


def french_system(text: str) -> str | None:
    """The EPSG code of what was typed -- ``L93``, ``CC44``, ``L2E``,
    ``Guyane``, or a latitude such as ``43.93`` for its CC zone -- or None
    when it names none of them."""
    token = re.sub(r"[\s\-_.]", "", text.strip().upper()).replace("É", "E")
    if token in FRENCH_SYSTEMS:
        return FRENCH_SYSTEMS[token]
    try:
        lat = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    if 41.0 <= lat <= 51.5:
        return f"EPSG:{3900 + cc_zone_for_lat(lat)}"
    return None


# -- typed and printed coordinates ----------------------------------------------------------

_SYMBOLS = str.maketrans({c: " " for c in "°º'′’\"″”,;"})
_TOKEN = re.compile(r"[-+]?\d+(?:\.\d+)?|[NSEWO]", re.IGNORECASE)
_HEMISPHERE = {"N": ("lat", 1.0), "S": ("lat", -1.0), "E": ("lon", 1.0),
               "W": ("lon", -1.0), "O": ("lon", -1.0)}         # O: Oeste


def _dms_value(numbers: list[float]) -> float:
    if not 1 <= len(numbers) <= 3:
        raise ValueError("a coordinate has one to three numbers")
    sign = -1.0 if numbers[0] < 0 or str(numbers[0]).startswith("-") else 1.0
    value = abs(numbers[0])
    if len(numbers) > 1:
        value += numbers[1] / 60.0
    if len(numbers) > 2:
        value += numbers[2] / 3600.0
    return sign * value


def parse_latlon(text: str) -> tuple[float, float]:
    """Latitude and longitude in degrees from what a user types::

        -16.398889, -71.536944         16.398889 S 71.536944 W
        16°23'56.0" S, 71°32'13.0" W   16 23 56 S 71 32 13 W
        -16 23 56 -71 32 13            16d23'56"S 71d32'13"W

    Hemisphere letters decide sign and which value is which; without
    them the order is latitude, longitude. Raises ValueError otherwise.
    """
    clean = text.strip().translate(_SYMBOLS)
    clean = re.sub(r"(?<=\d)[dD](?=\d)", " ", clean)    # 16d23' -> 16 23
    if not clean.strip():
        raise ValueError("empty")
    if re.sub(r"\s+", "", _TOKEN.sub("", clean)):
        raise ValueError(f"cannot read {text!r}")
    groups: list[tuple[list[float], str | None]] = []
    numbers: list[float] = []
    for token in _TOKEN.findall(clean):
        if token.upper() in _HEMISPHERE:
            if not numbers:
                raise ValueError(f"cannot read {text!r}")
            groups.append((numbers, token.upper()))
            numbers = []
        else:
            numbers.append(float(token))
    if numbers:
        groups.append((numbers, None))
    if len(groups) == 1 and groups[0][1] is None:
        nums = groups[0][0]
        if len(nums) not in (2, 4, 6):
            raise ValueError(f"cannot read {text!r}")
        half = len(nums) // 2
        groups = [(nums[:half], None), (nums[half:], None)]
    if len(groups) != 2:
        raise ValueError(f"cannot read {text!r}")
    lat = lon = None
    unnamed: list[float] = []
    for nums, hemisphere in groups:
        value = _dms_value(nums)
        if hemisphere is None:
            unnamed.append(value)
            continue
        which, sign = _HEMISPHERE[hemisphere]
        value = abs(value) * sign
        if which == "lat":
            lat = value
        else:
            lon = value
    for value in unnamed:
        if lat is None:
            lat = value
        elif lon is None:
            lon = value
    if lat is None or lon is None or abs(lat) > 90.0 or abs(lon) > 180.0:
        raise ValueError(f"cannot read {text!r}")
    return lat, lon


def format_decimal(lat: float, lon: float, decimals: int = 6) -> str:
    return f"{lat:.{decimals}f}, {lon:.{decimals}f}"


def _dms(value: float, positive: str, negative: str, decimals: int) -> str:
    scale = 10 ** decimals
    units = round(abs(value) * 3600.0 * scale)          # integer units, no 60.00"
    seconds_units = units % (60 * scale)
    minutes = (units // (60 * scale)) % 60
    degrees = units // (3600 * scale)
    seconds = seconds_units / scale
    return (f"{degrees}°{minutes:02d}'{seconds:0{3 + decimals}.{decimals}f}\" "
            f"{negative if value < 0 else positive}")


def format_dms(lat: float, lon: float, decimals: int = 2) -> str:
    """``16°23'56.00" S, 71°32'13.00" W``"""
    return f"{_dms(lat, 'N', 'S', decimals)}, {_dms(lon, 'E', 'W', decimals)}"
