"""List installed Wine components for a configured modlist prefix."""
import json
from pathlib import Path
from typing import Dict, List, Optional

from jackify.shared.colors import (
    COLOR_ACTION,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_SELECTION,
    COLOR_WARNING,
)
from jackify.shared.ui_utils import clear_screen, print_jackify_banner, print_section_header


class ListInstalledCommand:
    """Show deduplicated component records for a modlist prefix."""

    def run(self, appid: Optional[str] = None) -> None:
        clear_screen()
        print_jackify_banner()
        print_section_header("Installed Wine Components")

        if appid:
            self._show_for_appid(appid, modlist_name=None)
        else:
            self._run_interactive()

    def _run_interactive(self) -> None:
        from jackify.backend.handlers.modlist_handler import ModlistHandler

        print(f"{COLOR_INFO}Discovering configured modlists...{COLOR_RESET}")
        try:
            handler = ModlistHandler()
            discovered = handler.discover_executable_shortcuts("ModOrganizer.exe")
            shortcuts = [
                {"name": m.get("name", "Unknown"), "appid": str(m.get("appid", ""))}
                for m in discovered
                if m.get("appid")
            ]
        except Exception as exc:
            print(f"{COLOR_ERROR}Failed to discover modlists: {exc}{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        if not shortcuts:
            print(f"{COLOR_WARNING}No configured modlists found.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        print()
        for i, s in enumerate(shortcuts, 1):
            print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} {s['name']}")
            print(f"   {COLOR_ACTION}AppID: {s['appid']}{COLOR_RESET}")
        print(f"{COLOR_SELECTION}0.{COLOR_RESET} Cancel")

        selection = input(f"\n{COLOR_PROMPT}Select modlist (0-{len(shortcuts)}): {COLOR_RESET}").strip()
        if selection == "0" or not selection:
            return

        try:
            idx = int(selection) - 1
            if idx < 0 or idx >= len(shortcuts):
                raise ValueError()
        except ValueError:
            print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
            input("Press Enter to return to menu...")
            return

        chosen = shortcuts[idx]
        self._show_for_appid(chosen["appid"], modlist_name=chosen["name"])

    def _show_for_appid(self, appid: str, modlist_name: Optional[str]) -> None:
        from jackify.backend.handlers.path_handler import PathHandler

        compat = PathHandler.find_compat_data(appid)
        if not compat:
            print(f"{COLOR_ERROR}Prefix not found for AppID {appid}.{COLOR_RESET}")
            input("Press Enter to continue...")
            return

        pfx = compat / "pfx"

        wt_log = pfx / "winetricks.log"
        wt_entries: List[str] = []
        if wt_log.is_file():
            seen: set = set()
            for line in wt_log.read_text(errors="replace").splitlines():
                entry = line.strip()
                if entry and entry not in seen:
                    seen.add(entry)
                    wt_entries.append(entry)

        jc_path = pfx / "jackify_components.json"
        jc_data: Dict[str, dict] = {}
        if jc_path.is_file():
            try:
                jc_data = json.loads(jc_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        label = modlist_name or appid
        print(f"\n{COLOR_INFO}Installed components: {label}{COLOR_RESET}")
        if modlist_name:
            print(f"{COLOR_INFO}AppID: {appid}{COLOR_RESET}")
        print(f"{COLOR_INFO}Prefix: {pfx}{COLOR_RESET}\n")

        if not wt_entries and not jc_data:
            print(f"{COLOR_WARNING}No component records found.{COLOR_RESET}")
            print(f"{COLOR_INFO}winetricks.log: {wt_log}{COLOR_RESET}")
            input("\nPress Enter to continue...")
            return

        all_components: List[str] = list(wt_entries)
        for comp in jc_data:
            if comp not in all_components:
                all_components.append(comp)

        col_w = max((len(c) for c in all_components), default=20)
        col_w = max(col_w, 20)
        header = f"{'Component':<{col_w}}  {'Method':<12}  Timestamp"
        print(f"{COLOR_SELECTION}{header}{COLOR_RESET}")
        print("-" * (col_w + 30))

        for comp in all_components:
            if comp in jc_data:
                method = jc_data[comp].get("method", "native")
                ts = jc_data[comp].get("timestamp", "-")
            else:
                method = "winetricks"
                ts = "-"
            print(f"{comp:<{col_w}}  {method:<12}  {ts}")

        wt_note = "[OK]" if wt_log.is_file() else "[MISSING]"
        jc_note = "[OK]" if jc_path.is_file() else "[MISSING]"
        print(f"\n{COLOR_INFO}Sources: {wt_note} winetricks.log  {jc_note} jackify_components.json{COLOR_RESET}")
        input("\nPress Enter to continue...")
