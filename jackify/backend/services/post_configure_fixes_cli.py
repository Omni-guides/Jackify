"""JContainers and problem-mod CLI post-configure fixes, shared by every CLI entry point that
runs a modlist's configuration phase (--configure-modlist, the interactive install/reconfigure
menu). Previously copy-pasted per entry point, which is exactly how the interactive menu flow
ended up missing both fixes entirely - confirmed live (2026-09-08): a Dialogue History reinstall
through that path silently never created its save folder, since nothing here had ever been
wired into it. GUI reaches its own equivalent via InstallVerifierMixin instead of this module.
"""

import logging
from pathlib import Path
from typing import Optional

from jackify.shared.colors import COLOR_INFO, COLOR_PROMPT, COLOR_RESET, COLOR_WARNING

logger = logging.getLogger(__name__)


def apply_jcontainers_and_problem_mods_fixes(install_dir: str, app_id: Optional[str]) -> None:
    """Prompts for the JContainers DLL fix if needed, then disables known-problematic mods and
    creates any prefix directories they require (e.g. Dialogue History's Saves folder).

    Re-detects game type from the install's own ModOrganizer.ini rather than trusting a
    caller-passed value, which can be stale - the same ground-truth principle already
    established for this exact fix (see problem_mods_service.detect_game_type_from_install_dir).
    """
    from jackify.backend.services.problem_mods_service import detect_game_type_from_install_dir
    game_type = detect_game_type_from_install_dir(install_dir) or ''

    try:
        from jackify.backend.handlers.modlist_fixup_handler import (
            check_jcontainers_needs_fix,
            apply_jcontainers_fix,
        )
        if check_jcontainers_needs_fix(Path(install_dir), game_type):
            print(f"\n{COLOR_WARNING}JContainers Compatibility Fix{COLOR_RESET}")
            print(f"{COLOR_INFO}The mod JContainers has been detected. The Nexusmods version is known to cause crashes on Linux/Proton.{COLOR_RESET}")
            print(f"{COLOR_INFO}A fixed version is available from the mod's GitHub page. The original DLL will be backed up first.{COLOR_RESET}")
            try:
                user_input = input(f"{COLOR_PROMPT}Apply JContainers fix now? (Y/n): {COLOR_RESET}").strip().lower()
            except (EOFError, KeyboardInterrupt):
                user_input = "n"
            if user_input in ("", "y", "yes"):
                apply_jcontainers_fix(Path(install_dir), game_type)
                print(f"{COLOR_INFO}JContainers fix applied.{COLOR_RESET}")
            else:
                print(f"{COLOR_INFO}JContainers fix skipped.{COLOR_RESET}")
    except Exception as e:
        logger.warning("JContainers fix check failed (non-fatal): %s", e)

    try:
        from jackify.backend.services.install_verifier_service import resolve_pfx_for_appid
        from jackify.backend.services.problem_mods_service import (
            disable_problem_mods,
            create_prefix_dirs,
            get_enabled_mods,
        )
        all_disabled: list = []
        all_enabled_mods: set = set()
        for modlist_txt in Path(install_dir).glob("profiles/*/modlist.txt"):
            disabled = disable_problem_mods(modlist_txt, game_type)
            for name in disabled:
                if name not in all_disabled:
                    all_disabled.append(name)
            all_enabled_mods |= get_enabled_mods(modlist_txt)
        if all_disabled:
            print(f"{COLOR_INFO}Disabled known-problematic mod(s): {', '.join(all_disabled)}{COLOR_RESET}")
            logger.info(
                "Disabled %d problem mod(s) (%s): %s",
                len(all_disabled), game_type, ", ".join(all_disabled),
            )
        pm_pfx = resolve_pfx_for_appid(str(app_id)) if app_id else None
        if pm_pfx and all_enabled_mods:
            created = create_prefix_dirs(pm_pfx, game_type, all_enabled_mods)
            if created:
                logger.info(
                    "Created %d prefix dir(s) (%s): %s",
                    len(created), game_type, ", ".join(created),
                )
    except Exception as e:
        logger.warning("Problem mods fix check failed (non-fatal): %s", e)
