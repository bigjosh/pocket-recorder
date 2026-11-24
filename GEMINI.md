# Pocket Recorder Hardware Project — Agent Handoff Context

@./SPEC.md

## Project Goal
Take the pre-placed KiCad 8/9 project in `pocket_recorder_hw/` from unrouted ratsnest to a **100% routed, 0-ERC, 0-DRC, PCBWay-ready fabrication package** (`pocket_recorder_pcbway_gerbers.zip` + synchronized `.kicad_sch`, `.kicad_pcb`, and `pocket_recorder_bom.csv`).

Keep schematic, PCB, and BOM strictly synchronized. Prefer editing the Python generator scripts (`build_pocket_recorder.py` and `build_pocket_recorder_sch.py`, or merging them into a single unified `design.py`) over ad-hoc manual edits to one file.

## Locked Design Decisions (All 13 Spec Items Resolved)
1. **3.3 V USB & Switched 3.0 V SD Rails:**
   - Dedicated USB-only 3.3 V LDO (`U6`: `AP2112K-3.3TRG1`) fed from `VBUS_5V` to `STM32U5` `VDDUSB` (0 µA battery draw while recording).
   - GPIO-switched 3.0 V LDO (`U5`: `TLV75530PDBVR`, `SD_PWR_EN` on `PB5` with `100 kΩ` pull-down) + 4-bit SDMMC level translator (`U7`: `TXS02612RTWR`, `Ioff` partial power-down isolation) for the microSD card.
2. **RGB LED Supply:** Reverse-mount `D2` (`XZMDKCBDDG45S-9`) common anode wired to `VSYS`; cathodes through `2.2 kΩ` (R), `1 kΩ` (G), `1 kΩ` (B) straight to three 5 V-tolerant (`FT`) open-drain MCU pins.
3. **Battery Sense & VBUS Detect:**
   - `VBAT` sense: `220 kΩ` (`R16`) / `100 kΩ` (`R14`) + `10 nF` (`C27`) divider switched at the bottom by an `FT` open-drain GPIO (`VBAT_EN`, `PA2`) into an `FT_a` ADC pin (`VBAT_ADC`, `PA1`) for ~0 µA idle draw.
   - `VBUS_DET`: `100 kΩ` (`R13`) / `47 kΩ` (`R12`) divider from `VBUS_5V` to wake-capable `FT` pin (`PA0`).
   - Charger status: `BQ25185` `STAT1` / `STAT2` open-drain pins to MCU GPIOs (`PA3`, `PA4`).
4. **Charger:** Linear power-path charger `U3` (`BQ25185DLHR`), `500 mA` `ILIM` / `4.2 V` (`R5=18 kΩ`), `250 mA` `ICHG` (`R4=1.2 kΩ`), fixed `10 kΩ` (`R6`) on `TS/MR` (indoor room-temp charging only). Zero charger switching noise.
5. **Storage:** `J1` Hirose `DM3D-SF` push-pull microSD socket (`1.55 mm` height, flush with LQFP64). Orient card insertion inward so the seated 15.0 mm microSD card stays completely inside the `1.0 mm` parts-side rim keepout.
6. **USB HS & HSE Clock:** `Y1` `16 MHz` ±10 ppm crystal (`CX3225SB16000D0FLJCC` + 2× `12 pF` C0G `C28`/`C29`) on `PH0`/`PH1` (off in Stop 2). Route `USB_DP`/`USB_DM` as a `90 Ω` differential pair (`≤ 20 mm`, matched within `0.5 mm`, over unbroken `In1.Cu` GND).
7. **MCU & ESD Drop-Ins:** Primary BOM MCU is `STM32U595RJT6Q` (in stock at Mouser; 100% pin-identical drop-in for `U5A5`/`U585`/`U575` Q parts). USB ESD is `USBLC6-2SC6Y` (exact drop-in for `USBLC6-2SC6`).
8. **Outward Face Layout (Option 8C):**
   - **Zero silkscreen on outward face (`F.SilkS` completely empty)** — no pad names, no hole rings, no fab order number.
   - Top edge: 7 flat bare ENIG gold pads (`3.0 × 3.0 mm`, `6.0 mm` pitch, `3.0 mm` gaps). Row 1 (`y=3.0 mm`): `GND` (`x=6`), `D+` (`x=12`), `D-` (`x=18`), `5V` (`x=24`). Row 2 (`y=9.0 mm`): `SWDIO` (`x=9`), `NRST` (`x=15`), `SWCLK` (`x=21`).
   - Middle: Life-sized simplified line-art thumbprint centered vertically (`x=15.0, y≈24.5 mm`), rendered in **ENIG gold via `F.Mask` openings over the `F.Cu` GND pour** (`~0.38 mm` ridges, `≥ 0.34 mm` black resist dams).
   - Bottom row: `0.60 mm` NPTH holes `7.5 mm` apart — `MK1` mic port at `(11.25, 42.5)` and `D2` LED hole at `(18.75, 42.5)`.
   - Power zone (`U3`, `U4`, `L1`, `L2`) sits in the top-right behind `5V` for `≥ 30.0 mm` diagonal clearance from `MK1`.
9. **Pogo Pad Vias:** Short dog-bone fanout on `F.Cu` from each 3×3 mm pad to a **solder-mask-tented via outside the pad footprint** (waterproof without VIPPO). Keep `1.0 mm` `F.Cu` GND pour clearance from all 6 non-GND pads.
10. **Acoustic Vent Keepout:** Strict `Ø6.0 mm` flat bare solder mask disc around `MK1` `(11.25, 42.5)` — no vias, no copper features/step, no silkscreen.
11. **Assembly & Packages:** Stencil + hot-plate/reflow PCBA; compact QFN/DFN acceptable, **no BGA/WLCSP**. Favor `0603` passives over `0402` where space permits.
12. **PCB Fab & Stackup:** **PCBWay**, 4 layers (`F.Cu` / `In1.Cu` solid GND / `In2.Cu` power+sig / `B.Cu` parts), `1.6 mm`, **ENIG**, **Matte Black solder mask**, white silkscreen on `B.SilkS` only.
    - Matte-black resist rule: minimum solder mask bridge `≥ 0.127 mm` (`5 mil`) and copper-to-copper pad gap `≥ 0.22 mm` (keep LQFP64 pad width at `0.27 mm`).

## Hard Constraints (NEVER Violate During Iterative Routing)
- Outline: `30.0 × 48.0 mm`, `R1.5 mm` corners.
- Parts side (`B.Cu`) rim keepout: all component bodies, pads, courtyards, and seated microSD card body MUST stay inside `[1.0, 29.0] × [1.0, 47.0]`.
- Switcher acoustic separation: Euclidean distance from `MK1` `(11.25, 42.5)` to `U3`, `U4`, `L1`, and `L2` MUST be `>= 30.0 mm`.
- Fixed outward geometry: do NOT move `TP_*` pads, `MK1` hole `(11.25, 42.5)`, or `D2` hole `(18.75, 42.5)`.
- Zero components on `F.Cu` (except the 7 `TP_*` pogo pads); zero silkscreen on `F.SilkS`; zero vias inside `Ø6.0 mm` of `MK1`.

## STM32U595/U5A5 LQFP64 Pin-Swap Guardrails
When optimizing routing, you may swap pins ONLY within these verified rules (update schematic + PCB atomically):
- **LOCKED (Do not move):**
  - `USB_DM`/`USB_DP` (`PA11` pin 44 / `PA12` pin 45)
  - `SWDIO`/`SWCLK` (`PA13` pin 46 / `PA14` pin 49), `NRST` (pin 7), `BOOT0` (`PH3` pin 60)
  - `SDMMC1` (`PC8` 39, `PC9` 40, `PC10` 51, `PC11` 52, `PC12` 53, `PD2` 54)
  - `HSE` (`PH0` pin 5 / `PH1` pin 6), `LSE` (`PC14` pin 3)
  - All `VDD`, `VDDA`, `VBAT`, `VDDSMPS`, `VLXSMPS`, `VDD11`, `VDDUSB`, `VSS` pins.
- **SWAPPABLE (Verify alternate function / `FT` tolerance before moving):**
  - `LED_R`, `LED_G`, `LED_B`, `VBAT_EN`, `VBUS_DET` -> any 5 V-tolerant `FT` GPIO (note: `VBUS_DET` should stay on a `WKUP` pin like `PA0`, `PC13`, `PA2`, `PB2`).
  - `VBAT_ADC` -> MUST stay on a 5 V-tolerant `FT_a` ADC pin (e.g., `PA1` pin 15, `PC0`-`PC3` pins 8-11; NEVER a `TT_a` pin).
  - `SD_PWR_EN`, `SD_CD`, `CHG_STAT1`, `CHG_STAT2`, `RTC_INT` -> any spare GPIO.
  - `PDM_CLK`/`PDM_DATA` -> keep on `ADF1` AF3 pins (`PB3`/`PB4` on LQFP64, since `PC10`/`PC11` are used by `SDMMC1`).
  - `I2C_SCL`/`I2C_SDA` -> `I2C1` (`PB6`/`PB7` or `PB8`/`PB9`) or `I2C2` (`PB10`/`PB11`).
  - `UART_TX`/`UART_RX` -> any `USART1`/`2`/`3` pair routed cleanly to `J_DBG`.

## Part-Swap Rules
- Downsizing congested `0603` decoupling caps/resistors to `0402` is allowed ONLY if you keep the same capacitance/voltage/dielectric rating and update `pocket_recorder_bom.csv` with a verified in-stock DigiKey or Mouser MPN + URL.
- Never replace an active IC with a BGA or WLCSP package.

## Iterative Routing & Verification Loop (Definition of Done)
Run `python3 verify.py` after every iteration:
- `python3 verify.py --mech-only` : Fast pure-Python mechanical, keepout, clearance, and sch↔pcb parity check.
- `python3 verify.py --regen` : Regenerates `.kicad_sch` + `.kicad_pcb` + BOM, runs mechanical checks, KiCad ERC/DRC JSON checks, and SVG/PNG layer renders.
- `python3 verify.py --route` : Runs Specctra `.dsn` export -> Freerouting CLI -> `.ses` import -> zone fill -> full ERC/DRC + mechanical checks + layer renders.

**Definition of Done:** `python3 verify.py` exits `0` with `0` ERC errors, `0` DRC errors, `0` unrouted nets, all mechanical assertions passing, and clean visual inspection of `verify_out/top_outward.png` and `verify_out/bottom_parts.png` before running `pocket_recorder_hw/export_pcbway_gerbers.sh`.
