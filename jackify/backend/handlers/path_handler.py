#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Path Handler Module
Handles path-related operations for ModOrganizer.ini and other configuration files.
Logic split into mixins: MO2, DXVK, Steam, Game.
"""

from .path_handler_mo2 import (
    PathHandlerMO2Mixin,
    TARGET_EXECUTABLES_LOWER,
    STOCK_GAME_FOLDERS,
)
from .path_handler_dxvk import PathHandlerDXVKMixin
from .path_handler_steam import PathHandlerSteamMixin
from .path_handler_game import PathHandlerGameMixin

__all__ = [
    'PathHandler',
    'TARGET_EXECUTABLES_LOWER',
    'STOCK_GAME_FOLDERS',
]


class PathHandler(
    PathHandlerMO2Mixin,
    PathHandlerDXVKMixin,
    PathHandlerSteamMixin,
    PathHandlerGameMixin,
):
    """Handles path-related operations. MO2, DXVK, Steam, and Game logic in mixins."""
