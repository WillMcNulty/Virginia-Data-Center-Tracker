"""Small geometry helpers: distance in miles and point-in-polygon. site/geo.js has the same distance formula,
and tests/geo.test.js checks the two agree."""
import math

EARTH_MILES = 3958.8


def miles(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance in statute miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MILES * math.asin(math.sqrt(a))


def _in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_esri_polygon(x, y, rings):
    """Even-odd rule over all rings, which handles holes (Esri polygons list outer and inner rings together)."""
    return sum(_in_ring(x, y, r) for r in rings) % 2 == 1
