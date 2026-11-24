#!/usr/bin/env python3
"""
Pocket Recorder Gatekeeper Verification & Routing Pipeline (verify.py)

Runs deterministic checks and optional Freerouting + KiCad CLI ERC/DRC/Render:
  1. (--regen)    Re-runs build_pocket_recorder.py + build_pocket_recorder_sch.py.
  2. (--route)    Exports Specctra .dsn -> runs Freerouting CLI -> imports .ses -> fills zones.
  3. (always)     Pure-Python mechanical, acoustic, keepout, pad-overlap & sch<->pcb parity checks.
  4. (default)    KiCad CLI ERC + DRC (--format json) with exact (x, y) violation reporting.
  5. (default)    Renders top_outward & bottom_parts SVG (and PNG if converter available).

Usage:
  python3 verify.py --mech-only          # Fast pure-Python mechanical + parity check
  python3 verify.py                      # Full mechanical + KiCad ERC/DRC + layer renders
  python3 verify.py --regen              # Regenerate sch/pcb/bom then run full verification
  python3 verify.py --route --max-passes 25
"""
import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
HW_DIR = WORKSPACE / "pocket_recorder_hw"
PCB_PATH = HW_DIR / "pocket_recorder.kicad_pcb"
SCH_PATH = HW_DIR / "pocket_recorder.kicad_sch"
BOM_PATH = HW_DIR / "pocket_recorder_bom.csv"
OUT_DIR = WORKSPACE / "verify_out"

# Hard mechanical constants from SPEC.md + GEMINI.md
BOARD_W = 30.0
BOARD_H = 48.0
RIM_MIN_X, RIM_MAX_X = 1.0, 29.0
RIM_MIN_Y, RIM_MAX_Y = 1.0, 47.0
MIC_XY = (11.25, 42.5)
LED_XY = (18.75, 42.5)
VENT_RADIUS = 3.0  # Ø6.0 mm bare solder mask disc around MK1 (X7)
MIN_SWITCHER_DIST = 30.0  # R5: >=30 mm from MK1 to buck/charger/inductors
SWITCHER_REFS = ("U3", "U4", "L1", "L2")
EXPECTED_POGO = {
    "TP_GND":   (6.0,  3.0, "GND"),
    "TP_DP":    (12.0, 3.0, "USB_DP"),
    "TP_DM":    (18.0, 3.0, "USB_DM"),
    "TP_5V":    (24.0, 3.0, "VBUS_5V"),
    "TP_SWDIO": (9.0,  9.0, "SWDIO"),
    "TP_NRST":  (15.0, 9.0, "NRST"),
    "TP_SWCLK": (21.0, 9.0, "SWCLK"),
}


# ==============================================================================
# 1. MINIMAL ZERO-DEPENDENCY KICAD S-EXPRESSION PARSER
# ==============================================================================
_TOKEN_RE = re.compile(r'\s*(?:(\()|(\))|("(?:\\.|[^"\\])*")|([^\s()"]+))')


def parse_sexp(text):
    tokens = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if not m:
            break
        pos = m.end()
        if m.group(1):
            tokens.append("(")
        elif m.group(2):
            tokens.append(")")
        elif m.group(3):
            tokens.append(bytes(m.group(3)[1:-1], "utf-8").decode("unicode_escape"))
        else:
            tokens.append(m.group(4))

    stack = [[]]
    for tok in tokens:
        if tok == "(":
            lst = []
            stack[-1].append(lst)
            stack.append(lst)
        elif tok == ")":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].append(tok)
    return stack[0][0] if stack[0] else []


def find_children(node, tag):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def find_first(node, tag):
    for c in node[1:]:
        if isinstance(c, list) and c and c[0] == tag:
            return c
    return None


def prop_map(node):
    props = {}
    for p in find_children(node, "property"):
        if len(p) >= 3:
            props[p[1]] = p[2]
    return props


# ==============================================================================
# 2. GEOMETRY HELPERS
# ==============================================================================
def transform_pad_bbox(fx, fy, frot_deg, px, py, sx, sy):
    """
    Transform a pad in KiCad footprint-local coords into board coords.
    Note: KiCad footprint rotation angle rotates CCW in screen coords (Y-down):
      x' = x*cos(a) + y*sin(a), y' = -x*sin(a) + y*cos(a)
    """
    rad = math.radians(frot_deg)
    ca, sa = math.cos(rad), math.sin(rad)
    cx = fx + px * ca + py * sa
    cy = fy - px * sa + py * ca
    # Rotated bounding box half-extents
    hx = 0.5 * (abs(sx * ca) + abs(sy * sa))
    hy = 0.5 * (abs(sx * sa) + abs(sy * ca))
    return cx, cy, cx - hx, cy - hy, cx + hx, cy + hy


def dist_point_to_segment(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    proj_x, proj_y = x1 + t * dx, y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def boxes_overlap(a, b, margin=0.0):
    return not (
        a[2] + margin <= b[0]
        or b[2] + margin <= a[0]
        or a[3] + margin <= b[1]
        or b[3] + margin <= a[1]
    )


# ==============================================================================
# 3. PURE-PYTHON MECHANICAL, ACOUSTIC & PARITY CHECKS
# ==============================================================================
def run_mechanical_and_parity_checks():
    failures = []
    warnings = []
    metrics = {}

    if not PCB_PATH.exists():
        return ["Missing PCB file: " + str(PCB_PATH)], [], {}
    if not SCH_PATH.exists():
        return ["Missing schematic file: " + str(SCH_PATH)], [], {}

    pcb = parse_sexp(PCB_PATH.read_text(encoding="utf-8"))
    sch = parse_sexp(SCH_PATH.read_text(encoding="utf-8"))

    # --- 3A. Outline Bounds (X1: <= 30.0 x 48.0 mm) ---
    edge_xs, edge_ys = [], []
    for tag in ("gr_line", "gr_arc", "gr_rect"):
        for g in find_children(pcb, tag):
            layer = find_first(g, "layer")
            if layer and layer[1] == "Edge.Cuts":
                for pt_tag in ("start", "mid", "end"):
                    pt = find_first(g, pt_tag)
                    if pt and len(pt) >= 3:
                        edge_xs.append(float(pt[1]))
                        edge_ys.append(float(pt[2]))
    if not edge_xs:
        failures.append("X1: No Edge.Cuts geometry found.")
    else:
        w = round(max(edge_xs) - min(edge_xs), 3)
        h = round(max(edge_ys) - min(edge_ys), 3)
        metrics["board_size_mm"] = [w, h]
        if w > BOARD_W + 0.01 or h > BOARD_H + 0.01:
            failures.append(f"X1: Board outline {w}x{h} mm exceeds {BOARD_W}x{BOARD_H} mm.")

    # --- 3B. Outward Silkscreen (Zero text / pad labels / RefDes; only intentional vector icons on F.SilkS) ---
    fsilk_bad = []
    fsilk_gfx_count = 0
    for tag in ("gr_line", "gr_arc", "gr_circle"):
        for g in find_children(pcb, tag):
            layer = find_first(g, "layer")
            if layer and layer[1] == "F.SilkS":
                fsilk_gfx_count += 1
    for tag in ("gr_text",):
        for g in find_children(pcb, tag):
            layer = find_first(g, "layer")
            if layer and layer[1] == "F.SilkS":
                fsilk_bad.append(f"board {tag}")
    for fp in find_children(pcb, "footprint"):
        ref = prop_map(fp).get("Reference", "?")
        for tag in ("fp_line", "fp_arc", "fp_circle", "fp_rect", "fp_poly", "fp_text"):
            for g in find_children(fp, tag):
                layer = find_first(g, "layer")
                if layer and layer[1] == "F.SilkS":
                    fsilk_bad.append(f"{ref} {tag}")
        for p in find_children(fp, "property"):
            layer = find_first(p, "layer")
            hide = find_first(p, "hide")
            is_hidden = (hide is not None and len(hide) >= 2 and hide[1] == "yes") or (
                any(isinstance(c, str) and c == "hide" for c in p)
            )
            if layer and layer[1] == "F.SilkS" and not is_hidden:
                fsilk_bad.append(f"{ref} visible property '{p[1]}'")
    metrics["outward_fsilk_vector_primitives"] = fsilk_gfx_count
    if fsilk_bad:
        failures.append(f"Outward F.SilkS must have zero text/RefDes, found {len(fsilk_bad)} items: {fsilk_bad[:5]}")

    # --- 3C. Parse All Footprints & Pads ---
    pcb_fps = {}
    bcu_pad_boxes = []  # (ref, pad_num, net, (x1, y1, x2, y2))

    for fp in find_children(pcb, "footprint"):
        lib_id = fp[1]
        layer_n = find_first(fp, "layer")
        layer = layer_n[1] if layer_n else "?"
        at_n = find_first(fp, "at")
        fx = float(at_n[1])
        fy = float(at_n[2])
        frot = float(at_n[3]) if len(at_n) >= 4 else 0.0
        props = prop_map(fp)
        ref = props.get("Reference", "?")
        val = props.get("Value", "")

        pads_info = []
        for pad in find_children(fp, "pad"):
            pnum = pad[1]
            ptype = pad[2]
            pat = find_first(pad, "at")
            psize = find_first(pad, "size")
            pnet = find_first(pad, "net")
            px, py = float(pat[1]), float(pat[2])
            sx, sy = float(psize[1]), float(psize[2])
            if pnet and len(pnet) >= 3:
                net_name = pnet[2]
            elif pnet and len(pnet) == 2:
                net_name = pnet[1]
            else:
                net_name = ""
            cx, cy, x1, y1, x2, y2 = transform_pad_bbox(fx, fy, frot, px, py, sx, sy)
            pads_info.append({
                "num": pnum, "type": ptype, "net": net_name,
                "cx": cx, "cy": cy, "bbox": (x1, y1, x2, y2),
            })
            if layer == "B.Cu" and ptype != "np_thru_hole":
                bcu_pad_boxes.append((ref, pnum, net_name, (x1, y1, x2, y2)))

        pcb_fps[ref] = {
            "lib_id": lib_id, "layer": layer, "x": fx, "y": fy,
            "rot": frot, "val": val, "pads": pads_info,
        }

    # --- 3D. Fixed Outward Geometry (7 Pogo Pads + MK1 + D2) ---
    for ref, (ex, ey, enet) in EXPECTED_POGO.items():
        if ref not in pcb_fps:
            failures.append(f"C2/C3: Missing outward pogo pad {ref}.")
            continue
        fp = pcb_fps[ref]
        if fp["layer"] != "F.Cu":
            failures.append(f"C2: {ref} must be on F.Cu (found {fp['layer']}).")
        if math.hypot(fp["x"] - ex, fp["y"] - ey) > 0.02:
            failures.append(f"C2/C3: {ref} at ({fp['x']:.2f}, {fp['y']:.2f}), expected ({ex:.2f}, {ey:.2f}).")
        pnet = fp["pads"][0]["net"] if fp["pads"] else ""
        if pnet != enet:
            failures.append(f"C3: {ref} net is '{pnet}', expected '{enet}'.")

    # Verify zero non-pogo footprints on F.Cu (X3)
    bad_fcu = [r for r, d in pcb_fps.items() if d["layer"] == "F.Cu" and r not in EXPECTED_POGO]
    if bad_fcu:
        failures.append(f"X3: Non-pogo components placed on outward F.Cu: {bad_fcu}")

    # Verify MK1 & D2 exact hole positions and 7.5 mm pitch (U3 / Option 8C)
    for ref, (ex, ey) in [("MK1", MIC_XY), ("D2", LED_XY)]:
        if ref not in pcb_fps:
            failures.append(f"Missing required footprint {ref}.")
        else:
            fp = pcb_fps[ref]
            if math.hypot(fp["x"] - ex, fp["y"] - ey) > 0.02:
                failures.append(f"Option 8C/U3: {ref} at ({fp['x']:.2f}, {fp['y']:.2f}), expected ({ex:.2f}, {ey:.2f}).")

    # --- 3E. Switcher Acoustic Separation >= 30.0 mm from MK1 (R5) ---
    switcher_dists = {}
    if "MK1" in pcb_fps:
        mx, my = pcb_fps["MK1"]["x"], pcb_fps["MK1"]["y"]
        for sref in SWITCHER_REFS:
            if sref not in pcb_fps:
                failures.append(f"R5: Missing switcher/charger footprint {sref}.")
                continue
            sfp = pcb_fps[sref]
            center_d = math.hypot(sfp["x"] - mx, sfp["y"] - my)
            pad_ds = [math.hypot(p["cx"] - mx, p["cy"] - my) for p in sfp["pads"]]
            min_pad_d = min(pad_ds) if pad_ds else center_d
            switcher_dists[sref] = {"center_mm": round(center_d, 2), "nearest_pad_mm": round(min_pad_d, 2)}
            if min_pad_d < MIN_SWITCHER_DIST:
                failures.append(
                    f"R5: {sref} nearest pad is {min_pad_d:.2f} mm from MK1 "
                    f"(center {center_d:.2f} mm) — must be >= {MIN_SWITCHER_DIST:.1f} mm."
                )
    metrics["switcher_distances_from_MK1"] = switcher_dists

    # --- 3F. Parts-Side 1.0 mm Rim Keepout (X3) ---
    rim_violations = []
    for ref, pnum, _, (x1, y1, x2, y2) in bcu_pad_boxes:
        if x1 < RIM_MIN_X - 1e-3 or x2 > RIM_MAX_X + 1e-3 or y1 < RIM_MIN_Y - 1e-3 or y2 > RIM_MAX_Y + 1e-3:
            rim_violations.append(
                f"{ref}.{pnum} bbox=({x1:.2f},{y1:.2f})..({x2:.2f},{y2:.2f})"
            )
    if rim_violations:
        failures.append(
            f"X3: {len(rim_violations)} B.Cu pads violate 1.0 mm rim [{RIM_MIN_X}..{RIM_MAX_X}, "
            f"{RIM_MIN_Y}..{RIM_MAX_Y}]: {rim_violations[:6]}"
        )

    # --- 3G. B.Cu Inter-Footprint Pad Overlap Check (min 0.13 mm clearance) ---
    overlaps = []
    n_pads = len(bcu_pad_boxes)
    for i in range(n_pads):
        r1, p1, _, b1 = bcu_pad_boxes[i]
        for j in range(i + 1, n_pads):
            r2, p2, _, b2 = bcu_pad_boxes[j]
            if r1 == r2:
                continue
            if boxes_overlap(b1, b2, margin=0.127):
                overlaps.append(f"{r1}.{p1} <-> {r2}.{p2}")
    if overlaps:
        failures.append(f"Placement pad collision (<0.127 mm) between {len(overlaps)} pad pairs: {overlaps[:8]}")

    # --- 3H. Acoustic Vent Ø6.0 mm Keepout Around MK1 (X7) ---
    mx, my = MIC_XY
    bad_vias = []
    for via in find_children(pcb, "via"):
        at_n = find_first(via, "at")
        sz_n = find_first(via, "size")
        vx, vy = float(at_n[1]), float(at_n[2])
        vr = float(sz_n[1]) / 2.0 if sz_n else 0.3
        if math.hypot(vx - mx, vy - my) - vr < VENT_RADIUS:
            bad_vias.append(f"via@({vx:.2f},{vy:.2f})")
    if bad_vias:
        failures.append(f"X7: Vias inside Ø6.0 mm vent disc around MK1: {bad_vias}")

    bad_mask = 0
    for gl in find_children(pcb, "gr_line"):
        layer_n = find_first(gl, "layer")
        if layer_n and layer_n[1] == "F.Mask":
            st = find_first(gl, "start")
            en = find_first(gl, "end")
            sw = find_first(find_first(gl, "stroke") or [], "width")
            half_w = float(sw[1]) / 2.0 if sw else 0.2
            d = dist_point_to_segment(mx, my, float(st[1]), float(st[2]), float(en[1]), float(en[2])) - half_w
            if d < VENT_RADIUS:
                bad_mask += 1
    if bad_mask:
        failures.append(f"X7: {bad_mask} F.Mask thumbprint segments intrude into Ø6.0 mm vent disc around MK1.")

    # --- 3I. Outward GND Pour 1.0 mm Keepout Around Non-GND Pogo Pads (C5) ---
    keepout_zones = []
    for z in find_children(pcb, "zone"):
        layer_n = find_first(z, "layer")
        ko_n = find_first(z, "keepout")
        if layer_n and layer_n[1] == "F.Cu" and ko_n:
            poly = find_first(z, "polygon")
            pts = find_first(poly, "pts") if poly else None
            if pts:
                xs = [float(p[1]) for p in find_children(pts, "xy")]
                ys = [float(p[2]) for p in find_children(pts, "xy")]
                if xs and ys:
                    keepout_zones.append((min(xs), min(ys), max(xs), max(ys)))
    for ref, (ex, ey, enet) in EXPECTED_POGO.items():
        if enet == "GND":
            continue
        covered = any(
            kx1 <= ex - 2.49 and kx2 >= ex + 2.49 and ky1 <= ey - 2.49 and ky2 >= ey + 2.49
            for kx1, ky1, kx2, ky2 in keepout_zones
        )
        if not covered:
            failures.append(f"C5: Missing >=1.0 mm F.Cu copper-pour keepout around {ref} ({enet}).")

    # --- 3J. Schematic <-> PCB & BOM Parity ---
    sch_parts = {}
    for sym in find_children(sch, "symbol"):
        props = prop_map(sym)
        ref = props.get("Reference", "")
        if not ref or ref.startswith("#"):
            continue
        sch_parts[ref] = {
            "val": props.get("Value", ""),
            "fp": props.get("Footprint", ""),
        }
    sch_refs = set(sch_parts.keys())
    pcb_refs = set(pcb_fps.keys())
    if sch_refs != pcb_refs:
        missing_in_pcb = sorted(sch_refs - pcb_refs)
        missing_in_sch = sorted(pcb_refs - sch_refs)
        failures.append(
            f"Parity: Schematic/PCB RefDes mismatch — only in SCH: {missing_in_pcb}, only in PCB: {missing_in_sch}"
        )
    else:
        fp_mismatches = [
            f"{r} (SCH={sch_parts[r]['fp']} vs PCB={pcb_fps[r]['lib_id']})"
            for r in sorted(sch_refs)
            if sch_parts[r]["fp"] != pcb_fps[r]["lib_id"]
        ]
        if fp_mismatches:
            failures.append(f"Parity: Footprint mismatches: {fp_mismatches[:6]}")

    # Check BOM covers all physical parts (excluding bare PCB pads TP_*, J_BAT, J_DBG)
    if BOM_PATH.exists():
        bom_qty = 0
        with BOM_PATH.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                bom_qty += int(row["Qty"])
        expected_bom_parts = len([r for r in pcb_refs if not r.startswith("TP_") and r not in ("J_BAT", "J_DBG")])
        metrics["part_counts"] = {
            "total_pcb_footprints": len(pcb_refs),
            "bom_populated_parts": bom_qty,
            "expected_populated_parts": expected_bom_parts,
        }
        if bom_qty != expected_bom_parts:
            warnings.append(f"BOM qty ({bom_qty}) != populated PCB footprints ({expected_bom_parts}).")

    return failures, warnings, metrics


# ==============================================================================
# 4. FREEROUTING CLI BRIDGE (--route)
# ==============================================================================
def run_freerouting(freerouting_cmd, max_passes):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dsn_path = OUT_DIR / "pocket_recorder.dsn"
    ses_path = OUT_DIR / "pocket_recorder.ses"

    # Step 1: Export Specctra DSN via KiCad's pcbnew Python module
    export_code = (
        f"import pcbnew; b = pcbnew.LoadBoard(r'{PCB_PATH}'); "
        f"assert pcbnew.ExportSpecctraDSN(b, r'{dsn_path}'), 'DSN export failed'"
    )
    res = subprocess.run([sys.executable, "-c", export_code], capture_output=True, text=True)
    if res.returncode != 0:
        # Try KiCad's bundled python on macOS/Windows/Linux if system python lacks pcbnew
        alt_py = shutil.which("kicad-python") or "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
        if Path(alt_py).exists():
            res = subprocess.run([str(alt_py), "-c", export_code], capture_output=True, text=True)
        if res.returncode != 0:
            return False, (
                "Could not import KiCad 'pcbnew' to export Specctra DSN. "
                "Run with KiCad's bundled Python or export pocket_recorder.dsn from KiCad GUI.\n"
                f"stderr: {res.stderr.strip()}"
            )

    # Step 2: Locate & run Freerouting CLI
    if freerouting_cmd:
        cmd = freerouting_cmd.split() + ["-de", str(dsn_path), "-do", str(ses_path), "-mp", str(max_passes)]
    elif shutil.which("freerouting"):
        cmd = ["freerouting", "-de", str(dsn_path), "-do", str(ses_path), "-mp", str(max_passes)]
    elif os.environ.get("FREEROUTING_JAR") and Path(os.environ["FREEROUTING_JAR"]).exists():
        cmd = ["java", "-jar", os.environ["FREEROUTING_JAR"], "-de", str(dsn_path), "-do", str(ses_path), "-mp", str(max_passes)]
    elif (WORKSPACE / "freerouting.jar").exists():
        cmd = ["java", "-jar", str(WORKSPACE / "freerouting.jar"), "-de", str(dsn_path), "-do", str(ses_path), "-mp", str(max_passes)]
    else:
        return False, (
            "Freerouting not found. Install 'freerouting' on PATH, place freerouting.jar in the repo root, "
            "or set FREEROUTING_JAR=/path/to/freerouting.jar."
        )

    print(f"[route] Running: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not ses_path.exists():
        return False, f"Freerouting failed (rc={r.returncode}): {r.stderr.strip() or r.stdout.strip()}"

    # Step 3: Import SES & refill copper zones
    import_code = (
        f"import pcbnew; b = pcbnew.LoadBoard(r'{PCB_PATH}'); "
        f"assert pcbnew.ImportSpecctraSES(b, r'{ses_path}'), 'SES import failed'; "
        f"pcbnew.ZONE_FILLER(b).Fill(b.Zones()); "
        f"b.Save(r'{PCB_PATH}')"
    )
    py_exe = sys.executable
    if subprocess.run([py_exe, "-c", "import pcbnew"], capture_output=True).returncode != 0:
        py_exe = shutil.which("kicad-python") or "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
    r2 = subprocess.run([py_exe, "-c", import_code], capture_output=True, text=True)
    if r2.returncode != 0:
        return False, f"SES import/zone-fill failed: {r2.stderr.strip()}"
    return True, f"Freerouting completed ({max_passes} passes) and merged into {PCB_PATH.name}."


# ==============================================================================
# 5. KICAD CLI ERC, DRC & LAYER RENDERS
# ==============================================================================
def find_kicad_cli():
    cli = shutil.which("kicad-cli")
    if cli:
        return cli
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "10.0" / "bin" / "kicad-cli.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "9.0" / "bin" / "kicad-cli.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad" / "8.0" / "bin" / "kicad-cli.exe",
        Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"),
        Path(r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"),
        Path(r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def kicad_env():
    env = os.environ.copy()
    cfg_dir = OUT_DIR / ".kicad_cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    env.setdefault("KICAD_CONFIG_HOME", str(cfg_dir))
    env.setdefault("KICAD_DOCUMENTS_HOME", str(cfg_dir))
    if os.name == "nt":
        # Avoid OneDrive Documents permission failures in restricted environments
        env["KICAD_CONFIG_HOME"] = str(cfg_dir)
        env["KICAD_DOCUMENTS_HOME"] = str(cfg_dir)
        env["APPDATA"] = str(cfg_dir)
        env["LOCALAPPDATA"] = str(cfg_dir)
    return env


def run_kicad_erc_drc(allow_unrouted=False):
    kicad_cli = find_kicad_cli()
    if not kicad_cli:
        return None, ["kicad-cli not found on PATH — install KiCad 8/9/10 or run with --mech-only."]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    erc_json = OUT_DIR / "erc.json"
    drc_json = OUT_DIR / "drc.json"
    for p in (erc_json, drc_json):
        if p.exists():
            p.unlink()

    env = kicad_env()
    r_erc = subprocess.run(
        [kicad_cli, "sch", "erc", "--format", "json", "--severity-all", "-o", str(erc_json), str(SCH_PATH)],
        capture_output=True, text=True, env=env,
    )
    r_drc = subprocess.run(
        [kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "--schematic-parity", "-o", str(drc_json), str(PCB_PATH)],
        capture_output=True, text=True, env=env,
    )

    summary = {"erc_errors": 0, "erc_warnings": 0, "drc_errors": 0, "drc_warnings": 0, "unconnected": 0, "top_violations": []}
    failures = []

    if r_erc.returncode != 0 or not erc_json.exists():
        failures.append(f"kicad-cli sch erc failed (rc={r_erc.returncode}): {r_erc.stderr.strip()}")
    else:
        data = json.loads(erc_json.read_text(encoding="utf-8"))
        for sheet in data.get("sheets", []):
            for v in sheet.get("violations", []):
                sev = v.get("severity", "")
                if sev == "error":
                    summary["erc_errors"] += 1
                    summary["top_violations"].append(f"ERC ERROR: {v.get('description')}")
                elif sev == "warning":
                    summary["erc_warnings"] += 1

    if r_drc.returncode != 0 or not drc_json.exists():
        failures.append(f"kicad-cli pcb drc failed (rc={r_drc.returncode}): {r_drc.stderr.strip()}")
    else:
        data = json.loads(drc_json.read_text(encoding="utf-8"))
        for v in data.get("violations", []) + data.get("schematic_parity", []):
            sev = v.get("severity", "")
            pos = ""
            if v.get("items") and v["items"][0].get("pos"):
                p = v["items"][0]["pos"]
                pos = f" @({p.get('x', 0):.2f},{p.get('y', 0):.2f})"
            if sev == "error":
                summary["drc_errors"] += 1
                summary["top_violations"].append(f"DRC ERROR [{v.get('type')}]{pos}: {v.get('description')}")
            elif sev == "warning":
                summary["drc_warnings"] += 1
        unconn = data.get("unconnected_items", [])
        summary["unconnected"] = len(unconn)

    if summary["erc_errors"] > 0:
        failures.append(f"KiCad ERC failed with {summary['erc_errors']} error(s).")
    if summary["drc_errors"] > 0:
        failures.append(f"KiCad DRC failed with {summary['drc_errors']} error(s).")
    if summary["unconnected"] > 0 and not allow_unrouted:
        failures.append(f"KiCad DRC reports {summary['unconnected']} unrouted airwire(s).")

    return summary, failures


def render_layers():
    kicad_cli = find_kicad_cli()
    if not kicad_cli:
        return []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = kicad_env()
    renders = []
    specs = [
        ("top_outward",  "F.Cu,F.Mask,Edge.Cuts", "top"),
        ("bottom_parts", "B.Cu,In2.Cu,B.SilkS,Edge.Cuts", "bottom"),
    ]
    for name, layers, side in specs:
        svg_path = OUT_DIR / f"{name}.svg"
        r = subprocess.run(
            [kicad_cli, "pcb", "export", "svg", "--layers", layers, "--page-size-mode", "2", "-o", str(svg_path), str(PCB_PATH)],
            capture_output=True, text=True, env=env,
        )
        if r.returncode == 0 and svg_path.exists():
            renders.append(str(svg_path))
        png_path = OUT_DIR / f"{name}.png"
        if shutil.which("rsvg-convert") and svg_path.exists():
            subprocess.run(["rsvg-convert", "-w", "1600", "-o", str(png_path), str(svg_path)], check=False)
            if png_path.exists():
                renders.append(str(png_path))
        else:
            r3 = subprocess.run(
                [
                    kicad_cli, "pcb", "render",
                    "--side", side, "--width", "1200", "--height", "1600",
                    "--use-board-stackup-colors", "--background", "opaque",
                    "-o", str(png_path), str(PCB_PATH),
                ],
                capture_output=True, text=True, env=env,
            )
            if r3.returncode == 0 and png_path.exists():
                renders.append(str(png_path))
    return renders


# ==============================================================================
# 6. MAIN ENTRY POINT
# ==============================================================================
def main():
    ap = argparse.ArgumentParser(description="Pocket Recorder verification & Freerouting gatekeeper")
    ap.add_argument("--regen", action="store_true", help="Re-run PCB & schematic generators before checking")
    ap.add_argument("--route", action="store_true", help="Run Freerouting CLI (.dsn -> .ses -> merge + zone fill)")
    ap.add_argument("--freerouting-cmd", default=None, help="Custom freerouting command (e.g. 'java -jar /path/freerouting.jar')")
    ap.add_argument("--max-passes", type=int, default=20, help="Freerouting max optimization passes (default: 20)")
    ap.add_argument("--mech-only", action="store_true", help="Run only pure-Python mechanical + parity checks (skip kicad-cli)")
    ap.add_argument("--no-render", action="store_true", help="Skip SVG/PNG layer rendering")
    ap.add_argument("--allow-unrouted", action="store_true", help="Do not fail on unrouted airwires (useful during placement)")
    args = ap.parse_args()

    if args.regen:
        print("[regen] Running build_pocket_recorder.py & build_pocket_recorder_sch.py...")
        subprocess.run([sys.executable, str(WORKSPACE / "build_pocket_recorder.py")], cwd=WORKSPACE, check=True)
        subprocess.run([sys.executable, str(WORKSPACE / "build_pocket_recorder_sch.py")], cwd=WORKSPACE, check=True)

    all_failures = []
    if args.route:
        ok, msg = run_freerouting(args.freerouting_cmd, args.max_passes)
        print(f"[route] {msg}")
        if not ok:
            all_failures.append(msg)

    mech_fail, mech_warn, metrics = run_mechanical_and_parity_checks()
    all_failures.extend(mech_fail)

    eda_summary = None
    renders = []
    if not args.mech_only:
        eda_summary, eda_fail = run_kicad_erc_drc(allow_unrouted=args.allow_unrouted)
        all_failures.extend(eda_fail)
        if not args.no_render:
            renders = render_layers()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": len(all_failures) == 0,
        "failures": all_failures,
        "warnings": mech_warn,
        "metrics": metrics,
        "kicad_eda": eda_summary,
        "renders": renders,
    }
    report_path = OUT_DIR / "verify_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n================ POCKET RECORDER VERIFY SCORECARD ================")
    print(f"Board size      : {metrics.get('board_size_mm')} mm (limit <= 30.0 x 48.0)")
    print(f"Switcher dists  : {metrics.get('switcher_distances_from_MK1')}")
    print(f"Part counts     : {metrics.get('part_counts')}")
    if eda_summary:
        print(
            f"KiCad ERC/DRC   : ERC err={eda_summary['erc_errors']} (warn={eda_summary['erc_warnings']}) | "
            f"DRC err={eda_summary['drc_errors']} (warn={eda_summary['drc_warnings']}) | "
            f"Unrouted={eda_summary['unconnected']}"
        )
        for v in eda_summary["top_violations"][:10]:
            print(f"   - {v}")
    if mech_warn:
        print("Warnings:")
        for w in mech_warn:
            print(f"  [WARN] {w}")
    if all_failures:
        print("FAILURES:")
        for f in all_failures:
            print(f"  [FAIL] {f}")
        print(f"\nResult: FAILED ({len(all_failures)} issue(s)). Full report -> {report_path}")
        sys.exit(1)
    else:
        print(f"\nResult: ALL CHECKS PASSED! Full report -> {report_path}")
        sys.exit(0)


if __name__ == "__main__":
    main()
