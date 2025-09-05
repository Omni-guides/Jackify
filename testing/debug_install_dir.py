#!/usr/bin/env python3

import sys
import os
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def simulate_install_dir_processing():
    """Simulate the exact path processing that happens in the Install a Modlist workflow."""
    
    # Simulate the context that would be passed to the engine
    context = {
        'install_dir': Path("/home/deck/Games/Fallout/WOD"),
        'download_dir': Path("/home/deck/Games/Fallout/Downloads")
    }
    
    print("=== Simulating Install a Modlist workflow path processing ===")
    print(f"Original context['install_dir']: {context['install_dir']}")
    print(f"Original context['install_dir'] type: {type(context['install_dir'])}")
    
    # Simulate the path processing from modlist_operations.py lines 615-625
    install_dir_context = context['install_dir']
    print(f"install_dir_context: {install_dir_context}")
    print(f"install_dir_context type: {type(install_dir_context)}")
    
    if isinstance(install_dir_context, tuple):
        actual_install_path = Path(install_dir_context[0])
        if install_dir_context[1]:  # Second element is True if creation was intended
            print(f"Creating install directory as it was marked for creation: {actual_install_path}")
            actual_install_path.mkdir(parents=True, exist_ok=True)
    else:  # Should be a Path object or string already
        actual_install_path = Path(install_dir_context)
    
    print(f"actual_install_path: {actual_install_path}")
    print(f"actual_install_path type: {type(actual_install_path)}")
    
    install_dir_str = str(actual_install_path)
    print(f"install_dir_str: {install_dir_str}")
    print(f"install_dir_str type: {type(install_dir_str)}")
    
    # Now simulate what gets passed to the configuration context
    config_context = {
        'name': 'WOD',
        'appid': '12345',
        'path': install_dir_str,  # This is the key line!
        'mo2_exe_path': '/path/to/mo2.exe',
        'resolution': '1920x1080',
        'skip_confirmation': True,
        'manual_steps_completed': False
    }
    
    print(f"\nconfig_context['path']: {config_context['path']}")
    print(f"config_context['path'] type: {type(config_context['path'])}")
    
    # Check if there's any corruption
    if 'D' in config_context['path'] and '/WOD/D/' in config_context['path']:
        print("🚨 FOUND THE BUG! The path contains the extra 'D' segment!")
        print(f"Expected: /home/deck/Games/Fallout/WOD")
        print(f"Actual:   {config_context['path']}")
    else:
        print("✅ Path looks correct - no extra 'D' segment found")
    
    # Now simulate the Configure New Modlist workflow for comparison
    print("\n=== Simulating Configure New Modlist workflow ===")
    gui_context = {
        'modlist_name': 'WOD',
        'install_dir': '/home/deck/Games/Fallout/WOD',  # Direct from GUI
        'mo2_exe_path': '/path/to/mo2.exe',
        'resolution': '1920x1080'
    }
    
    gui_config_context = {
        'name': gui_context.get('modlist_name', ''),
        'path': gui_context.get('install_dir', ''),  # Direct from context
        'mo2_exe_path': gui_context.get('mo2_exe_path', ''),
        'modlist_value': gui_context.get('modlist_value'),
        'modlist_source': gui_context.get('modlist_source'),
        'resolution': gui_context.get('resolution'),
        'skip_confirmation': True,
        'manual_steps_completed': False
    }
    
    print(f"gui_config_context['path']: {gui_config_context['path']}")
    print(f"gui_config_context['path'] type: {type(gui_config_context['path'])}")
    
    # Compare the two paths
    print(f"\n=== Comparison ===")
    print(f"Install a Modlist path: {config_context['path']}")
    print(f"Configure New Modlist path: {gui_config_context['path']}")
    print(f"Paths are {'DIFFERENT' if config_context['path'] != gui_config_context['path'] else 'IDENTICAL'}")

if __name__ == "__main__":
    simulate_install_dir_processing()




