# Pocket Recorder Hardware Workspace

Ready-to-iterate KiCad 8/9 hardware workspace for the **Low-Power Outdoor Audio Recorder** (`30.0 x 48.0 mm`, 4-layer 1.6 mm PCBWay Matte-Black ENIG, STM32U595RJT6Q / U5A5 drop-in, TDK T5837 PDM mic, RV-3032-C7 RTC, Hirose DM3D-SF microSD).

## Contents
- `SPEC.md` — Original hardware specification.
- `GEMINI.md` — Persistent agent context (all 13 locked design decisions, hard mechanical constraints, STM32U5 pin-swap guardrails, and Definition of Done) loaded automatically by **Gemini CLI**.
- `build_pocket_recorder.py` — Generates `pocket_recorder_hw/pocket_recorder.kicad_pro`, `pocket_recorder.kicad_pcb`, `pocket_recorder_bom.csv`, and `export_pcbway_gerbers.sh`.
- `build_pocket_recorder_sch.py` — Generates the 1:1 synchronized `pocket_recorder_hw/pocket_recorder.kicad_sch`.
- `verify.py` — Automated gatekeeper script (mechanical assertions, sch<->pcb parity, Freerouting CLI bridge, KiCad ERC/DRC JSON parser, and layer SVG/PNG renders).
- `pocket_recorder_hw/` — Pre-generated KiCad 8/9 project, BOM, and PCBWay Gerber export script.
- `.gemini/settings.json.example` — Optional template for adding `KiCAD-MCP-Server` to Gemini CLI.

## Quick Start with Gemini CLI

1. **Initialize Git** so the agent can checkpoint and revert placement/routing trials safely:
   ```bash
   git init
   git add .
   git commit -m "Initial verified architecture, schematic, and pre-placed 4L PCB"
   ```

2. **Check local tools:**
   ```bash
   kicad-cli --version
   python3 verify.py --mech-only
   ```
   *(Install [Freerouting](https://github.com/freerouting/freerouting/releases) to enable automated routing via `python3 verify.py --route`.)*

3. **Launch Gemini CLI** in this directory:
   ```bash
   gemini
   ```
   Confirm `GEMINI.md` and `SPEC.md` loaded with `/memory show`, then prompt:
   > Review `GEMINI.md` and run `python3 verify.py`. Iteratively refine component placement, safe STM32 pin swaps, critical-net routing (`USB_DP`/`DM` 90R, `L1`/`L2` switch loops, `Y1` HSE, `MK1` PDM), and Freerouting passes until `verify.py` exits 0 with 0 ERC, 0 DRC, and 0 unrouted nets, then export `pocket_recorder_pcbway_gerbers.zip`.

## PCBWay Order Settings (Ready to Fab)
- **Upload Archive:** `pocket_recorder_hw/pocket_recorder_pcbway_gerbers.zip` (full turnkey bundle with BOM, CPL, KiCad sources & 3D renders: `pocket_recorder_hw/pocket_recorder_production_package_v1.0.0.zip`)
- **Size:** `30.0 x 48.0 mm`, `R1.5 mm` corners
- **Layers / Thickness:** 4 Layers, `1.6 mm`, FR-4 TG150-160 (`1 oz` outer / `0.5 oz` inner)
- **Finish:** ENIG (1U" or 2U")
- **Solder Mask:** **Matte Black** (PCBWay Special Options)
- **Silkscreen:** White — **Both Sides** (`F.SilkS` carries minimalist flanking upward arrows, hole rings, and unlock/lock icons; `B.SilkS` carries parts-side legends)
- **Via Process:** Tenting vias (all vias covered by solder mask)
- **Impedance Control:** `90 ohm +/-10%` differential pair (`USB_DP`/`USB_DM`, `19.586 mm`, `0.001 mm` skew, over solid `In1.Cu` GND)
- **Fab Note:** *"Top (`F.Mask`) contains intentional thumbprint graphic openings over copper pour; `F.SilkS` contains intentional white icon artwork. Do NOT add PCBWay order number on Top side—place on Bottom (`B.SilkS`) inside 1.0 mm rim."*
