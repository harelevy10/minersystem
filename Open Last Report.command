#!/bin/bash
# Double-click this to instantly open the last generated report (no re-screening).
cd "$(dirname "$0")" || exit 1
if [ -f output/report.html ]; then
  open output/report.html
else
  echo "No report found yet. Run 'Update Screener.command' first."
  echo "Press any key to close..."
  read -n 1
fi
