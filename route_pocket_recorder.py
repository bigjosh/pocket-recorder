#!/usr/bin/env python3
"""
Pocket Recorder 4-Layer PCB Router with PathFinder Negotiated Congestion

Stackup strategy:
  - F.Cu  : Solid GND pour + 7 outward pogo pads & dog-bone stubs ONLY (no signal tracks).
  - In1.Cu: Unbroken solid GND reference plane (no signal tracks).
  - In2.Cu: Primary long-haul power & signal routing layer.
  - B.Cu  : Parts-side local routing, critical high-speed/SMPS loops, and via fanouts.
"""
import heapq
import math
import sys
import uuid
from collections import defaultdict
from pathlib import Path

import numpy as np

WORKSPACE = Path(__file__).resolve().parent
HW_DIR = WORKSPACE / "pocket_recorder_hw"
PCB_PATH = HW_DIR / "pocket_recorder.kicad_pcb"
CACHE_PATH = HW_DIR / "routing_cache.sexp"

BOARD_W = 30.0
BOARD_H = 48.0
RES = 0.10  # 0.10 mm grid (301 x 481)
NX = int(round(BOARD_W / RES)) + 1
NY = int(round(BOARD_H / RES)) + 1

MIC_X, MIC_Y = 11.25, 42.5
VENT_VIA_KEEP_R = 3.45

USB_NETS = {"USB_DP", "USB_DM", "USB_DP_MCU", "USB_DM_MCU"}
POWER_NETS = {"VBUS_5V", "VSYS", "VBAT", "+1V8", "+3V0_SD", "+3V3_USB", "GND", "BUCK_SW", "SMPS_LX"}

VIA_SIZE = 0.45
VIA_DRILL = 0.20
VIA_R = VIA_SIZE / 2.0


def uid():
    return str(uuid.uuid4())


def net_widths(net, fine_pitch=False):
    """Return (w_bcu, w_in2) used consistently for BOTH obstacle checking and drawing."""
    if net in USB_NETS:
        return (0.20, 0.20)
    if net in ("VBUS_5V", "VSYS", "VBAT", "+1V8", "+3V0_SD", "+3V3_USB"):
        return (0.15 if fine_pitch else 0.18, 0.20)
    if net == "VDD11":
        return (0.15, 0.18)
    return (0.145 if fine_pitch else 0.15, 0.15)


def net_clearance(net):
    if net in USB_NETS:
        return 0.15
    if net in POWER_NETS:
        return 0.14
    return 0.135


def gx(x):
    return max(0, min(NX - 1, int(round(x / RES))))


def gy(y):
    return max(0, min(NY - 1, int(round(y / RES))))


def gx_lo(x):
    return max(0, min(NX - 1, int(math.ceil(x / RES - 1e-9))))


def gx_hi(x):
    return max(0, min(NX - 1, int(math.floor(x / RES + 1e-9))))


def gy_lo(y):
    return max(0, min(NY - 1, int(math.ceil(y / RES - 1e-9))))


def gy_hi(y):
    return max(0, min(NY - 1, int(math.floor(y / RES + 1e-9))))


def extract_board_data():
    import pcbnew
    b = pcbnew.LoadBoard(str(PCB_PATH))
    nets = {net.GetNetname(): nid for nid, net in b.GetNetsByNetcode().items()}

    pads = []
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        layer = fp.GetLayerName()
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            pos = p.GetPosition()
            sz = p.GetSize()
            pads.append({
                "ref": ref, "num": p.GetNumber(), "net": p.GetNetname(), "nid": p.GetNetCode(),
                "cx": pos.x / 1e6, "cy": pos.y / 1e6,
                "x1": bb.GetLeft() / 1e6, "y1": bb.GetTop() / 1e6,
                "x2": bb.GetRight() / 1e6, "y2": bb.GetBottom() / 1e6,
                "sx": sz.x / 1e6, "sy": sz.y / 1e6,
                "layer": layer,
                "is_npth": (p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH),
                "drill": p.GetDrillSize().x / 1e6,
            })

    fixed_vias = []
    fixed_segs = []
    for tr in b.GetTracks():
        if isinstance(tr, pcbnew.PCB_VIA):
            pos = tr.GetPosition()
            fixed_vias.append({
                "x": pos.x / 1e6, "y": pos.y / 1e6,
                "size": tr.GetWidth(pcbnew.F_Cu) / 1e6, "drill": tr.GetDrillValue() / 1e6,
                "net": tr.GetNetname(), "nid": tr.GetNetCode(),
            })
        else:
            st, en = tr.GetStart(), tr.GetEnd()
            fixed_segs.append({
                "x1": st.x / 1e6, "y1": st.y / 1e6, "x2": en.x / 1e6, "y2": en.y / 1e6,
                "w": tr.GetWidth() / 1e6, "layer": tr.GetLayerName(),
                "net": tr.GetNetname(), "nid": tr.GetNetCode(),
            })

    fmask_segs = []
    for d in b.GetDrawings():
        if d.GetLayerName() == "F.Mask" and isinstance(d, pcbnew.PCB_SHAPE):
            st, en = d.GetStart(), d.GetEnd()
            fmask_segs.append((st.x / 1e6, st.y / 1e6, en.x / 1e6, en.y / 1e6, d.GetWidth() / 1e6))

    return {
        "nets": nets, "pads": pads, "fixed_vias": fixed_vias,
        "fixed_segs": fixed_segs, "fmask_segs": fmask_segs,
    }


def seg_dist_sq(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0.0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    qx, qy = x1 + t * dx, y1 + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


def poly_length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts[:-1], pts[1:]))


def simplify_polyline(pts):
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        ax, ay = out[-1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        v1x, v1y = bx - ax, by - ay
        v2x, v2y = cx - bx, cy - by
        if abs(v1x * v2y - v1y * v2x) < 1e-6 and (v1x * v2x + v1y * v2y) >= 0:
            continue
        out.append(pts[i])
    out.append(pts[-1])
    return out


class BoardRouter:
    def __init__(self, data):
        self.nets = data["nets"]
        self.pads = data["pads"]
        self.fixed_vias = data["fixed_vias"]
        self.fixed_segs = data["fixed_segs"]
        self.fmask_segs = data["fmask_segs"]

        self.pad_by_ref_num = {}
        self.pads_by_net = defaultdict(list)
        for p in self.pads:
            self.pad_by_ref_num[(p["ref"], p["num"])] = p
            if p["net"]:
                self.pads_by_net[p["net"]].append(p)

        # Locked (critical + GND) vs flexible routed items
        self.locked_segs = []
        self.locked_vias = []
        self.net_segs = defaultdict(list)
        self.net_vias = defaultdict(list)

        self.edge_forbidden = np.zeros((NX, NY), dtype=bool)
        self._build_edge_mask(margin=0.45)

        self.via_edge_forbidden = np.zeros((NX, NY), dtype=bool)
        self._build_via_edge_mask(margin=0.62)

        self.via_hard_forbidden = np.copy(self.via_edge_forbidden)
        self.via_fmask_forbidden = np.zeros((NX, NY), dtype=bool)
        self.via_fmask_penalty = np.zeros((NX, NY), dtype=np.float32)
        self._build_via_static_masks()

        self.bcu_pad_list = [p for p in self.pads if p["layer"] == "B.Cu"]

        # Precompute disk offsets for fast rasterization on 0.10 mm grid
        self._disk_cache = {}

    def _disk_offsets(self, r_mm):
        key = int(round(r_mm * 1000))
        if key not in self._disk_cache:
            rc = int(math.ceil(r_mm / RES))
            pts = []
            r2 = (r_mm + 1e-6) ** 2
            for dx in range(-rc, rc + 1):
                for dy in range(-rc, rc + 1):
                    if (dx * RES) ** 2 + (dy * RES) ** 2 <= r2:
                        pts.append((dx, dy))
            self._disk_cache[key] = pts
        return self._disk_cache[key]

    def _build_edge_mask(self, margin):
        xs = np.arange(NX) * RES
        ys = np.arange(NY) * RES
        XX, YY = np.meshgrid(xs, ys, indexing="ij")
        bad = (XX < margin) | (XX > BOARD_W - margin) | (YY < margin) | (YY > BOARD_H - margin)
        r_allow = 1.5 - margin
        for cx, cy in [(1.5, 1.5), (28.5, 1.5), (28.5, 46.5), (1.5, 46.5)]:
            in_corner_quad = (
                ((XX < 1.5) if cx < 15 else (XX > 28.5))
                & ((YY < 1.5) if cy < 24 else (YY > 46.5))
            )
            bad |= in_corner_quad & (((XX - cx) ** 2 + (YY - cy) ** 2) > r_allow ** 2)
        self.edge_forbidden = bad

    def _build_via_edge_mask(self, margin):
        xs = np.arange(NX) * RES
        ys = np.arange(NY) * RES
        XX, YY = np.meshgrid(xs, ys, indexing="ij")
        bad = (XX < margin) | (XX > BOARD_W - margin) | (YY < margin) | (YY > BOARD_H - margin)
        r_allow = 1.5 - margin
        for cx, cy in [(1.5, 1.5), (28.5, 1.5), (28.5, 46.5), (1.5, 46.5)]:
            in_corner_quad = (
                ((XX < 1.5) if cx < 15 else (XX > 28.5))
                & ((YY < 1.5) if cy < 24 else (YY > 46.5))
            )
            bad |= in_corner_quad & (((XX - cx) ** 2 + (YY - cy) ** 2) > r_allow ** 2)
        self.via_edge_forbidden = bad

    def _build_via_static_masks(self):
        xs = np.arange(NX) * RES
        ys = np.arange(NY) * RES
        XX, YY = np.meshgrid(xs, ys, indexing="ij")

        # 1. MK1 Ø6.0 mm acoustic vent keepout
        self.via_hard_forbidden |= ((XX - MIC_X) ** 2 + (YY - MIC_Y) ** 2) <= VENT_VIA_KEEP_R ** 2

        # 2. All NPTH holes
        for p in self.pads:
            if p["is_npth"]:
                r_keep = p["drill"] / 2.0 + 0.28 + VIA_R
                self.via_hard_forbidden |= ((XX - p["cx"]) ** 2 + (YY - p["cy"]) ** 2) <= r_keep ** 2

        # 3. Outward F.Cu pogo pads
        for p in self.pads:
            if p["layer"] == "F.Cu":
                pad_m = VIA_R + 0.28
                self.via_hard_forbidden |= (
                    (XX >= p["x1"] - pad_m) & (XX <= p["x2"] + pad_m)
                    & (YY >= p["y1"] - pad_m) & (YY <= p["y2"] + pad_m)
                )

        # 4. Fixed F.Cu dogbones & vias
        for s in self.fixed_segs:
            if s["layer"] == "F.Cu":
                r_keep = s["w"] / 2.0 + VIA_R + 0.24
                r2 = r_keep * r_keep
                for ix in range(gx_lo(min(s["x1"], s["x2"]) - r_keep), gx_hi(max(s["x1"], s["x2"]) + r_keep) + 1):
                    px = ix * RES
                    for iy in range(gy_lo(min(s["y1"], s["y2"]) - r_keep), gy_hi(max(s["y1"], s["y2"]) + r_keep) + 1):
                        if seg_dist_sq(px, iy * RES, s["x1"], s["y1"], s["x2"], s["y2"]) <= r2:
                            self.via_hard_forbidden[ix, iy] = True

        for v in self.fixed_vias:
            r_keep = max(v["size"] / 2.0 + VIA_R + 0.22, v["drill"] / 2.0 + VIA_DRILL / 2.0 + 0.28)
            self.via_hard_forbidden |= ((XX - v["x"]) ** 2 + (YY - v["y"]) ** 2) <= r_keep ** 2

        # 5. HARD forbid non-GND vias from touching F.Mask thumbprint gold ridges (prevents front solder_mask_bridge!)
        for x1, y1, x2, y2, w in self.fmask_segs:
            r_m = w / 2.0 + VIA_R + 0.16
            r2 = r_m * r_m
            for ix in range(gx_lo(min(x1, x2) - r_m), gx_hi(max(x1, x2) + r_m) + 1):
                px = ix * RES
                for iy in range(gy_lo(min(y1, y2) - r_m), gy_hi(max(y1, y2) + r_m) + 1):
                    if seg_dist_sq(px, iy * RES, x1, y1, x2, y2) <= r2:
                        self.via_fmask_forbidden[ix, iy] = True
                        self.via_fmask_penalty[ix, iy] = 30.0

    def all_segs(self):
        out = list(self.locked_segs)
        for segs in self.net_segs.values():
            out.extend(segs)
        return out

    def all_vias(self):
        out = list(self.locked_vias)
        for vias in self.net_vias.values():
            out.extend(vias)
        return out

    def add_locked_poly(self, net, layer, width, pts):
        pts = simplify_polyline(pts)
        for a, b in zip(pts[:-1], pts[1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) >= 1e-4:
                self.locked_segs.append((net, layer, width, round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)))

    def add_locked_via(self, net, x, y, size=VIA_SIZE, drill=VIA_DRILL):
        self.locked_vias.append((net, round(x, 3), round(y, 3), size, drill))

    # ==========================================================================
    # STAGE A: HAND-CRAFTED CRITICAL NETS (USB 90R, BUCK_SW, SMPS_LX, HSE, MK1)
    # ==========================================================================
    def route_critical_nets(self):
        p = self.pad_by_ref_num

        # 1. USB_DP & USB_DM (TP_DP/DM vias -> D1.1 / D1.3) — exact 0.000 mm skew!
        d1_1 = (p[("D1", "1")]["cx"], p[("D1", "1")]["cy"])
        d1_3 = (p[("D1", "3")]["cx"], p[("D1", "3")]["cy"])
        dp_in = [(12.8, 5.1), (13.8, d1_1[1]), d1_1]
        dm_in = [(17.2, 5.1), (16.2, d1_3[1]), d1_3]
        self.add_locked_poly("USB_DP", "B.Cu", 0.20, dp_in)
        self.add_locked_poly("USB_DM", "B.Cu", 0.20, dm_in)

        # 2. USB_DP_MCU & USB_DM_MCU (D1.6/D1.4 -> U1.45/U1.44)
        #    Both drop cleanly to In2.Cu right beside D1 (2 matched vias each, zero F.Mask hits,
        #    non-crossing 0.15 mm coupled differential pair over solid In1.Cu GND, <= 19.85 mm!).
        d1_6 = (p[("D1", "6")]["cx"], p[("D1", "6")]["cy"])
        d1_4 = (p[("D1", "4")]["cx"], p[("D1", "4")]["cy"])
        u1_45 = (p[("U1", "45")]["cx"], p[("U1", "45")]["cy"])
        u1_44 = (p[("U1", "44")]["cx"], p[("U1", "44")]["cy"])

        # Symmetric D1 -> In2.Cu via drop (both verified vhard=False, fmask=False!)
        dp_b1 = [d1_6, (13.40, 5.60)]
        dm_b1 = [d1_4, (16.60, 5.60)]

        # In2.Cu coupled differential run (diag offset 0.50 -> gap 0.1536 mm; vertical gap 0.150 mm!)
        # Zero crossing: DP (left) jogs cleanly past DM_v2 (19.20, 15.60) at x=18.65 (0.55 mm center-to-center)
        # and exits at (18.90, 16.20) -> U1.45; DM (right) exits at (19.20, 15.60) -> U1.44!
        dp_in2 = [
            (13.40, 5.60), (15.80, 8.00), (18.85, 11.05), (18.85, 14.95),
            (18.65, 15.15), (18.65, 15.95), (18.90, 16.20),
        ]
        dp_b2 = [(18.90, 16.20), u1_45]

        dm_in2 = [(16.60, 5.60), (16.60, 8.30), (19.20, 10.90), (19.20, 15.60)]
        dm_b2 = [(19.20, 15.60), (19.10, u1_44[1]), u1_44]

        # Exact length match on In2.Cu (smooth trombone bump on DM around y=12.4..14.8, clear of TP_SWCLK!)
        dog_len = math.hypot(0.8, 2.1)
        l_dp0 = dog_len + poly_length(dp_in) + poly_length(dp_b1) + poly_length(dp_in2) + poly_length(dp_b2)
        l_dm0 = dog_len + poly_length(dm_in) + poly_length(dm_b1) + poly_length(dm_in2) + poly_length(dm_b2)
        if l_dp0 > l_dm0 + 0.05:
            dx = round((l_dp0 - l_dm0) / 2.0, 3)
            dm_in2 = [
                (16.60, 5.60), (16.60, 8.30), (19.20, 10.90), (19.20, 12.40),
                (19.20 + dx, 12.40), (19.20 + dx, 14.80), (19.20, 14.80), (19.20, 15.60),
            ]

        self.add_locked_poly("USB_DP_MCU", "B.Cu",   0.20, dp_b1)
        self.add_locked_via("USB_DP_MCU", 13.40, 5.60)
        self.add_locked_poly("USB_DP_MCU", "In2.Cu", 0.20, dp_in2)
        self.add_locked_via("USB_DP_MCU", 18.90, 16.20)
        self.add_locked_poly("USB_DP_MCU", "B.Cu",   0.20, dp_b2)

        self.add_locked_poly("USB_DM_MCU", "B.Cu",   0.20, dm_b1)
        self.add_locked_via("USB_DM_MCU", 16.60, 5.60)
        self.add_locked_poly("USB_DM_MCU", "In2.Cu", 0.20, dm_in2)
        self.add_locked_via("USB_DM_MCU", 19.20, 15.60)
        self.add_locked_poly("USB_DM_MCU", "B.Cu",   0.20, dm_b2)

        len_dp = dog_len + poly_length(dp_in) + poly_length(dp_b1) + poly_length(dp_in2) + poly_length(dp_b2)
        len_dm = dog_len + poly_length(dm_in) + poly_length(dm_b1) + poly_length(dm_in2) + poly_length(dm_b2)
        print(f"[crit] USB_DP total={len_dp:.2f} mm, USB_DM total={len_dm:.2f} mm, skew={abs(len_dp-len_dm):.3f} mm", flush=True)

        # 3. BUCK_SW (U4.7 -> L1.1) — ultra-short 0.28 mm wide switch node
        u4_7 = (p[("U4", "7")]["cx"], p[("U4", "7")]["cy"])
        l1_1 = (p[("L1", "1")]["cx"], p[("L1", "1")]["cy"])
        self.add_locked_poly("BUCK_SW", "B.Cu", 0.28, [u4_7, (u4_7[0], 12.80), (l1_1[0], 13.35), l1_1])

        # 4. SMPS_LX (U1.28 -> L2.1) — stays cleanly left of DP_MCU (x <= 13.30)!
        u1_28 = (p[("U1", "28")]["cx"], p[("U1", "28")]["cy"])  # (13.30, 8.275)
        l2_1 = (p[("L2", "1")]["cx"], p[("L2", "1")]["cy"])    # (10.35, 6.40)
        self.add_locked_poly("SMPS_LX", "B.Cu", 0.20, [u1_28, (u1_28[0], 7.40), (12.30, 6.40), l2_1])

        # 5. HSE_IN & HSE_OUT (16 MHz crystal Y1 at (3.0, 15.5) rot=90)
        u1_5 = (p[("U1", "5")]["cx"], p[("U1", "5")]["cy"])
        u1_6 = (p[("U1", "6")]["cx"], p[("U1", "6")]["cy"])
        y1_1 = (p[("Y1", "1")]["cx"], p[("Y1", "1")]["cy"])
        y1_3 = (p[("Y1", "3")]["cx"], p[("Y1", "3")]["cy"])
        c28_1 = (p[("C28", "1")]["cx"], p[("C28", "1")]["cy"])
        c29_1 = (p[("C29", "1")]["cx"], p[("C29", "1")]["cy"])

        # HSE_IN: U1.5 -> open center of Y1 (y=15.50) -> Y1.1 -> C28.1
        self.add_locked_poly("HSE_IN", "B.Cu", 0.16, [u1_5, (4.90, u1_5[1]), (4.20, 15.50), (2.20, 15.50), y1_1, (1.90, 16.90), c28_1])
        # HSE_OUT: U1.6 -> Y1.3 -> cleanly between Y1.2 (y<=13.80) and C29.2 (y>=13.075) via y=13.45 -> C29.1!
        self.add_locked_poly("HSE_OUT", "B.Cu", 0.16, [u1_6, (4.90, u1_6[1]), (3.80, 14.60), y1_3])
        self.add_locked_poly("HSE_OUT", "B.Cu", 0.16, [y1_3, (3.80, 13.55), (3.00, 13.55), (2.20, 12.75), c29_1])

        # 6. MK1 acoustic-vent-safe B.Cu fanouts (orthogonal GND ties clear of MK1.1 +1V8!)
        self.add_locked_poly("GND", "B.Cu", 0.22, [(13.32, 42.50), (11.97, 42.50)])
        self.add_locked_poly("GND", "B.Cu", 0.22, [(11.25, 43.22), (11.25, 46.20)])
        self.add_locked_via("GND", 11.25, 46.20)
        self.add_locked_poly("GND", "B.Cu", 0.20, [(11.25, 43.22), (11.80, 43.40), (12.50, 43.40)])

        self.add_locked_poly("PDM_DATA", "B.Cu", 0.16, [(13.32, 41.60), (13.32, 39.30)])
        self.add_locked_poly("PDM_CLK",  "B.Cu", 0.16, [(12.50, 41.60), (12.50, 39.30)])
        self.add_locked_poly("+1V8",     "B.Cu", 0.20, [(13.32, 43.40), (14.40, 44.48), (14.40, 44.80)])

    # ==========================================================================
    # STAGE B: CLEAN GND FANOUT (ONLY OBVIOUS EP/TIGHT CONNECTIONS FIRST)
    # ==========================================================================
    def init_gnd_anchors(self):
        """Tie IC exposed-pad GND pins & obvious local GND pairs; leave tricky pads for A* GND drop."""
        p = self.pad_by_ref_num
        self.gnd_done = {("MK1", "4"), ("MK1", "5"), ("MK1", "6")}

        # Centered thermal vias in U3.11 & U7.25 exposed pads
        for ref, pn in [("U3", "11"), ("U7", "25")]:
            pad = p[(ref, pn)]
            self.add_locked_via("GND", pad["cx"], pad["cy"])
            self.gnd_done.add((ref, pn))

        # U3.4 & U3.5 -> orthogonal into U3.11
        u3_ep = p[("U3", "11")]
        for pn in ("4", "5"):
            pad = p[("U3", pn)]
            self.add_locked_poly("GND", "B.Cu", 0.16, [(pad["cx"], pad["cy"]), (u3_ep["cx"], pad["cy"])])
            self.gnd_done.add(("U3", pn))

        # U7.2, U7.11, U7.24 -> orthogonal into U7.25
        u7_ep = p[("U7", "25")]
        self.add_locked_poly("GND", "B.Cu", 0.18, [(p[("U7", "2")]["cx"], p[("U7", "2")]["cy"]), (u7_ep["cx"], p[("U7", "2")]["cy"])])
        self.add_locked_poly("GND", "B.Cu", 0.18, [(p[("U7", "11")]["cx"], p[("U7", "11")]["cy"]), (p[("U7", "11")]["cx"], u7_ep["cy"])])
        self.add_locked_poly("GND", "B.Cu", 0.18, [(p[("U7", "24")]["cx"], p[("U7", "24")]["cy"]), (p[("U7", "24")]["cx"], u7_ep["cy"])])
        self.gnd_done.update({("U7", "2"), ("U7", "11"), ("U7", "24")})

        # U4.3, U4.5, U4.6 -> orthogonal tie
        self.add_locked_poly("GND", "B.Cu", 0.18, [
            (p[("U4", "3")]["cx"], p[("U4", "3")]["cy"]),
            (p[("U4", "6")]["cx"], p[("U4", "6")]["cy"]),
            (p[("U4", "5")]["cx"], p[("U4", "5")]["cy"]),
        ])
        self.gnd_done.update({("U4", "3"), ("U4", "6")})

        # U2.4 & U2.5 -> adjacent tie
        self.add_locked_poly("GND", "B.Cu", 0.20, [
            (p[("U2", "4")]["cx"], p[("U2", "4")]["cy"]),
            (p[("U2", "5")]["cx"], p[("U2", "5")]["cy"]),
        ])
        self.gnd_done.add(("U2", "5"))

        # U1 VSS pads -> fan INWARD cleanly to y=12.10 (below TP_SWDIO/TP_NRST pads & dogbone vias,
        # AND above F.Mask thumbprint at y=15.26!) leaving U1.31 (VDD11) and all outer corridors open!
        # U1.18 (8.30, 8.775) -> (8.30, 12.10)
        # U1.30 (14.30, 8.775) -> (14.30, 12.10)
        # U1.32 (15.30, 8.775) -> go down-right to (15.70, 12.10) so U1.31 (14.80) stays wide open!
        # U1.12 (5.875, 12.70) -> (7.30, 12.70)
        # U1.47 (17.225, 17.70) -> let A* GND fanout place clean via outside F.Mask!
        # U1.63 (8.30, 20.125) -> let A* GND fanout place clean via outside F.Mask!
        # U1 VSS pads -> exit STRAIGHT INWARD past pad row first (zero clipping of adjacent U1.29 +1V8!),
        # then drop GND vias at y=11.90 (below TP_SWDIO/TP_NRST pads & vias, above F.Mask thumbprint!).
        u1_inward = {
            "12": [(p[("U1", "12")]["cx"], p[("U1", "12")]["cy"]), (7.30, p[("U1", "12")]["cy"])],
            "18": [(p[("U1", "18")]["cx"], p[("U1", "18")]["cy"]), (8.30, 12.10)],
            "30": [(p[("U1", "30")]["cx"], p[("U1", "30")]["cy"]), (14.30, 9.60), (13.30, 10.60), (13.30, 12.10)],
            # U1.32 goes UP-RIGHT cleanly out of U1 hollow center so pins 33..38 are 100% unblocked!
            "32": [(p[("U1", "32")]["cx"], p[("U1", "32")]["cy"]), (15.30, 7.20), (17.50, 7.20)],
        }
        for pn, pts in u1_inward.items():
            self.add_locked_poly("GND", "B.Cu", 0.16, pts)
            self.add_locked_via("GND", pts[-1][0], pts[-1][1])
            self.gnd_done.add(("U1", pn))

        # Pre-anchor U1.47, J1.6, and C19.2 into clean open spots so they never get boxed in
        pre_gnd = [
            ("U1",    "47", (15.80, p[("U1", "47")]["cy"])),
            ("J1",    "6",  (p[("J1", "6")]["cx"],     p[("J1", "6")]["cy"] + 1.80)),
            ("C19",   "2",  (p[("C19", "2")]["cx"],    p[("C19", "2")]["cy"] - 1.20)),
        ]
        for ref, pn, (vx, vy) in pre_gnd:
            pad = p[(ref, pn)]
            self.add_locked_poly("GND", "B.Cu", 0.18, [(pad["cx"], pad["cy"]), (vx, vy)])
            self.add_locked_via("GND", vx, vy)
            self.gnd_done.add((ref, pn))

    # ==========================================================================
    # PATHFINDER NEGOTIATED-CONGESTION MULTI-LAYER ROUTER
    # ==========================================================================
    def _build_hard_obstacles(self, my_net, w_bcu, w_in2):
        """Hard obstacles that can NEVER be crossed: pads, NPTH, edge, fixed dogbones, locked critical/GND nets."""
        clr = net_clearance(my_net)
        extra = 0.025
        hb, hi = w_bcu / 2.0, w_in2 / 2.0

        hard = np.zeros((2, NX, NY), dtype=bool)
        hard[0] |= self.edge_forbidden
        hard[1] |= self.edge_forbidden
        via_hard = np.copy(self.via_hard_forbidden)
        # Hard-forbid NON-GND vias from touching F.Mask thumbprint gold ridges (zero front solder_mask_bridge!).
        # GND vias share the exact same net (GND) as the F.Cu pour, so they never bridge different nets!
        if my_net != "GND":
            via_hard |= self.via_fmask_forbidden

        for p in self.bcu_pad_list:
            if p["is_npth"]:
                for li, hw in ((0, hb), (1, hi)):
                    r = p["drill"] / 2.0 + hw + 0.27
                    r2 = r * r
                    for ix in range(gx_lo(p["cx"] - r), gx_hi(p["cx"] + r) + 1):
                        dx2 = (ix * RES - p["cx"]) ** 2
                        for iy in range(gy_lo(p["cy"] - r), gy_hi(p["cy"] + r) + 1):
                            if dx2 + (iy * RES - p["cy"]) ** 2 <= r2:
                                hard[li, ix, iy] = True
                continue

            if p["net"] == my_net:
                vm = VIA_R + 0.10
                via_hard[gx_lo(p["x1"] - vm):gx_hi(p["x2"] + vm) + 1, gy_lo(p["y1"] - vm):gy_hi(p["y2"] + vm) + 1] = True
                continue

            pad_clr = max(clr, net_clearance(p["net"]))
            m_tr = hb + pad_clr + extra
            hard[0, gx_lo(p["x1"] - m_tr):gx_hi(p["x2"] + m_tr) + 1, gy_lo(p["y1"] - m_tr):gy_hi(p["y2"] + m_tr) + 1] = True
            m_via = max(VIA_R + pad_clr, VIA_DRILL / 2.0 + 0.25) + extra
            via_hard[gx_lo(p["x1"] - m_via):gx_hi(p["x2"] + m_via) + 1, gy_lo(p["y1"] - m_via):gy_hi(p["y2"] + m_via) + 1] = True

        # Fixed vias + locked vias
        all_lv = [(v["net"], v["x"], v["y"], v["size"], v["drill"]) for v in self.fixed_vias] + self.locked_vias
        for vnet, vx, vy, vsz, vdr in all_lv:
            if vnet == my_net:
                r_v = vdr / 2.0 + VIA_DRILL / 2.0 + 0.27
                for dx, dy in self._disk_offsets(r_v):
                    ix, iy = gx(vx) + dx, gy(vy) + dy
                    if 0 <= ix < NX and 0 <= iy < NY:
                        via_hard[ix, iy] = True
                continue
            vclr = max(clr, net_clearance(vnet))
            for li, hw in ((0, hb), (1, hi)):
                r = max(vsz / 2.0 + hw + vclr, vdr / 2.0 + hw + 0.25) + extra
                r2 = r * r
                for ix in range(gx_lo(vx - r), gx_hi(vx + r) + 1):
                    dx2 = (ix * RES - vx) ** 2
                    for iy in range(gy_lo(vy - r), gy_hi(vy + r) + 1):
                        if dx2 + (iy * RES - vy) ** 2 <= r2:
                            hard[li, ix, iy] = True
            r_v = max(vsz / 2.0 + VIA_R + vclr, vdr / 2.0 + VIA_DRILL / 2.0 + 0.25) + extra
            r_v2 = r_v * r_v
            for ix in range(gx_lo(vx - r_v), gx_hi(vx + r_v) + 1):
                dx2 = (ix * RES - vx) ** 2
                for iy in range(gy_lo(vy - r_v), gy_hi(vy + r_v) + 1):
                    if dx2 + (iy * RES - vy) ** 2 <= r_v2:
                        via_hard[ix, iy] = True

        # Locked segments
        for snet, slyr, sw, sx1, sy1, sx2, sy2 in self.locked_segs:
            if snet == my_net:
                continue
            li = 0 if slyr == "B.Cu" else 1
            hw = hb if li == 0 else hi
            sclr = max(clr, net_clearance(snet))
            r_tr = sw / 2.0 + hw + sclr + extra
            r_tr2 = r_tr * r_tr
            for ix in range(gx_lo(min(sx1, sx2) - r_tr), gx_hi(max(sx1, sx2) + r_tr) + 1):
                px = ix * RES
                for iy in range(gy_lo(min(sy1, sy2) - r_tr), gy_hi(max(sy1, sy2) + r_tr) + 1):
                    if seg_dist_sq(px, iy * RES, sx1, sy1, sx2, sy2) <= r_tr2:
                        hard[li, ix, iy] = True
            r_v = max(sw / 2.0 + VIA_R + sclr, sw / 2.0 + VIA_DRILL / 2.0 + 0.25) + extra
            r_v2 = r_v * r_v
            for ix in range(gx_lo(min(sx1, sx2) - r_v), gx_hi(max(sx1, sx2) + r_v) + 1):
                px = ix * RES
                for iy in range(gy_lo(min(sy1, sy2) - r_v), gy_hi(max(sy1, sy2) + r_v) + 1):
                    if seg_dist_sq(px, iy * RES, sx1, sy1, sx2, sy2) <= r_v2:
                        via_hard[ix, iy] = True

        return hard, via_hard

    def _footprint_cells_of_net(self, net, w_bcu, w_in2):
        """
        Exact cell footprint matching 0.15 mm track / 0.45 mm via rules on 0.10 mm grid:
          - Track: r = sw/2 + 0.080 mm (for sw=0.15 -> 0.155 mm; two disjoint nets => center >= 0.31 mm => gap >= 0.16 mm > 0.135 mm!)
          - Via:   r = 0.310 mm on both layers (two disjoint vias => center >= 0.62 mm > 0.585 mm;
                   via vs 0.15 track => center >= 0.310 + 0.155 = 0.465 mm > 0.435 mm!)
        """
        tr_cells = set()
        via_cells = set()
        for snet, slyr, sw, sx1, sy1, sx2, sy2 in self.net_segs[net]:
            li = 0 if slyr == "B.Cu" else 1
            # Exact swath matching DRC on 0.10mm grid: 0.15 track -> r=0.150 (±1 cell);
            # 0.20 Power track -> r=0.205 (±2 cells, so 0.15 track must stay >= 0.40mm away -> gap=0.225 > 0.135!)
            r = sw / 2.0 + (0.105 if sw > 0.16 else 0.075)
            r2 = r * r
            for ix in range(gx_lo(min(sx1, sx2) - r), gx_hi(max(sx1, sx2) + r) + 1):
                px = ix * RES
                for iy in range(gy_lo(min(sy1, sy2) - r), gy_hi(max(sy1, sy2) + r) + 1):
                    if seg_dist_sq(px, iy * RES, sx1, sy1, sx2, sy2) <= r2:
                        tr_cells.add((li, ix, iy))
        for vnet, vx, vy, vsz, vdr in self.net_vias[net]:
            r = 0.325
            r2 = r * r
            for ix in range(gx_lo(vx - r), gx_hi(vx + r) + 1):
                dx2 = (ix * RES - vx) ** 2
                for iy in range(gy_lo(vy - r), gy_hi(vy + r) + 1):
                    if dx2 + (iy * RES - vy) ** 2 <= r2:
                        tr_cells.add((0, ix, iy))
                        tr_cells.add((1, ix, iy))
                        via_cells.add((ix, iy))
        return tr_cells, via_cells

    def _clear_pad_entry(self, hard, cx, cy, pad_info=None):
        ix, iy = gx(cx), gy(cy)
        hard[0, ix, iy] = False
        if pad_info is None:
            return
        x1, y1, x2, y2 = pad_info["x1"], pad_info["y1"], pad_info["x2"], pad_info["y2"]
        w, h = x2 - x1, y2 - y1
        if w >= h:
            for jx in range(gx_lo(x1 - 0.25), gx_hi(x2 + 0.25) + 1):
                if not self.edge_forbidden[jx, iy]:
                    hard[0, jx, iy] = False
        else:
            for jy in range(gy_lo(y1 - 0.25), gy_hi(y2 + 0.25) + 1):
                if not self.edge_forbidden[ix, jy]:
                    hard[0, ix, jy] = False

    def get_terminals_for_net(self, net):
        terms = []
        for p in self.pads_by_net[net]:
            if p["layer"] == "B.Cu":
                if p["ref"] == "MK1" and p["num"] == "1":
                    terms.append((0, 14.40, 44.80, None))
                elif p["ref"] == "MK1" and p["num"] == "2":
                    terms.append((0, 13.32, 39.30, None))
                elif p["ref"] == "MK1" and p["num"] == "3":
                    terms.append((0, 12.50, 39.30, None))
                else:
                    terms.append((0, p["cx"], p["cy"], p))
        for v in self.fixed_vias:
            if v["net"] == net:
                terms.append((1, v["x"], v["y"], None))
        return terms

    def _astar_pf(self, start_nodes, target_nodes, hard, via_hard, soft_cost, soft_via_cost, allow_soft=True, via_cost=8.0, max_exp=200000):
        target_set = set(target_nodes)
        if not start_nodes or not target_set:
            return None

        txs = [t[1] for t in target_nodes]
        tys = [t[2] for t in target_nodes]
        min_tx, max_tx = min(txs), max(txs)
        min_ty, max_ty = min(tys), max(tys)

        def heur(x, y):
            dx = max(min_tx - x, 0, x - max_tx)
            dy = max(min_ty - y, 0, y - max_ty)
            if dx < dy:
                return 1.30 * (1.4142 * dx + (dy - dx))
            return 1.30 * (1.4142 * dy + (dx - dy))

        gscore = {}
        parent = {}
        heap = []
        for s in start_nodes:
            if s in target_set:
                return [s]
            gscore[s] = 0.0
            heapq.heappush(heap, (heur(s[1], s[2]), 0.0, s))

        DIRS = [
            (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
            (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142),
        ]
        fmask_pen = self.via_fmask_penalty
        expansions = 0

        while heap:
            _, cur_g, cur = heapq.heappop(heap)
            if cur_g > gscore.get(cur, 1e18):
                continue
            if cur in target_set:
                path = [cur]
                while cur in parent:
                    cur = parent[cur]
                    path.append(cur)
                path.reverse()
                return path

            expansions += 1
            if expansions > max_exp:
                return None

            cl, cx, cy = cur
            lmult = 1.0 if cl == 1 else 1.12

            for dx, dy, dc in DIRS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < NX and 0 <= ny < NY):
                    continue
                nxt = (cl, nx, ny)
                if hard[cl, nx, ny] and nxt not in target_set:
                    continue
                if dx != 0 and dy != 0:
                    if hard[cl, cx + dx, cy] and hard[cl, cx, cy + dy]:
                        continue
                sc = float(soft_cost[cl, nx, ny])
                if not allow_soft and sc > 0.0 and nxt not in target_set:
                    continue
                ng = cur_g + dc * lmult + sc
                if ng < gscore.get(nxt, 1e18):
                    gscore[nxt] = ng
                    parent[nxt] = cur
                    heapq.heappush(heap, (ng + heur(nx, ny), ng, nxt))

            ol = 1 - cl
            if not via_hard[cx, cy] and not hard[ol, cx, cy]:
                svc = float(soft_via_cost[cx, cy]) + float(soft_cost[ol, cx, cy])
                if not allow_soft and svc > 0.0:
                    continue
                ng = cur_g + via_cost + float(fmask_pen[cx, cy]) + svc
                nxt = (ol, cx, cy)
                if ng < gscore.get(nxt, 1e18):
                    gscore[nxt] = ng
                    parent[nxt] = cur
                    heapq.heappush(heap, (ng + heur(cx, cy), ng, nxt))

        return None

    def _commit_net_path(self, net, w_bcu, w_in2, path, exact_start=None, exact_end=None):
        if len(path) < 2:
            return
        runs = []
        cur_layer = path[0][0]
        cur_pts = [(path[0][1] * RES, path[0][2] * RES)]
        vias_added = []

        for i in range(1, len(path)):
            l, ix, iy = path[i]
            px, py = ix * RES, iy * RES
            if l != cur_layer:
                runs.append((cur_layer, cur_pts))
                vias_added.append((px, py))
                cur_layer = l
                cur_pts = [(px, py)]
            else:
                cur_pts.append((px, py))
        runs.append((cur_layer, cur_pts))

        if exact_start is not None:
            runs[0][1][0] = exact_start
        if exact_end is not None:
            runs[-1][1][-1] = exact_end

        for l, pts in runs:
            lyr = "B.Cu" if l == 0 else "In2.Cu"
            w = w_bcu if l == 0 else w_in2
            pts = simplify_polyline(pts)
            for a, b in zip(pts[:-1], pts[1:]):
                if math.hypot(b[0] - a[0], b[1] - a[1]) >= 1e-4:
                    self.net_segs[net].append((net, lyr, w, round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)))
        for vx, vy in vias_added:
            self.net_vias[net].append((net, round(vx, 3), round(vy, 3), VIA_SIZE, VIA_DRILL))

    def _route_net_pf(self, net, hard, via_hard, soft_cost, soft_via_cost, w_bcu, w_in2, allow_soft=True):
        self.net_segs[net] = []
        self.net_vias[net] = []
        terms = self.get_terminals_for_net(net)
        if len(terms) < 2:
            return True

        # Prefer starting MST from U1 pin if present (avoids starting in MK1 vent pocket!)
        terms.sort(key=lambda t: (0 if (t[3] is not None and t[3]["ref"] == "U1") else 1))

        # Local copy of via_hard so same-net vias keep drill-to-drill spacing!
        v_hard = via_hard.copy()

        connected = [terms[0]]
        remaining = list(terms[1:])
        tree_nodes = {(terms[0][0], gx(terms[0][1]), gy(terms[0][2]))}
        if terms[0][3] is None and terms[0][0] == 1:
            tree_nodes.add((0, gx(terms[0][1]), gy(terms[0][2])))

        while remaining:
            best_i = 0
            best_d = 1e18
            for i, (_, rx, ry, _) in enumerate(remaining):
                for _, cx, cy, _ in connected:
                    d = math.hypot(rx - cx, ry - cy)
                    if d < best_d:
                        best_d = d
                        best_i = i
            tgt = remaining.pop(best_i)
            tl, tx, ty, tp = tgt
            tgt_nodes = [(tl, gx(tx), gy(ty))]
            if tp is None and tl == 1:
                tgt_nodes.append((0, gx(tx), gy(ty)))

            # Try strictly conflict-free FIRST (fast 50k cap), then PathFinder soft negotiation,
            # then gentle-cap fallback so large multi-pin nets (+1V8) NEVER time out and drop off the board!
            path = self._astar_pf(list(tree_nodes), tgt_nodes, hard, v_hard, soft_cost, soft_via_cost, allow_soft=False, max_exp=50000)
            if path is None and allow_soft:
                path = self._astar_pf(list(tree_nodes), tgt_nodes, hard, v_hard, soft_cost, soft_via_cost, allow_soft=True, max_exp=140000)
            if path is None and allow_soft:
                path = self._astar_pf(
                    list(tree_nodes), tgt_nodes, hard, v_hard,
                    np.minimum(6.0, soft_cost), np.minimum(6.0, soft_via_cost),
                    allow_soft=True, max_exp=200000,
                )
            if path is None:
                return False

            exact_s = None
            for cl, cx, cy, _ in connected:
                if gx(cx) == path[0][1] and gy(cy) == path[0][2]:
                    exact_s = (cx, cy)
                    break
            self._commit_net_path(net, w_bcu, w_in2, path, exact_start=exact_s, exact_end=(tx, ty))

            for node in path:
                tree_nodes.add(node)
            connected.append(tgt)

            for i in range(1, len(path)):
                if path[i][0] != path[i - 1][0]:
                    vx, vy = path[i][1] * RES, path[i][2] * RES
                    r_v = VIA_DRILL + 0.27
                    for ix in range(gx_lo(vx - r_v), gx_hi(vx + r_v) + 1):
                        for iy in range(gy_lo(vy - r_v), gy_hi(vy + r_v) + 1):
                            if (ix * RES - vx) ** 2 + (iy * RES - vy) ** 2 <= r_v ** 2:
                                v_hard[ix, iy] = True

        return True

    def route_all_pathfinder(self, max_iters=45):
        already_done = {"GND", "USB_DP", "USB_DM", "USB_DP_MCU", "USB_DM_MCU", "BUCK_SW", "SMPS_LX", "HSE_IN", "HSE_OUT"}
        nets = [n for n in self.pads_by_net.keys() if n and n not in already_done]

        # Sort: fine-pitch & bus nets first, large multi-pin power nets next
        def net_key(n):
            if n in ("BQ_ILIM", "BQ_ISET", "BQ_TS", "CHG_STAT1", "CHG_STAT2", "VDD11", "PDM_CLK", "PDM_DATA"):
                return (0, len(self.pads_by_net[n]), n)
            if n.startswith("SD_"):
                return (1, len(self.pads_by_net[n]), n)
            if n in ("RTC_32K", "I2C_SCL", "I2C_SDA", "SWDIO", "SWCLK", "NRST"):
                return (2, len(self.pads_by_net[n]), n)
            if n in POWER_NETS:
                return (3, len(self.pads_by_net[n]), n)
            return (4, len(self.pads_by_net[n]), n)

        nets.sort(key=net_key)

        # Precompute hard obstacle maps and widths for every net ONCE!
        print(f"[pf] Precomputing exact hard obstacle maps for {len(nets)} nets...", flush=True)
        net_meta = {}
        for n in nets:
            fp = any(p["ref"] in ("U1", "U3", "U4", "U7") for p in self.pads_by_net[n])
            wb, wi = net_widths(n, fine_pitch=fp)
            hard, vhard = self._build_hard_obstacles(n, wb, wi)
            for li, cx, cy, pinfo in self.get_terminals_for_net(n):
                if li == 0:
                    self._clear_pad_entry(hard, cx, cy, pinfo)
                else:
                    hard[0, gx(cx), gy(cy)] = False
                    hard[1, gx(cx), gy(cy)] = False
            net_meta[n] = (wb, wi, hard, vhard)

        # Occupancy & history grids (PathFinder with separate track & via occupancy for zero bloat!)
        occ = np.zeros((2, NX, NY), dtype=np.int16)
        occ_v = np.zeros((NX, NY), dtype=np.int16)
        hist = np.ones((2, NX, NY), dtype=np.float32)
        net_cells = {}  # net -> (tr_cells, via_cells)

        def add_net_occ(n):
            wb, wi, _, _ = net_meta[n]
            trc, viac = self._footprint_cells_of_net(n, wb, wi)
            net_cells[n] = (trc, viac)
            for li, ix, iy in trc:
                occ[li, ix, iy] += 1
            for ix, iy in viac:
                occ_v[ix, iy] += 1

        def rem_net_occ(n):
            if n in net_cells:
                trc, viac = net_cells.pop(n)
                for li, ix, iy in trc:
                    occ[li, ix, iy] -= 1
                for ix, iy in viac:
                    occ_v[ix, iy] -= 1

        def disk_dilate(arr, r_cells):
            # Exact circular max-dilation on 2D float32 array (avoids square corner bloat!)
            out = arr.copy()
            r2 = r_cells * r_cells + 1e-6
            ri = int(math.floor(r_cells))
            H, W = arr.shape
            for dx in range(-ri, ri + 1):
                for dy in range(-ri, ri + 1):
                    if dx == 0 and dy == 0:
                        continue
                    if dx * dx + dy * dy <= r2:
                        sx0 = max(0, -dx); sx1 = min(H, H - dx)
                        sy0 = max(0, -dy); sy1 = min(W, W - dy)
                        dx0 = max(0, dx);  dx1 = min(H, H + dx)
                        dy0 = max(0, dy);  dy1 = min(W, W + dy)
                        np.maximum(out[dx0:dx1, dy0:dy1], arr[sx0:sx1, sy0:sy1], out=out[dx0:dx1, dy0:dy1])
            return out

        def build_soft_fields(present_mult, wb, wi, cap=22.0):
            # Balanced cap (22.0): crossing a 4-cell track costs ~88 (beats 2-via detour ~25, fast A*!)
            raw = np.where(occ > 0, np.minimum(cap, present_mult * occ * hist), 0.0).astype(np.float32)
            # Tight exact dilation matching _footprint_cells_of_net (zero spill onto 0.40 mm pitch neighbors!)
            r_b = 1.70 if wb <= 0.16 else 2.05
            r_i = 1.70 if wi <= 0.16 else 2.05
            s_tr = np.zeros_like(raw)
            s_tr[0] = disk_dilate(raw[0], r_b)
            s_tr[1] = disk_dilate(raw[1], r_i)
            both = np.maximum(raw[0], raw[1])
            s_via = disk_dilate(both, 3.30)
            return s_tr, s_via

        import random
        rng = random.Random(7)
        prev_overused = 10**9
        stall_count = 0

        for it in range(max_iters):
            present_mult = 1.5 + it * 1.1
            if it == 0:
                to_route = list(nets)
            else:
                conflicted = []
                for n in nets:
                    if n not in net_cells or not self.net_segs[n]:
                        conflicted.append(n)
                        continue
                    trc, _ = net_cells[n]
                    if any(occ[li, ix, iy] > 1 for li, ix, iy in trc):
                        conflicted.append(n)
                if not conflicted:
                    print(f"[pf] CONVERGED at iteration {it}: 100% of {len(nets)} nets routed with ZERO overlaps!", flush=True)
                    return []
                hist[occ > 1] += 1.5

                # Neighborhood rip-up if stalled on a small conflict pocket OR unrouted nets with overused==0!
                if stall_count >= 2 and len(conflicted) <= 12:
                    ov_mask = (occ > 1).astype(np.float32)
                    # Also seed mask at all terminals of any unrouted net so we rip up nets blocking them!
                    for fn in conflicted:
                        if fn not in net_cells or not self.net_segs[fn]:
                            for li, tx, ty, _ in self.get_terminals_for_net(fn):
                                ov_mask[0, gx(tx), gy(ty)] = 1.0
                                ov_mask[1, gx(tx), gy(ty)] = 1.0
                    near = np.zeros_like(ov_mask)
                    near[0] = disk_dilate(ov_mask[0], 12.0)
                    near[1] = disk_dilate(ov_mask[1], 12.0)
                    conf_set = set(conflicted)
                    neighbors = []
                    for n in nets:
                        if n in conf_set or n not in net_cells:
                            continue
                        trc, _ = net_cells[n]
                        if any(near[li, ix, iy] > 0 for li, ix, iy in trc):
                            neighbors.append(n)
                    rng.shuffle(neighbors)
                    to_route = conflicted + neighbors[:10]
                    stall_count = 0
                    print(f"[pf iter {it}] Stalled -> neighborhood rip-up: {len(conflicted)} conflicted + {min(10, len(neighbors))} neighbors...", flush=True)
                else:
                    if it >= 3:
                        rng.shuffle(conflicted)
                    print(f"[pf iter {it}] Ripping up & rerouting {len(conflicted)} conflicted net(s)...", flush=True)
                    to_route = conflicted

            failed_this = []
            for n in to_route:
                rem_net_occ(n)
                wb, wi, hard, vhard = net_meta[n]
                s_tr, s_via = build_soft_fields(present_mult, wb, wi)
                ok = self._route_net_pf(n, hard, vhard, s_tr, s_via, wb, wi, allow_soft=(it < max_iters - 1))
                if ok:
                    add_net_occ(n)
                else:
                    self.net_segs[n] = []
                    self.net_vias[n] = []
                    failed_this.append(n)

            overused = int(np.sum(occ > 1))
            if overused >= prev_overused:
                stall_count += 1
            else:
                stall_count = 0
            prev_overused = overused
            extra_diag = ""
            if 0 < overused <= 40 and it >= 8:
                ov_pts = np.argwhere(occ > 1)
                c_nets = [n for n in nets if n in net_cells and any(occ[li, ix, iy] > 1 for li, ix, iy in net_cells[n][0])]
                sample = [(("B" if l == 0 else "I"), round(x * RES, 1), round(y * RES, 1)) for l, x, y in ov_pts[:3]]
                extra_diag = f" | nets={c_nets[:6]} @ {sample}"
            print(f"[pf iter {it}] done: failed={len(failed_this)} ({failed_this[:5]}), overused_cells={overused}{extra_diag}", flush=True)
            if not failed_this and overused == 0:
                print(f"[pf] CONVERGED at iteration {it}: 100% routed, 0 overlaps!", flush=True)
                return []
            # If stalled on a conflict pocket for 5 consecutive iterations, jump straight to strict legalization + push/mini-pf!
            if it >= 16 and it < max_iters - 2 and stall_count >= 5 and overused <= 100:
                print(f"[pf] Plateau at overused={overused} -> jumping to strict legalization pass...", flush=True)
                # Run one strict legalization pass right now
                conf_final = [n for n in nets if n not in net_cells or not self.net_segs[n] or any(occ[li, ix, iy] > 1 for li, ix, iy in net_cells[n][0])]
                for n in conf_final:
                    rem_net_occ(n)
                    wb, wi, hard, vhard = net_meta[n]
                    s_tr, s_via = build_soft_fields(present_mult, wb, wi)
                    if self._route_net_pf(n, hard, vhard, s_tr, s_via, wb, wi, allow_soft=False):
                        add_net_occ(n)
                    else:
                        self.net_segs[n] = []
                        self.net_vias[n] = []
                break

        # Push-aside rip-up-and-reroute polish for any remaining unrouted nets (depth-2 cascade!)
        unrouted = [n for n in nets if not self.net_segs[n]]
        if unrouted and int(np.sum(occ > 1)) == 0:
            print(f"[push] Starting push-aside polish for {len(unrouted)} unrouted net(s): {unrouted}", flush=True)

            def build_push_fields(wb, wi, pen_val, prot_nets):
                raw = np.where(occ > 0, pen_val, 0.0).astype(np.float32)
                for pn in prot_nets:
                    if pn in net_cells:
                        for li, ix, iy in net_cells[pn][0]:
                            raw[li, ix, iy] = 400.0
                r_b = 1.70 if wb <= 0.16 else 2.05
                r_i = 1.70 if wi <= 0.16 else 2.05
                s_tr = np.zeros_like(raw)
                s_tr[0] = disk_dilate(raw[0], r_b)
                s_tr[1] = disk_dilate(raw[1], r_i)
                both = np.maximum(raw[0], raw[1])
                s_via = disk_dilate(both, 3.30)
                return s_tr, s_via

            def snapshot_all():
                return (
                    {k: (list(self.net_segs[k]), list(self.net_vias[k])) for k in nets},
                    {k: (set(v[0]), set(v[1])) for k, v in net_cells.items()},
                    occ.copy(),
                    occ_v.copy(),
                )

            def restore_all(snap):
                saved_geo, saved_cells, saved_occ, saved_occv = snap
                for k, (sg, vi) in saved_geo.items():
                    self.net_segs[k] = sg
                    self.net_vias[k] = vi
                net_cells.clear()
                net_cells.update(saved_cells)
                occ[:] = saved_occ
                occ_v[:] = saved_occv

            def try_push(target, protected, depth, pen_val):
                wb, wi, hard, vhard = net_meta[target]
                s_tr, s_via = build_push_fields(wb, wi, pen_val, protected)
                # First try strictly conflict-free
                ok = self._route_net_pf(target, hard, vhard, s_tr, s_via, wb, wi, allow_soft=False)
                if ok:
                    add_net_occ(target)
                    return True
                if depth > 1:
                    return False
                # Route with soft overlap to identify minimum blockers
                ok = self._route_net_pf(target, hard, vhard, s_tr, s_via, wb, wi, allow_soft=True)
                if not ok:
                    self.net_segs[target] = []
                    self.net_vias[target] = []
                    return False
                trc_new, _ = self._footprint_cells_of_net(target, wb, wi)
                blockers = [m for m in nets if m != target and m in net_cells and not net_cells[m][0].isdisjoint(trc_new)]
                max_blk = 8 if depth == 0 else 2
                if not blockers or len(blockers) > max_blk or any(b in protected for b in blockers):
                    self.net_segs[target] = []
                    self.net_vias[target] = []
                    return False
                for b in blockers:
                    rem_net_occ(b)
                    self.net_segs[b] = []
                    self.net_vias[b] = []
                add_net_occ(target)
                new_prot = protected | {target}
                # Re-route all displaced blockers (sort shorter/easier first or harder first)
                blockers.sort(key=lambda b: len(self.pads_by_net[b]), reverse=True)
                for b in blockers:
                    if not try_push(b, new_prot, depth + 1, pen_val):
                        return False
                    new_prot = new_prot | {b}
                return True

            for rd in range(3):
                rem_list = [n for n in nets if not self.net_segs[n]]
                if not rem_list:
                    break
                progress = False
                for fn in rem_list:
                    for pen_val in (8.0, 18.0, 32.0):
                        snap = snapshot_all()
                        if try_push(fn, set(), 0, pen_val) and int(np.sum(occ > 1)) == 0:
                            print(f"  [push rd {rd}] INSERTED {fn} (pen={pen_val})! Remaining={len([n for n in nets if not self.net_segs[n]])}", flush=True)
                            progress = True
                            break
                        else:
                            restore_all(snap)
                if not progress:
                    break

            # Up to 3 rounds of local mini-PathFinder + push-aside rescue if 1..5 nets still remain unrouted
            for mrd in range(3):
                rem_list = [n for n in nets if not self.net_segs[n]]
                if not (1 <= len(rem_list) <= 5):
                    break
                rad_cells = 25.0 + mrd * 8.0
                n_nbrs = 14 + mrd * 4
                print(f"[mini-pf rd {mrd}] Running local 20-iter PathFinder rescue around {rem_list} (rad={rad_cells:.0f}, nbrs={n_nbrs})...", flush=True)
                snap_best = snapshot_all()
                best_rem = len(rem_list)
                seed_mask = np.zeros((2, NX, NY), dtype=np.float32)
                for fn in rem_list:
                    for _, tx, ty, _ in self.get_terminals_for_net(fn):
                        seed_mask[0, gx(tx), gy(ty)] = 1.0
                        seed_mask[1, gx(tx), gy(ty)] = 1.0
                near_m = np.zeros_like(seed_mask)
                near_m[0] = disk_dilate(seed_mask[0], rad_cells)
                near_m[1] = disk_dilate(seed_mask[1], rad_cells)
                rem_set = set(rem_list)
                local_nbrs = [
                    n for n in nets
                    if n not in rem_set and n in net_cells and any(near_m[li, ix, iy] > 0 for li, ix, iy in net_cells[n][0])
                ]
                rng.shuffle(local_nbrs)
                sub_nets = list(rem_list) + local_nbrs[:n_nbrs]
                for sn in sub_nets:
                    rem_net_occ(sn)
                    self.net_segs[sn] = []
                    self.net_vias[sn] = []
                hist_loc = np.ones((2, NX, NY), dtype=np.float32)
                for lit in range(20):
                    pm = 1.8 + lit * 1.4
                    if lit == 0:
                        l_route = list(sub_nets)
                    else:
                        l_route = [
                            n for n in nets
                            if n not in net_cells or not self.net_segs[n]
                            or any(occ[li, ix, iy] > 1 for li, ix, iy in net_cells[n][0])
                        ]
                        if not l_route:
                            print(f"[mini-pf rd {mrd}] CONVERGED at iter {lit}: 0 remaining!", flush=True)
                            break
                        hist_loc[occ > 1] += 1.6
                        l_route.sort(key=lambda x: (0 if x in rem_set else 1, rng.random()))
                    for n in l_route:
                        rem_net_occ(n)
                        wb, wi, hard, vhard = net_meta[n]
                        raw_l = np.where(occ > 0, np.minimum(24.0, pm * occ * hist_loc), 0.0).astype(np.float32)
                        r_b = 1.70 if wb <= 0.16 else 2.05
                        r_i = 1.70 if wi <= 0.16 else 2.05
                        st = np.zeros_like(raw_l)
                        st[0] = disk_dilate(raw_l[0], r_b)
                        st[1] = disk_dilate(raw_l[1], r_i)
                        sv = disk_dilate(np.maximum(raw_l[0], raw_l[1]), 3.30)
                        if self._route_net_pf(n, hard, vhard, st, sv, wb, wi, allow_soft=(lit < 19)):
                            add_net_occ(n)
                        else:
                            self.net_segs[n] = []
                            self.net_vias[n] = []
                    ov_l = int(np.sum(occ > 1))
                    unr_l = [n for n in nets if not self.net_segs[n]]
                    print(f"  [mini-pf rd {mrd} iter {lit}] failed={len(unr_l)} ({unr_l[:4]}), overused={ov_l}", flush=True)
                    if ov_l == 0 and len(unr_l) < best_rem:
                        best_rem = len(unr_l)
                        snap_best = snapshot_all()
                        if best_rem == 0:
                            break
                if int(np.sum(occ > 1)) > 0 or len([n for n in nets if not self.net_segs[n]]) > best_rem:
                    restore_all(snap_best)
                # Follow up with push-aside polish on whatever remains!
                rem_after = [n for n in nets if not self.net_segs[n]]
                if rem_after and int(np.sum(occ > 1)) == 0:
                    for fn in rem_after:
                        for pen_val in (8.0, 18.0, 32.0):
                            snap = snapshot_all()
                            if try_push(fn, set(), 0, pen_val) and int(np.sum(occ > 1)) == 0:
                                print(f"  [post-mini push] INSERTED {fn} (pen={pen_val})! Remaining={len([n for n in nets if not self.net_segs[n]])}", flush=True)
                                break
                            else:
                                restore_all(snap)

        return [n for n in nets if not self.net_segs[n]]

    # ==========================================================================
    # STAGE D: ROUTE ALL REMAINING GND PADS TO In1.Cu VIA (AFTER SIGNALS!)
    # ==========================================================================
    def finish_plane_fanouts(self, net_name, already_done=()):
        """
        Connect every B.Cu pad of a plane net ('GND' -> In1.Cu, '+1V8' -> In2.Cu) to the nearest
        clean via site (or existing same-net via) via B.Cu Dijkstra, routing cleanly around all tracks!
        """
        done_set = set(already_done)
        terms = []
        for p in self.pads_by_net[net_name]:
            if p["layer"] != "B.Cu" or (p["ref"], p["num"]) in done_set:
                continue
            if net_name == "+1V8" and p["ref"] == "MK1" and p["num"] == "1":
                terms.append((14.40, 44.80, None, ("MK1", "1")))
            else:
                terms.append((p["cx"], p["cy"], p, (p["ref"], p["num"])))
        print(f"[{net_name}] Fanning out {len(terms)} B.Cu pads to plane...", flush=True)

        wb, wi = (0.18, 0.18) if net_name == "GND" else (0.16, 0.16)
        hard, via_hard = self._build_hard_obstacles(net_name, wb, wi)
        # Note: for +1V8 on In2.Cu, a via must ALSO not hit any In2.Cu track of another net!
        clr = net_clearance(net_name)
        extra = 0.03
        for n, segs in self.net_segs.items():
            if n == net_name:
                continue
            for snet, slyr, sw, sx1, sy1, sx2, sy2 in segs:
                li = 0 if slyr == "B.Cu" else 1
                sclr = max(clr, net_clearance(snet))
                r_tr = sw / 2.0 + wb / 2.0 + sclr + extra
                r_tr2 = r_tr * r_tr
                for ix in range(gx_lo(min(sx1, sx2) - r_tr), gx_hi(max(sx1, sx2) + r_tr) + 1):
                    px = ix * RES
                    for iy in range(gy_lo(min(sy1, sy2) - r_tr), gy_hi(max(sy1, sy2) + r_tr) + 1):
                        if seg_dist_sq(px, iy * RES, sx1, sy1, sx2, sy2) <= r_tr2:
                            hard[li, ix, iy] = True
                r_v = max(sw / 2.0 + VIA_R + sclr, sw / 2.0 + VIA_DRILL / 2.0 + 0.25) + extra
                r_v2 = r_v * r_v
                for ix in range(gx_lo(min(sx1, sx2) - r_v), gx_hi(max(sx1, sx2) + r_v) + 1):
                    px = ix * RES
                    for iy in range(gy_lo(min(sy1, sy2) - r_v), gy_hi(max(sy1, sy2) + r_v) + 1):
                        if seg_dist_sq(px, iy * RES, sx1, sy1, sx2, sy2) <= r_v2:
                            via_hard[ix, iy] = True
        for n, vias in self.net_vias.items():
            if n == net_name:
                continue
            for vnet, vx, vy, vsz, vdr in vias:
                vclr = max(clr, net_clearance(vnet))
                r_tr = max(vsz / 2.0 + wb / 2.0 + vclr, vdr / 2.0 + wb / 2.0 + 0.25) + extra
                r_tr2 = r_tr * r_tr
                for ix in range(gx_lo(vx - r_tr), gx_hi(vx + r_tr) + 1):
                    dx2 = (ix * RES - vx) ** 2
                    for iy in range(gy_lo(vy - r_tr), gy_hi(vy + r_tr) + 1):
                        if dx2 + (iy * RES - vy) ** 2 <= r_tr2:
                            hard[0, ix, iy] = True
                            hard[1, ix, iy] = True
                r_v = max(vsz / 2.0 + VIA_R + vclr, vdr / 2.0 + VIA_DRILL / 2.0 + 0.25) + extra
                r_v2 = r_v * r_v
                for ix in range(gx_lo(vx - r_v), gx_hi(vx + r_v) + 1):
                    dx2 = (ix * RES - vx) ** 2
                    for iy in range(gy_lo(vy - r_v), gy_hi(vy + r_v) + 1):
                        if dx2 + (iy * RES - vy) ** 2 <= r_v2:
                            via_hard[ix, iy] = True

        existing_via_cells = set()
        for vn, vx, vy, _, _ in self.locked_vias:
            if vn == net_name:
                existing_via_cells.add((gx(vx), gy(vy)))
        for v in self.fixed_vias:
            if v["net"] == net_name:
                existing_via_cells.add((gx(v["x"]), gy(v["y"])))

        DIRS = [
            (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
            (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142),
        ]

        failed = []
        for tcx, tcy, pad, key in terms:
            self._clear_pad_entry(hard, tcx, tcy, pad)
            sx, sy = gx(tcx), gy(tcy)
            dist = {(sx, sy): 0.0}
            par = {}
            heap = [(0.0, sx, sy)]
            found = None
            reused = False

            while heap:
                cd, cx, cy = heapq.heappop(heap)
                if cd > dist.get((cx, cy), 1e18):
                    continue
                if (cx, cy) in existing_via_cells:
                    found = (cx, cy)
                    reused = True
                    break
                if not via_hard[cx, cy]:
                    found = (cx, cy)
                    reused = False
                    break
                if cd > 180.0:
                    break
                for dx, dy, dc in DIRS:
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < NX and 0 <= ny < NY):
                        continue
                    if hard[0, nx, ny] and (nx, ny) not in existing_via_cells:
                        continue
                    if dx != 0 and dy != 0 and hard[0, cx + dx, cy] and hard[0, cx, cy + dy]:
                        continue
                    nd = cd + dc
                    if nd < dist.get((nx, ny), 1e18):
                        dist[(nx, ny)] = nd
                        par[(nx, ny)] = (cx, cy)
                        heapq.heappush(heap, (nd, nx, ny))

            if found is None:
                failed.append(key)
                continue

            path = [found]
            cur = found
            while cur in par:
                cur = par[cur]
                path.append(cur)
            path.reverse()

            pts = [(ix * RES, iy * RES) for ix, iy in path]
            pts[0] = (tcx, tcy)
            self.add_locked_poly(net_name, "B.Cu", wb, pts)
            if not reused:
                vx, vy = found[0] * RES, found[1] * RES
                self.add_locked_via(net_name, vx, vy)
                existing_via_cells.add(found)
                r_v = VIA_DRILL + 0.27
                for ix in range(gx_lo(vx - r_v), gx_hi(vx + r_v) + 1):
                    for iy in range(gy_lo(vy - r_v), gy_hi(vy + r_v) + 1):
                        if (ix * RES - vx) ** 2 + (iy * RES - vy) ** 2 <= r_v ** 2:
                            via_hard[ix, iy] = True

        print(f"[{net_name}] Connected {len(terms) - len(failed)}/{len(terms)} pads; failed={failed}", flush=True)
        return failed

    def finish_gnd_fanouts(self):
        return self.finish_plane_fanouts("GND", already_done=self.gnd_done)

    def bridge_unconnected_via_drc(self, max_rounds=5):
        """
        Fill zones, query KiCad DRC for any remaining unconnected pairs (e.g. sliced +1V8 In2.Cu plane islands),
        and route each pair strictly conflict-free across B.Cu + In2.Cu until 0 airwires remain!
        """
        import json, subprocess
        sys.path.insert(0, str(WORKSPACE))
        import verify as vf

        kicad_cli = vf.find_kicad_cli()
        drc_tmp = WORKSPACE / "verify_out" / "drc_bridge.json"
        (WORKSPACE / "verify_out").mkdir(parents=True, exist_ok=True)
        env = vf.kicad_env()

        for rd in range(max_rounds):
            inject_routing_and_fill_zones(self.to_sexp())
            if drc_tmp.exists():
                drc_tmp.unlink()
            subprocess.run(
                [kicad_cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", str(drc_tmp), str(PCB_PATH)],
                capture_output=True, text=True, env=env,
            )
            data = json.loads(drc_tmp.read_text(encoding="utf-8"))
            unconn = data.get("unconnected_items", [])
            if not unconn:
                print(f"[bridge] Round {rd}: 0 unconnected items — 100% routed!", flush=True)
                return 0
            print(f"[bridge] Round {rd}: {len(unconn)} unconnected item(s) to bridge...", flush=True)

            # Parse exact (net_name, (x1, y1), (x2, y2)) pairs from DRC report
            pairs = []
            for u in unconn:
                its = u.get("items", [])
                if len(its) < 2:
                    continue
                d0, d1 = its[0].get("description", ""), its[1].get("description", "")
                p0, p1 = its[0].get("pos", {}), its[1].get("pos", {})
                # Extract net name from "[NET]" in description
                import re
                m = re.search(r"\[([^\]]+)\]", d0) or re.search(r"\[([^\]]+)\]", d1)
                if not m:
                    continue
                net = m.group(1)
                if net not in self.nets:
                    continue
                # Skip zone-to-zone pseudo-item if identical coords (it resolves once islands bridge!)
                x1, y1 = float(p0.get("x", 0)), float(p0.get("y", 0))
                x2, y2 = float(p1.get("x", 0)), float(p1.get("y", 0))
                if math.hypot(x2 - x1, y2 - y1) < 0.05:
                    continue
                # Determine which layer each endpoint is on (zone/In2.Cu vs B.Cu vs via)
                l0 = 1 if ("In2.Cu" in d0 or "Via" in d0) else 0
                l1 = 1 if ("In2.Cu" in d1 or "Via" in d1) else 0
                pairs.append((net, (l0, x1, y1, "Via" in d0), (l1, x2, y2, "Via" in d1)))

            if not pairs:
                return len(unconn)

            bridged_any = False
            zero = np.zeros((2, NX, NY), dtype=np.float32)
            zvia = np.zeros((NX, NY), dtype=np.float32)

            for net, (l0, x1, y1, isv0), (l1, x2, y2, isv1) in pairs:
                w = 0.15
                clr = net_clearance(net)
                extra = 0.03
                hard, vhard = self._build_hard_obstacles(net, w, w)
                # Mark ALL flexible net_segs & net_vias of OTHER nets into hard & vhard!
                for onet, segs in self.net_segs.items():
                    if onet == net:
                        continue
                    for snet, slyr, sw, sx1, sy1, sx2, sy2 in segs:
                        li = 0 if slyr == "B.Cu" else 1
                        sclr = max(clr, net_clearance(snet))
                        r_tr = sw / 2.0 + w / 2.0 + sclr + extra
                        r_tr2 = r_tr * r_tr
                        for ix in range(gx_lo(min(sx1, sx2) - r_tr), gx_hi(max(sx1, sx2) + r_tr) + 1):
                            px = ix * RES
                            for iy in range(gy_lo(min(sy1, sy2) - r_tr), gy_hi(max(sy1, sy2) + r_tr) + 1):
                                if seg_dist_sq(px, iy * RES, sx1, sy1, sx2, sy2) <= r_tr2:
                                    hard[li, ix, iy] = True
                        r_v = max(sw / 2.0 + VIA_R + sclr, sw / 2.0 + VIA_DRILL / 2.0 + 0.25) + extra
                        r_v2 = r_v * r_v
                        for ix in range(gx_lo(min(sx1, sx2) - r_v), gx_hi(max(sx1, sx2) + r_v) + 1):
                            px = ix * RES
                            for iy in range(gy_lo(min(sy1, sy2) - r_v), gy_hi(max(sy1, sy2) + r_v) + 1):
                                if seg_dist_sq(px, iy * RES, sx1, sy1, sx2, sy2) <= r_v2:
                                    vhard[ix, iy] = True
                for onet, vias in self.net_vias.items():
                    if onet == net:
                        continue
                    for vnet, vx, vy, vsz, vdr in vias:
                        vclr = max(clr, net_clearance(vnet))
                        r_tr = max(vsz / 2.0 + w / 2.0 + vclr, vdr / 2.0 + w / 2.0 + 0.25) + extra
                        r_tr2 = r_tr * r_tr
                        for ix in range(gx_lo(vx - r_tr), gx_hi(vx + r_tr) + 1):
                            dx2 = (ix * RES - vx) ** 2
                            for iy in range(gy_lo(vy - r_tr), gy_hi(vy + r_tr) + 1):
                                if dx2 + (iy * RES - vy) ** 2 <= r_tr2:
                                    hard[0, ix, iy] = True
                                    hard[1, ix, iy] = True
                        r_v = max(vsz / 2.0 + VIA_R + vclr, vdr / 2.0 + VIA_DRILL / 2.0 + 0.25) + extra
                        r_v2 = r_v * r_v
                        for ix in range(gx_lo(vx - r_v), gx_hi(vx + r_v) + 1):
                            dx2 = (ix * RES - vx) ** 2
                            for iy in range(gy_lo(vy - r_v), gy_hi(vy + r_v) + 1):
                                if dx2 + (iy * RES - vy) ** 2 <= r_v2:
                                    vhard[ix, iy] = True

                # Clear endpoint pad entries
                for cx, cy in ((x1, y1), (x2, y2)):
                    matched_pad = None
                    for p in self.pads_by_net[net]:
                        if math.hypot(p["cx"] - cx, p["cy"] - cy) < 0.05:
                            matched_pad = p
                            break
                    self._clear_pad_entry(hard, cx, cy, matched_pad)
                    hard[1, gx(cx), gy(cy)] = False

                snodes = [(l0, gx(x1), gy(y1))] + ([(1 - l0, gx(x1), gy(y1))] if isv0 else [])
                tnodes = [(l1, gx(x2), gy(y2))] + ([(1 - l1, gx(x2), gy(y2))] if isv1 else [])

                path = self._astar_pf(snodes, tnodes, hard, vhard, zero, zvia, allow_soft=False, via_cost=6.0)
                if path is not None and len(path) >= 2:
                    # Commit bridge into locked_segs/locked_vias
                    runs = []
                    cur_l = path[0][0]
                    pts = [(path[0][1] * RES, path[0][2] * RES)]
                    vias_add = []
                    for i in range(1, len(path)):
                        l, ix, iy = path[i]
                        px, py = ix * RES, iy * RES
                        if l != cur_l:
                            runs.append((cur_l, pts))
                            vias_add.append((px, py))
                            cur_l = l
                            pts = [(px, py)]
                        else:
                            pts.append((px, py))
                    runs.append((cur_l, pts))
                    runs[0][1][0] = (x1, y1)
                    runs[-1][1][-1] = (x2, y2)
                    for l, rpts in runs:
                        self.add_locked_poly(net, "B.Cu" if l == 0 else "In2.Cu", w, rpts)
                    for vx, vy in vias_add:
                        self.add_locked_via(net, vx, vy)
                    bridged_any = True
                    print(f"  [bridge] {net} ({x1:.2f},{y1:.2f}) -> ({x2:.2f},{y2:.2f}) OK ({len(vias_add)} via)", flush=True)
                else:
                    print(f"  [bridge] {net} ({x1:.2f},{y1:.2f}) -> ({x2:.2f},{y2:.2f}) BLOCKED", flush=True)

            if not bridged_any:
                break
        return -1

    def to_sexp(self):
        lines = []
        for net, lyr, w, x1, y1, x2, y2 in self.all_segs():
            nid = self.nets[net]
            lines.append(
                f'  (segment (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) '
                f'(width {w:.3f}) (layer "{lyr}") (net {nid}) (uuid "{uid()}"))'
            )
        for net, x, y, sz, dr in self.all_vias():
            nid = self.nets[net]
            lines.append(
                f'  (via (at {x:.3f} {y:.3f}) (size {sz:.3f}) (drill {dr:.3f}) '
                f'(layers "F.Cu" "B.Cu") (net {nid}) (uuid "{uid()}"))'
            )
        return "\n".join(lines)


def inject_routing_and_fill_zones(routing_sexp):
    CACHE_PATH.write_text(routing_sexp, encoding="utf-8")
    sys.path.insert(0, str(WORKSPACE))
    import build_pocket_recorder as bpr
    PCB_PATH.write_text(bpr.build_pcb(extra_routing=routing_sexp), encoding="utf-8")

    import pcbnew
    b = pcbnew.LoadBoard(str(PCB_PATH))
    filler = pcbnew.ZONE_FILLER(b)
    ok = filler.Fill(b.Zones())
    assert ok, "Zone fill failed"
    b.Save(str(PCB_PATH))
    print("Zones filled & saved cleanly!", flush=True)


def main():
    print("[1/5] Generating fresh base PCB & extracting geometry...", flush=True)
    sys.path.insert(0, str(WORKSPACE))
    import build_pocket_recorder as bpr
    with open(HW_DIR / "pocket_recorder.kicad_pro", "w", encoding="utf-8") as f:
        import json
        json.dump(bpr.KICAD_PRO, f, indent=2)
    PCB_PATH.write_text(bpr.build_pcb(), encoding="utf-8")
    data = extract_board_data()
    router = BoardRouter(data)

    print("[2/5] Routing critical high-speed & switching nets...", flush=True)
    router.route_critical_nets()
    router.init_gnd_anchors()

    def pre_anchor_plane_list(rt, net_name, pad_refs):
        wb = 0.18 if net_name == "GND" else 0.16
        hard_g, via_hard_g = rt._build_hard_obstacles(net_name, wb, wb)
        DIRS = [(1,0,1.0),(-1,0,1.0),(0,1,1.0),(0,-1,1.0),(1,1,1.4142),(1,-1,1.4142),(-1,1,1.4142),(-1,-1,1.4142)]
        done_set = rt.gnd_done if net_name == "GND" else rt.v18_done
        for ref, pn in pad_refs:
            if (ref, pn) in done_set:
                continue
            pad = rt.pad_by_ref_num[(ref, pn)]
            tcx, tcy = (14.40, 44.80) if (net_name == "+1V8" and ref == "MK1" and pn == "1") else (pad["cx"], pad["cy"])
            rt._clear_pad_entry(hard_g, tcx, tcy, None if (net_name == "+1V8" and ref == "MK1") else pad)
            sx, sy = gx(tcx), gy(tcy)
            dist = {(sx, sy): 0.0}; par = {}; heap = [(0.0, sx, sy)]; found = None
            while heap:
                cd, cx, cy = heapq.heappop(heap)
                if cd > dist.get((cx, cy), 1e18): continue
                if not via_hard_g[cx, cy]: found = (cx, cy); break
                if cd > 120.0: break
                for dx, dy, dc in DIRS:
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < NX and 0 <= ny < NY) or hard_g[0, nx, ny]: continue
                    if dx != 0 and dy != 0 and hard_g[0, cx+dx, cy] and hard_g[0, cx, cy+dy]: continue
                    nd = cd + dc
                    if nd < dist.get((nx, ny), 1e18):
                        dist[(nx, ny)] = nd; par[(nx, ny)] = (cx, cy); heapq.heappush(heap, (nd, nx, ny))
            if found:
                path = [found]; cur = found
                while cur in par: cur = par[cur]; path.append(cur)
                path.reverse()
                pts = [(ix * RES, iy * RES) for ix, iy in path]
                pts[0] = (tcx, tcy)
                rt.add_locked_poly(net_name, "B.Cu", wb, pts)
                vx, vy = found[0] * RES, found[1] * RES
                rt.add_locked_via(net_name, vx, vy)
                done_set.add((ref, pn))
                r_v = VIA_DRILL + 0.27
                for ix in range(gx_lo(vx - r_v), gx_hi(vx + r_v) + 1):
                    for iy in range(gy_lo(vy - r_v), gy_hi(vy + r_v) + 1):
                        if (ix * RES - vx) ** 2 + (iy * RES - vy) ** 2 <= r_v ** 2:
                            via_hard_g[ix, iy] = True

    router.v18_done = set()
    init_gnd_pre = [
        ("U1", "63"), ("U2", "4"), ("R7", "2"), ("C18", "2"), ("C20", "2"),
        ("C21", "2"), ("U5", "2"), ("Y1", "4"), ("C2", "2"), ("C22", "2"),
        ("D1", "2"), ("J1", "SH2"), ("C28", "2"), ("C12", "2"), ("C3", "2"),
        ("C4", "2"), ("C13", "2"), ("C23", "2"), ("R12", "2"),
    ]
    pre_anchor_plane_list(router, "GND", init_gnd_pre)

    print("[3/5] Running PathFinder negotiated-congestion router across B.Cu + In2.Cu (48 nets)...", flush=True)
    failed_nets = router.route_all_pathfinder(max_iters=45)

    print("[4/5] Connecting remaining GND pads to solid In1.Cu plane...", flush=True)
    failed_gnd = router.finish_gnd_fanouts()

    accum_gnd = list(init_gnd_pre)
    for rescue_round in range(2):
        if not failed_gnd:
            break
        accum_gnd.extend(failed_gnd)
        print(f"[rescue round {rescue_round+1}] Pre-anchoring {len(accum_gnd)} GND pads...", flush=True)
        router = BoardRouter(data)
        router.v18_done = set()
        router.route_critical_nets()
        router.init_gnd_anchors()
        pre_anchor_plane_list(router, "GND", accum_gnd)
        failed_nets = router.route_all_pathfinder(max_iters=45)
        failed_gnd = router.finish_gnd_fanouts()

    print("[5/5] Bridging any remaining airwires & filling zones...", flush=True)
    rem = router.bridge_unconnected_via_drc(max_rounds=4)
    segs = router.all_segs()
    vias = router.all_vias()
    print(f"Done! {len(segs)} segs, {len(vias)} vias | failed_nets={failed_nets}, failed_gnd={failed_gnd}, rem_unconnected={rem}", flush=True)


if __name__ == "__main__":
    main()
