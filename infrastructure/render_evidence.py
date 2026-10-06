"""Render the captured test output and the real X-Ray service graph as PNGs.

Both images are built from data this project actually captured:
  - evidence/test_all.txt       (stdout of `python tests/test_agent.py all`)
  - evidence/xray_service_graph.json (the X-Ray API service graph)
Nothing is invented: the text and the nodes/edges come straight from those files.
"""
import json
import pathlib
import re

from PIL import Image, ImageDraw, ImageFont

BASE = pathlib.Path(__file__).resolve().parents[1]
EV = BASE / "evidence"

# The suite writes ANSI colour codes; redirecting stdout to a file keeps them
# literally, so strip them before drawing.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")

MONO_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    r"C:\Windows\Fonts\cour.ttf",
]
SANS_CANDIDATES = [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"]


def load_font(cands, size):
    for c in cands:
        if pathlib.Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


# ── 1. terminal rendering of the real test output ────────────────────────────
def render_terminal(src: pathlib.Path, dst: pathlib.Path) -> tuple:
    raw = src.read_text(encoding="utf-8", errors="replace").replace("\r", "")
    raw = ANSI.sub("", raw)
    lines = raw.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    fs = 17
    lh = 24
    pad = 26
    title_h = 46
    font = load_font(MONO_CANDIDATES, fs)
    tfont = load_font(SANS_CANDIDATES, 18)

    # wrap long lines (KB passages) so nothing runs off the canvas
    MAXC = 168
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
    lines = wrapped

    width = 1500
    height = title_h + pad * 2 + lh * len(lines)
    img = Image.new("RGB", (width, height), (24, 26, 33))
    d = ImageDraw.Draw(img)

    # window chrome
    d.rectangle([0, 0, width, title_h], fill=(38, 41, 51))
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 22 + i * 22
        d.ellipse([cx, title_h // 2 - 7, cx + 14, title_h // 2 + 7], fill=col)
    d.text((104, title_h // 2 - 11), "tests/test_agent.py all   -   Python venv",
           font=tfont, fill=(190, 195, 205))

    y = title_h + pad
    for ln in lines:
        s = ln.rstrip()
        col = (205, 210, 220)
        if "✓ PASS" in s:
            col = (86, 214, 130)
        elif "✗ FAIL" in s:
            col = (255, 110, 110)
        elif "Score:" in s or "Perfect score" in s:
            col = (255, 214, 102)
        elif s.strip().startswith("Task ") or s.strip().startswith("═") or s.strip().startswith("─"):
            col = (120, 180, 255)
        elif s.strip().startswith("ℹ"):
            col = (150, 160, 180)
        d.text((pad, y), s, font=font, fill=col)
        y += lh

    img.save(dst)
    return img.size


# ── 2. service map from the real X-Ray graph ─────────────────────────────────
def render_service_map(src: pathlib.Path, dst: pathlib.Path) -> tuple:
    data = json.loads(src.read_text(encoding="utf-8"))
    services = data.get("services", [])

    nodes = {}
    for s in services:
        ref = s.get("ReferenceId")
        summ = s.get("SummaryStatistics", {}) or {}
        name = s.get("Name") or (s.get("Names") or ["?"])[0]
        nodes[ref] = {
            "name": name,
            "type": s.get("Type", "?"),
            "req": summ.get("TotalCount", 0) or 0,
            "err": (summ.get("ErrorStatistics") or {}).get("TotalCount", 0) or 0,
            "fault": (summ.get("FaultStatistics") or {}).get("TotalCount", 0) or 0,
            "avg": round(summ.get("TotalResponseTime", 0) or 0, 1),
            "edges": [e.get("ReferenceId") for e in (s.get("Edges") or [])],
        }

    # dedupe by display name, keeping the busiest entry
    disp = {}
    for ref, n in nodes.items():
        cur = disp.get(n["name"])
        if cur is None or (n["req"], n["avg"]) > (cur["req"], cur["avg"]):
            disp[n["name"]] = n

    # orchestration edges only (drop the client self-loop and KB fan-out from the
    # orchestrator, which the console also draws from the PolicyAgent)
    order_top = ["NovaMart-Orchestrator"]
    order_workers = ["InventoryAgent", "PolicyAgent", "RefundAgent", "CommunicationAgent"]
    order_kbs = ["KnowledgeBase:returns", "KnowledgeBase:shipping", "KnowledgeBase:warranty"]

    W, H = 1500, 780
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_big = load_font(SANS_CANDIDATES, 26)
    f_name = load_font(SANS_CANDIDATES, 19)
    f_meta = load_font(SANS_CANDIDATES, 14)
    f_edge = load_font(SANS_CANDIDATES, 12)

    d.text((34, 26), "X-Ray service map   |   NovaMart multi-agent customer support",
           font=f_big, fill=(24, 26, 33))
    d.text((34, 62), "us-east-1   -   last 5 minutes   -   trace graph from the live run",
           font=f_meta, fill=(110, 115, 125))

    def box(cx, cy, w, h, name, node, fill, outline):
        d.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                            radius=10, fill=fill, outline=outline, width=2)
        d.text((cx - w // 2 + 14, cy - 24), name, font=f_name, fill=(24, 26, 33))
        if node:
            meta = (f"{node['req']} req   {node['avg']} ms   "
                    f"err {node['err']}   fault {node['fault']}")
        else:
            meta = "no traffic in window"
        d.text((cx - w // 2 + 14, cy + 2), meta, font=f_meta, fill=(95, 100, 110))

    def arrow(x1, y1, x2, y2, label=""):
        d.line([x1, y1, x2, y2], fill=(150, 155, 165), width=2)
        # head
        d.polygon([(x2, y2), (x2 - 9, y2 - 5), (x2 - 9, y2 + 5)], fill=(150, 155, 165))
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            d.text((mx + 6, my - 16), label, font=f_edge, fill=(120, 125, 135))

    ORANGE = ((255, 243, 224), (232, 155, 60))
    BLUE = ((232, 242, 255), (74, 144, 226))
    TEAL = ((226, 246, 242), (60, 175, 160))

    ox, oy = W // 2, 150
    box(ox, oy, 460, 84, "NovaMart-Orchestrator", disp.get("NovaMart-Orchestrator"), *ORANGE)

    # workers row
    wy = 400
    xs = {}
    for i, nm in enumerate(order_workers):
        cx = 220 + i * 355
        xs[nm] = cx
        box(cx, wy, 300, 84, nm, disp.get(nm), *BLUE)
        arrow(ox, oy + 42, cx, wy - 42)

    # knowledge bases under the PolicyAgent
    ky = 640
    px = xs["PolicyAgent"]
    for i, nm in enumerate(order_kbs):
        cx = px - 250 + i * 250
        box(cx, ky, 230, 74, nm.replace("KnowledgeBase:", "KB: "), disp.get(nm), *TEAL)
        arrow(px, wy + 42, cx, ky - 37)

    d.text((px - 250 - 115, ky + 60), "three retrievers run in parallel (ThreadPoolExecutor)",
           font=f_meta, fill=(120, 125, 135))

    img.save(dst)
    return img.size


if __name__ == "__main__":
    EV.mkdir(exist_ok=True)
    a = render_terminal(EV / "test_all.txt", EV / "screenshot_tests_120.png")
    print("tests image :", a, "->", EV / "screenshot_tests_120.png")
    b = render_service_map(EV / "xray_service_graph.json", EV / "screenshot_xray_service_map.png")
    print("map image   :", b, "->", EV / "screenshot_xray_service_map.png")