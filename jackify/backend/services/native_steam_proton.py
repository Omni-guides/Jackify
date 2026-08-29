"""
Proton version assignment via direct config.vdf text manipulation.

Split out of native_steam_service.py to keep that file under the project's size guardrail -
this is a large, fully self-contained piece of logic (just needs a Steam path in, bool out).
"""
import glob
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def set_proton_version(steam_path: Path, app_id: int, proton_version: str = "proton_experimental") -> bool:
    """
    Set the Proton version for a specific app using ONLY config.vdf like steam-conductor does.

    Args:
        steam_path: The active Steam installation's userdata-adjacent root (NativeSteamService.steam_path)
        app_id: The unsigned AppID
        proton_version: The Proton version to set

    Returns:
        True if successful
    """
    logger.info(f"Setting Proton version '{proton_version}' for AppID {app_id} using STL-compatible format")

    try:
        # Step 1: Write to the main config.vdf for CompatToolMapping
        config_path = steam_path / "config" / "config.vdf"

        if not config_path.exists():
            logger.error(f"Steam config.vdf not found at: {config_path}")
            return False

        # Create backup first
        backup_dir = config_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"config_{int(time.time())}.bak"
        shutil.copy2(config_path, backup_path)
        logger.info(f"Created backup: {backup_path}")
        existing = sorted(glob.glob(str(backup_dir / "config_*.bak")))
        for old in existing[:-5]:
            try:
                os.remove(old)
            except Exception:
                pass

        # Read the file as text to avoid VDF library formatting issues
        with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
            config_text = f.read()

        # Find the CompatToolMapping section
        compat_start = config_text.find('"CompatToolMapping"')
        if compat_start == -1:
            logger.warning("CompatToolMapping section not found in config.vdf, creating it")
            # Find the Steam section to add CompatToolMapping to
            steam_section = config_text.find('"Steam"')
            if steam_section == -1:
                logger.error("Steam section not found in config.vdf")
                return False

            # Find the opening brace for Steam section
            steam_brace = config_text.find('{', steam_section)
            if steam_brace == -1:
                logger.error("Steam section opening brace not found")
                return False

            # Insert CompatToolMapping section right after Steam opening brace
            insert_pos = steam_brace + 1
            compat_section = '\n\t\t"CompatToolMapping"\n\t\t{\n\t\t}\n'
            config_text = config_text[:insert_pos] + compat_section + config_text[insert_pos:]

            # Update compat_start position after insertion
            compat_start = config_text.find('"CompatToolMapping"')
            logger.info("Created CompatToolMapping section in config.vdf")

        # Find the closing brace for CompatToolMapping
        # Look for the opening brace after CompatToolMapping
        brace_start = config_text.find('{', compat_start)
        if brace_start == -1:
            logger.error("CompatToolMapping opening brace not found")
            return False

        # Count braces to find the matching closing brace
        brace_count = 1
        pos = brace_start + 1
        compat_end = -1

        while pos < len(config_text) and brace_count > 0:
            if config_text[pos] == '{':
                brace_count += 1
            elif config_text[pos] == '}':
                brace_count -= 1
                if brace_count == 0:
                    compat_end = pos
                    break
            pos += 1

        if compat_end == -1:
            logger.error("CompatToolMapping closing brace not found")
            return False

        # Check if this AppID already exists - if so, remove its whole entry before
        # appending the new one. VDF readers (including get_proton_version_display,
        # below) return the first matching key in a section, so leaving the old entry in
        # place and appending a second one for the same AppID is silently ignored - the
        # UI would keep reporting the old Proton version after every change to an AppID
        # that already had a mapping, which is exactly what a stale duplicate looks like.
        app_id_pattern = f'"{app_id}"'
        search_region = config_text[compat_start:compat_end]
        entry_start_rel = search_region.find(app_id_pattern)
        if entry_start_rel != -1:
            entry_start = compat_start + entry_start_rel
            entry_brace_start = config_text.find('{', entry_start)
            entry_brace_count = 1
            pos = entry_brace_start + 1
            entry_end = -1
            while pos < len(config_text) and entry_brace_count > 0:
                if config_text[pos] == '{':
                    entry_brace_count += 1
                elif config_text[pos] == '}':
                    entry_brace_count -= 1
                    if entry_brace_count == 0:
                        entry_end = pos + 1
                        break
                pos += 1
            if entry_end != -1:
                logger.info(f"AppID {app_id} already exists in CompatToolMapping, removing old entry before writing new one")
                config_text = config_text[:entry_start] + config_text[entry_end:]
                compat_end -= (entry_end - entry_start)
            else:
                logger.warning(f"Could not find closing brace for existing AppID {app_id} entry - appending anyway")

        # Create the new entry in STL's exact format (tabs between key and value)
        new_entry = f'\t\t\t\t\t"{app_id}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"name"\t\t"{proton_version}"\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t\t"priority"\t\t"250"\n\t\t\t\t\t}}\n'

        # Insert the new entry just before the closing brace of CompatToolMapping
        new_config_text = config_text[:compat_end] + new_entry + config_text[compat_end:]

        # Write back the modified text
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_config_text)

        logger.info(f"Successfully set Proton version '{proton_version}' for AppID {app_id} using config.vdf only (steam-conductor method)")
        return True

    except Exception as e:
        logger.error(f"Error setting Proton version: {e}")
        return False
