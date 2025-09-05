"""
completers.py
Reusable tab completion functions for Jackify CLI, including bash-like path completion.
"""

import os
import readline
import logging # Added for debugging

# Get a logger for this module
completer_logger = logging.getLogger(__name__) # Logger will be named src.modules.completers

# Set level to DEBUG for this logger to ensure all debug messages are generated.
# These messages will be handled by handlers configured in the main application (e.g., via LoggingHandler).
completer_logger.setLevel(logging.INFO)

# Ensure messages DO NOT propagate to the root logger's console handler by default.
# A dedicated file handler will be added in jackify-cli.py.
completer_logger.propagate = False 

# IMPORTANT: Do NOT include '/' in the completer delimiters!
# Use: readline.set_completer_delims(' \t\n;')

def path_completer(text, state):
    """
    Bash-like pathname completer for readline.
    Args:
        text: The text to complete (provided by readline, e.g., "/foo/b" or "b" or "")
        state: The state index (0 for first match, 1 for second, etc.)
    Returns:
        The matching completion string that should replace 'text', or None.
    """
    line_buffer = readline.get_line_buffer()
    begidx = readline.get_begidx()
    endidx = readline.get_endidx()
    
    effective_text_for_completion = line_buffer[:endidx]
    expanded_effective_text = os.path.expanduser(os.path.expandvars(effective_text_for_completion))

    # Special case: if text is an exact directory (no trailing slash), complete to text + '/'
    if os.path.isdir(text) and not text.endswith(os.sep):
        if state == 0:
            return text + os.sep
        else:
            return None

    # Normal completion logic
    if os.path.isdir(expanded_effective_text):
        disk_basedir = expanded_effective_text
        disk_item_prefix = ""
    else:
        disk_basedir = os.path.dirname(expanded_effective_text)
        disk_item_prefix = os.path.basename(expanded_effective_text)
    if not disk_basedir:
        disk_basedir = "."

    matched_item_names_on_disk = []
    try:
        if not os.path.exists(disk_basedir) or not os.path.isdir(disk_basedir):
            completer_logger.warning(f"  Disk basedir '{disk_basedir}' non-existent or not a dir. No disk matches.")
        else:
            dir_contents = os.listdir(disk_basedir)
            for item_name in dir_contents:
                if item_name.startswith(disk_item_prefix):
                    matched_item_names_on_disk.append(item_name)
    except OSError as e:
        completer_logger.error(f"  OSError listing '{disk_basedir}': {e}")

    final_match_strings_for_readline = []
    text_dir_part = os.path.dirname(text)
    # If text is a directory with trailing slash, use it as the base for completions
    if os.path.isdir(text) and text.endswith(os.sep):
        base_path = text
    elif os.path.isdir(text):
        base_path = text + os.sep
    else:
        base_path = text_dir_part + os.sep if text_dir_part else ""

    for item_name in matched_item_names_on_disk:
        result_str_for_readline = os.path.join(base_path, item_name)
        actual_disk_path_of_item = os.path.join(disk_basedir, item_name)
        if os.path.isdir(actual_disk_path_of_item):
            result_str_for_readline += os.sep
        final_match_strings_for_readline.append(result_str_for_readline)
    final_match_strings_for_readline.sort()
    try:
        match = final_match_strings_for_readline[state]
        completer_logger.debug(f"  Returning match for state {state}: '{match}'")
        return match
    except IndexError:
        return None
    except Exception as e:
        completer_logger.exception(f"  Unexpected error retrieving match for state {state}: {e}")
        return None 