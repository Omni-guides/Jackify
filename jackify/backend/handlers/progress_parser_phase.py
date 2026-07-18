"""Phase extraction methods for ProgressParser (Mixin)."""

import logging
import re
from typing import Optional, Tuple

from jackify.shared.progress_models import InstallationPhase

logger = logging.getLogger(__name__)


class ProgressParserPhaseMixin:
    """Mixin providing phase extraction methods."""

    def _extract_phase(self, line: str) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase information from line."""
        section_match = re.search(r'===?\s*(.+?)\s*===?', line)
        if section_match:
            section_name = section_match.group(1).strip().lower()
            phase = self._map_section_to_phase(section_name)
            return (phase, section_match.group(1).strip())

        # [FILE_PROGRESS] lines drive file activity only - skip phase extraction for them
        if '[FILE_PROGRESS]' in line:
            return None

        # Make the [timestamp] prefix optional - engine no longer emits it.
        action_match = re.search(
            r'(?:\[.*?\]\s*)?(Installing|Downloading|Extracting|Validating|Processing|Checking existing)',
            line,
            re.IGNORECASE
        )
        if action_match:
            action = action_match.group(1).lower()
            phase = self._map_action_to_phase(action)
            return (phase, action_match.group(1))

        return None

    def _extract_phase_from_section(self, match: re.Match) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase from section header match."""
        section_name = match.group(1).strip().lower()
        phase = self._map_section_to_phase(section_name)
        return (phase, match.group(1).strip())

    def _extract_phase_from_action(self, match: re.Match) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase from action match."""
        action = match.group(1).lower()
        phase = self._map_action_to_phase(action)
        return (phase, match.group(1))

    def _map_section_to_phase(self, section_name: str) -> InstallationPhase:
        """Map section name to InstallationPhase enum."""
        section_lower = section_name.lower()
        if 'hash' in section_lower or 'validate' in section_lower or 'verif' in section_lower:
            return InstallationPhase.VALIDATE
        elif 'download' in section_lower:
            return InstallationPhase.DOWNLOAD
        elif 'extract' in section_lower:
            return InstallationPhase.EXTRACT
        elif 'install' in section_lower:
            return InstallationPhase.INSTALL
        elif 'bsa' in section_lower or 'building' in section_lower:
            return InstallationPhase.INSTALL
        elif 'finaliz' in section_lower or 'complet' in section_lower:
            return InstallationPhase.FINALIZE
        elif ('configur' in section_lower or 'initializ' in section_lower
              or 'looking' in section_lower or 'cleaning' in section_lower
              or 'unmodified' in section_lower or 'updating' in section_lower
              or 'folder' in section_lower or 'delete' in section_lower):
            return InstallationPhase.INITIALIZATION
        else:
            return InstallationPhase.UNKNOWN

    def _map_action_to_phase(self, action: str) -> InstallationPhase:
        """Map action word to InstallationPhase enum."""
        action_lower = action.lower()
        if 'download' in action_lower:
            return InstallationPhase.DOWNLOAD
        elif 'extract' in action_lower:
            return InstallationPhase.EXTRACT
        elif 'validat' in action_lower or 'checking' in action_lower:
            return InstallationPhase.VALIDATE
        elif 'install' in action_lower:
            return InstallationPhase.INSTALL
        else:
            return InstallationPhase.UNKNOWN

    def _extract_phase_from_text(self, text: str) -> Optional[Tuple[InstallationPhase, str]]:
        """Extract phase from status text like 'Installing files'."""
        text_lower = text.lower()

        if 'download' in text_lower:
            return (InstallationPhase.DOWNLOAD, text)
        elif 'extract' in text_lower:
            return (InstallationPhase.EXTRACT, text)
        elif 'validat' in text_lower or 'hash' in text_lower:
            return (InstallationPhase.VALIDATE, text)
        elif 'install' in text_lower:
            return (InstallationPhase.INSTALL, text)
        elif 'prepar' in text_lower or 'configur' in text_lower:
            return (InstallationPhase.INITIALIZATION, text)
        elif 'finish' in text_lower or 'complet' in text_lower:
            return (InstallationPhase.FINALIZE, text)
        else:
            return (InstallationPhase.UNKNOWN, text)
