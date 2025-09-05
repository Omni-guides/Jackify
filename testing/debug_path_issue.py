#!/usr/bin/env python3

import sys
import os
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_path_construction():
    """Test the exact path construction that's happening in the bug."""
    
    # Simulate the path that should be passed
    install_dir_str = "/home/deck/Games/Fallout/WOD"
    modlist_dir_path = Path(install_dir_str)
    
    print(f"Original install_dir_str: {install_dir_str}")
    print(f"modlist_dir_path: {modlist_dir_path}")
    print(f"modlist_dir_path type: {type(modlist_dir_path)}")
    
    # Simulate the path construction in edit_binary_working_paths
    drive_prefix = "Z:"
    rel_path = "Stock Game/f4se_loader.exe"
    
    new_binary_path = f"{drive_prefix}/{modlist_dir_path}/{rel_path}".replace('\\', '/').replace('//', '/')
    
    print(f"drive_prefix: {drive_prefix}")
    print(f"rel_path: {rel_path}")
    print(f"new_binary_path: {new_binary_path}")
    
    # Check if there's any string manipulation happening
    print(f"modlist_dir_path string: '{str(modlist_dir_path)}'")
    print(f"modlist_dir_path parts: {list(modlist_dir_path.parts)}")
    
    # Test with the exact path from the ModOrganizer.ini
    print("\n--- Testing with actual ModOrganizer.ini path ---")
    actual_path = "Z:/home/deck/Games/Fallout/WOD/D/Stock Game/f4se_loader.exe"
    print(f"Actual path from ModOrganizer.ini: {actual_path}")
    
    # Try to reconstruct this path
    parts = actual_path.split('/')
    print(f"Path parts: {parts}")
    
    # The issue is that there's a "D" segment that shouldn't be there
    if "D" in parts:
        d_index = parts.index("D")
        print(f"Found 'D' at index {d_index}: {parts[d_index]}")
        print(f"Parts before 'D': {parts[:d_index]}")
        print(f"Parts after 'D': {parts[d_index+1:]}")
        
        # Reconstruct without the D
        correct_parts = parts[:d_index] + parts[d_index+1:]
        correct_path = '/'.join(correct_parts)
        print(f"Correct path should be: {correct_path}")

if __name__ == "__main__":
    test_path_construction()




