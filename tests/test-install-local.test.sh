#!/bin/bash
# Tests for scripts/install-local.sh: backups, pruning, --no-backup, --restore and argument errors.
#
# Everything runs in a temp folder with HERDR_APP_HOME pointing into it and a fake `herdr-app`
# first on PATH (prints "ok", or fails while FAKE_CHECK_FAIL is set), so the real Herdr config
# is never touched. Standalone (not in run-all.sh, to keep that upstream file untouched):
#   bash tests/test-install-local.test.sh

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL="$REPO/scripts/install-local.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

mkdir -p "$T/bin"
cat > "$T/bin/herdr-app" <<'EOF'
#!/bin/sh
if [ -n "${FAKE_CHECK_FAIL:-}" ]; then echo "error: fake check failure"; exit 1; fi
echo ok
EOF
chmod +x "$T/bin/herdr-app"
export PATH="$T/bin:$PATH"
export HERDR_APP_HOME="$T/home"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }
count_backups() { ls -1d "$T"/home-backup-[0-9]* 2>/dev/null | wc -l | tr -d ' '; }

# A pretend upstream install: one company mod with a marker file, an unrelated mod, a theme.
seed_home() {
  rm -rf "$T"/home "$T"/home-backup-*
  mkdir -p "$T/home/mods/company-agents" "$T/home/mods/other" "$T/home/themes" "$T/home/layouts"
  echo "upstream" > "$T/home/mods/company-agents/marker.js"
  echo "mine" > "$T/home/mods/other/main.js"
  printf '{\n  "background": "#1e1e2e"\n}' > "$T/home/themes/pixel-hq.json"
  echo '{}' > "$T/home/layouts/pixel-hq.json"
}

echo "=== Testing scripts/install-local.sh ==="

# 1. The first install keeps the original and makes no timestamped backup.
seed_home
"$INSTALL" >/dev/null
[ -f "$T/home-backup-original/mods/company-agents/marker.js" ] || fail "first install did not back up into -original"
[ "$(count_backups)" = 0 ] || fail "first install also made a timestamped backup"
[ ! -e "$T/home/mods/company-agents/marker.js" ] || fail "install did not mirror company-agents with --delete"
[ "$(cat "$T/home/mods/other/main.js")" = mine ] || fail "install touched a mod that is not company-*"
pass "first install keeps the original, mirrors company-* mods, leaves other mods alone"

# 2. Repeated installs keep the original plus the newest 3.
for _ in 1 2 3 4 5; do "$INSTALL" >/dev/null; done
[ "$(count_backups)" = 3 ] || fail "expected 3 timestamped backups, got $(count_backups)"
[ -d "$T/home-backup-original" ] || fail "pruning removed the original"
pass "five more installs leave the original plus 3 timestamped backups"

# 3. --no-backup adds none.
before="$(ls -1d "$T"/home-backup-[0-9]*)"
"$INSTALL" --no-backup >/dev/null
[ "$before" = "$(ls -1d "$T"/home-backup-[0-9]*)" ] || fail "--no-backup changed the backups"
pass "--no-backup makes no backup and prunes nothing"

# 4. --restore original puts the seeded install back.
"$INSTALL" --restore original >/dev/null
diff -r -x gpui-kit.d.ts -x jsconfig.json "$T/home-backup-original/mods/company-agents" "$T/home/mods/company-agents" >/dev/null \
  || fail "--restore original did not reproduce company-agents"
diff "$T/home-backup-original/themes/pixel-hq.json" "$T/home/themes/pixel-hq.json" >/dev/null \
  || fail "--restore original did not restore the theme"
[ -d "$T/home/mods/company-brand" ] || fail "--restore deleted a mod the backup does not have"
pass "--restore original reproduces the original, keeps mods the backup lacks"

# 5. --restore with no name puts back the newest backup (the install before the restore).
"$INSTALL" --restore >/dev/null
[ ! -e "$T/home/mods/company-agents/marker.js" ] || fail "--restore did not return to the pre-restore install"
pass "--restore returns to the newest backup"

# 6. An adopted original: with no -original, the oldest timestamped backup becomes it.
seed_home
mkdir -p "$T/home-backup-20000101-000000/mods/company-agents"
echo "oldest" > "$T/home-backup-20000101-000000/mods/company-agents/marker.js"
mkdir -p "$T/home-backup-20000102-000000/mods"
"$INSTALL" >/dev/null
[ "$(cat "$T/home-backup-original/mods/company-agents/marker.js")" = oldest ] || fail "oldest backup was not adopted as -original"
pass "an older install's oldest backup is adopted as the original"

# 7. A failing check exits 1 and prunes nothing.
for _ in 1 2 3; do "$INSTALL" --no-backup >/dev/null; done
mkdir -p "$T"/home-backup-2000010{3,4,5}-000000/mods
before="$(count_backups)"
if FAKE_CHECK_FAIL=1 "$INSTALL" >/dev/null 2>&1; then fail "a failing check did not fail the install"; fi
[ "$(count_backups)" = "$((before + 1))" ] || fail "a failed install pruned backups"
pass "a failing check exits 1 and prunes nothing"

# 8. Argument errors exit 2.
code() { set +e; "$INSTALL" "$@" >/dev/null 2>&1; echo $?; set -e; }
[ "$(code --palette nope)" = 2 ] || fail "--palette nope did not exit 2"
[ "$(code --restore --palette oled)" = 2 ] || fail "--restore with --palette did not exit 2"
[ "$(code --restore 19990101-000000)" = 2 ] || fail "--restore of a missing backup did not exit 2"
[ "$(code --bogus)" = 2 ] || fail "an unknown argument did not exit 2"
pass "bad palette, --restore with --palette, missing backup and unknown flag exit 2"

# 9. --palette oled recolors the installed copy only.
"$INSTALL" --palette oled >/dev/null
grep -q '"background": "#000000"' "$T/home/themes/pixel-hq.json" || fail "--palette oled did not set the theme background"
grep -q '"background": "#0e0e0e"' "$REPO/themes/pixel-hq.json" || fail "--palette oled changed the repo's theme"
pass "--palette oled recolors the install, not the repo"

echo "All install-local tests passed."
