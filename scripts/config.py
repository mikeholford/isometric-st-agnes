"""Shared settings: the area we render, in British National Grid (EPSG:27700) metres."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BUILD = ROOT / "data" / "build"

# St Agnes, Cornwall: from Chapel Porth and Wheal Coates in the south-west, over the Beacon and the village, to
# Trevaunance Cove and Trevellas Porth in the north-east. 4 x 3.5 km.
XMIN, YMIN, XMAX, YMAX = 169500, 49000, 173500, 52500
CX, CY = (XMIN + XMAX) / 2, (YMIN + YMAX) / 2

# Downloads and ground textures come in square chunks of this many meters.
CHUNK = 500
NX, NY = int((XMAX - XMIN) / CHUNK), int((YMAX - YMIN) / CHUNK)

# Ground raster resolution in meters per pixel.
GROUND_RES = 0.25

# Environment Agency lidar comes at 1 m. The renderer's terrain mesh has a point every 2 m, the viewer's height map
# every 4 m.
LIDAR_RES = 1.0
TERRAIN_RES = 2.0
VIEWER_RES = 4.0

# The tide we draw, in metres above Ordnance Datum (about mean sea level): low water. The north coast of Cornwall
# has a tidal range of six to seven metres, and at low water the beaches of Trevaunance Cove and Chapel Porth are dry.
SEA_LEVEL = -2.5

# The compass directions the map is rendered from (render/run.mjs --look); the first is the one the viewer opens on.
VIEWS = (45, 135, 225, 315)


def write_area():
    """The renderer and the viewer read the area from here; scripts/build_terrain.py adds the terrain to it."""
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / "area.json"
    area = json.loads(path.read_text()) if path.exists() else {}
    area.update({"xmin": XMIN, "ymin": YMIN, "xmax": XMAX, "ymax": YMAX, "cx": CX, "cy": CY, "chunk": CHUNK, "nx": NX, "ny": NY})
    path.write_text(json.dumps(area))
