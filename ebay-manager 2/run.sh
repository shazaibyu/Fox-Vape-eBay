#!/bin/bash
# Run this from inside the ebay-manager folder: ./run.sh
set -e

if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "Starting eBay Seller Manager at http://localhost:8000"
echo "Press Ctrl+C to stop."
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000
