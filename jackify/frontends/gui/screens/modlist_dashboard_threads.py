"""Background worker threads for the Modlist Lifecycle Dashboard."""
import logging
from typing import Dict

from PySide6.QtCore import QThread, Signal

from jackify.backend.services.install_registry import InstallEntry
from jackify.backend.services.modlist_uninstall_service import uninstall_modlist

logger = logging.getLogger(__name__)


class GalleryVersionFetchThread(QThread):
    # machine_url -> version, lowercased title -> metadata, machine_url -> metadata, error or ""
    versions_ready = Signal(dict, dict, dict, str)

    def run(self):
        versions: Dict[str, str] = {}
        by_title: Dict[str, object] = {}
        by_machine_url: Dict[str, object] = {}
        error = ""
        try:
            from jackify.backend.services.modlist_gallery_service import ModlistGalleryService
            metadata = ModlistGalleryService().fetch_modlist_metadata(
                include_validation=False, include_search_index=False,
            )
            if metadata:
                for modlist in metadata.modlists:
                    # entry.machine_url is always stored as namespacedName ("Author/Slug") -
                    # both install-time capture (install_modlist_selection.py) and the
                    # identity backfill use that field - not the bare machineURL slug, which
                    # is a different, shorter string. Keying these dicts by machineURL meant
                    # gallery_versions.get(entry.machine_url) could never match anything.
                    if getattr(modlist, "namespacedName", None) and getattr(modlist, "version", None):
                        versions[modlist.namespacedName] = modlist.version
                    if getattr(modlist, "title", None):
                        by_title[modlist.title.lower()] = modlist
                    if getattr(modlist, "namespacedName", None):
                        by_machine_url[modlist.namespacedName] = modlist
            else:
                error = "No response from the modlist gallery."
        except Exception as e:
            logger.warning("Dashboard gallery version fetch failed: %s", e)
            error = str(e)
        self.versions_ready.emit(versions, by_title, by_machine_url, error)


class UninstallThread(QThread):
    finished_uninstall = Signal(bool, str)
    progress = Signal(str)

    def __init__(self, entry: InstallEntry, parent=None):
        super().__init__(parent)
        self._entry = entry

    def run(self):
        try:
            success, message = uninstall_modlist(self._entry, progress_callback=self.progress.emit)
        except Exception as e:
            logger.error("Uninstall failed for %s: %s", self._entry.modlist_name, e, exc_info=True)
            success, message = False, str(e)
        self.finished_uninstall.emit(success, message)
