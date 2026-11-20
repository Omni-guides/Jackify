"""
Manual download support for wabbajack-cli.

The CLI stops with exit code 3 and prints one entry per file it could not fetch itself
(non-premium Nexus accounts, mostly). parse_manual_block() reads those entries, and
build_manual_events() turns them into the events the manual download dialog already
consumes, filling the gaps (exact size, hash, mod and file IDs) from the .wabbajack file.
"""
import base64
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_TIMESTAMPED_RE = re.compile(r'^\d+:\d{2}:\d{2}(?:\.\d+)?\s+\[(\w+)\]\s?(.*)$')
_HEADER_RE = re.compile(r'^\d+ files? must be downloaded by hand into .+ before installing:?$')
_ENTRY_RE = re.compile(r'^(?P<name>.+) \((?P<size>[\d.]+\s?[KMGT]?B)\): (?P<reason>.+)$')
_SIZE_RE = re.compile(r'^([\d.]+)\s?([KMGT]?B)$', re.IGNORECASE)
_UNITS = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}


@dataclass
class ManualItem:
    name: str
    size_text: str
    reason: str
    url: str = ""
    instructions: str = ""


def _size_bytes(text: str) -> int:
    m = _SIZE_RE.match(text.strip())
    return int(float(m.group(1)) * _UNITS[m.group(2).upper()]) if m else 0


class ManualBlockParser:
    """Incremental reader for the CLI's manual download listing."""

    def __init__(self):
        self.items: List[ManualItem] = []
        self._active = False

    def consume(self, line: str) -> bool:
        """Feed one output line. Returns True when the line belongs to the listing."""
        stripped = line.strip()
        m = _TIMESTAMPED_RE.match(stripped)
        if m is None:
            return self._continuation(stripped)
        text = m.group(2).strip()
        if _HEADER_RE.match(text):
            self._active = True
            self.items = []
            return True
        if not self._active:
            return False
        entry = _ENTRY_RE.match(text)
        if entry:
            self.items.append(ManualItem(entry.group('name'), entry.group('size'), entry.group('reason')))
            return True
        self._active = False
        return False

    def _continuation(self, stripped: str) -> bool:
        if not self._active or not self.items or not stripped:
            return False
        item = self.items[-1]
        if stripped.startswith(('http://', 'https://')) and not item.url:
            item.url = stripped
        else:
            item.instructions = f"{item.instructions} {stripped}".strip()
        return True


def find_wabbajack_file(modlist: str, downloads_dir: str) -> Optional[Path]:
    """The .wabbajack the CLI used: the file passed in, or its copy in the downloads folder."""
    if modlist.endswith('.wabbajack') and Path(modlist).is_file():
        return Path(modlist)
    candidate = Path(downloads_dir) / (modlist.replace('/', '_@@_') + '.wabbajack')
    return candidate if candidate.is_file() else None


def load_archives(wabbajack_path: Optional[Path]) -> Dict[str, dict]:
    """Archive records from a .wabbajack file, keyed by archive name."""
    if wabbajack_path is None:
        return {}
    try:
        with zipfile.ZipFile(wabbajack_path) as zf:
            modlist = json.loads(zf.read('modlist'))
        return {a['Name']: a for a in modlist.get('Archives', []) if 'Name' in a}
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        logger.warning("Could not read archive details from %s: %s", wabbajack_path, e)
        return {}


def _hash_hex(wabbajack_hash: str) -> str:
    try:
        return base64.b64decode(wabbajack_hash).hex()
    except (ValueError, TypeError):
        return ""


def build_manual_events(
    items: List[ManualItem],
    archives: Dict[str, dict],
    loop_iteration: int = 1,
) -> List[dict]:
    """Events in the shape the manual download dialog expects."""
    events = []
    for index, item in enumerate(items, start=1):
        archive = archives.get(item.name, {})
        state = archive.get('State') or {}
        events.append({
            'file_name': item.name,
            'nexus_url': item.url,
            'expected_hash': _hash_hex(archive.get('Hash', '')),
            'expected_size': archive.get('Size') or _size_bytes(item.size_text),
            'mod_name': state.get('Name') or item.name,
            'mod_id': state.get('ModID', 0),
            'file_id': state.get('FileID', 0),
            'game_name': state.get('GameName', ''),
            'reason': item.reason,
            'index': index,
            'total': len(items),
            'loop_iteration': loop_iteration,
        })
    return events
