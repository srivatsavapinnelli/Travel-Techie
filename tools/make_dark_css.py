"""
Generates static/dark-auto.css from the page's own <style> block in static/index.html.

Why generate it? The page has ~90 rules with hard-coded light colours (white cards, slate text,
pale tints). Rewriting each by hand is slow and easy to miss; this script maps every colour in
those rules to a dark-theme equivalent and writes the result under `html[data-theme="dark"]`.
Hand-tuned exceptions live in static/theme.css (loaded after this file).

Run from the project folder (needs:  pip install tinycss2):
    python tools/make_dark_css.py

How colours are mapped (HLS = hue, lightness, saturation):
  backgrounds   light colours (L >= .5, or pale tints) -> dark surfaces (L .13 .. .36); darker or
                saturated brand colours are left alone
  text          DARK text -> light text, muted slate -> lighter slate; light text (white on buttons,
                white on dark panels) is left alone so it keeps working on coloured backgrounds
  borders       light greys -> subtle lighter-than-card lines
  shadows       white highlights are almost removed; black shadows stay
"""
from __future__ import annotations

import colorsys
import os
import re
import sys

import tinycss2

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "static", "index.html")
OUT = os.path.join(ROOT, "static", "dark-auto.css")
PREFIX = 'html[data-theme="dark"]'

COLOR_RE = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|rgba?\([^)]*\)", re.I)


# ---------------------------------------------------------------------------
# colour helpers
# ---------------------------------------------------------------------------
def parse_color(text: str):
    t = text.strip().lower()
    if t.startswith("#"):
        h = t[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return r, g, b, a
    nums = re.findall(r"[-+]?\d*\.?\d+%?", t[t.index("(") + 1:t.rindex(")")])
    vals = []
    for n in nums[:4]:
        vals.append(float(n[:-1]) / 100 if n.endswith("%") else float(n))
    r, g, b = (int(round(v)) for v in vals[:3])
    a = vals[3] if len(vals) > 3 else 1.0
    return r, g, b, a


def fmt(r, g, b, a):
    r, g, b = (max(0, min(255, int(round(v)))) for v in (r, g, b))
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"


def is_neutral(h, l, s):
    """Greys and slate blues (the page's text and surface colours) count as neutral."""
    return s < 0.15 or (s < 0.5 and 195 <= h * 360 <= 250)


SLATE_HUE = 215 / 360   # greys (white, #f5f5f5 ...) become slate blue so the dark theme isn't flat grey


def with_l(r, g, b, new_l, max_s=None, slate=False):
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if max_s is not None:
        s = min(s, max_s)
    if slate and s < 0.15:
        h, s = SLATE_HUE, 0.28
    r2, g2, b2 = colorsys.hls_to_rgb(h, max(0, min(1, new_l)), s)
    return r2 * 255, g2 * 255, b2 * 255


def map_color(literal: str, mode: str) -> str:
    r, g, b, a = parse_color(literal)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    neutral = is_neutral(h, l, s)

    if mode == "bg":
        if neutral and l >= 0.5:
            return fmt(*with_l(r, g, b, 0.13 + (1 - l) * 0.45, slate=True), a)
        if not neutral and l > 0.65:                       # pale tint (green-100, red-100, ...)
            return fmt(*with_l(r, g, b, 0.13 + (1 - l) * 0.45, max_s=0.5), a)
        return literal                                     # already dark, or a brand colour
    if mode == "border":
        if (neutral and l >= 0.5) or (not neutral and l > 0.65):
            return fmt(*with_l(r, g, b, 0.22 + (1 - l) * 0.3, max_s=0.5, slate=True), a)
        return literal
    if mode == "text":
        if neutral:
            if l < 0.45:
                return fmt(*with_l(r, g, b, max(1 - l, 0.78), slate=True), a)   # dark text -> light
            if l < 0.6:
                return fmt(*with_l(r, g, b, 0.68), a)               # muted slate -> lighter slate
            return literal                                          # already light (on a dark panel)
        if l < 0.35:                                                # dark coloured text (dark green, dark red ...)
            return fmt(*with_l(r, g, b, max(1 - l, 0.72), max_s=0.7), a)
        return literal
    if mode == "shadow":
        if l > 0.9:                                                # white highlight (neumorphic) -> nearly none
            return fmt(r, g, b, a * 0.06)
        return literal
    return literal


def property_mode(name: str):
    n = name.lower()
    if n in ("box-shadow", "text-shadow", "filter"):
        return "shadow"
    if n.startswith("border") or n.startswith("outline"):
        return "border"
    if n in ("color", "-webkit-text-fill-color", "caret-color", "fill", "stroke", "text-decoration-color"):
        return "text"
    if n.startswith("background"):
        return "bg"
    return None


def transform_value(name: str, value: str) -> str:
    mode = property_mode(name)
    if not mode:
        return value
    out = COLOR_RE.sub(lambda m: map_color(m.group(0), mode), value)
    # variables whose meaning depends on where they are used
    def var(name):   # matches var(--name) and var(--name, fallback)
        return re.compile(r"var\(\s*--%s\s*(?:,[^)]*)?\)" % name)
    if mode == "bg":
        out = var("navy").sub("#1e293b", out)               # navy panels (toast, board, footer) become dark slate
    if mode == "text":
        out = var("teal-dark").sub("#5eead4", out)
        out = var("coral-dark").sub("#fb923c", out)
    return out


# ---------------------------------------------------------------------------
# stylesheet walk
# ---------------------------------------------------------------------------
def split_selectors(prelude: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in prelude:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def prefix_selector(sel: str) -> str | None:
    if sel.startswith(":root") or sel == "html":
        return None
    if sel.startswith("html ") or sel.startswith("body") or sel == "*":
        return f"{PREFIX} {sel}" if not sel.startswith("body") else f"{PREFIX} {sel}"
    return f"{PREFIX} {sel}"


def rule_block(rule) -> str | None:
    prelude = tinycss2.serialize(rule.prelude).strip()
    decls = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
    lines = []
    for d in decls:
        if d.type != "declaration":
            continue
        value = tinycss2.serialize(d.value).strip()
        new = transform_value(d.name, value)
        if new != value:
            lines.append(f"  {d.name}: {new}{' !important' if d.important else ''};")
    if not lines:
        return None
    selectors = [p for p in (prefix_selector(s) for s in split_selectors(prelude)) if p]
    if not selectors:
        return None
    return ",\n".join(selectors) + " {\n" + "\n".join(lines) + "\n}\n"


def walk(rules) -> list[str]:
    out = []
    for r in rules:
        if r.type == "qualified-rule":
            block = rule_block(r)
            if block:
                out.append(block)
        elif r.type == "at-rule" and r.lower_at_keyword in ("media", "supports") and r.content:
            inner = walk(tinycss2.parse_rule_list(r.content, skip_comments=True, skip_whitespace=True))
            if inner:
                out.append(f"@{r.at_keyword} {tinycss2.serialize(r.prelude).strip()} {{\n" + "\n".join(inner) + "}\n")
    return out


EXTRA_SHEETS = ["features.css", "account.css"]   # our own stylesheets get the same treatment


def main() -> int:
    html = open(SRC, encoding="utf-8").read()
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    if not m:
        print("No <style> block found in", SRC)
        return 1
    sources = [("index.html <style>", m.group(1))]
    for name in EXTRA_SHEETS:
        path = os.path.join(ROOT, "static", name)
        if os.path.exists(path):
            sources.append((name, open(path, encoding="utf-8").read()))
    blocks = []
    for label, text in sources:
        found = walk(tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True))
        print(f"  {label}: {len(found)} dark blocks")
        blocks += [f"/* from {label} */\n"] + found
    header = ("/* GENERATED by tools/make_dark_css.py from the page's own CSS. Do not edit by hand:\n"
              "   put hand-tuned exceptions in theme.css instead. */\n")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(blocks))
    print(f"wrote {OUT}: {os.path.getsize(OUT):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
