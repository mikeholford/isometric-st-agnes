# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "shapely"]
# ///
"""Traffic for the viewer: lanes along the OpenStreetMap roads and paths that little cars, cyclists and walkers use.

A lane runs one way along a stretch of road between two junctions, on the left-hand side, as in Britain. There is
no open map of carriageway widths here, so a lane lies a fixed distance left of the OpenStreetMap line, by class of
road. Cars keep to the middle of their half, cyclists and walkers to its edge. Where a building, a tree crown or the
land itself (a hill, the side of a coombe) stands in front of the road on screen, the lane records a hidden stretch,
so a car disappears behind it instead of being drawn on the roof or the hillside; under a tree crown it shows
faintly, as if seen through the leaves. Roads that leave the map end in an exit: a car that drives out comes back in at another
exit of the same road class.

Output: data/build/traffic.json
  lanes  [{"e": road stretch, "a": from node, "b": to node, "p": [[x, z], ...] in local meters (x east, z south, as in
          render/scene.js), "c": road class, "v": speed for cars (m/s), "w", "wb" and "ww": weight when a car, a
          cyclist or a walker picks its next lane (0: not for them), "d", "db" and "dw": cars, cyclists and walkers
          per km, "bo" and "wo": how much further right a cyclist and a walker go than the lane (negative: left),
          "h": per view in config.VIEWS, [[s0, s1], ...] stretches in meters along the lane behind a building,
          "t": the same under tree crowns}]
  exits  the nodes where a road leaves the map
  views  the views the hidden stretches are for, as in config.VIEWS
"""

import json
import math
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, Point, box

from config import BUILD, CX, CY, LIDAR_RES, RAW, VIEWS, XMAX, XMIN, YMAX, YMIN
from geo import screen, wgs_to_grid

RES = 0.5  # occlusion raster, screen meters per pixel
STEP = 0.5  # lane sampling for hidden stretches, meters

# Road class: default speed (km/h, when OpenStreetMap gives no limit); for cars the weight at junctions (they prefer the bigger road) and cars per km of
# lane; the same two for cyclists, who prefer cycle paths and quiet roads, and for walkers, who prefer footpaths,
# village streets and farm tracks.
CLASSES = {
    "motorway": (120, 10, 8.0, 0, 0, 0, 0),
    "trunk": (100, 8, 4.0, 0, 0, 0, 0),
    "primary": (80, 6, 2.5, 0.5, 0.1, 0.3, 0.05),
    "secondary": (65, 5, 2.0, 1, 0.15, 0.5, 0.05),
    "tertiary": (50, 4, 1.6, 1.5, 0.3, 1, 0.25),
    "unclassified": (40, 3, 0.9, 3, 0.4, 1.5, 0.25),
    "residential": (30, 2, 1.6, 3, 0.6, 3, 1.5),
    "living_street": (15, 1, 1.0, 2, 0.5, 3, 1.5),
    "service": (15, 0.4, 0.4, 0.4, 0.05, 0.5, 0.1),
    "cycleway": (20, 0, 0, 5, 0.8, 1.5, 0.3),
    "track": (20, 0, 0, 0.5, 0.05, 2.5, 0.4),
    "footway": (5, 0, 0, 0, 0, 4, 1.5),
}
SKIP_SERVICE = {"parking_aisle", "driveway", "drive-through", "emergency_access"}
NO_CARS = {"no", "private", "agricultural", "forestry", "delivery"}
BIKES = {"yes", "designated", "permissive"}


def local(lat, lon):
    x, y = wgs_to_grid(lat, lon)
    return x - CX, CY - y


def road_ways():
    for w in json.loads((RAW / "osm_roads.json").read_text())["elements"]:
        t = w.get("tags", {})
        hw = t.get("highway", "")
        if w["type"] != "way" or t.get("area") == "yes" or t.get("service") in SKIP_SERVICE:
            continue
        if hw == "cycleway" or (hw in ("path", "track", "footway", "bridleway") and t.get("bicycle") in ("designated", "yes")):
            base = "cycleway"
        elif hw in ("footway", "path", "pedestrian", "steps", "bridleway"):
            base = "footway"
        else:
            base = hw.removesuffix("_link")
        if base not in CLASSES:
            continue
        kmh, weight, density, bike_weight, bike_density, walk_weight, walk_density = CLASSES[base]
        if NO_CARS & {t.get("access"), t.get("motor_vehicle"), t.get("motorcar"), t.get("vehicle")} - {None}:
            weight, density = 0, 0  # a farm road: no cars, but cyclists may
        if t.get("bicycle") in ("no", "use_sidepath") or (t.get("access") in ("no", "private") and t.get("bicycle") not in BIKES):
            bike_weight, bike_density = 0, 0
        if t.get("foot") in ("no", "use_sidepath") or (t.get("access") in ("no", "private") and t.get("foot") not in BIKES):
            walk_weight, walk_density = 0, 0
        if hw.endswith("_link"):
            walk_weight, walk_density = 0, 0
        if not weight and not bike_weight and not walk_weight:
            continue
        if hw.endswith("_link"):
            kmh, weight = min(kmh, 70), weight / 2
        digits = "".join(ch for ch in t.get("maxspeed", "") if ch.isdigit())
        if digits:
            kmh = int(digits) * (1.609 if "mph" in t["maxspeed"] else 1)
        oneway = t.get("oneway") in ("yes", "1", "true") or t.get("junction") in ("roundabout", "circular")
        oneway = oneway or (base == "motorway" and t.get("oneway") != "no")
        if t.get("oneway") == "-1":
            oneway = -1
        yield {
            "nodes": w["nodes"],
            "pts": [local(g["lat"], g["lon"]) for g in w["geometry"]],
            "c": base,
            "v": round(kmh / 3.6 * 0.9, 1),
            "w": weight,
            "d": density,
            "wb": bike_weight,
            "db": bike_density,
            "ww": walk_weight,
            "dw": walk_density,
            "oneway": oneway,
        }


def stretches(ways):
    """Split the ways at junctions: nodes shared by more than one way, and the ends of every way."""
    use = Counter(n for w in ways for n in w["nodes"])
    junction = {n for n, k in use.items() if k > 1} | {w["nodes"][0] for w in ways} | {w["nodes"][-1] for w in ways}
    for w in ways:
        start, pts = 0, [w["pts"][0]]
        for i in range(1, len(w["nodes"])):
            pts.append(w["pts"][i])
            if w["nodes"][i] in junction:
                yield {**w, "a": str(w["nodes"][start]), "b": str(w["nodes"][i]), "pts": pts}
                start, pts = i, [w["pts"][i]]


def clip(edges):
    """Keep what lies on the map; a road cut off by the map's edge ends in an exit there."""
    area = box(XMIN - CX + 1, CY - YMAX + 1, XMAX - CX - 1, CY - YMIN - 1)
    exits, n = set(), 0
    for e in edges:
        line = LineString(e["pts"])
        if area.contains(line):
            yield e
            continue
        part = line.intersection(area)
        pieces = getattr(part, "geoms", [part])
        for piece in pieces:
            if piece.geom_type != "LineString" or piece.length < 1:
                continue
            c = list(piece.coords)
            ends = []
            for pt, node in ((c[0], e["a"]), (c[-1], e["b"])):
                if Point(pt).distance(Point(e["pts"][0] if node == e["a"] else e["pts"][-1])) < 0.01:
                    ends.append(node)
                else:
                    n += 1
                    ends.append(f"x{n}")
                    exits.add(f"x{n}")
            yield {**e, "a": ends[0], "b": ends[1], "pts": c}
    clip.exits = exits


def offset(pts, d):
    """The polyline moved d meters to the right of its direction (x east, z south: right of east is south)."""
    p = np.asarray(pts, dtype=np.float64)
    keep = np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 0.05]
    p = p[keep]
    if len(p) < 2 or d == 0:
        return p
    seg = np.diff(p, axis=0)
    seg /= np.linalg.norm(seg, axis=1, keepdims=True)
    nrm = np.stack([-seg[:, 1], seg[:, 0]], axis=1)
    vn = np.vstack([nrm[:1], nrm[:-1] + nrm[1:], nrm[-1:]])
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-9)
    # Miter: a corner moves out further than d, up to twice as far for sharp bends.
    cos = np.r_[1.0, np.einsum("ij,ij->i", vn[1:-1], nrm[1:]), 1.0]
    return p + vn * (d / np.clip(cos, 0.5, 1.0))[:, None]


def lanes(edges):
    out = []
    for i, e in enumerate(edges):
        dirs = [(e["pts"], e["a"], e["b"])]
        if e["oneway"] == -1:
            dirs = [(e["pts"][::-1], e["b"], e["a"])]
        elif not e["oneway"]:
            dirs.append((e["pts"][::-1], e["b"], e["a"]))
        # Half the width of the road, by class: Cornish lanes are narrow, and many take only one car.
        width = {"cycleway": 0.6, "footway": 0.3, "track": 0.6}.get(e["c"])
        width = width or (1.0 if e["c"] in ("residential", "living_street", "service", "unclassified") else 1.5)
        for pts, a, b in dirs:
            # Britain drives on the left: a negative offset is to the left of the direction of travel.
            off = 0.0 if e["oneway"] else -width
            bike = off if e["c"] in ("cycleway", "track") else off - 0.7
            walk = off if e["c"] in ("footway", "track") else bike - 0.25
            p = offset(pts, off)
            if len(p) >= 2:
                lane = {"e": i, "a": a, "b": b, "p": p, **{k: e[k] for k in ("c", "v", "w", "d", "wb", "db", "ww", "dw")}}
                lane["bo"], lane["wo"] = round(bike - off, 2), round(walk - off, 2)
                out.append(lane)
    return out


def heights(dtm, xs, zs):
    """Ground height at local positions (x east, z south)."""
    rows = np.clip(((YMAX - (CY - zs)) / LIDAR_RES).astype(int), 0, dtm.shape[0] - 1)
    cols = np.clip(((xs + CX - XMIN) / LIDAR_RES).astype(int), 0, dtm.shape[1] - 1)
    return dtm[rows, cols]


def behind_land(dtm, xs, zs, hs, look, step=4.0):
    """Which ground points the land itself hides in this view: walk from each point toward the camera along its line
    of sight, which climbs as it comes nearer, and see whether the ground anywhere stands above it."""
    a = math.radians(look)
    c, sn, cos30 = math.cos(a), math.sin(a), math.cos(math.radians(30))
    u, w = xs * c + zs * sn, xs * sn - zs * c  # across the screen, and away from the camera
    hidden = np.zeros(len(xs), bool)
    top = float(dtm.max())
    for k in range(1, int(2 * cos30 * (top - float(hs.min())) / step) + 2):
        wk = w - k * step
        ray = hs + k * step / (2 * cos30) + 1.2  # a car's roof may still show over the brow
        if (ray > top).all():
            break
        hidden |= heights(dtm, u * c + wk * sn, u * sn - wk * c) > ray
    return hidden


def occluders(bounds, look):
    """Rasters in screen meters of what stands up from the ground: one of the buildings, one of the tree crowns.

    A ground point whose screen position falls inside one is behind it, or under it."""
    u0, v0, u1, v1 = bounds
    w, h = int((u1 - u0) / RES) + 1, int((v1 - v0) / RES) + 1
    img = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(img)
    trees = Image.new("1", (w, h), 0)
    px = lambda u, v: ((u - u0) / RES, (v1 - v) / RES)

    b = np.fromfile(BUILD / "buildings.bin", dtype=np.float32).reshape(-1, 12)
    u, v = screen(b[:, 0], b[:, 2], b[:, 1], look)  # building heights are absolute (metres above datum)
    tri = np.stack([(u - u0) / RES, (v1 - v) / RES], axis=1).reshape(-1, 3, 2)
    for t in tri:
        draw.polygon([tuple(q) for q in t], fill=1)

    buildings = np.array(img, dtype=bool)
    draw = ImageDraw.Draw(trees)
    t = np.fromfile(BUILD / "trees.bin", dtype=np.float32).reshape(-1, 11)
    for x, z, ht, r, base, kind, g in t[:, [0, 1, 2, 3, 4, 5, 10]]:
        if kind > 0.5:  # conifer: a cone from half the crown base up to the top
            bottom, rr = base * 0.5, r * 0.9
            cu, cv = screen(x, z, g + bottom, look)
            _, tv = screen(x, z, g + ht, look)
            ring = [px(cu + rr * math.cos(a), cv + 0.5 * rr * math.sin(a)) for a in np.linspace(math.pi, 2 * math.pi, 7)]
            draw.polygon([*ring, px(cu, tv)], fill=1)
        else:  # round crown, as render/scene.js scales it: an ellipsoid r * 1.12 wide and `half` high
            half = max(1, (ht - base) / 2, min(r * 0.9, ht * 0.42))
            cu, cv = screen(x, z, g + ht - half, look)
            a = r * 1.12
            bv = math.hypot(0.5 * a, math.cos(math.radians(30)) * half)
            (l, top), (rgt, bot) = px(cu - a, cv + bv), px(cu + a, cv - bv)
            draw.ellipse([l, top, rgt, bot], fill=1)
    return buildings, np.array(trees, dtype=bool)


def stretches_where(hit, s):
    """Runs of samples where hit is set, as [from, to] in meters; small gaps closed so nothing flickers."""
    runs, start = [], None
    for i, h in enumerate(np.r_[hit, False]):
        if h and start is None:
            start = i
        elif not h and start is not None:
            runs.append([s[start] - STEP / 2, s[i - 1] + STEP / 2])
            start = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < 1.5:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [[round(a, 1), round(b, 1)] for a, b in merged if b - a >= 1]


def hidden(lanes_):
    dtm = np.load(BUILD / "dtm.npy")
    samples = []
    for ln in lanes_:
        p = ln["p"]
        seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
        cum = np.r_[0, np.cumsum(seg)]
        s = np.arange(0, cum[-1], STEP)
        xs, zs = np.interp(s, cum, p[:, 0]), np.interp(s, cum, p[:, 1])
        samples.append((s, xs, zs, heights(dtm, xs, zs)))
    for ln in lanes_:
        ln["h"], ln["t"] = [], []
    for look in VIEWS:
        uv = [screen(xs, zs, hs, look) for _, xs, zs, hs in samples]
        us, vs = np.concatenate([u for u, _ in uv]), np.concatenate([v for _, v in uv])
        bounds = (us.min() - 2, vs.min() - 2, us.max() + 2, vs.max() + 2)
        buildings, trees = occluders(bounds, look)
        u0, _, _, v1 = bounds
        for ln, (s, xs, zs, hs), (u, v) in zip(lanes_, samples, uv):
            at = ((v1 - v) / RES).astype(int), ((u - u0) / RES).astype(int)
            gone = buildings[at] | behind_land(dtm, xs, zs, hs, look)
            ln["h"].append(stretches_where(gone, s))
            ln["t"].append(stretches_where(trees[at] & ~gone, s))


def main():
    ways = list(road_ways())
    edges = list(clip(stretches(ways)))
    out = lanes(edges)
    hidden(out)
    for ln in out:
        ln["p"] = [[round(float(x), 1), round(float(z), 1)] for x, z in ln["p"]]
    (BUILD / "traffic.json").write_text(json.dumps({"views": list(VIEWS), "lanes": out, "exits": sorted(clip.exits)}, separators=(",", ":")))
    km = sum(np.linalg.norm(np.diff(np.array(ln["p"]), axis=0), axis=1).sum() for ln in out) / 1000
    share = sum(sum(b - a for a, b in ln["h"][0]) for ln in out) / 1000 / km
    leafy = sum(sum(b - a for a, b in ln["t"][0]) for ln in out) / 1000 / km
    print(f"{len(out)} lanes, {km:.0f} km, {len(clip.exits)} exits, {share:.0%} behind buildings or hills, {leafy:.0%} under trees")


if __name__ == "__main__":
    main()
