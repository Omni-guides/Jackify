"""
Main window startup and background tasks mixin.
Gallery cache preload, protontricks check, update check.
"""

import sys

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QDialog
import logging

logger = logging.getLogger(__name__)

class MainWindowStartupMixin:
    """Mixin for startup and background tasks."""

    def _start_gallery_cache_preload(self):
        from PySide6.QtCore import QThread, Signal

        class GalleryCachePreloadThread(QThread):
            finished_signal = Signal(bool, str)

            def run(self):
                try:
                    from jackify.backend.services.modlist_gallery_service import ModlistGalleryService
                    service = ModlistGalleryService()
                    metadata = service.fetch_modlist_metadata(
                        include_validation=False,
                        include_search_index=True,
                        sort_by="title",
                        force_refresh=False
                    )
                    if metadata:
                        modlists_with_mods = sum(1 for m in metadata.modlists if hasattr(m, 'mods') and m.mods)
                        if modlists_with_mods > 0:
                            logger.debug(f"Gallery cache ready ({modlists_with_mods} modlists with mods)")
                        else:
                            logger.debug("Gallery cache updated")
                    else:
                        logger.debug("Failed to load gallery cache")
                except Exception as e:
                    logger.debug(f"Gallery cache preload error: {str(e)}")

        self._gallery_cache_preload_thread = GalleryCachePreloadThread()
        self._gallery_cache_preload_thread.start()
        logger.debug("Started background gallery cache preload")

    def _check_protontricks_on_startup(self):
        try:
            method = self.config_handler.get('component_installation_method', 'native')
            if method != 'system_protontricks':
                logger.debug(f"Skipping protontricks check (current method: {method}).")
                return
            is_installed, installation_type, details = self.protontricks_service.detect_protontricks()
            if not is_installed:
                logger.warning(f"Protontricks not found: {details}")
                from jackify.frontends.gui.dialogs.protontricks_error_dialog import ProtontricksErrorDialog
                dialog = ProtontricksErrorDialog(self.protontricks_service, self)
                result = dialog.exec()
                if result == QDialog.Rejected:
                    logger.info("User chose to exit due to missing protontricks")
                    sys.exit(1)
            else:
                logger.debug(f"Protontricks detected: {details}")
        except Exception as e:
            logger.error(f"Error checking protontricks: {e}")

    def _check_tool_updates_on_startup(self):
        class _ToolUpdateCheckThread(QThread):
            updates_found = Signal(bool)

            def run(self):
                try:
                    from jackify.backend.services.tool_registry import ToolRegistry, get_effective_definitions
                    registry = ToolRegistry()
                    for defn in get_effective_definitions():
                        if defn.pinned_version is not None:
                            continue
                        status = registry.get_status(defn.tool_id)
                        if not status or not status.installed:
                            continue
                        logger.debug(
                            "Startup tool update check: %s installed=%s version=%s",
                            defn.tool_id, status.installed, status.installed_version,
                        )
                        tag = registry.check_latest_version(defn.tool_id)
                        logger.debug("Startup tool update check: %s latest=%s", defn.tool_id, tag)
                        if tag and status.installed_version and tag.lstrip("v") != status.installed_version.lstrip("v"):
                            logger.debug("Startup tool update check: update available for %s", defn.tool_id)
                            self.updates_found.emit(True)
                            return
                    self.updates_found.emit(False)
                except Exception as e:
                    logger.warning("Tool update check failed: %s", e, exc_info=True)
                    self.updates_found.emit(False)

        def on_result(has_updates: bool):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: (
                self.main_menu.notify_tool_updates(has_updates)
                if hasattr(self, 'main_menu') and hasattr(self.main_menu, 'notify_tool_updates')
                else None
            ))

        self._tool_update_check_thread = _ToolUpdateCheckThread()
        self._tool_update_check_thread.updates_found.connect(on_result)
        self._tool_update_check_thread.start()

    def _prefetch_manifests_on_startup(self):
        class _ManifestPrefetchThread(QThread):
            def run(self):
                try:
                    from jackify.backend.services.tool_registry import (
                        fetch_remote_manifest as fetch_tools,
                        apply_remote_manifest as apply_tools,
                    )
                    tools = fetch_tools()
                    if tools:
                        apply_tools(tools)
                        logger.info("Tools manifest refreshed at startup (%d tools)", len(tools))
                    else:
                        logger.info("Tools manifest prefetch returned no data (bundled manifest in use)")
                except Exception as e:
                    logger.info("Tools manifest prefetch failed: %s", e)

                try:
                    from jackify.backend.services.problem_mods_service import (
                        fetch_remote_manifest as fetch_problems,
                        apply_remote_manifest as apply_problems,
                    )
                    problems = fetch_problems()
                    if problems:
                        apply_problems(problems)
                        logger.info("Problem mods manifest refreshed at startup")
                    else:
                        logger.info("Problem mods manifest prefetch returned no data (bundled manifest in use)")
                except Exception as e:
                    logger.info("Problem mods manifest prefetch failed: %s", e)

                try:
                    from jackify.backend.services.playbook.hook_wiring import get_registry
                    if get_registry().sync():
                        logger.info("Playbook registry refreshed at startup")
                    else:
                        logger.info("Playbook registry prefetch unreachable (cached/bundled set in use)")
                except Exception as e:
                    logger.info("Playbook registry prefetch failed: %s", e)

        self._manifest_prefetch_thread = _ManifestPrefetchThread()
        self._manifest_prefetch_thread.start()

    def _check_for_updates_on_startup(self):
        try:
            logger.debug("Checking for updates on startup...")

            class UpdateCheckThread(QThread):
                update_available = Signal(object)

                def __init__(self, update_service):
                    super().__init__()
                    self.update_service = update_service

                def run(self):
                    update_info = self.update_service.check_for_updates()
                    if update_info:
                        self.update_available.emit(update_info)

            def on_update_available(update_info):
                logger.debug(f"Update available: v{update_info.version}")

                def show_update_dialog():
                    from jackify.frontends.gui.dialogs.update_dialog import UpdateDialog
                    dialog = UpdateDialog(update_info, self.update_service, self)
                    dialog.exec()
                QTimer.singleShot(1000, show_update_dialog)

            self._update_thread = UpdateCheckThread(self.update_service)
            self._update_thread.update_available.connect(on_update_available)
            self._update_thread.start()
        except Exception as e:
            logger.debug(f"Error setting up update check: {e}")
