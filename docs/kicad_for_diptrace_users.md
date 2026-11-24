# KiCad for DipTrace Users — Quick Survival Guide

Switching from **DipTrace** to **KiCad 8/9/10** is very rewarding (especially the interactive push-and-shove router, real-time raytraced 3D viewer, and text-based Git-friendly files), **but** several core workflows work completely differently from DipTrace and will trip up your muscle memory at first.

Here are the biggest surprises you'll hit — and how to handle them in this project.

---

## 1. Hover-and-Press Hotkeys (Biggest Day-1 Muscle-Memory Shock)
In **DipTrace**, you mostly *click to select*, then drag or right-click a menu.
In **KiCad**, almost every tool is **hover your mouse over an item and press a single key** (no clicking needed first — and `Esc` returns to Select mode):

| Action | DipTrace Habit | KiCad Shortcut | Watch Out For |
|---|---|---|---|
| **Move** | Click & drag | **`M`** | Detaches wires/tracks from pads! |
| **Drag (keep wires/tracks connected!)** | Drag component | **`G`** (Schematic) / **`D`** (PCB) | Use **`G`** in Schematic and **`D`** in PCB so wires/traces rubber-band cleanly instead of ripping loose! |
| **Rotate 90°** | `R` or Space | **`R`** | Rotates CCW around cursor/origin |
| **Flip to Bottom Side (`B.Cu`)** | Right-click → Change Side | **`F`** | Instantly mirrors footprint onto `B.Cu` |
| **Edit Properties / Value** | Double-click | **`E`** (or double-click) | `V` edits Value only (Schematic); `U` edits RefDes |
| **Route Track** | Route Manual tool | **`X`** | Press **`V`** mid-route to drop a via & switch layers; **`Backspace`** undoes last corner |
| **Select Whole Trace / Net** | Right-click → Select Net | **`U`** (connected track) / **`I`** (whole net) | Super handy when deleting or moving a bus |
| **Zoom & Pan** | Right-drag to pan | **Middle-drag** to pan, **Scroll** to zoom | You can change mouse pan to Right-drag in *Preferences → Mouse and Touchpad* if you prefer DipTrace's feel! |

---

## 2. Symbols, Footprints & 3D Models Are Three Separate Libraries
In **DipTrace**, a *Component* (`.eli`) bundles its schematic symbol, attached PCB pattern, and 3D model into one neat record.

In **KiCad**, they are **completely decoupled**:
- **Symbols** live in `.kicad_sym` libraries (Schematic Editor).
- **Footprints** live in `.pretty/*.kicad_mod` folders (PCB Editor).
- **3D Models** (`.step`/`.wrl`) live in `.3dshapes` folders and are referenced by path inside the footprint.
- A symbol links to a footprint only via its text **`Footprint`** property (e.g., `Resistor_SMD:R_0603_1608Metric`).

> **Good news for this project:** Both `pocket_recorder.kicad_sch` and `usb_adapter.kicad_sch` embed their symbols and footprints directly inside the project files, and all 3D models use KiCad 10's built-in library (`${KICAD10_3DMODEL_DIR}`) plus local `3dmodels/*.wrl` files — so they open cleanly on any KiCad 10 install with zero missing libraries.

---

## 3. Copper Pours Do NOT Auto-Refill (`B` Key!)
This catches **every** DipTrace user on their first board:
- In **DipTrace**, copper pours update automatically (or via right-click → Update).
- In **KiCad**, moving a trace or component **does NOT refill copper zones** — the old copper stays right over your newly moved trace and looks like a short!
- **Always press `B`** to refill all copper zones (and **`Ctrl+B`** to hide fills while routing cleanly).
- **Inner Ground Planes (`In1.Cu`):** KiCad has no DipTrace-style negative "Plane Layer" that auto-fills the whole sheet. Instead, inner planes (`In1.Cu` GND in Pocket Recorder) are normal copper pour **Zones** drawn around the perimeter.

---

## 4. ERC Power Flags (`PWR_FLAG`) & Mandatory No-Connect (`X`)
KiCad's Schematic ERC is much stricter about electrical pin types than DipTrace:
- **The `PWR_FLAG` surprise:** If a net like `GND`, `+1V8`, or `VBUS_5V` only connects to pins typed *Power Input* (for example, power arriving from bare pogo pads or a passive inductor), KiCad ERC throws: *"Input Power pin not driven by any Output Power pins."* The idiomatic KiCad fix is attaching a virtual **`PWR_FLAG`** symbol to that net (you'll see `#FLG01`–`#FLG04` in Block 3 of `pocket_recorder.kicad_sch`).
- **Mandatory No-Connects:** Leaving *any* IC pin floating triggers an ERC error unless you explicitly place a blue **`X` (No-Connect flag, shortcut `Q`)** on it.
- **Labels vs Global Labels:** Plain Net Labels (`L`) are local to a single schematic sheet; **Global Labels (`Ctrl+L`)** connect across sheets (used throughout this project).

---

## 5. Schematic → PCB Sync (`F8`) Uses Hidden UUIDs
- In **DipTrace**, you go to *File → Renew Layout from Schematic → By Components / By RefDes*.
- In **KiCad**, press **`F8`** in either Schematic or PCB to open **Update PCB from Schematic**.
- **Gotcha:** KiCad matches parts by hidden **UUIDs**, not RefDes. If you delete a resistor in the schematic and place a brand-new one with the same RefDes (`R5`), `F8` will *delete* the routed `R5` on the PCB and drop a fresh unrouted one unless you check **"Re-link footprints to schematic symbols based on their reference designators"** in the `F8` dialog.

---

## 6. Interactive Push-and-Shove Router (Your New Favorite Feature!)
Unlike DipTrace's mostly manual routing, KiCad's router (`X`) defaults to **Shove mode** — as you route a new track, neighboring tracks smoothly slide out of the way while honoring DRC clearances!
- Look at the right-hand **Route** settings (or right-click while routing → *Interactive Router Settings*) to switch between:
  - **Highlight Collisions** (classic DipTrace feel)
  - **Shove** (default — pushes tracks and vias aside)
  - **Walk Around** (flows cleanly around obstacles without moving them)
- Press **`D`** on an existing trace segment to drag it smoothly while keeping 45° miters intact.
- Press **`6`** (in PCB Editor) to route a **Differential Pair** (like `USB_DP`/`USB_DM`).

---

## 7. Working on the Bottom Side (`B.Cu`) & Instant 3D Viewer (`Alt+3`)
Since all 59 components on the Pocket Recorder live on `B.Cu`:
- Use **View → Flip Board View** to mirror the entire PCB horizontally so you can read `B.SilkS` and inspect the parts side right-side-up (just like DipTrace's *View → Mirror*).
- Press **`Alt+3`** anytime to open KiCad's built-in **3D Viewer** (toggle *Preferences → Raytracing* for photorealistic Matte-Black + ENIG renders!).
- Use the right-hand **Appearance** panel (`Objects` / `Layers` / `Nets` tabs) to dim inactive layers (**High Contrast Mode** shortcut **`H`** cycles Normal / Dim / Hide!).

---

## 8. Board Outline (`Edge.Cuts`) & Rule Areas (Keepouts)
- **`Edge.Cuts` must be watertight:** Even a `0.001 mm` gap or overlapping line on `Edge.Cuts` will cause the 3D Viewer and board outline DRC to complain.
- **Keepouts = Rule Areas:** Instead of DipTrace's separate *Route Keepout* and *Copper Pour Keepout* shapes, KiCad uses one **Rule Area** polygon (`Ctrl+Shift+K`) with checkboxes for *Keep out tracks / vias / pads / copper pours / footprints* per layer (used on `F.Cu` around the 6 non-GND pogo pads and around the `MH1`/`MH2` magnet holes).

---

## 9. Gerber & Excellon Drill Export Are TWO Separate Buttons
In **DipTrace**, *Export → Gerber* and *N/C Drill* are clearly separate menu items; in **KiCad**:
1. Open **File → Fabrication Outputs → Gerbers (.gbr)...** (Plot dialog).
2. Click **Plot** to generate the Gerber files.
3. **Don't forget!** Inside that *same* dialog, click **Generate Drill Files...** → choose **Excellon**, **mm**, and check **"PTH and NPTH in separate files"** (critical for PCBWay so the `0.60 mm` mic/LED ports and `3.15 mm` magnet holes aren't plated!).
4. Even easier: for this repo, just run `python verify.py` / `python verify_usb_adapter.py` (or `export_pcbway_gerbers.sh`) — everything is automated via `kicad-cli`.

---

## 10. Bonus Tip for This Repo: Generator-First Workflow
Because KiCad files are clean plain-text S-expressions, **all schematic, PCB, BOM, and 3D-model definitions in this repository are generated deterministically by Python**:
- Main Recorder: `build_pocket_recorder.py` + `build_pocket_recorder_sch.py` + `verify.py`
- USB-C Adapter: `build_usb_adapter.py` + `verify_usb_adapter.py`

You can freely open, inspect, measure, and tweak `.kicad_sch` / `.kicad_pcb` directly in KiCad's GUI — just remember that running the Python generator scripts will overwrite manual GUI edits unless you mirror those changes into the scripts (or stop using the generators once you switch to GUI-only maintenance).
