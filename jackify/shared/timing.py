"""
Simple shared timing for consistent progress timestamps across all Jackify services.
"""
import time
import re

# Global state for shared timing
_start_time = None
_base_offset = 0

def initialize_from_console_output(console_text: str = None):
    """Initialize timing, optionally continuing from jackify-engine output"""
    global _start_time, _base_offset
    
    if _start_time is not None:
        return  # Already initialized
    
    if console_text:
        # Parse last timestamp from jackify-engine
        timestamp_pattern = r'\[(\d{2}):(\d{2}):(\d{2})\]'
        matches = list(re.finditer(timestamp_pattern, console_text))
        
        if matches:
            last_match = matches[-1]
            hours = int(last_match.group(1))
            minutes = int(last_match.group(2))
            seconds = int(last_match.group(3))
            _base_offset = hours * 3600 + minutes * 60 + seconds + 1
    
    _start_time = time.time()

def continue_from_timestamp(timestamp_str: str):
    """Continue timing from a specific timestamp string like '[00:00:31]'"""
    global _start_time, _base_offset
    
    # Parse timestamp like [00:00:31]
    timestamp_pattern = r'\[(\d{2}):(\d{2}):(\d{2})\]'
    match = re.match(timestamp_pattern, timestamp_str)
    
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        _base_offset = hours * 3600 + minutes * 60 + seconds + 1
        _start_time = time.time()
    else:
        # Fallback to normal initialization
        initialize_from_console_output()

def start_new_phase():
    """Start a new phase with timing reset to [00:00:00]"""
    global _start_time, _base_offset
    _start_time = time.time()
    _base_offset = 0

def set_base_offset_from_installation_end():
    """Set base offset to continue from where Installation phase typically ends"""
    global _start_time, _base_offset
    
    # Installation phase typically ends around 1-2 minutes, so start from 1:30
    _base_offset = 90  # 1 minute 30 seconds
    _start_time = time.time()

def get_timestamp():
    """Get current timestamp in [HH:MM:SS] format"""
    global _start_time, _base_offset
    
    if _start_time is None:
        initialize_from_console_output()
    
    elapsed = int(time.time() - _start_time)
    total_seconds = _base_offset + elapsed
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    return f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"

def reset():
    """Reset timing (for testing)"""
    global _start_time, _base_offset
    _start_time = None
    _base_offset = 0