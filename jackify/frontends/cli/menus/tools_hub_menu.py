"""
Tools Hub Menu Handler for Jackify CLI Frontend
"""

import logging
import threading
import time
from typing import Optional, Tuple

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_ACTION, COLOR_PROMPT,
    COLOR_INFO, COLOR_DISABLED, COLOR_WARNING, COLOR_ERROR, COLOR_SUCCESS
)
from jackify.shared.ui_utils import print_jackify_banner, print_section_header, clear_screen
from jackify.frontends.cli.ui.indeterminate_status import CliIndeterminateStatus

logger = logging.getLogger(__name__)


class ToolsHubMenuHandler:
    """CLI menu for managing third-party tools via ToolRegistry."""

    def show_tools_hub_menu(self, cli_instance) -> None:
        from jackify.backend.services.tool_registry import (
            ToolRegistry, get_active_engine_id
        )
        registry = ToolRegistry()

        while True:
            clear_screen()
            print_jackify_banner()
            print_section_header("Third Party Tools Hub")

            statuses = [s for s in registry.get_all_statuses() if not s.definition.hidden]
            active_engine_id = get_active_engine_id()

            print(f"{COLOR_INFO}Active engine: {active_engine_id}{COLOR_RESET}\n")

            for i, status in enumerate(statuses, 1):
                defn = status.definition
                if status.installed:
                    ver = status.installed_version or "unknown"
                    active_tag = (
                        f"  {COLOR_ACTION}[ACTIVE]{COLOR_RESET}"
                        if defn.is_engine and defn.tool_id == active_engine_id
                        else ""
                    )
                    print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} {defn.display_name}  "
                          f"{COLOR_INFO}v{ver}{COLOR_RESET}{active_tag}")
                else:
                    print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} "
                          f"{COLOR_DISABLED}{defn.display_name}  [not installed]{COLOR_RESET}")
                print(f"   {COLOR_ACTION}{defn.description}{COLOR_RESET}")

            print(f"\n{COLOR_SELECTION}0.{COLOR_RESET} Return to Main Menu")
            selection = input(
                f"\n{COLOR_PROMPT}Select tool (0-{len(statuses)}): {COLOR_RESET}"
            ).strip()

            if selection == "0":
                break
            if selection.lower() == "q":
                continue

            try:
                idx = int(selection) - 1
                if idx < 0 or idx >= len(statuses):
                    raise ValueError()
            except ValueError:
                print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
                time.sleep(1)
                continue

            self._show_tool_detail(registry, statuses[idx], active_engine_id, cli_instance)

    def _show_tool_detail(self, registry, status, active_engine_id: str, cli_instance=None) -> None:
        from jackify.backend.services.tool_registry import (
            get_active_engine_id, set_active_engine_id
        )

        defn = status.definition

        while True:
            clear_screen()
            print_jackify_banner()
            print_section_header(defn.display_name)
            print(f"{COLOR_INFO}{defn.description}{COLOR_RESET}\n")

            if status.installed:
                ver = status.installed_version or "unknown"
                print(f"Installed:  {COLOR_INFO}{ver}{COLOR_RESET}")
                if status.previous_version:
                    print(f"Previous:   {COLOR_DISABLED}{status.previous_version}{COLOR_RESET}")
                if defn.is_engine and defn.tool_id == active_engine_id:
                    print(f"Engine:     {COLOR_ACTION}[ACTIVE]{COLOR_RESET}")
            else:
                print(f"Status:     {COLOR_DISABLED}Not installed{COLOR_RESET}")

            latest = self._fetch_latest_with_spinner(registry, defn.tool_id)

            if latest:
                latest_clean = latest.lstrip("v")
                current_clean = (status.installed_version or "").lstrip("v")
                update_available = status.installed and latest_clean != current_clean
                update_tag = (
                    f"  {COLOR_WARNING}[update available]{COLOR_RESET}" if update_available
                    else f"  {COLOR_ACTION}[up to date]{COLOR_RESET}" if status.installed
                    else ""
                )
                print(f"Latest:     {COLOR_INFO}{latest}{COLOR_RESET}{update_tag}")
            else:
                update_available = False
                print(f"Latest:     {COLOR_DISABLED}(could not check){COLOR_RESET}")

            options: dict = {}
            opt_num = 1
            print()

            if not status.installed:
                print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Install")
                options[str(opt_num)] = "install"
                opt_num += 1
            else:
                if latest and update_available:
                    print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Update to {latest}")
                    options[str(opt_num)] = "update"
                    opt_num += 1
                if status.previous_version and defn.can_uninstall:
                    print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} "
                          f"Downgrade to {status.previous_version}")
                    options[str(opt_num)] = "downgrade"
                    opt_num += 1
                if defn.can_uninstall:
                    print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Uninstall")
                    options[str(opt_num)] = "uninstall"
                    opt_num += 1
                if defn.is_engine and defn.tool_id != active_engine_id:
                    print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Set as active engine")
                    options[str(opt_num)] = "set_active"
                    opt_num += 1
                if defn.tool_id == "ttw_installer":
                    print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Run TTW Installation")
                    options[str(opt_num)] = "run_ttw"
                    opt_num += 1

            print(f"{COLOR_SELECTION}0.{COLOR_RESET} Back")

            if not options:
                input(f"\n{COLOR_PROMPT}Press Enter to go back...{COLOR_RESET}")
                break

            selection = input(f"\n{COLOR_PROMPT}Enter selection: {COLOR_RESET}").strip()

            if selection == "0":
                break

            action = options.get(selection)
            if not action:
                print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
                time.sleep(1)
                continue

            if action == "run_ttw":
                from jackify.frontends.cli.menus.additional_menu import AdditionalMenuHandler
                AdditionalMenuHandler()._execute_ttw_install(cli_instance)
                status = registry.get_status(defn.tool_id) or status
                continue

            if action == "set_active":
                try:
                    set_active_engine_id(defn.tool_id)
                    active_engine_id = defn.tool_id
                    print(f"\n{COLOR_SUCCESS}Active engine set to {defn.display_name}.{COLOR_RESET}")
                except Exception as e:
                    print(f"\n{COLOR_ERROR}Failed to set active engine: {e}{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                status = registry.get_status(defn.tool_id) or status
                continue

            if action == "uninstall":
                confirm = input(
                    f"\n{COLOR_WARNING}Uninstall {defn.display_name}? (y/N): {COLOR_RESET}"
                ).strip().lower()
                if confirm not in ("y", "yes"):
                    print(f"{COLOR_INFO}Cancelled.{COLOR_RESET}")
                    time.sleep(0.8)
                    status = registry.get_status(defn.tool_id) or status
                    continue

            ok, msg = self._run_with_spinner(registry, action, defn.tool_id, defn.display_name)

            if ok:
                print(f"\n{COLOR_SUCCESS}{msg}{COLOR_RESET}")
            else:
                print(f"\n{COLOR_ERROR}{msg}{COLOR_RESET}")

            input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            status = registry.get_status(defn.tool_id) or status
            active_engine_id = get_active_engine_id()

    def _fetch_latest_with_spinner(self, registry, tool_id: str) -> Optional[str]:
        result: list = [None]
        spinner = CliIndeterminateStatus()
        spinner.set("Checking latest version...")

        def _worker():
            try:
                result[0] = registry.check_latest_version(tool_id)
            except Exception:
                result[0] = None

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        spinner.stop()
        return result[0]

    def _run_with_spinner(
        self, registry, action: str, tool_id: str, display_name: str
    ) -> Tuple[bool, str]:
        labels = {
            "install": f"Installing {display_name}",
            "update": f"Updating {display_name}",
            "downgrade": f"Downgrading {display_name}",
            "uninstall": f"Uninstalling {display_name}",
        }
        label = labels.get(action, f"Working on {display_name}")
        result: list = [False, ""]
        spinner = CliIndeterminateStatus()
        spinner.set(label)

        def _worker():
            try:
                if action == "install":
                    result[0], result[1] = registry.install(tool_id)
                elif action == "update":
                    result[0], result[1] = registry.update(tool_id)
                elif action == "downgrade":
                    result[0], result[1] = registry.downgrade(tool_id)
                elif action == "uninstall":
                    result[0], result[1] = registry.uninstall(tool_id)
            except Exception as e:
                result[0], result[1] = False, str(e)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        spinner.stop()
        return result[0], result[1]
