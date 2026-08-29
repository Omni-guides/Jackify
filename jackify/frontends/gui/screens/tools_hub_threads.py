"""
Background QThread workers for the Tools Hub screen.

Split out of tools_hub.py to keep that file under the size guardrail - these are
self-contained workers with no UI code, just network/install calls and a completion signal.
"""
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from jackify.backend.services.tool_registry import (
    ToolRegistry, fetch_release_list, fetch_remote_manifest, get_effective_definitions,
)
from jackify.backend.services.update_service import UpdateService

logger = logging.getLogger(__name__)


class VersionCheckThread(QThread):
    version_ready = Signal(str, str)   # tool_id, latest_tag

    def run(self):
        registry = ToolRegistry()
        for defn in get_effective_definitions():
            try:
                tag = registry.check_latest_version(defn.tool_id)
                self.version_ready.emit(defn.tool_id, tag or "unknown")
            except Exception as e:
                logger.debug("Version check failed for %s: %s", defn.tool_id, e)
                self.version_ready.emit(defn.tool_id, "unknown")


class ToolActionThread(QThread):
    finished_signal = Signal(str, bool, str)   # tool_id, success, message

    def __init__(self, tool_id: str, action: str, version: Optional[str] = None):
        super().__init__()
        self._tool_id = tool_id
        self._action = action
        self._version = version

    def run(self):
        registry = ToolRegistry()
        try:
            if self._action == "install":
                ok, msg = registry.install(self._tool_id, version=self._version)
            elif self._action == "update":
                ok, msg = registry.update(self._tool_id)
            elif self._action == "uninstall":
                ok, msg = registry.uninstall(self._tool_id)
            else:
                ok, msg = False, f"Unknown action: {self._action}"
        except Exception as e:
            ok, msg = False, str(e)
        self.finished_signal.emit(self._tool_id, ok, msg)


class ArchiveInstallThread(QThread):
    finished_signal = Signal(str, bool, str)   # tool_id, success, message

    def __init__(self, tool_id: str, archive_path: Path):
        super().__init__()
        self._tool_id = tool_id
        self._archive_path = archive_path

    def run(self):
        try:
            ok, msg = ToolRegistry().install_from_archive(self._tool_id, self._archive_path)
        except Exception as e:
            ok, msg = False, str(e)
        self.finished_signal.emit(self._tool_id, ok, msg)


class ManifestFetchThread(QThread):
    manifest_ready = Signal(list)   # List[ToolDefinition]

    def run(self):
        result = fetch_remote_manifest()
        if result:
            self.manifest_ready.emit(result)


class ReleaseFetchThread(QThread):
    releases_ready = Signal(str, list)   # tool_id, List[dict]

    def __init__(self, tool_id: str, github_repo: str):
        super().__init__()
        self._tool_id = tool_id
        self._github_repo = github_repo

    def run(self):
        releases = fetch_release_list(self._github_repo)
        self.releases_ready.emit(self._tool_id, releases)


class IconFetchThread(QThread):
    icon_ready = Signal(str, object)   # tool_id, Path

    def __init__(self, tool_ids_and_repos: List[Tuple[str, str]]):
        super().__init__()
        self._tool_ids_and_repos = tool_ids_and_repos

    def run(self):
        from jackify.backend.services.tool_icons import fetch_and_cache_icon
        for tool_id, repo in self._tool_ids_and_repos:
            path = fetch_and_cache_icon(tool_id, repo)
            if path:
                self.icon_ready.emit(tool_id, path)


class JackifyUpdateCheckThread(QThread):
    update_ready = Signal(object)   # UpdateInfo or None

    def __init__(self, update_service: UpdateService):
        super().__init__()
        self._update_service = update_service

    def run(self):
        try:
            update_info = self._update_service.check_for_updates()
        except Exception as e:
            logger.debug("Jackify update check failed: %s", e)
            update_info = None
        self.update_ready.emit(update_info)
