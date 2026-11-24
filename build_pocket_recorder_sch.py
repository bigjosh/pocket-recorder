#!/usr/bin/env python3
"""
Pocket Recorder KiCad 8/9 Schematic Generator
Generates: pocket_recorder_hw/pocket_recorder.kicad_sch

1:1 matched to build_pocket_recorder.py (RefDes, Values, Footprints, Pins, Nets):
  - All 68 board components (U1-U7, MK1, D1-D2, J1, Y1, L1-L2, TP_*, J_BAT, J_DBG, R1-R16, C1-C29)
  - Self-contained embedded (lib_symbols ...) — zero external symbol library dependencies
  - Clean A2 single-sheet layout organized into 6 labeled functional blocks
  - Automatic no-connect flags on unused pins + PWR_FLAG drivers for clean ERC
"""
import os
import uuid

OUT_DIR = "pocket_recorder_hw"
os.makedirs(OUT_DIR, exist_ok=True)

PROJECT_NAME = "pocket_recorder"
ROOT_UUID = str(uuid.uuid4())
G = 2.54  # Standard 100 mil KiCad schematic grid (mm)


def uid():
    return str(uuid.uuid4())


def gx(u):
    return round(u * G, 3)


def gy(u):
    return round(u * G, 3)


LIB_DEFS = {}
SYMBOL_PIN_OFFSETS = {}


def register_box_symbol(
    sym_name,
    ref_prefix,
    left_pins,
    right_pins,
    half_w_u=4,
    in_bom="yes",
    on_board="yes",
    is_power=False,
):
    n_rows = max(len(left_pins), len(right_pins), 1)
    half_h_u = max((n_rows + 1) // 2 + 1, 2)
    bw = gx(half_w_u)
    bh = gy(half_h_u)
    pin_len = G

    pin_lines = []
    offsets = {}

    def place_side(pins, side):
        if not pins:
            return
        start_u = (len(pins) - 1) / 2.0
        for idx, (pnum, pname, ptype) in enumerate(pins):
            py_u = start_u - idx
            py_sym = round(py_u * G, 3)
            if side == "L":
                px_sym = round(-(bw + pin_len), 3)
                ang = 0
            else:
                px_sym = round(bw + pin_len, 3)
                ang = 180
            pnum_s = str(pnum)
            offsets[pnum_s] = (px_sym, round(-py_sym, 3), side)
            pin_lines.append(
                f'      (pin {ptype} line (at {px_sym:.3f} {py_sym:.3f} {ang}) (length {pin_len:.3f})\n'
                f'        (name "{pname}" (effects (font (size 1.016 1.016))))\n'
                f'        (number "{pnum_s}" (effects (font (size 1.016 1.016))))\n'
                f'      )'
            )

    place_side(left_pins, "L")
    place_side(right_pins, "R")

    power_tag = "\n    (power)" if is_power else ""
    ref_y = round(bh + 1.905, 3)
    val_y = round(-(bh + 1.905), 3)

    sym_sexp = f"""  (symbol "Local:{sym_name}"{power_tag}
    (pin_names (offset 1.016))
    (exclude_from_sim no)
    (in_bom {in_bom})
    (on_board {on_board})
    (property "Reference" "{ref_prefix}" (at 0 {ref_y:.3f} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "{sym_name}" (at 0 {val_y:.3f} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at 0 0 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (property "Datasheet" "" (at 0 0 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (symbol "{sym_name}_0_1"
      (rectangle (start {-bw:.3f} {bh:.3f}) (end {bw:.3f} {-bh:.3f})
        (stroke (width 0.254) (type default))
        (fill (type background))
      )
    )
    (symbol "{sym_name}_1_1"
{chr(10).join(pin_lines)}
    )
  )"""
    LIB_DEFS[sym_name] = sym_sexp
    SYMBOL_PIN_OFFSETS[sym_name] = offsets


def register_passive_2pin(sym_name, ref_prefix, body_kind):
    pin_len = G
    px = round(2 * G, 3)
    if body_kind == "R":
        graphic = (
            '      (rectangle (start -2.54 1.016) (end 2.54 -1.016)\n'
            '        (stroke (width 0.254) (type default)) (fill (type none)))'
        )
    elif body_kind == "C":
        graphic = (
            '      (polyline (pts (xy -2.54 0) (xy -0.635 0)) (stroke (width 0.254) (type default)))\n'
            '      (polyline (pts (xy 0.635 0) (xy 2.54 0)) (stroke (width 0.254) (type default)))\n'
            '      (polyline (pts (xy -0.635 1.905) (xy -0.635 -1.905)) (stroke (width 0.381) (type default)))\n'
            '      (polyline (pts (xy 0.635 1.905) (xy 0.635 -1.905)) (stroke (width 0.381) (type default)))'
        )
    else:
        graphic = (
            '      (arc (start -2.54 0) (mid -1.905 0.9) (end -1.27 0) (stroke (width 0.254) (type default)) (fill (type none)))\n'
            '      (arc (start -1.27 0) (mid -0.635 0.9) (end 0 0) (stroke (width 0.254) (type default)) (fill (type none)))\n'
            '      (arc (start 0 0) (mid 0.635 0.9) (end 1.27 0) (stroke (width 0.254) (type default)) (fill (type none)))\n'
            '      (arc (start 1.27 0) (mid 1.905 0.9) (end 2.54 0) (stroke (width 0.254) (type default)) (fill (type none)))'
        )

    sym_sexp = f"""  (symbol "Local:{sym_name}"
    (pin_numbers (hide yes))
    (pin_names (offset 0.508) (hide yes))
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (property "Reference" "{ref_prefix}" (at 0 2.54 0)
      (effects (font (size 1.016 1.016)))
    )
    (property "Value" "{sym_name}" (at 0 -2.54 0)
      (effects (font (size 1.016 1.016)))
    )
    (property "Footprint" "" (at 0 0 0)
      (effects (font (size 1.016 1.016)) (hide yes))
    )
    (property "Datasheet" "" (at 0 0 0)
      (effects (font (size 1.016 1.016)) (hide yes))
    )
    (symbol "{sym_name}_0_1"
{graphic}
    )
    (symbol "{sym_name}_1_1"
      (pin passive line (at {-px:.3f} 0 0) (length {pin_len:.3f})
        (name "~" (effects (font (size 1.016 1.016))))
        (number "1" (effects (font (size 1.016 1.016))))
      )
      (pin passive line (at {px:.3f} 0 180) (length {pin_len:.3f})
        (name "~" (effects (font (size 1.016 1.016))))
        (number "2" (effects (font (size 1.016 1.016))))
      )
    )
  )"""
    LIB_DEFS[sym_name] = sym_sexp
    SYMBOL_PIN_OFFSETS[sym_name] = {
        "1": (-px, 0.0, "L"),
        "2": (px, 0.0, "R"),
    }


def register_all_symbols():
    register_passive_2pin("R_0603", "R", "R")
    register_passive_2pin("C_0603", "C", "C")
    register_passive_2pin("L_2016", "L", "L")

    register_box_symbol(
        "PWR_FLAG", "#FLG",
        left_pins=[],
        right_pins=[("1", "PWR", "power_out")],
        half_w_u=2, in_bom="no", on_board="no", is_power=True,
    )

    register_box_symbol(
        "POGO_PAD", "TP",
        left_pins=[],
        right_pins=[("1", "PAD", "passive")],
        half_w_u=2,
    )

    u1_left = [
        ("1",  "VBAT",          "power_in"),
        ("13", "VDDA",          "power_in"),
        ("19", "VDD_19",        "power_in"),
        ("29", "VDDSMPS",       "power_in"),
        ("33", "VDD_33",        "power_in"),
        ("64", "VDD_64",        "power_in"),
        ("48", "VDDUSB",        "power_in"),
        ("28", "VLXSMPS",       "passive"),
        ("31", "VDD11_31",      "power_in"),
        ("62", "VDD11_62",      "power_in"),
        ("12", "VSSA",          "power_in"),
        ("18", "VSS_18",        "power_in"),
        ("30", "VSSSMPS",       "power_in"),
        ("32", "VSS_32",        "power_in"),
        ("47", "VSS_47",        "power_in"),
        ("63", "VSS_63",        "power_in"),
        ("3",  "PC14_OSC32_IN", "input"),
        ("4",  "PC15_OSC32_OUT","bidirectional"),
        ("5",  "PH0_OSC_IN",    "input"),
        ("6",  "PH1_OSC_OUT",   "bidirectional"),
        ("7",  "NRST",          "bidirectional"),
        ("60", "PH3_BOOT0",     "input"),
        ("14", "PA0_VBUS_DET",  "input"),
        ("15", "PA1_VBAT_ADC",  "input"),
        ("16", "PA2_VBAT_EN",   "bidirectional"),
        ("17", "PA3",           "bidirectional"),
        ("20", "PA4",           "bidirectional"),
        ("2",  "PC13_RTC_INT",  "input"),
        ("8",  "PC0",           "bidirectional"),
        ("9",  "PC1",           "bidirectional"),
        ("10", "PC2",           "bidirectional"),
        ("11", "PC3",           "bidirectional"),
    ]
    u1_right = [
        ("45", "PA12_USB_DP",   "bidirectional"),
        ("44", "PA11_USB_DM",   "bidirectional"),
        ("46", "PA13_SWDIO",    "bidirectional"),
        ("49", "PA14_SWCLK",    "bidirectional"),
        ("42", "PA9_UART_TX",   "bidirectional"),
        ("43", "PA10_UART_RX",  "bidirectional"),
        ("55", "PB3_ADF1_CCK0", "bidirectional"),
        ("56", "PB4_ADF1_SDI0", "bidirectional"),
        ("58", "PB6_I2C1_SCL",  "bidirectional"),
        ("59", "PB7_I2C1_SDA",  "bidirectional"),
        ("24", "PB0",           "bidirectional"),
        ("25", "PB1",           "bidirectional"),
        ("26", "PB2",           "bidirectional"),
        ("39", "PC8_SD_D0",     "bidirectional"),
        ("40", "PC9_SD_D1",     "bidirectional"),
        ("51", "PC10_SD_D2",    "bidirectional"),
        ("52", "PC11_SD_D3",    "bidirectional"),
        ("53", "PC12_SD_CK",    "bidirectional"),
        ("54", "PD2_SD_CMD",    "bidirectional"),
        ("57", "PB5_SD_PWR_EN", "bidirectional"),
        ("61", "PB8_SD_CD",     "bidirectional"),
        ("21", "PA5",           "bidirectional"),
        ("22", "PA6",           "bidirectional"),
        ("23", "PA7",           "bidirectional"),
        ("27", "PB10",          "bidirectional"),
        ("34", "PB13_STAT1",    "bidirectional"),
        ("35", "PB14_STAT2",    "bidirectional"),
        ("36", "PB15_LED_B",    "bidirectional"),
        ("37", "PC6_LED_R",     "bidirectional"),
        ("38", "PC7_LED_G",     "bidirectional"),
        ("41", "PA8",           "bidirectional"),
        ("50", "PA15",          "bidirectional"),
    ]
    register_box_symbol("STM32U595RJT6Q", "U", u1_left, u1_right, half_w_u=6)

    register_box_symbol(
        "USBLC6-2SC6Y", "D",
        left_pins=[("1", "IO1_PAD", "passive"), ("3", "IO2_PAD", "passive"), ("5", "VBUS", "power_in")],
        right_pins=[("6", "IO1_MCU", "passive"), ("4", "IO2_MCU", "passive"), ("2", "GND", "power_in")],
        half_w_u=4,
    )
    register_box_symbol(
        "AP2112K-3.3TRG1", "U",
        left_pins=[("1", "VIN", "power_in"), ("3", "EN", "input"), ("2", "GND", "power_in")],
        right_pins=[("5", "VOUT", "power_out"), ("4", "NC", "no_connect")],
        half_w_u=4,
    )
    register_box_symbol(
        "BQ25185DLHR", "U",
        left_pins=[
            ("10", "IN", "power_in"), ("4", "~CE", "input"), ("6", "TS/MR", "input"),
            ("7", "ILIM/VSET", "passive"), ("8", "ISET", "passive"), ("5", "GND", "power_in"),
        ],
        right_pins=[
            ("1", "SYS", "power_out"), ("2", "BAT", "bidirectional"),
            ("9", "STAT1", "open_collector"), ("3", "STAT2", "open_collector"), ("11", "EP_GND", "power_in"),
        ],
        half_w_u=4,
    )
    register_box_symbol(
        "TPS62840DLCR", "U",
        left_pins=[
            ("2", "VIN", "power_in"), ("4", "EN", "input"), ("3", "MODE", "input"),
            ("5", "VSET", "input"), ("6", "STOP", "input"), ("1", "GND", "power_in"),
        ],
        right_pins=[("7", "SW", "passive"), ("8", "VOS", "input")],
        half_w_u=4,
    )
    register_box_symbol(
        "TLV75530PDBVR", "U",
        left_pins=[("1", "IN", "power_in"), ("3", "EN", "input"), ("2", "GND", "power_in")],
        right_pins=[("5", "OUT", "power_out"), ("4", "NC", "no_connect")],
        half_w_u=4,
    )
    register_box_symbol(
        "TXS02612RTWR", "U",
        left_pins=[
            ("5", "VCCA", "power_in"), ("6", "DAT0A", "bidirectional"), ("7", "DAT1A", "bidirectional"),
            ("1", "DAT2A", "bidirectional"), ("3", "DAT3A", "bidirectional"), ("9", "CLKA", "bidirectional"),
            ("4", "CMDA", "bidirectional"), ("24", "SEL", "input"),
            ("2", "GND_2", "power_in"), ("11", "GND_11", "power_in"), ("25", "EP_GND", "power_in"),
        ],
        right_pins=[
            ("21", "VCCB0", "power_in"), ("17", "VCCB1", "power_in"),
            ("18", "DAT0B0", "bidirectional"), ("16", "DAT1B0", "bidirectional"),
            ("23", "DAT2B0", "bidirectional"), ("22", "DAT3B0", "bidirectional"),
            ("19", "CLKB0", "bidirectional"), ("20", "CMDB0", "bidirectional"),
            ("14", "DAT0B1", "bidirectional"), ("15", "DAT1B1", "bidirectional"),
            ("8", "DAT2B1", "bidirectional"), ("10", "DAT3B1", "bidirectional"),
            ("13", "CLKB1", "bidirectional"), ("12", "CMDB1", "bidirectional"),
        ],
        half_w_u=4,
    )
    register_box_symbol(
        "DM3D-SF", "J",
        left_pins=[
            ("4", "VDD", "power_in"), ("7", "DAT0", "bidirectional"), ("8", "DAT1", "bidirectional"),
            ("1", "DAT2", "bidirectional"), ("2", "CD/DAT3", "bidirectional"),
            ("5", "CLK", "input"), ("3", "CMD", "bidirectional"), ("6", "VSS", "power_in"),
        ],
        right_pins=[
            ("SW1", "CD_SW", "passive"), ("SW2", "CD_GND", "passive"),
            ("SH1", "SHIELD1", "passive"), ("SH2", "SHIELD2", "passive"),
            ("SH3", "SHIELD3", "passive"), ("SH4", "SHIELD4", "passive"),
        ],
        half_w_u=4,
    )
    register_box_symbol(
        "RV-3032-C7", "U",
        left_pins=[("6", "VDD", "power_in"), ("1", "VBACKUP", "passive"), ("4", "EVI", "input"), ("5", "VSS", "power_in")],
        right_pins=[("8", "SCL", "input"), ("2", "SDA", "bidirectional"), ("7", "CLKOUT", "output"), ("3", "~INT", "open_collector")],
        half_w_u=4,
    )
    register_box_symbol(
        "T5837_MIC", "MK",
        left_pins=[("1", "VDD", "power_in"), ("4", "SELECT", "input"), ("5", "GND", "power_in"), ("6", "RING", "power_in")],
        right_pins=[("3", "CLK", "input"), ("2", "DATA", "output")],
        half_w_u=4,
    )
    register_box_symbol(
        "RGB_LED_CA", "D",
        left_pins=[("2", "CA", "passive")],
        right_pins=[("1", "R_K", "passive"), ("3", "G_K", "passive"), ("4", "B_K", "passive")],
        half_w_u=3,
    )
    register_box_symbol(
        "XTAL_4P", "Y",
        left_pins=[("1", "X1", "passive"), ("2", "GND1", "passive")],
        right_pins=[("3", "X2", "passive"), ("4", "GND2", "passive")],
        half_w_u=3,
    )
    register_box_symbol(
        "LIPO_PADS", "J",
        left_pins=[],
        right_pins=[("1", "BAT+", "passive"), ("2", "BAT-", "passive")],
        half_w_u=3,
    )
    register_box_symbol(
        "BENCH_2X4", "J",
        left_pins=[("1", "+1V8", "passive"), ("3", "SWDIO", "passive"), ("5", "NRST", "passive"), ("7", "UART_TX", "passive")],
        right_pins=[("2", "GND", "passive"), ("4", "SWCLK", "passive"), ("6", "PDM_CLK", "passive"), ("8", "UART_RX", "passive")],
        half_w_u=4,
    )


SCH_ITEMS = []


def add_section_box(title, x1_u, y1_u, x2_u, y2_u):
    x1, y1, x2, y2 = gx(x1_u), gy(y1_u), gx(x2_u), gy(y2_u)
    SCH_ITEMS.append(
        f'  (rectangle (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f})\n'
        f'    (stroke (width 0.254) (type dash) (color 80 110 150 1))\n'
        f'    (fill (type none)) (uuid "{uid()}")\n'
        f'  )'
    )
    SCH_ITEMS.append(
        f'  (text "{title}" (exclude_from_sim no) (at {x1 + 2.54:.3f} {y1 + 3.81:.3f} 0)\n'
        f'    (effects (font (size 2.032 2.032) (bold yes)) (justify left))\n'
        f'    (uuid "{uid()}")\n'
        f'  )'
    )


def add_note(text, x_u, y_u):
    SCH_ITEMS.append(
        f'  (text "{text}" (exclude_from_sim no) (at {gx(x_u):.3f} {gy(y_u):.3f} 0)\n'
        f'    (effects (font (size 1.27 1.27)) (justify left))\n'
        f'    (uuid "{uid()}")\n'
        f'  )'
    )


def place_part(sym_name, ref, val, footprint, mpn, x_u, y_u, pin_nets, stub_u=2, in_bom="yes", on_board="yes"):
    sx, sy = gx(x_u), gy(y_u)
    offsets = SYMBOL_PIN_OFFSETS[sym_name]

    max_dy = max((abs(dy) for _, dy, _ in offsets.values()), default=2.54)
    ref_y = sy - max_dy - 3.175
    val_y = sy + max_dy + 3.175

    pin_uuids = "\n".join(f'    (pin "{pnum}" (uuid "{uid()}"))' for pnum in offsets.keys())
    SCH_ITEMS.append(f"""  (symbol
    (lib_id "Local:{sym_name}")
    (at {sx:.3f} {sy:.3f} 0)
    (unit 1)
    (exclude_from_sim no)
    (in_bom {in_bom})
    (on_board {on_board})
    (dnp no)
    (uuid "{uid()}")
    (property "Reference" "{ref}" (at {sx:.3f} {ref_y:.3f} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "{val}" (at {sx:.3f} {val_y:.3f} 0)
      (effects (font (size 1.143 1.143)))
    )
    (property "Footprint" "{footprint}" (at {sx:.3f} {sy:.3f} 0)
      (effects (font (size 1.016 1.016)) (hide yes))
    )
    (property "Datasheet" "" (at {sx:.3f} {sy:.3f} 0)
      (effects (font (size 1.016 1.016)) (hide yes))
    )
    (property "MPN" "{mpn}" (at {sx:.3f} {sy:.3f} 0)
      (effects (font (size 1.016 1.016)) (hide yes))
    )
{pin_uuids}
    (instances
      (project "{PROJECT_NAME}"
        (path "/{ROOT_UUID}" (reference "{ref}") (unit 1))
      )
    )
  )""")

    stub_mm = gx(stub_u)
    for pnum, (dx, dy, side) in offsets.items():
        px, py = round(sx + dx, 3), round(sy + dy, 3)
        net = pin_nets.get(pnum) or pin_nets.get(int(pnum) if pnum.isdigit() else pnum)
        if net:
            if side == "L":
                wx = round(px - stub_mm, 3)
                ang, just = 180, "right bottom"
            else:
                wx = round(px + stub_mm, 3)
                ang, just = 0, "left bottom"
            SCH_ITEMS.append(
                f'  (wire (pts (xy {px:.3f} {py:.3f}) (xy {wx:.3f} {py:.3f}))\n'
                f'    (stroke (width 0) (type default)) (uuid "{uid()}"))'
            )
            SCH_ITEMS.append(
                f'  (global_label "{net}" (shape bidirectional) (at {wx:.3f} {py:.3f} {ang})\n'
                f'    (effects (font (size 1.016 1.016)) (justify {just}))\n'
                f'    (uuid "{uid()}"))'
            )
        else:
            SCH_ITEMS.append(f'  (no_connect (at {px:.3f} {py:.3f}) (uuid "{uid()}"))')


def build_schematic():
    register_all_symbols()

    # BLOCK 1: OUTWARD POGO CLUSTER, USB ESD, VBUS DETECT & USB 3.3V LDO
    add_section_box("1. OUTWARD 7-PAD CLUSTER, USB ESD & USB-ONLY 3.3V LDO", 6, 6, 74, 60)
    for ref, net, y_u in [
        ("TP_GND", "GND", 14), ("TP_DP", "USB_DP", 20), ("TP_DM", "USB_DM", 26),
        ("TP_5V", "VBUS_5V", 32), ("TP_SWDIO", "SWDIO", 38),
        ("TP_NRST", "NRST", 44), ("TP_SWCLK", "SWCLK", 50),
    ]:
        place_part("POGO_PAD", ref, net, "Custom:PogoPad_3x3mm_ENIG", "ENIG_3x3mm", 14, y_u, {"1": net})

    place_part(
        "USBLC6-2SC6Y", "D1", "USBLC6-2SC6Y",
        "Package_TO_SOT_SMD:SOT-23-6", "USBLC6-2SC6Y", 37, 22,
        {"1": "USB_DP", "2": "GND", "3": "USB_DM", "4": "USB_DM_MCU", "5": "VBUS_5V", "6": "USB_DP_MCU"},
    )
    place_part(
        "AP2112K-3.3TRG1", "U6", "AP2112K-3.3TRG1",
        "Package_TO_SOT_SMD:SOT-23-5", "AP2112K-3.3TRG1", 60, 22,
        {"1": "VBUS_5V", "2": "GND", "3": "VBUS_5V", "5": "+3V3_USB"},
    )
    place_part("C_0603", "C13", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 37, 36, {"1": "VBUS_5V", "2": "GND"}, stub_u=1)
    place_part("C_0603", "C10", "1uF",   "Resistor_SMD:R_0603_1608Metric", "CL10A105KB8NNNC", 52, 36, {"1": "VBUS_5V", "2": "GND"}, stub_u=1)
    place_part("C_0603", "C11", "1uF",   "Resistor_SMD:R_0603_1608Metric", "CL10A105KB8NNNC", 66, 36, {"1": "+3V3_USB", "2": "GND"}, stub_u=1)
    place_part("R_0603", "R13", "100k",  "Resistor_SMD:R_0603_1608Metric", "RC0603FR-07100KL", 42, 49, {"1": "VBUS_5V", "2": "VBUS_DET"}, stub_u=1)
    place_part("R_0603", "R12", "47k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0747KL",  60, 49, {"1": "VBUS_DET", "2": "GND"}, stub_u=1)
    add_note("USB_DP/DM routed 90R diff pair; VDDUSB LDO draws 0uA on battery.", 10, 57)

    # BLOCK 2: POWER-PATH CHARGER (250mA), LIPO & 1.8V ALWAYS-ON BUCK
    add_section_box("2. LINEAR POWER-PATH CHARGER (BQ25185) & 1.8V ALWAYS-ON BUCK (TPS62840)", 78, 6, 162, 60)
    place_part(
        "BQ25185DLHR", "U3", "BQ25185DLHR",
        "Package_SON:WSON-10-1EP_2.2x2mm_P0.4mm", "BQ25185DLHR", 98, 22,
        {
            "1": "VSYS", "2": "VBAT", "3": "CHG_STAT2", "4": "GND", "5": "GND",
            "6": "BQ_TS", "7": "BQ_ILIM", "8": "BQ_ISET", "9": "CHG_STAT1",
            "10": "VBUS_5V", "11": "GND",
        },
    )
    place_part("LIPO_PADS", "J_BAT", "LIPO_500MAH", "Custom:LiPo_SolderPads_2P", "SOLDER_PADS", 86, 46, {"1": "VBAT", "2": "GND"})
    place_part("R_0603", "R4", "1.2k",  "Resistor_SMD:R_0603_1608Metric", "RC0603FR-071K2L", 104, 40, {"1": "BQ_ISET", "2": "GND"}, stub_u=1)
    place_part("R_0603", "R5", "18k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0718KL", 104, 46, {"1": "BQ_ILIM", "2": "GND"}, stub_u=1)
    place_part("R_0603", "R6", "10k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0710KL", 104, 52, {"1": "BQ_TS",   "2": "GND"}, stub_u=1)
    place_part("C_0603", "C8", "1uF",   "Resistor_SMD:R_0603_1608Metric", "CL10A105KB8NNNC", 122, 40, {"1": "VBUS_5V", "2": "GND"}, stub_u=1)
    place_part("C_0603", "C9", "1uF",   "Resistor_SMD:R_0603_1608Metric", "CL10A105KB8NNNC", 122, 46, {"1": "VBAT",    "2": "GND"}, stub_u=1)
    place_part("C_0603", "C1", "10uF",  "Resistor_SMD:R_0603_1608Metric", "CL10A106KP8NNNC", 122, 52, {"1": "VSYS",    "2": "GND"}, stub_u=1)

    place_part(
        "TPS62840DLCR", "U4", "TPS62840DLCR",
        "Package_SON:Texas_VSON-HR-8_1.5x2mm_P0.5mm", "TPS62840DLCR", 142, 22,
        {"1": "GND", "2": "VSYS", "3": "GND", "4": "VSYS", "5": "GND", "6": "GND", "7": "BUCK_SW", "8": "+1V8"},
    )
    place_part("L_2016", "L1", "2.2uH", "Inductor_SMD:L_2016_Murata_DFE201610E", "DFE201610E-2R2M=P2", 144, 38, {"1": "BUCK_SW", "2": "+1V8"}, stub_u=1)
    place_part("C_0603", "C4", "4.7uF", "Resistor_SMD:R_0603_1608Metric", "CL10A475KP8NNNC", 144, 46, {"1": "VSYS", "2": "GND"}, stub_u=1)
    place_part("C_0603", "C2", "10uF",  "Resistor_SMD:R_0603_1608Metric", "CL10A106KP8NNNC", 144, 53, {"1": "+1V8", "2": "GND"}, stub_u=1)
    add_note("R4=1.2k (250mA), R5=18k (500mA/4.2V), R6=10k fixed TS. Place U3/U4/L1 >=30mm from MK1.", 80, 58)

    # BLOCK 3: SWITCHED VBAT ADC DIVIDER & ERC POWER FLAGS
    add_section_box("3. SWITCHED VBAT SENSE & ERC POWER FLAGS", 166, 6, 224, 60)
    place_part("R_0603", "R16", "220k", "Resistor_SMD:R_0603_1608Metric", "RC0603FR-07220KL", 184, 20, {"1": "VBAT", "2": "VBAT_ADC"}, stub_u=1)
    place_part("R_0603", "R14", "100k", "Resistor_SMD:R_0603_1608Metric", "RC0603FR-07100KL", 184, 28, {"1": "VBAT_ADC", "2": "VBAT_EN"}, stub_u=1)
    place_part("C_0603", "C27", "10nF", "Resistor_SMD:R_0603_1608Metric", "CL10B103KB8NNNC",  184, 36, {"1": "VBAT_ADC", "2": "VBAT_EN"}, stub_u=1)
    add_note("FW: Drive VBAT_EN (PA2 OD) LOW,", 169, 44)
    add_note("wait 5ms, sample PA1 (FT_a), then", 169, 48)
    add_note("disable ADC & release PA2 Hi-Z.", 169, 52)

    for idx, net in enumerate(["GND", "VBUS_5V", "+1V8", "VDD11"], 1):
        place_part("PWR_FLAG", f"#FLG0{idx}", "PWR_FLAG", "", "", 210, 12 + idx * 7, {"1": net}, stub_u=1, in_bom="no", on_board="no")

    # BLOCK 4: STM32U595RJT6Q MCU, HSE CRYSTAL, SMPS & DECOUPLING
    add_section_box("4. STM32U595RJT6Q MCU (DROP-IN U5A5/U585/U575 Q), 16MHz HSE & SMPS", 78, 64, 162, 154)
    stm32_nets = {
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
    place_part(
        "STM32U595RJT6Q", "U1", "STM32U595RJT6Q",
        "Package_QFP:LQFP-64_10x10mm_P0.5mm", "STM32U595RJT6Q", 112, 92, stm32_nets, stub_u=2,
    )
    place_part("XTAL_4P", "Y1", "16MHz", "Crystal:Crystal_SMD_3225-4Pin", "CX3225SB16000D0FLJCC", 90, 126, {"1": "HSE_IN", "2": "GND", "3": "HSE_OUT", "4": "GND"}, stub_u=1)
    place_part("C_0603", "C28", "12pF", "Resistor_SMD:R_0603_1608Metric", "CL10C120JB8NNNC", 90, 138, {"1": "HSE_IN",  "2": "GND"}, stub_u=1)
    place_part("C_0603", "C29", "12pF", "Resistor_SMD:R_0603_1608Metric", "CL10C120JB8NNNC", 90, 146, {"1": "HSE_OUT", "2": "GND"}, stub_u=1)

    place_part("L_2016", "L2", "2.2uH", "Inductor_SMD:L_2016_Murata_DFE201610E", "DFE201610E-2R2M=P2", 114, 126, {"1": "SMPS_LX", "2": "VDD11"}, stub_u=1)
    place_part("C_0603", "C6", "2.2uF", "Resistor_SMD:R_0603_1608Metric", "CL10A225KP8NNNC", 114, 138, {"1": "VDD11", "2": "GND"}, stub_u=1)
    place_part("C_0603", "C7", "2.2uF", "Resistor_SMD:R_0603_1608Metric", "CL10A225KP8NNNC", 114, 146, {"1": "VDD11", "2": "GND"}, stub_u=1)

    place_part("R_0603", "R7",  "10k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0710KL", 138, 126, {"1": "BOOT0", "2": "GND"}, stub_u=1)
    place_part("C_0603", "C17", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 138, 138, {"1": "NRST",  "2": "GND"}, stub_u=1)

    for ref, val, mpn, rail, y_u in [
        ("C5",  "4.7uF", "CL10A475KP8NNNC", "+1V8",     74),
        ("C14", "100nF", "CL10B104KB8NNNC", "+1V8",     82),
        ("C15", "100nF", "CL10B104KB8NNNC", "+1V8",     90),
        ("C16", "100nF", "CL10B104KB8NNNC", "+1V8",     98),
        ("C18", "100nF", "CL10B104KB8NNNC", "+1V8",    106),
        ("C19", "100nF", "CL10B104KB8NNNC", "+1V8",    114),
        ("C20", "100nF", "CL10B104KB8NNNC", "+3V3_USB",122),
    ]:
        place_part("C_0603", ref, val, "Resistor_SMD:R_0603_1608Metric", mpn, 150, y_u, {"1": rail, "2": "GND"}, stub_u=1)

    # BLOCK 5: PDM MICROPHONE, REVERSE-MOUNT RGB LED, RTC & BENCH 2x4 DEBUG
    add_section_box("5. PDM MIC (T5837), RGB LED, RTC (RV-3032-C7) & 2x4 BENCH DEBUG", 6, 64, 74, 154)
    place_part(
        "T5837_MIC", "MK1", "MMICT5837-00-012",
        "Audio:TDK_T5837_T5838_BottomPort", "MMICT5837-00-012", 22, 80,
        {"1": "+1V8", "2": "PDM_DATA", "3": "PDM_CLK", "4": "GND", "5": "GND", "6": "GND"},
    )
    place_part("C_0603", "C25", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 22, 96, {"1": "+1V8", "2": "GND"}, stub_u=1)

    place_part(
        "RGB_LED_CA", "D2", "XZMDKCBDDG45S-9",
        "LED_SMD:SunLED_XZMDKCBDDG45S-9_ReverseMount", "XZMDKCBDDG45S-9", 54, 76,
        {"1": "LED_R_K", "2": "VSYS", "3": "LED_G_K", "4": "LED_B_K"},
    )
    place_part("R_0603", "R3",  "2.2k",  "Resistor_SMD:R_0603_1608Metric", "RC0603FR-072K2L", 54, 86,  {"1": "LED_R", "2": "LED_R_K"}, stub_u=1)
    place_part("R_0603", "R1",  "1k",    "Resistor_SMD:R_0603_1608Metric", "RC0603FR-071KL",  54, 92,  {"1": "LED_G", "2": "LED_G_K"}, stub_u=1)
    place_part("R_0603", "R2",  "1k",    "Resistor_SMD:R_0603_1608Metric", "RC0603FR-071KL",  54, 98,  {"1": "LED_B", "2": "LED_B_K"}, stub_u=1)
    place_part("C_0603", "C26", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 54, 104, {"1": "VSYS",  "2": "GND"},     stub_u=1)

    place_part(
        "RV-3032-C7", "U2", "RV-3032-C7",
        "Timer_RTC:MicroCrystal_RV-3032-C7", "RV-3032-C7-32.768KHZ-2.5PPM-TA-QC", 22, 124,
        {"1": "RTC_VBACK", "2": "I2C_SDA", "3": "RTC_INT", "4": "GND", "5": "GND", "6": "+1V8", "7": "RTC_32K", "8": "I2C_SCL"},
    )
    place_part("C_0603", "C21", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 22, 140, {"1": "+1V8",      "2": "GND"},  stub_u=1)
    place_part("R_0603", "R8",  "10k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0710KL", 42, 118, {"1": "I2C_SCL",   "2": "+1V8"}, stub_u=1)
    place_part("R_0603", "R9",  "10k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0710KL", 42, 124, {"1": "I2C_SDA",   "2": "+1V8"}, stub_u=1)
    place_part("R_0603", "R10", "10k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0710KL", 42, 130, {"1": "RTC_VBACK", "2": "GND"},  stub_u=1)
    place_part("R_0603", "R11", "10k",   "Resistor_SMD:R_0603_1608Metric", "RC0603FR-0710KL", 42, 136, {"1": "RTC_INT",   "2": "+1V8"}, stub_u=1)

    place_part(
        "BENCH_2X4", "J_DBG", "2x4_BENCH",
        "Custom:BenchDebug_2x4_1.27mm", "BENCH_PADS", 62, 132,
        {"1": "+1V8", "2": "GND", "3": "SWDIO", "4": "SWCLK", "5": "NRST", "6": "PDM_CLK", "7": "UART_TX", "8": "UART_RX"},
        stub_u=1,
    )

    # BLOCK 6: SWITCHED 3.0V SD LDO, 4-BIT LEVEL TRANSLATOR & microSD SOCKET
    add_section_box("6. SWITCHED 3.0V SD LDO, SDMMC TRANSLATOR (TXS02612) & microSD", 166, 64, 224, 154)
    place_part(
        "TLV75530PDBVR", "U5", "TLV75530PDBVR",
        "Package_TO_SOT_SMD:SOT-23-5", "TLV75530PDBVR", 184, 78,
        {"1": "VSYS", "2": "GND", "3": "SD_PWR_EN", "5": "+3V0_SD"},
    )
    place_part("R_0603", "R15", "100k", "Resistor_SMD:R_0603_1608Metric", "RC0603FR-07100KL", 184, 91, {"1": "SD_PWR_EN", "2": "GND"}, stub_u=1)
    place_part("C_0603", "C12", "1uF",  "Resistor_SMD:R_0603_1608Metric", "CL10A105KB8NNNC",  208, 76, {"1": "VSYS",      "2": "GND"}, stub_u=1)
    place_part("C_0603", "C3",  "10uF", "Resistor_SMD:R_0603_1608Metric", "CL10A106KP8NNNC",  208, 84, {"1": "+3V0_SD",   "2": "GND"}, stub_u=1)

    place_part(
        "TXS02612RTWR", "U7", "TXS02612RTWR",
        "Package_DFN_QFN:WQFN-24-1EP_4x4mm_P0.5mm", "TXS02612RTWR", 182, 118,
        {
            "1": "SD_D2_1V8", "2": "GND", "3": "SD_D3_1V8", "4": "SD_CMD_1V8", "5": "+1V8",
            "6": "SD_D0_1V8", "7": "SD_D1_1V8", "9": "SD_CLK_1V8", "11": "GND",
            "16": "SD_D1_3V", "17": "+3V0_SD", "18": "SD_D0_3V", "19": "SD_CLK_3V",
            "20": "SD_CMD_3V", "21": "+3V0_SD", "22": "SD_D3_3V", "23": "SD_D2_3V",
            "24": "GND", "25": "GND",
        },
        stub_u=1,
    )
    place_part("C_0603", "C22", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 182, 140, {"1": "+1V8",    "2": "GND"}, stub_u=1)
    place_part("C_0603", "C23", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 182, 147, {"1": "+3V0_SD", "2": "GND"}, stub_u=1)

    place_part(
        "DM3D-SF", "J1", "DM3D-SF",
        "Connector_Card:Hirose_DM3D-SF_microSD", "DM3D-SF", 210, 118,
        {
            "1": "SD_D2_3V", "2": "SD_D3_3V", "3": "SD_CMD_3V", "4": "+3V0_SD",
            "5": "SD_CLK_3V", "6": "GND", "7": "SD_D0_3V", "8": "SD_D1_3V",
            "SW1": "SD_CD", "SW2": "GND", "SH1": "GND", "SH2": "GND", "SH3": "GND", "SH4": "GND",
        },
        stub_u=1,
    )
    place_part("C_0603", "C24", "100nF", "Resistor_SMD:R_0603_1608Metric", "CL10B104KB8NNNC", 210, 140, {"1": "+3V0_SD", "2": "GND"}, stub_u=1)

    lib_block = "\n".join(LIB_DEFS.values())
    items_block = "\n".join(SCH_ITEMS)

    return f"""(kicad_sch
  (version 20231120)
  (generator "pocket_recorder_sch_gen")
  (generator_version "1.0")
  (uuid "{ROOT_UUID}")
  (paper "A2")
  (title_block
    (title "Low-Power Outdoor Audio Recorder")
    (date "2026-11-23")
    (rev "1.0")
    (comment 1 "STM32U595RJT6Q (drop-in U5A5/U585/U575 Q) | 1.8V Always-On | 32kHz PDM | microSD")
    (comment 2 "PCBWay 4-Layer 1.6mm Matte-Black ENIG | 30.0 x 48.0 mm R1.5mm")
  )
  (lib_symbols
{lib_block}
  )
{items_block}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


if __name__ == "__main__":
    sch_path = os.path.join(OUT_DIR, f"{PROJECT_NAME}.kicad_sch")
    with open(sch_path, "w", encoding="utf-8") as f:
        f.write(build_schematic())
    print(f"Generated matching KiCad 8/9 schematic -> {sch_path}")
