#!/usr/bin/env python3
"""
Main entry point for Jackify package.
Launches the GUI by default.
"""

import sys
import os

# Add the src directory to the Python path
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

def main():
    """Main entry point - launch GUI by default"""
    from jackify.frontends.gui.main import main as gui_main
    return gui_main()

if __name__ == "__main__":
    main()
