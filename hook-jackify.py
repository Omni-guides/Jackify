# Custom hook to exclude temp directory from Jackify engine data collection
from PyInstaller.utils.hooks import collect_data_files
import os

def hook(hook_api):
    # Get the original data files for jackify.engine
    datas = collect_data_files('jackify.engine')
    
    # Filter out any files in the temp directory
    filtered_datas = []
    for src, dst in datas:
        # Skip any files that contain 'temp' in their path
        if 'temp' not in src:
            filtered_datas.append((src, dst))
    
    # Set the filtered data files
    hook_api.add_datas(filtered_datas) 