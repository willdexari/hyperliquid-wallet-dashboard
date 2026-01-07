#!/bin/bash
# Helper script to run the Streamlit dashboard

# Check if streamlit is available
if command -v streamlit &> /dev/null; then
    streamlit run src/ui/app.py
elif [ -x "/Users/willyb/Library/Python/3.9/bin/streamlit" ]; then
    /Users/willyb/Library/Python/3.9/bin/streamlit run src/ui/app.py
else
    echo "Error: streamlit not found"
    echo "Install with: pip3 install streamlit plotly"
    exit 1
fi
