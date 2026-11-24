#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p gerbers_pcbway
kicad-cli pcb drc --severity-all --output gerbers_pcbway/drc_report.rpt usb_adapter.kicad_pcb || true
kicad-cli pcb export gerbers \
  --output gerbers_pcbway/ \
  --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,F.Paste,B.Paste,Edge.Cuts" \
  --use-drill-file-origin \
  --subtract-soldermask \
  --check-zones \
  usb_adapter.kicad_pcb
kicad-cli pcb export drill \
  --output gerbers_pcbway/ \
  --format excellon \
  --drill-origin plot \
  --excellon-units mm \
  --excellon-separate-th \
  --generate-map \
  usb_adapter.kicad_pcb
rm -f usb_adapter_pcbway_gerbers.zip
(cd gerbers_pcbway && zip -r ../usb_adapter_pcbway_gerbers.zip .)
echo "Done -> usb_adapter_hw/usb_adapter_pcbway_gerbers.zip"
