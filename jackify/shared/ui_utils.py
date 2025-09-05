"""
UI Utilities for Jackify
Shared UI components and utilities used across frontend interfaces
"""

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