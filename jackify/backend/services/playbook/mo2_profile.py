"""
Read the active MO2 profile name from ModOrganizer.ini - the playbook system's `mo2_profiles`
match signal (section 3.2). Moved here from the old vnv_integration_helper.py once VNV/MEW's
own automation controllers were retired in favor of the generic playbook system; this parsing
was never actually VNV-specific.
"""
import configparser
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

def _parse_bytearray_value(value: str) -> str:
    """
    Parse Qt @ByteArray format to extract the actual string value.

    Format: @ByteArray(Viva New Vegas Extended)
    Returns: Viva New Vegas Extended
    """
    match = re.match(r'@ByteArray\((.*)\)', value)
    return match.group(1) if match else value


def get_selected_mo2_profile(modlist_install_location: Path) -> Optional[str]:
    """Read the raw selected_profile value from ModOrganizer.ini, or None if unavailable."""
    try:
        mo_ini_path = modlist_install_location / "ModOrganizer.ini"
        if not mo_ini_path.exists():
            return None
        config = configparser.ConfigParser()
        config.read(mo_ini_path, encoding='utf-8-sig')
        if 'General' not in config:
            return None
        selected_profile_raw = config.get('General', 'selected_profile', fallback='')
        if not selected_profile_raw:
            return None
        return _parse_bytearray_value(selected_profile_raw)
    except Exception as e:
        logger.debug(f"Error reading selected_profile from ModOrganizer.ini: {e}")
        return None
