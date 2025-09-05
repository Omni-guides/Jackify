# Custom PyInstaller hook to optimize PySide6 by removing unused components
# This significantly reduces build size by excluding unnecessary Qt modules and tools

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os
import shutil
from pathlib import Path

def hook(hook_api):
    """
    PySide6 optimization hook - removes unused Qt modules and development tools
    to reduce build size and improve startup performance.
    """
    
    # Get the PySide6 data files
    pyside_datas = collect_data_files('PySide6')
    
    # Filter out unnecessary components
    filtered_datas = []
    
    for src, dst in pyside_datas:
        # Skip development tools and scripts
        if any(skip in src for skip in [
            '/scripts/',
            '/assistant/',
            '/designer/',
            '/linguist/',
            '/lupdate',
            '/lrelease',
            '/qmllint',
            '/qmlformat',
            '/qmlls',
            '/qsb',
            '/svgtoqml',
            '/balsam',
            '/balsamui'
        ]):
            continue
            
        # Skip unused Qt modules (keep only what Jackify uses)
        if any(skip in src for skip in [
            'Qt3D',
            'QtBluetooth',
            'QtCharts',
            'QtConcurrent',  # Keep this one - might be needed
            'QtDataVisualization',
            'QtDBus',
            'QtDesigner',
            'QtGraphs',
            'QtHelp',
            'QtHttpServer',
            'QtLocation',
            'QtMultimedia',
            'QtNfc',
            'QtOpenGL',  # Keep this one - might be needed by QtWidgets
            'QtPdf',
            'QtPositioning',
            'QtPrintSupport',
            'QtQml',
            'QtQuick',
            'QtRemoteObjects',
            'QtScxml',
            'QtSensors',
            'QtSerial',
            'QtSpatialAudio',
            'QtSql',
            'QtStateMachine',
            'QtSvg',
            'QtTest',
            'QtTextToSpeech',
            'QtWeb',
            'QtXml',
            'QtNetworkAuth',
            'QtUiTools'
        ]):
            continue
            
        # Keep core modules that Jackify uses
        if any(keep in src for keep in [
            'QtCore',
            'QtGui', 
            'QtWidgets',
            'QtNetwork'
        ]):
            filtered_datas.append((src, dst))
            continue
            
    # Add the filtered data files
    hook_api.add_datas(filtered_datas)
    
    # Also filter submodules to exclude unused ones
    pyside_modules = collect_submodules('PySide6')
    filtered_modules = []
    
    for module in pyside_modules:
        # Keep only core modules
        if any(keep in module for keep in [
            'PySide6.QtCore',
            'PySide6.QtGui',
            'PySide6.QtWidgets', 
            'PySide6.QtNetwork'
        ]):
            filtered_modules.append(module)
    
    # Add the filtered modules
    hook_api.add_imports(*filtered_modules)
