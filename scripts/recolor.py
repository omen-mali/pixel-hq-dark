#!/usr/bin/env python3
"""Recolor Pixel HQ's six surface shades from one palette preset to another.

Upstream hardcodes its Catppuccin surface shades (canvas, chrome, terminal
background, surface, raised, border) in the mods, the layout and the theme.
This script swaps them for the shades of another preset in scripts/palettes.json,
so the fork's palette can be regenerated after every upstream merge instead of
being edited by hand.

Usage:
  recolor.py --from catppuccin --to neutral          recolor the repo
  recolor.py --from neutral --to oled --root DIR     recolor an installed copy
  recolor.py --check --from catppuccin               list leftover source shades

What it touches under --root:
  mods/company-*/**/*.js and *.svg   every matching hex, in one regex pass
  layouts/pixel-hq.json              every matching hex
  themes/pixel-hq.json               only "background"; the ANSI colors stay

A match keeps its 2-digit alpha suffix (#11111bdd -> #000000dd). The pass never
chains (a value that was just written is not matched again), and rerunning is a
no-op. A preset whose shades repeat (oled) can be a target but not a source,
because the original slot of each shade is lost.

Known caveat: two alpha-black overlays already exist upstream (#00000033 in
company-agents/main.js, #00000038 in company-spaces/main.js) and share neutral's
canvas base. Mapping neutral to a preset whose canvas is not #000000 (tinted)
shifts them too, which is not visible.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PALETTES = HERE / "palettes.json"
HEX = re.compile(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?\b")
THEME = Path("themes/pixel-hq.json")
LAYOUT = Path("layouts/pixel-hq.json")


def load_presets(path=PALETTES):
    """Return {preset name: {slot: "#rrggbb"}} from palettes.json, lowercased."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {name: {slot: color.lower() for slot, color in shades.items()}
            for name, shades in data["presets"].items()}


def build_map(src, dst):
    """Map each source shade (6 lowercase hex digits, no '#') to its target shade.

    Raises ValueError when the source repeats a shade, since the reverse slot
    would be ambiguous. Slots that are already equal are left out.
    """
    values = list(src.values())
    if len(set(values)) != len(values):
        raise ValueError("source palette repeats a shade, so it cannot be mapped from")
    return {src[slot][1:]: dst[slot][1:] for slot in src if src[slot] != dst[slot]}


def recolor_text(text, mapping):
    """Return (new text, number of replacements) for one file's contents."""
    count = 0

    def swap(m):
        nonlocal count
        target = mapping.get(m.group(1).lower())
        if target is None:
            return m.group(0)
        count += 1
        return "#" + target + (m.group(2) or "")

    return HEX.sub(swap, text), count


def hex_files(root):
    """List the files whose every hex is remapped: company mods' JS and SVG, and the layout."""
    root = Path(root)
    files = [p for mod in sorted(root.glob("mods/company-*")) if mod.is_dir()
             for p in sorted(mod.rglob("*")) if p.suffix in (".js", ".svg") and p.is_file()]
    if (root / LAYOUT).is_file():
        files.append(root / LAYOUT)
    return files


def recolor_theme(path, src, dst):
    """Set the theme's "background" to dst's when it is src's. Returns True if changed.

    Edits the text in place rather than re-dumping JSON, so the file's formatting
    (and the ANSI list) stays byte-identical apart from that one value.
    """
    path = Path(path)
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    current = json.loads(text).get("background", "")
    if current.lower() != src["background"] or src["background"] == dst["background"]:
        return False
    pattern = re.compile(r'("background"\s*:\s*")' + re.escape(current) + '"')
    new, n = pattern.subn(lambda m: m.group(1) + dst["background"] + '"', text, count=1)
    if n:
        path.write_text(new, encoding="utf-8")
    return bool(n)


def recolor(root, src, dst):
    """Recolor every target file under root. Returns {relative path: replacements}."""
    root = Path(root)
    mapping = build_map(src, dst)
    changed = {}
    for path in hex_files(root):
        text = path.read_text(encoding="utf-8")
        new, n = recolor_text(text, mapping)
        if n:
            path.write_text(new, encoding="utf-8")
            changed[str(path.relative_to(root))] = n
    if recolor_theme(root / THEME, src, dst):
        changed[str(THEME)] = 1
    return changed


def leftovers(root, src):
    """List (relative path, line number, hex) for every src shade still present."""
    root = Path(root)
    wanted = {color[1:] for color in src.values()}
    found = []
    for path in hex_files(root):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in HEX.finditer(line):
                if m.group(1).lower() in wanted:
                    found.append((str(path.relative_to(root)), no, m.group(0)))
    theme = root / THEME
    if theme.is_file() and json.loads(theme.read_text(encoding="utf-8")).get("background", "").lower() == src["background"]:
        found.append((str(THEME), 0, src["background"]))
    return found


def main(argv=None):
    """Parse arguments, run a recolor or a check, and return the exit code."""
    parser = argparse.ArgumentParser(description="Recolor Pixel HQ's surface shades between palette presets.")
    parser.add_argument("--from", dest="src", required=True, help="preset the files use now")
    parser.add_argument("--to", dest="dst", help="preset to switch to")
    parser.add_argument("--root", default=str(REPO), help="folder holding mods/, layouts/ and themes/ (default: this repo)")
    parser.add_argument("--check", action="store_true", help="list leftover --from shades and exit 1 if any")
    parser.add_argument("--palettes", default=str(PALETTES), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    presets = load_presets(args.palettes)
    for name in (args.src, args.dst):
        if name is not None and name not in presets:
            parser.error(f"unknown preset {name!r}; choose from {', '.join(presets)}")

    if args.check:
        found = leftovers(args.root, presets[args.src])
        for path, no, color in found:
            print(f"{path}:{no}: {color}")
        print(f"{len(found)} {args.src} shade(s) left")
        return 1 if found else 0

    if args.dst is None:
        parser.error("--to is required unless --check is given")
    try:
        changed = recolor(args.root, presets[args.src], presets[args.dst])
    except ValueError as err:
        print(f"recolor: {args.src}: {err}", file=sys.stderr)
        return 2
    for path, n in changed.items():
        print(f"{n:5d}  {path}")
    print(f"{sum(changed.values())} replacement(s) in {len(changed)} file(s): {args.src} -> {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
