# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "mapbox-earcut", "pillow", "scipy", "shapely"]
# ///
"""Turn building outlines and lidar into one triangle soup for the renderer.

England has no open 3D building model like the Dutch 3D BAG, so the buildings are made here: outlines from
OpenStreetMap where someone drew them and from OS OpenMap Local everywhere else, and for each outline the lidar
surface model says how high the roof is, how much it rises from eaves to ridge and which way the ridge runs.
A simple outline gets a gabled roof, a complex one a hipped roof, a level one a flat roof.

Output (data/build/):
  buildings.bin   float32 per vertex: x, y, z, nx, ny, nz, u, v, kind, building index, atlas u, atlas v (-1: none)
  roof_atlas.png  a placeholder: there is no open aerial photo here to take real roofs from
  buildings.json  per building: id, attributes, wall and roof colors
  footprints.json per building: footprint ring in local meters, for the ground and tree steps

Local coordinates: x east, y up (metres above Ordnance Datum), z south, origin at the area center.
"""

import hashlib
import json
from collections import Counter

import mapbox_earcut as earcut
import numpy as np
from PIL import Image, ImageDraw
from shapely import STRtree
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import split, voronoi_diagram

from config import BUILD, CX, CY, LIDAR_RES, RAW, XMAX, XMIN, YMAX, YMIN, write_area
from outlines import load_outlines
from roofs import lidar_roof

KIND = {"GroundSurface": 0, "WallSurface": 1, "RoofSurface": 2}
COLS = 12

# Roofs of a Cornish village: Delabole slate on nearly every house, new or weathered, and a few of grey-brown
# concrete tile; fibre cement or tin sheet on the farm buildings. (colour, weight)
ROOFS_HOUSE = [((70, 73, 80), 5), ((82, 85, 92), 5), ((58, 62, 70), 3), ((96, 98, 102), 2), ((102, 94, 88), 1)]
ROOFS_BARN = [((150, 150, 146), 3), ((120, 122, 124), 3), ((98, 114, 98), 2), ((88, 90, 96), 2), ((120, 92, 70), 1)]

# One house looks like the next when each takes its measures from a noisy 1 m lidar grid, so the lidar only
# decides what it can tell apart: how many storeys, whether the roof is pitched, and which way the ridge runs.
# The rest is the same for every house: eaves at a storey height, a roof pitch of 38 degrees.
EAVES = (2.7, 5.3, 7.9)  # height of the eaves for one, two and three storeys
PITCH = 0.78  # rise per metre of half width
MAX_RISE = 4.6


def ring_area(xy):
    return 0.5 * (np.dot(xy[:, 0], np.roll(xy[:, 1], 1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], 1)))


def extrude(rings_xy, z0, z1):
    """Prism from a footprint (rings in RD x/y, first exterior). Yields (kind, rings in 3D)."""
    out = []
    for i, r in enumerate(rings_xy):
        r = np.asarray(r, dtype=np.float64)[:, :2]
        if np.allclose(r[0], r[-1]):
            r = r[:-1]
        # Exterior counter-clockwise, holes clockwise, so wall normals point outward.
        if (ring_area(r) > 0) != (i == 0):
            r = r[::-1]
        for a, b in zip(r, np.roll(r, -1, axis=0)):
            if np.linalg.norm(b - a) < 0.05:
                continue
            out.append((1, [np.array([[a[0], a[1], z0], [b[0], b[1], z0], [b[0], b[1], z1], [a[0], a[1], z1]])]))
    top = []
    for i, r in enumerate(rings_xy):
        r = np.asarray(r, dtype=np.float64)[:, :2]
        if np.allclose(r[0], r[-1]):
            r = r[:-1]
        if (ring_area(r) > 0) != (i == 0):
            r = r[::-1]
        top.append(np.column_stack([r, np.full(len(r), z1)]))
    out.append((2, top))
    return out


def long_axis(xy):
    """Direction (radians, RD x/y) of the longest footprint edge."""
    xy = np.asarray(xy)[:, :2]
    d = np.roll(xy, -1, axis=0) - xy
    i = int(np.argmax(np.hypot(d[:, 0], d[:, 1])))
    return float(np.arctan2(d[i, 1], d[i, 0]))


def newell_normal(pts):
    n = np.zeros(3)
    for a, b in zip(pts, np.roll(pts, -1, axis=0)):
        n += [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]
    norm = np.linalg.norm(n)
    return n / norm if norm > 0 else None


def triangulate(rings):
    """rings: list of (N,3) arrays in RD meters, first is the exterior. Returns (M,3,3) triangles."""
    n = newell_normal(rings[0])
    if n is None:
        return np.zeros((0, 3, 3)), None
    drop = int(np.argmax(np.abs(n)))
    keep = [i for i in range(3) if i != drop]
    pts = np.concatenate(rings)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(pts[:, keep], ends)
    tris = pts[idx].reshape(-1, 3, 3)
    # earcut does not keep the winding; flip triangles that face away from the surface normal.
    tn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    flip = (tn @ n) < 0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    return tris, n


def stable_rand(key, salt=""):
    return int(hashlib.md5((key + salt).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def emit(verts, surfaces, bi, ground, center_u=False):
    """surfaces: iterable of (kind, rings in RD meters with absolute z). Appends vertices; returns roof triangles.

    center_u puts u=0 in the middle of each wall, so towers can draw a clock or louvres centered on a face."""
    roof_tris = []
    for kind, rings in surfaces:
        if kind == 0:
            continue  # the floor is never visible
        tris, n = triangulate(rings)
        if n is None or len(tris) == 0:
            continue
        if kind == 2:
            roof_tris.append(tris)
        # Wall pattern coordinates: u runs along the wall, v is height above ground.
        if kind == 1:
            h = np.array([n[1], -n[0]])
            h = h / (np.linalg.norm(h) or 1)
            u = tris[..., :2] @ h
            if center_u:
                u = u - 0.5 * (u.min() + u.max())
            uv = np.stack([u, tris[..., 2] - ground], axis=-1)
        else:
            uv = tris[..., :2] - [CX, CY]
        local = np.stack([tris[..., 0] - CX, tris[..., 2], CY - tris[..., 1]], axis=-1)
        normal = np.broadcast_to([n[0], n[2], -n[1]], local.shape)
        if kind == 2:
            # A roof surface can be folded (the hipped ring around a complex building): a normal per triangle.
            tn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
            tn /= np.maximum(np.linalg.norm(tn, axis=1, keepdims=True), 1e-9)
            tn[tn[:, 2] < 0] *= -1
            normal = np.repeat(np.stack([tn[:, 0], tn[:, 2], -tn[:, 1]], -1)[:, None, :], 3, axis=1)
        block = np.concatenate(
            [local, normal, uv, np.full(local.shape[:2] + (1,), kind), np.full(local.shape[:2] + (1,), bi),
             np.full(local.shape[:2] + (2,), -1.0)],
            axis=-1,
        ).reshape(-1, COLS)
        verts.append(block)
    return roof_tris


def ccw(ring):
    ring = np.asarray(ring, dtype=np.float64)
    return ring if ring_area(ring) > 0 else ring[::-1]


def rect_ring(cx, cy, w, d, ang):
    c, s = np.cos(ang), np.sin(ang)
    pts = [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]
    return ccw([(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts])


def ngon_ring(cx, cy, r, n, ang):
    return ccw([(cx + r * np.cos(ang + 2 * np.pi * (i + 0.5) / n), cy + r * np.sin(ang + 2 * np.pi * (i + 0.5) / n)) for i in range(n)])


def pyramid(ring, z0, apex):
    """Roof triangles from a footprint ring up to a point above its center."""
    ring = ccw(ring)
    cx, cy = ring.mean(0)
    return [(2, [np.array([[a[0], a[1], z0], [b[0], b[1], z0], [cx, cy, apex]])]) for a, b in zip(ring, np.roll(ring, -1, axis=0))]


def frustum(bottom, top, z0, z1):
    """Walls between two rings with the same vertex count, for tapered masts."""
    bottom, top = ccw(bottom), ccw(top)
    out = []
    for i in range(len(bottom)):
        j = (i + 1) % len(bottom)
        out.append((1, [np.array([[*bottom[i], z0], [*bottom[j], z0], [*top[j], z1], [*top[i], z1]])]))
    out.append((2, [np.column_stack([top, np.full(len(top), z1)])]))
    return out


def part(meta, pid, kind, axis, height, wall, roof, param=0.0):
    meta.append({"id": f"{pid}-{kind}", "kind": kind, "axis": round(float(axis), 4), "param": param, "height": height,
                 "wall_fixed": list(wall), "roof_fixed": list(roof), "rand": 0.5, "roof_rgb": None})
    return len(meta) - 1


def add_landmark_parts(verts, meta, pid, lm, ground, axis, roof_tris):
    """Towers, spires, roof turrets, crosses and chimney stacks that the lidar roof fit smooths away."""
    wall, roof = lm.get("wall", (150, 80, 62)), lm.get("roof", (70, 72, 80))
    if "tower" in lm:
        t = lm["tower"]
        ring = rect_ring(t["x"], t["y"], t["w"], t["w"], axis)
        bi = part(meta, pid, "tower", axis, t["top"], wall, roof, param=t["body"])
        emit(verts, extrude([ring], ground, ground + t["body"]), bi, ground, center_u=True)
        emit(verts, pyramid(ring, ground + t["body"], ground + t["top"]), bi, ground)
        if t.get("cross"):
            bi = part(meta, pid, "cross", axis, t["top"] + 2, (196, 170, 96), (196, 170, 96))
            top = ground + t["top"]
            emit(verts, extrude([rect_ring(t["x"], t["y"], 0.3, 0.3, axis)], top - 0.4, top + 2.2), bi, ground)
            emit(verts, extrude([rect_ring(t["x"], t["y"], 1.4, 0.3, axis)], top + 1.2, top + 1.5), bi, ground)
    if "turret" in lm:
        t = lm["turret"]
        ring = ngon_ring(t["x"], t["y"], t["r"], 8, axis)
        bi = part(meta, pid, "turret", axis, t["top"], (240, 238, 230), (62, 64, 72), param=t["body"])
        emit(verts, extrude([ring], ground + t["base"], ground + t["body"]), bi, ground, center_u=True)
        emit(verts, pyramid(ring, ground + t["body"], ground + t["top"]), bi, ground)
    for t in lm.get("stacks", []):
        # A mine chimney: a round, tapering stack of stone with a brick top.
        n = 10
        bi = part(meta, pid, "stack", 0.0, t["height"], t.get("wall", (150, 138, 122)), (96, 60, 48), param=t["height"])
        g = t.get("ground", ground)
        emit(verts, frustum(ngon_ring(t["x"], t["y"], t["r"], n, 0.0), ngon_ring(t["x"], t["y"], t["r"] * t.get("taper", 0.62), n, 0.0), g - 0.5, g + t["height"]), bi, g, center_u=True)
    if lm.get("bell") and roof_tris:
        # A small white bell turret on the highest point of the roof, as on the school.
        pts = np.concatenate(roof_tris).reshape(-1, 3)
        x, y, zmax = pts[np.argmax(pts[:, 2])]
        ring = rect_ring(x, y, 1.5, 1.5, axis)
        bi = part(meta, pid, "turret", axis, zmax - ground + 3.4, (240, 238, 230), (70, 74, 82), param=zmax - ground + 2.0)
        emit(verts, extrude([ring], zmax - 0.4, zmax + 2.0), bi, ground, center_u=True)
        emit(verts, pyramid(ring, zmax + 2.0, zmax + 3.4), bi, ground)


def add_masts(verts, meta, masts, dtm):
    for m in masts:
        g = ground_at(dtm, m["x"], m["y"])
        bot = rect_ring(m["x"], m["y"], m["base"], m["base"], 0.3)
        top = rect_ring(m["x"], m["y"], m["tip"], m["tip"], 0.3)
        bi = part(meta, "mast", "mast", 0.3, m["height"], (184, 188, 192), (150, 154, 158), param=m["height"])
        emit(verts, frustum(bot, top, g - 0.5, g + m["height"]), bi, g, center_u=True)


def long_side(poly):
    rc = np.array(poly.minimum_rotated_rectangle.exterior.coords)[:4]
    e1, e2 = rc[1] - rc[0], rc[2] - rc[1]
    e = e1 if np.hypot(*e1) >= np.hypot(*e2) else e2
    return float(np.arctan2(e[1], e[0]))


def ground_at(dtm, x, y):
    row = int(np.clip((YMAX - y) / LIDAR_RES, 0, dtm.shape[0] - 1))
    col = int(np.clip((x - XMIN) / LIDAR_RES, 0, dtm.shape[1] - 1))
    return float(dtm[row, col])


def pick(options, r):
    total = sum(w for _, w in options)
    t = r * total
    for c, w in options:
        t -= w
        if t <= 0:
            return c
    return options[0][0]


def measure(poly, dtm, dsm):
    """What the lidar says about a building: floor level, lowest ground, ridge height, rise of the roof and the
    direction of the ridge (radians, grid x/y), or None for the ridge when the roof is flat or too small to tell."""
    x0, y0, x1, y1 = poly.bounds
    c0, c1 = int((x0 - XMIN) / LIDAR_RES) - 1, int((x1 - XMIN) / LIDAR_RES) + 2
    r0, r1 = int((YMAX - y1) / LIDAR_RES) - 1, int((YMAX - y0) / LIDAR_RES) + 2
    c0, r0, c1, r1 = max(c0, 0), max(r0, 0), min(c1, dtm.shape[1]), min(r1, dtm.shape[0])
    if c1 - c0 < 2 or r1 - r0 < 2:
        return None
    px = lambda ring: [((x - XMIN) / LIDAR_RES - c0, (YMAX - y) / LIDAR_RES - r0) for x, y in ring.coords]
    mask = Image.new("L", (c1 - c0, r1 - r0), 0)
    ImageDraw.Draw(mask).polygon(px(poly.exterior), fill=1)
    inner = np.array(mask) > 0
    core = inner.copy()
    core[1:, :] &= inner[:-1, :]
    core[:-1, :] &= inner[1:, :]
    core[:, 1:] &= inner[:, :-1]
    core[:, :-1] &= inner[:, 1:]
    use = core if core.sum() >= 12 else inner
    g = dtm[r0:r1, c0:c1]
    ring = Image.new("L", (c1 - c0, r1 - r0), 0)
    ImageDraw.Draw(ring).line(px(poly.exterior), fill=1, width=3)
    around = (np.array(ring) > 0) | inner
    # The lowest ground the walls must reach: not one stray deep cell (a culvert, a shaft, a lidar fault), which
    # would hang a wall of 20 m under one corner.
    floor, low = float(np.median(g[around])), float(np.percentile(g[around], 4))
    # The ground under the building as a tilted plane (height = floor + tilt . (x - cx, y - cy)), for a building
    # that stands on a slope.
    rr, cc = np.nonzero(around)
    gx, gy = XMIN + (c0 + cc + 0.5) * LIDAR_RES, YMAX - (r0 + rr + 0.5) * LIDAR_RES
    cx, cy = poly.centroid.x, poly.centroid.y
    coef, *_ = np.linalg.lstsq(np.column_stack([gx - cx, gy - cy, np.ones(len(gx))]), g[around], rcond=None)
    slope = {"tilt": (float(coef[0]), float(coef[1])), "center": (cx, cy), "drop": float(g[around].max()) - low}
    if use.sum() < 4:
        return {"floor": floor, "low": low, "ridge": 3.0, "rise": 0.0, "axis": None, "cells": 0, **slope}
    rel = dsm[r0:r1, c0:c1][use] - floor
    ridge = float(np.percentile(rel, 93))
    spread = ridge - float(np.percentile(rel, 40))
    rows, cols = np.nonzero(use)
    xs, ys = XMIN + (c0 + cols + 0.5) * LIDAR_RES, YMAX - (r0 + rows + 0.5) * LIDAR_RES
    # Which way does the ridge run? Along the long side or across: the one where height falls off with the distance
    # from the middle line.
    rect = poly.minimum_rotated_rectangle
    rc = np.array(rect.exterior.coords)[:4]
    e1, e2 = rc[1] - rc[0], rc[2] - rc[1]
    long_e, short_e = (e1, e2) if np.hypot(*e1) >= np.hypot(*e2) else (e2, e1)
    center = rc.mean(0)
    best, axis = -2.0, None
    for along, across in ((long_e, short_e), (short_e, long_e)):
        width = np.hypot(*across)
        if width < 3.0:
            continue
        nrm = across / width
        d = np.abs((xs - center[0]) * nrm[0] + (ys - center[1]) * nrm[1])
        if d.std() < 0.3 or rel.std() < 0.15:
            continue
        corr = float(np.corrcoef(-d, rel)[0, 1])
        # The long side wins unless the short one is clearly better: most roofs run the long way.
        score = corr + (0.15 if along is long_e else 0.0)
        if score > best:
            best, axis = score, float(np.arctan2(along[1], along[0]))
    rise = float(np.clip(spread / 0.52, 0.0, max(ridge - 2.0, 0.0)))
    if rise < 0.7 or best < 0.25:
        rise, axis = (0.0, None) if rise < 0.7 else (rise, float(np.arctan2(long_e[1], long_e[0])))
    return {**slope, "floor": floor, "low": low, "ridge": ridge, "rise": rise, "axis": axis, "cells": int(use.sum()),
            "fill": poly.area / max(rect.area, 1e-6), "short": float(np.hypot(*short_e)), "long": float(np.hypot(*long_e))}


def steps(poly, dtm):
    """A long, simple building on a slope is a terrace that steps down the hill, like Stippy Stappy on Town Hill:
    the map draws the whole row as one outline. Cut it across into houses, so each gets its own floor level."""
    rect = poly.minimum_rotated_rectangle
    rc = np.array(rect.exterior.coords)[:4]
    e1, e2 = rc[1] - rc[0], rc[2] - rc[1]
    origin, long_e, short_e = (rc[0], e1, e2) if np.hypot(*e1) >= np.hypot(*e2) else (rc[1], e2, -e1)
    length = float(np.hypot(*long_e))
    if length < 13 or poly.area / max(rect.area, 1e-6) < 0.78 or poly.interiors:
        return [poly]
    ends = [ground_at(dtm, *(origin + short_e / 2 + long_e * t)) for t in (0.05, 0.95)]
    if abs(ends[0] - ends[1]) < 2.0:
        return [poly]
    n = max(2, round(length / 6.5))
    out = []
    for k in range(n):
        a, b = origin + long_e * (k / n), origin + long_e * ((k + 1) / n)
        strip = Polygon([a - short_e * 0.1, b - short_e * 0.1, b + short_e * 1.1, a + short_e * 1.1])
        piece = poly.intersection(strip)
        out += [q for q in getattr(piece, "geoms", [piece]) if q.geom_type == "Polygon" and q.area > 6]
    return out or [poly]


def load_addresses():
    """Address points from OS Open UPRN (scripts/fetch.py), as an index to ask which lie in an outline."""
    path = RAW / "os_uprn.json"
    pts = [Point(x, y) for x, y in json.loads(path.read_text())] if path.exists() else []
    return (STRtree(pts) if pts else None), pts


def houses(poly, tree, pts):
    """OS OpenMap Local draws a terrace, or a whole block in the middle of the village, as one outline. Every house
    in it has an address point, so the outline is cut where one address ends and the next begins: each house is the
    part of the block that is nearer to its own address than to any other. Returns [(polygon, direction of the row
    at this house in radians, or None)] and the number of addresses in the block."""
    if tree is None:
        return [(poly, None)], None
    inside = [pts[j] for j in tree.query(poly) if poly.buffer(0.5).contains(pts[j])]
    # Flats and an upstairs office share a spot or lie a few metres apart: one house. And a house needs room, so
    # the addresses are grouped more coarsely until each has at least 28 square metres of the block.
    for gap in (3.0, 4.5, 6.0, 8.0):
        groups = []
        for q in inside:
            near = next((g for g in groups if any(q.distance(o) < gap for o in g)), None)
            if near is None:
                groups.append([q])
            else:
                near.append(q)
        if poly.area / max(len(groups), 1) >= 28:
            break
    count = len(groups)
    if count < 2 or poly.interiors:
        return [(poly, None)], count
    seeds = [np.mean([[q.x, q.y] for q in g], axis=0) for g in groups]
    # The row runs along a wall of the block: of the walls that point about the way the next address lies, the longest.
    ring = np.array(poly.exterior.coords)
    edges = ring[1:] - ring[:-1]
    lengths, angles = np.hypot(edges[:, 0], edges[:, 1]), np.arctan2(edges[:, 1], edges[:, 0])

    def along_wall(a):
        off = np.abs((angles - a + np.pi / 2) % np.pi - np.pi / 2)
        ok = off < np.radians(30)
        return float(angles[np.argmax(np.where(ok, lengths, -1))]) if ok.any() else a

    cells = voronoi_diagram(MultiPoint(seeds), envelope=poly.envelope.buffer(60))
    out = []
    for cell in cells.geoms:
        k = next((i for i, sd in enumerate(seeds) if cell.contains(Point(sd))), None)
        if k is None:
            continue
        piece = poly.intersection(cell).buffer(0)
        others = [o for i, o in enumerate(seeds) if i != k]
        nearest = min(others, key=lambda o: np.hypot(*(o - seeds[k])))
        d = nearest - seeds[k]
        for q in getattr(piece, "geoms", [piece]):
            if q.geom_type == "Polygon" and q.area > 4:
                out.append((Polygon(q.exterior), along_wall(float(np.arctan2(d[1], d[0])))))
    # A sliver left over at a corner goes to the house it shares the longest wall with.
    big = [o for o in out if o[0].area >= 16]
    for q, _ in [o for o in out if o[0].area < 16]:
        if not big:
            break
        k = max(range(len(big)), key=lambda i: big[i][0].buffer(0.05).intersection(q.buffer(0.05)).area)
        merged = big[k][0].union(q.buffer(0.02)).buffer(0)
        if merged.geom_type == "Polygon":
            big[k] = (Polygon(merged.exterior), big[k][1])
    return (big or [(poly, None)]), count


def lean(surfaces, m, base):
    """A building on a slope that is no terrace: tilt it with the ground, so the uphill end does not sink into the
    hill and the downhill end does not stand on stilts. The walls stay upright; eaves and ridge follow the slope."""
    (tx, ty), (cx, cy) = m["tilt"], m["center"]
    # Only so far: a large building on a steep site has a level floor cut into the hill. At most 8 m from end to end.
    k = min(1.0, 8.0 / max(np.hypot(tx, ty) * m.get("long", 10.0), 1e-6))
    tx, ty = tx * k, ty * k
    out = []
    for kind, rings in surfaces:
        new = []
        for r in rings:
            r = np.array(r, dtype=np.float64)
            up = r[:, 2] > base + 0.01
            r[up, 2] += tx * (r[up, 0] - cx) + ty * (r[up, 1] - cy)
            new.append(r)
        out.append((kind, new))
    return out


def open_ring(ring):
    r = np.asarray(ring.coords if hasattr(ring, "coords") else ring, dtype=np.float64)[:, :2]
    return r[:-1] if np.allclose(r[0], r[-1]) else r


def flat_roof(poly, base, top):
    return extrude([open_ring(poly.exterior), *[open_ring(h) for h in poly.interiors]], base, top)


def gabled(poly, base, eave, ridge, axis):
    """Walls and two roof planes for a simple outline: the ridge runs through the middle along `axis`, the walls
    under it rise to a gable. Returns None when the outline does not split cleanly in two."""
    ring = ccw(open_ring(poly.exterior))
    c = np.array(poly.minimum_rotated_rectangle.centroid.coords[0])
    d = np.array([np.cos(axis), np.sin(axis)])
    nrm = np.array([-d[1], d[0]])
    across = (ring - c) @ nrm
    hw = float(np.abs(across).max())
    if hw < 1.0:
        return None
    reach = float(np.abs((ring - c) @ d).max()) + 5
    halves = split(Polygon(ring), LineString([c - d * reach, c + d * reach]))
    parts = [g for g in halves.geoms if g.geom_type == "Polygon" and g.area > 0.5]
    if len(parts) < 2:
        return None
    height = lambda pts: eave + (ridge - eave) * (1 - np.clip(np.abs((pts - c) @ nrm) / hw, 0, 1))
    out = []
    for g in parts:
        r = ccw(open_ring(g.exterior))
        z = height(r)
        out.append((2, [np.column_stack([r, z])]))
        for (a, za), (b, zb) in zip(zip(r, z), zip(np.roll(r, -1, axis=0), np.roll(z, -1))):
            on_ridge = abs((a - c) @ nrm) < 1e-6 and abs((b - c) @ nrm) < 1e-6
            if on_ridge or np.linalg.norm(b - a) < 0.05:
                continue
            out.append((1, [np.array([[a[0], a[1], base], [b[0], b[1], base], [b[0], b[1], zb], [a[0], a[1], za]])]))
    return out


def hipped(poly, base, eave, ridge, pitch=None):
    """Walls to the eaves, then the roof rises inward from every side: right for an L, a T or a courtyard block,
    where no single ridge fits. The roof is built in bands, like contour lines: the outline shrunk a metre or so at a
    time, each band a little higher than the last. A narrow wing runs out of bands early and gets a lower ridge of
    its own; the widest part goes on up to a level top."""
    outer = Polygon(ccw(open_ring(poly.exterior)))
    lo, hi = 0.0, 12.0
    for _ in range(12):  # how far in the outline can shrink before nothing is left
        mid = (lo + hi) / 2
        if outer.buffer(-mid, join_style="mitre").is_empty:
            hi = mid
        else:
            lo = mid
    if lo < 1.0:
        return None
    if pitch:
        ridge = min(ridge, eave + 0.72 * lo * pitch)
    parts = lambda g: [q for q in getattr(g, "geoms", [g]) if q.geom_type == "Polygon" and q.area > 0.3]
    lift = lambda r, z: np.column_stack([r, np.full(len(r), z)])
    out = [s for s in extrude([open_ring(outer.exterior)], base, eave) if s[0] == 1]
    n = max(2, int(np.ceil(0.72 * lo / 1.2)))
    prev, z_prev = [outer], eave
    for k in range(1, n + 1):
        z = eave + (ridge - eave) * k / n
        cur = parts(outer.buffer(-0.72 * lo * k / n, join_style="mitre").simplify(0.1))
        for a in prev:
            inside = [c for c in cur if a.contains(c.representative_point())]
            out.append((2, [lift(ccw(open_ring(a.exterior)), z_prev), *[lift(ccw(open_ring(c.exterior))[::-1], z) for c in inside]]))
        prev, z_prev = cur, z
        if not cur:
            break
    for a in prev:
        out.append((2, [lift(ccw(open_ring(a.exterior)), z_prev)]))
    return out


def emit_lidar(verts, res, pieces, floor):
    """The triangles of a lidar roof (scripts/roofs.py) into the vertex list. Each roof cell and wall goes to the
    house of the block it is nearest to, so every house keeps its own wall colour."""
    import shapely

    roof, roof_at, walls, wall_u, wall_at, _ = res
    tree = STRtree([q for _, q in pieces])
    ids = np.array([bi for bi, _ in pieces])
    owner = lambda at: ids[tree.nearest(shapely.points(at))]

    def rows(tris, uv, kind, bi):
        n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        if kind == 2:
            n[n[:, 2] < 0] *= -1
        local = np.stack([tris[..., 0] - CX, tris[..., 2], CY - tris[..., 1]], -1)
        normal = np.repeat(np.stack([n[:, 0], n[:, 2], -n[:, 1]], -1)[:, None, :], 3, axis=1)
        tail = np.concatenate([np.full(local.shape[:2] + (1,), kind), np.repeat(bi[:, None, None].astype(float), 3, axis=1), np.full(local.shape[:2] + (2,), -1.0)], -1)
        verts.append(np.concatenate([local, normal, uv, tail], -1).reshape(-1, COLS))

    rows(roof, roof[..., :2] - [CX, CY], 2, owner(roof_at))
    if len(walls):
        uv = np.stack([wall_u, walls[..., 2] - floor], -1)  # along the wall, and height above the floor
        bi = owner(wall_at)
        for a in ([0, 1, 2], [0, 2, 3]):
            rows(walls[:, a], uv[:, a], 1, bi)


def farmyards():
    """Farmyards and works in OpenStreetMap: a large building there is a barn or a shed, anywhere else it is a row of
    houses, a shop, a school or a hall."""
    from shapely.ops import unary_union

    from geo import wgs_to_grid

    path = RAW / "osm_land.json"
    polys = []
    for el in json.loads(path.read_text())["elements"] if path.exists() else []:
        if el.get("tags", {}).get("landuse") in ("farmyard", "industrial") and len(el.get("geometry", [])) >= 4:
            q = Polygon([wgs_to_grid(g["lat"], g["lon"]) for g in el["geometry"]]).buffer(0)
            if not q.is_empty:
                polys.append(q.buffer(12))
    return unary_union(polys) if polys else Polygon()


def standard(m, poly, exempt, along=None):
    """Height of the eaves and rise of the roof (metres above the floor) for an ordinary building: storeys from the
    lidar, the roof at one pitch."""
    ridge = float(np.clip(m["ridge"], 2.4, 40.0))
    half = 0.5 * m.get("short", 8.0)
    if along is not None:
        # A house in a row: the roof spans the house from front to back, across the row.
        ring = np.array(poly.exterior.coords)
        across = ring @ np.array([-np.sin(along), np.cos(along)])
        half = 0.5 * float(across.max() - across.min())
    pitched = m["rise"] >= 0.7 or (m["cells"] < 30 and poly.area > 30 and ridge > 3.6)
    rise = min(half * PITCH, MAX_RISE) if pitched else 0.0
    if exempt:
        measured = min(m["rise"], ridge - 2.0, half * 0.85, 5.0)
        return ridge - measured, measured
    eave = ridge - rise
    storeys = 0 if eave < 3.9 else 1 if eave < 6.6 else 2
    if ridge < 3.3:
        return max(2.2, ridge), 0.0  # a garage, a shed, a lean-to
    return EAVES[storeys], rise


def main():
    write_area()
    farm = farmyards()
    dtm, dsm = np.load(BUILD / "dtm.npy"), np.load(BUILD / "dsm.npy")
    sea = np.load(BUILD / "sea.npy")
    landmarks = json.loads((BUILD / "landmarks.json").read_text()) if (BUILD / "landmarks.json").exists() else {}
    named = landmarks.get("buildings", {})
    verts, meta, footprints = [], [], []
    shapes = Counter()
    outlines = []
    tree, pts = load_addresses()
    for pid, poly, tags in load_outlines():
        if pid in named:
            outlines.append((pid, poly, tags))
            continue
        row, count = houses(poly, tree, pts)
        shapes["rows cut into houses"] += len(row) > 1
        for k, (q, along) in enumerate(row):
            more = {"block": pid, "addresses": count if len(row) == 1 else 1}
            if along is not None:
                more["ridge"] = along
            # Without address points (or with one address), a long outline on a slope is still cut into steps.
            pieces = steps(q, dtm) if len(row) == 1 else [q]
            outlines += [(f"{pid}-{k}-{j}" if (k or j) else pid, piece, {**tags, **more}) for j, piece in enumerate(pieces)]
    # The real roof from the lidar for every ordinary block: scripts/roofs.py. Landmarks and churches keep the roof
    # built for them, and where the lidar shows nothing (a house newer than the survey) a standard roof stands in.
    lidar = {}
    for pid, poly, tags in load_outlines():
        if pid in named or tags.get("building") in ("church", "chapel") or tags.get("amenity") == "place_of_worship":
            continue
        bm = measure(poly, dtm, dsm)
        if bm is None or bm["ridge"] < 1.5:
            continue
        res = lidar_roof(poly, dtm, dsm, bm["floor"], max_height=14.0)
        if res is not None:
            lidar[pid] = {"res": res, "floor": bm["floor"], "pieces": []}
    shapes["roofs from the lidar"] = len(lidar)
    for pid, poly, tags in outlines:
        m = measure(poly, dtm, dsm)
        if m is None or sea[int(np.clip((YMAX - poly.centroid.y) / LIDAR_RES, 0, sea.shape[0] - 1)), int(np.clip((poly.centroid.x - XMIN) / LIDAR_RES, 0, sea.shape[1] - 1))]:
            continue
        lm = named.get(pid)
        ring = open_ring(poly.exterior)
        floor, base = m["floor"], max(m["low"] - 0.4, m["floor"] - 7.0)
        if m["ridge"] < 1.5:
            # Nothing stands here in the lidar: demolished, not yet built when the survey flew, or a roofless ruin.
            if not lm and not tags.get("name"):
                continue
            m["ridge"], m["rise"] = 3.0, 0.0
        church = tags.get("building") in ("church", "chapel") or tags.get("amenity") == "place_of_worship"
        on_farm = farm.intersects(poly.centroid)
        # A tree that hangs over a roof reads as a roof 15 m high, and no two houses measure alike: see EAVES.
        eave, rise = standard(m, poly, exempt=bool(church or lm or (on_farm and poly.area > 260)), along=tags.get("ridge"))
        height = eave + rise
        kind = "house"
        if poly.area > 260 and on_farm and height < 9.5:
            kind = "barn"
        elif poly.area < 22 or height < 3.3 or (tags.get("addresses") == 0 and poly.area < 60 and not tags.get("building") in ("house", "residential", "detached", "terrace")):
            # Small, low, or nobody's address: a garage, a garden shed, a store.
            kind = "shed" if on_farm else "outbuilding"
        if church:
            kind = "church"
        if lm:
            kind = lm["style"]
        if lm and lm.get("height"):
            height, rise = lm["height"], min(rise, lm["height"] - 2.0)
        if lm and lm.get("roofless"):
            rise = 0.0
        bi = len(meta)
        surfaces = None
        real = lidar.get(tags.get("block"))
        if real is not None:
            real["pieces"].append((bi, poly))
            surfaces, shape_name = [], "lidar"
        simple = m.get("fill", 0) > 0.78 and not poly.interiors
        if surfaces is None and rise >= 0.7 and simple:
            # The lidar says which way the ridge runs when it can; otherwise along the long side, as most do.
            ridge_axis = tags["ridge"] if "ridge" in tags else m["axis"] if m["axis"] is not None else long_side(poly)
            surfaces = gabled(poly, base, floor + height - rise, floor + height, ridge_axis)
            shape_name = "gabled"
        if surfaces is None and rise >= 0.7:
            surfaces = hipped(poly, base, floor + height - rise, floor + height, None if (church or lm) else PITCH)
            shape_name = "hipped"
        if surfaces is None:
            surfaces = flat_roof(poly, base, floor + height)
            shape_name = "flat"
        if m["drop"] > 1.5 and real is None:
            surfaces = lean(surfaces, m, base)
            shapes["on a slope"] += 1
        shapes[shape_name] += 1
        roof_tris = emit(verts, surfaces, bi, floor)
        footprints.append([[round(x - CX, 2), round(CY - y, 2)] for x, y in ring])
        rand = stable_rand(pid)
        meta.append({
            "id": pid,
            "kind": kind,
            "axis": round(m["axis"] if m["axis"] is not None else long_axis(ring), 4),
            "glass": False,
            "year": None,
            "roof": shape_name,
            "area": round(poly.area, 1),
            "height": round(height, 2),
            "ground": round(floor, 2),
            "roof_rgb": None,
            # One roof colour for a whole row: the houses of a terrace were roofed together.
            "roof_fixed": list(pick(ROOFS_BARN if kind in ("barn", "shed") else ROOFS_HOUSE, stable_rand(tags.get("block", pid), "roof"))),
            "rand": round(rand, 4),
        })
        if kind in ("house", "outbuilding"):
            # The eaves: no window is drawn above them.
            meta[-1]["param"] = round(height - rise if real is None else max(2.4, real["res"][5] - (floor - real["floor"])), 2)
        if lm:
            meta[-1].update({"name": lm["name"], "wall_fixed": lm.get("wall"), "frame_fixed": lm.get("frame")})
            if lm.get("roof"):
                meta[-1]["roof_fixed"] = lm["roof"]
            add_landmark_parts(verts, meta, pid, lm, floor, meta[-1]["axis"], roof_tris)
    for real in lidar.values():
        if real["pieces"]:
            emit_lidar(verts, real["res"], real["pieces"], real["floor"])
    # Structures with no outline on any map (a lone mine stack): built from scripts/landmarks.py alone.
    for extra in landmarks.get("structures", []):
        g = ground_at(dtm, extra["x"], extra["y"])
        add_landmark_parts(verts, meta, extra["id"], {**extra, "ground": g}, g, 0.0, [])
    add_masts(verts, meta, landmarks.get("masts", []), dtm)
    arr = np.concatenate(verts).astype(np.float32)
    arr.tofile(BUILD / "buildings.bin")
    (BUILD / "buildings.json").write_text(json.dumps(meta))
    (BUILD / "footprints.json").write_text(json.dumps(footprints))
    Image.new("RGB", (4, 4), (88, 90, 96)).save(BUILD / "roof_atlas.png")
    print(f"{len(meta)} buildings, {len(arr) // 3} triangles, {dict(Counter(m['kind'] for m in meta))}, roofs {dict(shapes)}")


if __name__ == "__main__":
    main()
