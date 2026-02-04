#!/bin/bash
# Unset any incorrectly set Streamlit env vars
unset STREAMLIT_SERVER_PORT

PORT="${PORT:-8501}"
exec streamlit run app.py --server.port="$PORT" --server.address=0.0.0.0 --server.headless=true
