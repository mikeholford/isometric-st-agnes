# The small things, all made up by rule: grass, flowers, stone hedges, gravestones round a church, paint on the road,
# kerbs, lamps, tubs by front doors, bins, aerials, washing. And the makers of things that are put somewhere by hand
# in deep/scenes/: a phone box, a bench, a person, a car, the giant.
#
# Nothing that moves is in the tiles: a deep place is a ghost town, and the viewer brings the life. A car frozen at
# the kerb or a sheep that never lifts its head looks wrong beside traffic that drives. So the parked cars, the
# sheep and the gulls are only put in with --movers, for a picture. Their rules still roll the dice either way, so
# that every tub and bin stands where it stood before.
# Run from scene.py, in its namespace.

G = lambda x, y: float(ground(x, y))


def along_line(line, step, start=0.0):
    """A point every `step` metres along a line: x, y, the way it runs, and how far along."""
    out, d = [], start
    while d < line.length:
        p, q = line.interpolate(d), line.interpolate(min(line.length, d + 0.4))
        dx, dy = q.x - p.x, q.y - p.y
        n_ = math.hypot(dx, dy) or 1.0
        out.append((p.x, p.y, dx / n_, dy / n_, d))
        d += step
    return out


# Where nothing may grow or stand: roads, pavements, buildings. A picture at 25 cm, for quick asking.
bm = Image.new('L', (int(2 * HALF * 4),) * 2, 0)
bd = ImageDraw.Draw(bm)
for geom in (asphalt, paved, gravel, pavement, taken.buffer(0.15)):
    for ring in rings(geom):
        bd.polygon([((x + HALF) / 0.25, (HALF - y) / 0.25) for x, y in ring], fill=255)
blocked = np.asarray(bm) > 0
free = lambda x, y: abs(x) < HALF - 0.3 and abs(y) < HALF - 0.3 and not blocked[int((HALF - y) / 0.25), int((x + HALF) / 0.25)]

# ---- Grass: four blades to a tuft, sixty tufts to the square metre, in the colour of the ground they stand on.
# Only where the picture shows it. There are millions of blades, so they are kept in arrays from start to finish.
rng = np.random.default_rng(3)
N = int((2 * HALF - 0.6) ** 2 * float(arg('grass', '60')))
gx_, gy_ = rng.uniform(-HALF + 0.3, HALF - 0.3, N), rng.uniform(-HALF + 0.3, HALF - 0.3, N)
gz_ = ground(gx_, gy_)
ok = in_picture(gx_, gy_, gz_, 0.5) & ~blocked[((HALF - gy_) / 0.25).astype(int), ((gx_ + HALF) / 0.25).astype(int)]
gx_, gy_, gz_ = gx_[ok], gy_[ok], gz_[ok]
gcol = alb[np.clip((HALF - gy_).astype(int), 0, N1), np.clip((gx_ + HALF).astype(int), 0, N1)] / 255
T = len(gx_)
tall = np.where(rng.random(T) < 0.13, 2.3, 1.0)
verts, tints = [], []
for blade in range(4):
    a = rng.uniform(0, 6.283, T)
    lean, high, wide = rng.uniform(0.0, 0.09, T) * tall, rng.uniform(0.1, 0.26, T) * tall, rng.uniform(0.018, 0.035, T)
    ox, oy = np.cos(a) * 0.035, np.sin(a) * 0.035
    p0 = np.stack([gx_ + ox - np.sin(a) * wide, gy_ + oy + np.cos(a) * wide, gz_ - 0.02], 1)
    p1 = np.stack([gx_ + ox + np.sin(a) * wide, gy_ + oy - np.cos(a) * wide, gz_ - 0.02], 1)
    tip = np.stack([gx_ + ox + np.cos(a) * lean, gy_ + oy + np.sin(a) * lean, gz_ + high], 1)
    verts.append(np.stack([p0, p1, tip], 1).reshape(-1, 3))
    shade = rng.uniform(0.75, 1.2, T)[:, None]
    low, top_ = gcol * shade * 0.7, np.clip(gcol * shade * 1.3 + np.array([0.05, 0.06, 0.0]), 0, 1)
    tints.append(np.stack([low, low, top_], 1).reshape(-1, 3))
gb = batch('grass')
gb.v, gb.tint = np.concatenate(verts), np.concatenate(tints)
del verts, tints
print(T, 'tufts of grass')

# ---- Flowers in the grass: daisies, buttercups, a few poppies.
fl = batch('paint')
for i in range(T // 150):
    k = rng.integers(0, T)
    x, y, z = float(gx_[k]) + rng.uniform(-0.3, 0.3), float(gy_[k]) + rng.uniform(-0.3, 0.3), float(gz_[k])
    kind = rng.random()
    colour, r_ = ((0.96, 0.96, 0.92), 0.04) if kind < 0.6 else ((0.95, 0.82, 0.1), 0.032) if kind < 0.9 else ((0.8, 0.1, 0.08), 0.05)
    h_ = 0.1 + 0.12 * rng.random()
    cyl(fl, (x, y, z + h_), r_, 0.008, colour, n=6)
    if kind < 0.6:
        cyl(fl, (x, y, z + h_ + 0.008), r_ * 0.4, 0.006, (0.95, 0.8, 0.1), n=5)

# ---- Stone hedges along the lanes: a bank faced with stone, as high as a hip, with gaps for gates.
stone = batch('stone')
keep_off = unary_union([taken.buffer(2.0), road_edge.buffer(0.3), pavement.buffer(0.05)])
for r_ in roads:
    if r_['hw'] not in ('secondary', 'residential', 'unclassified', 'tertiary'):
        continue
    off = r_['half'] + (1.7 if r_['hw'] == 'secondary' else 0.5)
    for side in ('left', 'right'):
        try:
            ln = r_['line'].parallel_offset(off, side, join_style=2).intersection(BLOCK.buffer(-0.6)).difference(keep_off)
        except Exception:  # noqa: BLE001
            continue
        for part in getattr(ln, 'geoms', [ln]):
            if part.geom_type != 'LineString' or part.length < 3.5:
                continue
            tint = rnd.choice(STONE)
            for x, y, dx, dy, d in along_line(part, 0.55):
                if d % 26 < 1.4:  # a gateway
                    continue
                post = d % 26 < 2.0 or d % 26 > 25.4
                h_ = 1.35 if post else 0.95 + 0.08 * rnd.random()
                yaw = math.atan2(dy, dx)
                z = G(x, y)
                cbox(stone, (x, y, z + h_ / 2 - 0.2), (0.6, 0.5 if post else 0.44, h_ + 0.4), yaw, tint)
                cbox(stone, (x, y, z + h_ + 0.04), (0.6, 0.56, 0.09), yaw + (rnd.random() - 0.5) * 0.3, tuple(c * 0.85 for c in tint))
                if rnd.random() < 0.28 and not post:
                    s_ = 0.16 + 0.14 * rnd.random()
                    blob(batch('leaves'), (x, y, z + h_ + 0.1), (s_ * 1.3, s_ * 1.3, s_), tuple(c * (0.8 + 0.5 * rnd.random()) for c in (0.18, 0.32, 0.1)), 0.3, int(d * 10))

# ---- The churchyard: headstones in rows, square to the church, a few crosses and chest tombs.
church = next((b['poly'] for b in buildings if b['meta'].get('kind') == 'church'), None)
if church is not None:
    yard = church.buffer(26).difference(road_edge.buffer(2.2)).difference(taken.difference(church.buffer(0.5)).buffer(1.6)).intersection(BLOCK.buffer(-2))
    yard = unary_union([g for g in getattr(yard, 'geoms', [yard]) if g.intersects(church)]).difference(church.buffer(2.4))  # not across the road
    rc = list(church.minimum_rotated_rectangle.exterior.coords)
    e0, e1 = np.subtract(rc[1], rc[0]), np.subtract(rc[2], rc[1])
    ax_ = e0 if np.linalg.norm(e0) > np.linalg.norm(e1) else e1
    ax_ = ax_ / np.linalg.norm(ax_)
    pp = np.array([-ax_[1], ax_[0]])
    cc_ = np.array(church.centroid.coords[0])
    yaw0 = math.atan2(ax_[1], ax_[0])
    mt = batch('matte')
    for u in np.arange(-36, 36, 2.3):
        for v in np.arange(-36, 36, 3.1):
            p = cc_ + ax_ * (u + rnd.uniform(-0.3, 0.3)) + pp * (v + rnd.uniform(-0.2, 0.2))
            if rnd.random() > 0.66 or not yard.contains(Point(p)) or not free(p[0], p[1]):
                continue
            z, grey = G(p[0], p[1]), rnd.uniform(0.38, 0.62)
            tint = (grey, grey * 0.98, grey * (0.9 + 0.12 * rnd.random()))
            yaw = yaw0 + math.pi / 2 + rnd.uniform(-0.12, 0.12)
            sort = rnd.random()
            if sort < 0.72:
                h_ = rnd.uniform(0.6, 1.15)
                cbox(mt, (p[0], p[1], z + h_ / 2 - 0.1), (0.56, 0.11, h_ + 0.2), yaw, tint)
                cyl(mt, (p[0] - math.sin(yaw) * -0.055, p[1] + math.cos(yaw) * -0.055, z + h_), 0.28, 0.11, tint, n=14, axis=(-math.sin(yaw), math.cos(yaw), 0))
            elif sort < 0.88:
                cbox(mt, (p[0], p[1], z + 0.65), (0.17, 0.13, 1.5), yaw, tint)
                cbox(mt, (p[0], p[1], z + 1.0), (0.66, 0.13, 0.17), yaw, tint)
                cbox(mt, (p[0], p[1], z + 0.06), (0.5, 0.4, 0.2), yaw, tint)
            else:
                cbox(mt, (p[0], p[1], z + 0.25), (0.85, 1.9, 0.6), yaw, tint)
                cbox(mt, (p[0], p[1], z + 0.59), (0.98, 2.04, 0.09), yaw, tuple(c * 0.9 for c in tint))
            if rnd.random() < 0.2:
                for _ in range(4):
                    blob(mt, (p[0] + rnd.uniform(-0.25, 0.25), p[1] + rnd.uniform(-0.25, 0.25) - 0.3, z + 0.1), (0.06, 0.06, 0.06), rnd.choice([(0.9, 0.2, 0.3), (0.95, 0.85, 0.2), (0.6, 0.3, 0.8), (0.95, 0.95, 0.95)]), 0, _)

# ---- Paint on the road, kerbs, drains.
mt, flat = batch('matte'), batch('paint')


def strip(x0, y0, x1, y1, w_, colour, lift=0.03):
    """A painted line on the ground from one spot to another, so many metres to each side."""
    n_ = math.dist((x0, y0), (x1, y1))
    sx, sy = -(y1 - y0) / n_ * w_, (x1 - x0) / n_ * w_
    quad(flat, (x0 + sx, y0 + sy, G(x0, y0) + lift), (x0 - sx, y0 - sy, G(x0, y0) + lift), (x1 - sx, y1 - sy, G(x1, y1) + lift), (x1 + sx, y1 + sy, G(x1, y1) + lift), colour)


main_roads = [r_ for r_ in roads if r_['hw'] == 'secondary']
for r_ in main_roads:
    pts = along_line(r_['line'], 0.5)
    for (x, y, dx, dy, d), (x1, y1, *_) in zip(pts, pts[1:]):
        if not inside(x, y) or not inside(x1, y1):
            continue
        if d % 6 < 2:
            strip(x, y, x1, y1, 0.05, (0.92, 0.92, 0.9))
        for side in (-1, 1):
            for inset in (0.2, 0.36):
                o = (r_['half'] - inset) * side
                a_, b__ = (x - dy * o, y + dx * o), (x1 - dy * o, y1 + dx * o)
                if asphalt.buffer(-0.15).contains(Point(a_)):
                    strip(a_[0], a_[1], b__[0], b__[1], 0.03, (0.93, 0.76, 0.08))
            o = (r_['half'] + 0.07) * side
            k_ = (x - dy * o, y + dx * o)
            if not asphalt.contains(Point(k_)) and not taken.buffer(0.1).contains(Point(k_)):
                cbox(flat, (k_[0], k_[1], G(k_[0], k_[1]) + 0.0), (0.5, 0.14, 0.22), math.atan2(dy, dx), (0.6, 0.59, 0.56) if int(d * 2) % 2 else (0.55, 0.54, 0.52))
                if int(d * 2) % 46 == 0:
                    g_ = (x - dy * (o - 0.3 * side), y + dx * (o - 0.3 * side))
                    cbox(flat, (g_[0], g_[1], G(g_[0], g_[1]) + 0.02), (0.5, 0.32, 0.03), math.atan2(dy, dx), (0.06, 0.06, 0.07))

# ---- Street lamps along the main road.
for r_ in main_roads:
    for i, (x, y, dx, dy, d) in enumerate(along_line(r_['line'], 33, 9)):
        side = 1 if i % 2 else -1
        px, py = x - dy * (r_['half'] + 0.6) * side, y + dx * (r_['half'] + 0.6) * side
        if not inside(px, py) or taken.buffer(0.3).contains(Point(px, py)):
            continue
        z = G(px, py)
        green_ = (0.07, 0.13, 0.1)
        cyl(mt, (px, py, z), 0.1, 0.9, green_, n=10, top=0.07)
        cyl(mt, (px, py, z + 0.9), 0.055, 4.2, green_, n=8, top=0.045)
        cyl(mt, (px, py, z + 5.0), 0.035, 1.0, green_, n=6, axis=(dy * side, -dx * side, 0.12))
        lx, ly = px + dy * side * 0.95, py - dx * side * 0.95
        cbox(mt, (lx, ly, z + 5.12), (0.5, 0.24, 0.13), math.atan2(dy, dx) + math.pi / 2, (0.12, 0.12, 0.13))
        cbox(batch('glass'), (lx, ly, z + 5.04), (0.4, 0.18, 0.03), math.atan2(dy, dx) + math.pi / 2, (1, 1, 1))


# ---- Things on the pavement by the church: a red phone box, a pillar box, a bench, a bin, a bus stop.
def phone_box(x, y, yaw):
    z, red = G(x, y), (0.72, 0.04, 0.04)
    gl, pt = batch('glass'), batch('gloss')
    cbox(pt, (x, y, z + 0.08), (0.96, 0.96, 0.16), yaw, (0.08, 0.08, 0.08))
    c, s = math.cos(yaw), math.sin(yaw)
    for ox, oy in ((-0.42, -0.42), (0.42, -0.42), (0.42, 0.42), (-0.42, 0.42)):
        cbox(pt, (x + c * ox - s * oy, y + s * ox + c * oy, z + 1.2), (0.09, 0.09, 2.1), yaw, red)
    cbox(pt, (x, y, z + 2.2), (0.96, 0.96, 0.22), yaw, red)
    blob(pt, (x, y, z + 2.3), (0.5, 0.5, 0.2), red, 0, 1)
    for k in range(4):
        a = yaw + k * math.pi / 2
        nx, ny = math.cos(a), math.sin(a)
        cbox(gl, (x + nx * 0.43, y + ny * 0.43, z + 1.15), (0.02, 0.76, 1.75), a, (1, 1, 1))
        cbox(pt, (x + nx * 0.47, y + ny * 0.47, z + 2.2), (0.02, 0.62, 0.11), a, (0.95, 0.95, 0.9))
        for j in range(9):
            cbox(pt, (x + nx * 0.445, y + ny * 0.445, z + 0.3 + j * 0.215), (0.03, 0.76, 0.025), a, red)
        for j in (-0.2, 0.2):
            cbox(pt, (x + nx * 0.445 - ny * j, y + ny * 0.445 + nx * j, z + 1.15), (0.03, 0.025, 1.75), a, red)


def pillar_box(x, y):
    z, red = G(x, y), (0.75, 0.05, 0.04)
    pt = batch('gloss')
    cyl(pt, (x, y, z), 0.25, 0.22, (0.06, 0.06, 0.06), n=18)
    cyl(pt, (x, y, z + 0.22), 0.225, 1.1, red, n=18)
    cyl(pt, (x, y, z + 1.32), 0.26, 0.06, red, n=18)
    blob(pt, (x, y, z + 1.38), (0.25, 0.25, 0.1), red, 0, 2)
    cbox(pt, (x + 0.2, y, z + 1.12), (0.08, 0.2, 0.035), 0, (0.03, 0.03, 0.03))


def bench(x, y, yaw):
    z, wood = G(x, y), (0.42, 0.27, 0.14)
    c, s = math.cos(yaw), math.sin(yaw)
    for k in range(4):
        o = -0.18 + k * 0.12
        cbox(mt, (x - s * o, y + c * o, z + 0.45), (1.7, 0.09, 0.035), yaw, wood)
    for k in range(3):
        cbox(mt, (x - s * 0.27, y + c * 0.27, z + 0.6 + k * 0.13), (1.7, 0.03, 0.09), yaw, wood)
    for o in (-0.75, 0.75):
        cbox(mt, (x + c * o, y + s * o, z + 0.22), (0.06, 0.5, 0.44), yaw, (0.06, 0.06, 0.07))
        cbox(mt, (x + c * o - s * 0.27, y + s * o + c * 0.27, z + 0.62), (0.06, 0.05, 0.5), yaw, (0.06, 0.06, 0.07))


def person(x, y, yaw, coat, trousers, hair, skin=(0.82, 0.62, 0.5), size=1.0, stride=0.25, z=None):
    """A figure the size of a model railway passenger: legs in mid step, coat, arms, head, hair."""
    z = G(x, y) if z is None else z
    c, s = math.cos(yaw), math.sin(yaw)
    at_ = lambda f, r__, h_: (x + c * f * size - s * r__ * size, y + s * f * size + c * r__ * size, z + h_ * size)
    for side in (-1, 1):
        cyl(mt, at_(stride * side * 0.5, 0.09 * side, 0.0), 0.07 * size, 0.86 * size, trousers, n=8, axis=(c * -stride * side * 0.6, s * -stride * side * 0.6, 1))
        cbox(mt, at_(stride * side * 0.5 + 0.06, 0.09 * side, 0.04), (0.26 * size, 0.1 * size, 0.08 * size), yaw, (0.08, 0.07, 0.06))
        cyl(mt, at_(-stride * side * 0.35, 0.24 * side, 0.82), 0.05 * size, 0.6 * size, coat, n=7, axis=(c * stride * side * 0.5, s * stride * side * 0.5, 1))
        blob(mt, at_(-stride * side * 0.35, 0.24 * side, 0.8), (0.055 * size,) * 3, skin, 0, 3)
    cyl(mt, at_(0, 0, 0.8), 0.19 * size, 0.62 * size, coat, n=12, top=0.2 * size)
    blob(mt, at_(0, 0, 1.56), (0.115 * size, 0.115 * size, 0.125 * size), skin, 0, 4)
    blob(mt, at_(-0.025, 0, 1.6), (0.122 * size, 0.125 * size, 0.11 * size), hair, 0, 5)


def car(x, y, yaw, paint, van=False):
    """A car drawn as a hull: forty slices from tail to nose, each a rounded box as high as the roof line there.
    Whatever stands above the waist and below the roof is glass."""
    z = G(x, y)
    c, s = math.cos(yaw), math.sin(yaw)
    body, gl = batch('carbody', smooth=True), batch('carglass', smooth=True)
    at_ = lambda f, r__, h_: (x + c * f - s * r__, y + s * f + c * r__, z + h_)
    L, Wd, roof_h, belt = (4.9, 1.95, 2.05, 1.2) if van else (4.2, 1.76, 1.42, 0.9)
    prof = [(-1, 1.9), (-0.96, 2.05), (0.5, 2.05), (0.6, 1.97), (0.8, 1.2), (0.96, 1.08), (1, 0.8)] if van else \
        [(-1, 0.7), (-0.94, 0.88), (-0.72, 0.95), (-0.45, 1.38), (-0.3, 1.42), (0.12, 1.42), (0.2, 1.38), (0.52, 0.92), (0.9, 0.8), (0.97, 0.7), (1, 0.55)]
    us = np.linspace(-1, 1, 41)
    tops = np.interp(us, [q[0] for q in prof], [q[1] for q in prof])
    halves = Wd / 2 * (1 - 0.3 * np.abs(us) ** 6)
    M, verts, local = 20, [], []
    for u, t_, w_ in zip(us, tops, halves):
        zc, hh = (0.2 + t_) / 2, (t_ - 0.2) / 2
        for i in range(M):
            th = 2 * math.pi * (i + 0.5) / M
            yy = w_ * math.copysign(abs(math.cos(th)) ** 0.45, math.cos(th))
            zz = zc + hh * math.copysign(abs(math.sin(th)) ** 0.45, math.sin(th))
            if zz > belt:  # the cabin leans in towards the roof
                yy *= 1 - 0.17 * (zz - belt) / max(0.01, roof_h - belt)
            verts.append(at_(u * L / 2, yy, zz))
            local.append((u, zz, t_))
    painted, glazed = [tuple(range(M - 1, -1, -1)), tuple(range(len(verts) - M, len(verts)))], []
    for j in range(len(us) - 1):
        for i in range(M):
            quad_ = (j * M + i, (j + 1) * M + i, (j + 1) * M + (i + 1) % M, j * M + (i + 1) % M)
            u = np.mean([local[q][0] for q in quad_])
            high = np.mean([local[q][1] for q in quad_])
            top_ = np.mean([local[q][2] for q in quad_])
            window = high > belt + 0.05 and (high < top_ - 0.1 or top_ < roof_h - 0.05) and (u > 0.3 if van else abs(u + 0.08) > 0.035)
            (glazed if window else painted).append(quad_)
    body.add(verts, painted, paint)
    gl.add(verts, glazed, (1, 1, 1))
    for f in (-L * 0.31, L * 0.31):
        for sd in (-1, 1):
            hub = at_(f, sd * (Wd / 2 - 0.2), 0.32)
            cyl(mt, hub, 0.32, 0.22, (0.035, 0.035, 0.04), n=20, axis=(-s * sd, c * sd, 0))
            cyl(batch('brass'), at_(f, sd * (Wd / 2 + 0.02), 0.32), 0.19, 0.012, (1, 1, 1), n=14, axis=(-s * sd, c * sd, 0))
    for sd in (-1, 1):
        cbox(batch('gloss'), at_(L / 2 - 0.05, sd * Wd * 0.3, 0.62), (0.08, 0.32, 0.13), yaw, (0.97, 0.97, 0.92))
        cbox(batch('gloss'), at_(-L / 2 + 0.04, sd * Wd * 0.3, 0.72 if not van else 1.0), (0.08, 0.26, 0.14), yaw, (0.75, 0.04, 0.03))
        cbox(body, at_(0.72 if not van else 1.35, sd * (Wd / 2 + 0.03), belt + 0.08), (0.1, 0.18, 0.11), yaw, paint)
    cbox(mt, at_(L / 2 - 0.01, 0, 0.42), (0.03, 0.5, 0.11), yaw, (0.95, 0.95, 0.93))
    cbox(mt, at_(-L / 2 + 0.01, 0, 0.5), (0.03, 0.5, 0.11), yaw, (0.93, 0.8, 0.12))
    cbox(mt, at_(L / 2 - 0.02, 0, 0.3), (0.12, Wd * 0.8, 0.16), yaw, (0.05, 0.05, 0.055))
    cbox(mt, at_(-L / 2 + 0.02, 0, 0.3), (0.12, Wd * 0.8, 0.16), yaw, (0.05, 0.05, 0.055))


CARS = [(0.55, 0.06, 0.06), (0.1, 0.18, 0.4), (0.75, 0.76, 0.78), (0.08, 0.08, 0.09), (0.9, 0.9, 0.88), (0.15, 0.32, 0.22), (0.45, 0.47, 0.5), (0.85, 0.6, 0.1)]
COATS = [(0.75, 0.15, 0.12), (0.12, 0.25, 0.5), (0.9, 0.75, 0.2), (0.15, 0.15, 0.18), (0.2, 0.45, 0.3), (0.85, 0.85, 0.8), (0.9, 0.45, 0.15), (0.45, 0.2, 0.5)]
LEGS = [(0.14, 0.17, 0.26), (0.1, 0.1, 0.11), (0.35, 0.32, 0.27), (0.5, 0.46, 0.38)]
HAIR = [(0.3, 0.2, 0.12), (0.12, 0.1, 0.08), (0.75, 0.62, 0.35), (0.6, 0.6, 0.6), (0.9, 0.9, 0.88)]

class Street:
    """A road to place things along: so many metres past a spot on it, so many to the left of the way one is going."""

    def __init__(self, road, start, away_from):
        self.line, self.half = road['line'], road['half']
        self.origin = self.line.project(Point(start))
        self.way = 1 if self.line.project(Point(away_from)) < self.origin else -1

    def at(self, off, across=0.0, way=1):
        """The spot and the heading there, going on along the road (way 1) or back (way -1)."""
        p = self.line.interpolate(self.origin + self.way * off)
        q = self.line.interpolate(self.origin + self.way * (off + 0.5 * way))
        dx, dy = q.x - p.x, q.y - p.y
        n_ = math.hypot(dx, dy) or 1
        return p.x - dy / n_ * across, p.y + dx / n_ * across, math.atan2(dy, dx)

    def kerb(self, off, near, extra=0.75):
        """A spot on the pavement, on the side of the road that `near` (a shape) is on, and which side that is."""
        x, y, yaw = self.at(off)
        dx, dy = math.cos(yaw), math.sin(yaw)
        side = 1 if (near.centroid.x - x) * -dy + (near.centroid.y - y) * dx > 0 else -1
        return x - dy * (self.half + extra) * side, y + dx * (self.half + extra) * side, yaw, side


# Cars parked on the side streets, in a picture with --movers only.
parked = []
for r_ in roads:
    if r_['hw'] not in ('residential', 'unclassified', 'service') or r_['kind'] != 'asphalt':
        continue
    for x, y, dx, dy, d in along_line(r_['line'], 7.5, 5):
        px, py = x + dy * (r_['half'] - 0.95), y - dx * (r_['half'] - 0.95)
        if rnd.random() < 0.55 and inside(px, py) and abs(px) < HALF - 4 and abs(py) < HALF - 4 and all(math.dist((px, py), q) > 6 for q in parked) \
                and all(o is r_ or o['line'].distance(Point(px, py)) > o['half'] + 1.6 for o in roads):
            parked.append((px, py))
            yaw, paint = math.atan2(dy, dx) + (math.pi if rnd.random() < 0.3 else 0), rnd.choice(CARS)
            if MOVERS:
                car(px, py, yaw, paint)

# ---- At every front door: tubs of flowers, and a lamp by the door. Bins at the side of the house.
FLOWERS = [(0.9, 0.2, 0.3), (0.95, 0.5, 0.7), (0.6, 0.3, 0.8), (0.95, 0.85, 0.2), (0.95, 0.95, 0.95), (0.9, 0.4, 0.1)]
for (pos, out, along_), i in zip(DOORWAYS, range(999)):
    for side in (-1, 1):
        x, y = pos[0] + out[0] * 0.32 + along_[0] * 0.78 * side, pos[1] + out[1] * 0.32 + along_[1] * 0.78 * side
        if rnd.random() < 0.75:
            z = G(x, y)
            cyl(mt, (x, y, z), 0.15, 0.3, CLAY, n=10, top=0.19)
            blob(batch('leaves'), (x, y, z + 0.42), (0.22, 0.22, 0.2), (0.15, 0.3, 0.1), 0.3, i)
            colour = rnd.choice(FLOWERS)
            for k in range(7):
                a = rnd.random() * 6.28
                blob(mt, (x + math.cos(a) * 0.15, y + math.sin(a) * 0.15, z + 0.5 + 0.1 * rnd.random()), (0.045,) * 3, colour, 0, k)
    cbox(mt, (pos[0] + out[0] * 0.07 + along_[0] * 0.7, pos[1] + out[1] * 0.07 + along_[1] * 0.7, pos[2] + 1.95), (0.14, 0.14, 0.24), math.atan2(along_[1], along_[0]), (0.05, 0.05, 0.05))
for (a, b_, floor, name, eaves), i in zip(FRONTS, range(999)):
    d = np.subtract(b_, a)
    length = float(np.linalg.norm(d))
    if length < 3:
        continue
    d = d / length
    out = np.array([d[1], -d[0]])
    if name is None and rnd.random() < 0.7:
        for k, colour in enumerate(rnd.sample([(0.1, 0.25, 0.14), (0.08, 0.08, 0.09), (0.12, 0.2, 0.45), (0.35, 0.22, 0.1)], rnd.randint(1, 3))):
            p = np.array(a) + d * (0.5 + k * 0.62) + out * 0.42
            if free(p[0], p[1]) or pavement.contains(Point(p)):
                z = G(p[0], p[1])
                cbox(mt, (p[0], p[1], z + 0.48), (0.5, 0.56, 0.92), math.atan2(d[1], d[0]), colour)
                cbox(mt, (p[0], p[1], z + 0.97), (0.54, 0.62, 0.06), math.atan2(d[1], d[0]), tuple(c * 1.3 for c in colour))
    if name:  # the pub: baskets of flowers along the front, a hanging sign, tables outside
        for k in range(int(length / 2.6)):
            p = np.array(a) + d * (1.3 + k * 2.6) + out * 0.35
            cyl(mt, (p[0] - out[0] * 0.35, p[1] - out[1] * 0.35, floor + 2.75), 0.012, 0.4, IRON, n=4, axis=(out[0], out[1], 0))
            blob(batch('leaves'), (p[0], p[1], floor + 2.5), (0.24, 0.24, 0.2), (0.16, 0.32, 0.1), 0.3, k)
            for q in range(10):
                ang = rnd.random() * 6.28
                blob(mt, (p[0] + math.cos(ang) * 0.2, p[1] + math.sin(ang) * 0.2, floor + 2.5 + rnd.uniform(-0.12, 0.15)), (0.05,) * 3, rnd.choice(FLOWERS), 0, q)
        p = np.array(a) + d * (length * 0.5) + out * 0.55
        yaw = math.atan2(out[1], out[0])
        cyl(mt, (p[0] - out[0] * 0.55, p[1] - out[1] * 0.55, floor + 4.3), 0.02, 1.0, IRON, n=5, axis=(out[0], out[1], 0))
        cbox(batch('gloss'), (p[0], p[1], floor + 3.75), (0.8, 0.05, 0.95), yaw, (0.08, 0.2, 0.14))
        for box in ((0.84, 0.06, 0.05, 0.47), (0.84, 0.06, 0.05, -0.47)):
            cbox(batch('brass'), (p[0], p[1], floor + 3.75 + box[3]), box[:3], yaw, (1, 1, 1))
        for k in range(3):
            p = np.array(a) + d * (length * (0.2 + 0.3 * k)) + out * 1.15
            z = G(p[0], p[1])
            cyl(mt, (p[0], p[1], z), 0.03, 0.72, IRON, n=6)
            cyl(mt, (p[0], p[1], z + 0.72), 0.34, 0.03, (0.4, 0.26, 0.14), n=16)
            for q in (-1, 1):
                c_ = p + d * 0.55 * q
                cbox(mt, (c_[0], c_[1], z + 0.24), (0.36, 0.36, 0.46), 0.3, (0.3, 0.2, 0.12))
            cyl(mt, (p[0], p[1], z + 0.75), 0.02, 1.5, (0.9, 0.9, 0.88), n=5)
            cyl(batch('matte'), (p[0], p[1], z + 1.95), 1.05, 0.4, (0.75, 0.1, 0.1) if k % 2 else (0.92, 0.88, 0.75), n=10, top=0.03)

# ---- Sheep, where there is open grass a good way from any house or road, and the picture shows it. With --movers only.
tx_, ty_ = to_block(t[:, 0], t[:, 1])
clear = ndi.distance_transform_edt(~blocked) * 0.25  # metres to the nearest road or building
spots = np.argwhere(clear[::8, ::8] > 24) * 2.0  # row, column in metres
spots = [(c - HALF, HALF - r_) for r_, c in spots if abs(c - HALF) < HALF - 12 and abs(HALF - r_) < HALF - 12]
spots = [q for q in spots if bool(in_picture(q[0], q[1], G(*q), -6))]
flock = []
if spots:
    fx, fy = rnd.choice(spots)
    for _ in range(4000):
        if len(flock) >= 22:
            break
        x, y = rnd.gauss(fx, 12), rnd.gauss(fy, 12)
        if not free(x, y) or clear[int((HALF - y) / 0.25), int((x + HALF) / 0.25)] < 9 or np.min(np.hypot(tx_ - x, ty_ - y)) < 4.5 \
                or any(math.dist((x, y), q) < 1.6 for q in flock):
            continue
        flock.append((x, y))
        z, yaw = G(x, y), rnd.random() * 6.283
        c, s_ = math.cos(yaw), math.sin(yaw)
        lamb = 0.62 if rnd.random() < 0.25 else 1.0
        wool = tuple(v * rnd.uniform(0.9, 1.0) for v in (0.9, 0.88, 0.8))
        grazing = rnd.random() < 0.6
        if not MOVERS:
            continue
        blob(batch('wool', smooth=True), (x, y, z + 0.62 * lamb), (0.52 * lamb, 0.3 * lamb, 0.3 * lamb) if abs(c) > abs(s_) else (0.3 * lamb, 0.52 * lamb, 0.3 * lamb), wool, 0.12, len(flock))
        blob(mt, (x + c * 0.55 * lamb, y + s_ * 0.55 * lamb, z + (0.3 if grazing else 0.8) * lamb), (0.13 * lamb, 0.11 * lamb, 0.12 * lamb), (0.12, 0.1, 0.09), 0, 1)
        for f in (-0.28, 0.28):
            for q in (-0.13, 0.13):
                cyl(mt, (x + (c * f - s_ * q) * lamb, y + (s_ * f + c * q) * lamb, z), 0.035 * lamb, 0.42 * lamb, (0.12, 0.1, 0.09), n=5)
print(len(flock) if MOVERS else 0, 'sheep')

# ---- Aerials on some chimneys. Gulls on some ridges, with --movers only.
for x, y, z in CHIMNEYS:
    if rnd.random() < 0.45:
        cyl(mt, (x, y, z), 0.014, 1.5, (0.6, 0.6, 0.62), n=4)
        cyl(mt, (x - 0.5, y, z + 1.4), 0.01, 1.0, (0.6, 0.6, 0.62), n=4, axis=(1, 0, 0))
        for k in range(5):
            cyl(mt, (x - 0.4 + k * 0.2, y - 0.22, z + 1.4), 0.007, 0.44, (0.6, 0.6, 0.62), n=4, axis=(0, 1, 0))
for mid, axis_, top_, length in RIDGES:
    for k in range(rnd.choice([0, 0, 1, 1, 2, 3])):
        p = np.asarray(mid) + np.asarray(axis_) * rnd.uniform(-0.4, 0.4) * length
        if not MOVERS:
            continue
        blob(mt, (p[0], p[1], top_ + 0.1), (0.13, 0.09, 0.085), (0.95, 0.95, 0.93), 0, k)
        blob(mt, (p[0] - 0.03, p[1], top_ + 0.13), (0.12, 0.07, 0.05), (0.62, 0.64, 0.67), 0, k)
        blob(mt, (p[0] + 0.11, p[1], top_ + 0.19), (0.05, 0.045, 0.045), (0.96, 0.96, 0.94), 0, k)
        cbox(mt, (p[0] + 0.17, p[1], top_ + 0.185), (0.05, 0.015, 0.015), 0, (0.95, 0.75, 0.1))

# ---- A washing line or two in the back gardens.
lines = 0
for _ in range(400):
    if lines >= 3:
        break
    x, y = rnd.uniform(-HALF + 8, HALF - 8), rnd.uniform(-HALF + 8, HALF - 8)
    a = rnd.random() * 3.14
    ends = [(x, y), (x + math.cos(a) * 5, y + math.sin(a) * 5)]
    if not all(free(px, py) for px, py in ends) or not 3 < taken.distance(Point(x, y)) < 9 or road_edge.distance(Point(x, y)) < 6 or (church is not None and church.distance(Point(x, y)) < 34):
        continue
    lines += 1
    z = max(G(*ends[0]), G(*ends[1])) + 1.9
    for px, py in ends:
        cyl(mt, (px, py, G(px, py)), 0.035, z - G(px, py) + 0.1, (0.5, 0.45, 0.4), n=6)
    cyl(mt, (ends[0][0], ends[0][1], z), 0.006, 5.0, (0.9, 0.9, 0.9), n=4, axis=(math.cos(a), math.sin(a), 0))
    for k in range(7):
        f = 0.5 + k * 0.6
        w_, h_ = rnd.uniform(0.3, 0.55), rnd.uniform(0.4, 0.8)
        p0 = (x + math.cos(a) * f, y + math.sin(a) * f)
        p1 = (x + math.cos(a) * (f + w_), y + math.sin(a) * (f + w_))
        sw = rnd.uniform(-0.08, 0.08)
        quad(mt, (p0[0] + sw, p0[1], z - h_), (p1[0] + sw, p1[1], z - h_), (p1[0], p1[1], z), (p0[0], p0[1], z), rnd.choice(FLOWERS + [(0.95, 0.95, 0.95), (0.2, 0.3, 0.6)]))


# ---- Bolster the giant, in mid stride on the road: 6.4 m of him, with a young tree for a staff.
def giant(x, y, yaw):
    z = G(x, y)
    c, s = math.cos(yaw), math.sin(yaw)
    P = lambda f, r__, h_: np.array([x + c * f - s * r__, y + s * f + c * r__, z + h_])
    fwd, up_ = np.array([c, s, 0.0]), np.array([0, 0, 1.0])
    skin, tunic, mane, fur_ = (0.78, 0.57, 0.44), (0.4, 0.29, 0.17), (0.25, 0.15, 0.08), (0.2, 0.15, 0.11)
    cloth, sk, hair_ = batch('cloth', smooth=True), batch('skin', smooth=True), batch('hair')
    r = random.Random(11)

    def limb(a_, b__, r0, r1, bt, tint):
        d_ = b__ - a_
        cyl(bt, a_, r0, float(np.linalg.norm(d_)), tint, n=16, top=r1, axis=d_, cap=False)
        blob(bt, b__, (r1 * 1.04,) * 3, tint, 0, 0)

    swing = lambda a_: fwd * math.sin(a_) - up_ * math.cos(a_)
    # Legs: the left one reaching forward onto its heel, the right one pushing off behind on its toes.
    for side, thigh, shin in ((1, 0.42, 0.22), (-1, -0.4, -0.95)):
        hip = P(0, 0.4 * side, 3.3)
        knee = hip + swing(thigh) * 1.6
        ankle = knee + swing(shin) * 1.5
        ankle[2] = max(ankle[2], z + 0.3)
        blob(sk, hip, (0.45, 0.45, 0.45), skin, 0, 0)
        limb(hip, knee, 0.43, 0.32, sk, skin)
        limb(knee, ankle, 0.31, 0.2, sk, skin)
        blob(sk, knee + (ankle - knee) * 0.32 - fwd * 0.08, (0.33, 0.31, 0.5), skin, 0, 1)  # the calf
        pitch = -0.25 if side > 0 else 0.7  # heel down in front, toes down behind
        toe = ankle + fwd * 0.72 * math.cos(pitch) - up_ * (0.2 + 0.72 * math.sin(pitch) * 0.6)
        toe[2] = max(toe[2], z + 0.1)
        limb(ankle - fwd * 0.16 - up_ * 0.1, toe, 0.2, 0.19, sk, skin)
        for k in range(5):
            blob(sk, toe + fwd * 0.17 + np.array([-s, c, 0]) * (k - 2) * 0.085 * side, (0.085, 0.06, 0.065), skin, 0, k)
    # The tunic: sackcloth to the middle of the thigh, a rope round the waist, a fur across the shoulders.
    cyl(cloth, P(0, 0, 2.55), 1.02, 1.1, tunic, n=28, top=0.86, cap=False)
    cyl(cloth, P(0.03, 0, 3.65), 0.86, 1.3, tunic, n=28, top=1.04, cap=False)
    blob(cloth, P(0.03, 0, 4.92), (0.98, 1.2, 0.5), tunic, 0, 2)
    for k in range(64):  # the hem is ragged
        a = k / 64 * 6.283
        q = P(math.cos(a) * 1.0, math.sin(a) * 1.0, 2.6)
        out_ = np.array([c * math.cos(a) - s * math.sin(a), s * math.cos(a) + c * math.sin(a), 0])
        cyl(cloth, q, 0.1, 0.25 + 0.3 * r.random(), tunic, n=5, top=0.01, axis=out_ * 0.12 - up_)
    for k in range(3):
        cyl(batch('matte'), P(0.02, 0, 3.58 + k * 0.07), 0.9 + 0.012 * k, 0.07, (0.62, 0.52, 0.34), n=28, cap=False)
    cyl(batch('matte'), P(0.86, 0.3, 3.0), 0.05, 0.62, (0.62, 0.52, 0.34), n=6)
    blob(batch('matte'), P(0.84, -0.42, 3.3), (0.2, 0.24, 0.3), (0.3, 0.2, 0.12), 0, 3)  # a pouch
    for k in range(520):  # the fur
        a, ring_ = r.random() * 6.283, r.random()
        rad_, h_ = 1.22 - 0.5 * ring_, 4.78 + 0.5 * ring_
        q = P(0.03 + math.cos(a) * rad_ * 0.86, math.sin(a) * rad_ * 1.08, h_)
        out_ = np.array([c * math.cos(a) - s * math.sin(a), s * math.cos(a) + c * math.sin(a), 0])
        cyl(hair_, q, 0.06, 0.32 + 0.25 * r.random(), tuple(v * r.uniform(0.6, 1.5) for v in fur_), n=4, top=0.006, axis=out_ * 0.55 - up_)
    blob(batch('matte'), P(0.03, 0, 5.0), (0.95, 1.2, 0.42), fur_, 0, 4)
    # Arms, bare, swinging against the legs; the right hand holds the staff.
    hands = {}
    for side, upper, lower in ((1, -0.42, -0.1), (-1, 0.5, 1.15)):
        sh = P(0.03, 1.2 * side, 5.02)
        el = sh + swing(upper) * 1.12 + np.array([-s, c, 0]) * 0.12 * side
        wr = el + swing(lower) * 1.0
        blob(sk, sh, (0.38, 0.38, 0.36), skin, 0, 5)
        limb(sh, el, 0.3, 0.25, sk, skin)
        limb(el, wr, 0.25, 0.19, sk, skin)
        blob(sk, wr + swing(lower) * 0.2, (0.24, 0.2, 0.26), skin, 0, 6)
        hands[side] = wr + swing(lower) * 0.2
    foot_ = P(1.75, -1.5, 0.0)
    lean_ = hands[-1] - foot_
    lean_ /= np.linalg.norm(lean_)
    cyl(batch('bark'), foot_, 0.15, 7.4, (0.3, 0.23, 0.16), n=9, top=0.07, axis=lean_)
    for k in range(4):
        q = foot_ + lean_ * (4.6 + k * 0.8)
        cyl(batch('bark'), q, 0.05, 0.5, (0.3, 0.23, 0.16), n=5, top=0.01, axis=lean_ + np.array([r.uniform(-1, 1), r.uniform(-1, 1), 0.2]))
    for k in range(5):
        SPRAYS.append([*(foot_ + lean_ * (7.0 + 0.15 * k) + np.array([r.uniform(-0.3, 0.3), r.uniform(-0.3, 0.3), 0])), 0, 0, 1, 0.4, 3])
    # Neck and head: a heavy brow, a nose, dark eyes; hair to the shoulders, a beard to the chest, oak leaves in his hair.
    cyl(sk, P(0.06, 0, 5.1), 0.3, 0.45, skin, n=14, cap=False)
    head = P(0.14, 0, 5.86)
    blob(sk, head, (0.52, 0.5, 0.58), skin, 0, 7)
    blob(sk, head + fwd * 0.3 - up_ * 0.3, (0.3, 0.36, 0.3), skin, 0, 8)  # the jaw
    blob(sk, head + fwd * 0.53 - up_ * 0.04, (0.13, 0.11, 0.17), tuple(v * 0.92 for v in skin), 0, 9)
    blob(sk, head + fwd * 0.44 + up_ * 0.2, (0.14, 0.4, 0.09), tuple(v * 0.95 for v in skin), 0, 10)  # the brow
    lat = np.array([-s, c, 0])
    for side in (-1, 1):
        blob(batch('gloss'), head + fwd * 0.46 + lat * 0.2 * side + up_ * 0.1, (0.065, 0.075, 0.06), (0.04, 0.03, 0.02), 0, 11)
        cbox(hair_, head + fwd * 0.5 + lat * 0.2 * side + up_ * 0.24, (0.09, 0.3, 0.07), yaw + 0.12 * side, mane)
        blob(sk, head + lat * 0.52 * side, (0.08, 0.06, 0.15), skin, 0, 12)
    for k in range(420):  # hair
        a, hi = r.uniform(0.7, 5.58), r.uniform(0.0, 1.0)
        ring_ = math.sqrt(max(0.0, 1 - (hi * 0.92) ** 2))
        root = head + fwd * math.cos(a) * 0.5 * ring_ + lat * math.sin(a) * 0.5 * ring_ + up_ * hi * 0.56
        out_ = root - head
        cyl(hair_, root, 0.05, r.uniform(0.6, 1.25), tuple(v * r.uniform(0.6, 1.45) for v in mane), n=4, top=0.008, axis=np.array([out_[0] * 0.5, out_[1] * 0.5, -0.9 + out_[2] * 0.5]))
    for k in range(360):  # beard and whiskers
        a, dn = r.uniform(-1.35, 1.35), r.uniform(0.0, 1.0)
        root = head + fwd * (math.cos(a) * 0.5 + 0.02) + lat * math.sin(a) * 0.48 - up_ * (0.1 + dn * 0.42)
        cyl(hair_, root, 0.04, r.uniform(0.45, 1.05), tuple(v * r.uniform(0.6, 1.5) for v in mane), n=4, top=0.006,
            axis=fwd * (0.3 + 0.3 * r.random()) + lat * math.sin(a) * 0.35 - up_)
    for k in range(40):  # a crown of oak leaves
        a = k / 40 * 6.283
        q = head + fwd * math.cos(a) * 0.5 + lat * math.sin(a) * 0.5 + up_ * (0.3 + 0.06 * r.random())
        tip = q + (fwd * math.cos(a) + lat * math.sin(a)) * 0.3 + up_ * (0.14 + 0.12 * r.random())
        side_ = np.cross(tip - q, up_) * 0.4
        quad(batch('leafcard'), tuple(q), tuple((q + tip) / 2 + side_), tuple(tip), tuple((q + tip) / 2 - side_), tuple(v * r.uniform(0.7, 1.3) for v in (0.22, 0.42, 0.12)))


# ---- Materials for what was added here.
m, nt, bsdf = material('grass')
tinted(nt, bsdf)
bsdf.inputs['Roughness'].default_value = 0.65
MATS['grass'] = MATS['leafcard'] = m
MATS['paint'] = MATS['matte']
m, nt, bsdf = material('carpaint')
tinted(nt, bsdf)
bsdf.inputs['Roughness'].default_value = 0.18
try:
    bsdf.inputs['Coat Weight'].default_value = 0.6
except Exception:  # noqa: BLE001
    pass
MATS['carpaint'] = MATS['carbody'] = m
MATS['carglass'] = MATS['glass']
m, nt, bsdf = material('cloth')  # wool, roughly woven
tinted(nt, bsdf, 0.18, 30.0)
bsdf.inputs['Roughness'].default_value = 0.95
weave = node(nt, 'ShaderNodeTexWave', wave_type='BANDS')
weave.inputs['Scale'].default_value, weave.inputs['Distortion'].default_value = 28.0, 1.5
bump(nt, bsdf, weave.outputs['Fac'], 0.5, 0.01)
try:
    bsdf.inputs['Sheen Weight'].default_value = 0.4
except Exception:  # noqa: BLE001
    pass
MATS['cloth'] = m
m, nt, bsdf = material('skin')
tinted(nt, bsdf, 0.06, 6.0)
bsdf.inputs['Roughness'].default_value = 0.55
try:
    bsdf.inputs['Subsurface Weight'].default_value = 0.25
    bsdf.inputs['Subsurface Radius'].default_value = (0.25, 0.1, 0.06)
except Exception:  # noqa: BLE001
    pass
MATS['skin'] = m
m, nt, bsdf = material('hair')
tinted(nt, bsdf)
bsdf.inputs['Roughness'].default_value = 0.5
MATS['hair'] = m
m, nt, bsdf = material('wool')
tinted(nt, bsdf, 0.12, 30.0)
bsdf.inputs['Roughness'].default_value = 1.0
curl = node(nt, 'ShaderNodeTexVoronoi', feature='F1')
curl.inputs['Scale'].default_value = 28.0
bump(nt, bsdf, curl.outputs['Distance'], 1.0, 0.05)
MATS['wool'] = m
m, nt, bsdf = material('lamp')  # the orange globe of a crossing beacon, lit
tinted(nt, bsdf)
bsdf.inputs['Roughness'].default_value = 0.2
attr_ = node(nt, 'ShaderNodeAttribute', attribute_name='tint')
nt.links.new(attr_.outputs['Color'], bsdf.inputs['Emission Color'])
bsdf.inputs['Emission Strength'].default_value = 1.5
MATS['lamp'] = m
