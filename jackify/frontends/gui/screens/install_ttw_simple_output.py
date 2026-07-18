"""
Simplified output handler for TTW installation - minimal filtering, maximum stability
This is a reference implementation showing the absolute minimum needed.
"""

def on_installation_output_simple(self, message):
    """
    Ultra-simplified output handler:
    - Strip emojis (required)
    - Show all output (no filtering)
    - Extract progress numbers for Activity window only
    - No regex except for simple number extraction
    """
    # Strip ANSI codes
    cleaned = strip_ansi_control_codes(message).strip()
    
    # Strip emojis - character by character (no regex)
    filtered_chars = []
    for char in cleaned:
        code = ord(char)
        is_emoji = (
            (0x1F300 <= code <= 0x1F9FF) or
            (0x1F600 <= code <= 0x1F64F) or
            (0x2600 <= code <= 0x26FF) or
            (0x2700 <= code <= 0x27BF)
        )
        if not is_emoji:
            filtered_chars.append(char)
    cleaned = ''.join(filtered_chars).strip()
    
    if not cleaned:
        return
    
    # Log everything
    self._write_to_log_file(message)
    
    # Show everything in console (no filtering)
    self._safe_append_text(cleaned)
    
    # Extract progress for Activity window ONLY - minimal regex with error handling
    # Pattern: "Progress: NN%" or "Loading manifest: <path>"
    try:
        import re
        match = re.search(r'Progress:\s*(\d+)%', cleaned)
        if match:
            percent = int(match.group(1))
            self._update_ttw_activity(percent, 100, percent)

        if 'loading manifest:' in cleaned.lower():
            self._ttw_current_phase = "Loading manifest"
    except (RecursionError, re.error, Exception):
        # If regex fails, just skip progress extraction - show output anyway
        pass
