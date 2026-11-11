# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "pillow", "shapely"]
# ///
"""Paint the ground: land use from OpenStreetMap and OS OpenMap Local, the coast and the cliffs from the lidar
terrain, in a pixel-art palette with baked sun shading and shadows.

There is no open aerial photo of St Agnes to take colours from, so every colour here comes from what a surface is:
pasture, heath, sand, slate cliff, sea. The lidar adds what the maps leave out: where the land is so steep that it
is bare rock, where gorse and hedges stand (a metre or two of canopy), where the tide line runs.

Output, in 2000x2000 px chunks of 500 m (0.25 m/px), row 0 north:
  data/build/ground/{ix}_{iy}.png   the ground, with the roads filled in by the surfaces around them
  data/build/roads/{ix}_{iy}.png    RGBA: the roads' own colours running on past their edges, alpha where a road is
"""

import hashlib
import json
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from config import BUILD, CHUNK, CX, CY, GROUND_RES, LIDAR_RES, NX as CHUNKS_X, NY as CHUNKS_Y, RAW, SEA_LEVEL, XMAX, XMIN, YMAX, YMIN
from geo import wgs_to_grid
from sun import SUN_AZIMUTH, SUN_ELEVATION

NX, NY = int((XMAX - XMIN) / GROUND_RES), int((YMAX - YMIN) / GROUND_RES)
UP = int(LIDAR_RES / GROUND_RES)  # ground pixels per lidar cell
HIGH_WATER = 3.2  # mean high water springs on this coast, metres above Ordnance Datum: below it is beach or wet rock

# Style categories. Order matters only for readability.
STYLES = {
    "pasture": (118, 164, 72),
    "grass": (116, 160, 70),
    "meadow": (128, 168, 78),
    "rough": (136, 152, 84),
    "shrub": (84, 122, 56),
    "forest": (68, 98, 50),
    "field": (150, 118, 82),
    "orchard": (118, 152, 72),
    "heath": (128, 112, 88),
    "marsh": (104, 132, 92),
    "water": (70, 128, 172),
    "sea": (40, 128, 168),
    "yard": (150, 158, 110),
    "farmyard": (164, 156, 138),
    "sand": (226, 206, 160),
    "rock": (132, 120, 106),
    "spoil": (176, 140, 104),
    "asphalt": (98, 100, 106),
    "concrete_pavers": (160, 156, 148),
    "concrete": (178, 175, 164),
    "gravel": (176, 164, 138),
    "dirt": (178, 156, 114),
    "building": (168, 162, 150),
}
CAT = {k: i for i, k in enumerate(STYLES)}
SOFT = {CAT[k] for k in ("pasture", "grass", "meadow", "rough", "shrub", "forest", "field", "orchard", "heath", "marsh", "yard", "farmyard", "dirt", "sand", "spoil")}
FIELDS = {CAT[k] for k in ("pasture", "meadow", "field", "rough")}

LANDUSE = {
    "farmland": "pasture", "meadow": "meadow", "grass": "grass", "village_green": "grass", "recreation_ground": "grass",
    "residential": "yard", "farmyard": "farmyard", "industrial": "concrete", "commercial": "concrete", "retail": "concrete",
    "quarry": "spoil", "brownfield": "spoil", "landfill": "spoil", "forest": "forest", "orchard": "orchard",
    "allotments": "orchard", "construction": "dirt", "cemetery": "grass", "religious": "grass", "plant_nursery": "orchard",
    "greenfield": "rough", "military": "rough", "flowerbed": "shrub",
}
NATURAL = {
    "heath": "heath", "scrub": "shrub", "wood": "forest", "grassland": "rough", "fell": "rough", "beach": "sand", "sand": "sand",
    "bare_rock": "rock", "scree": "rock", "shingle": "rock", "rock": "rock", "water": "water", "wetland": "marsh",
}
LEISURE = {"park": "grass", "garden": "grass", "playground": "grass", "pitch": "grass", "golf_course": "grass", "common": "rough",
           "nature_reserve": None, "sports_centre": "grass"}

# Roads are lines in OpenStreetMap: (half width in metres, surface) per kind of way.
ROADS = {
    "trunk": (3.6, "asphalt"), "primary": (3.5, "asphalt"), "secondary": (3.2, "asphalt"), "tertiary": (2.9, "asphalt"),
    "unclassified": (2.3, "asphalt"), "residential": (2.6, "asphalt"), "living_street": (2.3, "asphalt"),
    "service": (1.6, "asphalt"), "pedestrian": (2.0, "concrete_pavers"), "track": (1.4, "dirt"), "cycleway": (1.1, "asphalt"),
    "footway": (0.7, "dirt"), "path": (0.6, "dirt"), "bridleway": (0.8, "dirt"), "steps": (0.7, "concrete"),
}
PAVED = {"asphalt", "paved", "concrete", "paving_stones", "sett", "cobblestone", "concrete:plates", "tarmac"}
LOOSE = {"gravel", "fine_gravel", "compacted", "pebblestone"}
ROAD_STYLES = {"asphalt", "concrete_pavers", "concrete", "gravel", "dirt"}


def style_for(t):
    """The surface an OpenStreetMap area stands for, or None when it says nothing about the ground."""
    if t.get("amenity") == "parking":
        return "gravel" if t.get("surface") in LOOSE | {"unpaved", "ground", "dirt", "grass"} else "asphalt"
    if t.get("natural") in NATURAL:
        return NATURAL[t["natural"]]
    if t.get("landuse") in LANDUSE:
        if t["landuse"] == "farmland" and t.get("crop") not in (None, "grass"):
            return "field"
        return LANDUSE[t["landuse"]]
    if t.get("leisure") in LEISURE:
        return LEISURE[t["leisure"]]
    if t.get("tourism") in ("camp_site", "caravan_site"):
        return "grass"
    if t.get("amenity") in ("school", "grave_yard"):
        return "grass" if t["amenity"] == "grave_yard" else "yard"
    return None


def osm_polygons(el):
    """Shapely polygons in grid metres for an OpenStreetMap way or multipolygon relation (from `out geom`)."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union

    line = lambda g: [wgs_to_grid(p["lat"], p["lon"]) for p in g]
    if el["type"] == "way":
        g = el.get("geometry") or []
        if len(g) >= 4 and g[0] == g[-1]:
            return [Polygon(line(g)).buffer(0)]
        return []
    if el["type"] == "relation":
        outer = [LineString(line(m["geometry"])) for m in el.get("members", []) if m.get("type") == "way" and m.get("role") != "inner" and len(m.get("geometry") or []) >= 2]
        inner = [LineString(line(m["geometry"])) for m in el.get("members", []) if m.get("type") == "way" and m.get("role") == "inner" and len(m.get("geometry") or []) >= 2]
        shape = unary_union(list(polygonize(unary_union(outer)))) if outer else None
        if shape is None or shape.is_empty:
            return []
        holes = list(polygonize(unary_union(inner))) if inner else []
        if holes:
            shape = shape.difference(unary_union(holes))
        return [shape.buffer(0)]
    return []


def load_polygons():
    """[(priority, -area, style, key, is road, polygon)]: land first (large areas under small ones), then roads, then
    the ground under buildings."""
    from shapely.geometry import LineString, Polygon, box, shape
    from shapely.ops import unary_union

    extent = box(XMIN - 30, YMIN - 30, XMAX + 30, YMAX + 30)
    polys = []

    def add(prio, style, key, road, geom):
        geom = geom.intersection(extent)
        for part in getattr(geom, "geoms", [geom]):
            if part.geom_type == "Polygon" and part.area > 1:
                # Ordered by the area inside the outline, holes included: what lies in a hole is smaller, so it comes later.
                polys.append((prio, -Polygon(part.exterior).area, style, key, road, part))

    for el in json.loads((RAW / "osm_land.json").read_text())["elements"]:
        t = el.get("tags", {})
        style = style_for(t)
        if style is None:
            continue
        for g in osm_polygons(el):
            add(0, style, f"{el['type']}{el['id']}", style in ("asphalt", "gravel") and t.get("amenity") == "parking", g)

    # OS OpenMap Local fills in what OpenStreetMap leaves blank: woods, ponds and streams, the foreshore.
    for name, style in (("woodland", "forest"), ("surfacewater_area", "water"), ("foreshore", "sand")):
        path = RAW / f"os_{name}.geojson"
        if path.exists():
            for i, f in enumerate(json.loads(path.read_text())["features"]):
                add(-1, style, f"os{name}{i}", False, shape(f["geometry"]).buffer(0))

    lines = {}
    for el in json.loads((RAW / "osm_roads.json").read_text())["elements"]:
        t = el.get("tags", {})
        hw = t.get("highway", "").removesuffix("_link")
        if el["type"] != "way" or hw not in ROADS or t.get("area") == "yes" or t.get("tunnel") == "yes":
            continue
        half, style = ROADS[hw]
        surface = t.get("surface")
        if surface in PAVED:
            style = "asphalt" if hw not in ("footway", "path", "steps", "pedestrian") else "concrete_pavers"
        elif surface in LOOSE:
            style = "gravel"
        elif surface in ("unpaved", "ground", "dirt", "earth", "grass", "sand", "mud", "rock"):
            style = "dirt"
        elif hw == "footway" and t.get("footway") in ("sidewalk", "crossing"):
            style = "concrete_pavers"
        if t.get("service") in ("driveway", "parking_aisle"):
            half = 1.3
        if t.get("width"):
            try:
                half = min(6.0, max(0.5, float(t["width"].split()[0]) / 2))
            except ValueError:
                pass
        pts = [wgs_to_grid(p["lat"], p["lon"]) for p in el["geometry"]]
        if len(pts) >= 2:
            lines.setdefault((style, half), []).append(LineString(pts))
    # One merged shape per surface and width, so a road is one polygon where OpenStreetMap cuts it into stretches.
    for (style, half), group in sorted(lines.items(), key=lambda kv: -kv[0][1]):
        prio = 1 if style in ("dirt", "gravel") else 2  # paved roads over tracks and paths
        add(prio, style, f"road-{style}-{half}", True, unary_union(group).buffer(half, cap_style="round", join_style="round", resolution=4))

    for i, ring in enumerate(json.load(open(BUILD / "footprints.json"))):
        add(3, "building", f"b{i}", False, Polygon([(x + CX, CY - z) for x, z in ring]).buffer(0))
    polys.sort(key=lambda t: (t[0], t[1]))
    return polys


def to_px(ring):
    a = np.asarray(ring.coords)[:, :2]
    return list(zip(((a[:, 0] - XMIN) / GROUND_RES).tolist(), ((YMAX - a[:, 1]) / GROUND_RES).tolist()))


def upsample(a, smooth=True):
    """A lidar-resolution raster brought to the ground raster. Smooth for heights and shading; masks are cut at one
    half afterwards, so a coastline drawn at 1 m gets an edge at 25 cm instead of steps."""
    img = Image.fromarray(a.astype(np.float32), mode="F")
    return np.asarray(img.resize((NX, NY), Image.BILINEAR if smooth else Image.NEAREST))


def value_noise(shape, cell, seed, octaves=1):
    """Smooth noise in [0,1] with features of about `cell` pixels, tileable over the whole raster."""
    rng = np.random.default_rng(seed)
    out = np.zeros(shape, np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        c = max(1, int(cell / (2**o)))
        g = rng.random((shape[0] // c + 2, shape[1] // c + 2)).astype(np.float32)
        z = ndi.zoom(g, c, order=1)[: shape[0], : shape[1]]
        out += amp * z
        total += amp
        amp *= 0.5
    return out / total


def main():
    polys = load_polygons()
    print(f"{len(polys)} polygons")

    # Every polygon is drawn on its own small canvas and laid over what is there, so a hole in it (a field ringed
    # by a wood, the heath of the Beacon inside the farmland around it) leaves what lies under the hole alone.
    ids = np.zeros((NY, NX), np.int32)
    for i, (*_, shape) in enumerate(polys, start=1):
        x0, y0, x1, y1 = shape.bounds
        c0, c1 = max(int((x0 - XMIN) / GROUND_RES) - 1, 0), min(int((x1 - XMIN) / GROUND_RES) + 2, NX)
        r0, r1 = max(int((YMAX - y1) / GROUND_RES) - 1, 0), min(int((YMAX - y0) / GROUND_RES) + 2, NY)
        if c1 <= c0 or r1 <= r0:
            continue
        mask = Image.new("L", (c1 - c0, r1 - r0), 0)
        d = ImageDraw.Draw(mask)
        d.polygon([(x - c0, y - r0) for x, y in to_px(shape.exterior)], fill=1)
        for hole in shape.interiors:
            d.polygon([(x - c0, y - r0) for x, y in to_px(hole)], fill=0)
        ids[r0:r1, c0:c1][np.asarray(mask) > 0] = i

    cats = np.zeros(len(polys) + 1, np.uint8)
    roads = np.zeros(len(polys) + 1, bool)
    base = np.zeros((len(polys) + 1, 3), np.float32)
    stripes_dir = np.zeros(len(polys) + 1, np.float32)
    for i, (_, _, s, key, road, shape) in enumerate(polys, start=1):
        # Seeded per polygon, so a field keeps its crop when the map area changes.
        rng = np.random.default_rng(int(hashlib.md5(str(key).encode()).hexdigest()[:8], 16))
        c = np.array(STYLES[s], np.float32)
        if s == "pasture":
            # Most farmland here is grazing; one field in five is under the plough or cut for silage.
            choice = rng.random()
            if choice < 0.72:
                c = c * (0.92 + 0.16 * rng.random())
            elif choice < 0.84:
                s, c = "field", np.array((152, 116, 80), np.float32) * (0.9 + 0.2 * rng.random())
            elif choice < 0.93:
                s, c = "field", np.array((206, 184, 108), np.float32)
            else:
                s, c = "meadow", np.array((150, 176, 84), np.float32)
        elif s in ("meadow", "grass", "rough"):
            c = c * (0.94 + 0.12 * rng.random())
        cats[i] = CAT[s]
        roads[i] = road
        base[i] = c
        ext = np.asarray(shape.exterior.coords)[:, :2]
        ext = ext - ext.mean(0)
        _, v = np.linalg.eigh(ext.T @ ext)
        stripes_dir[i] = math.atan2(v[1, -1], v[0, -1])
    cats[0] = CAT["pasture"]
    base[0] = STYLES["pasture"]

    cat = cats[ids]
    img = base[ids]  # (NY, NX, 3) float32
    road = roads[ids]

    # What the lidar knows. The sea; the foreshore below high water; rock wherever the land is too steep to hold soil.
    dtm_lo = np.load(BUILD / "dtm.npy")
    sea_lo = np.load(BUILD / "sea.npy")
    gy, gx = np.gradient(ndi.gaussian_filter(dtm_lo, 1.0), LIDAR_RES)
    slope_lo = np.degrees(np.arctan(np.hypot(gx, gy)))
    shore_lo = ndi.distance_transform_edt(~sea_lo) * LIDAR_RES  # metres inland from the water
    depth_lo = ndi.distance_transform_edt(sea_lo) * LIDAR_RES  # metres out from the shore
    dtm = upsample(dtm_lo)
    sea = upsample(sea_lo) > 0.5
    slope = upsample(slope_lo)
    n1 = value_noise((NY, NX), 20, 1, octaves=2)
    n2 = value_noise((NY, NX), 40, 2, octaves=2)
    built = (cat == CAT["building"]) | road
    foreshore = ~sea & (dtm < HIGH_WATER) & (upsample(shore_lo) < 260) & ~built
    cliff = ~sea & ~built & ((slope > 37 + 6 * (n1 - 0.5)) | (foreshore & (slope > 11)))
    beach = foreshore & ~cliff
    cat[sea] = CAT["sea"]
    cat[beach] = CAT["sand"]
    cat[cliff] = CAT["rock"]
    road &= ~sea
    img[beach] = STYLES["sand"]
    img[cliff] = STYLES["rock"]
    del foreshore, built

    # The outer metre of a road stays clean of texture, so its edge reads as a line.
    road_rim = road & ~ndi.binary_erosion(road, iterations=2)

    yy, xx = np.ogrid[0:NY, 0:NX]
    yy, xx = yy.astype(np.float32), xx.astype(np.float32)
    # Field furrows along the long axis of each parcel.
    ang = stripes_dir[ids]
    field = cat == CAT["field"]
    along = xx * np.sin(ang) + yy * np.cos(ang)
    furrow = (np.sin(along * (2 * np.pi / 7.0)) > 0.3).astype(np.float32)
    img[field] *= (0.96 + 0.05 * furrow[field])[:, None]
    del along, furrow, ang, field

    # Orchards and allotments: rows of small dark shrubs.
    orch = cat == CAT["orchard"]
    rows = ((xx.astype(np.int32) // 6) % 3 == 0) & ((yy.astype(np.int32) // 6) % 2 == 0)
    img[orch & rows] *= 0.72
    del rows, orch

    soft = np.isin(cat, list(SOFT))
    img[soft] *= (0.96 + 0.08 * n1[soft])[:, None]
    grassy = np.isin(cat, [CAT[k] for k in ("pasture", "grass", "meadow", "rough", "orchard")])
    img[grassy] *= (0.95 + 0.1 * n2[grassy])[:, None]
    shrub = np.isin(cat, [CAT["shrub"], CAT["forest"], CAT["marsh"]])
    img[shrub & (n1 > 0.62)] *= 0.9
    img[shrub & (n1 < 0.3)] *= 1.05
    del grassy, shrub

    # Heath: heather and western gorse, the cover of the Beacon and the cliff tops. Purple-brown heather, straw-
    # coloured moor grass, and gorse in flower as scattered yellow.
    heath = cat == CAT["heath"]
    purple = np.array((134, 98, 122), np.float32)
    straw = np.array((166, 150, 100), np.float32)
    gorse = np.array((214, 186, 60), np.float32)
    m = heath & (n2 > 0.56)
    img[m] = img[m] * 0.45 + purple * 0.55
    m = heath & (n1 < 0.36)
    img[m] = img[m] * 0.55 + straw * 0.45
    speck = value_noise((NY, NX), 3, 5) > 0.8
    m = heath & speck & (n1 > 0.52) & (n2 < 0.5)
    img[m] = gorse
    # The same gorse, thinner, on rough coastal grass.
    m = (cat == CAT["rough"]) & speck & (n2 > 0.66)
    img[m] = img[m] * 0.4 + gorse * 0.6
    del heath, m

    # Gardens: lawn with paths and patios. Without a photo to say which is which, a noise decides: mostly lawn,
    # paving in patches, beds along the edges.
    yard = cat == CAT["yard"]
    patch = value_noise((NY, NX), 14, 9, octaves=2)
    lawn = np.array((112, 156, 68), np.float32)
    paving = np.array((176, 170, 156), np.float32)
    bed = np.array((92, 124, 60), np.float32)
    m = yard & (patch > 0.68)
    img[m] = paving * (0.97 + 0.05 * n1[m])[:, None]
    m = yard & (patch < 0.3)
    img[m] = bed * (0.94 + 0.1 * n1[m])[:, None]
    m = yard & (patch >= 0.3) & (patch <= 0.68)
    img[m] = lawn * (0.95 + 0.09 * n1[m])[:, None]
    del yard, patch, m

    # Mine waste: the burrows of Wheal Kitty, Wheal Coates and Blue Hills. Bare ochre and rust, with grey slate.
    spoil = cat == CAT["spoil"]
    m = spoil & (n2 > 0.58)
    img[m] = img[m] * 0.4 + np.array((168, 104, 78), np.float32) * 0.6
    m = spoil & (n1 < 0.34)
    img[m] = img[m] * 0.4 + np.array((148, 142, 134), np.float32) * 0.6
    del spoil

    # Hedges and scrub from the lidar: a metre or two of canopy on open land is a Cornish hedge, gorse or bramble.
    chm = upsample(np.load(BUILD / "chm.npy").astype(np.float32))
    open_land = np.isin(cat, [CAT[k] for k in ("pasture", "grass", "meadow", "rough", "field", "heath", "spoil", "farmyard", "yard")])
    low = open_land & (chm > 0.7) & (chm < 3.0)
    img[low] = np.array((78, 116, 54), np.float32) * (0.9 + 0.2 * n1[low])[:, None]
    under = open_land & (chm >= 3.0)
    img[under] = np.array((72, 104, 52), np.float32)
    del chm, low, under

    # And a hedge on every boundary between two fields, where the lidar shows none: the bank is there all the same.
    fieldish = np.isin(cat, list(FIELDS))
    edge = fieldish & ((ids != np.roll(ids, 1, 0)) | (ids != np.roll(ids, 1, 1)))
    edge = ndi.binary_dilation(edge, iterations=3) & fieldish
    img[edge] = np.array((86, 122, 58), np.float32) * (0.9 + 0.2 * n1[edge])[:, None]
    del edge, fieldish, open_land

    # Pavement patterns and a little grain on the tarmac.
    pav = (cat == CAT["concrete_pavers"]) & ~road
    grid = (xx.astype(np.int32) % 4 == 0) | (yy.astype(np.int32) % 4 == 0)
    img[pav & grid] *= 0.97
    asph = cat == CAT["asphalt"]
    img[asph] *= (0.985 + 0.03 * n1[asph])[:, None]
    del pav, grid, asph

    # Fresh water: ripples.
    water = cat == CAT["water"]
    ripple = (np.sin((xx * 0.7 + yy * 0.7) * 0.9 + n2 * 20) > 0.93) & (n1 > 0.55)
    img[water & ripple] = img[water & ripple] * 0.5 + np.array((140, 186, 214), np.float32) * 0.5
    del ripple, water

    # Sand: wet and darker near the water, dry and pale above; ripple marks low down.
    shore = upsample(shore_lo)
    wet = beach & (shore < 14 + 10 * n2)
    img[wet] = np.array((198, 180, 140), np.float32) * (0.97 + 0.06 * n1[wet])[:, None]
    img[beach & ~wet] *= (0.97 + 0.06 * n1[beach & ~wet])[:, None]
    del wet

    # Rock: beds of killas. The strata show as darker lines along the contours; lichen and thrift soften the tops,
    # rust stains run where the mine adits drain.
    step = np.mod(dtm + 2.5 * n2, 2.4)
    rock = cat == CAT["rock"]
    img[rock] *= (0.9 + 0.2 * n1[rock])[:, None]
    img[rock & (step < 0.5)] *= 0.78
    m = rock & (n2 > 0.64)
    img[m] = img[m] * 0.6 + np.array((150, 104, 80), np.float32) * 0.4
    m = rock & (slope < 30) & (n1 > 0.5) & (dtm > HIGH_WATER + 2)
    img[m] = img[m] * 0.5 + np.array((120, 140, 84), np.float32) * 0.5
    # Wet rock below high water is darker, with weed.
    m = rock & (dtm < HIGH_WATER)
    img[m] *= 0.8
    del rock, step, m

    # The sea: turquoise over the sand near the shore, deepening to blue; a line of foam where it meets the land,
    # broken lines of surf behind it, and long swell lines further out.
    depth = upsample(depth_lo) + 18 * (n2 - 0.5)
    bands = [(0, (150, 214, 204)), (9, (98, 192, 192)), (26, (64, 168, 184)), (60, (46, 142, 174)), (130, (38, 120, 164)), (260, (32, 102, 152)), (480, (28, 90, 140))]
    for lo, colour in bands:
        m = sea & (depth >= lo)
        img[m] = colour
    surf = np.zeros((NY, NX), bool)
    for at, width, gate in ((1.2, 1.6, 0.0), (9, 1.1, 0.42), (20, 0.9, 0.5), (36, 0.8, 0.56), (58, 0.7, 0.6)):
        surf |= (np.abs(depth - at) < width) & (n1 > gate)
    img[sea & surf] = np.array((244, 248, 246), np.float32)
    swell = sea & (depth > 80) & (np.mod(depth + 30 * n1, 46) < 1.1) & (n2 > 0.52)
    img[swell] = img[swell] * 0.55 + np.array((150, 204, 214), np.float32) * 0.45
    glint = sea & (value_noise((NY, NX), 2, 11) > 0.93) & (n1 > 0.6)
    img[glint] = img[glint] * 0.6 + np.array((190, 226, 230), np.float32) * 0.4
    del depth, surf, swell, glint, shore, beach, cliff, xx, yy

    paint_osm(img, cat)

    # Darken edges between unlike surfaces so plots read as crisp shapes. Roads get their edge from their mask.
    hard = ~np.isin(cat, list(SOFT | {CAT["sea"], CAT["rock"]})) & ~road
    border = (cat != np.roll(cat, 1, 0)) | (cat != np.roll(cat, 1, 1))
    img[border & hard] *= 0.86
    del hard, border

    # The shape of the land in light: slopes that face the sun are brighter, slopes that face away are dimmer.
    # Level ground stays as painted. The sea is left alone.
    az, el = math.radians(SUN_AZIMUTH), math.radians(SUN_ELEVATION)
    sun = np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])  # east, north, up
    sgy, sgx = np.gradient(ndi.gaussian_filter(dtm_lo, 1.5), LIDAR_RES)  # rows run south: d/dnorth = -sgy
    nrm = np.stack([-sgx, sgy, np.ones_like(sgx)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    lit = np.clip(nrm @ sun, 0, None) / math.sin(el)
    relief = np.clip(0.42 + 0.58 * lit, 0.5, 1.22)
    relief[sea_lo] = 1.0
    img *= upsample(relief)[..., None]
    del relief, lit, nrm, sgx, sgy

    # Baked shadows: of the land on itself (the cliffs on the coves), and of buildings and trees, plus a contact
    # shadow along every wall.
    shadow, contact = compute_shadows(dtm_lo, sea_lo)
    img *= np.where(shadow[..., None], np.array((0.62, 0.66, 0.8), np.float32), 1.0)
    img[contact] *= 0.8
    del shadow, contact

    # A kerb: the outer half metre of every road a little darker.
    img[road_rim] *= 0.74
    del road_rim

    img = np.clip(img, 0, 255).astype(np.uint8)
    Image.fromarray(img[::8, ::8]).save(BUILD / "ground_preview.png")
    # Two layers. The roads keep hard edges: their own layer has each road colour running on outward, with the road
    # itself in the alpha channel, which render/scene.js cuts at one half. The ground layer has the roads filled in
    # with the colours around them, so its soft texture doesn't smear grey past those hard edges.
    ri = ndi.distance_transform_edt(~road, return_distances=False, return_indices=True)
    road_img = np.dstack([img[ri[0], ri[1]], np.where(road, 255, 0).astype(np.uint8)])
    del ri
    gi = ndi.distance_transform_edt(road, return_distances=False, return_indices=True)
    img = img[gi[0], gi[1]]
    del gi
    save_chunks(img, BUILD / "ground")
    save_chunks(road_img, BUILD / "roads")
    print("ground done")


def save_chunks(img, out):
    if out.exists():
        for f in out.glob("*.png"):
            f.unlink()
    out.mkdir(exist_ok=True)
    px = int(CHUNK / GROUND_RES)
    for ix in range(CHUNKS_X):
        for iy in range(CHUNKS_Y):
            row = (CHUNKS_Y - 1 - iy) * px
            Image.fromarray(img[row : row + px, ix * px : ix * px + px]).save(out / f"{ix}_{iy}.png", optimize=False, compress_level=1)


def paint_osm(img, cat):
    """Sports pitches, riding arenas and graveyards from OpenStreetMap, drawn onto the ground."""
    path = RAW / "osm_landmarks.json"
    if not path.exists():
        return
    from geo import wgs_to_grid

    for el in json.load(open(path))["elements"]:
        t = el.get("tags", {})
        g = el.get("geometry")
        if el["type"] != "way" or not g:
            continue
        rd = np.array([wgs_to_grid(p["lat"], p["lon"]) for p in g])
        px = [((x - XMIN) / GROUND_RES, (YMAX - y) / GROUND_RES) for x, y in rd]
        x0, y0 = np.floor(np.min(px, 0)).astype(int) - 4
        x1, y1 = np.ceil(np.max(px, 0)).astype(int) + 4
        if x1 < 0 or y1 < 0 or x0 >= NX or y0 >= NY:
            continue
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, NX), min(y1, NY)
        w, h = x1 - x0, y1 - y0
        area = Image.new("L", (w, h), 0)
        ImageDraw.Draw(area).polygon([(a - x0, b - y0) for a, b in px], fill=1)
        area = np.array(area) > 0
        lines = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(lines)
        sub = img[y0:y1, x0:x1]
        # The pitch's own axes, from its outline.
        pts = np.array(px) - (x0, y0)
        if np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]  # OSM repeats the first node to close the ring; it would pull the center toward it
        c = pts.mean(0)
        _, vecs = np.linalg.eigh((pts - c).T @ (pts - c))
        ua, va = vecs[:, -1], vecs[:, 0]
        hu = np.abs((pts - c) @ ua).max()
        hv = np.abs((pts - c) @ va).max()
        P = lambda a, b: tuple(c + a * hu * ua + b * hv * va)
        sport = t.get("sport")
        if t.get("landuse") == "cemetery":
            sub[area] = np.array((108, 150, 70), np.float32)
            gy, gx = np.mgrid[0:h, 0:w]
            along = (gx - c[0]) * ua[0] + (gy - c[1]) * ua[1]
            across = (gx - c[0]) * va[0] + (gy - c[1]) * va[1]
            stones = (np.mod(along, 7) < 2) & (np.mod(across, 12) < 3) & area
            sub[stones] = np.array((176, 176, 170), np.float32)
            path_m = (np.abs(along) < 3) | (np.abs(across) < 3)
            sub[area & path_m] = np.array((196, 186, 160), np.float32)
        elif sport == "tennis":
            sub[area] = np.array((190, 104, 72), np.float32)
            d.polygon([P(-0.8, -0.7), P(0.8, -0.7), P(0.8, 0.7), P(-0.8, 0.7)], outline=1, width=2)
            d.line([P(0, -0.8), P(0, 0.8)], fill=1, width=2)
            d.line([P(-0.45, -0.55), P(0.45, -0.55)], fill=1, width=1)
            d.line([P(-0.45, 0.55), P(0.45, 0.55)], fill=1, width=1)
        elif sport == "equestrian":
            sub[area] = np.array((214, 196, 154), np.float32)
            d.polygon([tuple(p) for p in pts], outline=1, width=2)
        elif t.get("leisure") == "pitch":
            # Football: mowing stripes and the full set of lines, scaled to the pitch.
            gy, gx = np.mgrid[0:h, 0:w]
            along = (gx - c[0]) * ua[0] + (gy - c[1]) * ua[1]
            stripe = (np.mod(along, 40) < 20) & area
            sub[area] = np.array((96, 156, 64), np.float32)
            sub[stripe] = np.array((110, 170, 72), np.float32)
            m = 0.94
            d.polygon([P(-m, -m), P(m, -m), P(m, m), P(-m, m)], outline=1, width=2)
            d.line([P(0, -m), P(0, m)], fill=1, width=2)
            r = 9.15 / GROUND_RES
            d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=1, width=2)
            for s_ in (-1, 1):
                d.polygon([P(s_ * m, -0.6), P(s_ * (m - 0.3), -0.6), P(s_ * (m - 0.3), 0.6), P(s_ * m, 0.6)], outline=1, width=2)
                d.polygon([P(s_ * m, -0.28), P(s_ * (m - 0.1), -0.28), P(s_ * (m - 0.1), 0.28), P(s_ * m, 0.28)], outline=1, width=2)
        else:
            continue
        sub[np.array(lines) > 0] = np.array((240, 240, 236), np.float32)


def compute_shadows(dtm, sea):
    """Hard shadows at lidar resolution, upsampled to the ground raster: the land's own (a cliff over a cove), and
    those of building roofs and tree crowns, which stand on ground that may be higher or lower than where their
    shadow falls. Returns (shadow, contact shadow along walls)."""
    res = LIDAR_RES
    ny, nx = dtm.shape
    top = np.zeros((ny, nx), np.float32)  # height of the top of what stands on a cell, above its ground
    bot = np.full((ny, nx), np.inf, np.float32)  # and of its underside (a tree crown has air below)

    v = np.fromfile(BUILD / "buildings.bin", dtype=np.float32).reshape(-1, 12)
    tris = v.reshape(-1, 3, 12)
    tris = tris[tris[:, 0, 8] == 2]  # roofs
    for t in tris:
        col = (t[:, 0] + CX - XMIN) / res
        row = (YMAX - (CY - t[:, 2])) / res
        c0, c1 = int(max(col.min(), 0)), int(min(col.max() + 1, nx))
        r0, r1 = int(max(row.min(), 0)), int(min(row.max() + 1, ny))
        if c1 <= c0 or r1 <= r0:
            continue
        gy, gx = np.mgrid[r0:r1, c0:c1].astype(np.float32) + 0.5
        (x0, x1, x2), (y0, y1, y2) = col, row
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-9:
            continue
        a = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
        b = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
        c = 1 - a - b
        inside = (a >= -0.01) & (b >= -0.01) & (c >= -0.01)
        h = a * t[0, 1] + b * t[1, 1] + c * t[2, 1] - dtm[r0:r1, c0:c1]  # roof heights are absolute
        sub = top[r0:r1, c0:c1]
        np.maximum(sub, np.where(inside, h, 0), out=sub)
        sb = bot[r0:r1, c0:c1]
        np.minimum(sb, np.where(inside, 0, np.inf), out=sb)

    trees = np.fromfile(BUILD / "trees.bin", dtype=np.float32).reshape(-1, 11)
    for x, z, h, r, base, *_ in trees:
        col, row = (x + CX - XMIN) / res, (YMAX - (CY - z)) / res
        rr = r / res
        c0, c1 = int(max(col - rr, 0)), int(min(col + rr + 1, nx))
        r0, r1 = int(max(row - rr, 0)), int(min(row + rr + 1, ny))
        if c1 <= c0 or r1 <= r0:
            continue
        gy, gx = np.mgrid[r0:r1, c0:c1].astype(np.float32) + 0.5
        dd = ((gx - col) ** 2 + (gy - row) ** 2) / (rr * rr)
        inside = dd < 1
        mid, half = (h + base) / 2, (h - base) / 2
        s = np.sqrt(np.clip(1 - dd, 0, 1)) * half
        sub = top[r0:r1, c0:c1]
        np.maximum(sub, np.where(inside, mid + s, 0), out=sub)
        sb = bot[r0:r1, c0:c1]
        np.minimum(sb, np.where(inside, mid - s, np.inf), out=sb)

    az, el = math.radians(SUN_AZIMUTH), math.radians(SUN_ELEVATION)
    dx, dy = math.sin(az), -math.cos(az)  # toward the sun, in columns and rows
    shadow = np.zeros((ny, nx), bool)
    occupied = top > 0.3
    obj_top, obj_bot = dtm + top, dtm + np.where(np.isinf(bot), 1e6, bot)
    reach = float(top.max())
    relief = float(dtm.max() - dtm.min())
    steps = int(relief / math.tan(el) / res) + 1
    for k in range(1, steps + 1):
        ox, oy = int(round(dx * k)), int(round(dy * k))
        ray = dtm + k * res * math.tan(el)  # height of the sun ray from each cell, k cells toward the sun
        land = shift(dtm, ox, oy, -1e6)
        hit = land > ray + 0.6
        if k * res * math.tan(el) <= reach + 40:
            # Objects only matter close by: beyond their height (and some slope) they cannot reach the ray.
            hit |= (shift(obj_top, ox, oy, -1e6) >= ray) & (shift(obj_bot, ox, oy, 1e6) <= ray) & shift(occupied, ox, oy, False)
        shadow |= hit
    shadow &= ~occupied & ~sea
    contact = ndi.binary_dilation(occupied & (bot < 0.5) & (top > 1.5), iterations=1) & ~occupied
    return upsample(shadow) > 0.5, upsample(contact, smooth=False) > 0.5


def shift(a, ox, oy, fill):
    """out[r, c] = a[r + oy, c + ox]"""
    out = np.full_like(a, fill)
    h, w = a.shape
    rs, re = max(0, -oy), min(h, h - oy)
    cs, ce = max(0, -ox), min(w, w - ox)
    out[rs:re, cs:ce] = a[rs + oy : re + oy, cs + ox : ce + ox]
    return out


if __name__ == "__main__":
    main()
