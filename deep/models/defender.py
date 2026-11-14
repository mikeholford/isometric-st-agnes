# /// script
# requires-python = "==3.13.*"
# dependencies = ["bpy==5.3.0", "pillow"]
# ///
"""Mike's Land Rover: a blue Defender 110 station wagon of 1995, built in Blender by rule, to drive on the map.

Nothing here is traced from a drawing. The sizes are the ones Land Rover gives for a 110 (a wheelbase of 2.794 m,
1.79 m wide, a little over 2 m high), and what makes it this car is taken from four photographs: slate blue paint
gone matt, a white roof, white steel wheels with all-terrain tyres, a black cage of tubes outside the body, a
snorkel up the right-hand screen pillar, chequer plate on the wings, the spare wheel on the back door, an awning
rolled up along the left of the roof.

  uv run deep/models/defender.py                 pictures from where the four photographs were taken, and the car
                                                 as the map sees it from eight sides, in out/models/defender/
  uv run deep/models/defender.py --only map      just one of them: front, side, rear, quarter or map
  uv run deep/models/defender.py --place 1340,925,45
                                                 the car stood in the picture of a deep place (out/deep/churchtown-45/
                                                 picture.jpg, or --onto another): where in the picture, in its pixels,
                                                 and which way the car points, in degrees clockwise from north.
                                                 Several cars: 1340,925,45/600,300,135
  --samples 64    rays through every pixel
  --device cpu    cpu or gpu
  --bag           with the black bag on the roof, as on the mountain road
  --plate "AB12 CDE"   the registration to letter the number plates with. Without it they are blank: the real one
                  is not written down in here, since this file is open for anyone to read

The car stands on its wheels at the middle of its wheelbase: x runs forward, y to its left, z up, in metres.
build() makes it and returns everything it made, so that a renderer of sprites can call it too.
"""
import math, os, sys
import bpy
import bmesh  # only after bpy: it comes with it
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
arg = lambda name, fallback: sys.argv[sys.argv.index('--' + name) + 1] if '--' + name in sys.argv else fallback
flag = lambda name: '--' + name in sys.argv

AXLE = 1.397  # half the wheelbase
TRACK = 0.745  # middle of a tyre from the middle of the car
TYRE_R, TYRE_W = 0.405, 0.25
BODY, CABIN = 0.845, 0.785  # half the width of the body below the waist, and of the cabin above it
WAIST, GUTTER, ROOF = 1.20, 1.86, 2.04
REAR, BULKHEAD, NOSE = -2.34, 0.80, 1.92
SCREEN = lambda z: BULKHEAD - (z - WAIST) * 0.18 / (GUTTER - WAIST)  # the windscreen leans back a little


def linear(c):
    """A colour as it is written for a screen (0 to 255) to what the renderer counts in."""
    return tuple(((v / 255 + 0.055) / 1.055) ** 2.4 if v / 255 > 0.04045 else v / 255 / 12.92 for v in c) + (1.0,)


def paint(name, colour, rough=0.5, metal=0.0, coat=0.0, glow=0.0, wear=None, clear=False, root=None):
    """A material. `wear` is what thirty years outdoors have done to it, as four amounts from 0 to 1: dust thrown up
    from the road (thick by the sills, none on the roof), dirt gathered where parts meet, paint bleached chalky
    where it faces the sun, and how unevenly all of that lies. It is laid out in the car's own measure (`root`), so
    a patch of dirt stays on its panel whichever way the car is turned."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = linear(colour)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    b.inputs['Coat Weight'].default_value = coat
    if clear:
        b.inputs['Transmission Weight'].default_value, b.inputs['IOR'].default_value = 1.0, 1.45
    if glow:
        b.inputs['Emission Color'].default_value = linear(colour)
        b.inputs['Emission Strength'].default_value = glow
    if not wear:
        return m
    dust, grime, fade, vary = wear
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

    def noise(scale, detail=5.0):
        n = new('ShaderNodeTexNoise')
        n.inputs['Scale'].default_value, n.inputs['Detail'].default_value = scale, detail
        link(where, n.inputs['Vector'])
        return n.outputs['Fac']

    def times(x, y):
        n = new('ShaderNodeMath', operation='MULTIPLY')
        link(x, n.inputs[0])
        link(y, n.inputs[1])
        return n.outputs[0]

    def towards(amount, colour_socket, other):
        n = new('ShaderNodeMixRGB')
        link(amount, n.inputs[0])
        link(colour_socket, n.inputs[1])
        n.inputs[2].default_value = other
        return n.outputs[0]

    coords = new('ShaderNodeTexCoord')
    coords.object = root
    where = coords.outputs['Object']
    c = new('ShaderNodeRGB').outputs[0]
    c.default_value = linear(colour)
    shade = new('ShaderNodeHueSaturation')  # no panel is one even colour
    link(c, shade.inputs['Color'])
    link(ramp(noise(1.1), 0.3, 0.7, 1 - vary, 1 + vary), shade.inputs['Value'])
    c = shade.outputs[0]
    facing = new('ShaderNodeSeparateXYZ')  # bleached where it faces the sky
    link(new('ShaderNodeNewGeometry').outputs['Normal'], facing.inputs[0])
    chalk = linear(tuple(v + (235 - v) * 0.45 for v in colour))
    c = towards(times(ramp(facing.outputs['Z'], 0.2, 1.0, 0.0, fade), ramp(noise(2.3), 0.35, 0.7, 0.3, 1.0)), c, chalk)
    height = new('ShaderNodeSeparateXYZ')  # dust from the road, thick low down
    link(where, height.inputs[0])
    dusty = times(ramp(height.outputs['Z'], 1.3, 0.3, 0.0, dust), ramp(noise(3.5, 8.0), 0.3, 0.75, 0.2, 1.0))
    c = towards(dusty, c, linear((150, 128, 100)))
    nook = new('ShaderNodeAmbientOcclusion', samples=4)  # dirt where parts meet
    nook.inputs['Distance'].default_value = 0.14
    c = towards(ramp(nook.outputs['AO'], 0.45, 0.95, grime, 0.0), c, (0.02, 0.018, 0.015, 1.0))
    link(c, b.inputs['Base Color'])
    dull = new('ShaderNodeMath', operation='MULTIPLY_ADD')  # dust takes the shine off
    link(dusty, dull.inputs[0])
    dull.inputs[1].default_value, dull.inputs[2].default_value = 0.35, rough
    link(dull.outputs[0], b.inputs['Roughness'])
    edge = new('ShaderNodeBevel', samples=4)  # no edge on a real car is a knife
    edge.inputs['Radius'].default_value = 0.012
    dents = new('ShaderNodeBump')
    dents.inputs['Strength'].default_value = 0.05
    link(noise(60.0, 2.0), dents.inputs['Height'])
    link(edge.outputs[0], dents.inputs['Normal'])
    link(dents.outputs[0], b.inputs['Normal'])
    return m


def build(bag=False, plate=''):
    made = []
    root = bpy.data.objects.new('defender', None)  # everything hangs on this: turn it and the whole car turns
    bpy.context.scene.collection.objects.link(root)
    worn = lambda name, colour, rough, wear, **more: paint(name, colour, rough, wear=wear, root=root, **more)
    # Wear is: dust from the road, dirt in the corners, bleaching by the sun, unevenness.
    blue = worn('slate blue', (46, 74, 108), 0.6, (0.6, 0.75, 0.24, 0.09), coat=0.1)  # thirty years old: more chalk than shine
    white = worn('white', (226, 226, 216), 0.55, (0.6, 0.8, 0.0, 0.05))
    black = worn('black', (18, 18, 20), 0.6, (0.42, 0.3, 0.16, 0.08))
    rubber = worn('rubber', (15, 15, 15), 0.9, (0.55, 0.2, 0.1, 0.1))
    glass = worn('glass', (150, 170, 165), 0.03, (0.5, 0.5, 0.0, 0.03), clear=True)
    chrome = paint('chrome', (225, 228, 230), 0.16, metal=1.0)
    lens = worn('lens', (228, 232, 235), 0.1, (0.4, 0.5, 0.0, 0.03), coat=1.0, glow=0.1)
    amber = worn('amber', (240, 130, 22), 0.2, (0.4, 0.5, 0.0, 0.03), coat=1.0, glow=0.08)
    red = worn('red', (175, 22, 20), 0.2, (0.4, 0.5, 0.0, 0.03), coat=1.0, glow=0.06)
    plate_front = worn('white plate', (240, 240, 232), 0.35, (0.6, 0.4, 0.0, 0.04))
    plate_rear = worn('yellow plate', (246, 204, 24), 0.35, (0.6, 0.4, 0.0, 0.04))
    ink = paint('ink', (10, 10, 10), 0.6)
    chequer = worn('chequer plate', (30, 30, 32), 0.42, (0.3, 0.5, 0.4, 0.1), metal=0.6)
    canvas = worn('canvas', (150, 150, 146), 0.9, (0.2, 0.5, 0.3, 0.08))
    steel = worn('steel', (70, 70, 72), 0.5, (0.8, 0.5, 0.0, 0.1), metal=0.8)
    seat = paint('seat', (38, 38, 42), 0.85)
    cover = paint('seat cover', (150, 34, 30), 0.85)
    lining = paint('lining', (24, 24, 26), 0.9)
    smoked = paint('smoked glass', (16, 22, 28), 0.05, coat=1.0)  # for glass with nothing behind it

    def add(name, bm, material, bevel=0.0):
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name, me)
        ob.data.materials.append(material)
        bpy.context.scene.collection.objects.link(ob)
        if bevel:
            b = ob.modifiers.new('bevel', 'BEVEL')
            b.width, b.segments, b.limit_method, b.angle_limit = bevel, 2, 'ANGLE', math.radians(40)
        made.append(ob)
        return ob

    def hexa(name, low, high, material, bevel=0.0):
        """A block from its four lower corners and its four upper ones, each going round the same way."""
        bm = bmesh.new()
        v = [bm.verts.new(p) for p in list(low) + list(high)]
        for f in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            bm.faces.new([v[i] for i in f])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        return add(name, bm, material, bevel)

    def box(name, x, y, z, material, bevel=0.0):
        ring = lambda h: [(x[0], y[0], h), (x[1], y[0], h), (x[1], y[1], h), (x[0], y[1], h)]
        return hexa(name, ring(z[0]), ring(z[1]), material, bevel)

    def prism(name, outline, y, material, bevel=0.0):
        """A shape drawn from the side (x, z) and pushed through from one y to the other."""
        bm = bmesh.new()
        near = [bm.verts.new((px, y[0], pz)) for px, pz in outline]
        far = [bm.verts.new((px, y[1], pz)) for px, pz in outline]
        bm.faces.new(near)
        bm.faces.new(far[::-1])
        for i in range(len(outline)):
            j = (i + 1) % len(outline)
            bm.faces.new((near[j], near[i], far[i], far[j]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        return add(name, bm, material, bevel)

    def rod(name, a, b, r, material, r2=None, n=20, bevel=0.0):
        """A round bar from a to b; with r2, a cone."""
        a, b = Vector(a), Vector(b)
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=n, radius1=r, radius2=r if r2 is None else r2, depth=(b - a).length)
        for f in bm.faces:
            f.smooth = len(f.verts) == 4
        ob = add(name, bm, material, bevel)
        ob.matrix_world = Matrix.Translation((a + b) / 2) @ Vector((0, 0, 1)).rotation_difference(b - a).to_matrix().to_4x4()
        return ob

    def tube(name, points, r, material):
        """A bent tube: bars from point to point, with a ball in every bend."""
        for i in range(len(points) - 1):
            rod(f'{name} {i}', points[i], points[i + 1], r, material, n=14)
        for i, p in enumerate(points[1:-1]):
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=14, v_segments=8, radius=r)
            for f in bm.faces:
                f.smooth = True
            add(f'{name} bend {i}', bm, material).location = p

    def cut(ob, cutter):
        cutter.hide_render = cutter.hide_viewport = True
        cutter.display_type = 'WIRE'
        m = ob.modifiers.new('cut', 'BOOLEAN')
        m.operation, m.object, m.solver = 'DIFFERENCE', cutter, 'EXACT'
        ob.modifiers.move(len(ob.modifiers) - 1, 0)  # cut first, then round the edges

    def words(name, text, at, size, facing, material=ink):
        """Lettering standing on a surface that faces forward (+1) or backward (-1)."""
        cu = bpy.data.curves.new(name, 'FONT')
        cu.body, cu.size, cu.align_x, cu.align_y, cu.extrude, cu.space_line = text, size, 'CENTER', 'CENTER', 0.002, 0.95
        ob = bpy.data.objects.new(name, cu)
        ob.data.materials.append(material)
        bpy.context.scene.collection.objects.link(ob)
        ob.matrix_world = Matrix(((0, 0, facing, at[0]), (facing, 0, 0, at[1]), (0, 1, 0, at[2]), (0, 0, 0, 1)))
        made.append(ob)

    # The opening of a wheel arch seen from the side: square, with the top corners cut off, as Land Rover made them.
    arch = lambda x0, grow=0.0: [(x0 - 0.53 - grow, 0.2), (x0 - 0.53 - grow, 0.80 + grow * 0.4), (x0 - 0.38 - grow * 0.4, 0.95 + grow),
                                 (x0 + 0.38 + grow * 0.4, 0.95 + grow), (x0 + 0.53 + grow, 0.80 + grow * 0.4), (x0 + 0.53 + grow, 0.2)]

    # ---- The body below the waist: the tub behind the bulkhead, the two wings and what lies between them.
    tub = box('tub', (REAR, BULKHEAD), (-BODY, BODY), (0.47, WAIST), blue, 0.012)
    wings = [box(f'wing {s}', (BULKHEAD - 0.01, NOSE), (min(s * 0.50, s * BODY), max(s * 0.50, s * BODY)), (0.52, 1.13), blue, 0.015) for s in (-1, 1)]
    box('between the wings', (BULKHEAD - 0.01, NOSE - 0.02), (-0.51, 0.51), (0.52, 1.08), black)
    prism('bonnet', [(BULKHEAD - 0.02, 1.215), (NOSE + 0.01, 1.165), (NOSE + 0.01, 1.075), (BULKHEAD - 0.02, 1.075)], (-0.525, 0.525), blue, 0.02)
    for s in (-1, 1):
        for x0, body in ((-AXLE, tub), (AXLE, wings[0 if s < 0 else 1])):
            cut(body, prism(f'arch cut {x0} {s}', arch(x0), (s * 0.56, s * 1.2), black))
            box(f'arch back {x0} {s}', (x0 - 0.54, min(x0 + 0.54, NOSE - 0.03)), (s * 0.55, s * 0.57), (0.3, 0.97), black)
            flare = prism(f'arch flare {x0} {s}', arch(x0, 0.04), (s * (BODY - 0.03), s * (BODY + 0.04)), black, 0.01)
            cut(flare, prism(f'flare cut {x0} {s}', arch(x0), (s * 0.5, s * 1.3), black))
            cut(flare, box(f'flare foot {x0} {s}', (x0 - 0.8, x0 + 0.8), (s * 0.5, s * 1.3), (0, 0.50), black))
    box('chassis', (REAR + 0.1, NOSE - 0.1), (-0.5, 0.5), (0.36, 0.56), black)
    capping = box('capping', (REAR - 0.004, BULKHEAD), (-BODY - 0.004, BODY + 0.004), (WAIST - 0.012, WAIST + 0.016), blue, 0.006)

    # ---- The cabin and the roof.
    lo = [(REAR, -CABIN, WAIST), (BULKHEAD, -CABIN, WAIST), (BULKHEAD, CABIN, WAIST), (REAR, CABIN, WAIST)]
    hi = [(REAR, -CABIN, GUTTER), (SCREEN(GUTTER), -CABIN, GUTTER), (SCREEN(GUTTER), CABIN, GUTTER), (REAR, CABIN, GUTTER)]
    cabin = hexa('cabin', lo, hi, blue, 0.012)
    # The car is hollow, so that there is an inside to see through the glass.
    inside = hexa('inside', [(REAR + 0.05, -CABIN + 0.04, 0.62), (0.74, -CABIN + 0.04, 0.62), (0.74, CABIN - 0.04, 0.62), (REAR + 0.05, CABIN - 0.04, 0.62)],
                  [(REAR + 0.05, -CABIN + 0.04, GUTTER - 0.02), (SCREEN(GUTTER) - 0.04, -CABIN + 0.04, GUTTER - 0.02), (SCREEN(GUTTER) - 0.04, CABIN - 0.04, GUTTER - 0.02),
                   (REAR + 0.05, CABIN - 0.04, GUTTER - 0.02)], lining)
    for shell in (cabin, tub, capping):
        cut(shell, inside)

    def opening(name, cutter, rubber):
        """A hole for a window, through the wall and through the rubber that will hold the glass."""
        for ob in (cabin, rubber):
            cut(ob, cutter)
    box('gutter', (REAR - 0.02, SCREEN(GUTTER) + 0.03), (-CABIN - 0.02, CABIN + 0.02), (GUTTER - 0.01, GUTTER + 0.03), white, 0.008)
    box('roof', (REAR - 0.005, SCREEN(GUTTER) + 0.01), (-CABIN, CABIN), (GUTTER + 0.02, ROOF), white, 0.06)
    for y in (-0.42, -0.14, 0.14, 0.42):  # the ribs pressed into the roof
        box(f'roof rib {y}', (REAR + 0.25, SCREEN(GUTTER) - 0.25), (y - 0.025, y + 0.025), (ROOF - 0.004, ROOF + 0.01), white, 0.006)
    for s in (-1, 1):  # the little windows in the curve of the roof
        for x0, x1 in ((-2.05, -1.25), (-1.05, -0.25)):
            box(f'alpine light {s} {x0}', (x0, x1), (s * (CABIN - 0.012), s * (CABIN + 0.004)), (GUTTER + 0.05, ROOF - 0.075), smoked, 0.004)

    def pane(name, x, z, s):
        """A side window: black rubber round dark glass."""
        frame = box(name + ' rubber', (x[0] - 0.022, x[1] + 0.022), (s * (CABIN - 0.01), s * (CABIN + 0.003)), (z[0] - 0.022, z[1] + 0.022), rubber)
        opening(name, box(name + ' hole', x, (s * (CABIN - 0.07), s * (CABIN + 0.05)), z, rubber), frame)
        box(name, x, (s * (CABIN - 0.01), s * (CABIN + 0.007)), z, glass)

    for s in (-1, 1):
        pane(f'front door glass {s}', (-0.08, 0.60), (1.28, 1.80), s)
        pane(f'rear door glass {s}', (-1.00, -0.22), (1.28, 1.80), s)
        pane(f'side glass {s}', (-2.22, -1.14), (1.28, 1.80), s)
        box(f'side glass bar {s}', (-1.70, -1.67), (s * (CABIN - 0.01), s * (CABIN + 0.009)), (1.28, 1.80), rubber)  # it slides
        # Where the doors shut, a handle on each, a step under them.
        for x in (0.74, -0.15, -1.07):
            box(f'door gap {x} {s}', (x - 0.005, x + 0.005), (s * (BODY - 0.01), s * (BODY + 0.0015)), (0.52, WAIST - 0.02), ink)
            box(f'door gap above {x} {s}', (x - 0.005, x + 0.005), (s * (CABIN - 0.01), s * (CABIN + 0.0015)), (WAIST + 0.02, GUTTER - 0.02), ink)
        box(f'door sill {s}', (-0.60, 0.74), (s * (BODY - 0.01), s * (BODY + 0.0015)), (0.515, 0.525), ink)
        for x in (-0.13, -1.05):
            box(f'door handle {x} {s}', (x, x + 0.13), (s * BODY, s * (BODY + 0.022)), (1.085, 1.12), black, 0.006)
        box(f'side step {s}', (-0.95, 0.62), (s * (BODY + 0.005), s * (BODY + 0.135)), (0.385, 0.42), black, 0.008)
        for x in (-0.7, 0.35):
            box(f'step bracket {x} {s}', (x, x + 0.05), (s * 0.5, s * (BODY + 0.1)), (0.37, 0.39), black)
        box(f'chequer plate {s}', (BULKHEAD + 0.03, NOSE - 0.02), (s * 0.545, s * (BODY - 0.012)), (1.128, 1.136), chequer, 0.002)
        rod(f'side repeater {s}', (1.62, s * BODY, 1.0), (1.62, s * (BODY + 0.012), 1.0), 0.02, amber)
        box(f'mirror arm {s}', (0.70, 0.72), (s * CABIN, s * (CABIN + 0.12)), (1.37, 1.39), black)
        box(f'mirror {s}', (0.69, 0.73), (s * (CABIN + 0.08), s * (CABIN + 0.21)), (1.28, 1.47), black, 0.012)
        for x0, x in ((-AXLE, -AXLE - 0.52), (AXLE, AXLE - 0.52)):  # mud flaps behind the wheels
            box(f'mud flap {x0} {s}', (x - 0.012, x), (s * 0.60, s * 0.885), (0.16, 0.52), rubber)
    box('fuel filler', (-1.98, -1.82), (-BODY - 0.002, -BODY + 0.01), (0.98, 1.12), black, 0.004)

    # ---- The windscreen, its wipers, the vents under it.
    face = lambda z, out: SCREEN(z) + out
    for out, grow, m, name in ((0.003, 0.03, rubber, 'screen rubber'), (0.008, 0.0, glass, 'screen')):
        z0, z1, w = 1.29 - grow, 1.80 + grow, 0.70 + grow
        pane_ = hexa(name, [(face(z0, -0.02), -w, z0), (face(z0, out), -w, z0), (face(z0, out), w, z0), (face(z0, -0.02), w, z0)],
                     [(face(z1, -0.02), -w, z1), (face(z1, out), -w, z1), (face(z1, out), w, z1), (face(z1, -0.02), w, z1)], m)
        if grow:
            opening('screen', hexa('screen hole', [(face(1.29, -0.25), -0.70, 1.29), (face(1.29, 0.06), -0.70, 1.29), (face(1.29, 0.06), 0.70, 1.29), (face(1.29, -0.25), 0.70, 1.29)],
                                   [(face(1.80, -0.25), -0.70, 1.80), (face(1.80, 0.06), -0.70, 1.80), (face(1.80, 0.06), 0.70, 1.80), (face(1.80, -0.25), 0.70, 1.80)], rubber), pane_)
    for y in (-0.33, 0.27):
        rod(f'wiper {y}', (face(1.29, 0.02), y, 1.29), (face(1.52, 0.02), y + 0.33, 1.52), 0.007, black, n=8)
    for y in (-0.36, 0.36):
        box(f'vent flap {y}', (face(1.245, 0.0), face(1.245, 0.006)), (y - 0.22, y + 0.22), (1.222, 1.268), blue, 0.004)

    # ---- The face: grille, lamps, bumper, number plate.
    box('grille', (NOSE - 0.01, NOSE + 0.022), (-0.36, 0.36), (0.70, 1.07), black, 0.006)
    for k in range(7):
        box(f'grille bar {k}', (NOSE + 0.02, NOSE + 0.03), (-0.34, 0.34), (0.735 + k * 0.047, 0.755 + k * 0.047), black)
    box('bonnet badge', (NOSE + 0.008, NOSE + 0.016), (-0.17, 0.17), (1.09, 1.135), black, 0.003)
    words('bonnet lettering', 'DEFENDER', (NOSE + 0.017, 0, 1.1125), 0.034, 1, chrome)
    box('land rover oval', (NOSE + 0.03, NOSE + 0.034), (0.20, 0.30), (0.74, 0.78), paint('green oval', (20, 70, 40), 0.3), 0.003)
    for s in (-1, 1):
        box(f'lamp panel {s}', (NOSE - 0.01, NOSE + 0.016), (min(s * 0.37, s * 0.80), max(s * 0.37, s * 0.80)), (0.70, 1.07), black, 0.008)
        rod(f'headlamp rim {s}', (NOSE, s * 0.555, 0.90), (NOSE + 0.03, s * 0.555, 0.90), 0.098, chrome, n=32)
        rod(f'headlamp {s}', (NOSE, s * 0.555, 0.90), (NOSE + 0.04, s * 0.555, 0.90), 0.086, lens, r2=0.07, n=32)
        rod(f'side lamp {s}', (NOSE, s * 0.725, 0.995), (NOSE + 0.03, s * 0.725, 0.995), 0.037, lens)
        rod(f'indicator {s}', (NOSE, s * 0.725, 0.815), (NOSE + 0.03, s * 0.725, 0.815), 0.037, amber)
    box('bumper', (NOSE + 0.02, NOSE + 0.17), (-0.80, 0.80), (0.53, 0.675), black, 0.012)
    box('front plate', (NOSE + 0.17, NOSE + 0.176), (-0.26, 0.26), (0.548, 0.658), plate_front, 0.002)
    if plate:
        words('front plate lettering', plate, (NOSE + 0.177, 0, 0.603), 0.085, 1)

    # ---- The back: the door with the spare wheel on it, windows, lamps, the plate, the tow bar.
    def back(name, y, z, material, proud=0.004, bevel=0.0):
        return box(name, (REAR - proud, REAR + 0.01), y, z, material, bevel)

    for y in (-0.50, 0.36):
        back(f'back door gap {y}', (y - 0.005, y + 0.005), (0.62, GUTTER - 0.02), ink, 0.0015)
    back('back door sill', (-0.50, 0.36), (0.615, 0.625), ink, 0.0015)
    for name, y in (('back door glass', (-0.36, 0.22)), ('back glass left', (0.44, 0.72)), ('back glass right', (-0.72, -0.58))):
        frame = back(name + ' rubber', (y[0] - 0.022, y[1] + 0.022), (1.30, 1.79), rubber, 0.003)
        opening(name, box(name + ' hole', (REAR - 0.05, REAR + 0.09), y, (1.322, 1.768), rubber), frame)
        back(name, y, (1.322, 1.768), glass, 0.007)
    back('back door handle', (0.24, 0.32), (1.10, 1.16), black, 0.03, 0.006)
    for s in (-1, 1):
        rod(f'tail lamp {s}', (REAR, s * 0.755, 1.06), (REAR - 0.035, s * 0.755, 1.06), 0.04, red)
        rod(f'back indicator {s}', (REAR, s * 0.755, 0.93), (REAR - 0.035, s * 0.755, 0.93), 0.04, amber)
    rod('fog lamp', (REAR, 0.62, 0.66), (REAR - 0.03, 0.62, 0.66), 0.04, red)
    rod('reversing lamp', (REAR, -0.62, 0.66), (REAR - 0.03, -0.62, 0.66), 0.04, lens)
    back('back plate', (0.42, 0.72), (0.76, 0.985), plate_rear, 0.006, 0.002)
    if plate:  # the back plate is the square kind, in two lines
        words('back plate lettering', plate.replace(' ', '\n'), (REAR - 0.0065, 0.57, 0.875), 0.082, -1)
    oval = rod('uk oval', (REAR, -0.64, 1.10), (REAR - 0.005, -0.64, 1.10), 0.075, white, n=32)
    oval.scale = (1, 1.35, 1)
    words('uk lettering', 'UK', (REAR - 0.0055, -0.64, 1.10), 0.07, -1)
    back('defender badge', (-0.80, -0.60), (0.80, 0.83), chrome, 0.005)
    box('back crossmember', (REAR - 0.03, REAR + 0.1), (-0.82, 0.82), (0.49, 0.62), black, 0.008)
    box('tow bar', (REAR - 0.10, REAR + 0.05), (-0.06, 0.06), (0.36, 0.52), steel, 0.006)
    rod('tow ball', (REAR - 0.07, 0, 0.52), (REAR - 0.07, 0, 0.57), 0.025, chrome)

    # ---- Inside: seats, a wheel to steer with on the right, the boxes over the back wheels.
    box('floor mat', (REAR + 0.05, 0.74), (-CABIN + 0.04, CABIN - 0.04), (0.60, 0.645), lining)
    box('dashboard', (0.46, 0.76), (-CABIN + 0.04, CABIN - 0.04), (0.98, 1.235), lining, 0.02)
    for s in (-1, 1):
        box(f'front seat {s}', (-0.08, 0.40), (s * 0.14, s * 0.62), (0.80, 1.00), seat, 0.03)
        hexa(f'front seat back {s}', [(-0.12, min(s * 0.14, s * 0.62), 0.98), (0.0, min(s * 0.14, s * 0.62), 0.98), (0.0, max(s * 0.14, s * 0.62), 0.98), (-0.12, max(s * 0.14, s * 0.62), 0.98)],
             [(-0.22, min(s * 0.14, s * 0.62), 1.55), (-0.11, min(s * 0.14, s * 0.62), 1.55), (-0.11, max(s * 0.14, s * 0.62), 1.55), (-0.22, max(s * 0.14, s * 0.62), 1.55)], seat, 0.03)
        box(f'front headrest {s}', (-0.25, -0.13), (min(s * 0.26, s * 0.50), max(s * 0.26, s * 0.50)), (1.58, 1.76), cover, 0.03)
        for x0 in (-AXLE,):  # the wheel boxes, or one would look from the back seat straight at the tyre
            box(f'wheel box top {s}', (x0 - 0.56, x0 + 0.56), (min(s * 0.54, s * 0.76), max(s * 0.54, s * 0.76)), (0.955, 0.99), lining)
            for x in (x0 - 0.56, x0 + 0.54):
                box(f'wheel box end {x} {s}', (x, x + 0.02), (min(s * 0.54, s * 0.76), max(s * 0.54, s * 0.76)), (0.60, 0.99), lining)
    box('back seat', (-0.98, -0.52), (-0.66, 0.66), (0.80, 0.98), seat, 0.03)
    box('back seat back', (-1.10, -0.98), (-0.66, 0.66), (0.96, 1.50), seat, 0.03)
    for y in (-0.42, 0.0, 0.42):
        box(f'back headrest {y}', (-1.12, -1.02), (y - 0.11, y + 0.11), (1.53, 1.70), seat, 0.03)
    hub = Vector((0.47, -0.38, 1.24))
    lean = Vector((0.9, 0, -0.44)).normalized()  # the column runs up and back to the driver
    rim_ = [hub - lean * 0.14 + Matrix.Rotation(2 * math.pi * i / 16, 3, lean) @ Vector((0, 0.19, 0)) for i in range(17)]
    tube('steering wheel', rim_, 0.014, lining)
    rod('steering column', hub, hub - lean * 0.14, 0.02, lining, n=8)
    for i in (0, 5, 11):
        rod(f'steering spoke {i}', hub - lean * 0.14, rim_[i], 0.01, lining, n=6)

    # ---- Wheels: an all-terrain tyre with blocks on its shoulders, a white steel rim with a ring of holes.
    def wheel(name, centre, axis):
        """axis points out of the car, from the back of the wheel to its face."""
        c, a = Vector(centre), Vector(axis).normalized()
        turn = a.rotation_difference(Vector((0, 0, 1))).inverted()
        side = lambda ang, r: c + turn @ Vector((math.cos(ang) * r, math.sin(ang) * r, 0))
        tyre = rod(name + ' tyre', c - a * TYRE_W / 2, c + a * TYRE_W / 2, TYRE_R - 0.012, rubber, n=48, bevel=0.035)
        cut(tyre, rod(name + ' bore', c - a * TYRE_W, c + a * TYRE_W, 0.222, rubber, n=48))  # a tyre is a ring: the rim shows in it
        for i in range(30):  # the tread
            ang = 2 * math.pi * i / 30
            for k, off in enumerate((-0.085, 0.0, 0.085)):
                p = side(ang + (0.1 if k == 1 else 0), TYRE_R - 0.012)
                rod(f'{name} block {i} {k}', p + a * (off - 0.032), p + a * (off + 0.032), 0.022, rubber, n=6)
        face = c + a * (TYRE_W / 2 - 0.035)
        rod(name + ' rim', c - a * (TYRE_W / 2 - 0.02), face, 0.225, white, n=40, bevel=0.01)
        rod(name + ' dish', face, face + a * 0.012, 0.17, white, r2=0.09, n=40)
        rod(name + ' hub', face, face + a * 0.045, 0.062, white, r2=0.05, n=20)
        for i in range(12):  # the holes that cool the brakes
            p = side(2 * math.pi * i / 12, 0.195) + a * (TYRE_W / 2 - 0.036)
            rod(f'{name} hole {i}', p, p + a * 0.004, 0.017, ink, n=10)
        for i in range(5):
            p = side(2 * math.pi * i / 5, 0.085) + a * (TYRE_W / 2 - 0.03)
            rod(f'{name} nut {i}', p, p + a * 0.02, 0.011, chrome, n=6)

    for s in (-1, 1):
        for x0 in (-AXLE, AXLE):
            wheel(f'wheel {x0} {s}', (x0, s * TRACK, TYRE_R), (0, s, 0))
    wheel('spare wheel', (REAR - 0.03 - TYRE_W / 2, -0.07, 1.02), (-1, 0, 0))
    rod('spare wheel bore', (REAR - TYRE_W - 0.04, -0.07, 1.02), (REAR - TYRE_W - 0.046, -0.07, 1.02), 0.05, ink)  # no hub in it, only the hole for one

    # ---- The cage: black tubes outside the body, up the screen pillars, along the roof, down the back.
    T, top, out = 0.024, ROOF + 0.045, CABIN + 0.035
    for s in (-1, 1):
        tube(f'cage side {s}', [(BULKHEAD + 0.07, s * (BODY - 0.03), 1.14), (BULKHEAD + 0.035, s * out, WAIST + 0.06), (SCREEN(GUTTER) + 0.03, s * out, GUTTER + 0.03),
                                (SCREEN(GUTTER) - 0.1, s * out, top), (REAR + 0.02, s * out, top), (REAR - 0.045, s * out, GUTTER), (REAR - 0.045, s * out, 0.98)], T, black)
        tube(f'cage middle {s}', [(-0.15, s * out, top), (-0.15, s * (CABIN + 0.03), WAIST + 0.08), (-0.15, s * (BODY + 0.028), WAIST - 0.02), (-0.15, s * (BODY + 0.028), WAIST - 0.14)], T, black)
        rod(f'cage brace {s}', (SCREEN(GUTTER) - 0.1, 0, top), (-0.15, s * out, top), T * 0.85, black, n=12)
        box(f'cage foot {s}', (BULKHEAD + 0.02, BULKHEAD + 0.12), (s * (BODY - 0.08), s * (BODY + 0.0)), (1.132, 1.142), black)
    for x in (SCREEN(GUTTER) - 0.1, -0.15, -0.9, -1.6, REAR + 0.02):
        rod(f'cage bar {x}', (x, -out, top), (x, out, top), T, black, n=14)

    # ---- The snorkel: up the right-hand pillar, with its mushroom of a head above the roof.
    y = -(BODY + 0.045)
    box('snorkel foot', (0.98, 1.30), (y - 0.035, -BODY + 0.005), (0.93, 1.10), black, 0.02)
    tube('snorkel', [(1.10, y, 1.04), (BULKHEAD + 0.10, y + 0.015, 1.22), (BULKHEAD + 0.02, -(CABIN + 0.085), 1.36), (SCREEN(GUTTER) + 0.03, -(CABIN + 0.085), GUTTER + 0.06),
                     (SCREEN(GUTTER) + 0.03, -(CABIN + 0.085), ROOF + 0.10)], 0.042, black)
    rod('snorkel head', (SCREEN(GUTTER) - 0.03, -(CABIN + 0.085), ROOF + 0.13), (SCREEN(GUTTER) + 0.13, -(CABIN + 0.085), ROOF + 0.19), 0.085, black, r2=0.07, n=24, bevel=0.01)

    # ---- On the roof: the awning rolled up along the left, and the bag when it is packed.
    rod('awning', (-1.75, out + 0.08, top + 0.01), (0.35, out + 0.08, top + 0.01), 0.062, canvas, n=20, bevel=0.01)
    for x in (-1.5, -0.7, 0.1):
        box(f'awning strap {x}', (x, x + 0.04), (out - 0.02, out + 0.15), (top - 0.03, top + 0.075), black)
    if bag:
        box('roof bag', (-2.2, -0.75), (-0.6, 0.6), (top + 0.02, top + 0.34), paint('bag', (22, 22, 24), 0.7), 0.09)
    for ob in made:
        ob.parent = root
    return root, made


def stage(sun=250.0):
    """The light of a deep place (deep/scene.py), so the car belongs there: the same sky, the same sun, the same
    film. The sun stands at `sun` degrees clockwise from north, forty degrees up; on the map that is 250."""
    scene = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    world = bpy.data.worlds.new('sky')
    world.use_nodes = True
    nt = world.node_tree
    sky = nt.nodes.new('ShaderNodeTexSky')
    sky.sky_type = 'MULTIPLE_SCATTERING'
    az, el = math.radians(sun), math.radians(40)
    sky.sun_elevation, sky.sun_rotation = el, az
    try:
        sky.sun_disc = False
    except Exception:  # noqa: BLE001
        pass
    nt.links.new(sky.outputs[0], nt.nodes['Background'].inputs[0])
    nt.nodes['Background'].inputs[1].default_value = 0.3
    scene.world = world
    lamp = bpy.data.lights.new('sun', 'SUN')
    lamp.energy, lamp.angle, lamp.color = 4.4, math.radians(1.6), (1.0, 0.95, 0.86)
    so = bpy.data.objects.new('sun', lamp)
    scene.collection.objects.link(so)
    so.rotation_euler = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el))).to_track_quat('Z', 'Y').to_euler()
    scene.render.engine = 'CYCLES'
    cy = scene.cycles
    cy.samples, cy.use_adaptive_sampling, cy.adaptive_threshold = int(arg('samples', '96')), True, 0.02
    cy.use_denoising, cy.denoiser = True, 'OPENIMAGEDENOISE'
    cy.max_bounces, cy.diffuse_bounces, cy.glossy_bounces, cy.transmission_bounces = 8, 3, 4, 6  # glass wants more than a wall does
    cy.device = 'CPU'
    if arg('device', 'cpu') == 'gpu':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'METAL' if sys.platform == 'darwin' else 'OPTIX'
        prefs.refresh_devices()
        for d in prefs.devices:
            d.use = True
        cy.device = 'GPU'
    scene.view_settings.view_transform = 'AgX'
    try:
        scene.view_settings.look = 'AgX - Medium High Contrast'
    except Exception:  # noqa: BLE001
        pass
    scene.view_settings.exposure = 0.3
    return scene


def ground(colour=(118, 112, 104)):
    me = bpy.data.meshes.new('ground')
    me.from_pydata([(-60, -60, 0), (60, -60, 0), (60, 60, 0), (-60, 60, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new('ground', me)
    ob.data.materials.append(paint('ground', colour, 0.95))
    bpy.context.scene.collection.objects.link(ob)
    return ob


def camera(at, to, lens=50):
    cam = bpy.data.cameras.new('camera')
    ob = bpy.data.objects.new('camera', cam)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = at
    ob.rotation_euler = (Vector(to) - Vector(at)).to_track_quat('-Z', 'Y').to_euler()
    cam.lens, cam.clip_end = lens, 500
    bpy.context.scene.camera = ob
    return ob


def map_camera(look, metres, pixels):
    """The map's own camera: thirty degrees down, no perspective, looking the way of one of the map's views. The
    spot the car stands on comes out in the middle of the picture."""
    scene = bpy.context.scene
    cam = bpy.data.cameras.new('map camera')
    ob = bpy.data.objects.new('map camera', cam)
    scene.collection.objects.link(ob)
    cam.type, cam.ortho_scale, cam.clip_end = 'ORTHO', metres, 500
    ob.rotation_euler = (math.radians(60), 0, math.radians(-look))
    ob.location = -(ob.rotation_euler.to_matrix() @ Vector((0, 0, -1))) * 60
    scene.camera = ob
    scene.render.resolution_x = scene.render.resolution_y = pixels
    scene.render.film_transparent = True


def heading(root, degrees):
    """Point the car: degrees clockwise from north, as a compass has it. North is +y here and east +x."""
    root.rotation_euler = (0, 0, math.radians(90 - degrees))


def main():
    from PIL import Image, ImageFilter
    out = arg('out', ROOT + '/out/models/defender')
    os.makedirs(out, exist_ok=True)
    only, place = arg('only', ''), arg('place', '')
    scene = stage(sun=250.0 if place or only == 'map' else 140.0)
    root, car = build(bag=flag('bag'), plate=arg('plate', ''))
    floor = ground()
    render = lambda path: (setattr(scene.render, 'filepath', path), bpy.ops.render.render(write_still=True))
    if place:
        # Stood in a deep place: rendered as the map sees it, at the sharpness of the deep tiles, with its shadow on
        # a floor that shows nothing but shadow, and laid over the picture of the place.
        floor.is_shadow_catcher = True
        onto = Image.open(arg('onto', ROOT + '/out/deep/churchtown-45/picture.jpg')).convert('RGB')
        per_metre = float(arg('scale', '32'))  # the picture of a deep place is kept at half the sharpness of its tiles
        map_camera(45, 10.0, 640)
        spots = [[float(v) for v in q.split(',')] for q in place.split('/')]
        for i, (px, py, way) in enumerate(spots):
            heading(root, way)
            render(f'{out}/sprite-{i}.png')
            sprite = Image.open(f'{out}/sprite-{i}.png')
            size = round(10.0 * per_metre)
            sprite = sprite.resize((size, size), Image.LANCZOS)
            onto.paste(sprite, (round(px - size / 2), round(py - size / 2)), sprite)
        onto.save(f'{out}/placed.png')
        px, py = spots[0][:2]
        onto.crop((int(px - 600), int(py - 400), int(px + 600), int(py + 400))).save(f'{out}/placed-close.png')
        return
    # From where the photographs were taken: on the hill road in front, on the cliff at its right side, behind it in
    # the gorge, and the front quarter by the tent.
    views = {'front': ((6.4, 3.6, 1.75), (0.2, 0.1, 0.95), 50), 'side': ((0.9, -8.2, 3.3), (0.0, 0.0, 0.95), 50),
             'rear': ((-7.6, 0.7, 1.5), (0.0, 0.0, 1.05), 55), 'quarter': ((6.2, -5.2, 1.7), (0.0, 0.0, 0.95), 50)}
    for name, (at, to, lens) in views.items():
        if only and only != name:
            continue
        scene.render.resolution_x, scene.render.resolution_y = 1500, 1000
        camera(at, to, lens)
        render(f'{out}/{name}.png')
    if only and only != 'map':
        return
    # As the map sees it, the car pointed to eight headings, with its shadow.
    floor.is_shadow_catcher = True
    map_camera(45, 8.0, 512)
    sheet = Image.new('RGB', (512 * 4, 512 * 2), (96, 98, 100))
    for i in range(8):
        heading(root, 45 * i)
        render(f'{out}/map-{i}.png')
        tile = Image.open(f'{out}/map-{i}.png')
        sheet.paste(tile, (512 * (i % 4), 512 * (i // 4)), tile)
    sheet.save(f'{out}/map.png')


if __name__ == '__main__':
    main()
