#!/bin/bash
# Run the Stock App

# Load environment variables if .env exists
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the Streamlit app
streamlit run app.py --server.port 8501 --theme.base dark
