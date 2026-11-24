#!/usr/bin/env python3
"""
Pocket Recorder Hardware Generator (KiCad 8/9/10 + PCBWay 4L Matte-Black ENIG)
Generates:
  - pocket_recorder_hw/pocket_recorder.kicad_pro
  - pocket_recorder_hw/pocket_recorder.kicad_pcb
  - pocket_recorder_hw/pocket_recorder_bom.csv
  - pocket_recorder_hw/export_pcbway_gerbers.sh
"""
import csv
import json
import math
import os
import stat
import uuid

OUT_DIR = "pocket_recorder_hw"
os.makedirs(OUT_DIR, exist_ok=True)


def uid():
    return str(uuid.uuid4())


# ==============================================================================
# 1. NETLIST DEFINITION
# ==============================================================================
NETS = [
    "", "GND", "VBUS_5V", "VSYS", "VBAT", "+1V8", "+3V0_SD", "+3V3_USB",
    "USB_DP", "USB_DM", "USB_DP_MCU", "USB_DM_MCU", "VBUS_DET",
    "SWDIO", "SWCLK", "NRST", "BOOT0", "UART_TX", "UART_RX",
    "PDM_CLK", "PDM_DATA", "LED_R", "LED_G", "LED_B",
    "LED_R_K", "LED_G_K", "LED_B_K",
    "VBAT_ADC", "VBAT_EN", "CHG_STAT1", "CHG_STAT2",
    "BQ_ILIM", "BQ_ISET", "BQ_TS",
    "BUCK_SW", "SMPS_LX", "VDD11",
    "SD_PWR_EN", "SD_CD",
    "SD_D0_1V8", "SD_D1_1V8", "SD_D2_1V8", "SD_D3_1V8", "SD_CLK_1V8", "SD_CMD_1V8",
    "SD_D0_3V", "SD_D1_3V", "SD_D2_3V", "SD_D3_3V", "SD_CLK_3V", "SD_CMD_3V",
    "I2C_SCL", "I2C_SDA", "RTC_32K", "RTC_INT", "RTC_VBACK",
    "HSE_IN", "HSE_OUT",
]
NET_ID = {name: i for i, name in enumerate(NETS)}


def net_s(name):
    return f'(net {NET_ID[name]} "{name}")' if name else '(net 0 "")'


# ==============================================================================
# 2. KICAD PROJECT (.kicad_pro) — PCBWAY 4L MATTE-BLACK ENIG RULES
# ==============================================================================
KICAD_PRO = {
    "board": {
        "design_settings": {
            "defaults": {
                "board_outline_line_width": 0.1,
                "copper_line_width": 0.2,
                "silk_line_width": 0.15,
            },
            "rules": {
                "min_clearance": 0.127,
                "min_copper_edge_clearance": 0.3,
                "min_hole_clearance": 0.25,
                "min_hole_to_hole": 0.25,
                "min_silk_clearance": 0.15,
                "min_through_hole_diameter": 0.2,
                "min_track_width": 0.127,
                "min_via_annular_width": 0.125,
                "min_via_diameter": 0.45,
                "solder_mask_clearance": 0.05,
                "solder_mask_min_width": 0.127,  # PCBWay Matte-Black resist bridge minimum
            },
        },
        "layer_presets": [],
    },
    "meta": {"filename": "pocket_recorder.kicad_pro", "version": 1},
    "net_settings": {
        "classes": [
            {
                "clearance": 0.13,
                "diff_pair_gap": 0.15,
                "diff_pair_width": 0.20,
                "name": "Default",
                "track_width": 0.15,
                "via_diameter": 0.45,
                "via_drill": 0.20,
            },
            {
                "clearance": 0.15,
                "diff_pair_gap": 0.15,
                "diff_pair_width": 0.20,  # PCBWay 90-ohm diff pair ref In1.Cu
                "name": "USB_HS_90R",
                "track_width": 0.20,
                "via_diameter": 0.45,
                "via_drill": 0.20,
            },
            {
                "clearance": 0.135,
                "name": "Power",
                "track_width": 0.22,
                "via_diameter": 0.45,
                "via_drill": 0.20,
            },
        ],
        "netclass_assignments": {
            "USB_DP": "USB_HS_90R", "USB_DM": "USB_HS_90R",
            "USB_DP_MCU": "USB_HS_90R", "USB_DM_MCU": "USB_HS_90R",
            "VBUS_5V": "Power", "VSYS": "Power", "VBAT": "Power",
            "+1V8": "Power", "+3V0_SD": "Power", "+3V3_USB": "Power",
            "GND": "Power", "BUCK_SW": "Power", "SMPS_LX": "Power",
        },
    },
}


# ==============================================================================
# 3. PROCEDURAL ENIG GOLD THUMBPRINT ARTWORK (F.Mask openings over F.Cu GND)
# ==============================================================================
def generate_thumbprint_fmask(cx=15.0, cy=24.5, rx=7.4, ry=9.8):
    """
    Generates smooth vector ridge openings on F.Mask (0.38 mm gold ridge width,
    >=0.34 mm matte-black solder mask dams between ridges) centered at (cx, cy).
    Clear of Row 2 pads (y<=10.5) and MIC/LED holes + 6 mm keepout (y>=39.5).
    """
    lines = []
    ridge_w = 0.38
    pitch = 0.78  # 0.40 mm black resist dam between 0.38 mm gold ridges
    core_x, core_y = cx - 0.4, cy + 1.1
    n_rings = 14

    def inside_oval(x, y):
        dx = (x - cx) / rx
        dy = (y - cy) / ry
        return (dx * dx + dy * dy) <= 1.0

    for k in range(1, n_rings + 1):
        r = k * pitch
        pts = []
        steps = 120
        for s in range(steps + 1):
            t = 2.0 * math.pi * s / steps
            stretch_y = 1.32 if math.sin(t) < 0 else 1.18
            shear = 0.14 * math.sin(2.0 * t)
            x = core_x + (r * 0.86) * math.cos(t) + r * shear
            y = core_y + (r * stretch_y) * math.sin(t) - 0.12 * r * math.cos(t)

            gap = False
            if k >= 3 and ((k * 37 + s) % 59) < 4:
                gap = True
            if k <= 4 and (math.pi * 0.35 < t < math.pi * 0.65):
                gap = True

            if inside_oval(x, y) and not gap:
                pts.append((x, y))
            else:
                if len(pts) >= 2:
                    for p1, p2 in zip(pts[:-1], pts[1:]):
                        lines.append(
                            f'  (gr_line (start {p1[0]:.3f} {p1[1]:.3f}) '
                            f'(end {p2[0]:.3f} {p2[1]:.3f}) '
                            f'(stroke (width {ridge_w:.2f}) (type solid)) '
                            f'(layer "F.Mask") (uuid "{uid()}"))'
                        )
                pts = []
        if len(pts) >= 2:
            for p1, p2 in zip(pts[:-1], pts[1:]):
                lines.append(
                    f'  (gr_line (start {p1[0]:.3f} {p1[1]:.3f}) '
                    f'(end {p2[0]:.3f} {p2[1]:.3f}) '
                    f'(stroke (width {ridge_w:.2f}) (type solid)) '
                    f'(layer "F.Mask") (uuid "{uid()}"))'
                )
    return "\n".join(lines)


def generate_top_silkscreen():
    """
    Outward-face (F.SilkS) white minimalist icons:
      - Two symmetric upward-pointing arrows flanking the ENIG gold thumbprint (x=4.30 & x=25.70)
      - Two Ø2.70 mm rings around the bottom 0.60 mm holes (MK1 at 11.25,42.5 & D2 at 18.75,42.5)
      - 0.90x Unlock (left) & Lock (right) vector padlocks centered above each ring (y=39.45, 0.62 mm gap)
    """
    elems = []

    def gl(x1, y1, x2, y2, w=0.20):
        return (
            f'  (gr_line (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) '
            f'(stroke (width {w:.2f}) (type solid)) (layer "F.SilkS") (uuid "{uid()}"))'
        )

    def ga(cx, cy, r, a0_deg, a1_deg, steps=16, w=0.17):
        pts = [
            (cx + r * math.cos(math.radians(a0_deg + (a1_deg - a0_deg) * i / steps)),
             cy + r * math.sin(math.radians(a0_deg + (a1_deg - a0_deg) * i / steps)))
            for i in range(steps + 1)
        ]
        return [gl(p1[0], p1[1], p2[0], p2[1], w=w) for p1, p2 in zip(pts[:-1], pts[1:])]

    def gc(cx, cy, r, w=0.20):
        return (
            f'  (gr_circle (center {cx:.3f} {cy:.3f}) (end {cx + r:.3f} {cy:.3f}) '
            f'(stroke (width {w:.2f}) (type solid)) (fill none) (layer "F.SilkS") (uuid "{uid()}"))'
        )

    # 1. Two symmetric upward-pointing arrows flanking the thumbprint
    for ax in (4.30, 25.70):
        y_bot, y_top = 27.60, 21.40
        aw, ah = 1.35, 1.45
        elems.append(gl(ax, y_bot, ax, y_top, w=0.24))
        elems.append(gl(ax - aw, y_top + ah, ax, y_top, w=0.24))
        elems.append(gl(ax + aw, y_top + ah, ax, y_top, w=0.24))

    # 2. Circles around both bottom holes: MK1 (11.25, 42.5) & D2 (18.75, 42.5)
    for hx in (11.25, 18.75):
        elems.append(gc(hx, 42.50, 1.35, w=0.20))

    # 3. Padlock icons (0.90x scale) centered above each circle at (hx, 39.45)
    S = 0.90
    CY_REF = 45.55
    CY_NEW = 42.50 - 3.05  # 39.45 mm (exact 0.62 mm gap above Ø2.70 mm ring top)

    def sy(y):
        return CY_NEW + (y - CY_REF) * S

    def add_body(cx):
        hw = 0.95 * S
        y_top, y_bot = sy(45.35), sy(46.75)
        elems.append(gl(cx - hw, y_top, cx + hw, y_top, w=0.17))
        elems.append(gl(cx + hw, y_top, cx + hw, y_bot, w=0.17))
        elems.append(gl(cx + hw, y_bot, cx - hw, y_bot, w=0.17))
        elems.append(gl(cx - hw, y_bot, cx - hw, y_top, w=0.17))
        elems.append(gl(cx, sy(45.90), cx, sy(46.22), w=0.20))

    sr = 0.55 * S
    # Left: UNLOCKED (cx = 11.25)
    cx_u = 11.25
    add_body(cx_u)
    elems.append(gl(cx_u - sr, sy(45.35), cx_u - sr, sy(44.70), w=0.17))
    elems.extend(ga(cx_u, sy(44.70), sr, 180.0, 340.0, steps=16, w=0.17))

    # Right: LOCKED (cx = 18.75)
    cx_l = 18.75
    add_body(cx_l)
    elems.append(gl(cx_l - sr, sy(45.35), cx_l - sr, sy(44.90), w=0.17))
    elems.extend(ga(cx_l, sy(44.90), sr, 180.0, 360.0, steps=16, w=0.17))
    elems.append(gl(cx_l + sr, sy(44.90), cx_l + sr, sy(45.35), w=0.17))

    return "\n".join(elems)


# ==============================================================================
# 4. MPN LOOKUP (1:1 MATCH WITH build_pocket_recorder_sch.py & BOM)
# ==============================================================================
MPN_MAP = {
    "U1": "STM32U595RJT6Q",
    "MK1": "MMICT5837-00-012",
    "U2": "RV-3032-C7-32.768KHZ-2.5PPM-TA-QC",
    "U3": "BQ25185DLHR",
    "U4": "TPS62840DLCR",
    "U5": "TLV75530PDBVR",
    "U6": "AP2112K-3.3TRG1",
    "U7": "TXS02612RTWR",
    "D1": "USBLC6-2SC6Y",
    "D2": "XZMDKCBDDG45S-9",
    "J1": "DM3D-SF",
    "Y1": "CX3225SB16000D0FLJCC",
    "L1": "DFE201610E-2R2M=P2",
    "L2": "DFE201610E-2R2M=P2",
    "R1": "RC0603FR-071KL",
    "R2": "RC0603FR-071KL",
    "R3": "RC0603FR-072K2L",
    "R4": "RC0603FR-071K2L",
    "R5": "RC0603FR-0718KL",
    "R6": "RC0603FR-0710KL",
    "R7": "RC0603FR-0710KL",
    "R8": "RC0603FR-0710KL",
    "R9": "RC0603FR-0710KL",
    "R10": "RC0603FR-0710KL",
    "R11": "RC0603FR-0710KL",
    "R12": "RC0603FR-0747KL",
    "R13": "RC0603FR-07100KL",
    "R14": "RC0603FR-07100KL",
    "R15": "RC0603FR-07100KL",
    "R16": "RC0603FR-07220KL",
    "C1": "CL10A106KP8NNNC",
    "C2": "CL10A106KP8NNNC",
    "C3": "CL10A106KP8NNNC",
    "C4": "CL10A475KP8NNNC",
    "C5": "CL10A475KP8NNNC",
    "C6": "CL10A225KP8NNNC",
    "C7": "CL10A225KP8NNNC",
    "C8": "CL10A105KB8NNNC",
    "C9": "CL10A105KB8NNNC",
    "C10": "CL10A105KB8NNNC",
    "C11": "CL10A105KB8NNNC",
    "C12": "CL10A105KB8NNNC",
    "C13": "CL10B104KB8NNNC",
    "C14": "CL10B104KB8NNNC",
    "C15": "CL10B104KB8NNNC",
    "C16": "CL10B104KB8NNNC",
    "C17": "CL10B104KB8NNNC",
    "C18": "CL10B104KB8NNNC",
    "C19": "CL10B104KB8NNNC",
    "C20": "CL10B104KB8NNNC",
    "C21": "CL10B104KB8NNNC",
    "C22": "CL10B104KB8NNNC",
    "C23": "CL10B104KB8NNNC",
    "C24": "CL10B104KB8NNNC",
    "C25": "CL10B104KB8NNNC",
    "C26": "CL10B104KB8NNNC",
    "C27": "CL10B103KB8NNNC",
    "C28": "CL10C120JB8NNNC",
    "C29": "CL10C120JB8NNNC",
    "TP_GND": "ENIG_3x3mm",
    "TP_DP": "ENIG_3x3mm",
    "TP_DM": "ENIG_3x3mm",
    "TP_5V": "ENIG_3x3mm",
    "TP_SWDIO": "ENIG_3x3mm",
    "TP_NRST": "ENIG_3x3mm",
    "TP_SWCLK": "ENIG_3x3mm",
    "J_BAT": "SOLDER_PADS",
    "J_DBG": "BENCH_PADS",
}


# ==============================================================================
# 5. FOOTPRINT BUILDERS (PARTS SIDE = B.Cu PROPERLY MIRRORED, OUTWARD = F.Cu)
#    All B.Cu footprints mirror Y (y -> -y vs top-view) so physical parts
#    placed on the bottom side have standard CCW pin numbering, and every pad
#    carries the footprint's absolute rotation angle (at px py rot).
# ==============================================================================
def model_block_for_ref(ref):
    """Attach standard KiCad 3D STEP model for realistic 3D board rendering."""
    # (relative_path, offset_xyz, scale_xyz, rotate_xyz)
    MODEL_MAP = {
        "U1":  ("Package_QFP.3dshapes/LQFP-64_10x10mm_P0.5mm.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "U2":  ("Crystal.3dshapes/Crystal_SMD_MicroCrystal_CC7V-T1A-2Pin_3.2x1.5mm.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "U3":  ("Package_DFN_QFN.3dshapes/Texas_DLH0010A_WSON-10-1EP_2.2x2mm_P0.4mm_EP0.9x1.5mm.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "U4":  ("Package_DFN_QFN.3dshapes/DFN-8-1EP_2x2mm_P0.5mm_EP0.6x1.2mm.step", (0, 0, 0), (0.75, 1.0, 1.0), (0, 0, 0)),
        "U5":  ("Package_TO_SOT_SMD.3dshapes/SOT-23-5.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "U6":  ("Package_TO_SOT_SMD.3dshapes/SOT-23-5.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "U7":  ("Package_DFN_QFN.3dshapes/QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "D1":  ("Package_TO_SOT_SMD.3dshapes/SOT-23-6.step", (0, 0, 0), (1, 1, 1), (0, 0, 90)),
        "D2":  ("LED_SMD.3dshapes/LED_RGB_Wuerth-PLCC4_3.2x2.8mm_150141M173100.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "J1":  ("Connector_Card.3dshapes/microSD_HC_Hirose_DM3D-SF.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "MK1": ("Sensor_Audio.3dshapes/InvenSense_ICS-43434-6_3.5x2.65mm.step", (0.71, 0, 0), (1, 1, 1), (0, 0, 90)),
        "Y1":  ("Crystal.3dshapes/Crystal_SMD_3225-4Pin_3.2x2.5mm.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "L1":  ("Inductor_SMD.3dshapes/L_Murata_DFE201610P.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
        "L2":  ("Inductor_SMD.3dshapes/L_Murata_DFE201610P.step", (0, 0, 0), (1, 1, 1), (0, 0, 0)),
    }
    if ref in MODEL_MAP:
        rel, off, scl, rot = MODEL_MAP[ref]
    elif ref.startswith("R") and ref[1:].isdigit():
        rel, off, scl, rot = ("Resistor_SMD.3dshapes/R_0603_1608Metric.step", (0, 0, 0), (1, 1, 1), (0, 0, 0))
    elif ref.startswith("C") and ref[1:].isdigit():
        rel, off, scl, rot = ("Capacitor_SMD.3dshapes/C_0603_1608Metric.step", (0, 0, 0), (1, 1, 1), (0, 0, 0))
    else:
        return ""
    return (
        f'    (model "${{KICAD10_3DMODEL_DIR}}/{rel}"\n'
        f'      (offset (xyz {off[0]} {off[1]} {off[2]}))\n'
        f'      (scale (xyz {scl[0]} {scl[1]} {scl[2]}))\n'
        f'      (rotate (xyz {rot[0]} {rot[1]} {rot[2]}))\n'
        f'    )'
    )


def fp_wrapper(
    lib_name, ref, val, x, y, rot, layer, pads_str, extras="",
    ref_xy=(0.0, 0.0), hide_ref=None,
):
    silk = "B.SilkS" if layer == "B.Cu" else "F.SilkS"
    if hide_ref is None:
        hide_ref = (layer == "F.Cu")
    hide_s = " (hide yes)" if hide_ref else ""
    mpn = MPN_MAP.get(ref, "")
    rx, ry = ref_xy
    model_s = model_block_for_ref(ref)
    return f"""  (footprint "{lib_name}"
    (layer "{layer}")
    (uuid "{uid()}")
    (at {x:.3f} {y:.3f} {rot})
    (property "Reference" "{ref}" (at {rx:.3f} {ry:.3f} {rot}) (layer "{silk}"){hide_s}
      (effects (font (size 0.8 0.8) (thickness 0.15)) (justify mirror)))
    (property "Value" "{val}" (at 0 0 {rot}) (layer "B.Fab") (hide yes)
      (effects (font (size 0.8 0.8) (thickness 0.15))))
    (property "MPN" "{mpn}" (at 0 0 {rot}) (layer "B.Fab") (hide yes)
      (effects (font (size 0.8 0.8) (thickness 0.15))))
{pads_str}
{extras}
{model_s}
  )"""


def smd_pad(num, px, py, sx, sy, net_name, side="B", rot=0, paste=True, mask_margin=None):
    layers = [f'"{side}.Cu"']
    if paste:
        layers.append(f'"{side}.Paste"')
    layers.append(f'"{side}.Mask"')
    mm = f" (solder_mask_margin {mask_margin:.3f})" if mask_margin is not None else ""
    return (
        f'    (pad "{num}" smd roundrect (at {px:.3f} {py:.3f} {rot}) '
        f'(size {sx:.3f} {sy:.3f}) (layers {" ".join(layers)}) '
        f'(roundrect_rratio 0.12){mm} {net_s(net_name)} (uuid "{uid()}"))'
    )


def fp_0603(ref, val, x, y, rot, n1, n2):
    # Hide B.SilkS RefDes on dense 0603 passives (Fab layer holds assembly labels)
    # so zero silkscreen overlaps pads or board edges.
    pads = "\n".join([
        smd_pad("1", -0.80, 0, 0.90, 0.95, n1, "B", rot=rot),
        smd_pad("2",  0.80, 0, 0.90, 0.95, n2, "B", rot=rot),
    ])
    fab = (
        f'    (fp_rect (start -0.85 -0.45) (end 0.85 0.45) '
        f'(stroke (width 0.10) (type solid)) (layer "B.Fab") (uuid "{uid()}"))'
    )
    return fp_wrapper(
        "Resistor_SMD:R_0603_1608Metric", ref, val, x, y, rot, "B.Cu",
        pads, fab, hide_ref=True,
    )


def fp_lqfp64(ref, val, x, y, rot, pin_nets):
    """
    STM32U5 LQFP64 (10x10 body, 0.50 mm pitch, 0.27 mm pad width for PCBWay black mask dams).
    Mirrored for B.Cu (y negated from F.Cu):
      1..16:  left edge (x=-span),  y=+3.75 .. -3.75
      17..32: top edge  (y=-span),  x=-3.75 .. +3.75
      33..48: right edge(x=+span),  y=-3.75 .. +3.75
      49..64: bot edge  (y=+span),  x=+3.75 .. -3.75
    """
    pads = []
    pitch = 0.50
    span = 5.675
    pw, pl = 0.27, 1.45  # 0.23 mm gap >= 0.22 mm PCBWay black resist requirement
    for i in range(16):
        offset = -3.75 + i * pitch
        pads.append(smd_pad(str(1 + i),  -span, -offset, pl, pw, pin_nets.get(1 + i, ""), "B", rot=rot))
        pads.append(smd_pad(str(17 + i), offset,  -span, pw, pl, pin_nets.get(17 + i, ""), "B", rot=rot))
        pads.append(smd_pad(str(33 + i),  span,  offset, pl, pw, pin_nets.get(33 + i, ""), "B", rot=rot))
        pads.append(smd_pad(str(49 + i), -offset,  span, pw, pl, pin_nets.get(49 + i, ""), "B", rot=rot))
    p1_dot = (
        f'    (fp_circle (center -4.3 4.3) (end -4.0 4.3) '
        f'(stroke (width 0.15) (type solid)) (layer "B.SilkS") (uuid "{uid()}"))'
    )
    return fp_wrapper(
        "Package_QFP:LQFP-64_10x10mm_P0.5mm", ref, val, x, y, rot, "B.Cu",
        "\n".join(pads), p1_dot, ref_xy=(0.0, 0.0), hide_ref=False,
    )


def fp_sot23_5(ref, val, x, y, rot, pnets, hide_ref=True):
    # Mirrored for B.Cu (y negated from F.Cu)
    coords = {1: (-0.95, -1.1), 2: (0.0, -1.1), 3: (0.95, -1.1), 4: (0.95, 1.1), 5: (-0.95, 1.1)}
    pads = "\n".join(smd_pad(str(k), cx, cy, 0.60, 1.05, pnets.get(k, ""), "B", rot=rot) for k, (cx, cy) in coords.items())
    return fp_wrapper("Package_TO_SOT_SMD:SOT-23-5", ref, val, x, y, rot, "B.Cu", pads, hide_ref=hide_ref)


def fp_sot23_6(ref, val, x, y, rot, pnets, hide_ref=True):
    # Mirrored for B.Cu (y negated from F.Cu)
    coords = {1: (-0.95, -1.1), 2: (0.0, -1.1), 3: (0.95, -1.1), 4: (0.95, 1.1), 5: (0.0, 1.1), 6: (-0.95, 1.1)}
    pads = "\n".join(smd_pad(str(k), cx, cy, 0.60, 1.05, pnets.get(k, ""), "B", rot=rot) for k, (cx, cy) in coords.items())
    return fp_wrapper("Package_TO_SOT_SMD:SOT-23-6", ref, val, x, y, rot, "B.Cu", pads, hide_ref=hide_ref)


def fp_wson10(ref, val, x, y, rot, pnets):
    """
    BQ25185DLHR 10-WSON (2.2 x 2.0 mm, 0.40 mm pitch + EP), mirrored for B.Cu.
    Uses TI-recommended 0.20 mm pad width (0.20 mm copper gap) and 0.03 mm mask
    margin (0.14 mm >= 0.127 mm PCBWay matte-black solder mask bridge).
    """
    pads = []
    for i in range(5):
        py = 0.80 - i * 0.40  # Mirrored for B.Cu (pin 1 at bottom-left -> pin 5 top-left)
        pads.append(smd_pad(str(1 + i), -0.95, py, 0.65, 0.20, pnets.get(1 + i, ""), "B", rot=rot, mask_margin=0.03))
        pads.append(smd_pad(str(10 - i), 0.95, py, 0.65, 0.20, pnets.get(10 - i, ""), "B", rot=rot, mask_margin=0.03))
    pads.append(smd_pad("11", 0.0, 0.0, 0.85, 1.55, pnets.get(11, "GND"), "B", rot=rot, mask_margin=0.03))
    return fp_wrapper("Package_SON:WSON-10-1EP_2.2x2mm_P0.4mm", ref, val, x, y, rot, "B.Cu", "\n".join(pads), hide_ref=True)


def fp_vson8_hr(ref, val, x, y, rot, pnets):
    """
    TPS62840DLCR 8-VSON-HR (2.0 x 1.5 mm, 0.50 mm pitch), mirrored for B.Cu.
    0.26 mm pad width -> 0.24 mm copper gap, 0.14 mm >= 0.127 mm black mask dam.
    """
    pads = []
    for i in range(4):
        px = -0.75 + i * 0.50
        pads.append(smd_pad(str(1 + i), px, -0.675, 0.26, 0.55, pnets.get(1 + i, ""), "B", rot=rot))
        pads.append(smd_pad(str(8 - i), px,  0.675, 0.26, 0.55, pnets.get(8 - i, ""), "B", rot=rot))
    return fp_wrapper("Package_SON:Texas_VSON-HR-8_1.5x2mm_P0.5mm", ref, val, x, y, rot, "B.Cu", "\n".join(pads), hide_ref=True)


def fp_wqfn24(ref, val, x, y, rot, pnets):
    """TXS02612RTWR 24-WQFN (4.0 x 4.0 mm, 0.50 mm pitch + EP), mirrored for B.Cu."""
    pads = []
    for i in range(6):
        off = -1.25 + i * 0.50
        pads.append(smd_pad(str(1 + i),  -1.90, -off, 0.75, 0.26, pnets.get(1 + i, ""), "B", rot=rot))
        pads.append(smd_pad(str(7 + i),   off, -1.90, 0.26, 0.75, pnets.get(7 + i, ""), "B", rot=rot))
        pads.append(smd_pad(str(13 + i),  1.90,  off, 0.75, 0.26, pnets.get(13 + i, ""), "B", rot=rot))
        pads.append(smd_pad(str(19 + i), -off,  1.90, 0.26, 0.75, pnets.get(19 + i, ""), "B", rot=rot))
    pads.append(smd_pad("25", 0.0, 0.0, 2.45, 2.45, pnets.get(25, "GND"), "B", rot=rot))
    return fp_wrapper("Package_DFN_QFN:WQFN-24-1EP_4x4mm_P0.5mm", ref, val, x, y, rot, "B.Cu", "\n".join(pads), hide_ref=True)


def fp_rv3032(ref, val, x, y, rot, pnets):
    """Micro Crystal RV-3032-C7 SON-8 (3.2 x 1.5 mm, edge pads), mirrored for B.Cu."""
    coords = {
        1: (-1.35, -0.55), 2: (-0.45, -0.55), 3: (0.45, -0.55), 4: (1.35, -0.55),
        5: ( 1.35,  0.55), 6: ( 0.45,  0.55), 7: (-0.45,  0.55), 8: (-1.35,  0.55),
    }
    pads = "\n".join(smd_pad(str(k), cx, cy, 0.50, 0.60, pnets.get(k, ""), "B", rot=rot) for k, (cx, cy) in coords.items())
    return fp_wrapper("Timer_RTC:MicroCrystal_RV-3032-C7", ref, val, x, y, rot, "B.Cu", pads, hide_ref=True)


def fp_t5837(ref, val, x, y, rot, pnets):
    """
    TDK T5837 / T5838 bottom-port PDM MEMS mic (3.50 x 2.65 mm) aligned so the
    0.60 mm NPTH acoustic port sits at (x, y). Uses a hollow custom annular ring
    pad (ID=1.14 mm -> 0.27 mm >= 0.25 mm hole clearance, OD=1.74 mm) with zero
    solder paste inside the hole.
    """
    hole = (
        f'    (pad "" np_thru_hole circle (at 0 0) (size 0.60 0.60) (drill 0.60) '
        f'(layers "*.Cu" "*.Mask") (uuid "{uid()}"))'
    )
    # Custom hollow annular ring pad matching KiCad Sensor_Audio convention
    ring = (
        f'    (pad "6" smd custom (at 0.720 0.000 {rot}) (size 0.300 0.300) '
        f'(layers "B.Cu" "B.Mask") '
        f'(options (clearance outline) (anchor circle)) '
        f'(primitives (gr_circle (center -0.720 0.000) (end 0.000 0.000) (width 0.300) (fill no))) '
        f'{net_s("GND")} (uuid "{uid()}"))'
    )
    # TDK 3.50 x 2.65 mm pad spacing relative to acoustic port at (0,0), mirrored for B.Cu
    sig_coords = {
        1: (2.070,  0.900),  # VDD
        2: (2.070, -0.900),  # DATA
        3: (1.250, -0.900),  # CLK
        4: (1.250,  0.900),  # SELECT (GND = Left)
        5: (2.070,  0.000),  # GND
    }
    pads = [hole, ring] + [
        smd_pad(str(k), cx, cy, 0.52, 0.58, pnets.get(k, ""), "B", rot=rot)
        for k, (cx, cy) in sig_coords.items()
    ]
    # Segmented paste arcs on B.Paste around acoustic ring (no paste in hole)
    paste_segs = []
    for a0, a1 in [(10, 80), (100, 170), (190, 260), (280, 350)]:
        r_in, r_out = 0.59, 0.84
        pts = []
        for a in range(a0, a1 + 1, 10):
            rad = math.radians(a)
            pts.append(f"(xy {r_out*math.cos(rad):.3f} {r_out*math.sin(rad):.3f})")
        for a in range(a1, a0 - 1, -10):
            rad = math.radians(a)
            pts.append(f"(xy {r_in*math.cos(rad):.3f} {r_in*math.sin(rad):.3f})")
        paste_segs.append(
            f'    (fp_poly (pts {" ".join(pts)}) (stroke (width 0) (type solid)) '
            f'(fill yes) (layer "B.Paste") (uuid "{uid()}"))'
        )
    return fp_wrapper(
        "Audio:TDK_T5837_T5838_BottomPort", ref, val, x, y, rot, "B.Cu",
        "\n".join(pads), "\n".join(paste_segs), hide_ref=True,
    )


def fp_rgb_led(ref, val, x, y, rot, pnets):
    """SunLED XZMDKCBDDG45S-9 reverse-mount RGB LED centered over 0.60 mm NPTH hole, mirrored for B.Cu."""
    hole = (
        f'    (pad "" np_thru_hole circle (at 0 0) (size 0.60 0.60) (drill 0.60) '
        f'(layers "*.Cu" "*.Mask") (uuid "{uid()}"))'
    )
    coords = {1: (-1.40, 0.80), 2: (1.40, 0.80), 3: (1.40, -0.80), 4: (-1.40, -0.80)}
    pads = [hole] + [smd_pad(str(k), cx, cy, 1.00, 0.90, pnets.get(k, ""), "B", rot=rot) for k, (cx, cy) in coords.items()]
    return fp_wrapper("LED_SMD:SunLED_XZMDKCBDDG45S-9_ReverseMount", ref, val, x, y, rot, "B.Cu", "\n".join(pads), hide_ref=True)


def fp_dm3d_sf(ref, val, x, y, rot, pnets):
    """
    Hirose DM3D-SF push-pull microSD socket (1.55 mm height, 11.95 x 11.45 mm body),
    exact KiCad/Hirose pad coordinates mirrored for B.Cu:
      - Pins 1..8 at y = -5.35 (card-entry side on B.Cu), pitch 1.10 mm, x = +3.175..-4.525
      - Seated 15.0 mm microSD card extends from y = +5.725 (back) to y = -10.075 (front)
    """
    pads = []
    for i in range(8):
        px = 3.175 - i * 1.10
        pads.append(smd_pad(str(i + 1), px, -5.35, 0.70, 1.75, pnets.get(i + 1, ""), "B", rot=rot))
    # Card detect switch pads (SW1=pin 9, SW2=pin 10)
    pads.append(smd_pad("SW1", -5.65,  3.875, 1.45, 1.00, pnets.get("SW1", "SD_CD"), "B", rot=rot))
    pads.append(smd_pad("SW2",  5.575, 5.450, 1.00, 1.55, pnets.get("SW2", "GND"),   "B", rot=rot))
    # 4 Shield ground anchor pads
    sh_coords = [
        ("SH1", -5.975,  2.375, 0.80, 1.50),
        ("SH2", -5.775, -5.225, 1.20, 1.50),
        ("SH3",  5.625, -5.225, 1.50, 1.50),
        ("SH4",  5.975,  3.025, 0.80, 1.40),
    ]
    for sh_name, sx, sy, sw, sh in sh_coords:
        pads.append(smd_pad(sh_name, sx, sy, sw, sh, "GND", "B", rot=rot))
    extras = "\n".join([
        f'    (fp_rect (start -6.375 -5.725) (end 6.375 5.725) (stroke (width 0.10) (type solid)) (layer "B.CrtYd") (uuid "{uid()}"))',
        # Seated 15.0 mm microSD card outline on B.Fab (must stay inside [1.0,29.0]x[1.0,47.0])
        f'    (fp_rect (start -5.525 -10.075) (end 5.475 5.725) (stroke (width 0.10) (type dash)) (layer "B.Fab") (uuid "{uid()}"))',
    ])
    return fp_wrapper(
        "Connector_Card:Hirose_DM3D-SF_microSD", ref, val, x, y, rot, "B.Cu",
        "\n".join(pads), extras, ref_xy=(0.0, 0.0), hide_ref=False,
    )


def fp_xtal3225(ref, val, x, y, rot, n1, n3):
    # Mirrored for B.Cu
    pads = "\n".join([
        smd_pad("1", -1.10, -0.80, 1.20, 1.00, n1,    "B", rot=rot),
        smd_pad("2",  1.10, -0.80, 1.20, 1.00, "GND", "B", rot=rot),
        smd_pad("3",  1.10,  0.80, 1.20, 1.00, n3,    "B", rot=rot),
        smd_pad("4", -1.10,  0.80, 1.20, 1.00, "GND", "B", rot=rot),
    ])
    return fp_wrapper("Crystal:Crystal_SMD_3225-4Pin", ref, val, x, y, rot, "B.Cu", pads, hide_ref=True)


def fp_ind2016(ref, val, x, y, rot, n1, n2):
    pads = "\n".join([
        smd_pad("1", -0.75, 0, 0.70, 1.55, n1, "B", rot=rot),
        smd_pad("2",  0.75, 0, 0.70, 1.55, n2, "B", rot=rot),
    ])
    return fp_wrapper("Inductor_SMD:L_2016_Murata_DFE201610E", ref, val, x, y, rot, "B.Cu", pads, hide_ref=True)


def fp_pogo_pad(ref, net_name, x, y):
    """Outward 3.0 x 3.0 mm bare ENIG gold pad (no paste, zero outward silkscreen)."""
    pad = smd_pad("1", 0, 0, 3.00, 3.00, net_name, "F", rot=0, paste=False, mask_margin=0.0)
    return fp_wrapper("Custom:PogoPad_3x3mm_ENIG", ref, net_name, x, y, 0, "F.Cu", pad, hide_ref=True)


def fp_bench_2x4(x, y):
    """Parts-side 2x4 bench debug pad group (X5: 1.8V, GND, SWDIO, SWCLK, NRST, TX, RX, PDM_CLK)."""
    pins = [
        (1, -0.635, -1.905, "+1V8"),    (2, 0.635, -1.905, "GND"),
        (3, -0.635, -0.635, "SWDIO"),   (4, 0.635, -0.635, "SWCLK"),
        (5, -0.635,  0.635, "NRST"),    (6, 0.635,  0.635, "PDM_CLK"),
        (7, -0.635,  1.905, "UART_TX"), (8, 0.635,  1.905, "UART_RX"),
    ]
    pads = "\n".join(smd_pad(str(n), px, py, 0.85, 0.85, net, "B", rot=0, paste=False) for n, px, py, net in pins)
    return fp_wrapper(
        "Custom:BenchDebug_2x4_1.27mm", "J_DBG", "2x4_BENCH", x, y, 0, "B.Cu",
        pads, ref_xy=(0.0, -3.15), hide_ref=False,
    )


def fp_bat_pads(x, y):
    """Hard-wired LiPo cell solder pads (P6: no reverse-polarity protection)."""
    pads = "\n".join([
        smd_pad("1", 0, -1.75, 2.20, 2.80, "VBAT", "B", rot=0, paste=False),
        smd_pad("2", 0,  1.75, 2.20, 2.80, "GND",  "B", rot=0, paste=False),
    ])
    pol = "\n".join([
        f'    (fp_text user "+" (at -1.6 -1.75 0) (layer "B.SilkS") (effects (font (size 0.9 0.9) (thickness 0.16)) (justify mirror)) (uuid "{uid()}"))',
        f'    (fp_text user "-" (at -1.6  1.75 0) (layer "B.SilkS") (effects (font (size 0.9 0.9) (thickness 0.16)) (justify mirror)) (uuid "{uid()}"))',
    ])
    return fp_wrapper("Custom:LiPo_SolderPads_2P", "J_BAT", "LIPO_500MAH", x, y, 0, "B.Cu", pads, pol, hide_ref=True)


# ==============================================================================
# 6. ASSEMBLE COMPLETE 4-LAYER KICAD PCB
# ==============================================================================
STM32_PINS = {
    1: "+1V8", 2: "RTC_INT", 3: "RTC_32K", 5: "HSE_IN", 6: "HSE_OUT", 7: "NRST",
    12: "GND", 13: "+1V8", 14: "VBUS_DET", 15: "VBAT_ADC", 16: "VBAT_EN",
    18: "GND", 19: "+1V8",
    28: "SMPS_LX", 29: "+1V8", 30: "GND", 31: "VDD11", 32: "GND", 33: "+1V8",
    34: "CHG_STAT1", 35: "CHG_STAT2", 36: "LED_B", 37: "LED_R", 38: "LED_G",
    39: "SD_D0_1V8", 40: "SD_D1_1V8", 42: "UART_TX", 43: "UART_RX",
    44: "USB_DM_MCU", 45: "USB_DP_MCU", 46: "SWDIO", 47: "GND", 48: "+3V3_USB",
    49: "SWCLK", 51: "SD_D2_1V8", 52: "SD_D3_1V8", 53: "SD_CLK_1V8", 54: "SD_CMD_1V8",
    55: "PDM_CLK", 56: "PDM_DATA", 57: "SD_PWR_EN", 58: "I2C_SCL", 59: "I2C_SDA",
    60: "BOOT0", 61: "SD_CD", 62: "VDD11", 63: "GND", 64: "+1V8",
}


def build_pcb(extra_routing=""):
    fps = []

    # --- Outward Face 7 Pogo Pads (Option 8C + Item 9 Dog-Bone Tented Vias) ---
    pogo_spec = [
        ("TP_GND",   "GND",     6.0, 3.0,  0.0,  2.1),
        ("TP_DP",    "USB_DP", 12.0, 3.0,  0.8,  2.1),
        ("TP_DM",    "USB_DM", 18.0, 3.0, -0.8,  2.1),
        ("TP_5V",    "VBUS_5V",24.0, 3.0,  0.0,  2.1),
        ("TP_SWDIO", "SWDIO",   9.0, 9.0,  0.0,  2.1),
        ("TP_NRST",  "NRST",   15.0, 9.0,  0.0,  2.1),
        ("TP_SWCLK", "SWCLK",  21.0, 9.0,  0.0,  2.1),
    ]
    dogbones = []
    fcu_keepouts = []
    for ref, net, px, py, dx, dy in pogo_spec:
        fps.append(fp_pogo_pad(ref, net, px, py))
        vx, vy = px + dx, py + dy
        tw = 0.35 if net in ("GND", "VBUS_5V") else 0.20
        dogbones.append(
            f'  (segment (start {px:.3f} {py:.3f}) (end {vx:.3f} {vy:.3f}) '
            f'(width {tw:.2f}) (layer "F.Cu") (net {NET_ID[net]}) (uuid "{uid()}"))'
        )
        dogbones.append(
            f'  (via (at {vx:.3f} {vy:.3f}) (size 0.55) (drill 0.25) '
            f'(layers "F.Cu" "B.Cu") (net {NET_ID[net]}) (uuid "{uid()}"))'
        )
        if net != "GND":
            # >=1.0 mm F.Cu copper-pour keepout around non-GND pogo pads (C5)
            x1, y1, x2, y2 = px - 2.55, py - 2.55, px + 2.55, py + 2.75
            fcu_keepouts.append(f"""  (zone (net 0) (net_name "") (layer "F.Cu") (uuid "{uid()}")
    (keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour not_allowed) (footprints allowed))
    (polygon (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}) (xy {x1:.2f} {y2:.2f})))
  )""")

    # --- Acoustic Vent Ø6.0 mm Keepout on F.Cu (zero copper step/vias around MK1) ---
    # Keep F.Cu GND pour uniform (or flat bare mask) — zero vias inside Ø6.0 mm of MK1.

    # --- Active ICs on Parts Side (B.Cu, properly mirrored, zero collisions) ---
    # U1 at (11.5, 14.4) rot=0:
    #   - TP_SWDIO via (9.0, 11.1) and TP_NRST via (15.0, 11.1) land cleanly inside U1 hollow center!
    #   - TOP: SMPS_LX(28) -> L2 at (9.6, 6.4) (>36 mm from MK1)
    #   - RIGHT: USB_DM(44)/USB_DP(45) -> D1 at (15.0, 5.2)
    #   - LEFT: HSE_IN(5)/HSE_OUT(6) -> Y1 at (3.0, 16.0); RTC -> U2 at (3.4, 22.8)
    #   - BOTTOM: SDMMC -> U7 at (10.2, 26.8) -> J1 at (22.3, 31.5)
    fps.append(fp_lqfp64("U1", "STM32U595RJT6Q", 11.55, 13.95, 0, STM32_PINS))
    fps.append(fp_sot23_6("D1", "USBLC6-2SC6Y", 15.0, 5.2, 0, {
        1: "USB_DP", 2: "GND", 3: "USB_DM", 4: "USB_DM_MCU", 5: "VBUS_5V", 6: "USB_DP_MCU"
    }))
    fps.append(fp_sot23_5("U6", "AP2112K-3.3TRG1", 21.0, 4.4, 0, {
        1: "VBUS_5V", 2: "GND", 3: "VBUS_5V", 5: "+3V3_USB"
    }))
    fps.append(fp_wson10("U3", "BQ25185DLHR", 25.6, 6.4, 0, {
        1: "VSYS", 2: "VBAT", 3: "CHG_STAT2", 4: "GND", 5: "GND",
        6: "BQ_TS", 7: "BQ_ILIM", 8: "BQ_ISET", 9: "CHG_STAT1", 10: "VBUS_5V", 11: "GND"
    }))
    fps.append(fp_vson8_hr("U4", "TPS62840DLCR", 25.05, 11.2, 0, {
        1: "GND", 2: "VSYS", 3: "GND", 4: "VSYS", 5: "GND", 6: "GND", 7: "BUCK_SW", 8: "+1V8"
    }))
    fps.append(fp_ind2016("L1", "2.2uH", 25.0, 13.8, 0, "BUCK_SW", "+1V8"))
    fps.append(fp_ind2016("L2", "2.2uH", 9.6, 6.4, 180, "SMPS_LX", "VDD11"))
    fps.append(fp_xtal3225("Y1", "16MHz", 3.0, 15.5, 90, "HSE_IN", "HSE_OUT"))
    fps.append(fp_rv3032("U2", "RV-3032-C7", 3.4, 22.8, 0, {
        1: "RTC_VBACK", 2: "I2C_SDA", 3: "RTC_INT", 4: "GND",
        5: "GND", 6: "+1V8", 7: "RTC_32K", 8: "I2C_SCL"
    }))
    # U7 placed at (6.45, 29.85) — cleanly outside the F.Mask thumbprint so ALL 1V8/3V pins can drop vias!
    fps.append(fp_wqfn24("U7", "TXS02612RTWR", 6.45, 29.85, 0, {
        1: "SD_D2_1V8", 2: "GND", 3: "SD_D3_1V8", 4: "SD_CMD_1V8", 5: "+1V8",
        6: "SD_D0_1V8", 7: "SD_D1_1V8", 9: "SD_CLK_1V8", 11: "GND",
        16: "SD_D1_3V", 17: "+3V0_SD", 18: "SD_D0_3V", 19: "SD_CLK_3V",
        20: "SD_CMD_3V", 21: "+3V0_SD", 22: "SD_D3_3V", 23: "SD_D2_3V",
        24: "GND", 25: "GND"
    }))
    fps.append(fp_sot23_5("U5", "TLV75530PDBVR", 4.2, 35.6, 0, {
        1: "VSYS", 2: "GND", 3: "SD_PWR_EN", 5: "+3V0_SD"
    }))
    # J1 at (22.3, 31.5) rot=0: seated 15.0 mm card occupies [16.775..27.775, 21.425..37.225]
    # Completely inside [1.0..29.0, 1.0..47.0] and 100% clear of all other parts!
    fps.append(fp_dm3d_sf("J1", "DM3D-SF", 22.3, 31.5, 0, {
        1: "SD_D2_3V", 2: "SD_D3_3V", 3: "SD_CMD_3V", 4: "+3V0_SD",
        5: "SD_CLK_3V", 6: "GND", 7: "SD_D0_3V", 8: "SD_D1_3V",
        "SW1": "SD_CD", "SW2": "GND"
    }))
    fps.append(fp_t5837("MK1", "MMICT5837-00-012", 11.25, 42.5, 0, {
        1: "+1V8", 2: "PDM_DATA", 3: "PDM_CLK", 4: "GND", 5: "GND", 6: "GND"
    }))
    fps.append(fp_rgb_led("D2", "XZMDKCBDDG45S-9", 18.75, 42.5, 0, {
        1: "LED_R_K", 2: "VSYS", 3: "LED_G_K", 4: "LED_B_K"
    }))
    fps.append(fp_bat_pads(27.5, 17.4))
    fps.append(fp_bench_2x4(26.2, 42.5))

    # --- 0603 Passives (Resistors & Capacitors, collision-free, clear of dogbone vias & SD card) ---
    passives = [
        # LED resistors (U2) below J1, above D2
        ("R1", "1k",   16.2, 39.2, 0, "LED_G", "LED_G_K"),
        ("R2", "1k",   19.6, 39.2, 0, "LED_B", "LED_B_K"),
        ("R3", "2.2k", 23.0, 39.2, 0, "LED_R", "LED_R_K"),
        # BQ25185 config (wide open around U3 at 25.6, 6.4)
        ("R4", "1.2k", 24.4,  3.1, 0,  "BQ_ISET", "GND"),
        ("R5", "18k",  27.8,  3.1, 90, "BQ_ILIM", "GND"),
        ("R6", "10k",  28.2,  9.8, 90, "BQ_TS",   "GND"),
        # BOOT0 (right below U1.60 -> 2mm straight drop!), I2C pull-ups, RTC VBACKUP/nINT (tucked left of U7)
        ("R7",  "10k",  9.6, 22.6, 270, "BOOT0",     "GND"),
        ("R8",  "10k",  2.0, 26.0, 90,  "I2C_SCL",   "+1V8"),
        ("R9",  "10k",  3.4, 26.0, 90,  "I2C_SDA",   "+1V8"),
        ("R10", "10k",  2.0, 29.4, 90,  "RTC_VBACK", "GND"),
        ("R11", "10k",  2.0, 32.8, 90,  "RTC_INT",   "+1V8"),
        # VBUS detect divider, VBAT switched divider, SD_PWR_EN pull-down
        ("R12", "47k",  20.5,  7.2, 0, "VBUS_DET",  "GND"),
        ("R13", "100k", 20.5,  9.0, 0, "VBUS_5V",   "VBUS_DET"),
        ("R14", "100k", 21.0, 16.0, 0, "VBAT_ADC",  "VBAT_EN"),
        ("R15", "100k",  7.6, 36.2, 0, "SD_PWR_EN", "GND"),
        ("R16", "220k", 21.0, 17.8, 0, "VBAT",      "VBAT_ADC"),
        # Bulk & Decoupling Capacitors (0603)
        ("C1",  "10uF",  26.2,  8.8, 0,  "VSYS",     "GND"),
        ("C2",  "10uF",  21.6, 13.8, 0,  "+1V8",     "GND"),
        ("C3",  "10uF",  10.8, 35.4, 0,  "+3V0_SD",  "GND"),
        ("C4",  "4.7uF", 23.4,  8.8, 0,  "VSYS",     "GND"),
        ("C5",  "4.7uF",  5.8,  6.8, 0,  "+1V8",     "GND"),
        ("C6",  "2.2uF",  9.6,  4.0, 0,  "VDD11",    "GND"),
        ("C7",  "2.2uF", 11.8, 22.8, 0,  "VDD11",    "GND"),
        ("C8",  "1uF",   24.4,  1.6, 0,  "VBUS_5V",  "GND"),
        ("C9",  "1uF",   24.4, 17.4, 90, "VBAT",     "GND"),
        ("C10", "1uF",   18.0,  2.4, 0,  "VBUS_5V",  "GND"),
        ("C11", "1uF",   21.0,  1.8, 0,  "+3V3_USB", "GND"),
        ("C12", "1uF",    1.9, 36.2, 90, "VSYS",     "GND"),
        ("C13", "100nF", 15.0,  2.4, 0,  "VBUS_5V",  "GND"),
        ("C14", "100nF",  6.0,  2.4, 0,  "+1V8",     "GND"),
        ("C15", "100nF",  6.0,  4.0, 0,  "+1V8",     "GND"),
        ("C16", "100nF",  3.0,  8.8, 0,  "+1V8",     "GND"),
        ("C17", "100nF",  3.0, 10.6, 0,  "NRST",     "GND"),
        ("C18", "100nF", 19.6, 11.4, 90, "+1V8",     "GND"),
        ("C19", "100nF", 14.7, 22.8, 0,  "+1V8",     "GND"),
        ("C20", "100nF", 19.6, 19.6, 0,  "+3V3_USB", "GND"),
        ("C21", "100nF",  3.8, 20.8, 0,  "+1V8",     "GND"),
        ("C22", "100nF",  6.2, 25.4, 0,  "+1V8",     "GND"),
        ("C23", "100nF", 11.0, 32.8, 180, "+3V0_SD", "GND"),
        ("C24", "100nF", 13.8, 35.4, 0,  "+3V0_SD",  "GND"),
        ("C25", "100nF",  6.2, 42.5, 90, "+1V8",     "GND"),
        ("C26", "100nF", 15.4, 42.5, 90, "VSYS",     "GND"),
        ("C27", "10nF",  22.6, 19.6, 0,  "VBAT_ADC", "VBAT_EN"),
        ("C28", "12pF",   1.9, 18.6, 270, "HSE_IN",   "GND"),
        ("C29", "12pF",   3.0, 12.6, 0,  "HSE_OUT",  "GND"),
    ]
    for ref, val, px, py, rot, n1, n2 in passives:
        fps.append(fp_0603(ref, val, px, py, rot, n1, n2))

    nets_block = "\n".join(f'  (net {i} "{n}")' for i, n in enumerate(NETS))

    outline = f"""  (gr_line (start 1.500 0.000) (end 28.500 0.000) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_arc  (start 28.500 0.000) (mid 29.561 0.439) (end 30.000 1.500) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_line (start 30.000 1.500) (end 30.000 46.500) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_arc  (start 30.000 46.500) (mid 29.561 47.561) (end 28.500 48.000) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_line (start 28.500 48.000) (end 1.500 48.000) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_arc  (start 1.500 48.000) (mid 0.439 47.561) (end 0.000 46.500) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_line (start 0.000 46.500) (end 0.000 1.500) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_arc  (start 0.000 1.500) (mid 0.439 0.439) (end 1.500 0.000) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (uuid "{uid()}"))
  (gr_rect (start 1.000 1.000) (end 29.000 47.000) (stroke (width 0.1) (type dash)) (layer "Dwgs.User") (uuid "{uid()}"))
  (gr_circle (center 11.250 42.500) (end 14.250 42.500) (stroke (width 0.1) (type dash)) (layer "Dwgs.User") (uuid "{uid()}"))"""

    zones = f"""  (zone (net {NET_ID["GND"]}) (net_name "GND") (layer "In1.Cu") (uuid "{uid()}")
    (connect_pads (clearance 0.2)) (min_thickness 0.2)
    (fill yes (thermal_gap 0.25) (thermal_bridge_width 0.25))
    (polygon (pts (xy 0.35 0.35) (xy 29.65 0.35) (xy 29.65 47.65) (xy 0.35 47.65)))
  )
  (zone (net {NET_ID["GND"]}) (net_name "GND") (layer "F.Cu") (uuid "{uid()}")
    (connect_pads yes (clearance 0.20)) (min_thickness 0.2)
    (fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))
    (polygon (pts (xy 0.35 0.35) (xy 29.65 0.35) (xy 29.65 47.65) (xy 0.35 47.65)))
  )"""

    thumbprint = generate_thumbprint_fmask()
    top_silk = generate_top_silkscreen()

    return f"""(kicad_pcb
  (version 20240108)
  (generator "pocket_recorder_gen")
  (generator_version "1.1")
  (general (thickness 1.6))
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (1 "In1.Cu" power)
    (2 "In2.Cu" signal)
    (31 "B.Cu" signal)
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user "User.Drawings")
    (44 "Edge.Cuts" user)
    (46 "B.CrtYd" user)
    (47 "F.CrtYd" user)
    (48 "B.Fab" user)
    (49 "F.Fab" user)
  )
  (setup
    (stackup
      (layer "F.SilkS" (type "Top Silk Screen"))
      (layer "F.Paste" (type "Top Solder Paste"))
      (layer "F.Mask" (type "Top Solder Mask") (color "Matte Black") (thickness 0.015))
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "prepreg") (thickness 0.21) (material "FR4") (epsilon_r 4.5))
      (layer "In1.Cu" (type "copper") (thickness 0.018))
      (layer "dielectric 2" (type "core") (thickness 1.065) (material "FR4") (epsilon_r 4.5))
      (layer "In2.Cu" (type "copper") (thickness 0.018))
      (layer "dielectric 3" (type "prepreg") (thickness 0.21) (material "FR4") (epsilon_r 4.5))
      (layer "B.Cu" (type "copper") (thickness 0.035))
      (layer "B.Mask" (type "Bottom Solder Mask") (color "Matte Black") (thickness 0.015))
      (layer "B.Paste" (type "Bottom Solder Paste"))
      (layer "B.SilkS" (type "Bottom Silk Screen"))
      (copper_finish "ENIG")
    )
    (pad_to_mask_clearance 0.05)
    (solder_mask_min_width 0.127)
    (tenting (front yes) (back yes))
  )
{nets_block}
{outline}
{thumbprint}
{top_silk}
{chr(10).join(fps)}
{chr(10).join(dogbones)}
{extra_routing}
{chr(10).join(fcu_keepouts)}
{zones}
)
"""


# ==============================================================================
# 7. BOM CSV + PCBWAY GERBER EXPORT SCRIPT
# ==============================================================================
BOM_ROWS = [
    ("U1", 1, "STM32U595RJT6Q", "STMicroelectronics", "LQFP64", "MCU 4MB USB-HS SMPS (drop-in for U5A5/U585/U575 Q)", "https://www.mouser.com/en/ProductDetail/STMicroelectronics/STM32U595RJT6Q?qs=amGC7iS6iy%2Fnod5kGWzwSQ%3D%3D"),
    ("MK1", 1, "MMICT5837-00-012", "TDK InvenSense", "LGA-6 Bottom Port", "PDM MEMS Mic T5837 (fits T5838)", "https://www.digikey.com/en/products/detail/tdk-invensense/MMICT5837-00-012/16903859"),
    ("U2", 1, "RV-3032-C7-32.768KHZ-2.5PPM-TA-QC", "Micro Crystal", "SON-8", "RTC +/-2.5ppm 32.768kHz CLKOUT", "https://www.digikey.com/en/products/detail/micro-crystal-ag/RV-3032-C7-32-768KHZ-2-5PPM-TA-QC/16273061"),
    ("U3", 1, "BQ25185DLHR", "Texas Instruments", "WSON-10", "Linear Power-Path Charger 250mA", "https://www.digikey.com/en/products/detail/texas-instruments/BQ25185DLHR/21769368"),
    ("U4", 1, "TPS62840DLCR", "Texas Instruments", "VSON-HR-8", "1.8V Always-On Buck 60nA Iq", "https://www.digikey.com/en/products/detail/texas-instruments/TPS62840DLCR/10445071"),
    ("U5", 1, "TLV75530PDBVR", "Texas Instruments", "SOT-23-5", "Switched 3.0V 500mA SD LDO", "https://www.digikey.com/en/products/detail/texas-instruments/TLV75530PDBVR/9356540"),
    ("U6", 1, "AP2112K-3.3TRG1", "Diodes Inc.", "SOT-23-5", "USB-Only 3.3V LDO for VDDUSB", "https://www.digikey.com/en/products/detail/diodes-incorporated/AP2112K-3-3TRG1/4470746"),
    ("U7", 1, "TXS02612RTWR", "Texas Instruments", "WQFN-24", "4-Bit SDMMC Level Translator (Ioff)", "https://www.digikey.com/en/products/detail/texas-instruments/TXS02612RTWR/1965237"),
    ("D1", 1, "USBLC6-2SC6Y", "STMicroelectronics", "SOT-23-6", "USB 2.0 HS ESD Protection", "https://www.digikey.com/en/products/detail/stmicroelectronics/USBLC6-2SC6Y/2819177"),
    ("D2", 1, "XZMDKCBDDG45S-9", "SunLED", "4-PLCC Bottom", "Reverse-Mount RGB LED", "https://www.digikey.com/en/products/detail/sunled/XZMDKCBDDG45S-9/4902045"),
    ("J1", 1, "DM3D-SF", "Hirose", "SMT 1.55mm H", "Push-Pull microSD Socket", "https://www.digikey.com/en/products/detail/hirose-electric-co-ltd/DM3D-SF/1786510"),
    ("Y1", 1, "CX3225SB16000D0FLJCC", "Kyocera AVX", "SMD 3225", "16MHz +/-10ppm 8pF HSE Crystal", "https://www.digikey.com/en/products/detail/kyocera-avx/CX3225SB16000D0FLJCC/6123301"),
    ("L1,L2", 2, "DFE201610E-2R2M=P2", "Murata", "2016 1.0mm H", "2.2uH Shielded Inductor", "https://www.digikey.com/en/products/detail/murata-electronics/DFE201610E-2R2M-P2/7430537"),
    ("R1,R2", 2, "RC0603FR-071KL", "Yageo", "0603", "1k 1% (LED G/B)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-071KL/726843"),
    ("R3", 1, "RC0603FR-072K2L", "Yageo", "0603", "2.2k 1% (LED R)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-072K2L/727016"),
    ("R4", 1, "RC0603FR-071K2L", "Yageo", "0603", "1.2k 1% (BQ25185 ISET 250mA)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-071K2L/726852"),
    ("R5", 1, "RC0603FR-0718KL", "Yageo", "0603", "18k 1% (BQ25185 ILIM/VSET)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-0718KL/726989"),
    ("R6-R11", 6, "RC0603FR-0710KL", "Yageo", "0603", "10k 1% (TS, BOOT0, I2C, RTC)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-0710KL/726880"),
    ("R12", 1, "RC0603FR-0747KL", "Yageo", "0603", "47k 1% (VBUS_DET bot)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-0747KL/727253"),
    ("R13-R15", 3, "RC0603FR-07100KL", "Yageo", "0603", "100k 1% (VBUS top, VBAT bot, SD_EN PD)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-07100KL/726889"),
    ("R16", 1, "RC0603FR-07220KL", "Yageo", "0603", "220k 1% (VBAT sense top)", "https://www.digikey.com/en/products/detail/yageo/RC0603FR-07220KL/727062"),
    ("C1-C3", 3, "CL10A106KP8NNNC", "Samsung", "0603", "10uF 10V X5R", "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10A106KP8NNNC/3886850"),
    ("C4,C5", 2, "CL10A475KP8NNNC", "Samsung", "0603", "4.7uF 10V X5R", "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10A475KP8NNNC/3886702"),
    ("C6,C7", 2, "CL10A225KP8NNNC", "Samsung", "0603", "2.2uF 10V X5R (VDD11)", "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10A225KP8NNNC/3886743"),
    ("C8-C12", 5, "CL10A105KB8NNNC", "Samsung", "0603", "1uF 50V X5R", "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10A105KB8NNNC/3887518"),
    ("C13-C26", 14, "CL10B104KB8NNNC", "Samsung", "0603", "100nF 50V X7R", "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10B104KB8NNNC/3886658"),
    ("C27", 1, "CL10B103KB8NNNC", "Samsung", "0603", "10nF 50V X7R (VBAT ADC)", "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10B103KB8NNNC/3886667"),
    ("C28,C29", 2, "CL10C120JB8NNNC", "Samsung", "0603", "12pF 50V C0G (16MHz HSE)", "https://www.digikey.com/en/products/detail/samsung-electro-mechanics/CL10C120JB8NNNC/3886912"),
]

EXPORT_SH = """#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p gerbers_pcbway
echo "Running KiCad DRC..."
kicad-cli pcb drc --severity-all --output gerbers_pcbway/drc_report.rpt pocket_recorder.kicad_pcb || true
echo "Exporting PCBWay 4-Layer Gerbers (incl. approved F.SilkS icon artwork)..."
kicad-cli pcb export gerbers \\
  --output gerbers_pcbway/ \\
  --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,B.Paste,Edge.Cuts" \\
  --use-drill-file-origin \\
  --subtract-soldermask \\
  --check-zones \\
  pocket_recorder.kicad_pcb
kicad-cli pcb export drill \\
  --output gerbers_pcbway/ \\
  --format excellon \\
  --drill-origin plot \\
  --excellon-units mm \\
  --excellon-separate-th \\
  --generate-map \\
  pocket_recorder.kicad_pcb
rm -f pocket_recorder_pcbway_gerbers.zip
(cd gerbers_pcbway && zip -r ../pocket_recorder_pcbway_gerbers.zip .)
echo "Done -> pocket_recorder_hw/pocket_recorder_pcbway_gerbers.zip"
"""

if __name__ == "__main__":
    import sys, subprocess
    unrouted = "--unrouted" in sys.argv
    cache_path = os.path.join(OUT_DIR, "routing_cache.sexp")
    extra_routing = ""
    if not unrouted and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as cf:
            extra_routing = cf.read()

    with open(os.path.join(OUT_DIR, "pocket_recorder.kicad_pro"), "w", encoding="utf-8") as f:
        json.dump(KICAD_PRO, f, indent=2)

    pcb_path = os.path.join(OUT_DIR, "pocket_recorder.kicad_pcb")
    with open(pcb_path, "w", encoding="utf-8") as f:
        f.write(build_pcb(extra_routing=extra_routing))

    # Auto-fill copper zones when routing_cache.sexp is embedded
    if extra_routing:
        try:
            import pcbnew
            b = pcbnew.LoadBoard(pcb_path)
            pcbnew.ZONE_FILLER(b).Fill(b.Zones())
            b.Save(pcb_path)
        except ImportError:
            for kp in [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\KiCad\9.0\bin\python.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\KiCad\8.0\bin\python.exe"),
                r"C:\Program Files\KiCad\10.0\bin\python.exe",
                r"C:\Program Files\KiCad\9.0\bin\python.exe",
                r"C:\Program Files\KiCad\8.0\bin\python.exe",
            ]:
                if os.path.exists(kp):
                    subprocess.run(
                        [kp, "-c", f"import pcbnew; b=pcbnew.LoadBoard(r'{pcb_path}'); pcbnew.ZONE_FILLER(b).Fill(b.Zones()); b.Save(r'{pcb_path}')"],
                        check=True,
                    )
                    break

    with open(os.path.join(OUT_DIR, "pocket_recorder_bom.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Qty", "MPN", "Manufacturer", "Package", "Description", "Order_Link"])
        w.writerows(BOM_ROWS)

    sh_path = os.path.join(OUT_DIR, "export_pcbway_gerbers.sh")
    with open(sh_path, "w", encoding="utf-8") as f:
        f.write(EXPORT_SH)
    os.chmod(sh_path, os.stat(sh_path).st_mode | stat.S_IEXEC)

    print(f"Generated project files in ./{OUT_DIR}/")
