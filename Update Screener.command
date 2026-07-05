#!/bin/bash
# Double-click this to run a fresh S&P 500 screen and open the HTML report.
# Edit the line below to change the universe (sp500 / nasdaq100 / russell2000)
# or screen specific tickers, e.g.:  python3 generate_html.py --tickers NVDA AAPL MSFT
cd "$(dirname "$0")" || exit 1
echo "Running Minervini screen — this can take a few minutes on first run..."
/usr/bin/python3 generate_html.py --universe sp500
echo ""
echo "Done. You can close this window."
