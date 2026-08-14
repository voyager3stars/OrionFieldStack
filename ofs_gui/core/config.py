import os
import sys

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHUTTERPRO_PATH = os.path.join(BASE_DIR, "shutterpro03", "shutterpro03.py")
SSE_PATH = os.path.join(BASE_DIR, "SSE", "SSE.py")
STARFLUX_PATH = os.path.join(BASE_DIR, "starflux", "starflux.py")
STARFORGE_PATH = os.path.join(BASE_DIR, "starforge", "starforge.py")
SKYSYNC_PATH = os.path.join(BASE_DIR, "skysync", "skysync.py")
GUI_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ofs_gui_sp03_config.json")

def get_sse_python():
    # Use the GUI's own python environment which is verified to have all dependencies
    return sys.executable

def get_starflux_python():
    # Use the starflux virtual environment if available to run starflux
    venv_python = os.path.join(BASE_DIR, "starflux", "venv", "bin", "python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable

def get_starforge_python():
    # Use the starforge virtual environment if available to run starforge
    venv_python = os.path.join(BASE_DIR, "starforge", "venv", "bin", "python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable

def get_ofs_link_python():
    # Use the ofs_link virtual environment if available to run ofs_link
    venv_python = os.path.join(BASE_DIR, "ofs_link", "venv", "bin", "python")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable
