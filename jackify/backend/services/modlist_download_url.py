"""Look up a modlist's CDN download URL from the gallery metadata cache.

Shared by CLF3's fetch step (modlist_operations_configuration_cli.py) and the CLI discovery
flow's fail-fast check (frontends/cli/menus/modlist_discovery.py) - both need to know, for a
given machine_url, whether CLF3 has anything to download before committing to it.
"""

import json
import logging
from typing import Optional

from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)


def get_modlist_download_url(machine_name: str) -> Optional[str]:
    """Return the cached CDN download URL for a gallery modlist, or None if not found."""
    list_id = machine_name.split('/')[-1] if '/' in machine_name else machine_name
    cache_file = get_jackify_data_dir() / "modlist-cache" / "metadata" / "modlist_metadata.json"
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not read modlist metadata cache: %s", e)
        return None
    for entry in data.get("modlists", []):
        if entry.get("namespacedName") == machine_name or entry.get("machineURL") == list_id:
            return (entry.get("links") or {}).get("download")
    return None
