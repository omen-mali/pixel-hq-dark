#!/usr/bin/env python3
"""Tests for scripts/recolor.py: hex remapping, theme handling and --check.

Standalone (not in run-all.sh, to keep that upstream file untouched):
  python3 tests/test-recolor.test.py
"""

import importlib.util
import io
import json
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


if __name__ == "__main__":
    print("=== Testing scripts/recolor.py ===")
    for test in (test_text_mapping, test_no_chaining, test_identity_skipped_and_oled_refused,
                 test_files_and_theme, test_round_trip, test_check):
        test()
    print("All recolor tests passed.")
