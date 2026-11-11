"""The viewer's search list: named places first, then every street, shop, farm and cove that has a name in OpenStreetMap.

England has no open register of addresses (the Dutch example lists every house number), so the search finds streets
and named places, not house numbers.
"""

import json

from config import BUILD, RAW, XMAX, XMIN, YMAX, YMIN
from geo import wgs_to_grid

SKIP = ("boundary", "route", "railway", "aeroway", "power", "type")  # relations and lines that are no place to fly to


def main():
    lm = json.loads((BUILD / "landmarks.json").read_text())
    places = [{"name": p["name"], "note": p.get("note"), "x": round(p["x"], 1), "y": round(p["y"], 1), "h": p["h"]} for p in lm["places"]]
    seen = {p["name"].lower() for p in places}
    path = RAW / "osm_names.json"
    for el in json.loads(path.read_text())["elements"] if path.exists() else []:
        t = el.get("tags", {})
        at = el if "lat" in el else el.get("center")
        name = t.get("name", "").strip()
        if not at or not name or any(k in t for k in SKIP) or t.get("place") in ("island", "county", "region"):
            continue
        x, y = wgs_to_grid(at["lat"], at["lon"])
        if not (XMIN <= x <= XMAX and YMIN <= y <= YMAX) or name.lower() in seen:
            continue
        seen.add(name.lower())  # a street comes in several stretches: the first is enough to find it
        kind = "Street" if "highway" in t else None
        places.append({"name": name, "note": kind, "x": round(x, 1), "y": round(y, 1), "h": 4})
    (BUILD / "places.json").write_text(json.dumps(places, ensure_ascii=False))
    print(f"{len(places)} places")


if __name__ == "__main__":
    main()
