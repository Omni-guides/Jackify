"""List and manage registered modlists (CLI counterpart to the GUI Lifecycle Dashboard)."""
import json
import os
from typing import List, Optional

from jackify.shared.colors import (
    COLOR_ERROR, COLOR_INFO, COLOR_PROMPT, COLOR_RESET, COLOR_SELECTION,
    COLOR_SUCCESS, COLOR_WARNING,
)


class ModlistsCommand:
    """Handler for the `modlists` CLI command."""

    def add_parser(self, subparsers):
        p = subparsers.add_parser(
            "modlists",
            help="List and manage registered modlists (CLI counterpart to the GUI dashboard)",
        )
        p.add_argument("--json", action="store_true", help="Output as JSON instead of a table")
        return p

    def execute(self, args) -> int:
        if getattr(args, "json", False):
            return self._execute_json()
        return self._execute_interactive()

    def _execute_json(self) -> int:
        from jackify.backend.services.dashboard_status import resolve_all_statuses
        from jackify.backend.services.install_registry import backfill_from_shortcuts, mark_missing_installs

        try:
            backfill_from_shortcuts()
        except Exception:
            pass
        entries = mark_missing_installs()
        statuses = resolve_all_statuses(entries)
        rows = [
            {
                "install_id": e.install_id,
                "modlist_name": e.modlist_name,
                "game_type": e.game_type,
                "appid": e.appid,
                "installed_version": e.installed_version,
                "status": statuses.get(e.install_id),
                "install_dir": e.install_dir,
                "provenance": e.provenance,
            }
            for e in entries
        ]
        print(json.dumps(rows, indent=2))
        return 0

    def _execute_interactive(self) -> int:
        while True:
            entries, statuses = self._load_entries()
            if not entries:
                print(f"{COLOR_WARNING}No modlists registered yet.{COLOR_RESET}")
                print(f"{COLOR_INFO}Install or configure a modlist to have it appear here.{COLOR_RESET}")
                return 0

            self._print_table(entries, statuses)
            choice = input(
                f"\n{COLOR_PROMPT}Select a modlist to manage (number), or 0 to return: {COLOR_RESET}"
            ).strip()
            if choice == "0" or not choice:
                return 0
            if not choice.isdigit() or not (1 <= int(choice) <= len(entries)):
                print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
                continue

            entry = entries[int(choice) - 1]
            self._manage_entry(entry)

    def _load_entries(self):
        from jackify.backend.services.dashboard_status import resolve_all_statuses
        from jackify.backend.services.install_registry import backfill_from_shortcuts, mark_missing_installs

        try:
            backfill_from_shortcuts()
        except Exception:
            pass
        entries = mark_missing_installs()
        statuses = resolve_all_statuses(entries)
        return entries, statuses

    def _print_table(self, entries: List, statuses: dict) -> None:
        from jackify.backend.services.dashboard_status import get_proton_version_display

        name_w = max((len(e.modlist_name) for e in entries), default=20)
        name_w = max(name_w, 20)
        header = f"  {'#':<3}{'Modlist':<{name_w}}  {'Status':<18}  {'Version':<12}  {'Proton':<20}  AppID"
        print(f"\n{COLOR_SELECTION}{header}{COLOR_RESET}")
        print("-" * (name_w + 74))

        for i, e in enumerate(entries, 1):
            status = statuses.get(e.install_id, "unknown")
            proton = (get_proton_version_display(e.appid) if e.appid else None) or "-"
            version = e.installed_version or "-"
            appid = e.appid or "-"
            colour = COLOR_ERROR if status == "missing" else COLOR_RESET
            print(
                f"{colour}  {i:<3}{e.modlist_name:<{name_w}}  {status:<18}  {version:<12}  "
                f"{proton:<20}  {appid}{COLOR_RESET}"
            )

    def _manage_entry(self, entry) -> None:
        while True:
            from jackify.backend.services.modlist_properties_service import mo2_skip_status
            try:
                skip_enabled = mo2_skip_status(entry.install_dir, entry.modlist_name)
            except Exception:
                skip_enabled = False
            skip_label = "Remove MO2 Skip" if skip_enabled else "Add MO2 Skip"

            print(f"\n{COLOR_PROMPT}--- {entry.modlist_name} ---{COLOR_RESET}")
            print(f"{COLOR_INFO}Install directory: {entry.install_dir}{COLOR_RESET}")
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Launch")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Reconfigure")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Show install directory")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Uninstall (deletes shortcut, prefix and files)")
            print(f"{COLOR_SELECTION}5.{COLOR_RESET} Remove from this list only (keeps files/shortcut)")
            print(f"{COLOR_SELECTION}6.{COLOR_RESET} {skip_label} (skip MO2's launcher window on launch)")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Back")
            choice = input(f"{COLOR_PROMPT}Enter your selection (0-6): {COLOR_RESET}").strip()

            if choice == "1":
                self._launch(entry)
            elif choice == "2":
                self._reconfigure(entry)
                return
            elif choice == "3":
                print(f"{COLOR_INFO}{entry.install_dir}{COLOR_RESET}")
            elif choice == "4":
                if self._uninstall(entry):
                    return
            elif choice == "5":
                if self._remove_from_list(entry):
                    return
            elif choice == "6":
                self._toggle_mo2_skip(entry, skip_enabled)
            elif choice == "0":
                return
            else:
                print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")

    def _toggle_mo2_skip(self, entry, currently_enabled: bool) -> None:
        from jackify.backend.services.modlist_properties_service import toggle_mo2_skip
        from jackify.shared.messages import STEAM_RESTART_WARNING

        binary_title = None
        if not currently_enabled:
            from pathlib import Path
            from jackify.backend.handlers.mo2_custom_executables import list_launch_candidates

            ini_path = Path(entry.install_dir) / "ModOrganizer.ini"
            candidates = list_launch_candidates(ini_path)
            if not candidates:
                print(f"{COLOR_ERROR}Could not find a launchable executable in this modlist's ModOrganizer.ini.{COLOR_RESET}")
                return
            if len(candidates) == 1:
                binary_title = candidates[0]["title"]
            else:
                print(f"\n{COLOR_PROMPT}Which executable should Steam launch straight into?{COLOR_RESET}")
                for i, c in enumerate(candidates, 1):
                    print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} {c['title']}")
                choice = input(f"{COLOR_PROMPT}Enter your selection: {COLOR_RESET}").strip()
                if not choice.isdigit() or not (1 <= int(choice) <= len(candidates)):
                    print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
                    return
                binary_title = candidates[int(choice) - 1]["title"]

        if currently_enabled:
            action = "Remove"
            explanation = "This restores the normal launch - Steam will open Mod Organizer 2 itself instead of jumping straight into the game."
        else:
            action = "Add"
            explanation = (
                f"This makes the modlist's Steam shortcut launch straight into '{binary_title}', "
                "skipping Mod Organizer 2's own window. It always uses whichever profile MO2 last "
                "had active - to change mods or switch profiles, remove the skip first (same "
                "menu option), make your changes, then re-add it."
            )
        print(f"{COLOR_INFO}{explanation}{COLOR_RESET}")
        print(f"{COLOR_WARNING}{action}ing MO2 Skip requires restarting Steam. "
              f"{STEAM_RESTART_WARNING}{COLOR_RESET}")
        confirm = input(f"{COLOR_PROMPT}Continue? (y/N): {COLOR_RESET}").strip().lower()
        if confirm != "y":
            return

        success, message = toggle_mo2_skip(entry.install_dir, entry.modlist_name, binary_title)
        if success:
            print(f"{COLOR_SUCCESS}{message or 'MO2 Skip updated.'}{COLOR_RESET}")
        else:
            print(f"{COLOR_ERROR}Failed: {message}{COLOR_RESET}")

    def _launch(self, entry) -> None:
        if not entry.appid:
            print(f"{COLOR_ERROR}\"{entry.modlist_name}\" has no known Steam AppID - launch it from your Steam library instead.{COLOR_RESET}")
            return
        from jackify.backend.services.steam_launch_service import launch_steam_app

        if launch_steam_app(entry.appid):
            print(f"{COLOR_SUCCESS}Launched \"{entry.modlist_name}\" via Steam.{COLOR_RESET}")
        else:
            print(f"{COLOR_ERROR}Could not launch \"{entry.modlist_name}\" - open it from your Steam library instead.{COLOR_RESET}")

    def _reconfigure(self, entry) -> None:
        from jackify.backend.handlers.config_handler import ConfigHandler
        from jackify.backend.handlers.menu_handler import ModlistMenuHandler

        context = {
            "name": entry.modlist_name,
            "appid": entry.appid,
            "path": entry.install_dir,
            "resolution": None,
            "modlist_source": "existing",
        }
        modlist_menu = ModlistMenuHandler(config_handler=ConfigHandler())
        if not modlist_menu.modlist_handler:
            print(f"{COLOR_ERROR}Internal error: could not initialize modlist handler.{COLOR_RESET}")
            return
        if modlist_menu.run_modlist_configuration_phase(context):
            self._apply_problem_mods_fix(entry.install_dir, entry.game_type, entry.appid)

    def _apply_problem_mods_fix(self, install_dir: str, game_type: str, appid: Optional[str]) -> None:
        """Disable known-bad mods and create any prefix dirs they require."""
        try:
            from pathlib import Path
            from jackify.backend.services.install_verifier_service import resolve_pfx_for_appid
            from jackify.backend.services.problem_mods_service import (
                detect_game_type_from_install_dir,
                disable_problem_mods,
                create_prefix_dirs,
                get_enabled_mods,
            )
            resolved_game_type = detect_game_type_from_install_dir(install_dir) or game_type
            all_disabled: list = []
            all_enabled_mods: set = set()
            for modlist_txt in Path(install_dir).glob("profiles/*/modlist.txt"):
                disabled = disable_problem_mods(modlist_txt, resolved_game_type)
                for name in disabled:
                    if name not in all_disabled:
                        all_disabled.append(name)
                all_enabled_mods |= get_enabled_mods(modlist_txt)
            if all_disabled:
                print(f"{COLOR_INFO}Disabled known-problematic mod(s): {', '.join(all_disabled)}{COLOR_RESET}")
            pfx = resolve_pfx_for_appid(str(appid)) if appid else None
            if pfx and all_enabled_mods:
                create_prefix_dirs(pfx, resolved_game_type, all_enabled_mods)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Problem mods fix check failed (non-fatal): %s", e)

    def _uninstall(self, entry) -> bool:
        """Returns True if the caller should stop managing this (now-removed) entry."""
        provenance_note = (
            " Jackify did not install this modlist, so it cannot verify what else is in this "
            "directory."
            if entry.provenance == "backfill" else ""
        )
        print(f"\n{COLOR_WARNING}This deletes the install directory, the Steam shortcut "
              f"\"{entry.modlist_name}\", and its Proton prefix (saves, configs, everything).{COLOR_RESET}")
        print(f"{COLOR_INFO}{entry.install_dir}{COLOR_RESET}")
        print(f"{COLOR_WARNING}Steam will be restarted during removal - this will close any "
              f"running game.{provenance_note}{COLOR_RESET}")
        print(f"{COLOR_WARNING}This cannot be undone.{COLOR_RESET}")
        confirm = input(f"{COLOR_PROMPT}Type the modlist name to confirm, or press Enter to cancel: {COLOR_RESET}").strip()
        if confirm != entry.modlist_name:
            print(f"{COLOR_INFO}Cancelled.{COLOR_RESET}")
            return False

        if not os.path.isdir(entry.install_dir):
            print(f"\n{COLOR_WARNING}The files for \"{entry.modlist_name}\" cannot be reached, "
                  f"so they will NOT be deleted. Only the Steam shortcut and Proton prefix will "
                  f"be removed.{COLOR_RESET}")
            proceed = input(f"{COLOR_PROMPT}Continue? (y/N): {COLOR_RESET}").strip().lower()
            if proceed != 'y':
                print(f"{COLOR_INFO}Cancelled.{COLOR_RESET}")
                return False

        from jackify.backend.services.modlist_uninstall_service import uninstall_modlist

        def progress(msg: str) -> None:
            print(f"{COLOR_INFO}{msg}{COLOR_RESET}")

        success, message = uninstall_modlist(entry, progress_callback=progress)
        if success:
            print(f"{COLOR_SUCCESS}{message}{COLOR_RESET}")
        else:
            print(f"{COLOR_ERROR}{message}{COLOR_RESET}")
        return True

    def _remove_from_list(self, entry) -> bool:
        """Returns True if the caller should stop managing this (now-removed) entry."""
        print(f"\n{COLOR_INFO}This only removes \"{entry.modlist_name}\" from Jackify's tracked "
              f"list - the Steam shortcut, Proton prefix and files are left untouched.{COLOR_RESET}")
        confirm = input(f"{COLOR_PROMPT}Remove from list? (y/N): {COLOR_RESET}").strip().lower()
        if confirm != 'y':
            print(f"{COLOR_INFO}Cancelled.{COLOR_RESET}")
            return False

        from jackify.backend.services.install_registry import remove_from_registry

        if remove_from_registry(entry.install_id):
            print(f"{COLOR_SUCCESS}Removed \"{entry.modlist_name}\" from the list.{COLOR_RESET}")
        else:
            print(f"{COLOR_ERROR}Could not remove \"{entry.modlist_name}\" from the list.{COLOR_RESET}")
        return True
