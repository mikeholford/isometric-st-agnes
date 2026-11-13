# Isometric St Agnes

A zoomable isometric pixel-art map of St Agnes on the north coast of Cornwall: 4 × 3.5 km from Chapel Porth and Wheal Coates, over the Beacon and the village, to Trevaunance Cove and Trevellas Porth. It is rendered procedurally from open data, so it is exact, seamless and rebuilds in about twenty minutes.

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

The giant of the St Agnes legend is always out walking somewhere on the map: on a road, a path or the sand of a beach. Everyone sees him in the same place, with no server. The day is cut into legs of twenty minutes, and the number of a leg seeds the dice that pick where he starts and every turn he takes (`bolsterLeg` in `viewer/index.html`). A second dice, used only for the pauses where he stops and looks about, does not change that route. An old link still names the same roads. Because he now slows on hills and stops to look, the same link puts him where this walk would have put him.

He walks at 1.9 metres a second on the flat. The step is a pendulum. With a leg scaled from his 6.4 metre height, a full swing and back is 2π√(L/g), and one step is half of that, a little under two seconds. The foot on the ground stays where he put it until he lifts it. Uphill the step shortens and he leans into the hill. Downhill the step shortens too, and he waits longer on the planted foot, so he stays slower than on the flat.

His shadow is the sun at St Agnes for this minute, long when the sun is low. After dark he carries a lantern, which lights the road around him. The sun is worked from UTC and the longitude, so every visitor shares it. The painted map keeps the sun it was rendered with. Footprints sink into sand, and the tide takes them. The tide is the Open-Meteo marine forecast when that answers, and otherwise a harmonic tide of the M2 and S2, sized toward the 3.2 metre springs of this coast. That harmonic is an approximation, not a published prediction. Grass keeps a fainter print. On a hard road there is only a puff of dust. Wind and rain come from Open-Meteo as well. They move his tunic, his hair and his straw beard, and rain darkens him and splashes at his feet. They do not move him. If the forecast does not arrive, the air is calm and dry, the harmonic tide is used, and he is still in the same place.

Gulls at Chapel Porth lift as he comes near. If he wades there and the water is over his feet, but not yet up to his knee, the sea foams round his ankles. A building, a hedge or a tree in front of him is the layer of buildings and trees, so it covers the part of him it stands in front of, and his head still shows above a roof or a crown. A hill, the Beacon included, is the ground itself. The part of him the land hides is not drawn, and turning the map turns that hidden part with it.

Click him and a card gives the time and place, a short piece of the legend with its source, and a note to copy. The link is still `#bolster=<seconds since 1970>`. He is then gone for that visitor until the next leg. Finds, and the streak of days, live in that browser only. A shared tally of finds would need a server, and there is not one. The rumour at the top of the menu starts vague and grows sharper as the twenty minutes go on. In the first two minutes of a leg the card says you found him as he set out. Footsteps can be turned on when the map is close. They stay off unless the visitor asks.

He is drawn from the old sources: Robert Hunt (1865) and George Cruikshank's drawing in Hunt's book give a belted tunic to the knee, bare lower legs, great hands and a knife, and no club. The beard and the leaves in his hair nod to the village's Bolster Festival. His story is on the map at the Beacon, Chapel Porth and the Bolster Bank. The card quotes only that story, and says where each line comes from.

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
- OS OpenMap Local and OS Open UPRN: contains OS data © Crown copyright and database right 2026. Open Government Licence v3.0.
- Buildings, land use, roads, paths, names and points of interest: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL.
- Music: [My Street](https://opengameart.org/content/my-street) by congusbongus, CC0.
- Code: after [jankeesvw/isometric-helenaveen](https://github.com/jankeesvw/isometric-helenaveen).
