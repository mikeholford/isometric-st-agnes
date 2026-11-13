# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "shapely"]
# ///
"""Named places of St Agnes: style overrides and extra geometry for buildings, plus the viewer's place list.

Positions are from OpenStreetMap. The short texts are written for this map; dates and facts were checked against
the Wikipedia articles on St Agnes, Wheal Coates, Wheal Kitty, Trevaunance Cove and the Truro and Newquay Railway.
The stories only people who live here know are still to be added: every entry takes a "text".

Output: data/build/landmarks.json
"""

import json

import numpy as np
from shapely.geometry import Point

from config import BUILD
from geo import wgs_to_grid
from outlines import load_outlines

STONE = (150, 138, 122)  # killas rubble with granite dressings: the mine buildings
SLATE = (66, 68, 74)

# Buildings found by a point; the outline under (or nearest to) that point gets the name and the style.
BUILDINGS = [
    {
        "name": "St Agnes Parish Church",
        "note": "A chapel of ease of about 1482, restored in 1848; the spire was rebuilt in 1905",
        "kind": "Parish church · about 1482",
        "latlon": (50.31237, -5.20337),
        "style": "church",
        "wall": (158, 148, 134),
        "roof": SLATE,
        "text": "The church of St Agnes stands in Churchtown, the oldest part of the village. It was built about 1482 as a chapel of ease, and St Agnes became a parish of its own only in 1846. Piers St Aubyn restored the building in 1848, all but the tower and spire; the spire was rebuilt in 1905. A spire is a rare thing on a Cornish church, and this one shows from the Beacon and from the sea.",
        # Tower at the west end; the size is an estimate until someone measures it.
        "tower_at": "west",
        "tower": {"w": 4.6, "body": 14.0, "top": 26.0, "cross": False},
    },
    {
        "name": "St Agnes Methodist Church",
        "kind": "Methodist church",
        "latlon": (50.30989, -5.20176),
        "style": "church",
        "wall": (170, 160, 146),
        "roof": SLATE,
        "text": "The Methodist church of the village, on British Road. Methodism ran deep in the mining districts of Cornwall, and the parish once had a chapel in every hamlet.",
    },
    {
        "name": "Our Lady, Star of the Sea",
        "kind": "Catholic church",
        "latlon": (50.3146, -5.205),
        "text": "The Catholic church of St Agnes, on Trevaunance Road, on the way down to the cove.",
    },
    {
        "name": "Miners and Mechanics Institute",
        "note": "A gift of John Passmore Edwards, 1893",
        "kind": "Institute · 1893",
        "latlon": (50.31012, -5.20303),
        "style": "school",
        "wall": (164, 150, 132),
        "roof": SLATE,
        "frame": (236, 232, 222),
        "text": "Built in 1893 for the miners and tradesmen of St Agnes, paid for by the Cornish newspaper owner and philanthropist John Passmore Edwards, who gave Cornwall many of its institutes and libraries. It is still the village's meeting place.",
    },
    {
        "name": "St Agnes Museum",
        "kind": "Museum",
        "latlon": (50.30765, -5.20378),
        "web": "https://www.stagnesmuseum.org.uk",
        "text": "The parish museum, run by volunteers, on Penwinnick Road. It tells of mining, the harbour, the sea and the people of the parish; its best-known exhibit is a leatherback turtle of 320 kg that washed ashore.",
    },
    {
        "name": "The Driftwood Spars",
        "note": "Inn and brewery at Trevaunance Cove",
        "kind": "Inn and brewery",
        "latlon": (50.31824, -5.20269),
        "web": "https://driftwoodspars.co.uk",
        "wall": (236, 232, 220),
        "roof": SLATE,
        "style": "house",
        "text": "The inn just above Trevaunance Cove, in an old building of the cove's working days, when ore, coal and fish came and went here. It is said to take its name from the ships' spars built into it. It brews its own beer.",
    },
    {
        "name": "The St Agnes Hotel",
        "kind": "Pub and hotel",
        "latlon": (50.31244, -5.20383),
        "text": "The inn in Churchtown, opposite the church.",
    },
    {
        "name": "The Railway Inn",
        "kind": "Pub",
        "latlon": (50.30935, -5.20332),
        "text": "A pub on Vicarage Road, in the middle of the village.",
    },
    {
        "name": "Peterville Inn",
        "kind": "Pub",
        "latlon": (50.31224, -5.19959),
        "text": "The pub at Peterville, at the bottom of Town Hill, where the road turns down the valley to the cove.",
    },
    {
        "name": "The Taphouse",
        "kind": "Pub",
        "latlon": (50.31227, -5.19888),
    },
    {
        "name": "St Agnes Lifeboat Station",
        "note": "RNLI inshore lifeboat at Trevaunance Cove",
        "kind": "RNLI lifeboat station",
        "latlon": (50.31923, -5.20183),
        "web": "https://rnli.org/find-my-nearest/lifeboat-stations/st-agnes-lifeboat-station",
        "wall": (226, 222, 210),
        "roof": (88, 90, 96),
        "style": "house",
        "text": "The inshore lifeboat of St Agnes launches from here across the beach of Trevaunance Cove. The crew are volunteers from the village.",
    },
    {
        "name": "Towanroath Engine House, Wheal Coates",
        "note": "The engine house on the cliff, 1872",
        "kind": "Mine engine house · 1872",
        "latlon": (50.30503, -5.23309),
        "style": "engine",
        "wall": STONE,
        "roofless": True,
        "height": 11.0,
        "stacks": [{"dx": 5.5, "dy": 0.0, "r": 1.5, "height": 15.0}],
        "text": "The picture of Cornish mining: the pumping engine house of Towanroath shaft, built in 1872 on the cliff slope above the sea. Its steam engine pumped the water out of the workings of Wheal Coates. The mine closed in 1889, was worked again from 1911 to 1913 and shut for good in 1914. The ruins were made safe in 1986. The National Trust looks after them; they are part of the Cornish Mining World Heritage Site.",
        "more": "https://www.nationaltrust.org.uk/visit/cornwall/wheal-coates",
    },
    {
        "name": "Whim Engine House, Wheal Coates",
        "kind": "Mine engine house",
        "latlon": (50.3053, -5.23187),
        "style": "engine",
        "wall": STONE,
        "roofless": True,
        "height": 10.0,
        "stacks": [{"dx": -5.0, "dy": 0.0, "r": 1.4, "height": 13.0}],
        "text": "Up the slope from Towanroath stand the other buildings of Wheal Coates: the whim engine house, whose engine wound the ore up the shaft, the stamps engine house, which crushed it, and the calciner, where the tin ore was roasted to drive off arsenic.",
        "more": "https://www.nationaltrust.org.uk/visit/cornwall/wheal-coates",
    },
    {
        "name": "Blue Hills Engine House",
        "kind": "Mine engine house",
        "latlon": (50.32109, -5.19248),
        "style": "engine",
        "wall": STONE,
        "roofless": True,
        "height": 10.0,
        "stacks": [{"dx": 5.0, "dy": 0.0, "r": 1.4, "height": 13.0}],
        "text": "The pumping engine house of Blue Hills Mine in Trevellas Coombe. The mine worked from about 1810 until 1897.",
    },
    {
        "name": "NCI St Agnes Head",
        "note": "Coastwatch lookout",
        "kind": "Coastwatch lookout",
        "latlon": (50.31754, -5.23238),
        "web": "https://www.nci.org.uk/stations/st-agnes-head",
        "text": "Volunteers of the National Coastwatch Institution keep watch from this lookout over the sea off St Agnes Head: walkers on the cliff path, surfers, fishing boats, and the weather.",
    },
    {
        "name": "Chapel Porth Cafe",
        "note": "Home of the hedgehog ice cream",
        "kind": "Beach cafe",
        "latlon": (50.29996, -5.23382),
        "text": "The little cafe in the National Trust car park at Chapel Porth. Its hedgehog is a cone of Cornish ice cream, covered in clotted cream and rolled in roasted hazelnuts.",
    },
]

# Places that are not a building: a disc on the ground to hover and click.
POINTS = [
    {
        "name": "St Agnes Beacon",
        "note": "192 m: the top of the map",
        "kind": "Hill · 192 m",
        "latlon": (50.30731, -5.21735),
        "text": "The Beacon rises 192 metres above the sea and can be seen from most of west Cornwall. Fires were lit here to pass on warnings and, later, to mark celebrations. A Bronze Age burial mound stands on the top, the last of a row of three. Old stories say the giant Bolster could stand with one foot here and the other on Carn Brea, six miles off, and that the heaps of stones on the hill were carried up by his wife in her apron when he was angry with her. The hill is heathland of heather and gorse, in the care of the National Trust.",
        "more": "https://www.nationaltrust.org.uk/visit/cornwall/st-agnes-and-chapel-porth",
    },
    {
        "name": "Bolster Bank",
        "note": "The earth bank that gave the giant his name",
        "kind": "Earthwork",
        "latlon": (50.30295, -5.21054),
        "text": "A bank of earth with a ditch that once ran about two miles, from Chapel Coombe to Trevaunance Coombe, and cut the whole headland off from the land behind it. About a third is left. Nobody knows who built it or when; the name is on record in 1398, as Bothlester, so the bank is older than that. The name is Cornish for a hump like an upturned boat. When Cornish was no longer spoken here, people took Bolster for the name of a giant and said the bank was his work. That was written down before 1742, and it is the oldest record of the giant.",
        "more": "https://historicengland.org.uk/listing/the-list/list-entry/1016444",
    },
    {
        "name": "Trevaunance Cove",
        "note": "The beach of St Agnes, and what is left of its harbour",
        "kind": "Cove and lost harbour",
        "latlon": (50.3203, -5.2020),
        "text": "The village beach. The Tonkin family of Trevaunance tried to build a harbour here in 1632, in 1684 and in 1699; the sea took every one. A harbour of the 1790s did last: for more than a century it shipped out tin and copper ore and brought in coal, until storms in 1915 and 1916 broke it. Its granite blocks still lie on the west side of the cove.",
    },
    {
        "name": "Chapel Porth",
        "note": "National Trust beach under the cliffs of Wheal Coates",
        "kind": "Cove",
        "latlon": (50.30025, -5.23476),
        "text": "At high water there is hardly a beach here; at low water the sand runs a long way north and south under the cliffs. The cove takes its name from a medieval chapel that stood above it until about 1780; its holy well lasted until 1820. The legend of the giant Bolster ends here. He would not leave St Agnes alone, so she asked for one proof of his love: to fill a hole in the cliff with his blood. The hole ran out to the sea and never filled, and the giant bled to death. People point to the red rock as his blood; iron in the rock gives the colour. Robert Hunt wrote the story down in 1865. On the early May bank holiday weekend the village plays it out on the cliffs here, at the Bolster Festival.",
        "more": "https://www.nationaltrust.org.uk/visit/cornwall/st-agnes-and-chapel-porth",
    },
    {
        "name": "St Agnes Head",
        "kind": "Headland",
        "latlon": (50.31825, -5.2374),
        "text": "The headland north of the Beacon, heath to the cliff edge. Kittiwakes, fulmars and guillemots nest on the cliffs below, and seals fish off the rocks.",
    },
    {
        "name": "Trevellas Porth",
        "kind": "Cove",
        "latlon": (50.32357, -5.19632),
        "text": "The rocky cove at the foot of Trevellas Coombe, next along the coast from Trevaunance. The stream that reaches the sea here once drove the stamps and water wheels of the tin works up the valley.",
    },
    {
        "name": "Blue Hills Tin Streams",
        "note": "Tin is still made here",
        "kind": "Tin works",
        "latlon": (50.32007, -5.19231),
        "web": "https://www.cornishtin.com",
        "text": "A family tin works in Trevellas Coombe, where tin is still produced and visitors can see how it is done.",
    },
    {
        "name": "Wheal Kitty",
        "note": "Mine above the cove, worked until 1930",
        "kind": "Mine · closed 1930",
        "latlon": (50.3155, -5.19704),
        "text": "Wheal Kitty stands on the hill between the village and Trevellas Coombe. It raised tin until 1930, one of the last mines of St Agnes to close. Two engine houses and four stacks still stand; a beam engine of 1852 pumped Sara's shaft. The mine buildings are in use again, among others as the headquarters of Surfers Against Sewage.",
    },
    {
        "name": "Wheal Friendly",
        "kind": "Mine",
        "latlon": (50.31681, -5.20402),
        "text": "A small mine in the valley above Trevaunance Cove, worked together with Wheal Kitty in its last years.",
    },
    {
        "name": "Stippy Stappy",
        "note": "The stepped terrace down Town Hill",
        "kind": "Terrace of cottages",
        "latlon": (50.31262, -5.20195),
        "text": "A row of 18th-century cottages that steps down the steep hill from Churchtown to Peterville, each a little lower than the last.",
    },
    {
        "name": "St Agnes station",
        "note": "On the Truro and Newquay line, 1903 to 1963",
        "kind": "Former railway station",
        "latlon": (50.29852, -5.20044),
        "text": "St Agnes had a railway for sixty years. The line from Chacewater opened as far as Perranporth on 6 July 1903, went on to Newquay two years later, and closed on 4 February 1963. The station stood here, most of a mile south of the village.",
    },
    {
        "name": "Goonbell Halt",
        "kind": "Former railway halt",
        "latlon": (50.30296, -5.19186),
        "text": "A halt on the Truro and Newquay line, opened on 14 August 1905 for the hamlet of Goonbell. The line closed in 1963.",
    },
]

# Series in the viewer's panel: a walk past these places, starting with the one nearest the village.
CATEGORIES = [
    ("mining", "Tin and copper", [
        "Towanroath Engine House, Wheal Coates", "Whim Engine House, Wheal Coates", "Wheal Kitty", "Wheal Friendly",
        "Blue Hills Engine House", "Blue Hills Tin Streams", "Trevaunance Cove",
    ]),
    ("bolster", "The giant Bolster", ["Bolster Bank", "St Agnes Beacon", "Chapel Porth"]),
    ("village", "The village", [
        "St Agnes Parish Church", "Stippy Stappy", "Miners and Mechanics Institute", "St Agnes Methodist Church",
        "Our Lady, Star of the Sea", "St Agnes Museum",
    ]),
    ("coast", "Coast and Beacon", [
        "Trevaunance Cove", "St Agnes Lifeboat Station", "Trevellas Porth", "St Agnes Head", "NCI St Agnes Head",
        "St Agnes Beacon", "Chapel Porth",
    ]),
    ("pubs", "Pubs and cafes", [
        "The St Agnes Hotel", "The Railway Inn", "Peterville Inn", "The Taphouse", "The Driftwood Spars", "Chapel Porth Cafe",
    ]),
    ("gone", "Gone", ["St Agnes station", "Goonbell Halt", "Trevaunance Cove"]),
]

# What the viewer shows when a place is clicked; the rest of an entry is for the render.
INFO = ("note", "kind", "text", "address", "web", "more", "photo")
RENDER = ("style", "wall", "roof", "frame", "tower", "turret", "bell", "stacks", "roofless", "height", "name")

MASTS = []


def main():
    outlines = load_outlines()
    out = {"buildings": {}, "places": [], "masts": [], "hotspots": [], "categories": [], "structures": []}
    for b in BUILDINGS:
        x, y = b["at"] if "at" in b else wgs_to_grid(*b["latlon"])
        pt = Point(x, y)
        dist, pid, poly = min(((p.distance(pt), i, p) for i, p, _ in outlines), key=lambda t: t[0])
        if dist > 15:
            pid = None
        info = {k: b[k] for k in INFO if k in b}
        out["places"].append({"name": b["name"], "note": b.get("note"), "x": x, "y": y, "h": 6.0})
        if pid is None:
            # No outline on any map: still a place to click, as a point.
            out["hotspots"].append({"name": b["name"], "x": x, "y": y, **info})
            print(f"{b['name']}: no building")
            continue
        entry = {k: b[k] for k in RENDER if k in b}
        rect = np.array(poly.minimum_rotated_rectangle.exterior.coords)[:4]
        c = rect.mean(0)
        if "tower" in b:
            # The tower stands at one end of the nave: the end of the long axis that lies furthest toward that side.
            ends = [(rect[i] + rect[(i + 1) % 4]) / 2 for i in range(4)]
            ends.sort(key=lambda e: -np.hypot(*(e - c)))
            west = min(ends[:2], key=lambda e: e[0]) if b.get("tower_at", "west") == "west" else max(ends[:2], key=lambda e: e[0])
            toward = (west - c) / np.hypot(*(west - c))
            at = west - toward * b["tower"]["w"] * 0.4
            entry["tower"] = {**b["tower"], "x": float(at[0]), "y": float(at[1])}
        if "stacks" in b:
            entry["stacks"] = [{**s, "x": float(c[0] + s["dx"]), "y": float(c[1] + s["dy"])} for s in b["stacks"]]
        if entry:
            entry.setdefault("style", "house")
            out["buildings"][pid] = entry
        out["hotspots"].append({"name": b["name"], "pid": pid, "x": x, "y": y, **info})
        print(f"{b['name']}: {pid}")
    for p in POINTS:
        x, y = p["at"] if "at" in p else wgs_to_grid(*p["latlon"])
        out["places"].append({"name": p["name"], "note": p.get("note"), "x": x, "y": y, "h": 2.0})
        out["hotspots"].append({"name": p["name"], "x": x, "y": y, **{k: p[k] for k in INFO if k in p}})
    for m in MASTS:
        x, y = wgs_to_grid(*m["latlon"])
        out["masts"].append({**{k: v for k, v in m.items() if k != "latlon"}, "x": x, "y": y})
    names = {h["name"] for h in out["hotspots"]}
    for key, label, members in CATEGORIES:
        missing = [n for n in members if n not in names]
        assert not missing, f"{label}: no hotspot for {missing}"
        out["categories"].append({"key": key, "label": label, "names": members})
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "landmarks.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
