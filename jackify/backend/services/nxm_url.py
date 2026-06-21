"""NXM URL parser.

nxm://{game}/mods/{mod_id}/files/{file_id}?key=KEY&expires=TS&user_id=UID
"""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, parse_qs


@dataclass
class NxmUrl:
    game: str
    mod_id: int
    file_id: int
    key: str
    expires: str
    user_id: Optional[str] = None
    raw: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.game} / mod {self.mod_id} / file {self.file_id}"


def parse_nxm_url(url: str) -> NxmUrl:
    """Parse an nxm:// URL into its components.

    Raises ValueError if the URL is malformed.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() != "nxm":
        raise ValueError(f"Not an NXM URL: {url}")

    game = parsed.netloc.lower()
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    # Expected: ['mods', '{mod_id}', 'files', '{file_id}']
    if len(parts) < 4 or parts[0] != "mods" or parts[2] != "files":
        raise ValueError(f"Unexpected NXM URL path: {parsed.path}")

    try:
        mod_id = int(parts[1])
        file_id = int(parts[3])
    except ValueError:
        raise ValueError(f"Non-integer mod/file ID in NXM URL: {url}")

    params = parse_qs(parsed.query)
    key = params.get("key", [""])[0]
    expires = params.get("expires", [""])[0]
    user_id = params.get("user_id", [None])[0]

    return NxmUrl(
        game=game,
        mod_id=mod_id,
        file_id=file_id,
        key=key,
        expires=expires,
        user_id=user_id,
        raw=url,
    )
