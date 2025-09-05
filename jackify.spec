# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['jackify/frontends/gui/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[('jackify/engine', 'jackify/engine'), ('jackify/shared', 'jackify/shared'), ('assets/JackifyLogo_256.png', 'assets')],
    hiddenimports=[
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 
        'jackify.backend.core', 'jackify.backend.handlers', 'jackify.backend.services', 'jackify.backend.models',
        'jackify.backend.handlers.resolution_handler', 'jackify.backend.handlers.modlist_handler',
        'jackify.backend.handlers.menu_handler', 'jackify.backend.handlers.path_handler',
        'jackify.frontends.cli', 'jackify.frontends.cli.main',
        'jackify.frontends.cli.menus', 'jackify.frontends.cli.menus.main_menu',
        'jackify.frontends.cli.menus.tuxborn_menu', 'jackify.frontends.cli.menus.wabbajack_menu',
        'jackify.frontends.gui.widgets.unsupported_game_dialog',
        'jackify.shared.paths', 'jackify.shared.ui_utils'
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas', 'IPython', 'jupyter', 'test', 'tests', 'unittest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='jackify',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/JackifyLogo_256.png',
)
