"""
Reader for the manual download listing CLF3 prints when it cannot fetch archives itself.

CLF3 exits 0 after printing the list, so the install looks successful unless the listing
is captured. The block looks like:

    Manual downloads needed (22), save them to /path/to/downloads:
    1. Some Archive.7z (68.9 MiB)
    https://example.com/files/file/123-some-archive/
    Note: optional author instructions
    ...
    Run the same command again once these archives are in place.
"""
import re
from dataclasses import dataclass
from typing import List, Optional

_TRACING_PREFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\S+\s+(?:INFO|WARN|ERROR)\s+\S+:\s+')
_HEADER_RE = re.compile(r'^Manual downloads needed \((\d+)\)(?:,\s*save them to (.+?))?:?$')
_ITEM_RE = re.compile(r'^(\d+)\.\s+(.+?)(?:\s+\(([^()]+)\))?$')
_URL_RE = re.compile(r'^https?://\S+')
_END_RE = re.compile(r'^Run the same command again')


@dataclass
class Clf3ManualItem:
    name: str
    size_text: str = ""
    url: str = ""
    note: str = ""


class Clf3ManualListParser:
    """Incremental parser: feed every CLF3 output line, read items once the block ends."""

    def __init__(self) -> None:
        self.items: List[Clf3ManualItem] = []
        self.expected_count: int = 0
        self.downloads_dir: str = ""
        self._active = False

    @property
    def found(self) -> bool:
        return self.expected_count > 0 or bool(self.items)

    def feed(self, line: str) -> bool:
        """Returns True when the line is part of the listing."""
        text = _TRACING_PREFIX_RE.sub('', line.strip())
        header = _HEADER_RE.match(text)
        if header:
            self._active = True
            self.items = []
            self.expected_count = int(header.group(1))
            self.downloads_dir = (header.group(2) or "").strip()
            return True
        if not self._active:
            return False
        if _END_RE.match(text):
            self._active = False
            return True
        if not text:
            return True
        if text.startswith('Note:'):
            if self.items:
                self.items[-1].note = text[len('Note:'):].strip()
            return True
        if _URL_RE.match(text):
            if self.items and not self.items[-1].url:
                self.items[-1].url = text.split()[0]
            return True
        item = _ITEM_RE.match(text)
        if item:
            self.items.append(Clf3ManualItem(name=item.group(2).strip(), size_text=item.group(3) or ""))
            return True
        self._active = False
        return False


def format_manual_summary(parser: Clf3ManualListParser, max_items: Optional[int] = None) -> str:
    """Plain text list of the files and where to get them."""
    count = parser.expected_count or len(parser.items)
    lines = [f"{count} file(s) must be downloaded by hand"
             + (f" into {parser.downloads_dir}" if parser.downloads_dir else "") + ":"]
    shown = parser.items if max_items is None else parser.items[:max_items]
    for i, item in enumerate(shown, 1):
        size = f" ({item.size_text})" if item.size_text else ""
        lines.append(f"{i}. {item.name}{size}")
        if item.url:
            lines.append(f"   {item.url}")
    if len(shown) < len(parser.items):
        lines.append(f"...and {len(parser.items) - len(shown)} more (see Show Details)")
    return "\n".join(lines)
