# Wine Cellar add-on: status (2026-10-13)

Installed: 0.3.2. Next: 0.4.0 (stats page, CSV/JSON export, Grafana views and dashboard; Racks hidden).

## Racks (paused, work saved)
Built and tested, switched off at the user's request (did not like drag-and-drop sorting).
- Patch against 0.3.2: `wine-cellar-racks-wip.patch` (server, UI, tests).
- To re-enable: remove `hidden` from `#racksBtn` in index.html. The backend endpoints (/api/racks, /api/bottles/place, fill, clear) and tables wc_racks / wc_bottles are already in 0.4.0.
- Touch drag (press and hold) was not tested on a real device.

## Systembolaget
Strict matching works; user's cellar is mostly local producers, so almost nothing matches. Default is now off for new installs.

## Ideas not built
Value history with dated points, "Check price" links, drinking-window estimate, HA sensors/alerts, tasting notes with photos, wishlist.
