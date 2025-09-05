from .ui_colors import COLOR_INFO, COLOR_RESET

def show_status(message: str):
    """Show a single-line status message, overwriting the current line."""
    status_width = 80  # Pad to clear previous text
    print(f"\r\033[K{COLOR_INFO}{message:<{status_width}}{COLOR_RESET}", end="", flush=True)

def clear_status():
    """Clear the current status line."""
    print("\r\033[K", end="", flush=True) 