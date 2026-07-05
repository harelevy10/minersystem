#!/bin/bash
cd "$(dirname "$0")"
read -p "Enter a stock symbol: " TICKER
python3 analyze.py "$TICKER"
echo
read -p "Press Enter to close..."
