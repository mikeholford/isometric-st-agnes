# /// script
# requires-python = "==3.13.*"
# dependencies = ["bpy==5.3.0", "numpy", "pillow", "scipy", "shapely>=2.1"]
# ///
"""A place on the map, looked at closely: rebuilt with as much detail as we can think of and rendered with a path
tracer (Blender's Cycles) from where the map's own camera stands, so that the picture lies exactly over the map.

What is real: the shape of the land (lidar), where the buildings stand and how high they are, where the roads run
(OpenStreetMap), where the trees stand and how big they are. What is made up, by rule: everything smaller than that.
Windows, doors, chimneys, slates, walls, grass, flowers, gravestones. deep/details.py holds the rules;
deep/scenes/<place>.py holds what was put in one place by hand.

  uv run deep/scene.py churchtown             the place as tiles for the viewer, in out/deep/churchtown-45/
  uv run deep/scene.py churchtown --try       one small picture, timed: how fast is this machine?
  uv run deep/scene.py churchtown --picture out/church.png [--at x,z] [--across 48] [--res 2400x1500] [--movers]

  --look 45       the compass direction the camera looks in, one of the map's views
  --scale 64      pixels to the metre (the map itself has 8)
  --samples 64    rays through every pixel: more is cleaner and slower
  --device auto   auto, cpu or gpu: a graphics card is used when there is one (Metal on a Mac)
  --sun az,el     where the sun stands; without it, where it stands on the map (scripts/sun.py)
  --movers        with everything that moves in the picture: people, parked cars, sheep, gulls, the traffic and the
                  giant. The tiles never have them: the place is a ghost town, and the viewer draws the life itself

A render that was cut short goes on where it stopped: every chunk of the picture is a file of its own.

Coordinates: the map's local metres are x east and z south from the middle of the map. In here X is east, Y north
and Z up, in metres from the middle of the block of land that is built, and from its lowest ground.
"""
import json, math, os, random, sys, time
import numpy as np
import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = ROOT + '/deep'
B = ROOT + '/data/build/'
sys.path.insert(0, ROOT + '/scripts')
from geo import wgs_to_grid  # noqa: E402
from config import CX, CY  # noqa: E402
from sun import SUN_AZIMUTH, SUN_ELEVATION  # noqa: E402

arg = lambda name, fallback: sys.argv[sys.argv.index('--' + name) + 1] if '--' + name in sys.argv else fallback
flag = lambda name: '--' + name in sys.argv
PLACE = next(p for p in json.load(open(SRC + '/places.json')) if p['id'] == sys.argv[1])
LOOK, SCALE, SAMPLES = int(arg('look', '45')), int(arg('scale', '64')), int(arg('samples', '64'))
MODE = 'try' if flag('try') else 'picture' if flag('picture') else 'tiles'
MOVERS = flag('movers')
WORK = f"{ROOT}/out/deep/{PLACE['id']}-{LOOK}"
HERE = WORK + '/work'
os.makedirs(HERE, exist_ok=True)
rnd = random.Random(7)
Image.MAX_IMAGE_PIXELS = None

# ------------------------------------------------------------------------------------------------------------------
# The picture: a rectangle of the map's own picture, in metres across the screen (u) and up it (v), counted the way
# the viewer counts them: u = x cos + z sin, v = (x sin - z cos) / 2 + height cos 30.

COS30 = math.cos(math.radians(30))
LC, LS = math.cos(math.radians(LOOK)), math.sin(math.radians(LOOK))
dtm = np.load(B + 'dtm.npy')  # 1 m cells, row 0 north, metres above Ordnance Datum
HX, HZ = dtm.shape[1] // 2, dtm.shape[0] // 2


def screen(x, z, h):
    return x * LC + z * LS, (x * LS - z * LC) / 2 + h * COS30


def unscreen(u, v, h):
    """The point at height h that the map draws at u, v."""
    d = 2 * (v - h * COS30)
    return u * LC + d * LS, u * LS - d * LC


x_at, z_at = [float(q) for q in arg('at', '').split(',')] if flag('at') else PLACE['at']
H_AT = float(dtm[int(z_at + HZ), int(x_at + HX)])
u_at, v_at = screen(x_at, z_at, H_AT)
if MODE == 'tiles':
    FW, FH = PLACE['size']
    PW, PH = round(FW * SCALE), round(FH * SCALE)
else:
    PW, PH = [int(q) for q in arg('res', '1280x800').split('x')]
    FW = float(arg('across', PW / SCALE))
    FH = FW * PH / PW
U0, U1, V0, V1 = u_at - FW / 2, u_at + FW / 2, v_at - FH / 2, v_at + FH / 2

CHUNK, EDGE, TILE = 2048, 32, 512  # a chunk's edge is rendered and thrown away: the denoiser needs neighbours on every side
todo = [(cx, row) for row in range(math.ceil(PH / CHUNK)) for cx in range(math.ceil(PW / CHUNK))]


def cut_tiles():
    """The pyramid: the picture halved and halved again, each size cut into tiles, laid out as Deep Zoom has them.
    Only the sizes sharper than the map itself are kept; below that the map shows. The picture fades out towards its
    edges, so that it has no hard border where it lies on the map. It is cut twice: whole, and once more with only
    what stands up, which the viewer draws over its cars and walkers."""
    full, stands = Image.new('RGB', (PW, PH)), Image.new('L', (PW, PH))
    for cx, row in todo:
        full.paste(Image.open(f'{WORK}/chunks-{SCALE}/{cx}_{row}.png'), (cx * CHUNK, row * CHUNK))
        stands.paste(Image.open(f'{WORK}/chunks-{SCALE}/{cx}_{row}_mask.png'), (cx * CHUNK, row * CHUNK))
    full.resize((PW // 2, PH // 2), Image.LANCZOS).save(WORK + '/picture.jpg', quality=90)  # the whole place in one file, to look at
    soft = float(PLACE.get('soft', 5)) * SCALE  # metres of fading at the edge, in pixels
    fx = np.clip(np.minimum(np.arange(PW), PW - 1 - np.arange(PW)) / soft, 0, 1)
    fy = np.clip(np.minimum(np.arange(PH), PH - 1 - np.arange(PH)) / soft, 0, 1)
    fade = np.minimum(fx[None, :], fy[:, None])
    fade = fade * fade * (3 - 2 * fade)
    whole = Image.fromarray((fade * 255).astype(np.uint8))
    up = Image.fromarray((fade * np.asarray(stands)).astype(np.uint8))
    del fade
    top = math.ceil(math.log2(max(PW, PH)))
    least = top - max(0, round(math.log2(SCALE / 4)))
    for layer, img in (('map', Image.merge('RGBA', (*full.split(), whole))), ('objects', Image.merge('RGBA', (*full.split(), up)))):
        for level in range(top, least - 1, -1):
            os.makedirs(f'{WORK}/{layer}_files/{level}', exist_ok=True)
            for row in range(math.ceil(img.height / TILE)):
                for col in range(math.ceil(img.width / TILE)):
                    img.crop((col * TILE, row * TILE, min(img.width, (col + 1) * TILE), min(img.height, (row + 1) * TILE))).save(
                        f'{WORK}/{layer}_files/{level}/{col}_{row}.webp', quality=88, method=4)
            img = img.resize((math.ceil(img.width / 2), math.ceil(img.height / 2)), Image.LANCZOS)
    json.dump({'id': PLACE['id'], 'name': PLACE['name'], 'look': LOOK, 'scale': SCALE, 'u': [U0, U1], 'v': [V0, V1], 'width': PW, 'height': PH,
               'tileSize': TILE, 'minLevel': least, 'tiles': 'map_files/', 'objects': 'objects_files/'}, open(WORK + '/place.json', 'w'))
    print(f'tiles in {WORK}, and the whole picture to look at in {WORK}/picture.jpg')


if MODE == 'tiles':
    os.makedirs(f'{WORK}/chunks-{SCALE}', exist_ok=True)  # a folder for each sharpness, so one never passes for another
    if all(os.path.exists(f'{WORK}/chunks-{SCALE}/{cx}_{row}{kind}.png') for cx, row in todo for kind in ('', '_mask')):
        cut_tiles()  # all of it is rendered already: only the tiles are cut again
        sys.exit()

# The land that has to be built for it: whatever shows in the rectangle, whatever is tall enough in front of it to
# stand up into it, and a margin beyond for the shadows that fall in from outside.
TALL, SHADE = 30.0, 28
reach = int(FW / 2 + FH * 2 + TALL * 2 + 140)
wc0, wr0 = max(0, int(x_at + HX) - reach), max(0, int(z_at + HZ) - reach)
win = dtm[wr0:int(z_at + HZ) + reach, wc0:int(x_at + HX) + reach]
wx, wz = np.meshgrid(np.arange(win.shape[1]) + wc0 + 0.5 - HX, np.arange(win.shape[0]) + wr0 + 0.5 - HZ)
wu, wv = screen(wx, wz, win)
shows = (wu > U0 - 3) & (wu < U1 + 3) & (wv < V1 + 3) & (wv + TALL * COS30 > V0 - 3)
needed = ndi.binary_dilation(shows, iterations=SHADE)
rows, cols = np.flatnonzero(needed.any(1)), np.flatnonzero(needed.any(0))
CXB = round((cols[0] + cols[-1]) / 2 + wc0 - HX)  # the block: its middle in the map's local metres, and half its side
CZB = round((rows[0] + rows[-1]) / 2 + wr0 - HZ)
HALF = float(math.ceil(max(cols[-1] - cols[0], rows[-1] - rows[0]) / 2) + 6)
N1 = int(2 * HALF) - 1
print(f"{PLACE['name']}: a picture {FW:.0f} m by {FH:.0f} m at {PW} by {PH} pixels, on a block of land {2 * HALF:.0f} m square")


def inside(x, y):
    """Is this spot (X, Y of the block) on land the picture needs?"""
    c, r = int(x + CXB + HX) - wc0, int(CZB - y + HZ) - wr0
    return 0 <= r < needed.shape[0] and 0 <= c < needed.shape[1] and bool(needed[r, c])


# ------------------------------------------------------------------------------------------------------------------
# The land

pad = 6
c0, r0 = int(CXB + HX - HALF) - pad, int(CZB + HZ - HALF) - pad
sub = dtm[r0:r0 + int(2 * HALF) + 2 * pad, c0:c0 + int(2 * HALF) + 2 * pad].astype(np.float64)
Z0 = float(sub[pad:-pad, pad:-pad].min())
sub = ndi.gaussian_filter(sub, 0.6)


def ground(x, y):
    """Height of the land at X, Y (scalars or arrays), above the lowest ground of the block."""
    col = np.asarray(x) + CXB + HX - 0.5 - c0
    row = (CZB - np.asarray(y)) + HZ - 0.5 - r0
    return ndi.map_coordinates(sub, [np.atleast_1d(row), np.atleast_1d(col)], order=3, mode='nearest').reshape(np.shape(x)) - Z0


def to_block(x_local, z_local):
    return x_local - CXB, CZB - z_local


def in_picture(x, y, z, edge=1.0):
    """Does the point X, Y, Z of the block show in the picture? Works on arrays."""
    u, v = screen(np.asarray(x) + CXB, CZB - np.asarray(y), np.asarray(z) + Z0)
    return (u > U0 - edge) & (u < U1 + edge) & (v > V0 - edge) & (v < V1 + edge)


# ------------------------------------------------------------------------------------------------------------------
# Geometry in batches: one mesh for each material, with a colour and two free numbers on every vertex

class Batch:
    """One mesh in the making. What comes in millions (blades of grass) is handed over whole instead: v an array of
    points, three to a triangle, tint an array of their colours."""

    def __init__(self, name, smooth=False):
        self.name, self.smooth = name, smooth
        self.v, self.f, self.tint, self.uvw = [], [], [], []

    def add(self, verts, faces, tint=(1, 1, 1), uvw=None):
        base = len(self.v)
        self.v.extend(verts)
        self.f.extend([tuple(i + base for i in face) for face in faces])
        self.tint.extend([tint] * len(verts) if isinstance(tint[0], (int, float)) else tint)
        self.uvw.extend(uvw if uvw is not None else [(0.0, 0.0)] * len(verts))


BATCH = {}


def batch(name, smooth=False):
    if name not in BATCH:
        BATCH[name] = Batch(name, smooth)
    return BATCH[name]


def quad(b, p0, p1, p2, p3, tint, uvw=None):
    b.add([p0, p1, p2, p3], [(0, 1, 2, 3)], tint, uvw)


def obox(b, o, ax, ay, az, tint):
    """A box from a corner and three edges."""
    o, ax, ay, az = (np.asarray(v, float) for v in (o, ax, ay, az))
    c = [o, o + ax, o + ax + ay, o + ay, o + az, o + ax + az, o + ax + ay + az, o + ay + az]
    b.add([tuple(p) for p in c], [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)], tint)


def cbox(b, centre, size, yaw, tint):
    """A box about its centre, turned about the vertical."""
    c, s = math.cos(yaw), math.sin(yaw)
    ax, ay, az = np.array([c, s, 0]) * size[0], np.array([-s, c, 0]) * size[1], np.array([0, 0, 1.0]) * size[2]
    obox(b, np.asarray(centre, float) - ax / 2 - ay / 2 - az / 2, ax, ay, az, tint)


def cyl(b, base, radius, height, tint, n=12, top=None, axis=(0, 0, 1), cap=True):
    base, axis = np.asarray(base, float), np.asarray(axis, float)
    axis = axis / np.linalg.norm(axis)
    side = np.cross(axis, (0, 0, 1) if abs(axis[2]) < 0.9 else (1, 0, 0))
    side /= np.linalg.norm(side)
    other = np.cross(axis, side)
    top = radius if top is None else top
    ring = [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)) for i in range(n)]
    verts = [tuple(base + (side * c + other * s) * radius) for c, s in ring] + [tuple(base + axis * height + (side * c + other * s) * top) for c, s in ring]
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    if cap:
        faces += [tuple(range(n, 2 * n)), tuple(range(n - 1, -1, -1))]
    b.add(verts, faces, tint)


def prism(b, ring, z0, z1, tint, top=True, bottom=False, uv=None):
    """A flat-topped solid over an outline (a list of X, Y), from z0 to z1."""
    n = len(ring)
    verts = [(x, y, z0) for x, y in ring] + [(x, y, z1) for x, y in ring]
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    if top or bottom:
        tris = tessellate_polygon([[Vector((x, y, 0)) for x, y in ring]])
        if top:
            faces += [(n + i, n + j, n + k) for i, j, k in tris]
        if bottom:
            faces += [(k, j, i) for i, j, k in tris]
    b.add(verts, faces, tint, [uv(x, y, z) for x, y, z in verts] if uv else None)


def rings(geom):
    """The outer rings of whatever shapely hands back, anticlockwise, without the closing point."""
    polys = [geom] if isinstance(geom, Polygon) else list(getattr(geom, 'geoms', []))
    return [list(orient(p).exterior.coords)[:-1] for p in polys if isinstance(p, Polygon) and not p.is_empty and p.area > 0.02]


ICO = None


def blob(b, centre, radii, tint, jitter=0.0, seed=0):
    """A lumpy ball."""
    global ICO
    if ICO is None:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1)
        ob = bpy.context.object
        ICO = (np.array([v.co[:] for v in ob.data.vertices]), [tuple(p.vertices) for p in ob.data.polygons])
        bpy.data.objects.remove(ob)
    verts, faces = ICO
    r = np.random.default_rng(seed)
    k = 1 + jitter * (r.random(len(verts)) - 0.5) * 2
    pts = verts * k[:, None] * np.asarray(radii) + np.asarray(centre)
    b.add([tuple(p) for p in pts], faces, tint)


# ------------------------------------------------------------------------------------------------------------------
# Roads, from OpenStreetMap: outlines for the ground, centre lines for the paint

ROADS = {'secondary': 3.2, 'tertiary': 2.9, 'unclassified': 2.3, 'residential': 2.6, 'service': 1.6, 'footway': 0.9, 'path': 0.9, 'track': 1.4, 'steps': 1.0}
roads = []
for w in json.load(open(ROOT + '/data/raw/osm_roads.json'))['elements']:
    hw = w.get('tags', {}).get('highway')
    if w['type'] != 'way' or hw not in ROADS:
        continue
    pts = []
    for g in w['geometry']:
        X, Y = wgs_to_grid(g['lat'], g['lon'])
        pts.append(to_block(X - CX, CY - Y))
    line = LineString(pts)
    if line.distance(Point(0, 0)) < HALF * 1.6:
        surface = w['tags'].get('surface', '')
        kind = 'gravel' if surface in ('fine_gravel', 'gravel', 'unpaved', 'ground', 'dirt') or hw == 'track' else 'paved' if hw in ('footway', 'path', 'steps') else 'asphalt'
        roads.append({'line': line, 'half': ROADS[hw], 'hw': hw, 'kind': kind, 'name': w['tags'].get('name')})


def rounded(pts, times=3):
    for _ in range(times):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out += [(a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25), (a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75)]
        pts = out + [pts[-1]]
    return pts


joined = []
for hw, kind in sorted({(r['hw'], r['kind']) for r in roads}):
    merged = linemerge([r['line'] for r in roads if (r['hw'], r['kind']) == (hw, kind)])
    for line in getattr(merged, 'geoms', [merged]):
        joined.append({'line': LineString(rounded(list(line.coords))), 'half': ROADS[hw], 'hw': hw, 'kind': kind, 'name': None})
roads = joined
asphalt = unary_union([r['line'].buffer(r['half'], resolution=16) for r in roads if r['kind'] == 'asphalt'])
paved = unary_union([r['line'].buffer(r['half'], resolution=16) for r in roads if r['kind'] == 'paved']).difference(asphalt)
gravel = unary_union([r['line'].buffer(r['half'], resolution=16) for r in roads if r['kind'] == 'gravel']).difference(asphalt)
# A pavement along the main road through the village.
main = unary_union([r['line'].buffer(r['half'] + 1.25, resolution=16) for r in roads if r['hw'] == 'secondary'])
pavement = main.difference(asphalt)

# ------------------------------------------------------------------------------------------------------------------
# Buildings: the outline of each, and what the map knows of it

meta = json.load(open(B + 'buildings.json'))
bin_ = np.fromfile(B + 'buildings.bin', dtype=np.float32).reshape(-1, 12)
order = np.argsort(bin_[:, 9], kind='stable')
bin_ = bin_[order]
starts = np.flatnonzero(np.r_[True, np.diff(bin_[:, 9]) != 0, True])
known = []  # (point inside, meta, vertices) of every building of the map near the block
for a, e in zip(starts[:-1], starts[1:]):
    x, y = to_block(bin_[a:e, 0].mean(), bin_[a:e, 2].mean())
    if abs(x) < HALF + 30 and abs(y) < HALF + 30:
        known.append((Point(x, y), meta[int(bin_[a, 9])], bin_[a:e]))
buildings = []
for ring in json.load(open(B + 'footprints.json')):
    poly = orient(Polygon([to_block(x, z) for x, z in ring]).buffer(0))
    if poly.is_empty or not isinstance(poly, Polygon) or poly.distance(Point(0, 0)) > HALF * 1.5:
        continue
    near = sorted(known, key=lambda k: poly.distance(k[0]) + (0 if k[1]['kind'] != 'tower' else 5))
    m = near[0][1] if near and poly.distance(near[0][0]) < 2 else {'kind': 'house', 'height': 6.5, 'ground': None, 'param': 3.8, 'rand': rnd.random()}
    buildings.append({'poly': poly.simplify(0.25), 'meta': m})
BLOCK = box(-HALF, -HALF, HALF, HALF)
kept = []
for b in buildings:
    part = b['poly'] if b['poly'].within(BLOCK.buffer(-1)) else b['poly'].intersection(BLOCK.buffer(-1))
    part = max(getattr(part, 'geoms', [part]), key=lambda g: g.area, default=None)
    if part is not None and isinstance(part, Polygon) and part.area > 6 and any(inside(x, y) for x, y in part.exterior.coords):
        kept.append({'poly': orient(part), 'meta': b['meta']})
buildings = kept
taken = unary_union([b['poly'] for b in buildings])
tower_verts = next((k[2] for k in known if k[1]['kind'] == 'tower'), None)

# ------------------------------------------------------------------------------------------------------------------
# The ground: a mesh every half metre, painted from the map's own unlit ground, with the roads drawn sharp over it

PX = 0.05  # metres a pixel of the mask
size = int(2 * HALF / PX)
mask = Image.new('RGB', (size, size), (0, 0, 0))
draw = ImageDraw.Draw(mask)
to_px = lambda ring: [((x + HALF) / PX, (HALF - y) / PX) for x, y in ring]
for geom, colour in ((pavement, (0, 255, 0)), (gravel, (0, 0, 255)), (paved, (0, 160, 160)), (asphalt, (255, 0, 0))):
    for ring in rings(geom):
        draw.polygon(to_px(ring), fill=colour)
mask.save(HERE + '/mask.png')

alb = np.asarray(Image.open(B + 'ground_albedo.jpg').convert('RGB')).astype(np.float32)  # 1 m a pixel, row 0 north
ac0, ar0 = int(CXB + HX - HALF), int(CZB + HZ - HALF)
alb = alb[ar0:ar0 + int(2 * HALF), ac0:ac0 + int(2 * HALF)]
# The map's own roads are grey smears at this size: take them out, and let what grows beside them close over.
lum, sat = alb.mean(-1), (alb.max(-1) - alb.min(-1)) / np.maximum(1, alb.max(-1))
grey = (sat < 0.16) & (lum > 50) & (lum < 175)
idx = ndi.distance_transform_edt(grey, return_distances=False, return_indices=True)
alb = ndi.gaussian_filter(alb[idx[0], idx[1]], (1.2, 1.2, 0))
lum, sat = alb.mean(-1), (alb.max(-1) - alb.min(-1)) / np.maximum(1, alb.max(-1))
garden = ndi.gaussian_filter(((sat < 0.3) & (lum > 120)).astype(np.float32), 1.5)[..., None]
wood = ndi.gaussian_filter((lum < 92).astype(np.float32), 2.0)[..., None]
alb = np.array([92.0, 112, 52]) * (1 - wood) + np.array([64.0, 76, 42]) * wood  # pasture, or the floor of a wood
alb = alb * (1 - garden) + np.array([84.0, 108, 50]) * garden  # lawns
rs = np.random.default_rng(5)
for size_, amount in ((14, 0.22), (5, 0.14), (1.5, 0.08)):  # fields are never one colour
    alb = alb * (1 + amount * ndi.gaussian_filter(rs.standard_normal(alb.shape[:2]), size_)[..., None] * size_ * 2)
    alb[..., 0] *= 1 + amount * 0.8 * ndi.gaussian_filter(rs.standard_normal(alb.shape[:2]), size_) * size_ * 2  # drier, yellower patches
Image.fromarray(np.clip(alb, 0, 255).astype(np.uint8)).resize((int(2 * HALF) * 10,) * 2, Image.BICUBIC).save(HERE + '/albedo.png')
green = np.ones(alb.shape[:2], bool)  # where grass can grow: everywhere that is not road or house


def albedo_at(x, y):
    r, c = int(min(N1, max(0, HALF - y))), int(min(N1, max(0, x + HALF)))
    return alb[r, c] / 255, bool(green[r, c])


n = int(2 * HALF / 0.5) + 1
xs = np.linspace(-HALF, HALF, n)
gx, gy = np.meshgrid(xs, xs)
gz = ground(gx, gy)
g = batch('ground')
g.v = list(zip(gx.ravel().tolist(), gy.ravel().tolist(), gz.ravel().tolist()))
g.f = [(r * n + c, r * n + c + 1, (r + 1) * n + c + 1, (r + 1) * n + c) for r in range(n - 1) for c in range(n - 1)]
g.tint = [(1, 1, 1)] * len(g.v)
g.uvw = list(zip(((gx.ravel() + HALF) / (2 * HALF)).tolist(), ((gy.ravel() + HALF) / (2 * HALF)).tolist()))
# The block is cut out of the land: its sides show the earth and the rock under it.
soil = batch('soil')
for edge in (zip(xs, [-HALF] * n), zip([HALF] * n, xs), zip(xs[::-1], [HALF] * n), zip([-HALF] * n, xs[::-1])):
    pts = list(edge)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        h0, h1 = float(ground(x0, y0)), float(ground(x1, y1))
        for top, low in ((0.0, 0.5), (0.5, 2.0), (2.0, None)):
            z0a, z1a = (h0 - low, h1 - low) if low is not None else (-6.0, -6.0)
            quad(soil, (x0, y0, z0a), (x1, y1, z1a), (x1, y1, h1 - top), (x0, y0, h0 - top), (1, 1, 1),
                 [(h0 - z0a, 0.0), (h1 - z1a, 0.0), (top, 0.0), (top, 0.0)])
quad(soil, (-HALF, -HALF, -6), (-HALF, HALF, -6), (HALF, HALF, -6), (HALF, -HALF, -6), (1, 1, 1), [(20.0, 0.0)] * 4)

# ------------------------------------------------------------------------------------------------------------------
# Houses

WALLS = [(0.86, 0.84, 0.78), (0.8, 0.76, 0.66), (0.9, 0.88, 0.84), (0.74, 0.7, 0.62), (0.78, 0.82, 0.82), (0.84, 0.74, 0.68), (0.82, 0.8, 0.66)]
STONE = [(0.42, 0.39, 0.35), (0.5, 0.46, 0.4), (0.36, 0.34, 0.33)]
SLATE = [(0.37, 0.385, 0.41), (0.4, 0.41, 0.42), (0.34, 0.355, 0.385), (0.42, 0.415, 0.405), (0.385, 0.4, 0.405)]
DOORS = [(0.08, 0.16, 0.3), (0.12, 0.28, 0.2), (0.5, 0.08, 0.08), (0.05, 0.05, 0.06), (0.75, 0.6, 0.15), (0.3, 0.42, 0.5), (0.85, 0.85, 0.82)]
WHITE, GRANITE, IRON, CLAY = (0.9, 0.9, 0.87), (0.55, 0.53, 0.5), (0.05, 0.05, 0.06), (0.6, 0.3, 0.2)
road_edge = unary_union([asphalt, paved, gravel])
RIDGES, DOORWAYS, CHIMNEYS, FRONTS = [], [], [], []


def facade(p0, p1, z0, z1, floor, wall, tint, openings, trim):
    """One wall, from p0 to p1 (X, Y), with real openings cut in it: each is (along, bottom, width, height, kind),
    in metres from p0 and from the floor. A window sits back in the wall behind its frame; a door likewise."""
    p0, p1 = np.array(p0, float), np.array(p1, float)
    length = float(np.linalg.norm(p1 - p0))
    along = (p1 - p0) / length
    out = np.array([along[1], -along[0]])
    at = lambda s, h, d=0.0: (float(p0[0] + along[0] * s + out[0] * d), float(p0[1] + along[1] * s + out[1] * d), float(h))
    uv = lambda s, h: (s, h - floor)
    cuts = sorted(o for o in openings if o[0] - o[2] / 2 > 0.25 and o[0] + o[2] / 2 < length - 0.25 and floor + o[1] > z0 + 0.05 and floor + o[1] + o[3] < z1 - 0.15)
    # The wall between the openings, and above and below each.
    s = 0.0
    spans = []
    for a, bot, w, h, kind in cuts:
        if a - w / 2 < s:
            continue
        spans.append((s, a - w / 2, z0, z1))
        spans.append((a - w / 2, a + w / 2, z0, floor + bot))
        spans.append((a - w / 2, a + w / 2, floor + bot + h, z1))
        s = a + w / 2
    spans.append((s, length, z0, z1))
    for s0, s1, h0, h1 in spans:
        if s1 - s0 > 1e-3 and h1 - h0 > 1e-3:
            quad(wall, at(s0, h0), at(s1, h0), at(s1, h1), at(s0, h1), tint, [uv(s0, h0), uv(s1, h0), uv(s1, h1), uv(s0, h1)])
    paint, glass, stone = batch('gloss'), batch('glass'), batch('matte')
    for a, bot, w, h, kind in cuts:
        b0, b1, l, r = floor + bot, floor + bot + h, a - w / 2, a + w / 2
        deep = 0.11
        # The reveal: the thickness of the wall round the opening.
        for q in ((at(l, b0), at(l, b0, -deep), at(l, b1, -deep), at(l, b1)), (at(r, b0, -deep), at(r, b0), at(r, b1), at(r, b1, -deep)),
                  (at(l, b1, -deep), at(r, b1, -deep), at(r, b1), at(l, b1)), (at(l, b0), at(r, b0), at(r, b0, -deep), at(l, b0, -deep))):
            quad(wall, *q, tint, [uv(l, b0)] * 4)
        ax3, up, out3 = np.array([along[0], along[1], 0]), np.array([0, 0, 1.0]), np.array([out[0], out[1], 0])
        o3 = lambda s_, h_, d_: np.array(at(s_, h_, d_))
        if kind == 'door':
            colour = trim['door']
            if w < 1.2:
                DOORWAYS.append((at(a, b0, 0.0), (float(out[0]), float(out[1])), (float(along[0]), float(along[1]))))
            quad(paint, at(l, b0, -deep + 0.02), at(r, b0, -deep + 0.02), at(r, b1 - 0.28, -deep + 0.02), at(l, b1 - 0.28, -deep + 0.02), colour)
            for i in range(2):  # panels
                for j in range(2):
                    obox(paint, o3(l + 0.1 + i * (w / 2 - 0.02), b0 + 0.18 + j * 0.86, -deep + 0.02), ax3 * (w / 2 - 0.16), out3 * 0.015, up * 0.7, tuple(c * 0.86 for c in colour))
            quad(glass, at(l, b1 - 0.26, -deep + 0.03), at(r, b1 - 0.26, -deep + 0.03), at(r, b1, -deep + 0.03), at(l, b1, -deep + 0.03), (1, 1, 1))  # the fanlight
            obox(paint, o3(l, b1 - 0.29, -deep), ax3 * w, out3 * 0.05, up * 0.04, WHITE)
            obox(batch('brass'), o3(r - 0.16, b0 + 1.0, -deep + 0.03), ax3 * 0.05, out3 * 0.06, up * 0.05, (1, 1, 1))  # the knob
            obox(batch('brass'), o3(a - 0.12, b0 + 1.08, -deep + 0.03), ax3 * 0.24, out3 * 0.012, up * 0.045, (1, 1, 1))  # the letter box
            obox(stone, o3(l - 0.15, b0 - 0.16, 0), ax3 * (w + 0.3), out3 * 0.42, up * 0.16, GRANITE)  # the step
            for s_ in (l - 0.09, r):
                obox(paint, o3(s_, b0, 0), ax3 * 0.09, out3 * 0.025, up * (h + 0.09), trim['frame'])
            obox(paint, o3(l - 0.09, b1, 0), ax3 * (w + 0.18), out3 * 0.03, up * 0.1, trim['frame'])
            continue
        quad(glass, at(l, b0, -deep + 0.03), at(r, b0, -deep + 0.03), at(r, b1, -deep + 0.03), at(l, b1, -deep + 0.03), (1, 1, 1))
        f = 0.055  # the frame, the meeting rail of the sash, and its glazing bars
        frame = trim['frame']
        for box in ((l, b0, w, f), (l, b1 - f, w, f), (l, b0, f, h), (r - f, b0, f, h), (l, b0 + h / 2 - 0.025, w, 0.05)):
            obox(paint, o3(box[0], box[1], -deep + 0.03), ax3 * box[2], out3 * 0.05, up * box[3], frame)
        bars = trim['bars'] if kind == 'window' else 3
        for i in range(1, bars + 1):
            obox(paint, o3(l + w * i / (bars + 1) - 0.012, b0, -deep + 0.04), ax3 * 0.024, out3 * 0.025, up * h, frame)
        if kind == 'lancet':
            for j in range(1, 6):
                obox(paint, o3(l, b0 + h * j / 6, -deep + 0.04), ax3 * w, out3 * 0.02, up * 0.02, frame)
        obox(stone, o3(l - 0.08, b0 - 0.07, -0.02), ax3 * (w + 0.16), out3 * 0.09, up * 0.07, GRANITE)  # the sill
        if trim['lintel']:
            obox(stone, o3(l - 0.14, b1, 0), ax3 * (w + 0.28), out3 * 0.02, up * 0.2, GRANITE)
        elif trim['surround']:
            for s_ in (l - 0.1, r):
                obox(paint, o3(s_, b0 - 0.07, 0), ax3 * 0.1, out3 * 0.018, up * (h + 0.17), trim['surround'])
            obox(paint, o3(l - 0.1, b1, 0), ax3 * (w + 0.2), out3 * 0.018, up * 0.1, trim['surround'])


def roof(poly, eaves, ridge, hipped, tint, wall, wall_tint, seed):
    """A slate roof laid course by course: each course is the outline drawn in a little further and a little higher,
    as slates overlap going up a roof. A gabled roof draws in from the two long sides only; a hipped one from all."""
    rect = poly.minimum_rotated_rectangle
    c = list(rect.exterior.coords)
    e0, e1 = np.subtract(c[1], c[0]), np.subtract(c[2], c[1])
    long_, short = (e0, e1) if np.linalg.norm(e0) >= np.linalg.norm(e1) else (e1, e0)
    half = float(np.linalg.norm(short)) / 2
    axis = long_ / np.linalg.norm(long_)
    perp = np.array([-axis[1], axis[0]])
    pitch = math.atan2(max(0.8, ridge - eaves), half)
    pitch = min(math.radians(50), max(math.radians(27), pitch))
    lap = 0.21  # how much of each slate shows, up the slope
    dt, dz = lap * math.cos(pitch), lap * math.sin(pitch)
    slates, matte = batch('slate'), batch('matte')
    for ring in rings(poly.buffer(0.3, join_style=2)):
        prism(matte, ring, eaves - 0.16, eaves - 0.02, (0.12, 0.12, 0.13), bottom=True)  # fascia and gutter
    levels = []
    while len(levels) < 400:
        t = len(levels) * dt
        level = poly.buffer(-t, join_style=2) if hipped else poly.intersection(affinity.translate(poly, *(perp * t))).intersection(affinity.translate(poly, *(-perp * t)))
        if level.is_empty or level.area < 0.05:
            break
        levels.append(level)
    k, last = len(levels), (levels[-1] if levels else poly)
    for j, level in enumerate(levels):
        z = eaves + j * dz
        shade = 0.93 + 0.14 * random.Random(seed * 131 + j).random()
        for ring in rings(level):
            prism(wall, ring, z - dz if j else eaves - 0.2, z, wall_tint, top=False, uv=lambda x, y, z_: (x * axis[0] + y * axis[1], z_ - eaves + 3.5))
        outer = level.buffer(0.3, join_style=2)
        inner = levels[j + 1].buffer(0.3, join_style=2) if j + 1 < k else None
        band, edge = (outer.difference(inner), inner.boundary) if inner is not None else (outer, None)
        for tri in shapely.constrained_delaunay_triangles(band).geoms:
            pts = list(tri.exterior.coords)[:3]
            up = [edge is not None and edge.distance(Point(q)) < 1e-4 for q in pts]
            v3 = [(q[0], q[1], z + (dz if u_ else 0.025)) for q, u_ in zip(pts, up)]
            nrm = np.cross(np.subtract(v3[1], v3[0]), np.subtract(v3[2], v3[0]))
            if nrm[2] < 0:
                v3, up, nrm = v3[::-1], up[::-1], -nrm
            flat = math.hypot(nrm[0], nrm[1])
            run_ = (-nrm[1] / flat, nrm[0] / flat) if flat > 1e-6 else (axis[0], axis[1])
            slates.add(v3, [(0, 1, 2)], tuple(v * shade for v in tint), [(q[0] * run_[0] + q[1] * run_[1], j + (1.0 if u_ else 0.0)) for q, u_ in zip(v3, up)])
    top = eaves + k * dz
    # The ridge: a row of ridge tiles along the last course.
    lr = last.minimum_rotated_rectangle
    if not lr.is_empty and lr.geom_type == 'Polygon':
        lc = list(lr.exterior.coords)
        a, b_ = np.subtract(lc[1], lc[0]), np.subtract(lc[2], lc[1])
        run = a if np.linalg.norm(a) >= np.linalg.norm(b_) else b_
        mid = np.mean(lc[:4], axis=0)
        length = float(np.linalg.norm(run))
        if length > 0.8:
            yaw = math.atan2(run[1], run[0])
            for i in range(int(length / 0.45) + 1):
                p = mid + run / length * (-length / 2 + 0.225 + i * 0.45)
                if i * 0.45 + 0.4 <= length + 0.3:
                    cbox(matte, (p[0], p[1], top + 0.03), (0.43, 0.3, 0.12), yaw, (0.3, 0.2, 0.17) if seed % 3 else (0.2, 0.2, 0.22))
            RIDGES.append((mid, run / length, top + 0.09, length))
    return axis, top, last


def house(bld, i):
    poly, m = bld['poly'], bld['meta']
    r = random.Random(i * 977 + 3)
    kind = m.get('kind', 'house')
    ring = rings(poly)[0]
    lows = [float(ground(x, y)) for x, y in ring]
    floor = (m['ground'] - Z0) if m.get('ground') else float(np.mean(lows))
    base = min(lows) - 0.3
    height = float(m.get('height') or 6.5)
    eaves_h = float(m.get('param') or height * 0.6)
    if kind == 'church':
        eaves_h = 5.6
    if kind == 'outbuilding':
        eaves_h = min(eaves_h, 2.4)
    eaves, ridge = floor + eaves_h, floor + max(height, eaves_h + 1.2)
    stone = kind == 'church' or r.random() < 0.38
    wall = batch('stone' if stone else 'render')
    tint = r.choice(STONE) if stone else r.choice(WALLS)
    if kind == 'church':
        tint = (0.5, 0.45, 0.38)
    trim = {'frame': WHITE if r.random() < 0.8 else r.choice(DOORS), 'door': r.choice(DOORS), 'bars': r.choice([1, 1, 2, 3]),
            'lintel': stone, 'surround': None if stone or r.random() < 0.5 else tuple(min(1, c * 1.1 + 0.05) for c in tint)}
    rect_ratio = poly.area / max(1e-6, poly.minimum_rotated_rectangle.area)
    hipped = m.get('roof') == 'hipped' or rect_ratio < 0.74
    # Which wall looks on the road gets the door.
    edges = [(ring[j], ring[(j + 1) % len(ring)]) for j in range(len(ring))]
    lengths = [math.dist(a, b_) for a, b_ in edges]
    front = min(range(len(edges)), key=lambda j: (road_edge.distance(Point((edges[j][0][0] + edges[j][1][0]) / 2, (edges[j][0][1] + edges[j][1][1]) / 2)) if lengths[j] > 3.2 else 1e9))
    others = unary_union([o['poly'] for o in buildings if o is not bld])
    for j, (a, b_) in enumerate(edges):
        length = lengths[j]
        mid = ((a[0] + b_[0]) / 2, (a[1] + b_[1]) / 2)
        d = ((b_[0] - a[0]) / length, (b_[1] - a[1]) / length) if length > 1e-6 else (1, 0)
        blocked = others.distance(Point(mid[0] + d[1] * 0.6, mid[1] - d[0] * 0.6)) < 0.3
        opens = []
        if length > 2.2 and not blocked and kind != 'outbuilding':
            bays = max(1, int(round(length / 2.9)))
            for bay in range(bays):
                s = (bay + 0.5) * length / bays
                if kind == 'church':
                    opens.append((s, 1.6, 0.95, 3.1, 'lancet'))
                    continue
                if j == front and bay == bays // 2:
                    opens.append((s, 0.02, 0.96, 2.32, 'door'))
                else:
                    opens.append((s, 0.85, 1.05, 1.3, 'window'))
                if eaves_h > 4.5:
                    opens.append((s, 3.45, 1.05, 1.2, 'window'))
        elif kind == 'outbuilding' and j == front and length > 2.4:
            opens.append((length / 2, 0.02, min(2.2, length - 0.8), 2.0, 'door'))
        facade(a, b_, base, eaves, floor, wall, tint, opens, trim)
        if j == front:
            FRONTS.append((a, b_, floor, m.get('name'), eaves))
    axis, top, last = roof(poly, eaves, ridge, hipped, r.choice(SLATE), wall, tint, i)
    # Chimneys at the ends of the ridge, with pots.
    if kind in ('house',) and not last.is_empty:
        lr = last.minimum_rotated_rectangle
        if lr.geom_type == 'Polygon':
            mid = np.array(lr.centroid.coords[0])
            run = max(1.0, math.sqrt(poly.minimum_rotated_rectangle.area) * 0.5)
            ends = [mid + axis * s for s in (-1, 1)]
            span = max(np.linalg.norm(np.subtract(p, mid)) for p in last.exterior.coords) if last.geom_type == 'Polygon' else 1
            for s in (-1, 1):
                if r.random() < 0.72:
                    p = mid + axis * s * max(0.2, span - 0.55)
                    yaw = math.atan2(axis[1], axis[0])
                    colour = (0.45, 0.24, 0.18) if r.random() < 0.5 else tint
                    cbox(batch('stone' if stone else 'brick'), (p[0], p[1], top + 0.1), (0.62, 0.95, 1.9), yaw, colour)
                    cbox(batch('matte'), (p[0], p[1], top + 1.08), (0.72, 1.05, 0.1), yaw, (0.35, 0.33, 0.31))
                    for o in (-0.25, 0.25):
                        q = p + np.array([-axis[1], axis[0]]) * o
                        cyl(batch('matte'), (q[0], q[1], top + 1.13), 0.105, 0.36, CLAY, n=10, top=0.085)
                    CHIMNEYS.append((float(p[0]), float(p[1]), top + 1.13))
    # A downpipe at one corner.
    a = ring[r.randrange(len(ring))]
    cyl(batch('matte'), (a[0], a[1], base), 0.045, eaves - base, (0.1, 0.1, 0.11), n=6)


for i, bld in enumerate(buildings):
    if bld['meta'].get('kind') != 'tower':
        house(bld, i)

# The church tower and its spire.
if tower_verts is not None:
    pts = [to_block(x, z) for x, z in tower_verts[:, [0, 2]].tolist()]
    sq = Polygon(pts).convex_hull.minimum_rotated_rectangle
    ring = rings(sq)[0]
    cx, cy = sq.centroid.coords[0]
    base = min(float(ground(x, y)) for x, y in ring) - 0.3
    floor = float(ground(cx, cy))
    stone = batch('stone')
    tint = (0.5, 0.45, 0.38)
    trim = {'frame': (0.25, 0.22, 0.2), 'door': (0.3, 0.2, 0.12), 'bars': 0, 'lintel': True, 'surround': None}
    for j in range(4):
        a, b_ = ring[j], ring[(j + 1) % 4]
        length = math.dist(a, b_)
        facade(a, b_, base, floor + 14.0, floor, stone, tint, [(length / 2, 9.6, 0.9, 2.6, 'louvre'), (length / 2, 4.2, 0.5, 1.8, 'lancet')], trim)
        # A clock on each face.
        d = ((b_[0] - a[0]) / length, (b_[1] - a[1]) / length)
        out = (d[1], -d[0])
        centre = ((a[0] + b_[0]) / 2 + out[0] * 0.04, (a[1] + b_[1]) / 2 + out[1] * 0.04, floor + 8.1)
        cyl(batch('matte'), centre, 0.85, 0.05, (0.1, 0.1, 0.12), n=28, axis=(out[0], out[1], 0))
        cyl(batch('matte'), (centre[0] + out[0] * 0.03, centre[1] + out[1] * 0.03, centre[2]), 0.74, 0.04, (0.93, 0.91, 0.84), n=28, axis=(out[0], out[1], 0))
        for ang, long_ in ((0.9, 0.6), (2.6, 0.42)):
            tip = (centre[0] + out[0] * 0.08 + d[0] * math.cos(ang) * long_ / 2, centre[1] + out[1] * 0.08 + d[1] * math.cos(ang) * long_ / 2, centre[2] + math.sin(ang) * long_ / 2)
            cyl(batch('matte'), (centre[0] + out[0] * 0.08, centre[1] + out[1] * 0.08, centre[2]), 0.03, long_, (0.05, 0.05, 0.06), n=6, axis=(d[0] * math.cos(ang), d[1] * math.cos(ang), math.sin(ang)))
    for ring_ in rings(sq.buffer(0.18, join_style=2)):
        prism(batch('stone'), ring_, floor + 13.9, floor + 14.25, tuple(c * 0.9 for c in tint))
    # The spire: eight sides, drawn in course by course like a roof, to its height in the map.
    for k in range(60):
        f = k / 60
        r_ = (1 - f) * math.dist(ring[0], ring[1]) / 2 * 1.02
        z = floor + 14.25 + f * 12.0
        cyl(batch('slate'), (cx, cy, z), r_, 0.22, tuple(c * (0.85 + 0.25 * random.Random(k).random()) for c in (0.3, 0.31, 0.33)), n=8, top=r_ - 0.02)
    cyl(batch('brass'), (cx, cy, floor + 26.2), 0.035, 1.3, (1, 1, 1), n=6)
    cbox(batch('brass'), (cx, cy, floor + 27.2), (0.7, 0.05, 0.05), 0.4, (1, 1, 1))

# ------------------------------------------------------------------------------------------------------------------
# Trees and bushes

t = np.fromfile(B + 'trees.bin', dtype=np.float32).reshape(-1, 11)  # x, z, height, crown radius, ..., ground
LEAF = [(0.16, 0.3, 0.09), (0.2, 0.34, 0.1), (0.13, 0.26, 0.09), (0.24, 0.36, 0.12), (0.18, 0.28, 0.07), (0.3, 0.38, 0.12)]
LEAFC = [(0.25, 0.4, 0.12), (0.3, 0.44, 0.14), (0.21, 0.35, 0.12), (0.34, 0.46, 0.16), (0.27, 0.38, 0.11), (0.38, 0.47, 0.17)]
bark, leaves = batch('bark'), batch('leaves', smooth=True)
SPRAYS = []  # where each spray of leaves goes: place, which way it faces, how big, which green
SPRAY = 0.5  # metres across half a spray


def foliage(centre, s, tint, seed, group):
    """A bough in leaf: a dark heart that no light gets through, and sprays of leaves all over its upper side."""
    blob(leaves, centre, (s * 0.7, s * 0.7, s * 0.58), tuple(c * 0.4 for c in tint), 0.2, seed)
    r_ = np.random.default_rng(seed)
    count = max(5, int(s * s * 13))
    d = r_.standard_normal((count, 3))
    d /= np.linalg.norm(d, axis=1)[:, None]
    d[:, 2] = np.abs(d[:, 2]) * 0.95 - 0.3  # few underneath, where nobody looks
    d /= np.linalg.norm(d, axis=1)[:, None]
    pos = np.asarray(centre) + d * np.array([s, s, s * 0.82]) * r_.uniform(0.72, 1.0, (count, 1))
    size = SPRAY * np.clip(s / 0.7, 0.7, 1.25) * r_.uniform(0.8, 1.25, count)
    SPRAYS.extend(np.c_[pos, d, size, np.full(count, group)].tolist())
for k, (x, z, h, rad, _, kind, *rest) in enumerate(t):
    X, Y = to_block(float(x), float(z))
    if not inside(X, Y) or taken.distance(Point(X, Y)) < 0.4:
        continue
    r = random.Random(k)
    g0 = float(ground(X, Y))
    h, rad = float(h), float(rad)
    gi = r.randrange(len(LEAF))
    green_ = LEAF[gi]
    if h < 5.5:  # a bush or a stretch of hedge
        wide = max(rad, h * 0.55)
        for i in range(max(3, int(wide * wide * 2.2))):
            a, d = r.random() * 6.28, wide * math.sqrt(r.random()) * 0.8
            s = wide * (0.28 + 0.25 * r.random())
            foliage((X + math.cos(a) * d, Y + math.sin(a) * d, g0 + h * (0.3 + 0.45 * r.random())), s, green_, k * 100 + i, gi)
        continue
    trunk = min(0.5, 0.12 + h * 0.022)
    lean = (r.random() - 0.5) * 0.12, (r.random() - 0.5) * 0.12
    cyl(bark, (X, Y, g0 - 0.2), trunk, h * 0.62, (0.2, 0.15, 0.1), n=9, top=trunk * 0.5, axis=(lean[0], lean[1], 1))
    crown_base, wide = h * (0.3 + 0.1 * r.random()), min(rad, h * 0.55)
    for i in range(4):  # boughs
        a = r.random() * 6.28
        start = np.array([X + lean[0] * h * 0.4, Y + lean[1] * h * 0.4, g0 + h * (0.32 + 0.08 * i)])
        cyl(bark, start, trunk * 0.4, wide * 0.8, (0.2, 0.15, 0.1), n=6, top=trunk * 0.12, axis=(math.cos(a), math.sin(a), 0.75))
    count = int(min(150, max(24, wide * wide * 9)))
    for i in range(count):
        # Sprays of leaf on the outside of the crown, darker ones within.
        a, up = r.random() * 6.28, r.random()
        shell = 0.45 + 0.55 * r.random() ** 0.4
        zz = crown_base + (h - crown_base) * (0.06 + 0.92 * up)
        girth = wide * math.sin(math.pi * (0.1 + 0.84 * up)) ** 0.7 * shell
        s = max(0.35, wide * (0.13 + 0.12 * r.random()))
        lit = (0.6 + 0.5 * up) * (0.7 + 0.5 * shell) + 0.15 * (r.random() - 0.5)
        foliage((X + math.cos(a) * girth, Y + math.sin(a) * girth, g0 + zz), s, green_, k * 100 + i, gi)

# ------------------------------------------------------------------------------------------------------------------
# Materials

def material(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes['Principled BSDF']
    return m, nt, bsdf


def node(nt, kind, **props):
    n_ = nt.nodes.new(kind)
    if kind.startswith('ShaderNodeTex') and kind not in ('ShaderNodeTexImage', 'ShaderNodeTexSky') and 'Vector' in n_.inputs:
        where = nt.nodes.get('where') or nt.nodes.new('ShaderNodeNewGeometry')
        where.name = 'where'
        nt.links.new(where.outputs['Position'], n_.inputs['Vector'])
    for k, v in props.items():
        if k.startswith('in_'):
            n_.inputs[int(k[3:])].default_value = v
        else:
            setattr(n_, k, v)
    return n_


def tinted(nt, bsdf, vary=0.0, scale=6.0):
    """Base colour from the colour on the vertices, with a little unevenness."""
    attr = node(nt, 'ShaderNodeAttribute', attribute_name='tint')
    if not vary:
        nt.links.new(attr.outputs['Color'], bsdf.inputs['Base Color'])
        return attr
    noise = node(nt, 'ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = scale
    noise.inputs['Detail'].default_value = 6
    ramp = node(nt, 'ShaderNodeMapRange')
    ramp.inputs[3].default_value, ramp.inputs[4].default_value = 1 - vary, 1 + vary
    nt.links.new(noise.outputs['Fac'], ramp.inputs[0])
    mix = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
    mix.inputs[0].default_value = 1
    nt.links.new(attr.outputs['Color'], mix.inputs[1])
    nt.links.new(ramp.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], bsdf.inputs['Base Color'])
    return mix


def bump(nt, bsdf, source, strength, distance=0.02):
    b = node(nt, 'ShaderNodeBump')
    b.inputs['Strength'].default_value = strength
    b.inputs['Distance'].default_value = distance
    nt.links.new(source, b.inputs['Height'])
    nt.links.new(b.outputs[0], bsdf.inputs['Normal'])
    return b


def weather(nt, bsdf, streaks, grime):
    """What rain and years do to a wall: streaks running down it, dirt gathered where surfaces meet."""
    base = bsdf.inputs['Base Color'].links[0].from_socket
    tall_ = node(nt, 'ShaderNodeMapping')
    tall_.inputs['Scale'].default_value = (2.6, 2.6, 0.1)
    nt.links.new(nt.nodes['where'].outputs['Position'], tall_.inputs[0])
    run = node(nt, 'ShaderNodeTexNoise')
    run.inputs['Scale'].default_value, run.inputs['Detail'].default_value = 1.0, 6
    nt.links.new(tall_.outputs[0], run.inputs[0])
    amt = node(nt, 'ShaderNodeMapRange')
    amt.inputs[1].default_value, amt.inputs[2].default_value, amt.inputs[3].default_value, amt.inputs[4].default_value = 0.56, 0.85, 0.0, streaks
    nt.links.new(run.outputs['Fac'], amt.inputs[0])
    patch = node(nt, 'ShaderNodeTexNoise')
    patch.inputs['Scale'].default_value = 0.45
    here = node(nt, 'ShaderNodeMapRange')
    here.inputs[1].default_value, here.inputs[2].default_value = 0.4, 0.65
    nt.links.new(patch.outputs['Fac'], here.inputs[0])
    some = node(nt, 'ShaderNodeMath', operation='MULTIPLY')
    nt.links.new(amt.outputs[0], some.inputs[0])
    nt.links.new(here.outputs[0], some.inputs[1])
    amt = some
    ao = node(nt, 'ShaderNodeAmbientOcclusion', samples=3)
    ao.inputs['Distance'].default_value = 0.9
    inv = node(nt, 'ShaderNodeMapRange')
    inv.inputs[1].default_value, inv.inputs[2].default_value, inv.inputs[3].default_value, inv.inputs[4].default_value = 0.35, 0.95, grime, 0.0
    nt.links.new(ao.outputs['AO'], inv.inputs[0])
    both = node(nt, 'ShaderNodeMath', operation='MAXIMUM')
    nt.links.new(amt.outputs[0], both.inputs[0])
    nt.links.new(inv.outputs[0], both.inputs[1])
    dirty = node(nt, 'ShaderNodeMixRGB')
    dirty.inputs[2].default_value = (0.09, 0.085, 0.07, 1)
    nt.links.new(both.outputs[0], dirty.inputs[0])
    nt.links.new(base, dirty.inputs[1])
    nt.links.new(dirty.outputs[0], bsdf.inputs['Base Color'])


MATS = {}

m, nt, bsdf = material('ground')
uv = node(nt, 'ShaderNodeAttribute', attribute_name='uvw')
img = node(nt, 'ShaderNodeTexImage', image=bpy.data.images.load(HERE + '/albedo.png'), interpolation='Cubic')
msk = node(nt, 'ShaderNodeTexImage', image=bpy.data.images.load(HERE + '/mask.png'), interpolation='Linear')
msk.image.colorspace_settings.name = 'Non-Color'
nt.links.new(uv.outputs['Vector'], img.inputs[0])
nt.links.new(uv.outputs['Vector'], msk.inputs[0])
fine = node(nt, 'ShaderNodeTexNoise')
fine.inputs['Scale'].default_value, fine.inputs['Detail'].default_value = 1.6, 12
grain = node(nt, 'ShaderNodeTexNoise')
grain.inputs['Scale'].default_value, grain.inputs['Detail'].default_value = 28.0, 6
vary = node(nt, 'ShaderNodeMapRange')
vary.inputs[3].default_value, vary.inputs[4].default_value = 0.72, 1.25
nt.links.new(fine.outputs['Fac'], vary.inputs[0])
earth = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
earth.inputs[0].default_value = 1
nt.links.new(img.outputs['Color'], earth.inputs[1])
nt.links.new(vary.outputs[0], earth.inputs[2])
sep = node(nt, 'ShaderNodeSeparateColor')
nt.links.new(msk.outputs['Color'], sep.inputs[0])
# Asphalt: near black, speckled with its stone; pavement: pale slabs; gravel: buff.
speck = node(nt, 'ShaderNodeMapRange')
speck.inputs[3].default_value, speck.inputs[4].default_value = 0.05, 0.17
nt.links.new(grain.outputs['Fac'], speck.inputs[0])
tar = node(nt, 'ShaderNodeCombineColor')
# A road is never one grey: it is patched and worn in lanes, and cracked where the frost has been at it.
worn = node(nt, 'ShaderNodeTexNoise')
worn.inputs['Scale'].default_value, worn.inputs['Detail'].default_value = 0.3, 4
wr = node(nt, 'ShaderNodeMapRange')
wr.inputs[1].default_value, wr.inputs[2].default_value, wr.inputs[3].default_value, wr.inputs[4].default_value = 0.3, 0.7, 0.72, 1.2
nt.links.new(worn.outputs['Fac'], wr.inputs[0])
split = node(nt, 'ShaderNodeTexVoronoi', feature='DISTANCE_TO_EDGE')
split.inputs['Scale'].default_value = 0.2
warp = node(nt, 'ShaderNodeTexNoise')
warp.inputs['Scale'].default_value = 1.5
bend_ = node(nt, 'ShaderNodeMixRGB', blend_type='ADD')
bend_.inputs[0].default_value = 0.6
nt.links.new(nt.nodes['where'].outputs['Position'], bend_.inputs[1])
nt.links.new(warp.outputs['Color'], bend_.inputs[2])
nt.links.new(bend_.outputs[0], split.inputs[0])
sr = node(nt, 'ShaderNodeMapRange')
sr.inputs[1].default_value, sr.inputs[2].default_value, sr.inputs[3].default_value, sr.inputs[4].default_value = 0.0, 0.004, 0.6, 1.0
nt.links.new(split.outputs['Distance'], sr.inputs[0])
t1 = node(nt, 'ShaderNodeMath', operation='MULTIPLY')
nt.links.new(speck.outputs[0], t1.inputs[0])
nt.links.new(wr.outputs[0], t1.inputs[1])
t2 = node(nt, 'ShaderNodeMath', operation='MULTIPLY')
nt.links.new(t1.outputs[0], t2.inputs[0])
nt.links.new(sr.outputs[0], t2.inputs[1])
for i in range(3):
    nt.links.new(t2.outputs[0], tar.inputs[i])
slab = node(nt, 'ShaderNodeTexBrick')
slab.inputs['Scale'].default_value, slab.inputs['Mortar Size'].default_value = 1.0, 0.012
slab.inputs['Color1'].default_value, slab.inputs['Color2'].default_value, slab.inputs['Mortar'].default_value = (0.45, 0.44, 0.42, 1), (0.52, 0.5, 0.47, 1), (0.22, 0.22, 0.21, 1)
slab.inputs['Brick Width'].default_value, slab.inputs['Row Height'].default_value = 0.9, 0.6
geo = node(nt, 'ShaderNodeNewGeometry')
nt.links.new(geo.outputs['Position'], slab.inputs[0])
grav = node(nt, 'ShaderNodeMapRange')
grav.inputs[3].default_value, grav.inputs[4].default_value = 0.32, 0.6
nt.links.new(grain.outputs['Fac'], grav.inputs[0])
buff = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
buff.inputs[0].default_value = 1
buff.inputs[1].default_value = (0.9, 0.82, 0.68, 1)
nt.links.new(grav.outputs[0], buff.inputs[2])
last = earth.outputs[0]
for chan, colour in (('Blue', buff.outputs[0]), ('Green', slab.outputs['Color']), ('Red', tar.outputs[0])):
    mix = node(nt, 'ShaderNodeMixRGB')
    nt.links.new(sep.outputs[chan], mix.inputs[0])
    nt.links.new(last, mix.inputs[1])
    nt.links.new(colour, mix.inputs[2])
    last = mix.outputs[0]
nt.links.new(last, bsdf.inputs['Base Color'])
bsdf.inputs['Roughness'].default_value = 0.92
bump(nt, bsdf, grain.outputs['Fac'], 0.35, 0.03)
MATS['ground'] = m

m, nt, bsdf = material('soil')
deep = node(nt, 'ShaderNodeAttribute', attribute_name='uvw')
sepd = node(nt, 'ShaderNodeSeparateXYZ')
nt.links.new(deep.outputs['Vector'], sepd.inputs[0])
wob = node(nt, 'ShaderNodeTexNoise')
wob.inputs['Scale'].default_value, wob.inputs['Detail'].default_value = 0.35, 5
depth = node(nt, 'ShaderNodeMath', operation='MULTIPLY_ADD')
depth.inputs[1].default_value = 1.4
nt.links.new(wob.outputs['Fac'], depth.inputs[0])
nt.links.new(sepd.outputs['X'], depth.inputs[2])
ramp = node(nt, 'ShaderNodeValToRGB')
els = ramp.color_ramp.elements
els[0].position, els[0].color = 0.0, (0.035, 0.024, 0.016, 1)
els[1].position, els[1].color = 1.0, (0.05, 0.046, 0.05, 1)
for pos_, colour in ((0.05, (0.04, 0.027, 0.017, 1)), (0.075, (0.2, 0.105, 0.045, 1)), (0.16, (0.17, 0.095, 0.045, 1)), (0.2, (0.085, 0.075, 0.075, 1))):
    e_ = els.new(pos_)
    e_.color = colour
scale_ = node(nt, 'ShaderNodeMath', operation='MULTIPLY')
scale_.inputs[1].default_value = 1 / 14
nt.links.new(depth.outputs[0], scale_.inputs[0])
nt.links.new(scale_.outputs[0], ramp.inputs[0])
tilt = node(nt, 'ShaderNodeMapping')
tilt.inputs['Rotation'].default_value, tilt.inputs['Scale'].default_value = (0.42, 0.3, 0.0), (0.16, 0.16, 1.5)
nt.links.new(nt.nodes['where'].outputs['Position'], tilt.inputs[0])
beds = node(nt, 'ShaderNodeTexVoronoi', feature='DISTANCE_TO_EDGE')
beds.inputs['Scale'].default_value = 1.6
nt.links.new(tilt.outputs[0], beds.inputs[0])
crack = node(nt, 'ShaderNodeMapRange')
crack.inputs[1].default_value, crack.inputs[2].default_value, crack.inputs[3].default_value, crack.inputs[4].default_value = 0.0, 0.1, 0.25, 1.0
nt.links.new(beds.outputs['Distance'], crack.inputs[0])
tone = node(nt, 'ShaderNodeTexVoronoi', feature='F1')
tone.inputs['Scale'].default_value = 1.6
nt.links.new(tilt.outputs[0], tone.inputs[0])
sept = node(nt, 'ShaderNodeSeparateColor')
nt.links.new(tone.outputs['Color'], sept.inputs[0])
tone2 = node(nt, 'ShaderNodeMapRange')
tone2.inputs[3].default_value, tone2.inputs[4].default_value = 0.5, 1.5
nt.links.new(sept.outputs['Red'], tone2.inputs[0])
both = node(nt, 'ShaderNodeMath', operation='MULTIPLY')
nt.links.new(crack.outputs[0], both.inputs[0])
nt.links.new(tone2.outputs[0], both.inputs[1])
grit = node(nt, 'ShaderNodeTexNoise')
grit.inputs['Scale'].default_value, grit.inputs['Detail'].default_value = 9.0, 8
grit2 = node(nt, 'ShaderNodeMapRange')
grit2.inputs[3].default_value, grit2.inputs[4].default_value = 0.6, 1.4
nt.links.new(grit.outputs['Fac'], grit2.inputs[0])
rock = node(nt, 'ShaderNodeMath', operation='GREATER_THAN')  # only the rock is cracked into beds
rock.inputs[1].default_value = 2.6
nt.links.new(depth.outputs[0], rock.inputs[0])
pick = node(nt, 'ShaderNodeMix')
nt.links.new(rock.outputs[0], pick.inputs[0])
nt.links.new(grit2.outputs[0], pick.inputs[2])
nt.links.new(both.outputs[0], pick.inputs[3])
mul = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
mul.inputs[0].default_value = 1
nt.links.new(ramp.outputs[0], mul.inputs[1])
nt.links.new(pick.outputs[0], mul.inputs[2])
nt.links.new(mul.outputs[0], bsdf.inputs['Base Color'])
bsdf.inputs['Roughness'].default_value = 0.95
bump(nt, bsdf, pick.outputs[0], 0.8, 0.08)
MATS['soil'] = m

for name, rough, vary_, scale in (('render', 0.86, 0.1, 2.5), ('matte', 0.8, 0.04, 8.0), ('gloss', 0.32, 0.0, 1), ('bark', 0.95, 0.25, 12.0), ('brick', 0.85, 0.15, 14.0)):
    m, nt, bsdf = material(name)
    tinted(nt, bsdf, vary_, scale)
    bsdf.inputs['Roughness'].default_value = rough
    if name in ('render', 'bark', 'brick'):
        n_ = node(nt, 'ShaderNodeTexNoise')
        n_.inputs['Scale'].default_value = 40 if name == 'render' else 18
        bump(nt, bsdf, n_.outputs['Fac'], 0.25 if name == 'render' else 0.8, 0.02)
    if name == 'render':
        weather(nt, bsdf, 0.3, 0.55)
    MATS[name] = m

m, nt, bsdf = material('stone')  # rubble walls: stones of uneven colour with mortar between
attr = node(nt, 'ShaderNodeAttribute', attribute_name='tint')
vor = node(nt, 'ShaderNodeTexVoronoi', feature='F1')
vor.inputs['Scale'].default_value = 3.4
edge = node(nt, 'ShaderNodeTexVoronoi', feature='DISTANCE_TO_EDGE')
edge.inputs['Scale'].default_value = 3.4
lay = node(nt, 'ShaderNodeMapping')
lay.inputs['Scale'].default_value = (1.0, 1.0, 1.9)
nt.links.new(nt.nodes['where'].outputs['Position'], lay.inputs[0])
nt.links.new(lay.outputs[0], vor.inputs[0])
nt.links.new(lay.outputs[0], edge.inputs[0])
ramp = node(nt, 'ShaderNodeMapRange')
ramp.inputs[1].default_value, ramp.inputs[2].default_value, ramp.inputs[3].default_value, ramp.inputs[4].default_value = 0.0, 0.06, 0.45, 1.0
nt.links.new(edge.outputs['Distance'], ramp.inputs[0])
sepc = node(nt, 'ShaderNodeSeparateColor')
nt.links.new(vor.outputs['Color'], sepc.inputs[0])
tone = node(nt, 'ShaderNodeMapRange')
tone.inputs[3].default_value, tone.inputs[4].default_value = 0.6, 1.35
nt.links.new(sepc.outputs['Red'], tone.inputs[0])
m1 = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
m1.inputs[0].default_value = 1
nt.links.new(attr.outputs['Color'], m1.inputs[1])
nt.links.new(tone.outputs[0], m1.inputs[2])
m2 = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
m2.inputs[0].default_value = 1
nt.links.new(m1.outputs[0], m2.inputs[1])
nt.links.new(ramp.outputs[0], m2.inputs[2])
rust = node(nt, 'ShaderNodeMapRange')
rust.inputs[1].default_value, rust.inputs[2].default_value, rust.inputs[3].default_value, rust.inputs[4].default_value = 0.55, 1.0, 0.0, 0.6
nt.links.new(sepc.outputs['Green'], rust.inputs[0])
m3 = node(nt, 'ShaderNodeMixRGB')
m3.inputs[2].default_value = (0.2, 0.11, 0.06, 1)
nt.links.new(rust.outputs[0], m3.inputs[0])
nt.links.new(m1.outputs[0], m3.inputs[1])
nt.links.new(m3.outputs[0], m2.inputs[1])
nt.links.new(m2.outputs[0], bsdf.inputs['Base Color'])
bsdf.inputs['Roughness'].default_value = 0.9
bump(nt, bsdf, ramp.outputs[0], 1.0, 0.05)
weather(nt, bsdf, 0.2, 0.5)
MATS['stone'] = m

m, nt, bsdf = material('slate')  # the slates along each course come from a brick pattern laid over the course
attr = node(nt, 'ShaderNodeAttribute', attribute_name='tint')
uvw = node(nt, 'ShaderNodeAttribute', attribute_name='uvw')
brick = node(nt, 'ShaderNodeTexBrick')
brick.inputs['Scale'].default_value, brick.inputs['Mortar Size'].default_value = 1.0, 0.007
brick.inputs['Brick Width'].default_value, brick.inputs['Row Height'].default_value = 0.3, 1.0
brick.inputs['Color1'].default_value, brick.inputs['Color2'].default_value, brick.inputs['Mortar'].default_value = (0.7, 0.71, 0.74, 1), (1.22, 1.2, 1.16, 1), (0.25, 0.25, 0.25, 1)
nt.links.new(uvw.outputs['Vector'], brick.inputs[0])
mix = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
mix.inputs[0].default_value = 1
nt.links.new(attr.outputs['Color'], mix.inputs[1])
nt.links.new(brick.outputs['Color'], mix.inputs[2])
mottle = node(nt, 'ShaderNodeTexNoise')
mottle.inputs['Scale'].default_value, mottle.inputs['Detail'].default_value = 5.0, 8
mr = node(nt, 'ShaderNodeMapRange')
mr.inputs[3].default_value, mr.inputs[4].default_value = 0.78, 1.22
nt.links.new(mottle.outputs['Fac'], mr.inputs[0])
mix1 = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
mix1.inputs[0].default_value = 1
nt.links.new(mix.outputs[0], mix1.inputs[1])
nt.links.new(mr.outputs[0], mix1.inputs[2])
lichen = node(nt, 'ShaderNodeTexNoise')
lichen.inputs['Scale'].default_value, lichen.inputs['Detail'].default_value = 2.2, 10
lichen.inputs['Roughness'].default_value = 0.75
lr_ = node(nt, 'ShaderNodeMapRange')
lr_.inputs[1].default_value, lr_.inputs[2].default_value, lr_.inputs[3].default_value, lr_.inputs[4].default_value = 0.6, 0.72, 0.0, 0.6
nt.links.new(lichen.outputs['Fac'], lr_.inputs[0])
mix2 = node(nt, 'ShaderNodeMixRGB')
mix2.inputs[2].default_value = (0.36, 0.3, 0.1, 1)
nt.links.new(lr_.outputs[0], mix2.inputs[0])
nt.links.new(mix1.outputs[0], mix2.inputs[1])
nt.links.new(mix2.outputs[0], bsdf.inputs['Base Color'])
bsdf.inputs['Roughness'].default_value = 0.42
bump(nt, bsdf, brick.outputs['Fac'], 0.6, 0.01).invert = True
MATS['slate'] = m

m, nt, bsdf = material('glass')  # a window from outside by day: dark, with the sky in it
bsdf.inputs['Base Color'].default_value = (0.015, 0.02, 0.025, 1)
bsdf.inputs['Roughness'].default_value = 0.04
bsdf.inputs['Specular IOR Level'].default_value = 1.0
MATS['glass'] = m

m, nt, bsdf = material('brass')
bsdf.inputs['Base Color'].default_value = (0.8, 0.6, 0.25, 1)
bsdf.inputs['Metallic'].default_value = 1.0
bsdf.inputs['Roughness'].default_value = 0.3
MATS['brass'] = m

m, nt, bsdf = material('leaves')
col = tinted(nt, bsdf, 0.35, 11.0)
bsdf.inputs['Roughness'].default_value = 0.6
leafy = node(nt, 'ShaderNodeTexVoronoi', feature='F1')
leafy.inputs['Scale'].default_value = 16.0
bump(nt, bsdf, leafy.outputs['Distance'], 1.0, 0.1)
try:
    bsdf.inputs['Subsurface Weight'].default_value = 0.15
    bsdf.inputs['Subsurface Radius'].default_value = (0.3, 0.6, 0.15)
except Exception:  # noqa: BLE001
    pass
MATS['leaves'] = m

def leaf_material(colour):
    m, nt, bsdf = material('leaf')
    info = node(nt, 'ShaderNodeObjectInfo')
    own = node(nt, 'ShaderNodeAttribute', attribute_name='tint')
    each = node(nt, 'ShaderNodeMapRange')
    each.inputs[3].default_value, each.inputs[4].default_value = 0.72, 1.28
    nt.links.new(info.outputs['Random'], each.inputs[0])
    c1 = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
    c1.inputs[0].default_value = 1
    c1.inputs[1].default_value = (*[c ** 2.2 for c in colour], 1)
    nt.links.new(own.outputs['Color'], c1.inputs[2])
    c2 = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
    c2.inputs[0].default_value = 1
    nt.links.new(c1.outputs[0], c2.inputs[1])
    nt.links.new(each.outputs[0], c2.inputs[2])
    nt.links.new(c2.outputs[0], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.38
    through = node(nt, 'ShaderNodeBsdfTranslucent')
    glow = node(nt, 'ShaderNodeMixRGB', blend_type='MULTIPLY')
    glow.inputs[0].default_value = 1
    glow.inputs[2].default_value = (1.5, 1.9, 0.7, 1)
    nt.links.new(c2.outputs[0], glow.inputs[1])
    nt.links.new(glow.outputs[0], through.inputs['Color'])
    both_ = node(nt, 'ShaderNodeMixShader')
    both_.inputs[0].default_value = 0.35
    nt.links.new(bsdf.outputs[0], both_.inputs[1])
    nt.links.new(through.outputs[0], both_.inputs[2])
    nt.links.new(both_.outputs[0], next(n_ for n_ in nt.nodes if n_.type == 'OUTPUT_MATERIAL').inputs['Surface'])
    return m


def spray_mesh(seed, colour, leaves_=170):
    """A spray of leaves a metre across (it is scaled where it is used): each leaf two triangles folded along its rib."""
    r_ = np.random.default_rng(seed)
    d = r_.standard_normal((leaves_, 3))
    d /= np.linalg.norm(d, axis=1)[:, None]
    d[:, 2] = np.abs(d[:, 2]) * 0.8 - 0.15
    at_ = d * r_.uniform(0.25, 1.0, (leaves_, 1)) ** 0.6 * np.array([1.0, 1.0, 0.55])
    out = d + r_.standard_normal((leaves_, 3)) * 0.5 + np.array([0, 0, -0.35])  # ribs point outward and droop a little
    out /= np.linalg.norm(out, axis=1)[:, None]
    face = np.array([0, 0, 1.0]) + d * 0.5 + r_.standard_normal((leaves_, 3)) * 0.45  # blades face the sky, more or less
    side = np.cross(face, out)
    side /= np.linalg.norm(side, axis=1)[:, None]
    face = np.cross(out, side)
    long_, wide_ = r_.uniform(0.17, 0.26, (leaves_, 1)), r_.uniform(0.09, 0.14, (leaves_, 1))
    base, tip = at_, at_ + out * long_
    mid_ = at_ + out * long_ * 0.45 - face * wide_ * 0.18
    left, right = mid_ + side * wide_ * 0.5 + face * wide_ * 0.2, mid_ - side * wide_ * 0.5 + face * wide_ * 0.2
    verts = np.stack([base, right, tip, left], 1).reshape(-1, 3)
    faces = [f for i in range(0, leaves_ * 4, 4) for f in ((i, i + 1, i + 2), (i, i + 2, i + 3))]
    mesh = bpy.data.meshes.new('spray')
    mesh.from_pydata(verts.tolist(), [], faces)
    shade = r_.uniform(0.7, 1.25, (leaves_, 1)) * np.array([1.0, 1.0, 1.0]) + r_.uniform(0, 0.25, (leaves_, 1)) * np.array([1.0, 0.5, 0.0])
    tint = mesh.attributes.new('tint', 'FLOAT_COLOR', 'POINT')
    tint.data.foreach_set('color', np.c_[np.repeat(shade, 4, axis=0), np.ones(leaves_ * 4)].astype(np.float32).ravel())
    mesh.materials.append(leaf_material(colour))
    return mesh


# ------------------------------------------------------------------------------------------------------------------
# Details, in files of their own so this one stays readable

exec(compile(open(SRC + '/details.py').read(), SRC + '/details.py', 'exec'))
if os.path.exists(f"{SRC}/scenes/{PLACE['id']}.py"):
    exec(compile(open(f"{SRC}/scenes/{PLACE['id']}.py").read(), f"{SRC}/scenes/{PLACE['id']}.py", 'exec'))

# ------------------------------------------------------------------------------------------------------------------
# Meshes

scene = bpy.context.scene
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
LOW = ('ground', 'soil', 'grass', 'paint')  # what lies flat: the map's cars and walkers are never hidden behind these
for name, b in BATCH.items():
    if not len(b.v):
        continue
    mesh = bpy.data.meshes.new(name)
    if isinstance(b.v, np.ndarray):
        count = len(b.v)
        mesh.vertices.add(count)
        mesh.loops.add(count)
        mesh.polygons.add(count // 3)
        mesh.vertices.foreach_set('co', b.v.astype(np.float32).ravel())
        mesh.loops.foreach_set('vertex_index', np.arange(count, dtype=np.int32))
        mesh.polygons.foreach_set('loop_start', np.arange(0, count, 3, dtype=np.int32))
        mesh.update(calc_edges=True)
    else:
        mesh.from_pydata(b.v, [], b.f)
    tint = mesh.attributes.new('tint', 'FLOAT_COLOR', 'POINT')
    # The colours above are written as they look on a screen; the renderer works with light, so they are made linear.
    tint.data.foreach_set('color', np.c_[np.power(np.clip(np.asarray(b.tint, np.float32), 0, 4), 2.2), np.ones(len(b.v), np.float32)].ravel())
    uvw = mesh.attributes.new('uvw', 'FLOAT2', 'POINT')
    if len(b.uvw):
        uvw.data.foreach_set('vector', np.asarray(b.uvw, np.float32).ravel())
    if b.smooth:
        mesh.polygons.foreach_set('use_smooth', [True] * len(mesh.polygons))
    mesh.materials.append(MATS.get(name, MATS['matte']))
    ob = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(ob)
    print(f'{name}: {len(b.v)} points')

if SPRAYS:
    arr = np.asarray(SPRAYS)
    r_ = np.random.default_rng(1)
    for gi_ in range(len(LEAFC)):
        sel = arr[arr[:, 7] == gi_]
        if not len(sel):
            continue
        pos, nrm, sz = sel[:, :3], sel[:, 3:6], sel[:, 6:7]
        ref = np.where(np.abs(nrm[:, 2:3]) < 0.9, np.array([[0, 0, 1.0]]), np.array([[1.0, 0, 0]]))
        u_ = np.cross(nrm, ref)
        u_ /= np.linalg.norm(u_, axis=1)[:, None]
        v_ = np.cross(nrm, u_)
        spin = r_.uniform(0, 6.283, (len(sel), 1))
        # A triangle whose area is the square of the size wanted: that is the scale the spray is drawn at.
        corners = [pos + 0.8774 * sz * (np.cos(spin + q * 2.0944) * u_ + np.sin(spin + q * 2.0944) * v_) for q in range(3)]
        mesh = bpy.data.meshes.new('places')
        mesh.from_pydata(np.stack(corners, 1).reshape(-1, 3).tolist(), [], [(i, i + 1, i + 2) for i in range(0, len(sel) * 3, 3)])
        where_ = bpy.data.objects.new(f'places{gi_}', mesh)
        scene.collection.objects.link(where_)
        where_.instance_type, where_.use_instance_faces_scale, where_.instance_faces_scale = 'FACES', True, 1.0
        where_.show_instancer_for_render = where_.show_instancer_for_viewport = False
        spray = bpy.data.objects.new(f'spray{gi_}', spray_mesh(gi_, LEAFC[gi_]))
        scene.collection.objects.link(spray)
        spray.parent = where_
    print(len(arr), 'sprays of leaves')

# ------------------------------------------------------------------------------------------------------------------
# Light: the sky, and the sun where it stands on the map, so that shadows here agree with the shadows around

world = bpy.data.worlds.new('sky')
scene.world = world
world.use_nodes = True
nt = world.node_tree
bg = nt.nodes['Background']
sky = nt.nodes.new('ShaderNodeTexSky')
sky.sky_type = 'MULTIPLE_SCATTERING'
az_, el_ = [float(q) for q in arg('sun', f'{SUN_AZIMUTH},{SUN_ELEVATION}').split(',')]
SUN_AZ, SUN_EL = math.radians(az_), math.radians(el_)
sky.sun_elevation, sky.sun_rotation = SUN_EL, SUN_AZ
try:
    sky.sun_disc = False
except Exception:  # noqa: BLE001
    pass
nt.links.new(sky.outputs[0], bg.inputs[0])
bg.inputs['Strength'].default_value = 0.3
# Where the camera sees past the land it sees the dark of the map's own background, not the sky.
dark = nt.nodes.new('ShaderNodeBackground')
dark.inputs[0].default_value = (0.0144, 0.0176, 0.0252, 1)
path = nt.nodes.new('ShaderNodeLightPath')
mix = nt.nodes.new('ShaderNodeMixShader')
nt.links.new(path.outputs['Is Camera Ray'], mix.inputs[0])
nt.links.new(bg.outputs[0], mix.inputs[1])
nt.links.new(dark.outputs[0], mix.inputs[2])
nt.links.new(mix.outputs[0], nt.nodes['World Output'].inputs[0])

sun = bpy.data.lights.new('sun', 'SUN')
low_sun = max(0.0, min(1.0, (40 - el_) / 20))  # the lower the sun, the warmer its light
sun.energy, sun.angle, sun.color = 4.4, math.radians(1.6), (1.0, 0.95 - 0.05 * low_sun, 0.86 - 0.1 * low_sun)
so = bpy.data.objects.new('sun', sun)
scene.collection.objects.link(so)
# Azimuth is clockwise from north (north is +Y, east is +X); the lamp shines down its own -Z.
to_sun = Vector((math.sin(SUN_AZ) * math.cos(SUN_EL), math.cos(SUN_AZ) * math.cos(SUN_EL), math.sin(SUN_EL)))
so.rotation_euler = to_sun.to_track_quat('Z', 'Y').to_euler()

# ------------------------------------------------------------------------------------------------------------------
# The camera: the map's own, thirty degrees down and without perspective, so a metre is as wide anywhere in the picture

cam = bpy.data.cameras.new('camera')
co = bpy.data.objects.new('camera', cam)
scene.collection.objects.link(co)
scene.camera = co
cam.type = 'ORTHO'
co.rotation_euler = (math.radians(60), 0, math.radians(-LOOK))
look = Vector((COS30 * LS, COS30 * LC, -0.5))
cam.clip_start, cam.clip_end = 1, 3000


def aim(px, py, w, h):
    """Point the camera at a rectangle of the picture, given in the picture's pixels from its top left corner."""
    u, v = U0 + (px + w / 2) * FW / PW, V1 - (py + h / 2) * FH / PH
    X, Y = to_block(*unscreen(u, v, H_AT))
    co.location = Vector((X, Y, H_AT - Z0)) - look * 900
    cam.ortho_scale = max(w, h) * FW / PW
    scene.render.resolution_x, scene.render.resolution_y = w, h


# A graphics card can give up in the middle of a render; on a Mac it does so the first time it is used, while its
# programs are still being made ready, and when the scene changes under it. Nothing rendered is lost, since every
# chunk is a file, so the run then starts afresh: once more the same way, then without the card's ray tracing
# hardware and tuned programs, then on the processor. ATTEMPT counts those fresh starts.
ATTEMPT = int(os.environ.get('DEEP_ATTEMPT', '0'))
# The masks of what stands up are quick to render and go on the processor, in a run of their own after the picture:
# changing the whole scene under a graphics card that has just rendered it is what made it give up.
ONLY_MASKS = MODE == 'tiles' and all(os.path.exists(f'{WORK}/chunks-{SCALE}/{cx}_{row}.png') for cx, row in todo)


def device(want):
    """Render on a graphics card when there is one: many times faster than on the processor alone."""
    if ONLY_MASKS:
        return 'CPU', f'the processor, {os.cpu_count()} threads: the picture is rendered, only the masks are left, and they are quick'
    if want != 'cpu' and ATTEMPT < 3:
        try:
            prefs = bpy.context.preferences.addons['cycles'].preferences
            for kind in ('METAL', 'OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
                try:
                    prefs.compute_device_type = kind
                    prefs.refresh_devices()
                except Exception:  # noqa: BLE001
                    continue
                cards = [d for d in prefs.devices if d.type == kind]
                if cards:
                    for d in prefs.devices:
                        d.use = d.type == kind
                    plain = ''
                    if kind == 'METAL' and ATTEMPT == 2:
                        prefs.metalrt, prefs.kernel_optimization_level, plain = 'OFF', 'OFF', ', without its ray tracing hardware and tuned programs'
                    return 'GPU', f"{kind.lower()}: {', '.join(d.name for d in cards)}{plain}"
            prefs.compute_device_type = 'NONE'
        except Exception as e:  # noqa: BLE001
            print('no graphics card to render on:', e)
    if want == 'gpu':
        sys.exit('--device gpu was asked for, and there is no graphics card that will render this')
    return 'CPU', f'the processor, {os.cpu_count()} threads'


def afresh(why=None):
    """Start this same run again from the top, in place of this one. What is rendered already is kept."""
    env = dict(os.environ)
    if why is not None:
        how = ('the same way', 'without its ray tracing hardware and tuned programs', 'on the processor')[min(2, ATTEMPT)]
        print(f"the graphics card gave up ({str(why).strip().splitlines()[0][:100]}). Nothing is lost: starting again, {how}.", flush=True)
        env['DEEP_ATTEMPT'] = str(ATTEMPT + 1)
    sys.stdout.flush()
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


scene.render.engine = 'CYCLES'
cy = scene.cycles
cy.device, using = device(arg('device', 'auto'))
print('rendering on', using)
cy.samples = SAMPLES
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.02
cy.use_denoising = True
cy.denoiser = 'OPENIMAGEDENOISE'
cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces, cy.transmission_bounces = 5, 3, 3, 2
scene.render.use_persistent_data = True  # the scene is handed to the renderer once, not again for every chunk
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = 'AgX'
try:
    scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception:  # noqa: BLE001
    pass
scene.view_settings.exposure = float(arg('exposure', '0.3'))
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'


def shot(path):
    scene.render.filepath = path
    t0 = time.time()
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as e:
        if cy.device != 'GPU':
            raise
        afresh(e)
    return time.time() - t0


if MODE != 'tiles':
    # One picture. --blur gives it the shallow focus of a photograph of a model.
    blur = float(arg('blur', '0'))
    if blur:
        cam.dof.use_dof, cam.dof.focus_distance = True, 900
        cam.lens = 5000  # only sets the size of the opening: a camera without perspective has no focal length
        cam.dof.aperture_fstop = 5.0 / (2 * blur * FW / 100)
    aim(0, 0, PW, PH)
    out = os.path.abspath(arg('picture', WORK + '/try.png'))
    took = shot(out)
    rate = PW * PH / 1e6 / took * 60
    print(f'{out}: {took:.0f} s for {PW * PH / 1e6:.1f} megapixels, {rate:.1f} megapixels a minute')
    if MODE == 'try':
        whole = PLACE['size'][0] * PLACE['size'][1] * SCALE * SCALE / 1e6
        print(f"at that rate all of {PLACE['name']} ({whole:.0f} megapixels at {SCALE} pixels a metre) takes about {whole / rate:.0f} minutes")
    sys.exit()

# ------------------------------------------------------------------------------------------------------------------
# The place as tiles: rendered in chunks, each a file of its own so that a render cut short goes on where it stopped;
# then once more as a mask of everything that stands up, for the layer the viewer draws over its cars and walkers.



def chunk(cx, cy, path, mode):
    w, h = min(CHUNK, PW - cx * CHUNK), min(CHUNK, PH - cy * CHUNK)
    aim(cx * CHUNK - EDGE, cy * CHUNK - EDGE, w + 2 * EDGE, h + 2 * EDGE)
    took = shot(HERE + '/chunk.png')
    img = Image.open(HERE + '/chunk.png').crop((EDGE, EDGE, EDGE + w, EDGE + h))
    (img.getchannel('A') if mode == 'L' else img.convert('RGB')).save(path + '.part', 'PNG')
    os.replace(path + '.part', path)
    return took, w * h


t0, done = time.time(), 0
for i, (cx, cy_) in enumerate(todo):
    path = f'{WORK}/chunks-{SCALE}/{cx}_{cy_}.png'
    if os.path.exists(path):
        continue
    took, pixels = chunk(cx, cy_, path, 'RGB')
    done += pixels
    left = sum(min(CHUNK, PW - x * CHUNK) * min(CHUNK, PH - y * CHUNK) for x, y in todo[i + 1:] if not os.path.exists(f'{WORK}/chunks-{SCALE}/{x}_{y}.png'))
    print(f'chunk {cx},{cy_}: {took:.0f} s; about {left / max(1, done) * (time.time() - t0) / 60:.0f} minutes to go', flush=True)

if cy.device == 'GPU':
    print('the picture is rendered; now the masks of what stands up, on the processor', flush=True)
    afresh()  # this run again: it finds the picture done and goes on the processor (ONLY_MASKS)

scene.render.film_transparent = True
scene.render.image_settings.color_mode = 'RGBA'
white = bpy.data.materials.new('white')
white.use_nodes = True
glow_ = white.node_tree.nodes.new('ShaderNodeEmission')
white.node_tree.links.new(glow_.outputs[0], next(n_ for n_ in white.node_tree.nodes if n_.type == 'OUTPUT_MATERIAL').inputs['Surface'])
bpy.context.view_layer.material_override = white
for ob in scene.objects:
    ob.is_holdout = ob.name in LOW
cy.samples, cy.use_adaptive_sampling, cy.use_denoising = 8, False, False
for cx, cy_ in todo:
    path = f'{WORK}/chunks-{SCALE}/{cx}_{cy_}_mask.png'
    if not os.path.exists(path):
        chunk(cx, cy_, path, 'L')
print('masks done', flush=True)

cut_tiles()
