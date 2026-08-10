"""Download helpers for the native Wine component installer.

Multi-source fetching with integrity checking, split out of
native_component_installer.py to keep that module within the file size limit.
"""

import hashlib
import logging
import time
import urllib.request
from pathlib import Path
from typing import Sequence, Union

logger = logging.getLogger(__name__)


class ComponentDownloadMixin:
    """Fetches component payloads. Expects the host class to provide `logger`,
    `_emit_status()` and, where relevant, `_current_component`."""

    def _download_file(self, url: Union[str, Sequence[str]], dest: Path,
                       sha256: Union[str, Sequence[str]] = "") -> bool:
        urls = [url] if isinstance(url, str) else list(url)

        if dest.is_file():
            if not sha256:
                return True
            if self._verify_sha256(dest, sha256):
                return True
            self.logger.warning("SHA256 mismatch on cached %s, re-downloading", dest.name)
            dest.unlink()

        for index, candidate in enumerate(urls):
            if not self._download_from_url(candidate, dest):
                continue
            if sha256 and not self._verify_sha256(dest, sha256):
                self.logger.error("SHA256 mismatch on %s from %s", dest.name, candidate)
                dest.unlink()
                continue
            return True

        self.logger.error("All %d source(s) failed for %s", len(urls), dest.name)
        return False

    def _download_from_url(self, url: str, dest: Path) -> bool:
        """Download to a .part file and rename only once the transfer is verifiably
        complete, so an interrupted download can never be left behind and trusted as a
        cached copy on the next run."""
        component = getattr(self, '_current_component', dest.stem)
        self.logger.info("Downloading %s ...", dest.name)
        self._emit_status(f"Downloading {dest.name}...")
        partial = dest.with_name(dest.name + '.part')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Jackify/1.0'})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get('Content-Length', 0) or 0)
                downloaded = 0
                start = time.monotonic()
                last_emit = start
                chunk_size = 65536
                with open(partial, 'wb') as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        if total > 0 and now - last_emit >= 0.5:
                            pct = downloaded / total * 100.0
                            elapsed = now - start
                            speed = downloaded / elapsed / 1048576.0 if elapsed > 0.05 else 0.0
                            self._emit_status(f"[NATIVE_DL] {component} {pct:.1f} {speed:.1f}")
                            last_emit = now

            if downloaded == 0:
                self.logger.error("Download from %s produced an empty file", url)
                partial.unlink(missing_ok=True)
                return False
            if total > 0 and downloaded != total:
                self.logger.error(
                    "Truncated download from %s: got %d bytes, expected %d",
                    url, downloaded, total,
                )
                partial.unlink(missing_ok=True)
                return False

            partial.replace(dest)
            return True
        except Exception as exc:
            self.logger.error("Download failed for %s: %s", url, exc)
            partial.unlink(missing_ok=True)
            return False

    def _verify_sha256(self, path: Path, expected: Union[str, Sequence[str]]) -> bool:
        accepted = {expected.lower()} if isinstance(expected, str) else {e.lower() for e in expected}
        h = hashlib.sha256()
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
            return h.hexdigest().lower() in accepted
        except Exception:
            return False

    def _discard_cached_installer(self, path: Path) -> None:
        """Drop a cached installer that Wine refused to run. The redist URLs are not
        version-pinned, so a corrupt cached copy is otherwise re-used on every retry and
        no amount of re-running configuration would clear it."""
        try:
            path.unlink(missing_ok=True)
            self.logger.info("Discarded cached installer %s so the next attempt re-downloads", path.name)
        except Exception as exc:
            self.logger.debug("Could not discard cached installer %s: %s", path.name, exc)

