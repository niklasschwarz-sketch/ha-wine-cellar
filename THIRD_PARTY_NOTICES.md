# Third-party software and data

Wine Cellar itself is MIT licensed (see `LICENSE`). The components below keep their own licences.

Wine Cellar is not affiliated with, endorsed by or sponsored by CellarTracker, Vivino, Wine-Searcher, Systembolaget, Open Food Facts, Home Assistant or Nabu Casa. Those names belong to their owners and are used only to say what the add-on can link to or read from.

## Software used inside the add-on
| Component | Licence | Used for |
|---|---|---|
| [Tesseract.js](https://github.com/naptha/tesseract.js) 5.1.1 and tesseract.js-core 5.1.0 | Apache-2.0 | Reading label photos in your own browser. Downloaded while the add-on is built. |
| [tessdata](https://github.com/naptha/tessdata) language files (English, French, Italian, Spanish) | Apache-2.0 | Text recognition models for the label reader. Downloaded while the add-on is built. |
| [pg8000](https://github.com/tlocke/pg8000) 1.31.2 | BSD-3-Clause | Optional database driver, installed in the image. |
| Python standard library, SQLite | PSF licence, public domain | Server and built-in database. |
| Home Assistant add-on base image (Alpine Linux) | Various open-source licences | Runs the add-on. |

The Code 128 barcode encoder, the pairing rules and the icon and logo were written for this project. Code 128 is an open standard (ISO/IEC 15417).

## Data the add-on can fetch (only when you use the feature)
- **Open Food Facts** bottle pictures and product data: pictures are licensed CC BY-SA, data under the ODbL. The add-on stores the picture's source link and credit and shows them under the picture. Pictures you add yourself are yours.
- **Systembolaget prices** (off by default): read from the community-maintained mirror at github.com/AlexGustafsson/systembolaget-api-data, which republishes Systembolaget's public assortment data. The data belongs to Systembolaget. Check their terms before relying on it beyond personal use.
- **Links** to CellarTracker, Vivino, Wine-Searcher and Systembolaget are plain web links. Nothing is copied from those sites. Scores and reviews are typed in by the user.
