# /// script
# dependencies = ["shapely"]
# ///
"""Road names for the viewer: the name shows when the pointer is on a road.

The lines are the OpenStreetMap roads and paths the map draws. A road without a name in OpenStreetMap takes the name
and number of the OS OpenMap Local road that runs along it. Lines are in local meters on the ground (x east, z south
from the center of the area). Output: data/build/roads.json
  [{"n": name, "k": kind, "w": half width in meters, "p": [[x, z], ...]}, ...]
"""

import json
import math

from shapely.geometry import LineString, shape
from shapely.strtree import STRtree

from config import BUILD, CX, CY, RAW, XMAX, XMIN, YMAX, YMIN
from geo import wgs_to_grid

KINDS = {
    "primary": ("A road", 3.5), "secondary": ("B road", 3.2), "tertiary": ("Road", 3.0), "unclassified": ("Lane", 2.5),
    "residential": ("Street", 2.6), "living_street": ("Street", 2.4), "service": ("Access road", 2.0),
    "pedestrian": ("Street", 2.2), "track": ("Track", 1.6), "footway": ("Path", 1.2), "path": ("Path", 1.2),
    "steps": ("Steps", 1.2), "bridleway": ("Bridleway", 1.4), "cycleway": ("Cycle path", 1.4),
}
NEAR = 9.0  # an OS road line this close along a stretch is the same road


def os_roads():
    path = RAW / "os_road.geojson"
    lines, names = [], []
    for f in json.loads(path.read_text())["features"] if path.exists() else []:
        p = f["properties"]
        name, ref = (p.get("DISTNAME") or "").strip(), (p.get("ROADNUMBER") or "").strip()
        if name or ref:
            lines.append(shape(f["geometry"]))
            names.append((name, ref))
    return STRtree(lines) if lines else None, lines, names


def os_name(line, tree, lines, names):
    """The OS name and number that most of the sample points along the line agree on."""
    votes = {}
    n = max(2, int(line.length / 12))
    for i in range(n + 1):
        pt = line.interpolate(i / n, normalized=True)
        for j in tree.query(pt.buffer(NEAR)):
            if lines[j].distance(pt) <= NEAR:
                votes[names[j]] = votes.get(names[j], 0) + 1
    best = max(votes.items(), key=lambda kv: kv[1], default=None)
    return best[0] if best and best[1] >= 0.6 * (n + 1) else ("", "")


def main():
    tree, lines, names = os_roads()
    out, named = [], 0
    for el in json.loads((RAW / "osm_roads.json").read_text())["elements"]:
        t = el.get("tags", {})
        kind = KINDS.get(t.get("highway", "").replace("_link", ""))
        if el["type"] != "way" or not kind or len(el.get("geometry", [])) < 2:
            continue
        pts = [wgs_to_grid(p["lat"], p["lon"]) for p in el["geometry"]]
        if not any(XMIN <= x <= XMAX and YMIN <= y <= YMAX for x, y in pts):
            continue
        name, ref = t.get("name", "").strip(), t.get("ref", "").strip()
        if tree is not None and not (name and ref) and kind[0] not in ("Path", "Steps", "Track", "Bridleway", "Cycle path"):
            os_n, os_r = os_name(LineString(pts), tree, lines, names)
            name, ref = name or os_n, ref or os_r
        if not (name or ref):
            continue
        named += 1
        label = kind[0] if not ref or ref == name else f"{ref} · {kind[0]}"
        out.append({"n": name or ref, "k": label, "w": kind[1], "p": [[round(x - CX, 1), round(CY - y, 1)] for x, y in pts]})
    (BUILD / "roads.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    length = sum(math.dist(a, b) for r in out for a, b in zip(r["p"], r["p"][1:]))
    print(f"{named} named stretches of road, {length / 1000:.0f} km, {len({r['n'] for r in out})} names")


if __name__ == "__main__":
    main()
