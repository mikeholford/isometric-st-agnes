# /// script
# requires-python = "==3.13.*"
# dependencies = ["bpy==5.3.0", "pillow"]
# ///
"""Bolster, the giant of St Agnes, built in Blender by rule, to walk on the map as the Land Rover drives on it.

He is made after three sheets of pictures of the giant of the village's Bolster Festival, turned from a carried
figure into one that walks: a face like a slab of weathered stone with a great nose, straw brows and beard, a crown
of fern and flowers on long dark hair, a crimson tunic with pink sleeves and a pale green hem, an olive waistcoat,
garlands and silver brooches, a belt with a knife, and hands, legs and bare feet of the same stone as his face. No
club: the old tales give him none. He stands 6.4 m, as on the map.

Every part hangs on joints (hips, knees, ankles, shoulders, elbows), and pose() says where they are at any moment of
a step. So one figure gives every picture of a walk.

  uv run deep/models/bolster.py                  the four sides of him standing, six moments of a step from the
                                                 side, and the eight ways he walks as the map sees him, in
                                                 out/models/bolster/
  uv run deep/models/bolster.py --only turn      just one of them: turn, walk or map
  uv run deep/models/bolster.py --place 1335,930,200
                                                 stood in the picture of a deep place, as defender.py does
  --samples 64    rays through every pixel

He faces along x, y is to his left, z is up, in metres, feet on the ground at the middle.
"""
import math, os, random, sys
import bpy
import bmesh  # only after bpy: it comes with it
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from defender import ROOT, arg, flag, ground, heading, linear, map_camera, stage  # noqa: E402

HIP, SHOULDER = 2.25, 4.2  # the joints above the ground when he stands
THIGH, SHIN, UPPER, FORE = 1.02, 1.0, 1.08, 0.95
SOLE = 0.26  # the ankle above the sole
Z = Vector((0, 0, 1))


def matter(name, colour, rough=0.8, other=None, amount=0.5, grain=3.0, bump=0.3, grime=0.5, metal=0.0):
    """A material with a hand-made look: mottled with a second colour, rough to the touch, dark in its folds. It is
    laid out in each part's own measure, so the pattern stays on a leg as the leg swings."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Roughness'].default_value, b.inputs['Metallic'].default_value = rough, metal
    link = nt.links.new

    def new(kind, **props):
        n = nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def ramp(source, lo, hi, out_lo, out_hi):
        n = new('ShaderNodeMapRange')
        for i, v in zip((1, 2, 3, 4), (lo, hi, out_lo, out_hi)):
            n.inputs[i].default_value = v
        link(source, n.inputs[0])
        return n.outputs[0]

    def noise(scale, detail=6.0):
        n = new('ShaderNodeTexNoise')
        n.inputs['Scale'].default_value, n.inputs['Detail'].default_value = scale, detail
        link(where, n.inputs['Vector'])
        return n.outputs['Fac']

    def towards(amount_, colour_socket, colour_):
        n = new('ShaderNodeMixRGB')
        link(amount_, n.inputs[0])
        link(colour_socket, n.inputs[1])
        n.inputs[2].default_value = colour_
        return n.outputs[0]

    where = new('ShaderNodeTexCoord').outputs['Object']
    c = new('ShaderNodeRGB').outputs[0]
    c.default_value = linear(colour)
    shade = new('ShaderNodeHueSaturation')
    link(c, shade.inputs['Color'])
    link(ramp(noise(grain * 0.5), 0.3, 0.7, 0.62, 1.2), shade.inputs['Value'])
    c = shade.outputs[0]
    if other:
        c = towards(ramp(noise(grain, 8.0), 0.5, 0.68, 0.0, amount), c, linear(other))
    nook = new('ShaderNodeAmbientOcclusion', samples=4)
    nook.inputs['Distance'].default_value = 0.35
    c = towards(ramp(nook.outputs['AO'], 0.4, 0.95, grime, 0.0), c, (0.02, 0.018, 0.015, 1.0))
    link(c, b.inputs['Base Color'])
    lumps = new('ShaderNodeBump')
    lumps.inputs['Strength'].default_value, lumps.inputs['Distance'].default_value = bump, 0.08
    link(noise(grain * 2.2, 9.0), lumps.inputs['Height'])
    link(lumps.outputs[0], b.inputs['Normal'])
    return m


class Batch:
    """Many simple shapes gathered into one object: cones, balls, leaves."""

    def __init__(self):
        self.bm = bmesh.new()

    def cone(self, a, b, r1, r2=None, n=12):
        a, b = Vector(a), Vector(b)
        m = Matrix.Translation((a + b) / 2) @ Z.rotation_difference(b - a).to_matrix().to_4x4()
        bmesh.ops.create_cone(self.bm, cap_ends=True, segments=n, radius1=r1, radius2=r1 if r2 is None else r2, depth=(b - a).length, matrix=m)

    def ball(self, centre, radii, turn=None, n=20):
        radii = (radii,) * 3 if isinstance(radii, (int, float)) else radii
        m = Matrix.Translation(centre) @ (turn or Matrix.Identity(4)) @ Matrix.Diagonal((*radii, 1.0))
        bmesh.ops.create_uvsphere(self.bm, u_segments=n, v_segments=max(6, n // 2), radius=1.0, matrix=m)

    def limb(self, a, b, r1, r2=None, n=16):
        """A bone with flesh on it: a cone with a ball at each end."""
        self.cone(a, b, r1, r2, n)
        self.ball(a, r1, n=n)
        self.ball(b, r1 if r2 is None else r2, n=n)

    def leaf(self, base, tip, width, facing):
        """A flat blade from base to tip, widest a third of the way along, its face towards `facing`."""
        base, tip = Vector(base), Vector(tip)
        side = (tip - base).cross(Vector(facing))
        side = side.normalized() * width / 2 if side.length > 1e-6 else Vector((width / 2, 0, 0))
        mid = base + (tip - base) * 0.38
        self.bm.faces.new([self.bm.verts.new(p) for p in (base, mid + side, tip, mid - side)])

    def shell(self, centre, radii, z0, z1, gap=0.0, rings=14, around=40):
        """Cloth lying on an egg shape between two heights, open down the front by `gap` radians each side."""
        cx, cy, cz = centre
        grid = []
        for i in range(rings + 1):
            z = z0 + (z1 - z0) * i / rings
            r = math.sqrt(max(0.0, 1 - ((z - cz) / radii[2]) ** 2))
            grid.append([self.bm.verts.new((cx + radii[0] * r * math.cos(a), cy + radii[1] * r * math.sin(a), z))
                         for a in (gap + (2 * math.pi - 2 * gap) * k / around for k in range(around + 1))])
        for i in range(rings):
            for k in range(around):
                self.bm.faces.new((grid[i][k], grid[i][k + 1], grid[i + 1][k + 1], grid[i + 1][k]))

    def done(self, name, material, at=None, parent=None, smooth=True):
        for f in self.bm.faces:
            f.smooth = smooth
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        ob = bpy.data.objects.new(name, me)
        ob.data.materials.append(material)
        bpy.context.scene.collection.objects.link(ob)
        if at is not None:
            ob.matrix_world = at
        if parent is not None:
            world = ob.matrix_world.copy()
            ob.parent = parent
            ob.matrix_world = world
        return ob


def pose(step=None):
    """Where his joints are. `step` runs from 0 to 1 over two paces, the left leg leading; None is standing still
    with the arms a little out, as on the sheet of his four sides. A leg swings from the hip, bends at the knee as it
    comes through, and lands on its heel; the arms swing against the legs. Whichever foot is lowest is on the ground,
    and that alone makes him rise and sink as he walks."""
    walking = step is not None
    out = {'legs': {}, 'arms': {}}
    low = 0.0
    for s, lead in ((1, 0.0), (-1, 0.5)):
        p = 2 * math.pi * ((step or 0.0) + lead)
        swing = math.radians(27) * math.sin(p) if walking else 0.0
        bend = math.radians(5) + (math.radians(50) * max(0.0, math.cos(p)) if walking else 0.0)
        toe_up = math.radians(17) * math.sin(p) ** 3 if walking else 0.0
        hip = Vector((0, s * 0.43, HIP))
        knee = hip + THIGH * Vector((math.sin(swing), 0, -math.cos(swing)))
        ankle = knee + SHIN * Vector((math.sin(swing - bend), 0, -math.cos(swing - bend)))
        turn = Matrix.Rotation(-toe_up, 4, 'Y')
        low = min(low, *((ankle + turn.to_3x3() @ Vector((x, 0, -SOLE))).z for x in (-0.32, 0.9)))  # heel and toe
        out['legs'][s] = (hip, knee, ankle, turn)
        reach = -math.radians(21) * math.sin(p) if walking else 0.0
        elbow_bend = math.radians(16) + (math.radians(18) * max(0.0, -math.sin(p)) if walking else 0.0)
        away = 0.1 if walking else 0.24  # how far the arm hangs from the body
        shoulder = Vector((0, s * 1.2, SHOULDER))
        elbow = shoulder + UPPER * Vector((math.sin(reach), s * away, -math.cos(reach))).normalized()
        wrist = elbow + FORE * Vector((math.sin(reach + elbow_bend), s * away * 0.6, -math.cos(reach + elbow_bend))).normalized()
        out['arms'][s] = (shoulder, elbow, wrist)
    out['lift'] = -low  # the legs were hung from hips at standing height: now set him down on his lowest foot
    return out


def build(step=None):
    rnd = random.Random(3)
    root = bpy.data.objects.new('bolster', None)
    bpy.context.scene.collection.objects.link(root)
    stone = matter('stone', (112, 110, 106), 0.9, other=(142, 108, 64), amount=0.6, grain=2.4, bump=0.8, grime=0.85)
    tunic = matter('crimson cloth', (92, 14, 38), 0.95, grain=14.0, bump=0.12, grime=0.45)
    sleeve = matter('pink cloth', (152, 28, 78), 0.95, grain=14.0, bump=0.12, grime=0.45)
    hem = matter('green cloth', (134, 170, 92), 0.95, grain=14.0, bump=0.14, grime=0.4)
    olive = matter('olive cloth', (104, 96, 44), 0.95, other=(128, 104, 52), amount=0.4, grain=10.0, bump=0.16, grime=0.5)
    trim = matter('trim', (150, 110, 60), 0.9, grain=10.0, bump=0.1)
    cuff = matter('cuff', (206, 196, 170), 0.95, grain=12.0, bump=0.1)
    leather = matter('leather', (78, 48, 28), 0.6, other=(110, 72, 40), amount=0.4, grain=6.0, bump=0.15)
    brass = matter('brass', (176, 140, 70), 0.35, metal=1.0, bump=0.05, grime=0.3)
    silver = matter('silver', (210, 212, 214), 0.3, metal=1.0, bump=0.08, grime=0.6)
    straw = matter('straw', (186, 118, 48), 0.8, other=(214, 160, 84), amount=0.6, grain=9.0, bump=0.1, grime=0.3)
    hair = matter('hair', (48, 34, 24), 0.75, other=(84, 62, 40), amount=0.6, grain=9.0, bump=0.1, grime=0.3)
    fern = [matter(f'fern {i}', c, 0.7, other=(190, 200, 70), amount=0.35, grain=8.0, bump=0.05, grime=0.35)
            for i, c in enumerate(((70, 128, 40), (104, 152, 48), (52, 104, 44)))]
    petals = [matter(f'petal {i}', c, 0.7, bump=0.02, grime=0.2) for i, c in enumerate(((214, 60, 96), (238, 196, 40), (150, 70, 160), (236, 232, 220), (200, 40, 40)))]
    eye = matter('eye', (236, 234, 224), 0.3, bump=0.0, grime=0.2)
    dark = matter('dark', (14, 12, 12), 0.6, bump=0.0, grime=0.0)
    tooth = matter('tooth', (226, 214, 180), 0.5, bump=0.03, grime=0.4)

    j = pose(step)
    up = Vector((0, 0, j['lift']))
    lean = 0.07 if step is not None else 0.0  # he leans into his walk

    def body(x, y, z):
        """A spot on his trunk or head, leaning with him from the hips."""
        return Vector((x + (z - HIP) * lean, y, z)) + up

    # ---- Legs and feet, of stone.
    for s, (hip, knee, ankle, turn) in j['legs'].items():
        b = Batch()
        b.limb(hip + up, knee + up, 0.40, 0.33)
        b.limb(knee + up, ankle + up, 0.33, 0.25)
        b.ball(knee + up + Vector((0.08, 0, 0)), (0.3, 0.3, 0.3))
        b.done(f'leg {s}', stone, parent=root)
        f = Batch()  # the foot, made about its ankle and then turned on it
        f.ball((0.0, 0, -0.02), (0.3, 0.27, 0.24))
        f.ball((0.34, 0, -0.09), (0.6, 0.31, 0.17))
        f.ball((-0.22, 0, -0.12), (0.2, 0.22, 0.14))
        for k, (y, r, x) in enumerate(((-0.22, 0.12, 0.9), (-0.08, 0.1, 0.94), (0.04, 0.095, 0.92), (0.15, 0.09, 0.88), (0.25, 0.08, 0.82))):
            f.ball((x, -s * y, -SOLE + r + 0.01), (r * 1.35, r, r))  # the big toe on the inside
        f.done(f'foot {s}', stone, at=Matrix.Translation(ankle + up) @ turn @ Matrix.Diagonal((0.92, 1.35, 1.15, 1.0)), parent=root)

    # ---- The tunic: crimson, with a pale green hem that swings clear of the knees. Under it the trunk.
    cloth = Batch()
    cloth.ball(body(0, 0, 3.4), (0.7, 1.12, 1.08), n=28)
    cloth.ball(body(0.05, 0, 2.95), (0.6, 1.0, 0.7), n=28)  # he is no thin giant
    squash = Matrix.Diagonal((0.76, 1.0, 1.0, 1.0))
    bmesh.ops.create_cone(cloth.bm, cap_ends=False, segments=36, radius1=1.14, radius2=0.98, depth=0.95, matrix=Matrix.Translation(body(0.04, 0, 2.2)) @ squash)
    cloth.done('tunic', tunic, parent=root)
    skirt = Batch()
    bmesh.ops.create_cone(skirt.bm, cap_ends=False, segments=36, radius1=1.2, radius2=1.14, depth=0.5, matrix=Matrix.Translation(body(0.04, 0, 1.5)) @ squash)
    skirt.done('hem', hem, parent=root)

    # ---- The waistcoat: olive, open down the front, with a band along its edge.
    coat = Batch()
    coat.shell(body(0, 0, 3.4), (0.75, 1.17, 1.13), 2.86 + up.z, 4.38 + up.z, gap=0.32)
    for s in (-1, 1):
        coat.ball(body(0, s * 1.02, 4.1), (0.5, 0.42, 0.42))
    coat.done('waistcoat', olive, parent=root)
    edge = Batch()
    edge.shell(body(0, 0, 3.4), (0.77, 1.19, 1.13), 2.74 + up.z, 2.9 + up.z, gap=0.32, rings=2)
    edge.done('waistcoat band', trim, parent=root)

    # ---- Belt, buckle and the knife in its sheath.
    gear = Batch()
    bmesh.ops.create_cone(gear.bm, cap_ends=False, segments=36, radius1=1.035, radius2=1.035, depth=0.2, matrix=Matrix.Translation(body(0.05, 0, 2.6)) @ Matrix.Diagonal((0.78, 1.0, 1.0, 1.0)))
    gear.limb(body(0.72, 0.36, 2.55), body(0.80, 0.4, 1.86), 0.11, 0.06, n=10)
    gear.done('belt', leather, parent=root)
    metal = Batch()
    metal.ball(body(0.86, 0.0, 2.6), (0.03, 0.15, 0.13), n=10)
    metal.cone(body(0.74, 0.36, 2.6), body(0.72, 0.35, 2.92), 0.05, 0.04, n=8)
    metal.done('buckle', brass, parent=root)
    disc = Batch()
    for z, r in ((3.72, 0.2), (4.08, 0.11), (3.36, 0.11)):
        x = 0.62 + 0.06 * (1 - abs(z - 3.6))
        disc.cone(body(x, 0, z), body(x + 0.05, 0, z), r, r * 0.85, n=20)
    disc.done('brooches', silver, parent=root, smooth=False)

    # ---- Arms in pink sleeves, cuffs, and great stone hands.
    for s, (shoulder, elbow, wrist) in j['arms'].items():
        shoulder = body(shoulder.x, shoulder.y, shoulder.z) - up
        a = Batch()
        a.limb(shoulder + up, elbow + up, 0.4, 0.33)
        a.limb(elbow + up, wrist + up, 0.33, 0.27)
        a.done(f'sleeve {s}', sleeve, parent=root)
        along = (wrist - elbow).normalized()
        c = Batch()
        c.cone(wrist + up - along * 0.14, wrist + up + along * 0.06, 0.29, 0.28, n=16)
        c.done(f'cuff {s}', cuff, parent=root)
        h = Batch()  # the hand, made hanging from its wrist: the palm towards the thigh, the thumb forward
        h.ball((0, 0, -0.32), (0.27, 0.13, 0.33))
        for k, x in enumerate((-0.19, -0.06, 0.07, 0.19)):
            h.limb((x, 0, -0.56), (x + 0.02, s * -0.05, -0.86 - 0.05 * (k in (1, 2))), 0.075, 0.06, n=8)
        h.limb((0.2, 0, -0.2), (0.36, s * -0.03, -0.5), 0.085, 0.065, n=8)
        h.done(f'hand {s}', stone, at=Matrix.Translation(wrist + up) @ Z.rotation_difference(-along).to_matrix().to_4x4() @ Matrix.Scale(1.4, 4), parent=root)

    # ---- The head: a slab of stone with a brow, a great nose, cheeks and a jaw. A big head: he is a giant of a tale.
    K = 1.17
    at = lambda x, y, z: body(0.06 + (x - 0.06) * K, y * K, 5.02 + (z - 5.15) * K)
    big = lambda *r: tuple(v * K for v in r)
    head = Batch()
    head.limb(body(0, 0, 4.2), body(0.05, 0, 4.55), 0.5, 0.46)
    head.ball(at(0.06, 0, 5.15), big(0.6, 0.68, 0.8), n=28)
    head.ball(at(0.46, 0, 5.5), big(0.27, 0.64, 0.18))
    head.ball(at(0.34, 0, 4.5), big(0.38, 0.56, 0.27))
    for s in (-1, 1):
        head.ball(at(0.42, s * 0.38, 4.98), big(0.24, 0.25, 0.22))
    head.limb(at(0.6, 0, 5.42), at(0.94, 0, 4.98), 0.16 * K, 0.21 * K, n=12)
    head.ball(at(0.98, 0, 4.93), big(0.23, 0.21, 0.21))
    for s in (-1, 1):
        head.ball(at(0.86, s * 0.15, 4.89), big(0.12, 0.11, 0.1))
    head.done('head', stone, parent=root)
    face = Batch()
    for s in (-1, 1):
        face.ball(at(0.6, s * 0.27, 5.31), 0.062 * K, n=12)
    face.done('eyes', eye, parent=root)
    teeth = Batch()
    for k in range(8):  # a grin full of them
        teeth.ball(at(0.6 - 0.014 * abs(k - 3.5), (k - 3.5) * 0.09, 4.735 + 0.01 * abs(k - 3.5)), big(0.03, 0.05, 0.045), n=8)
    teeth.done('teeth', tooth, parent=root)
    pit = Batch()
    pit.ball(at(0.5, 0, 4.7), big(0.115, 0.4, 0.085))
    for s in (-1, 1):
        pit.ball(at(0.655, s * 0.27, 5.31), 0.028 * K, n=8)
        pit.ball(at(0.56, s * 0.27, 5.32), big(0.07, 0.12, 0.09))  # the shadow the eye sits in
    pit.done('mouth', dark, parent=root)

    # ---- Straw brows that bristle, a little moustache under the nose and a fringe of beard along the jaw.
    whiskers = Batch()
    for s in (-1, 1):
        for k in range(34):
            y = s * (0.07 + 0.5 * k / 33)
            base = at(0.68 - 0.22 * (k / 33) ** 2, y, 5.44)
            whiskers.cone(base, base + Vector((0.22 + rnd.uniform(-0.05, 0.1), s * rnd.uniform(0.0, 0.16), rnd.uniform(-0.04, 0.1))), 0.03, 0.008, n=5)
    for k in range(30):
        y = rnd.uniform(-0.3, 0.3)
        base = at(0.64 - 0.3 * y * y, y, 4.81)
        whiskers.cone(base, base + Vector((0.05, y * 0.3, -rnd.uniform(0.03, 0.07))), 0.022, 0.008, n=5)
    for k in range(120):
        t = rnd.uniform(-1, 1)
        y, x = 0.6 * t, 0.56 - 0.5 * t * t
        base = at(x + rnd.uniform(-0.04, 0.04), y, 4.42 + 0.3 * t * t)
        whiskers.cone(base, base + Vector((rnd.uniform(0.0, 0.1), t * 0.1, -rnd.uniform(0.25, 0.5))), 0.03, 0.008, n=5)
    whiskers.done('whiskers', straw, parent=root)

    # ---- Long, wild dark hair down his back, and on it the crown: a heap of fern fronds, with flowers among them.
    mane = Batch()
    for k in range(620):
        ang = rnd.uniform(math.radians(58), math.radians(302))  # all round but the face
        z0 = rnd.uniform(5.2, 5.9)
        r0 = 0.64 * math.sqrt(max(0.05, 1 - ((z0 - 5.15) / 0.84) ** 2))
        reach = lambda r, t_, q_: at(0.04 + r * 0.95 * math.cos(ang) + 0.07 * math.sin(wave + q_ * 2), r * 1.05 * math.sin(ang) + 0.07 * math.cos(wave + q_ * 2.3), t_)
        end, wave = rnd.uniform(3.7, 4.6), rnd.uniform(0, 6.3)
        point = reach(r0, z0, 0)
        for q in range(5):
            t = (q + 1) / 5
            nxt = reach(r0 + 0.3 * t, z0 + (end - z0) * t, q + 1)
            mane.cone(point, nxt, 0.028 - 0.004 * q, 0.024 - 0.004 * q, n=4)
            point = nxt
    mane.done('hair', hair, parent=root)
    fronds = [Batch() for _ in fern]
    blooms = [Batch() for _ in petals]
    for k in range(300):
        ang, high = rnd.uniform(0, 2 * math.pi), rnd.uniform(0.0, 1.0) ** 0.7  # where on the top of his head it grows
        ring = 0.66 * math.sqrt(1 - (high * 0.9) ** 2)
        base = at(0.06 + ring * math.cos(ang), ring * 1.08 * math.sin(ang), 5.45 + 0.62 * high)
        rise = 0.15 + 1.1 * high + rnd.uniform(-0.25, 0.25)
        way = Vector((math.cos(ang) * math.cos(rise), math.sin(ang) * math.cos(rise), math.sin(rise)))
        length = rnd.uniform(0.5, 1.0)
        f = fronds[k % len(fronds)]
        across = way.cross(Z).normalized() if abs(way.z) < 0.99 else Vector((1, 0, 0))
        facing = across.cross(way)
        droop = Vector((0, 0, -0.25 * length))  # a frond bends over at its tip
        f.leaf(base, base + way * length + droop, 0.05, facing)  # the rib, and then the leaflets off it in pairs
        for q in range(1, 10):
            t = q / 10
            spot = base + way * length * t + droop * t * t
            size = 0.24 * math.sin(math.pi * q / 10.5) + 0.05
            for side in (-1, 1):
                f.leaf(spot, spot + (across * side + way * 0.45).normalized() * size, 0.075, facing)
        if k % 7 == 0:
            blooms[k % len(blooms)].ball(base + way * length * rnd.uniform(0.3, 0.8), rnd.uniform(0.035, 0.055), n=8)
    # ---- The garlands: two ropes of leaves from his shoulders down past the belt, with small flowers in them.
    for s in (-1, 1):
        for k in range(60):
            t = k / 59
            z = 4.32 - 2.75 * t
            bulge = 0.72 * math.sqrt(max(0.0, 1 - ((z - 3.3) / 1.2) ** 2)) + 0.14
            centre = body(max(0.5, bulge) + 0.06, s * (0.52 - 0.12 * math.sin(math.pi * t)), z)
            for q in range(6):
                way = Vector((rnd.uniform(0.2, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 0.5))).normalized()
                fronds[(k + q) % len(fronds)].leaf(centre, centre + way * rnd.uniform(0.16, 0.3), 0.1, Vector((1, 0, 0.3)))
            if k % 2 == 0:
                blooms[(k * 3 + (s > 0)) % len(blooms)].ball(centre + Vector((0.07, rnd.uniform(-0.08, 0.08), rnd.uniform(-0.05, 0.05))), rnd.uniform(0.028, 0.045), n=8)
    for i, f in enumerate(fronds):
        f.done(f'fern {i}', fern[i], parent=root)
    for i, f in enumerate(blooms):
        f.done(f'flowers {i}', petals[i], parent=root)
    return root


def clear():
    for ob in [ob for ob in bpy.data.objects if ob.type in ('MESH', 'EMPTY', 'CAMERA')]:
        bpy.data.objects.remove(ob)


def main():
    from PIL import Image
    out = arg('out', ROOT + '/out/models/bolster')
    os.makedirs(out, exist_ok=True)
    only, place = arg('only', ''), arg('place', '')
    scene = stage(sun=250.0 if place or only == 'map' else 150.0)
    scene.render.film_transparent = True  # every picture is laid on a plain ground afterwards
    render = lambda path: (setattr(scene.render, 'filepath', path), bpy.ops.render.render(write_still=True))

    def flat_camera(turn, metres, wide, high):
        """A camera level with his middle and without perspective, looking at him from `turn` degrees round."""
        cam = bpy.data.cameras.new('camera')
        ob = bpy.data.objects.new('camera', cam)
        scene.collection.objects.link(ob)
        cam.type, cam.ortho_scale, cam.clip_end = 'ORTHO', metres, 500
        a = math.radians(turn)
        ob.location = (60 * math.cos(a), 60 * math.sin(a), 3.3)
        ob.rotation_euler = (Vector((0, 0, 3.3)) - Vector(ob.location)).to_track_quat('-Z', 'Y').to_euler()
        scene.camera = ob
        scene.render.resolution_x, scene.render.resolution_y = wide, high

    if place:
        onto = Image.open(arg('onto', ROOT + '/out/deep/churchtown-45/picture.jpg')).convert('RGB')
        per_metre, metres = float(arg('scale', '32')), 16.0
        spots = [[float(v) for v in q.split(',')] for q in place.split('/')]
        for i, (px, py, way) in enumerate(spots):
            clear()
            root = build(0.1 + 0.3 * i)
            ground().is_shadow_catcher = True
            map_camera(45, metres, 1024)
            heading(root, way)
            render(f'{out}/sprite-{i}.png')
            size = round(metres * per_metre)
            sprite = Image.open(f'{out}/sprite-{i}.png').resize((size, size), Image.LANCZOS)
            onto.paste(sprite, (round(px - size / 2), round(py - size / 2)), sprite)
        onto.save(f'{out}/placed.png')
        px, py = spots[0][:2]
        onto.crop((int(px - 600), int(py - 440), int(px + 600), int(py + 360))).save(f'{out}/placed-close.png')
        return
    if only in ('', 'turn'):  # his four sides, standing, as on the sheet he was made after
        clear()
        build(None)
        ground((176, 176, 176))
        sheet = Image.new('RGB', (4 * 620, 900), (176, 176, 176))
        for i, turn in enumerate((0, -45, -90, 180)):
            flat_camera(turn, 7.6, 620, 900)
            render(f'{out}/turn-{i}.png')
            tile = Image.open(f'{out}/turn-{i}.png')
            sheet.paste(tile, (620 * i, 0), tile)
        sheet.save(f'{out}/turn.png')
    if only in ('', 'walk'):  # six moments of a step, from his right
        sheet = Image.new('RGB', (6 * 520, 800), (176, 176, 176))
        for i in range(6):
            clear()
            build(i / 6 * 0.5 + 0.02)
            ground((176, 176, 176))
            flat_camera(-90, 7.4, 520, 800)
            render(f'{out}/walk-{i}.png')
            tile = Image.open(f'{out}/walk-{i}.png')
            sheet.paste(tile, (520 * i, 0), tile)
        sheet.save(f'{out}/walk.png')
    if only in ('', 'map'):  # as the map sees him, walking eight ways, with his shadow
        clear()
        root = build(0.1)
        ground().is_shadow_catcher = True
        map_camera(45, 13.0, 640)
        sheet = Image.new('RGB', (640 * 4, 640 * 2), (112, 114, 112))
        for i in range(8):
            heading(root, 45 * i)
            render(f'{out}/map-{i}.png')
            tile = Image.open(f'{out}/map-{i}.png')
            sheet.paste(tile, (640 * (i % 4), 640 * (i // 4)), tile)
        sheet.save(f'{out}/map.png')


if __name__ == '__main__':
    main()
