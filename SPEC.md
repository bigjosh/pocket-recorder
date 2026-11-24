# Low-power recorder board: specification

Goal is to produce a ready to build hardware design that includes BOM wiht links to order parts, and fully routed PCB gerber file set. 

## 1. Purpose

A small, battery-powered audio recorder that records continuously outdoors with no housing, is downloaded and recharged over USB every few days.

## 2. Recording

| ID | Requirement |
|---|---|
| R1 | Continuous mono recording at 32 kHz, 16 bit . |
| R2 | Microphone: TDK T5837 bottom-port PDM MEMS (low-power mode, about 120 µA, 65.5 dBA noise, -21 dBFS at 94 dB SPL). The footprint also takes the T5838. |
| R3 | The microphone hears through a 0.60 mm unplated hole in the board. |
| R4 | Captured by the processor's digital filter (ADF1) and DMA while the processor sleeps in Stop 2, buffered in RAM, written to storage in bursts. |
| R5 | No buck-converter or charger switching noise in recordings: both at least 30 mm from the microphone. |

## 3. Power and battery life

| ID | Requirement |
|---|---|
| P1 | Cell: one LiPo, today 500 mAh, 30.8 x 49.5 x 2.9 mm; similar cells up to about 3 mm thick may be used. |
| P2 | 3 to 7 days between downloads on 500 mAh. |
| P4 | Charging from USB overnight, with power path (the recorder runs from USB while charging). |
| P5 | Rails: 1.8 V always on. |
| P6 | The cell is hard-wired to two solder pads. No reverse-battery protection: polarity is checked with a meter before soldering, cable out. |

## 4. Storage and timekeeping

| ID | Requirement |
|---|---|
| S1 | Low power SD card. |
| S2 | Real-time clock: Micro Crystal RV-3032-C7 (±2.5 ppm), which also supplies the 32.768 kHz clock to the processor. |

## 5. Processor

| ID | Requirement |
|---|---|
| M1 | STM32U5A5RJT6Q, LQFP64, 1.8 V, internal switching regulator. Only the "Q" (SMPS) variants are allowed; the U595, U585 and U575 "Q" parts fit the same footprint. |

## 6. Connections on the outward face

| ID | Requirement |
|---|---|
| C1 | No USB socket on the board. USB and debug go through one cluster of seven pads on the outward face, reached by two pogo-pin adapter boards (USB and debug) that clamp on the board's edges. No locating holes. |
| C2 | Pads 3.0 x 3.0 mm, bare gold, each with a via in its centre; 6.0 mm pitch, 3.0 mm gaps between all pads. |
| C3 | Seen from the outward face, row 1 (nearer a short edge): GND, D+, D-, 5V. Row 2: SWDIO, NRST, SWCLK, each centred under a gap of row 1. Pad names in silkscreen. |
| C4 | The cluster goes at whichever short edge suits routing. |
| C5 | The outward ground pour keeps 1.0 mm from every bare pad except GND. |
| C6 | USB data protected by an ESD part (ST USBLC6-2SC6) beside the pads. No ESD part on the debug pads. |
| C7 | The debug adapter supplies its probe's 1.8 V reference itself (no 1.8 V pad in the cluster). |
| C8 | Any mounted board can be reflashed through SWD with connect-under-reset. |

## 7. User interface

| ID | Requirement |
|---|---|
| U1 | No buttons. After boot, the SWDIO and SWCLK pads are two user buttons (internal pull-ups; a short to GND with metal or a jumper presses one). Reset by shorting NRST to GND. BOOT0 is strapped low: the USB loader is entered only from firmware. |
| U2 | One RGB LED, reverse-mount (SunLED XZMDKCBDDG45S-9), on the parts side shining through a 0.60 mm hole. Red, green and blue each through a resistor (2.2 kΩ, 1 kΩ, 1 kΩ) straight to a processor pin, open-drain, about 1 mA per colour. |
| U3 | The LED hole and the sound hole are in line, 7.5 mm apart, each inside a 6.6 mm silkscreen circle. |

## 8. Mechanical

| ID | Requirement |
|---|---|
| X1 | Outline at most 30.0 x 48.0 mm, corners R1.5 mm, inside the cell's outline. |
| X2 | Four layers, 1.6 mm, ENIG. |
| X3 | All part on one side. The board is glued parts-side-down onto the cell (foam tape or silicone) and sealed by a silicone bead between board and cell under its rim; a 1.0 mm band along every edge on the parts side stays free of parts. |
| X5 | Test and debug pads (including a 2 x 4 debug group with 1.8 V, SWD, reset, UART and the microphone clock) are on the parts side, for bench work before the board is mounted. |
| X6 | The outward face has a simplified line art thumbprint, life sized, centered. The seven pads are at the top edge of the of board reltive to the orientation of the fingerprint, the two holes are cin a horazonal row that is horazonally centered on the face and vertically placed midpoint between the top fo the finger print and the bottom of the pads.  |
| X7 | A 6 mm disc round the sound hole stays flat solder mask (no silkscreen, via or pad), for an optional acoustic vent sticker. |

## 9. Environment

| ID | Requirement |
|---|---|
| E1 | Outdoor use with no housing. The parts side is sealed by the bead. |
| E2 | The sound hole may be covered later by an ePTFE acoustic vent (first choice Gore AVP4342.04.0, IPx8); the board does not depend on it. |

## 10. Manufacturing and sourcing

| ID | Requirement |
|---|---|
| F1 | Parts listed above are recommendations - alternates can be condiered.  |
| F2 | All parts in final design must be available in stock from Digit or Mouser. |
| F3 | Hand-solderable parts prefered. Note that I consider the RV3032 to be hand solcerable because all pads are along the edge and so reachable and inspectable. |


## 11. Platform

Final output as a DipTRACE project is the prefered output format, but KiCAD acceptable if nessisary.
