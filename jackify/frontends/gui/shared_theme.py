"""
Jackify GUI theme and shared constants
"""
import os

JACKIFY_COLOR_BLUE = "#3fd0ea"  # Official Jackify blue
DEBUG_BORDERS = False  # Enable debug borders to visualize widget boundaries
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')
LOGO_PATH = os.path.join(ASSETS_DIR, 'jackify_logo.png')
DISCLAIMER_TEXT = (
    "Jackify is provided as-is. Back up your modlist and game data before making changes. "
    "The developers are not responsible for data loss or other issues arising from its use."
)