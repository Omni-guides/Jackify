#!/usr/bin/env python3
import os
import random
import subprocess
import logging
import time

try:
    import readline  # For tab completion
except ModuleNotFoundError:
    readline = None
import glob
from pathlib import Path
import vdf
from typing import Optional, List, Dict, Callable, Tuple
import re
import shutil

# Import other necessary modules
from .protontricks_handler import ProtontricksHandler
from .vdf_handler import VDFHandler
from .path_handler import PathHandler
from .completers import path_completer

from .shortcut_vdf_management import ShortcutVDFManagementMixin
from .shortcut_creation import ShortcutCreationMixin
from .shortcut_steam_restart import ShortcutSteamRestartMixin
from .shortcut_discovery import ShortcutDiscoveryMixin
from .shortcut_launch_options import ShortcutLaunchOptionsMixin

logger = logging.getLogger(__name__)


class ShortcutHandler(
    ShortcutVDFManagementMixin,
    ShortcutCreationMixin,
    ShortcutSteamRestartMixin,
    ShortcutDiscoveryMixin,
    ShortcutLaunchOptionsMixin,
):
    """Handles creation and management of Steam shortcuts"""
    
    def __init__(self, steamdeck: bool, verbose: bool = False):
        """
        Initialize the ShortcutHandler.

        Args:
            steamdeck (bool): True if running on Steam Deck, False otherwise.
            verbose (bool): Controls verbose output for methods like secure_steam_restart.
        """
        self.logger = logging.getLogger(__name__)
        self.vdf_handler = VDFHandler()
        self.steamdeck = steamdeck
        self.verbose = verbose # Store verbose flag
        self.path_handler = PathHandler() # Add PathHandler instance
        self.shortcuts_path = self.path_handler._find_shortcuts_vdf() # Use PathHandler method
        self._last_shortcuts_backup = None # Track the last backup path
        self._safe_shortcuts_backup = None # Track backup made just before restart
        # Initialize ProtontricksHandler here, passing steamdeck status
        self.protontricks_handler = ProtontricksHandler(self.steamdeck)
        
    def _enable_tab_completion(self):
        """Enable tab completion for file paths using the shared completer"""
        if readline is None:
            self.logger.debug("readline module not available; disabling CLI tab completion")
            return
        readline.set_completer(path_completer)
        readline.set_completer_delims(' \t\n;')
        readline.parse_and_bind("tab: complete")

