"""Walking routes for the viewer: the South West Coast Path and other waymarked routes from OpenStreetMap.

Lines are in local meters on the ground (x east, z south from the center of the area), which the viewer projects for
the view it shows. Output: data/build/routes.json
"""

import json

from config import BUILD, CX, CY, RAW, XMAX, XMIN, YMAX, YMIN
from geo import wgs_to_grid


def ground(lat, lon):
    x, y = wgs_to_grid(lat, lon)
    return [round(x - CX, 1), round(CY - y, 1)], XMIN <= x <= XMAX and YMIN <= y <= YMAX


def main():
    path = RAW / "osm_routes.json"
    routes, nodes = [], []
    if path.exists():
        for el in json.loads(path.read_text())["elements"]:
            t = el.get("tags", {})
            if el["type"] == "relation":
                lines = []
                for m in el.get("members", []):
                    if m.get("type") != "way" or not m.get("geometry"):
                        continue
                    pts = [ground(p["lat"], p["lon"]) for p in m["geometry"]]
                    if any(inside for _, inside in pts):
                        lines.append([p for p, _ in pts])
                if lines:
                    network = t.get("network", "")
                    name = t.get("name") or t.get("ref") or "Walking route"
                    routes.append({"name": name, "kind": "long" if network in ("nwn", "iwn") else "junction", "ref": t.get("ref"), "lines": lines})
            elif el["type"] == "node" and t.get("rwn_ref"):
                p, inside = ground(el["lat"], el["lon"])
                if inside:
                    nodes.append({"ref": t["rwn_ref"], "at": p})
    (BUILD / "routes.json").write_text(json.dumps({"routes": routes, "nodes": nodes}, ensure_ascii=False))
    print(f"{len(routes)} routes, {len(nodes)} junctions")


if __name__ == "__main__":
    main()
