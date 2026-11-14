# Isometric St Agnes

A zoomable isometric miniature of St Agnes on the north coast of Cornwall: 4 × 3.5 km from Chapel Porth and Wheal Coates, over the Beacon and the village, to Trevaunance Cove and Trevellas Porth. It is rendered procedurally from open data, so it is exact and seamless, and it rebuilds from scratch on a laptop with a graphics card.

It follows [Isometric Helenaveen](https://jankeesvw.github.io/isometric-helenaveen/) by [@jankeesvw](https://github.com/jankeesvw/isometric-helenaveen), whose pipeline, renderer and viewer this is. That map is built from Dutch open data; this one swaps in what England has, and adds what a flat Dutch peat village does not need: terrain.

## What is different from the example

| | Helenaveen | St Agnes |
|---|---|---|
| Grid | RD New (EPSG:28992) | British National Grid (EPSG:27700), `scripts/geo.py` |
| Heights | AHN, 50 cm | Environment Agency LIDAR Composite 2022, 1 m: bare earth (DTM) and first return (DSM) |
| Buildings | 3D BAG solids with roof shapes | Outlines from OpenStreetMap, and OS OpenMap Local where OpenStreetMap has none, say where a building stands. Its real footprint and roof planes come from the lidar surface, on a 1 m grid square to the building (`scripts/roofs.py`). OS OpenMap Local draws a terrace as one block, so each block is divided among its address points (OS Open UPRN) and every house has its own walls. A house newer than the lidar survey gets a standard roof (`scripts/build_buildings.py`) |
| Ground | BGT polygons, coloured with an aerial photo | Land use from OpenStreetMap and OS OpenMap Local; sea, foreshore, cliffs, hedges and scrub from the lidar and the OS low water mark (`scripts/build_ground.py`) |
| Aerial photo | PDOK, 25 cm | None: no open photo newer than 2008 covers the village, so colours come from what a surface is |
| Terrain | Flat | A real surface (`scripts/build_terrain.py`): the renderer drapes the ground over it, buildings and trees stand on it, the viewer looks heights up in `height.bin` (plain numbers: a browser may adjust the colours of a picture) |
| Traffic | Drives on the right | Drives on the left, and disappears behind hills |
| Road names | Not shown | The name shows when the pointer is on a road (`scripts/build_roads.py`): names from OpenStreetMap, and from OS OpenMap Local where OpenStreetMap has none |
| Turning | A button | The button, or hold Command (Ctrl on other keyboards) and drag |

## Bolster the giant

The giant of the St Agnes legend is always out walking somewhere on the map: on a road, a path or the sand of a beach. Everyone sees him in the same place, with no server: the day is cut into legs of twenty minutes, and the number of a leg seeds the dice that pick where he starts and every turn he takes (`bolsterLeg` in `viewer/index.html`). Click him and a card gives the time and place of the find, with a link (`#bolster=<seconds since 1970>`) that shows anyone where he stood at that minute. He is then gone for that visitor until his next leg.

He is drawn from the old sources: Robert Hunt (1865) and George Cruikshank's drawing in Hunt's book give a belted tunic to the knee, bare lower legs, great hands and a knife, and no club. The beard and the leaves in his hair nod to the village's Bolster Festival. His story is on the map at the Beacon, Chapel Porth and the Bolster Bank.

He walks as a body of his size would. A leg swings like a pendulum of its own length, so with his hip 3.4 m up a step takes π√(L/g) = 1.85 s, and at 1.9 m/s on level ground it is 3.5 m long. The beat stays the same; the land changes the length of the step: shorter uphill, a little longer down a gentle fall, shorter again where he has to brake (Tobler's hiking function). Every footfall of a leg is laid out along the route before he takes the first (`footfalls`), a foot on the ground stays on its spot until it is lifted, and he leans into a hill. All of it follows from the time, so the link still gives the place. Legs before `HILLS_FROM` keep the old steady pace, so links to older finds still show the right spot: set it to the leg in which this goes live.

His shadow is cast by the real sun over St Agnes at this minute (`sunAt`), along the land as it rises and falls, crisp at his feet and soft at his head. After dark he carries a lantern that lights the road around him.

## Light and lens

The light on the map follows the real sun (`HOURS` in `viewer/index.html`): golden toward sunset, violet in the dusk, moonlit after, with the lamps coming on as it gets dark. A light map is multiplied with the map, so a lamp gives the ground its own colours back. The moon button turns to night or day by hand for the visit. The houses and trees keep the shadows they were rendered with (`scripts/sun.py`); only what moves has a shadow from the sun of the hour.

The lens is what makes it a miniature: one small WebGL pass over a copy of the screen at about a third of its size blurs every point by how far it lies from the plane of focus, using the heights of the land, and adds bloom and a vignette. It is laid over the sharp map, so the full-size picture never goes through a shader and a phone keeps up. `?lens=off` shows the map without it.

## Deep places

Some places on the map can be gone into much closer than the rest: 64 pixels to the metre where the map has 8. Zoom in on one and, past what the map's own tiles hold, a far more detailed picture of the place comes up over the map; there the zoom goes on to where a slate on a roof is a few pixels wide. Zoomed out, nothing of it is loaded.

`deep/scene.py` makes that picture. It rebuilds the place in Blender and renders it with Cycles, a path tracer, from exactly where the map's camera stands, so that the picture lies on the map to the pixel, with the sun where the map has it. What is real is what the map knows: the shape of the land, the outlines and heights of the buildings, the roads, where each tree stands and how big it is. Everything smaller is made up by rule (`deep/details.py`): slates laid in courses, rubble walls, sash windows, doors, chimney pots, grass by the blade, flowers, stone hedges, gravestones round a church, paint on the road, parked cars. What is put somewhere by hand, also made up, is in `deep/scenes/<place>.py`: the phone box by the church, a bench, people talking. Cars, walkers and the giant are left out of the tiles, since the map draws its own, and they pass behind the deep buildings and trees as they do behind the map's.

```
uv run deep/scene.py churchtown --try     # one small picture, timed: says how long the whole place will take
uv run deep/scene.py churchtown           # the place as tiles, in out/deep/churchtown-45/
./site.sh                                 # puts the deep places into site/ with the rest
```

It needs [uv](https://docs.astral.sh/uv/) and the data of the pipeline below (`data/build/`); uv fetches Blender as a Python module by itself. A graphics card is used when there is one (Metal on a Mac with an Apple chip, `--device cpu` to do without). The render is done in chunks, each a file of its own, so one that was cut short goes on where it stopped. `--look 135` renders another of the map's four views, `--scale 32` half as sharp in a quarter of the time. `--picture out/x.png --across 48 --movers` makes a single picture instead, with the giant in it.

A new place is a line in `deep/places.json`: a name, the spot in the middle of the picture in the map's local metres (x east and z south of the middle of the map), and how wide and high the picture is in metres on the screen. A file of the same name in `deep/scenes/` is run after the rules, for what belongs only there.

The tiles of a deep place are heavy next to the rest of the site: all of Churchtown is about as much as a whole view of the map. They do not have to live with the site. `DEEP_URL=https://... ./site.sh` writes only the list (`deep.json`) and expects `out/deep/` to have been uploaded under that address, to any plain store of files.

## Pipeline

Run `./build.sh` for everything. The steps:

1. `scripts/fetch.py` downloads the raw data into `data/raw/`: lidar in 2 km blocks, one request at a time (the service allows only a few a minute), OS OpenMap Local for grid square SW, and OpenStreetMap through Overpass.
2. `scripts/build_terrain.py` mosaics the lidar and decides where the sea is: the lidar measured the water at whatever the tide was, so the sea is OS tidal water below the low water mark.
3. `scripts/landmarks.py` names the places people look for and gives some their own look: the church spire, the engine houses and stacks of Wheal Coates and Blue Hills. `scripts/build_buildings.py` builds every building: a gabled roof for a simple outline, a hipped one for an L or a T, flat where the lidar is level.
4. `scripts/build_trees.py` finds individual trees in the canopy height model (surface minus bare earth).
5. `scripts/build_ground.py` paints the ground in a fixed palette: pasture and ploughed fields with hedges, the heather and gorse of the Beacon, mine waste, sand, slate cliffs with their beds, and a sea that deepens from turquoise to blue with surf along the shore. It bakes in the light on every slope and the shadows of land, buildings and trees.
6. `render/scene.js` is a three.js scene with a 2:1 isometric orthographic camera, rendered tile by tile in headless Chromium by `render/run.mjs`, from all four diagonal directions (`VIEWS` in `scripts/config.py`). The map is rendered at 8 pixels to the metre, and every tile twice as large each way and averaged down (`--ss 2`), so roof edges and tree crowns come out smooth instead of stepped. The painterly filter and the ink lines are measured in metres, so they look the same at any resolution.
7. `./site.sh` cuts the images into Deep Zoom pyramids of WebP tiles, 512 pixels a side, and assembles `site/` with `viewer/index.html` (OpenSeadragon): search, named places with a story, the South West Coast Path, traffic, the light of the hour, and a compass button that turns the map a quarter. `map.json` tells the viewer the scale and the tile size.

`./deploy.sh` publishes `site/` to the `gh-pages` branch as a single fresh commit.

## Iterating

`node render/run.mjs crop <x> <y> <w> <h> --scale 8 --ss 2 --kuwahara 2 --out out/crop.png` renders one region of the full image in a second. `node render/run.mjs crop 0 0 4000 2400 --scale 0.75` gives an overview of the whole map. `SCALE=4 SS=1 ./build.sh` is the quick build: a quarter of the pixels and no smoothing of edges.

On a machine without a graphics card, `ANGLE=swiftshader` renders in software, which is slow but exact; `CHROME=<path>` picks another Chromium than the one Playwright installed.

For another place in England: set the area in `scripts/config.py`, the grid square in `scripts/fetch.py` (`OS_SQUARE`), measure `GRID_FIX` in `scripts/geo.py` again, and write your own `scripts/landmarks.py`.

## Data and licences

- Lidar: © Environment Agency copyright and/or database right 2022. All rights reserved. [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
- OS OpenMap Local and OS Open UPRN: contains OS data © Crown copyright and database right 2026. Open Government Licence v3.0.
- Buildings, land use, roads, paths, names and points of interest: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL.
- Music: [My Street](https://opengameart.org/content/my-street) by congusbongus, CC0.
- Code: after [jankeesvw/isometric-helenaveen](https://github.com/jankeesvw/isometric-helenaveen).
