# Churchtown, by hand: what stands on the pavement by the parish church. The tiles hold only what stays put. With
# --movers, for a picture, people are about, the giant comes down the road and the traffic has stopped for him.
# All of it is made up. Spots are given in the map's local
# metres (x east, z south) and along the road in metres from the junction with Trevaunance Road: less than nothing is
# down Churchtown, more is on along Town Hill. Run from scene.py after details.py, in its namespace.

junction, down_the_hill = to_block(521, -4), to_block(515, 84)
road = min(main_roads, key=lambda q: q['line'].distance(Point(junction))) if main_roads else None
if road is not None and church is not None:
    street = Street(road, junction, away_from=down_the_hill)

    # A red phone box, a pillar box, a bench, a bin and a bus stop on the church's side of the road.
    x, y, yaw, side = street.kerb(-31, church)
    phone_box(x, y, yaw)
    x, y, yaw, side = street.kerb(-28.6, church)
    pillar_box(x, y)
    x, y, yaw, side = street.kerb(-24, church, 0.95)
    bench(x, y, yaw + (0 if side > 0 else math.pi))
    x, y, yaw, side = street.kerb(-21.6, church)
    cyl(mt, (x, y, G(x, y)), 0.24, 0.85, (0.07, 0.16, 0.1), n=12)
    cyl(mt, (x, y, G(x, y) + 0.85), 0.27, 0.07, (0.05, 0.1, 0.07), n=12)
    x, y, yaw, side = street.kerb(-37, church)
    cyl(mt, (x, y, G(x, y)), 0.04, 2.7, (0.5, 0.5, 0.52), n=6)
    cbox(mt, (x + math.cos(yaw) * 0.25, y + math.sin(yaw) * 0.25, G(x, y) + 2.45), (0.46, 0.03, 0.4), yaw, (0.9, 0.75, 0.1))

    # A zebra crossing by the church gate, with its two beacons.
    for k in range(int((2 * street.half - 0.6) / 1.2) + 1):
        across = -street.half + 0.6 + k * 1.2
        x0, y0, _ = street.at(-15.3, across)
        x1, y1, _ = street.at(-12.7, across)
        strip(x0, y0, x1, y1, 0.3, (0.93, 0.93, 0.9), 0.04)
    for across in (-street.half - 0.45, street.half + 0.45):
        x, y, _ = street.at(-16.2 if across < 0 else -11.8, across)
        for k in range(6):
            cyl(mt, (x, y, G(x, y) + k * 0.36), 0.045, 0.36, (0.06, 0.06, 0.06) if k % 2 else (0.94, 0.94, 0.92), n=8)
        blob(batch('lamp'), (x, y, G(x, y) + 2.3), (0.16, 0.16, 0.16), (1.0, 0.55, 0.05), 0, 3)

    # People on the pavement, in a picture with --movers only: the map has walkers of its own. Those near the giant
    # have stopped to look up. Without --movers the dice are still rolled for the six who used to stand here, so
    # that whatever is made after them comes out as it did.
    gx0, gy0, _ = street.at(-6.5)
    for i, off in enumerate((-44, -40.5, -39.8, -33, -26.5, -19, -18.2, -9, -6.5, 6, 9.5, 17, 24) if MOVERS else (-40.6, -39.8, -27.3, -26.5, 9.6, 10.4)):
        x, y, yaw, side = street.kerb(off, church, 0.45 + 0.5 * rnd.random())
        if not inside(x, y) or taken.buffer(0.2).contains(Point(x, y)):
            continue
        looking = MOVERS and math.dist((x, y), (gx0, gy0)) < 16
        face = math.atan2(gy0 - y, gx0 - x) if looking else yaw + (math.pi if i % 3 == 0 else 0) if MOVERS else yaw + (0 if i % 2 == 0 else math.pi)
        child = i == (2 if MOVERS else 1)
        coat, legs, hair = rnd.choice(COATS), rnd.choice(LEGS), rnd.choice(HAIR)
        if not MOVERS:
            continue
        person(x, y, face, coat, legs, hair, size=0.72 if child else 1.0, stride=0.25 if MOVERS and not looking else 0.04)
        if child:  # with a red balloon
            cyl(mt, (x + 0.2, y, G(x, y) + 0.9), 0.004, 1.2, (0.9, 0.9, 0.9), n=4, axis=(0.1, 0.05, 1))
            blob(batch('gloss'), (x + 0.32, y + 0.06, G(x, y) + 2.25), (0.17, 0.17, 0.21), (0.85, 0.06, 0.08), 0, 9)
        if i in ((4, 9) if MOVERS else (3,)):  # and a dog on a lead
            px, py = x - math.sin(face) * 0.6, y + math.cos(face) * 0.6
            cbox(mt, (px, py, G(px, py) + 0.3), (0.55, 0.2, 0.22), face, (0.55, 0.38, 0.2))
            blob(mt, (px + math.cos(face) * 0.32, py + math.sin(face) * 0.32, G(px, py) + 0.42), (0.11, 0.1, 0.1), (0.55, 0.38, 0.2), 0, 6)
            for f in (-0.2, 0.2):
                for q in (-0.07, 0.07):
                    cyl(mt, (px + math.cos(face) * f - math.sin(face) * q, py + math.sin(face) * f + math.cos(face) * q, G(px, py)), 0.03, 0.22, (0.5, 0.34, 0.18), n=5)

    if MOVERS:
        # Traffic keeps left: a car has pulled up short of the giant, a red van waits behind it, one comes the other way.
        for off, way, colour, van in ((-23, 1, (0.1, 0.18, 0.4), False), (-30.5, 1, (0.7, 0.05, 0.04), True), (14, -1, (0.75, 0.76, 0.78), False),
                                      (33, 1, (0.15, 0.32, 0.22), False), (-62, -1, (0.85, 0.6, 0.1), False)):
            x, y, yaw = street.at(off, street.half * 0.5, way)
            if inside(x, y):
                car(x, y, yaw, colour, van=van)
        x, y, yaw = street.at(-6.5, 0.0, -1)
        giant(x, y, yaw)
