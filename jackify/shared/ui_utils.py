"""
UI Utilities for Jackify
Shared UI components and utilities used across frontend interfaces
"""

import os
import sys

def clear_screen():
    """
    Clear the terminal screen with AppImage compatibility.
    
    This function provides robust screen clearing that works in various environments
    including AppImage containers where standard terminal utilities might not work properly.
    """
    try:
        # Method 1: Try standard os.system approach first
        if os.name == 'nt':
            # Windows
            result = os.system('cls')
        else:
            # Unix/Linux - try clear command
            result = os.system('clear')
        
        # If os.system failed (non-zero return), try fallback methods
        if result != 0:
            _clear_screen_fallback()
            
    except Exception:
        # If os.system completely fails, use fallback
        _clear_screen_fallback()

def _clear_screen_fallback():
    """
    Fallback screen clearing methods for environments where os.system doesn't work.
    This is particularly useful in AppImage environments.
    """
    try:
        # Method 2: ANSI escape sequences (works in most terminals)
        # \033[H moves cursor to home position (0,0)
        # \033[2J clears entire screen
        # \033[3J clears scroll buffer (optional, not all terminals support)
        print('\033[H\033[2J\033[3J', end='', flush=True)
    except Exception:
        try:
            # Method 3: Alternative ANSI sequence
            print('\033c', end='', flush=True)  # Full terminal reset
        except Exception:
            # Method 4: Last resort - print enough newlines to "clear" screen
            print('\n' * 50)

def print_jackify_banner():
    """Print the Jackify application banner"""
    print("""
╔════════════════════════════════════════════════════════════════════════╗
║                         Jackify CLI (pre-alpha)                        ║
║                                                                        ║
║            A tool for installing and configuring modlists              ║
║                     & associated utilities on Linux                    ║
╚════════════════════════════════════════════════════════════════════════╝
""")

def print_section_header(title):
    """Print a section header with formatting"""
    print(f"\n{'='*30}\n{title}\n{'='*30}\n")

def print_subsection_header(title):
    """Print a subsection header with formatting"""
    print(f"[ {title} ]\n") 