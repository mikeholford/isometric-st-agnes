"""British National Grid (EPSG:27700) <-> WGS84, and the map's projections.

The Ordnance Survey's own formulas: a seven-parameter Helmert shift between WGS84 and OSGB36, then the Transverse
Mercator projection on the Airy 1830 ellipsoid. The Helmert shift alone is up to five metres off; OSTN15, the grid
of corrections the Ordnance Survey publishes, is exact. Over a map of a few kilometres that correction is one
constant shift, so GRID_FIX holds it, measured against OSTN15 (PROJ, "OSGB36 to WGS 84 (9)") at the corners and
the centre of this area: what is left is under 5 cm. Measure it again for another area.
"""

import math

from config import CX, CY, XMAX, XMIN, YMAX, YMIN

HX, HZ = (XMAX - XMIN) / 2, (YMAX - YMIN) / 2

GRID_FIX = (3.387, 0.886)  # metres added to the Helmert result (east, north) to match OSTN15 here

_AIRY = (6377563.396, 6356256.909)
_WGS = (6378137.0, 6356752.3141)
_F0, _LAT0, _LON0, _N0, _E0 = 0.9996012717, math.radians(49), math.radians(-2), -100000.0, 400000.0
# WGS84 -> OSGB36: metres, arc seconds, parts per million.
_HELMERT = (-446.448, 125.157, -542.060, -0.1502, -0.2470, -0.8421, 20.4894)


def _to_xyz(lat, lon, ell):
    a, b = ell
    e2 = 1 - b * b / (a * a)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return nu * math.cos(lat) * math.cos(lon), nu * math.cos(lat) * math.sin(lon), nu * (1 - e2) * math.sin(lat)


def _from_xyz(x, y, z, ell):
    a, b = ell
    e2 = 1 - b * b / (a * a)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(8):
        nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * nu * math.sin(lat), p)
    return lat, math.atan2(y, x)


def _helmert(x, y, z, sign):
    tx, ty, tz, rx, ry, rz, s = (sign * v for v in _HELMERT)
    rx, ry, rz = (math.radians(v / 3600) for v in (rx, ry, rz))
    s = 1 + s * 1e-6
    return tx + s * x - rz * y + ry * z, ty + rz * x + s * y - rx * z, tz - ry * x + rx * y + s * z


def _meridian(lat):
    a, b = _AIRY
    n = (a - b) / (a + b)
    d, s = lat - _LAT0, lat + _LAT0
    return b * _F0 * (
        (1 + n + 1.25 * n**2 + 1.25 * n**3) * d
        - (3 * n + 3 * n**2 + 2.625 * n**3) * math.sin(d) * math.cos(s)
        + (1.875 * n**2 + 1.875 * n**3) * math.sin(2 * d) * math.cos(2 * s)
        - 35 / 24 * n**3 * math.sin(3 * d) * math.cos(3 * s)
    )


def wgs_to_grid(lat, lon):
    """WGS84 degrees to British National Grid easting and northing in metres."""
    lat, lon = _from_xyz(*_helmert(*_to_xyz(math.radians(lat), math.radians(lon), _WGS), 1), _AIRY)
    a, b = _AIRY
    e2 = 1 - b * b / (a * a)
    n = (a - b) / (a + b)
    sin, cos, tan = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * _F0 / math.sqrt(1 - e2 * sin**2)
    rho = a * _F0 * (1 - e2) * (1 - e2 * sin**2) ** -1.5
    eta2 = nu / rho - 1
    m = _meridian(lat)
    d = lon - _LON0
    north = (
        m + _N0
        + nu / 2 * sin * cos * d**2
        + nu / 24 * sin * cos**3 * (5 - tan**2 + 9 * eta2) * d**4
        + nu / 720 * sin * cos**5 * (61 - 58 * tan**2 + tan**4) * d**6
    )
    east = (
        _E0
        + nu * cos * d
        + nu / 6 * cos**3 * (nu / rho - tan**2) * d**3
        + nu / 120 * cos**5 * (5 - 18 * tan**2 + tan**4 + 14 * eta2 - 58 * tan**2 * eta2) * d**5
    )
    return east + GRID_FIX[0], north + GRID_FIX[1]


def grid_to_wgs(east, north):
    """British National Grid metres to WGS84 degrees (lat, lon)."""
    east, north = east - GRID_FIX[0], north - GRID_FIX[1]
    a, b = _AIRY
    e2 = 1 - b * b / (a * a)
    lat = _LAT0
    m = 0.0
    while True:
        lat += (north - _N0 - m) / (a * _F0)
        m = _meridian(lat)
        if abs(north - _N0 - m) < 1e-5:
            break
    sin, cos, tan = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * _F0 / math.sqrt(1 - e2 * sin**2)
    rho = a * _F0 * (1 - e2) * (1 - e2 * sin**2) ** -1.5
    eta2 = nu / rho - 1
    d = east - _E0
    lat = (
        lat
        - tan / (2 * rho * nu) * d**2
        + tan / (24 * rho * nu**3) * (5 + 3 * tan**2 + eta2 - 9 * tan**2 * eta2) * d**4
        - tan / (720 * rho * nu**5) * (61 + 90 * tan**2 + 45 * tan**4) * d**6
    )
    lon = (
        _LON0
        + d / (cos * nu)
        - d**3 / (6 * cos * nu**3) * (nu / rho + 2 * tan**2)
        + d**5 / (120 * cos * nu**5) * (5 + 28 * tan**2 + 24 * tan**4)
        - d**7 / (5040 * cos * nu**7) * (61 + 662 * tan**2 + 1320 * tan**4 + 720 * tan**6)
    )
    lat, lon = _from_xyz(*_helmert(*_to_xyz(lat, lon, _AIRY), -1), _WGS)
    return math.degrees(lat), math.degrees(lon)


def screen(x, z, h=0.0, look=45):
    """Local meters (x east, z south, h up) to the render's screen meters (u right, v up) for a camera looking `look`
    degrees from north, 30 degrees down (render/scene.js). Works on numbers and numpy arrays alike."""
    a = math.radians(look)
    return x * math.cos(a) + z * math.sin(a), (x * math.sin(a) - z * math.cos(a)) * 0.5 + h * math.cos(math.radians(30))
