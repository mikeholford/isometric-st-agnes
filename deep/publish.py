"""Put the deep places that have been rendered (out/deep/<place>-<look>/, see deep/scene.py) into a site folder, and
write the list the viewer reads them from (deep.json).

  python3 deep/publish.py site

The tiles of a deep place are many and heavy. To keep them somewhere else than the site (a bucket of files with a web
address), say where they will be found and upload out/deep/ there yourself; then only the list is written:

  DEEP_URL=https://tiles.example.org/deep/ python3 deep/publish.py site
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    site, url = Path(sys.argv[1]), os.environ.get("DEEP_URL", "")
    places = []
    for folder in sorted((ROOT / "out" / "deep").glob("*/")):
        if not (folder / "place.json").exists():
            continue
        place = json.loads((folder / "place.json").read_text())
        # In the site, the folder carries the time of the render in its name, as the map's own tiles do: a browser
        # that still holds tiles of an older render then never mixes them with the new ones.
        name = folder.name if url else f"{folder.name}-{int((folder / 'place.json').stat().st_mtime)}"
        base = f"{url.rstrip('/')}/{name}/" if url else f"deep/{name}/"
        if not url:
            for old in (site / "deep").glob(f"{folder.name}*"):
                shutil.rmtree(old, ignore_errors=True)
        for layer in ("tiles", "objects"):
            if not url:
                shutil.copytree(folder / place[layer], site / "deep" / name / place[layer])
            place[layer] = base + place[layer]
        places.append(place)
    (site / "deep.json").write_text(json.dumps({"places": places}))
    print(f"{len(places)} deep places in {site}/deep.json" + (f", their tiles expected under {url}" if url else ""))


if __name__ == "__main__":
    main()
