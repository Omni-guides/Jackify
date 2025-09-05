"""
Jackify GUI theme and shared constants
"""
import os

JACKIFY_COLOR_BLUE = "#3fd0ea"  # Official Jackify blue
DEBUG_BORDERS = False
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')
LOGO_PATH = os.path.join(ASSETS_DIR, 'jackify_logo.png')
DISCLAIMER_TEXT = (
    "Disclaimer: Jackify is currently in an alpha state. This software is provided as-is, "
    "without any warranty or guarantee of stability. By using Jackify, you acknowledge that you do so at your own risk. "
    "The developers are not responsible for any data loss, system issues, or other problems that may arise from its use. "
    "Please back up your data and use caution."
) 