"""
Tools Hub Menu Handler for Jackify CLI Frontend
"""

import logging
import subprocess
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
            print(f"{COLOR_SELECTION}U.{COLOR_RESET} Update All")
            selection = input(
                f"\n{COLOR_PROMPT}Select tool (0-{len(statuses)}): {COLOR_RESET}"
            ).strip()

            if selection == "0":
                break
            if selection.lower() == "q":
                continue
            if selection.lower() == "u":
                self._update_all(registry, statuses)
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
                if status.can_downgrade and defn.github_repo:
                    print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Change Version")
                    options[str(opt_num)] = "change_version"
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
                elif defn.can_launch:
                    print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Launch")
                    options[str(opt_num)] = "launch"
                    opt_num += 1

            if defn.upstream_url:
                print(f"{COLOR_SELECTION}{opt_num}.{COLOR_RESET} Open Website")
                options[str(opt_num)] = "open_website"
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

            if action == "launch":
                binary = registry.get_binary_path(defn.tool_id)
                if not binary:
                    print(f"\n{COLOR_ERROR}No executable found for {defn.display_name}. "
                          f"Try reinstalling it.{COLOR_RESET}")
                else:
                    try:
                        subprocess.Popen(
                            [str(binary)], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                        print(f"\n{COLOR_SUCCESS}Launched {defn.display_name}.{COLOR_RESET}")
                    except Exception as e:
                        print(f"\n{COLOR_ERROR}Launch failed: {e}{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                continue

            if action == "open_website":
                try:
                    subprocess.Popen(
                        ["xdg-open", defn.upstream_url], start_new_session=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    print(f"\n{COLOR_SUCCESS}Opening {defn.upstream_url}{COLOR_RESET}")
                except Exception as e:
                    print(f"\n{COLOR_ERROR}Failed to open URL: {e}{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                continue

            if action == "change_version":
                version = self._pick_version(defn, status)
                if version:
                    ok, msg = self._run_with_spinner(
                        registry, "install", defn.tool_id, defn.display_name, version=version
                    )
                    if ok:
                        print(f"\n{COLOR_SUCCESS}{msg}{COLOR_RESET}")
                    else:
                        print(f"\n{COLOR_ERROR}{msg}{COLOR_RESET}")
                    input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
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

    def _pick_version(self, defn, status) -> Optional[str]:
        from jackify.backend.services.tool_registry import fetch_release_list

        result: list = [None]
        spinner = CliIndeterminateStatus()
        spinner.set("Fetching releases...")

        def _worker():
            result[0] = fetch_release_list(defn.github_repo)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join()
        spinner.stop()

        releases = result[0] or []
        if not releases:
            print(f"\n{COLOR_ERROR}Could not fetch release list from GitHub.{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return None

        print(f"\n{COLOR_INFO}Currently installed: "
              f"{status.installed_version or 'unknown'}{COLOR_RESET}\n")
        for i, rel in enumerate(releases, 1):
            tag = rel.get("tag_name") or rel.get("name", "")
            date = (rel.get("published_at") or "")[:10]
            print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} {tag}  {COLOR_DISABLED}({date}){COLOR_RESET}")
        print(f"{COLOR_SELECTION}0.{COLOR_RESET} Cancel")

        selection = input(
            f"\n{COLOR_PROMPT}Select version (0-{len(releases)}): {COLOR_RESET}"
        ).strip()
        if selection == "0":
            return None
        try:
            idx = int(selection) - 1
            if idx < 0 or idx >= len(releases):
                raise ValueError()
        except ValueError:
            print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
            time.sleep(1)
            return None
        return releases[idx].get("tag_name") or releases[idx].get("name")

    def _update_all(self, registry, statuses) -> None:
        installed = [s for s in statuses if s.installed]
        spinner = CliIndeterminateStatus()
        spinner.set("Checking for updates...")

        updates_needed = []
        for s in installed:
            try:
                latest = registry.check_latest_version(s.definition.tool_id)
            except Exception:
                latest = None
            if latest:
                latest_clean = latest.lstrip("v")
                current_clean = (s.installed_version or "").lstrip("v")
                if latest_clean != current_clean:
                    updates_needed.append(s.definition)
        spinner.stop()

        if not updates_needed:
            print(f"\n{COLOR_INFO}Everything is up to date.{COLOR_RESET}")
            input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return

        names = ", ".join(d.display_name for d in updates_needed)
        confirm = input(
            f"\n{COLOR_PROMPT}Update the following tools? {names} (y/N): {COLOR_RESET}"
        ).strip().lower()
        if confirm not in ("y", "yes"):
            print(f"{COLOR_INFO}Cancelled.{COLOR_RESET}")
            time.sleep(0.8)
            return

        for defn in updates_needed:
            ok, msg = self._run_with_spinner(registry, "update", defn.tool_id, defn.display_name)
            if ok:
                print(f"{COLOR_SUCCESS}{defn.display_name}: {msg}{COLOR_RESET}")
            else:
                print(f"{COLOR_ERROR}{defn.display_name}: {msg}{COLOR_RESET}")
        input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

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
        self, registry, action: str, tool_id: str, display_name: str,
        version: Optional[str] = None,
    ) -> Tuple[bool, str]:
        labels = {
            "install": f"Installing {display_name} {version}" if version else f"Installing {display_name}",
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
                    result[0], result[1] = registry.install(tool_id, version=version)
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
