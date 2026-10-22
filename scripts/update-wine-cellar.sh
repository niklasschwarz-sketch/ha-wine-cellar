#!/bin/sh
# Developer helper: copies the newest Wine Cellar from GitHub into your Home Assistant's local add-ons folder and updates it.
# Normal users do not need it: add the repository in the add-on store instead (see the README).
# Run it in the "Terminal & SSH" add-on:   sh update-wine-cellar.sh
# It works without a token while the repository is public. For a private copy, run it with REQUIRE_TOKEN=1: it asks once for a
# read-only GitHub token and remembers it. A BRANCH=name prefix picks another branch.
set -e
REPO="niklasschwarz-sketch/ha-wine-cellar"
BRANCH="${BRANCH:-main}"
SLUG="local_wine_cellar"
TOKEN_FILE="${TOKEN_FILE:-/root/.wine_cellar_token}"
URL="${WC_URL:-https://api.github.com/repos/$REPO/tarball/$BRANCH}"

D=/local_apps; [ -d "$D" ] || D=/addons
[ -d "$D" ] || { echo "Could not find the local add-ons folder (/local_apps)."; exit 1; }

TOKEN=""
[ -f "$TOKEN_FILE" ] && TOKEN="$(cat "$TOKEN_FILE")"
if [ -z "$TOKEN" ] && [ -z "$WC_URL" ] && [ -n "$REQUIRE_TOKEN" ]; then
  echo "A GitHub token is needed once. Create it at github.com > Settings > Developer settings >"
  echo "Personal access tokens > Fine-grained tokens: only the repository $REPO, permission Contents: Read-only."
  printf "Paste the token and press Enter (it is not shown): "
  stty -echo 2>/dev/null || true
  read -r TOKEN
  stty echo 2>/dev/null || true
  echo
  [ -n "$TOKEN" ] || { echo "No token entered."; exit 1; }
fi

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
CODE="$(curl -sSL -o "$W/src.tgz" -w '%{http_code}' ${TOKEN:+-H "Authorization: Bearer $TOKEN"} -H "Accept: application/vnd.github+json" "$URL" || true)"
case "$CODE" in
  200|000) ;;   # 000 is what curl reports for a local file
  401|403|404)
    [ -z "$TOKEN" ] && { echo "GitHub cannot see the repository without a token (HTTP $CODE). If it is private, run:  REQUIRE_TOKEN=1 sh update-wine-cellar.sh"; exit 1; }
    rm -f "$TOKEN_FILE"
    echo "GitHub said no (HTTP $CODE): $(head -c 300 "$W/src.tgz" | tr '\n' ' ')"
    case "$CODE" in
      401) echo "The token is wrong or expired. Make a new one and run the script again." ;;
      403) echo "The token can be read but is not allowed to download this repository. Check: Resource owner is niklasschwarz-sketch, Repository access includes ha-wine-cellar, and Repository permissions > Contents is Read-only. Or you hit a rate limit; wait a few minutes." ;;
      404) echo "GitHub cannot see the repository with this token. Check the token's repository access and that it has not expired." ;;
    esac
    echo "The saved token was forgotten. Run the script again with a corrected token."; exit 1 ;;
  *) echo "Download failed (HTTP $CODE): $(head -c 300 "$W/src.tgz" | tr '\n' ' ')"; exit 1 ;;
esac
[ -s "$W/src.tgz" ] || { echo "Nothing was downloaded. Check that Home Assistant has internet access."; exit 1; }
[ -n "$TOKEN" ] && [ -z "$WC_URL" ] && { umask 077; printf '%s' "$TOKEN" > "$TOKEN_FILE"; }

mkdir -p "$W/x" && tar xzf "$W/src.tgz" -C "$W/x"
SRC="$(find "$W/x" -maxdepth 2 -type d -name wine_cellar | head -1)"
[ -n "$SRC" ] && [ -f "$SRC/config.yaml" ] || { echo "The download did not contain the wine_cellar folder."; exit 1; }

NEWV="$(grep -m1 '^version' "$SRC/config.yaml" | tr -d '"' | awk '{print $2}')"
OLDV="none"; [ -f "$D/wine_cellar/config.yaml" ] && OLDV="$(grep -m1 '^version' "$D/wine_cellar/config.yaml" | tr -d '"' | awk '{print $2}')"
echo "Installed folder: $OLDV   GitHub: $NEWV"
rm -rf "$D/wine_cellar.new" && cp -R "$SRC" "$D/wine_cellar.new"
rm -rf "$D/wine_cellar" && mv "$D/wine_cellar.new" "$D/wine_cellar"
echo "Copied version $NEWV into $D/wine_cellar"

if command -v ha >/dev/null 2>&1; then
  ha addons reload >/dev/null 2>&1 || true
  if [ "$OLDV" = "$NEWV" ]; then
    echo "Same version number, rebuilding the add-on..."; ha addons rebuild "$SLUG" || echo "Rebuild it in Settings > Add-ons > Wine Cellar."
  else
    echo "Updating the add-on (it restarts)..."; ha addons update "$SLUG" || echo "Press Update on Wine Cellar in Settings > Add-ons (use the three dots > Check for updates first)."
  fi
else
  echo "Now open Settings > Add-ons > Add-on store > three dots > Check for updates, then Wine Cellar > Update."
fi
