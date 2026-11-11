# /// script
# requires-python = ">=3.11"
# dependencies = ["pyshp"]
# ///
"""Download the raw open data for the area: Environment Agency lidar, OS OpenMap Local and OpenStreetMap.

  lidar/            1 m bare-earth terrain (DTM) and first-return surface (DSM) of the Environment Agency's National
                    LIDAR Programme composite, Open Government Licence v3.0
  os_*.geojson      buildings, woodland, water, foreshore and tidal lines of OS OpenMap Local for the 100 km grid
                    square, cut to the area, Open Government Licence v3.0
  osm_*.json        buildings, land use, roads, walking routes, names and points of interest, ODbL
"""

import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile

from config import RAW, XMAX, XMIN, YMAX, YMIN
from geo import grid_to_wgs

UA = {"User-Agent": "isometric-village-map/0.1"}

# Environment Agency LIDAR Composite, 1 m, on the Defra Data Services Platform: dataset and coverage per model.
LIDAR = "https://environment.data.gov.uk/spatialdata"
COVERAGES = {
    "dtm": ("lidar-composite-digital-terrain-model-dtm-1m", "13787b9a-26a4-4775-8523-806d13af58fc__Lidar_Composite_Elevation_DTM_1m"),
    "dsm": ("lidar-composite-digital-surface-model-first-return-dsm-1m", "df4e3ec3-315e-48aa-aaaf-b5ae74d7b2bb__Lidar_Composite_Elevation_FZ_DSM_1m"),
}

# OS OpenMap Local comes per 100 km square of the National Grid; St Agnes is in SW.
OS_SQUARE = "SW"
OS_LAYERS = ["Building", "ImportantBuilding", "Woodland", "SurfaceWater_Area", "SurfaceWater_Line", "Foreshore", "TidalWater", "TidalBoundary", "Glasshouse", "NamedPlace"]
MARGIN = 60  # metres around the area, so shapes that cross its edge come whole
LIDAR_BLOCK = 2000  # metres a side per lidar request: 2000 x 2000 cells of 1 m


def get(url, binary=False, tries=5, data=None):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA, data=data), timeout=180) as r:
                body = r.read()
                return body if binary else json.loads(body)
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                raise
            print(f"retry {attempt + 1} {url[:100]}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))


def lidar_blocks():
    """The area in blocks of at most LIDAR_BLOCK metres a side: (x0, y0, width, height)."""
    return [
        (x0, y0, min(LIDAR_BLOCK, XMAX - x0), min(LIDAR_BLOCK, YMAX - y0))
        for x0 in range(XMIN, XMAX, LIDAR_BLOCK)
        for y0 in range(YMIN, YMAX, LIDAR_BLOCK)
    ]


def fetch_lidar(kind, x0, y0, w, h):
    """One block of lidar heights. The service allows only a few requests a minute (it answers 429 beyond that), so
    the blocks are large, fetched one after the other, and a refusal means: wait a good while."""
    d = RAW / "lidar"
    d.mkdir(exist_ok=True)
    out = d / f"{kind}_{x0}_{y0}_{w}_{h}.tif"
    if out.exists():
        return
    dataset, coverage = COVERAGES[kind]
    url = (
        f"{LIDAR}/{dataset}/wcs?service=WCS&version=2.0.1&request=GetCoverage&CoverageId={coverage}"
        f"&format=image/tiff&subset=E({x0},{x0 + w})&subset=N({y0},{y0 + h})"
    )
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
                body = r.read()
            if body[:2] in (b"II", b"MM"):
                out.write_bytes(body)
                print(f"lidar {kind} {x0},{y0}: {len(body) >> 20} MB", file=sys.stderr)
                time.sleep(5)
                return
            raise RuntimeError(f"not a TIFF: {body[:120]!r}")
        except Exception as e:  # noqa: BLE001
            wait = 60 * (attempt + 1) if getattr(e, "code", None) == 429 else 10 * (attempt + 1)
            print(f"lidar {kind} {x0},{y0}: {e}; waiting {wait} s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"lidar {kind} {x0},{y0}: gave up")


def fetch_os():
    """The layers of OS OpenMap Local we use, as GeoJSON in grid metres, cut to the area."""
    if all((RAW / f"os_{layer.lower()}.geojson").exists() for layer in OS_LAYERS):
        return
    import shapefile  # pyshp

    cache = RAW / f"OpenMapLocal_{OS_SQUARE}.zip"
    if not cache.exists():
        url = f"https://api.os.uk/downloads/v1/products/OpenMapLocal/downloads?area={OS_SQUARE}&format=ESRI%C2%AE+Shapefile&redirect"
        cache.write_bytes(get(url, binary=True))
    box = (XMIN - MARGIN, YMIN - MARGIN, XMAX + MARGIN, YMAX + MARGIN)
    with zipfile.ZipFile(cache) as z:
        names = z.namelist()
        for layer in OS_LAYERS:
            base = next((n[:-4] for n in names if n.endswith(f"_{layer}.shp")), None)
            feats = []
            if base:
                part = lambda ext: io.BytesIO(z.read(base + ext))
                with shapefile.Reader(shp=part(".shp"), shx=part(".shx"), dbf=part(".dbf")) as r:
                    for sr in r.iterShapeRecords(bbox=box):
                        feats.append({"type": "Feature", "properties": sr.record.as_dict(), "geometry": sr.shape.__geo_interface__})
            (RAW / f"os_{layer.lower()}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, default=str))
            print(f"os {layer}: {len(feats)}", file=sys.stderr)


def overpass(out, q, what):
    """Run an Overpass query into out (Overpass is often busy, so try a few servers)."""
    if out.exists():
        return
    for host in ("overpass-api.de/api/interpreter", "overpass.private.coffee/api/interpreter", "maps.mail.ru/osm/tools/overpass/api/interpreter"):
        try:
            body = get(f"https://{host}", binary=True, tries=2, data=urllib.parse.urlencode({"data": q}).encode())
            json.loads(body)["elements"]  # an error page is not JSON
            out.write_bytes(body)
            return
        except Exception as e:  # noqa: BLE001
            print(f"overpass {host}: {e}", file=sys.stderr)
    print(f"OpenStreetMap unavailable; {what} are skipped", file=sys.stderr)


def osm_bbox():
    lats, lons = zip(*(grid_to_wgs(x, y) for x in (XMIN - MARGIN, XMAX + MARGIN) for y in (YMIN - MARGIN, YMAX + MARGIN)))
    return f"{min(lats)},{min(lons)},{max(lats)},{max(lons)}"


def fetch_osm():
    bbox = osm_bbox()
    overpass(RAW / "osm_buildings.json", f'[out:json][timeout:90];way["building"]({bbox});out geom tags;', "building outlines")
    overpass(
        RAW / "osm_land.json",
        f"""[out:json][timeout:120];
( nwr["landuse"]({bbox}); nwr["natural"~"^(heath|scrub|wood|grassland|fell|beach|sand|bare_rock|scree|shingle|rock|water|wetland)$"]({bbox});
  nwr["leisure"]({bbox}); nwr["amenity"~"^(parking|school|grave_yard)$"]({bbox}); nwr["tourism"~"^(camp_site|caravan_site)$"]({bbox}); );
out geom;""",
        "land use",
    )
    # Pitches, graveyards, single trees and everything a visitor might look for.
    overpass(
        RAW / "osm_landmarks.json",
        f"""[out:json][timeout:90];
( way["leisure"="pitch"]({bbox}); nwr["landuse"="cemetery"]({bbox}); nwr["amenity"="grave_yard"]({bbox});
  nwr["amenity"="place_of_worship"]({bbox}); nwr["tourism"]({bbox}); nwr["historic"]({bbox}); nwr["man_made"]({bbox});
  node["natural"="tree"]({bbox}); );
out geom tags;""",
        "pitches, graveyards and points of interest",
    )
    # Everything with a name, for the search box: streets, pubs, shops, coves, farms.
    overpass(RAW / "osm_names.json", f'[out:json][timeout:90];nwr["name"]({bbox});out center tags;', "names for the search box")
    overpass(
        RAW / "osm_routes.json",
        f'[out:json][timeout:120];( relation["route"~"^(hiking|foot|walking)$"]({bbox}); );out geom;',
        "walking routes",
    )
    kinds = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service"
    overpass(
        RAW / "osm_roads.json",
        f"""[out:json][timeout:120];
( way["highway"~"^({kinds})$"]({bbox}); way["highway"~"^(cycleway|footway|path|pedestrian|track|steps|bridleway)$"]({bbox}); );
out geom;""",
        "roads and paths",
    )


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    fetch_osm()  # one query at a time: the public Overpass servers turn away parallel requests
    fetch_os()
    for kind in COVERAGES:
        for block in lidar_blocks():
            fetch_lidar(kind, *block)
    print("done", file=sys.stderr)


if __name__ == "__main__":
    main()
