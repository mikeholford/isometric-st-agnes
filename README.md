# Isometric St Agnes

A zoomable isometric pixel-art map of St Agnes on the north coast of Cornwall: 4 × 3.5 km from Chapel Porth and Wheal Coates, over the Beacon and the village, to Trevaunance Cove and Trevellas Porth. It is rendered procedurally from open data, so it is exact, seamless and rebuilds in about twenty minutes.

It follows [Isometric Helenaveen](https://jankeesvw.github.io/isometric-helenaveen/) by [@jankeesvw](https://github.com/jankeesvw/isometric-helenaveen), whose pipeline, renderer and viewer this is. That map is built from Dutch open data; this one swaps in what England has, and adds what a flat Dutch peat village does not need: terrain.

## What is different from the example

| | Helenaveen | St Agnes |
|---|---|---|
| Grid | RD New (EPSG:28992) | British National Grid (EPSG:27700), `scripts/geo.py` |
| Heights | AHN, 50 cm | Environment Agency LIDAR Composite 2022, 1 m: bare earth (DTM) and first return (DSM) |
| Buildings | 3D BAG solids with roof shapes | Outlines from OpenStreetMap, and OS OpenMap Local where OpenStreetMap has none; height, roof rise and ridge direction measured per outline in the lidar (`scripts/build_buildings.py`) |
| Ground | BGT polygons, coloured with an aerial photo | Land use from OpenStreetMap and OS OpenMap Local; sea, foreshore, cliffs, hedges and scrub from the lidar and the OS low water mark (`scripts/build_ground.py`) |
| Aerial photo | PDOK, 25 cm | None: no open photo newer than 2008 covers the village, so colours come from what a surface is |
| Terrain | Flat | A real surface (`scripts/build_terrain.py`): the renderer drapes the ground over it, buildings and trees stand on it, the viewer looks heights up in `height.png` |
| Traffic | Drives on the right | Drives on the left, and disappears behind hills |

## Pipeline

Run `./build.sh` for everything. The steps:

1. `scripts/fetch.py` downloads the raw data into `data/raw/`: lidar in 2 km blocks, one request at a time (the service allows only a few a minute), OS OpenMap Local for grid square SW, and OpenStreetMap through Overpass.
2. `scripts/build_terrain.py` mosaics the lidar and decides where the sea is: the lidar measured the water at whatever the tide was, so the sea is OS tidal water below the low water mark.
3. `scripts/landmarks.py` names the places people look for and gives some their own look: the church spire, the engine houses and stacks of Wheal Coates and Blue Hills. `scripts/build_buildings.py` builds every building: a gabled roof for a simple outline, a hipped one for an L or a T, flat where the lidar is level.
4. `scripts/build_trees.py` finds individual trees in the canopy height model (surface minus bare earth).
5. `scripts/build_ground.py` paints the ground in a fixed palette: pasture and ploughed fields with hedges, the heather and gorse of the Beacon, mine waste, sand, slate cliffs with their beds, and a sea that deepens from turquoise to blue with surf along the shore. It bakes in the light on every slope and the shadows of land, buildings and trees.
6. `render/scene.js` is a three.js scene with a 2:1 isometric orthographic camera, rendered tile by tile in headless Chromium by `render/run.mjs`, from all four diagonal directions (`VIEWS` in `scripts/config.py`).
7. `./site.sh` cuts the images into Deep Zoom pyramids of WebP tiles and assembles `site/` with `viewer/index.html` (OpenSeadragon): search, named places with a story, the South West Coast Path, traffic, evening light, and a compass button that turns the map a quarter.

`./deploy.sh` publishes `site/` to the `gh-pages` branch as a single fresh commit.

## Iterating

`node render/run.mjs crop <x> <y> <w> <h> --scale 4 --out out/crop.png` renders one region of the full image in a second. `node render/run.mjs crop 0 0 4000 2400 --scale 0.75` gives an overview of the whole map.

For another place in England: set the area in `scripts/config.py`, the grid square in `scripts/fetch.py` (`OS_SQUARE`), measure `GRID_FIX` in `scripts/geo.py` again, and write your own `scripts/landmarks.py`.

## Data and licences

- Lidar: © Environment Agency copyright and/or database right 2022. All rights reserved. [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
- OS OpenMap Local: contains OS data © Crown copyright and database right 2026. Open Government Licence v3.0.
- Buildings, land use, roads, paths, names and points of interest: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL.
- Music: [My Street](https://opengameart.org/content/my-street) by congusbongus, CC0.
- Code: after [jankeesvw/isometric-helenaveen](https://github.com/jankeesvw/isometric-helenaveen).
