"""Building outlines for the area, shared by scripts/landmarks.py (which names some) and scripts/build_buildings.py."""

import json

from shapely import STRtree
from shapely.geometry import Polygon, shape

from config import RAW, XMAX, XMIN, YMAX, YMIN
from geo import wgs_to_grid


def load_outlines():
    """Building outlines in grid metres: every OpenStreetMap building, plus the OS OpenMap Local buildings that
    OpenStreetMap does not have. Returns [(id, Polygon, tags)]."""
    out = []
    path = RAW / "osm_buildings.json"
    if path.exists():
        for el in json.loads(path.read_text())["elements"]:
            if el["type"] != "way" or len(el.get("geometry", [])) < 4:
                continue
            poly = Polygon([wgs_to_grid(g["lat"], g["lon"]) for g in el["geometry"]]).buffer(0)
            if poly.geom_type == "Polygon" and poly.area > 8:
                out.append((f"osm{el['id']}", poly, el.get("tags", {})))
    tree = STRtree([p for _, p, _ in out]) if out else None
    n_os = 0
    for i, f in enumerate(json.loads((RAW / "os_building.geojson").read_text())["features"]):
        geom = shape(f["geometry"]).buffer(0)
        for poly in getattr(geom, "geoms", [geom]):
            if poly.geom_type != "Polygon" or poly.area < 12:
                continue
            if tree is not None:
                near = [out[j][1] for j in tree.query(poly)]
                covered = sum(poly.intersection(o).area for o in near)
                if covered > 0.3 * poly.area:
                    # OpenStreetMap has (part of) this block already: keep what is left of it, if that is a building.
                    for o in near:
                        poly = poly.difference(o.buffer(0.3))
                    parts = [q for q in getattr(poly, "geoms", [poly]) if q.geom_type == "Polygon" and q.area > 25]
                    parts = [q.buffer(-0.6).buffer(0.6) for q in parts]
                    parts = [q for q in parts if q.geom_type == "Polygon" and q.area > 25]
                else:
                    parts = [poly]
            else:
                parts = [poly]
            for k, q in enumerate(parts):
                # Simplify a little: OpenMap Local outlines carry more points than a 1:10 000 map needs.
                q = q.simplify(0.3)
                if q.geom_type == "Polygon" and not q.is_empty:
                    out.append((f"os{i}_{k}", Polygon(q.exterior), {}))
                    n_os += 1
    inside = [(i, p, t) for i, p, t in out if XMIN - 20 < p.centroid.x < XMAX + 20 and YMIN - 20 < p.centroid.y < YMAX + 20]
    print(f"{len(inside)} outlines: {len(inside) - n_os} from OpenStreetMap, {n_os} from OS OpenMap Local")
    return inside
