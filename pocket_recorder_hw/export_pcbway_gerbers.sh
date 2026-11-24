#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p gerbers_pcbway
echo "Running KiCad DRC..."
kicad-cli pcb drc --severity-all --output gerbers_pcbway/drc_report.rpt pocket_recorder.kicad_pcb || true
echo "Exporting PCBWay 4-Layer Gerbers (incl. approved F.SilkS icon artwork)..."
kicad-cli pcb export gerbers \
  --output gerbers_pcbway/ \
  --layers "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,B.Paste,Edge.Cuts" \
  --use-drill-file-origin \
  --subtract-soldermask \
  --check-zones \
  pocket_recorder.kicad_pcb
kicad-cli pcb export drill \
  --output gerbers_pcbway/ \
  --format excellon \
  --drill-origin plot \
  --excellon-units mm \
  --excellon-separate-th \
  --generate-map \
  pocket_recorder.kicad_pcb
rm -f pocket_recorder_pcbway_gerbers.zip
(cd gerbers_pcbway && zip -r ../pocket_recorder_pcbway_gerbers.zip .)
echo "Done -> pocket_recorder_hw/pocket_recorder_pcbway_gerbers.zip"
