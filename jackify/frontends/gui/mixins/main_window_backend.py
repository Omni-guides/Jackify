"""
Main window backend initialization mixin.
System info, config, modlist service, protontricks service, resource limits.
"""

import os

from jackify.backend.models.configuration import SystemInfo
from jackify.backend.services.modlist_service import ModlistService
import logging

logger = logging.getLogger(__name__)

class MainWindowBackendMixin:
    """Mixin for backend service initialization."""

    def _initialize_backend(self):
        from jackify.shared.steam_utils import detect_steam_installation_types
        is_flatpak, is_native = detect_steam_installation_types()
        self.system_info = SystemInfo(
            is_steamdeck=self._is_steamdeck(),
            is_flatpak_steam=is_flatpak,
            is_native_steam=is_native
        )
        self._apply_resource_limits()
        from jackify.backend.handlers.config_handler import ConfigHandler
        self.config_handler = ConfigHandler()
        self.backend_services = {'modlist_service': ModlistService(self.system_info)}
        self.gui_services = {}
        from jackify.backend.services.protontricks_detection_service import ProtontricksDetectionService
        self.protontricks_service = ProtontricksDetectionService(steamdeck=self.system_info.is_steamdeck)
        from jackify.backend.services.update_service import UpdateService
        from jackify import __version__
        self.update_service = UpdateService(__version__)

        from jackify.backend.services.nxm_ipc import NxmIpcServer
        self._nxm_ipc_server = NxmIpcServer(self)
        self._nxm_ipc_server.url_received.connect(self._on_nxm_url_received)
        self._nxm_ipc_server.start()

        from jackify.backend.services.nxm_protocol import ensure_nxm_registered
        ensure_nxm_registered()

        logger.debug(f"GUI Backend initialized - Steam Deck: {self.system_info.is_steamdeck}")

    def _is_steamdeck(self):
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    content = f.read()
                    if "steamdeck" in content:
                        return True
            return False
        except Exception:
            return False

    def _apply_resource_limits(self):
        try:
            from jackify.backend.services.resource_manager import ResourceManager
            resource_manager = ResourceManager()
            success = resource_manager.apply_recommended_limits()
            if success:
                status = resource_manager.get_limit_status()
                if status['target_achieved']:
                    logger.debug(f"Resource limits optimized: file descriptors set to {status['current_soft']}")
                else:
                    logger.info(f"Resource limits improved: file descriptors increased to {status['current_soft']} (target: {status['target_limit']})")
            else:
                status = resource_manager.get_limit_status()
                logger.warning(f"Could not optimize resource limits: current file descriptors={status['current_soft']}, target={status['target_limit']}")
                from jackify.backend.handlers.config_handler import ConfigHandler
                config_handler = ConfigHandler()
                if config_handler.get('debug_mode', False):
                    instructions = resource_manager.get_manual_increase_instructions()
                    logger.debug(f"Manual increase instructions available for {instructions['distribution']}")
        except Exception as e:
            logger.warning(f"Error applying resource limits: {e}")
