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
  uv run deep/models/bolster.py --sprites        him for the viewer to walk about: from each of the map's four views,
                                                 walking sixteen ways, twenty-four moments of a stride to each, as
                                                 small sheets in out/sprites/bolster/ (site.sh takes them from there).
                                                 Without a shadow: the viewer casts his from where the sun really is.
                                                 It is an hour's work and can be cut short: every picture is kept
                                                 (out/sprites/bolster-cells/) and not made twice. --part 0/3 makes
                                                 a third of them, to run three at once; the last to end joins them
  --samples 64    rays through every pixel

He faces along x, y is to his left, z is up, in metres, feet on the ground at the middle.
"""
import math, os, random, sys
import bpy
import bmesh  # only after bpy: it comes with it
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from defender import ROOT, arg, flag, ground, heading, linear, map_camera, stage  # noqa: E402

HIP, SHOULDER = 2.5, 4.2  # the joints above the ground when he stands
THIGH, SHIN, UPPER, FORE = 1.15, 1.12, 1.08, 0.95
PACE = 3.0  # the length of a step: the map gives him 3.5 m on the level, more than these legs can do without the splits
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


def granite(name, colour=(140, 132, 120), lichen=(168, 120, 56), moss=(104, 108, 70)):
    """Weathered stone: grey and speckled, with patches of ochre lichen and a little moss, and dark cracks."""
    m = matter(name, colour, 0.92, other=lichen, amount=0.9, grain=1.7, bump=0.0, grime=0.9)
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    link = nt.links.new
    where = next(n for n in nt.nodes if n.bl_idname == 'ShaderNodeTexCoord').outputs['Object']

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

    def noise(scale, detail=8.0):
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

    c = b.inputs['Base Color'].links[0].from_socket
    c = towards(ramp(noise(3.3), 0.56, 0.7, 0.0, 0.5), c, linear(moss))
    c = towards(ramp(noise(42.0, 2.0), 0.35, 0.65, 0.35, 0.0), c, (0.012, 0.012, 0.012, 1.0))  # the dark grains in it
    cells = new('ShaderNodeTexVoronoi', feature='DISTANCE_TO_EDGE')
    cells.inputs['Scale'].default_value = 1.5
    link(where, cells.inputs['Vector'])
    some = new('ShaderNodeMath', operation='MULTIPLY')  # a crack here and there, not a net of them
    link(ramp(cells.outputs['Distance'], 0.0, 0.014, 1.0, 0.0), some.inputs[0])
    link(ramp(noise(1.1, 3.0), 0.45, 0.6, 0.0, 1.0), some.inputs[1])
    crack = some.outputs[0]
    c = towards(crack, c, (0.02, 0.018, 0.016, 1.0))
    link(c, b.inputs['Base Color'])
    height = new('ShaderNodeMath', operation='SUBTRACT')
    link(noise(9.0), height.inputs[0])
    link(crack, height.inputs[1])
    lumps = new('ShaderNodeBump')
    lumps.inputs['Strength'].default_value, lumps.inputs['Distance'].default_value = 0.9, 0.1
    link(height.outputs[0], lumps.inputs['Height'])
    link(lumps.outputs[0], b.inputs['Normal'])
    return m


def carve(name, lumps, material, parent, at, facets=0.14, grain=0.04):
    """One piece of stone from many lumps that run into each other, some of them taken away again (eye sockets, a
    mouth, a crease). Then most of its faces are thrown out, so that what is left is flat cuts, as hewn stone has."""
    mb = bpy.data.metaballs.new(name)
    mb.resolution = mb.render_resolution = grain
    clay = bpy.data.objects.new(name + ' clay', mb)
    bpy.context.scene.collection.objects.link(clay)
    for centre, radii, take in lumps:
        el = mb.elements.new(type='ELLIPSOID')
        el.co, el.radius = centre, 1.74  # at this radius a lump alone comes out the size it was asked for
        el.size_x, el.size_y, el.size_z = radii
        el.use_negative, el.stiffness = take, 3.0 if take else 2.0
    bpy.context.view_layer.update()
    me = bpy.data.meshes.new_from_object(clay.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(clay)
    bpy.data.metaballs.remove(mb)
    for f in me.polygons:
        f.use_smooth = False
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(material)
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new('hew', 'DECIMATE').ratio = facets
    ob.matrix_world = at
    world = ob.matrix_world.copy()
    ob.parent = parent
    ob.matrix_world = world
    return ob


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
    """Where his joints are. `step` runs from 0 to 1 over a stride of two paces: in the first half his left foot is
    in the air, in the second his right. None is standing still with the arms a little out, as on the sheet of his
    four sides.

    The feet do what the viewer has always had them do (bolsterBody in viewer/index.html), so that a foot that is
    down stays where it is on the road while he goes over it: the standing foot goes back under him at an even pace,
    the other stays down for the first seventh of the step while the weight comes over, then swings through, slow at
    both ends, heel up first, toes up to land. The hips sink with both feet down and rise over the standing leg. The
    knees are found from where hip and ankle are."""
    out = {'legs': {}, 'arms': {}, 'lift': 0.0}
    if step is None:
        for s in (-1, 1):
            hip = Vector((0, s * 0.43, HIP))
            knee = hip + THIGH * Vector((math.sin(0.04), 0, -math.cos(0.04)))
            out['legs'][s] = (hip, knee, Vector((0, s * 0.43, SOLE)), Matrix.Identity(4))
            shoulder = Vector((0, s * 1.2, SHOULDER))
            elbow = shoulder + UPPER * Vector((0, s * 0.24, -1)).normalized()
            wrist = elbow + FORE * Vector((math.sin(0.28), s * 0.15, -math.cos(0.28))).normalized()
            out['arms'][s] = (shoulder, elbow, wrist)
        return out
    step %= 1.0
    air, ph = (1 if step < 0.5 else -1), (step * 2) % 1.0
    u = min(1.0, max(0.0, (ph - 0.14) / 0.86))
    go = (1 - math.cos(math.pi * u)) / 2
    reach = THIGH + SHIN
    drop = 0.8 * (reach - math.sqrt(reach * reach - PACE * PACE / 4)) * (1 + math.cos(2 * math.pi * ph)) / 2
    out['lift'] = -drop
    tilt = math.sin(math.pi * u) * (0.5 * u - 0.55 * (1 - u)) - 0.35 * (1 - u) ** 3 if u > 0 else -0.35 * ph / 0.14
    feet = {air: (-PACE / 2 + 2 * PACE * go - PACE * ph, 0.42 * math.sin(math.pi * u) ** 1.3, tilt), -air: (PACE / 2 - PACE * ph, 0.0, 0.0)}
    for s in (-1, 1):
        x, up_, toes = feet[s]
        hip = Vector((0, s * 0.43, HIP))
        # The ankle: above the sole, and higher when the foot is tipped, so that neither toe nor heel goes into the road.
        want = Vector((x, s * 0.43, drop + SOLE + up_ + max(0.0, -toes) * 0.75 + max(0.0, toes) * 0.3))
        d = min((want - hip).length, reach - 0.002)
        ankle = hip + (want - hip).normalized() * d
        along = math.atan2(ankle.x - hip.x, hip.z - ankle.z)  # the leg's angle forward of straight down
        bend = math.acos(max(-1.0, min(1.0, (THIGH * THIGH + d * d - SHIN * SHIN) / (2 * THIGH * d))))
        knee = hip + THIGH * Vector((math.sin(along + bend), 0, -math.cos(along + bend)))  # knees bend forward
        out['legs'][s] = (hip, knee, ankle, Matrix.Rotation(-toes, 4, 'Y'))
        swing = s * math.radians(21) * math.cos(2 * math.pi * step)  # an arm goes forward as the leg on its side goes back
        elbow_bend = math.radians(16) + math.radians(18) * max(0.0, swing / math.radians(21))
        shoulder = Vector((0, s * 1.2, SHOULDER))
        elbow = shoulder + UPPER * Vector((math.sin(swing), s * 0.1, -math.cos(swing))).normalized()
        wrist = elbow + FORE * Vector((math.sin(swing + elbow_bend), s * 0.06, -math.cos(swing + elbow_bend))).normalized()
        out['arms'][s] = (shoulder, elbow, wrist)
    return out


def build(step=None):
    rnd = random.Random(3)
    root = bpy.data.objects.new('bolster', None)
    bpy.context.scene.collection.objects.link(root)
    stone = granite('stone')
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

    # ---- The head: one piece of hewn stone. A heavy brow, a great hooked nose, cheekbones, a jaw, and cut into it
    # two deep eye sockets and a wide grin. A big head: he is a giant of a tale. It is made where it would be if he
    # stood still, and then moved with him, so that the lichen stays where it is on his face as he walks.
    K = 1.17
    rest = lambda x, y, z: Vector((0.06 + (x - 0.06) * K, y * K, 5.02 + (z - 5.15) * K))
    nod = body(0, 0, 5.1) - Vector((0, 0, 5.1))
    at = lambda x, y, z: rest(x, y, z) + nod
    big = lambda *r: tuple(v * K for v in r)
    lumps = [((0.04, 0, 5.18), (0.56, 0.64, 0.74), False), ((0.0, 0, 4.42), (0.42, 0.46, 0.42), False),  # skull, neck
             ((0.30, 0, 4.52), (0.36, 0.54, 0.26), False), ((0.52, 0, 4.4), (0.17, 0.26, 0.15), False),  # jaw, chin
             ((0.5, 0, 5.5), (0.2, 0.6, 0.13), False),  # brow
             ((0.66, 0, 5.34), (0.13, 0.13, 0.16), False), ((0.82, 0, 5.14), (0.16, 0.15, 0.18), False), ((0.97, 0, 4.94), (0.2, 0.19, 0.18), False),  # nose
             ((0.56, 0, 4.85), (0.11, 0.38, 0.065), False), ((0.53, 0, 4.55), (0.11, 0.34, 0.065), False),  # lips
             ((0.7, 0, 4.7), (0.22, 0.36, 0.07), True)]  # the grin
    for s in (-1, 1):
        lumps += [((0.56, s * 0.3, 5.5), (0.14, 0.2, 0.11), False), ((0.84, s * 0.16, 4.9), (0.11, 0.1, 0.09), False),  # brow, nostril
                  ((0.44, s * 0.42, 5.02), (0.2, 0.2, 0.18), False),  # cheekbone
                  ((0.68, s * 0.27, 5.33), (0.14, 0.13, 0.09), True),  # eye socket
                  ((0.58, s * 0.36, 4.76), (0.12, 0.08, 0.07), True)]  # the corner of the grin, turned up
        lumps += [((0.72 - 0.06 * q, s * (0.24 + 0.08 * q), 4.96 - 0.07 * q), (0.05, 0.04, 0.05), True) for q in range(3)]  # a crease from nose to mouth
        lumps += [((0.58, s * 0.2, 5.72 + 0.06 * s), (0.04, 0.2, 0.025), True)]  # a line across the forehead
    carve('head', [(tuple(rest(*c)), big(*r), take) for c, r, take in lumps], stone, root, Matrix.Translation(nod))
    face = Batch()
    for s in (-1, 1):
        face.ball(at(0.565, s * 0.27, 5.33), 0.05 * K, n=12)
    face.done('eyes', eye, parent=root)
    teeth = Batch()
    for k in range(7):  # a grin full of square teeth, a row above and a row below
        y = (k - 3) * 0.094
        teeth.cone(at(0.6 - 0.02 * abs(k - 3), y, 4.7 + 0.012 * abs(k - 3)), at(0.6 - 0.02 * abs(k - 3), y, 4.785 + 0.012 * abs(k - 3)), 0.056 * K, 0.056 * K, n=4)
    for k in range(6):
        y = (k - 2.5) * 0.094
        teeth.cone(at(0.56 - 0.02 * abs(k - 2.5), y, 4.615), at(0.56 - 0.02 * abs(k - 2.5), y, 4.685), 0.052 * K, 0.052 * K, n=4)
    teeth.done('teeth', tooth, parent=root, smooth=False)
    pit = Batch()
    pit.ball(at(0.42, 0, 4.7), big(0.14, 0.36, 0.1))
    for s in (-1, 1):
        pit.ball(at(0.608, s * 0.265, 5.325), 0.022 * K, n=8)
    pit.done('mouth', dark, parent=root)

    # ---- Straw brows that bristle, and a fringe of beard along the jaw, longest under the chin.
    whiskers = Batch()
    for s in (-1, 1):
        for k in range(46):
            y = s * (0.07 + 0.52 * (k % 23) / 22)
            base = at(0.69 - 0.2 * ((k % 23) / 22) ** 2, y, 5.5 + (0.05 if k >= 23 else 0))
            whiskers.cone(base, base + Vector((0.2 + rnd.uniform(-0.05, 0.1), s * rnd.uniform(0.02, 0.2), rnd.uniform(0.0, 0.16))), 0.03, 0.008, n=5)
    for k in range(260):
        t = rnd.uniform(-1, 1)
        y, x = 0.6 * t, 0.66 - 0.5 * t * t
        base = at(x + rnd.uniform(-0.04, 0.04), y, 4.5 + 0.4 * t * t + rnd.uniform(-0.06, 0.04))
        whiskers.cone(base, base + Vector((rnd.uniform(0.02, 0.14), t * 0.14, -rnd.uniform(0.18, 0.4) * (1.5 - t * t))), 0.03, 0.008, n=5)
    whiskers.done('whiskers', straw, parent=root)

    # ---- Long, wild dark hair down his back, and on it the crown: a heap of fern fronds, with flowers among them.
    mane = Batch()
    for k in range(1150):
        ang = rnd.uniform(math.radians(58), math.radians(302))  # all round but the face
        z0 = rnd.uniform(5.2, 5.9)
        r0 = 0.64 * math.sqrt(max(0.05, 1 - ((z0 - 5.15) / 0.84) ** 2))
        reach = lambda r, t_, q_: at(0.04 + r * 0.95 * math.cos(ang) + 0.11 * math.sin(wave + q_ * 2), r * 1.05 * math.sin(ang) + 0.11 * math.cos(wave + q_ * 2.3), t_)
        end, wave = rnd.uniform(3.7, 4.6), rnd.uniform(0, 6.3)
        point = reach(r0, z0, 0)
        for q in range(9):
            t = (q + 1) / 9
            nxt = reach(r0 + 0.36 * t, z0 + (end - z0) * t, (q + 1) * 0.45)
            mane.cone(point, nxt, 0.018 - 0.0013 * q, 0.0167 - 0.0013 * q, n=4)
            point = nxt
    mane.done('hair', hair, parent=root)
    fronds = [Batch() for _ in fern]
    blooms = [Batch() for _ in petals]
    for k in range(300):
        ang, high = rnd.uniform(0, 2 * math.pi), rnd.uniform(0.0, 1.0) ** 0.7  # where on the top of his head it grows
        ring = 0.66 * math.sqrt(1 - (high * 0.9) ** 2)
        base = at(0.06 + ring * math.cos(ang), ring * 1.08 * math.sin(ang), 5.62 + 0.46 * high)
        front = max(0.0, math.cos(ang))  # over his face the fronds stand up, so the brow shows
        rise = 0.15 + 0.55 * front + 1.1 * high + rnd.uniform(-0.25, 0.25)
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

    if flag('sprites'):
        # For the viewer: to each of the map's views and each way he can walk (north first, a sixteenth of a turn
        # further in each) a small sheet of the moments of a stride, six to a row. Small sheets, because a browser
        # holds a picture unpacked: all of him in one would be hundreds of megabytes on a phone, and this way it
        # holds only the way he is walking. The picture is aimed at his middle, RISE metres up, so that little of it
        # is empty; the viewer knows to set it that much above the spot he stands on.
        import json, time
        out, cells = ROOT + '/out/sprites/bolster', ROOT + '/out/sprites/bolster-cells'
        os.makedirs(out, exist_ok=True)
        os.makedirs(cells, exist_ok=True)
        metres, sharp, ways, frames, across, rise, looks = 9.0, 48, 16, 24, 6, 3.2, (45, 135, 225, 315)
        cell = round(metres * sharp)
        part, parts = [int(v) for v in arg('part', '0/1').split('/')]
        name = lambda look, w, f: f'{cells}/{look}-{w}-{f}.png'
        began = time.time()
        for f in range(frames):
            todo = [(look, w) for look in looks for w in range(ways) if not os.path.exists(name(look, w, f))]
            if f % parts != part or not todo:
                continue
            clear()
            root = build(f / frames)
            ground().visible_camera = False  # the road still throws its light up at him, and is not in the picture
            for look in looks:
                for ob in [ob for ob in bpy.data.objects if ob.type == 'CAMERA']:
                    bpy.data.objects.remove(ob)
                map_camera(look, metres, cell)
                scene.camera.location.z += rise
                for w in range(ways):
                    if (look, w) in todo:
                        heading(root, 360 / ways * w)
                        render(name(look, w, f) + '.part.png')
                        os.replace(name(look, w, f) + '.part.png', name(look, w, f))
            print('moment', f + 1, 'of', frames, 'done,', round((time.time() - began) / 60), 'minutes in', flush=True)
        if not all(os.path.exists(name(look, w, f)) for look in looks for w in range(ways) for f in range(frames)):
            print('not every picture is there yet: the sheets are joined by the run that finds them all')
            return
        for old in os.listdir(out):
            os.remove(f'{out}/{old}')
        for look in looks:
            for w in range(ways):
                sheet = Image.new('RGBA', (cell * across, cell * (frames // across)), (0, 0, 0, 0))
                for f in range(frames):
                    sheet.paste(Image.open(name(look, w, f)), (cell * (f % across), cell * (f // across)))
                for size in (48, 24, 12):
                    small = sheet if size == sharp else sheet.resize((sheet.width * size // sharp, sheet.height * size // sharp), Image.LANCZOS)
                    small.save(f'{out}/bolster-{look}-{size}-{w}.webp', quality=86, method=4)
        json.dump({'metres': metres, 'rise': rise, 'ways': ways, 'frames': frames, 'across': across, 'sizes': [12, 24, 48], 'looks': list(looks),
                   'file': 'bolster-{look}-{size}-{way}.webp'}, open(f'{out}/sprite.json', 'w'))
        print('sheets joined')
        return
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
    if only == 'face':  # close to, from the front and from his right, to hold against the pictures he was made after
        clear()
        build(None)
        sheet = Image.new('RGB', (2 * 800, 900), (176, 176, 176))
        for i, turn in enumerate((-12, -60)):
            flat_camera(turn, 2.9, 800, 900)
            scene.camera.location.z = scene.camera.location.z + 1.95
            render(f'{out}/face-{i}.png')
            tile = Image.open(f'{out}/face-{i}.png')
            sheet.paste(tile, (800 * i, 0), tile)
        sheet.save(f'{out}/face.png')
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
            build(i / 6)
            ground((176, 176, 176))
            flat_camera(-90, 7.4, 520, 800)
            render(f'{out}/walk-{i}.png')
            tile = Image.open(f'{out}/walk-{i}.png')
            sheet.paste(tile, (520 * i, 0), tile)
        sheet.save(f'{out}/walk.png')
    if only in ('', 'map'):  # as the map sees him, walking eight ways, with his shadow
        clear()
        root = build(0.2)
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
