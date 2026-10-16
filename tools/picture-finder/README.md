# Picture finder

A small helper that runs on your own computer (Mac, Windows or Linux) and finds bottle pictures for wines in your cellar. It is not part of the add-on and nothing is installed on Home Assistant.

## What you need
- Python 3 (already on a Mac: open Terminal and type `python3 --version`).
- An image-search API key. This tool uses [Brave Search](https://brave.com/search/api/) (create an account, choose a plan, copy the key). Google's own image search API is closed to new customers and scraping Google is against its terms, so it is not used. Check the current free allowance and terms on Brave's site.

## Steps
1. In Wine Cellar: **More → Import / export → Download full copy (JSON)**.
2. In Terminal, in this folder:
   ```
   BRAVE_API_KEY=your-key python3 picture_finder.py
   ```
   (or save the key once in a file named `.picture_finder_key` in your home folder and run `python3 picture_finder.py`)
3. Open <http://127.0.0.1:8765>, choose the JSON file, press **Search all**.
4. Each wine shows up to 10 candidates and the best match is already selected. Click another picture, or choose **none** to skip. You can also **drag your own picture onto a wine**, or use **add my own picture**.
5. Press **Make zip**, then in Wine Cellar: **More → Import / export → Import pictures from a zip**.

## Good to know
- Only wines without a picture are searched, unless you tick the box to include the others.
- Your own photos in the cellar are never replaced by found pictures. A picture you drop on a wine here counts as your own and does replace the old one.
- The page only answers on this computer. Your API key stays in the program and is never sent to the page.
- Search results come from the open web. Keep the pictures for your own private cellar and do not publish them. The zip also records each picture's source link, which the app shows under the picture.
- Free plans allow roughly one search a second, so 100 wines take about two minutes.

Tests: `python3 test_picture_finder.py` from the repository root (uses a fake search service, needs `pip install playwright`).
