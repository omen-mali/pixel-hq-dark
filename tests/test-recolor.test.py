#!/usr/bin/env python3
"""Tests for scripts/recolor.py: hex remapping, theme handling, color groups, --check and --inventory.

Standalone (not in run-all.sh, to keep that upstream file untouched):
  python3 tests/test-recolor.test.py
"""

import colorsys
import importlib.util
import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("recolor", REPO / "scripts" / "recolor.py")
recolor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recolor)

P = recolor.load_presets()
CAT, NEU, OLED = P["catppuccin"], P["neutral"], P["oled"]
THEME_TEXT = '{\n  "background": "#1e1e2e",\n  "foreground": "#cdd6f4",\n  "ansi": [\n    "#45475a",\n    "#1e1e2e"\n  ]\n}'


def make_root(td):
    """Build a tiny install-shaped tree: one company mod, an outside mod, a layout and a theme."""
    root = Path(td)
    (root / "mods/company-x/sub").mkdir(parents=True)
    (root / "mods/other").mkdir(parents=True)
    (root / "layouts").mkdir()
    (root / "themes").mkdir()
    (root / "mods/company-x/main.js").write_text('bg("#11111b"); bg("#11111BDD"); bg("#89b4fa"); bg("#181825");\n')
    (root / "mods/company-x/sub/icon.svg").write_text('<rect fill="#313244"/>')
    (root / "mods/company-x/notes.md").write_text("#11111b stays: not a target file")
    (root / "mods/other/main.js").write_text('bg("#11111b");')
    (root / "layouts/pixel-hq.json").write_text('{"colors": {"canvas": "#11111b", "raised": "#313244"}}')
    (root / "themes/pixel-hq.json").write_text(THEME_TEXT)
    return root


def run(argv):
    """Call recolor.main quietly and return (exit code, stdout)."""
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = recolor.main(argv)
    return code, out.getvalue()


def test_text_mapping():
    m = recolor.build_map(CAT, NEU)
    new, n = recolor.recolor_text('"#11111b" "#11111BDD" "#89b4fa" "#45475a"', m)
    assert new == '"#000000" "#000000DD" "#89b4fa" "#2c2c2c"', new
    assert n == 3
    print("PASS: alpha suffix kept, case ignored, other colors untouched")


def test_no_chaining():
    # A -> B and B -> C must not turn A into C in one pass.
    src = {"canvas": "#111111", "chrome": "#222222"}
    dst = {"canvas": "#222222", "chrome": "#333333"}
    new, _ = recolor.recolor_text("#111111 #222222", recolor.build_map(src, dst))
    assert new == "#222222 #333333", new
    print("PASS: one pass, no chained replacements")


def test_identity_skipped_and_oled_refused():
    m = recolor.build_map(NEU, OLED)
    assert "000000" not in m, "canvas is #000000 in both, so it should be skipped"
    try:
        recolor.build_map(OLED, NEU)
    except ValueError:
        pass
    else:
        raise AssertionError("oled repeats #000000 and must be refused as a source")
    code, _ = run(["--from", "oled", "--to", "neutral", "--root", tempfile.gettempdir()])
    assert code == 2
    print("PASS: identity slots skipped, repeating source refused")


def test_files_and_theme():
    with tempfile.TemporaryDirectory() as td:
        root = make_root(td)
        code, _ = run(["--from", "catppuccin", "--to", "neutral", "--root", td])
        assert code == 0
        js = (root / "mods/company-x/main.js").read_text()
        assert js == 'bg("#000000"); bg("#000000DD"); bg("#89b4fa"); bg("#0a0a0a");\n', js
        assert (root / "mods/company-x/sub/icon.svg").read_text() == '<rect fill="#1e1e1e"/>'
        assert "#11111b" in (root / "mods/company-x/notes.md").read_text(), "non-JS/SVG files are left alone"
        assert "#11111b" in (root / "mods/other/main.js").read_text(), "only company-* mods are touched"
        assert json.loads((root / "layouts/pixel-hq.json").read_text())["colors"] == {"canvas": "#000000", "raised": "#1e1e1e"}
        theme = (root / "themes/pixel-hq.json").read_text()
        assert theme == THEME_TEXT.replace('"background": "#1e1e2e"', '"background": "#0e0e0e"'), theme

        before = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
        code, out = run(["--from", "catppuccin", "--to", "neutral", "--root", td])
        assert code == 0 and "0 replacement(s)" in out, out
        assert before == {p: p.read_text() for p in root.rglob("*") if p.is_file()}, "rerun must be a no-op"
    print("PASS: target files recolored, theme background only, rerun is a no-op")


def test_round_trip():
    with tempfile.TemporaryDirectory() as td:
        root = make_root(td)
        original = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
        run(["--from", "catppuccin", "--to", "neutral", "--root", td])
        run(["--from", "neutral", "--to", "catppuccin", "--root", td])
        restored = {p: p.read_text() for p in root.rglob("*") if p.is_file()}
        # Case is normalised to the palette's spelling, so compare case-insensitively.
        assert {p: t.lower() for p, t in original.items()} == {p: t.lower() for p, t in restored.items()}
    print("PASS: catppuccin -> neutral -> catppuccin restores the files")


def test_check():
    with tempfile.TemporaryDirectory() as td:
        make_root(td)
        code, out = run(["--check", "--from", "catppuccin", "--root", td])
        assert code == 1 and "mods/company-x/main.js:1: #11111b" in out and "themes/pixel-hq.json" in out, out
        assert "mods/other" not in out and "notes.md" not in out, out
        run(["--from", "catppuccin", "--to", "neutral", "--root", td])
        code, out = run(["--check", "--from", "catppuccin", "--root", td])
        assert code == 0 and "0 catppuccin shade(s) left" in out, out
    print("PASS: --check lists leftovers and exits 1, then 0 once clean")


def palettes_with(td, factors=None, groups=None, overrides=None):
    """Write a copy of the real palettes.json into td with other scene factors, overrides or groups. Returns its path."""
    data = json.loads((REPO / "scripts/palettes.json").read_text())
    if groups is not None:
        data["groups"] = groups
    for name, per in (factors or {}).items():
        data["groups"]["scene"]["presets"][name] = per
    if overrides is not None:
        data["groups"]["scene"]["overrides"] = overrides
    path = Path(td) / "palettes.json"
    path.write_text(json.dumps(data))
    return str(path)


# The plan's starting factors. They collapse four near-identical upstream pairs, which the
# overrides split again (oled needs none: it can never be a source).
STRESS = {"neutral": {"saturation": 0.15, "lightness": 0.6}, "oled": {"saturation": 0.1, "lightness": 0.45},
          "tinted": {"saturation": 0.5, "lightness": 0.6}}
STRESS_OVERRIDES = {"neutral": {"#242843": "#1d1d20", "#2e3250": "#222225"},
                    "tinted": {"#0c0e1c": "#090a0e", "#12152c": "#0e0f16"}}


def test_transform():
    assert recolor.transform("2a2f52", 1, 1) == "2a2f52"
    out = recolor.transform("2a2f52", 0.5, 0.6)
    h0 = colorsys.rgb_to_hls(*(int("2a2f52"[i:i + 2], 16) / 255 for i in (0, 2, 4)))[0]
    h1, l1, _ = colorsys.rgb_to_hls(*(int(out[i:i + 2], 16) / 255 for i in (0, 2, 4)))
    assert abs(h0 - h1) < 0.02, (h0, h1)
    assert l1 < 0.25, l1
    assert recolor.transform("808080", 1, 5) == "ffffff", "lightness is clamped to 1"
    print("PASS: transform keeps hue, scales lightness, clamps, and is exact at 1/1")


def test_group_scope_and_clash():
    group = {"files": {"mods/company-x/main.js"}, "colors": ["2a2f52"],
             "presets": {p: (1, 1) for p in P}}
    group["presets"]["neutral"] = (0, 0.5)
    groups = {"g": group}
    with tempfile.TemporaryDirectory() as td:
        root = make_root(td)
        (root / "mods/company-x/main.js").write_text('bg("#2a2f52");\n')
        (root / "mods/company-x/sub/icon.svg").write_text('<rect fill="#2a2f52"/>')
        recolor.recolor(root, CAT, NEU, recolor.group_maps(groups, "catppuccin", "neutral"))
        assert "#2a2f52" not in (root / "mods/company-x/main.js").read_text(), "group file not recolored"
        assert "#2a2f52" in (root / "mods/company-x/sub/icon.svg").read_text(), "group touched a file it does not name"
    try:
        recolor.file_map("mods/company-x/main.js", {"11111b": "000000"}, [({"mods/company-x/main.js"}, {"11111b": "222222"})])
    except ValueError:
        pass
    else:
        raise AssertionError("a shade mapped by both a surface slot and a group must be refused")
    print("PASS: groups only touch their files, and double-mapped shades are refused")


def test_validate():
    groups = recolor.load_groups(palettes_with(tempfile.mkdtemp(), STRESS, overrides=STRESS_OVERRIDES))
    assert recolor.validate(P, groups) == [], recolor.validate(P, groups)
    # Two colors that collapse to one shade under neutral make neutral ambiguous as a source.
    bad = {"g": {"files": {"x"}, "colors": ["101010", "101011"], "presets": {p: (1, 1) for p in P}}}
    bad["g"]["presets"]["neutral"] = (0, 1)
    assert any("one shade" in p for p in recolor.validate(P, bad))
    # A group shade equal to a surface shade is ambiguous too.
    clash = {"g": {"files": {"x"}, "colors": ["0a0a0a"], "presets": {p: (1, 1) for p in P}}}
    assert any("surface" in p for p in recolor.validate(P, clash))
    with tempfile.TemporaryDirectory() as td:
        path = palettes_with(td, groups={"scene": {"files": ["x"], "colors": {"a": ["#0a0a0a"]},
                                                  "presets": {p: {"saturation": 1, "lightness": 1} for p in P}}})
        code, _ = run(["--palettes", path, "--from", "catppuccin", "--to", "neutral", "--root", td])
        assert code == 2, "main must refuse an ambiguous palette file"
    print("PASS: validate catches collapsing and surface-clashing group shades; main exits 2")


def copy_repo(td):
    """Copy the repo's mods, layouts and themes into td and return it as a Path."""
    root = Path(td)
    for part in ("mods", "layouts", "themes"):
        shutil.copytree(REPO / part, root / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return root


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_text().lower() for p in root.rglob("*")
            if p.suffix in (".js", ".svg", ".json") and p.is_file()}


def test_round_trips_on_real_mods():
    with tempfile.TemporaryDirectory() as td:
        pal = palettes_with(td, STRESS, overrides=STRESS_OVERRIDES)
        root = copy_repo(Path(td) / "repo")
        # The repo holds neutral; take the copy back to upstream's colors with the real palettes
        # (which also checks the real neutral is a usable source), then apply the stress neutral.
        code, _ = run(["--from", "neutral", "--to", "catppuccin", "--root", str(root)])
        assert code == 0
        start = snapshot(root)
        run(["--palettes", pal, "--from", "catppuccin", "--to", "neutral", "--root", str(root)])
        neutral = snapshot(root)
        assert neutral != start, "the stress factors should change the scene"
        for other in ("tinted", "catppuccin"):
            run(["--palettes", pal, "--from", "neutral", "--to", other, "--root", str(root)])
            assert snapshot(root) != neutral, f"neutral -> {other} changed nothing"
            run(["--palettes", pal, "--from", other, "--to", "neutral", "--root", str(root)])
            after = snapshot(root)
            diff = [(f, n) for f in neutral for n, (a, b) in
                    enumerate(zip(neutral[f].splitlines(), after[f].splitlines()), 1) if a != b]
            # Even the two upstream alpha-black overlays, which share neutral's canvas, come back.
            assert diff == [], diff
    print("PASS: neutral -> tinted -> neutral and neutral -> catppuccin -> neutral are lossless on the real mods")


def test_inventory_and_check_with_groups():
    with tempfile.TemporaryDirectory() as td:
        pal = palettes_with(td, STRESS, overrides=STRESS_OVERRIDES)
        root = copy_repo(Path(td) / "repo")
        run(["--from", "neutral", "--to", "catppuccin", "--root", str(root)])  # back to upstream's colors
        code, out = run(["--palettes", pal, "--inventory", "--root", str(root)])
        assert code == 0 and "#262a42" not in out and "#4a5b80" in out, "group colors covered, pet colors listed"
        code, out = run(["--palettes", pal, "--check", "--from", "catppuccin", "--root", str(root)])
        assert code == 1 and "scene.js" in out, "scene colors are leftovers until the recolor runs"
        run(["--palettes", pal, "--from", "catppuccin", "--to", "neutral", "--root", str(root)])
        code, out = run(["--palettes", pal, "--check", "--from", "catppuccin", "--root", str(root)])
        assert code == 0, out
    print("PASS: --inventory skips group colors, --check reports group leftovers until recolored")


if __name__ == "__main__":
    print("=== Testing scripts/recolor.py ===")
    for test in (test_text_mapping, test_no_chaining, test_identity_skipped_and_oled_refused,
                 test_files_and_theme, test_round_trip, test_check, test_transform, test_group_scope_and_clash,
                 test_validate, test_round_trips_on_real_mods, test_inventory_and_check_with_groups):
        test()
    print("All recolor tests passed.")
