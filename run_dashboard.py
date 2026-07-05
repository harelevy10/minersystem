import os
import sys

project_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_dir)
sys.path.insert(0, project_dir)

from streamlit.web import cli as stcli
sys.argv = [
    "streamlit", "run",
    os.path.join(project_dir, "dashboard.py"),
    "--server.port=8501",
    "--server.headless=true"
]
sys.exit(stcli.main())
