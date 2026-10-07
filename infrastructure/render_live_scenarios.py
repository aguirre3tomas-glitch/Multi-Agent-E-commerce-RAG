"""Split the live test output into one image per scenario.

The reviewer asked for screenshots of `python src/agent_orchestrator.py test`.
One 9890px image is unusable, so each of the three scenarios gets its own
screenshot, including the X-Ray trace id the run printed.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from render_evidence import (ANSI, MONO_CANDIDATES, SANS_CANDIDATES,  # noqa: E402
                             load_font)

BASE = pathlib.Path(__file__).resolve().parents[1]
EV = BASE / "evidence"

SEP = "─" * 40


def split_scenarios(text: str) -> list:
    """Return [(header_line, [lines]), ...] split on the separator banner."""
    lines = text.split("\n")
    blocks, cur = [], []
    for ln in lines:
        if ln.startswith(SEP[:30]):
            if cur:
                blocks.append(cur)
            cur = []
            continue
        cur.append(ln)
    if cur:
        blocks.append(cur)
    # drop empty blocks and the leading "Running local agent test..." noise
    out = []
    for b in blocks:
        b = [x for x in b]
        while b and not b[0].strip():
            b.pop(0)
        if b:
            out.append(b)
    return out


def render(lines: list, dst: pathlib.Path, title: str) -> tuple:
    fs, lh, pad, title_h = 15, 21, 24, 44
    font = load_font(MONO_CANDIDATES, fs)
    tfont = load_font(SANS_CANDIDATES, 17)

    MAXC = 176
    wrapped = []
    for ln in lines:
        s = ln.rstrip()
        while len(s) > MAXC:
            cut = s.rfind(" ", 0, MAXC)
            if cut < MAXC // 2:
                cut = MAXC
            wrapped.append(s[:cut])
            s = "    " + s[cut:].lstrip()
        wrapped.append(s)

    width = 1520
    height = title_h + pad * 2 + lh * len(wrapped)
    img = Image.new("RGB", (width, height), (24, 26, 33))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, title_h], fill=(38, 41, 51))
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 22 + i * 22
        d.ellipse([cx, title_h // 2 - 7, cx + 14, title_h // 2 + 7], fill=col)
    d.text((104, title_h // 2 - 10), title, font=tfont, fill=(190, 195, 205))

    y = title_h + pad
    for s in wrapped:
        col = (205, 210, 220)
        if s.strip().startswith("Tool #"):
            col = (120, 180, 255)
        elif "X-Ray trace" in s:
            col = (86, 214, 130)
        elif s.strip().startswith("Query:"):
            col = (255, 214, 102)
        elif s.strip().startswith("Session:"):
            col = (150, 160, 180)
        elif s.strip().startswith("STEP"):
            col = (200, 150, 255)
        d.text((pad, y), s, font=font, fill=col)
        y += lh
    img.save(dst)
    return img.size


if __name__ == "__main__":
    raw = EV / "live_test.txt"
    text = ANSI.sub("", raw.read_text(encoding="utf-8", errors="replace")).replace("\r", "")
    blocks = split_scenarios(text)

    # the first block holds the "Running local agent test..." preamble; keep only
    # the three blocks that carry a Query
    scenarios = [b for b in blocks if any(x.strip().startswith("Query:") for x in b)]
    print(f"scenarios found: {len(scenarios)}")

    for n, b in enumerate(scenarios, 1):
        q = next(x.strip() for x in b if x.strip().startswith("Query:"))
        trace = next((x.strip() for x in b if "X-Ray trace" in x), "no trace id")
        tid = re.search(r"1-[0-9a-f]{8}-[0-9a-f]{24}", trace)
        title = f"src/agent_orchestrator.py test   -   scenario {n}/3"
        dst = EV / f"screenshot_live_test_scenario{n}.png"
        size = render(b, dst, title)
        print(f"  scenario {n}: {size} -> {dst.name}")
        print(f"     {q[:100]}")
        print(f"     trace: {tid.group(0) if tid else 'n/a'}")
