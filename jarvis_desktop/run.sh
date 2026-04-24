#!/bin/bash

set -e

unset OPENAI_API_KEY

echo "🤖 J.A.R.V.I.S. WebSocket Edition"
echo "=================================="
echo ""

if [ ! -f "main.py" ]; then
    echo "❌ Error: Please run this script from jarvis_desktop directory"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found"
    echo "Please create one with OPENAI_API_KEY=your_key"
    exit 1
fi

echo "🌐 Starting WebSocket bridge on ws://localhost:8000"
echo "🎯 Make sure the React frontend is running:"
echo "   cd ../jarvis-ui && npm run dev"
echo ""

python main.py "$@"
