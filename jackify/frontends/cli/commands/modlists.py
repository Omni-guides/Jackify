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
            print(f"\n{COLOR_PROMPT}--- {entry.modlist_name} ---{COLOR_RESET}")
            print(f"{COLOR_INFO}Install directory: {entry.install_dir}{COLOR_RESET}")
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Launch")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Reconfigure")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Show install directory")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Uninstall (deletes shortcut, prefix and files)")
            print(f"{COLOR_SELECTION}5.{COLOR_RESET} Remove from this list only (keeps files/shortcut)")
            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Back")
            choice = input(f"{COLOR_PROMPT}Enter your selection (0-5): {COLOR_RESET}").strip()

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
            elif choice == "0":
                return
            else:
                print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")

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
        modlist_menu.run_modlist_configuration_phase(context)

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
