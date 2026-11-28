#!/bin/bash
# Install this fork's Pixel HQ into the local Herdr config, in a chosen palette.
#
#   scripts/install-local.sh                   neutral (the repo's palette)
#   scripts/install-local.sh --palette oled    or: tinted, catppuccin
#
# Steps:
#   1. Back up the installed Pixel HQ files. The very first backup is kept for good as
#      ~/.config/herdr-app-backup-original/. Later ones go to 
#      ~/.config/herdr-app-backup-<timestamp>/.
#   2. Stage the repo's layout, theme and company-* mods in a temp folder and recolor
#      them there from neutral to the chosen palette (scripts/recolor.py), so Herdr
#      never sees a half-recolored file.
#   3. Mirror the staged files into the config folder. Each company-* mod folder is
#      synced with --delete so files removed upstream go away, while Herdr's generated
#      gpui-kit.d.ts / jsconfig.json and __pycache__ are kept and never copied.
#      Nothing else is touched: other layouts, themes and mods, pond-agents.json,
#      pixel-hq-names.json and settings stay as they are.
#   4. Run `herdr-app check` on every installed company-* mod and fail if one fails.
#   5. Only after a clean install: delete all but the newest $KEEP_BACKUPS timestamped backups.
#
# HERDR_APP_HOME picks another config folder, as it does for Herdr itself.
#
# Written for macOS's bash 3.2: no mapfile, and no `[ … ] && cmd` as a function's last
# line (it returns 1 when the test fails, which `set -e` turns into an exit).

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"
ORIGINAL="$HOME_DIR-backup-original"
KEEP_BACKUPS=3
PALETTE="neutral"
FILES=(layouts/pixel-hq.json layouts/pixel-hq.svg themes/pixel-hq.json)
EXCLUDES=(--exclude gpui-kit.d.ts --exclude jsconfig.json --exclude __pycache__ --exclude '*.pyc' --exclude .DS_Store)
BACKUP=""

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; }

# Print the timestamped backups, oldest first (the timestamp makes names sort by time).
list_backups() {
  ls -1d "$HOME_DIR"-backup-[0-9]* 2>/dev/null || true
}

# Copy the installed layout, theme and company-* mods into $1.
backup_to() {
  local dest="$1" f mod
  mkdir -p "$dest/layouts" "$dest/themes" "$dest/mods"
  for f in "${FILES[@]}"; do
    if [ -e "$HOME_DIR/$f" ]; then cp -p "$HOME_DIR/$f" "$dest/$f"; fi
  done
  # No trailing slash on the source: BSD cp would copy the folder's contents instead of the folder itself.
  for mod in "$HOME_DIR"/mods/company-*; do
    if [ -d "$mod" ]; then cp -Rp "$mod" "$dest/mods/"; fi
  done
}

# Back up the current install and set BACKUP to where it went.
# The first backup ever becomes $ORIGINAL, an older install's oldest timestamped backup is adopted as it.
take_backup() {
  local oldest
  if [ ! -d "$ORIGINAL" ]; then
    oldest="$(list_backups | head -n 1)"
    if [ -n "$oldest" ]; then
      mv "$oldest" "$ORIGINAL"
      echo "backup:  kept the oldest backup as $ORIGINAL"
    else
      backup_to "$ORIGINAL"
      BACKUP="$ORIGINAL"
      echo "backup:  $ORIGINAL (the first install, kept for good)"
      return 0
    fi
  fi
  BACKUP="$HOME_DIR-backup-$(date +%Y%m%d-%H%M%S)"
  backup_to "$BACKUP"
  echo "backup:  $BACKUP"
}

# Mirror the layout, theme and company-* mods found in $1 into the config folder.
mirror_into_home() {
  local src="$1" f mod
  mkdir -p "$HOME_DIR/layouts" "$HOME_DIR/themes" "$HOME_DIR/mods"
  for f in "${FILES[@]}"; do
    if [ -e "$src/$f" ]; then cp -p "$src/$f" "$HOME_DIR/$f"; fi
  done
  for mod in "$src"/mods/company-*; do
    if [ -d "$mod" ]; then rsync -a --delete "${EXCLUDES[@]}" "$mod/" "$HOME_DIR/mods/$(basename "$mod")/"; fi
  done
}

# Run `herdr-app check` on each installed mod that $1 provided. Returns 1 if any fails.
check_mods() {
  local src="$1" mod name out failed=0
  for mod in "$src"/mods/company-*; do
    if [ ! -d "$mod" ]; then continue; fi
    name="$(basename "$mod")"
    if out="$(herdr-app check "$HOME_DIR/mods/$name" 2>&1)" && ! grep -q -i -E '\berror\b' <<<"$out"; then
      echo "check:   ok    $name"
    else
      echo "check:   FAIL  $name"; sed 's/^/         /' <<<"$out"; failed=1
    fi
  done
  return "$failed"
}

# Delete all but the newest $KEEP_BACKUPS timestamped backups. Never touches $ORIGINAL.
prune_backups() {
  local total old
  total="$(list_backups | wc -l | tr -d ' ')"
  if [ "$total" -le "$KEEP_BACKUPS" ]; then return 0; fi
  list_backups | head -n "$((total - KEEP_BACKUPS))" | while IFS= read -r old; do
    rm -rf "$old"
    echo "prune:   $old"
  done
}

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

# 1. Back up what is currently installed.
take_backup

# 2. Stage and recolor.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/layouts" "$STAGE/themes" "$STAGE/mods"
cp -p "$REPO/layouts/pixel-hq.json" "$REPO/layouts/pixel-hq.svg" "$STAGE/layouts/"
cp -p "$REPO/themes/pixel-hq.json" "$STAGE/themes/"
for mod in "$REPO"/mods/company-*; do
  rsync -a "${EXCLUDES[@]}" "$mod/" "$STAGE/mods/$(basename "$mod")/"
done
if [ "$PALETTE" != "neutral" ]; then
  python3 "$REPO/scripts/recolor.py" --root "$STAGE" --from neutral --to "$PALETTE" | tail -1
fi

# 3. Put it in place.
mirror_into_home "$STAGE"
echo "install: $(ls -1d "$STAGE"/mods/company-* | wc -l | tr -d ' ') mods, layout and theme -> $HOME_DIR ($PALETTE)"

# 4. Check every mod.
if ! check_mods "$STAGE"; then
  echo "install-local: a mod failed its check; restore with: cp -Rp \"$BACKUP\"/* \"$HOME_DIR\"/" >&2
  exit 1
fi

# 5. Keep the original and the newest few backups.
prune_backups
echo "done. If the window does not refresh, quit and reopen Herdr once."
