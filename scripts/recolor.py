#!/usr/bin/env python3
"""Recolor Pixel HQ's surface shades and color groups from one palette preset to another.

Upstream hardcodes its Catppuccin surface shades (canvas, chrome, terminal
background, surface, raised, border) in the mods, the layout and the theme.
This script swaps them for the shades of another preset in scripts/palettes.json,
so the fork's palette can be regenerated after every upstream merge instead of
being edited by hand.

Color groups (palettes.json "groups") cover art with too many shades for one slot
each, such as the office scene. A group lists upstream's colors and, per preset, a
saturation and lightness factor. The preset's shade of a color is that color with
its HLS saturation and lightness scaled (hue kept). A group only applies to the
files it names.

Usage:
  recolor.py --from catppuccin --to neutral          recolor the repo
  recolor.py --from neutral --to oled --root DIR     recolor an installed copy
  recolor.py --check --from catppuccin               list leftover source shades
  recolor.py --inventory                             list dark blue-gray colors no group covers

What it touches under --root:
  mods/company-*/**/*.js and *.svg   every matching hex, in one regex pass
  layouts/pixel-hq.json              every matching hex
  themes/pixel-hq.json               only "background"; the ANSI colors stay

A match keeps its 2-digit alpha suffix (#11111bdd -> #000000dd). The pass never
chains (a value that was just written is not matched again), and rerunning is a
no-op. A preset whose shades repeat (oled) can be a target but not a source,
because the original slot of each shade is lost. The same goes for a group whose
transform maps two colors to one shade.

Known caveat: two alpha-black overlays already exist upstream (#00000033 in
company-agents/main.js, #00000038 in company-spaces/main.js) and share neutral's
canvas base. Mapping neutral to a preset whose canvas is not #000000 (tinted)
shifts them too, which is not visible.
"""

import argparse
import colorsys
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
# What --inventory counts as a dark blue-gray: HLS hue, minimum saturation, maximum lightness.
NAVY_HUE, NAVY_MIN_SAT, NAVY_MAX_LIGHT = (0.55, 0.75), 0.12, 0.45


def load_presets(path=PALETTES):
    """Return {preset name: {slot: "#rrggbb"}} from palettes.json, lowercased."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {name: {slot: color.lower() for slot, color in shades.items()}
            for name, shades in data["presets"].items()}


def load_groups(path=PALETTES):
    """Return {group: {"files", "colors", "presets"}} from palettes.json's "groups".

    "files" is a set of POSIX paths relative to the root, "colors" a list of 6-digit
    lowercase hex without '#', in file order, "presets" maps each preset name to
    (saturation factor, lightness factor), and "overrides" maps a preset name to
    {color: shade} for colors whose transformed shade would collide with another.
    Raises ValueError when a group does not define exactly the surface presets, lists
    a color twice, or overrides a color it does not list.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    names = set(data["presets"])
    groups = {}
    for name, g in data.get("groups", {}).items():
        colors = [c.lower().lstrip("#") for role in g["colors"].values() for c in role]
        if len(set(colors)) != len(colors):
            raise ValueError(f"group {name!r} lists a color twice")
        if set(g["presets"]) != names:
            raise ValueError(f"group {name!r} must define exactly the presets {sorted(names)}")
        overrides = {p: {k.lower().lstrip("#"): v.lower().lstrip("#") for k, v in per.items()}
                     for p, per in g.get("overrides", {}).items()}
        for p, per in overrides.items():
            if p not in names or not set(per) <= set(colors):
                raise ValueError(f"group {name!r} overrides an unknown preset or a color it does not list")
        groups[name] = {
            "files": set(g["files"]),
            "colors": colors,
            "presets": {p: (float(v["saturation"]), float(v["lightness"])) for p, v in g["presets"].items()},
            "overrides": overrides,
        }
    return groups


def transform(color, saturation, lightness):
    """Scale a 6-digit hex color's HLS saturation and lightness (clamped to 1), keeping its hue."""
    if saturation == 1 and lightness == 1:
        return color
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, min(1.0, l * lightness), min(1.0, s * saturation))
    return "".join(f"{round(v * 255):02x}" for v in (r, g, b))


def group_shades(group, preset):
    """Return the preset's shade of each group color, in the group's order (overrides win)."""
    s, l = group["presets"][preset]
    fixed = group.get("overrides", {}).get(preset, {})
    return [fixed.get(c) or transform(c, s, l) for c in group["colors"]]


def group_map(group, src, dst):
    """Map each group color's src shade to its dst shade, leaving out equal pairs.

    Raises ValueError when two colors share a src shade, since the reverse is ambiguous.
    """
    before, after = group_shades(group, src), group_shades(group, dst)
    if len(set(before)) != len(before):
        raise ValueError(f"its transform maps two colors to one shade, so it cannot be mapped from")
    return {b: a for b, a in zip(before, after) if b != a}


def is_source(presets, name):
    """Tell whether a preset can be mapped from: its surface shades are all different."""
    values = list(presets[name].values())
    return len(set(values)) == len(values)


def validate(presets, groups):
    """List problems that would make recoloring from a preset ambiguous; empty when all is well.

    Only presets that can be a source are checked: their group shades must be distinct
    within a group, and no shade may be claimed by two groups or by a group and a surface slot.
    """
    problems = []
    for p in presets:
        if not is_source(presets, p):
            continue
        claimed = {v[1:]: "surface" for v in presets[p].values()}
        for name, group in groups.items():
            shades = group_shades(group, p)
            seen = {}
            for color, shade in zip(group["colors"], shades):
                if shade in seen:
                    problems.append(f"{p}: group {name!r} maps #{seen[shade]} and #{color} to one shade "
                                    f"#{shade}; add an override for one of them")
                seen.setdefault(shade, color)
            for shade in set(shades):
                if shade in claimed:
                    problems.append(f"{p}: #{shade} is used by group {name!r} and by {claimed[shade]}")
                claimed.setdefault(shade, f"group {name!r}")
    return problems


def group_maps(groups, src, dst):
    """Return [(files, mapping)] for every group, from preset src to preset dst."""
    out = []
    for name, group in groups.items():
        try:
            out.append((group["files"], group_map(group, src, dst)))
        except ValueError as err:
            raise ValueError(f"group {name!r}: {err}") from None
    return out


def changing_shades(group, preset):
    """Return the preset's shades of the group colors that some other preset gives a different shade."""
    mine = group_shades(group, preset)
    others = [group_shades(group, p) for p in group["presets"] if p != preset]
    return {m for i, m in enumerate(mine) if any(o[i] != m for o in others)}


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


def file_map(rel, surface, extra):
    """Combine the surface mapping with every (files, mapping) in extra whose files include rel.

    Raises ValueError when two mappings claim the same source shade in one file.
    """
    mapping = dict(surface)
    for files, more in extra:
        if rel not in files:
            continue
        clash = set(mapping) & set(more)
        if clash:
            raise ValueError(f"{rel}: #{sorted(clash)[0]} is mapped twice")
        mapping.update(more)
    return mapping


def recolor(root, src, dst, extra=()):
    """Recolor every target file under root. Returns {relative path: replacements}.

    extra is a list of (files, mapping) from group_maps(); each applies only to its files.
    """
    root = Path(root)
    surface = build_map(src, dst)
    changed = {}
    for path in hex_files(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        new, n = recolor_text(text, file_map(rel, surface, extra))
        if n:
            path.write_text(new, encoding="utf-8")
            changed[rel] = n
    if recolor_theme(root / THEME, src, dst):
        changed[str(THEME)] = 1
    return changed


def leftovers(root, src, extra=()):
    """List (relative path, line number, hex) for every src shade still present.

    extra is a list of (files, shades) to look for only in those files.
    """
    root = Path(root)
    surface = {color[1:] for color in src.values()}
    found = []
    for path in hex_files(root):
        rel = path.relative_to(root).as_posix()
        wanted = surface.union(*(shades for files, shades in extra if rel in files))
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in HEX.finditer(line):
                if m.group(1).lower() in wanted:
                    found.append((rel, no, m.group(0)))
    theme = root / THEME
    if theme.is_file() and json.loads(theme.read_text(encoding="utf-8")).get("background", "").lower() == src["background"]:
        found.append((str(THEME), 0, src["background"]))
    return found


def is_navy(color):
    """Tell whether a 6-digit hex color is the dark blue-gray --inventory looks for."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return NAVY_HUE[0] <= h <= NAVY_HUE[1] and s >= NAVY_MIN_SAT and l <= NAVY_MAX_LIGHT


def inventory(root, presets, groups):
    """Return {hex: [(relative path, line)]} for dark blue-gray colors that no slot or group covers.

    A color counts as covered when it is any preset's shade of a surface slot or a group color.
    """
    root = Path(root)
    covered = {v[1:] for shades in presets.values() for v in shades.values()}
    for group in groups.values():
        for p in group["presets"]:
            covered.update(group_shades(group, p))
    found = {}
    for path in hex_files(root):
        rel = path.relative_to(root).as_posix()
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in HEX.finditer(line):
                color = m.group(1).lower()
                if color not in covered and is_navy(color):
                    found.setdefault(color, []).append((rel, no))
    return found


def main(argv=None):
    """Parse arguments, run a recolor, a check or an inventory, and return the exit code."""
    parser = argparse.ArgumentParser(description="Recolor Pixel HQ's surface shades between palette presets.")
    parser.add_argument("--from", dest="src", help="preset the files use now")
    parser.add_argument("--to", dest="dst", help="preset to switch to")
    parser.add_argument("--root", default=str(REPO), help="folder holding mods/, layouts/ and themes/ (default: this repo)")
    parser.add_argument("--check", action="store_true", help="list leftover --from shades and exit 1 if any")
    parser.add_argument("--inventory", action="store_true", help="list dark blue-gray colors no slot or group covers")
    parser.add_argument("--palettes", default=str(PALETTES), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    presets = load_presets(args.palettes)
    try:
        groups = load_groups(args.palettes)
    except ValueError as err:
        print(f"recolor: palettes: {err}", file=sys.stderr)
        return 2
    problems = validate(presets, groups)
    if problems:
        for problem in problems:
            print(f"recolor: palettes: {problem}", file=sys.stderr)
        return 2

    if args.inventory:
        found = inventory(args.root, presets, groups)
        for color, where in sorted(found.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            print(f"#{color}  {len(where):3d}  " + ", ".join(f"{p}:{n}" for p, n in where))
        print(f"{len(found)} uncovered dark blue-gray color(s)")
        return 0

    if args.src is None:
        parser.error("--from is required unless --inventory is given")
    for name in (args.src, args.dst):
        if name is not None and name not in presets:
            parser.error(f"unknown preset {name!r}; choose from {', '.join(presets)}")

    if args.check:
        extra = [(g["files"], changing_shades(g, args.src)) for g in groups.values()]
        found = leftovers(args.root, presets[args.src], extra)
        for path, no, color in found:
            print(f"{path}:{no}: {color}")
        print(f"{len(found)} {args.src} shade(s) left")
        return 1 if found else 0

    if args.dst is None:
        parser.error("--to is required unless --check is given")
    try:
        changed = recolor(args.root, presets[args.src], presets[args.dst], group_maps(groups, args.src, args.dst))
    except ValueError as err:
        print(f"recolor: {args.src}: {err}", file=sys.stderr)
        return 2
    for path, n in changed.items():
        print(f"{n:5d}  {path}")
    print(f"{sum(changed.values())} replacement(s) in {len(changed)} file(s): {args.src} -> {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
