#!/bin/bash
# Install this fork's Pixel HQ into the local Herdr config, in a chosen palette.
#
#   scripts/install-local.sh                   neutral (the repo's palette)
#   scripts/install-local.sh --palette oled    or: tinted, catppuccin
#
# Steps:
#   1. Back up the installed Pixel HQ files to ~/.config/herdr-app-backup-<timestamp>/.
#   2. Stage the repo's layout, theme and company-* mods in a temp folder and recolor
#      them there from neutral to the chosen palette (scripts/recolor.py), so Herdr
#      never sees a half-recolored file.
#   3. Mirror the staged files into the config folder. Each company-* mod folder is
#      synced with --delete so files removed upstream go away, while Herdr's generated
#      gpui-kit.d.ts / jsconfig.json and __pycache__ are kept and never copied.
#      Nothing else is touched: other layouts, themes and mods, pond-agents.json,
#      pixel-hq-names.json and settings stay as they are.
#   4. Run `herdr-app check` on every installed company-* mod and fail if one fails.
#
# HERDR_APP_HOME picks another config folder, as it does for Herdr itself.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"
PALETTE="neutral"

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --palette) PALETTE="${2:?--palette needs a name}"; shift 2 ;;
    --palette=*) PALETTE="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install-local: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1]))["presets"] else 1)' \
    "$REPO/scripts/palettes.json" "$PALETTE"; then
  echo "install-local: unknown palette '$PALETTE' (see scripts/palettes.json)" >&2
  exit 2
fi
if [ ! -d "$HOME_DIR" ]; then
  echo "install-local: $HOME_DIR does not exist; open Herdr once first" >&2
  exit 1
fi

EXCLUDES=(--exclude gpui-kit.d.ts --exclude jsconfig.json --exclude __pycache__ --exclude '*.pyc' --exclude .DS_Store)
MODS=()
for mod in "$REPO"/mods/company-*/; do MODS+=("$(basename "$mod")"); done

# 1. Back up what is currently installed.
BACKUP="$HOME_DIR-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP/layouts" "$BACKUP/themes" "$BACKUP/mods"
for f in layouts/pixel-hq.json layouts/pixel-hq.svg themes/pixel-hq.json; do
  [ -e "$HOME_DIR/$f" ] && cp -p "$HOME_DIR/$f" "$BACKUP/$f"
done
# No trailing slash on the source: BSD cp would copy the folder's contents instead of the folder itself.
for mod in "$HOME_DIR"/mods/company-*; do
  [ -d "$mod" ] && cp -Rp "$mod" "$BACKUP/mods/"
done
echo "backup:  $BACKUP"

# 2. Stage and recolor.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/layouts" "$STAGE/themes" "$STAGE/mods"
cp -p "$REPO/layouts/pixel-hq.json" "$REPO/layouts/pixel-hq.svg" "$STAGE/layouts/"
cp -p "$REPO/themes/pixel-hq.json" "$STAGE/themes/"
for mod in "${MODS[@]}"; do
  rsync -a "${EXCLUDES[@]}" "$REPO/mods/$mod/" "$STAGE/mods/$mod/"
done
if [ "$PALETTE" != "neutral" ]; then
  python3 "$REPO/scripts/recolor.py" --root "$STAGE" --from neutral --to "$PALETTE" | tail -1
fi

# 3. Put it in place.
mkdir -p "$HOME_DIR/layouts" "$HOME_DIR/themes" "$HOME_DIR/mods"
cp -p "$STAGE/layouts/pixel-hq.json" "$STAGE/layouts/pixel-hq.svg" "$HOME_DIR/layouts/"
cp -p "$STAGE/themes/pixel-hq.json" "$HOME_DIR/themes/"
for mod in "${MODS[@]}"; do
  rsync -a --delete "${EXCLUDES[@]}" "$STAGE/mods/$mod/" "$HOME_DIR/mods/$mod/"
done
echo "install: ${#MODS[@]} mods, layout and theme -> $HOME_DIR ($PALETTE)"

# 4. Check every mod.
failed=0
for mod in "${MODS[@]}"; do
  if out="$(herdr-app check "$HOME_DIR/mods/$mod" 2>&1)" && ! grep -q -i -E '\berror\b' <<<"$out"; then
    echo "check:   ok    $mod"
  else
    echo "check:   FAIL  $mod"; sed 's/^/         /' <<<"$out"; failed=1
  fi
done
if [ "$failed" -ne 0 ]; then
  echo "install-local: a mod failed its check; restore with: cp -Rp \"$BACKUP\"/* \"$HOME_DIR\"/" >&2
  exit 1
fi
echo "done. If the window does not refresh, quit and reopen Herdr once."
