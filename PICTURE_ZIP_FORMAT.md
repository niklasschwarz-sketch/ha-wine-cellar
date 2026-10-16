# Picture zip format

Wine Cellar can attach many bottle pictures at once: **More → Import / export → Import pictures from a zip**. You can make the zip by hand, with your own script, or with any tool. This page is the full specification.

The app only reads the zip you give it. It does not check where the pictures came from. **Only add pictures you have the right to use**, for example your own photos, pictures with an open licence, or pictures you keep for private use only. The optional `sources.json` file lets you record where each one came from, and the app shows that under the picture.

## 1. What goes in the zip

A flat list of picture files and, optionally, one `sources.json`:

```
my-pictures.zip
├── 12.jpg
├── 48.png
├── i123456.webp
├── wc-7.jpg
└── sources.json        (optional)
```

Folders inside the zip are allowed (only the file name counts), and macOS `__MACOSX` entries are ignored.

## 2. File names: which wine the picture belongs to

The name before the extension says which wine gets the picture. Use one of three forms:

| Name | Meaning | Where to find the number |
|---|---|---|
| `12.jpg` | The wine's number in Wine Cellar | `id` of each wine in **Import / export → Download full copy (JSON)** |
| `i123456.jpg` | The wine's CellarTracker number (iWine) | The `iWine` column of a CellarTracker CSV export, or of the app's CSV download |
| `wc-12.jpg` | Same as `12.jpg` (the form the app's CSV uses for wines that have no CellarTracker number) | The `iWine` column of the app's CSV download, where it reads `wc-12` |

Extensions: `.jpg`, `.jpeg`, `.png` or `.webp`, in any letter case.

## 3. The pictures

- JPEG, PNG or WebP. The app checks the file's content, not just its name, and skips anything else.
- At most **3 MB per picture**. About 1000 pixels on the long side is plenty and keeps the cellar small.
- At most **600 files** and **200 MB** in total after unpacking, and the zip itself at most **64 MB**.
- One picture per wine. If a wine appears twice, the later file wins.

## 4. Optional `sources.json`

A JSON object. Each key is the file name **without** the extension, exactly as written in the zip (`"12"`, `"i123456"`, `"wc-7"`):

```json
{
  "12":      { "url": "https://example.com/page-with-the-picture", "credit": "Example Wine Shop" },
  "i123456": { "own": true },
  "wc-7":    { "credit": "Photo: my sister" }
}
```

| Field | Meaning |
|---|---|
| `url` | Link shown under the picture ("Picture from …"). Must start with `http://` or `https://`, otherwise it is ignored. |
| `credit` | Text of that link, up to 120 characters. Default: "Picture found on the web". |
| `own` | `true` marks the picture as **your own photo**. It is then treated like a photo you took in the app: it is never replaced by pictures found online, and it replaces an older picture. |

## 5. What the import does

For every picture file the app:

1. Skips it if it is not a real JPEG, PNG or WebP, or is over 3 MB (counted as "files skipped").
2. Finds the wine from the file name. If there is no such wine it is counted as "wines not found".
3. Leaves the wine alone if it already has a photo you uploaded yourself, unless this picture has `"own": true` in `sources.json` (counted as "of your own photos kept").
4. Otherwise saves the picture, replacing the old one, together with its source link and credit.

When it finishes, a message at the bottom shows the counts. Nothing else in your cellar is changed, and nothing is deleted.

## 6. Make a zip yourself

Name the pictures by wine number (here with the numbers 12 and 48) and zip them, on macOS or Linux:

```
zip my-pictures.zip 12.jpg 48.png
```

With Python, including a `sources.json`:

```python
import json, zipfile

files = {"12.jpg": "https://example.com/page", "48.png": None}   # file -> source link (or None)
with zipfile.ZipFile("my-pictures.zip", "w") as z:
    sources = {}
    for name, url in files.items():
        z.write(name)
        stem = name.rsplit(".", 1)[0]
        sources[stem] = {"url": url, "credit": "Example Wine Shop"} if url else {"own": True}
    z.writestr("sources.json", json.dumps(sources))
```

## 7. Tools that make such a zip

The app does not need any particular tool. The separate project [Picture finder for HA Wine Cellar](https://github.com/niklasschwarz-sketch/Picture-finder-for-Ha-Wine-Cellar) runs on your own computer and builds a zip in this format from an image-search service. It is optional, and it is not part of this repository or the add-on.
