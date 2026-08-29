"""
Settings Menu Handler for Jackify CLI Frontend
"""

import logging
import time
from typing import List, Optional

from jackify.shared.colors import (
    COLOR_SELECTION, COLOR_RESET, COLOR_ACTION, COLOR_PROMPT,
    COLOR_INFO, COLOR_DISABLED, COLOR_WARNING, COLOR_ERROR, COLOR_SUCCESS
)
from jackify.shared.ui_utils import print_jackify_banner, print_section_header, clear_screen

logger = logging.getLogger(__name__)

_SLOW_GE_MARKERS = ("GE-Proton9", "GE-Proton8")


class SettingsMenuHandler:
    """CLI menu for reading/writing the persistent settings GUI's Settings dialog manages."""

    def show_settings_menu(self, cli_instance) -> None:
        from jackify.backend.handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()

        while True:
            clear_screen()
            print_jackify_banner()
            print_section_header("Settings")

            debug_mode = config_handler.get("debug_mode", False)
            proton_path = config_handler.get("proton_path")
            proton_version = config_handler.get("proton_version")
            game_proton_path = config_handler.get("game_proton_path")
            game_proton_version = config_handler.get("game_proton_version")
            method = config_handler.get("component_installation_method", "native")
            if method == "bundled_protontricks":
                method = "system_protontricks"
            auto_tool_compat = config_handler.get("auto_tool_compat", True)
            usvfs_linux_fix = config_handler.get("usvfs_linux_fix", True)
            playbooks_enabled = config_handler.get("playbooks_enabled", True)
            jackify_db_enabled = config_handler.get("jackify_db_enabled", True)
            force_github_updates = config_handler.get("force_github_updates", False)

            method_labels = {
                "native": "Native",
                "winetricks": "Winetricks",
                "system_protontricks": "Protontricks",
            }

            print(f"{COLOR_INFO}General{COLOR_RESET}")
            print(f"{COLOR_SELECTION}1.{COLOR_RESET} Debug Mode"
                  f"{self._bool_tag(debug_mode)}")

            print(f"\n{COLOR_INFO}Install Engine{COLOR_RESET}")
            print(f"{COLOR_SELECTION}2.{COLOR_RESET} Install Proton  "
                  f"{COLOR_ACTION}{proton_version or 'Auto (Recommended)'}{COLOR_RESET}")
            print(f"{COLOR_SELECTION}3.{COLOR_RESET} Game Proton     "
                  f"{COLOR_ACTION}{game_proton_version or 'Same as Install Proton'}{COLOR_RESET}")
            print(f"{COLOR_SELECTION}4.{COLOR_RESET} Component Install Method  "
                  f"{COLOR_ACTION}{method_labels.get(method, method)}{COLOR_RESET}")

            print(f"\n{COLOR_INFO}Automation & Data{COLOR_RESET}")
            print(f"{COLOR_SELECTION}5.{COLOR_RESET} Auto Tool Compat"
                  f"{self._bool_tag(auto_tool_compat)}")
            print(f"{COLOR_SELECTION}6.{COLOR_RESET} USVFS Linux Fix"
                  f"{self._bool_tag(usvfs_linux_fix)}")
            print(f"{COLOR_SELECTION}7.{COLOR_RESET} Playbooks"
                  f"{self._bool_tag(playbooks_enabled)}")
            print(f"{COLOR_SELECTION}8.{COLOR_RESET} JackifyDB Local Recording"
                  f"{self._bool_tag(jackify_db_enabled)}")
            print(f"{COLOR_SELECTION}9.{COLOR_RESET} Force GitHub Updates"
                  f"{self._bool_tag(force_github_updates)}")

            print(f"\n{COLOR_SELECTION}0.{COLOR_RESET} Back")
            selection = input(f"\n{COLOR_PROMPT}Enter selection: {COLOR_RESET}").strip()

            if selection == "0":
                break
            elif selection == "1":
                self._toggle(config_handler, "debug_mode", debug_mode)
                print(f"\n{COLOR_INFO}Restart Jackify for this to take effect.{COLOR_RESET}")
                time.sleep(1.2)
            elif selection == "2":
                self._pick_install_proton(config_handler)
            elif selection == "3":
                self._pick_game_proton(config_handler)
            elif selection == "4":
                self._pick_component_method(config_handler, method)
            elif selection == "5":
                self._toggle(config_handler, "auto_tool_compat", auto_tool_compat)
            elif selection == "6":
                self._toggle(config_handler, "usvfs_linux_fix", usvfs_linux_fix)
            elif selection == "7":
                self._toggle(config_handler, "playbooks_enabled", playbooks_enabled)
            elif selection == "8":
                self._toggle(config_handler, "jackify_db_enabled", jackify_db_enabled)
            elif selection == "9":
                self._toggle(config_handler, "force_github_updates", force_github_updates)
            else:
                print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
                time.sleep(1)

    @staticmethod
    def _bool_tag(value: bool) -> str:
        color = COLOR_SUCCESS if value else COLOR_DISABLED
        return f"  {color}[{'ON' if value else 'OFF'}]{COLOR_RESET}"

    @staticmethod
    def _toggle(config_handler, key: str, current: bool) -> None:
        config_handler.set(key, not current)
        config_handler.save_config()

    def _pick_install_proton(self, config_handler) -> None:
        from jackify.backend.handlers.wine_utils import WineUtils

        versions = self._scan_protons()
        entries: List[Optional[dict]] = [None]
        labels = ["Auto (Recommended)"]
        for proton in versions:
            proton_type = proton.get("type", "Unknown")
            if proton_type not in ("GE-Proton", "Valve-Proton"):
                continue
            name = proton.get("name", "Unknown Proton")
            slow = self._is_slow_proton(proton)
            display = f"{name} (GE)" if proton_type == "GE-Proton" else name
            if slow:
                display += " (Slow texture processing)"
            entries.append(proton)
            labels.append(display)

        choice = self._prompt_choice("Install Proton", labels)
        if choice is None:
            return
        proton = entries[choice]

        if proton is None:
            best = WineUtils.select_best_proton()
            if best:
                config_handler.set("proton_path", str(best["path"]))
                config_handler.set("proton_version", best["name"])
            else:
                print(f"\n{COLOR_WARNING}No compatible Proton version found. "
                      f"Jackify requires Proton 9.0+, Proton Experimental, or "
                      f"GE-Proton 10+.{COLOR_RESET}")
                config_handler.set("proton_path", None)
                config_handler.set("proton_version", None)
                input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
        else:
            config_handler.set("proton_path", str(proton["path"]))
            config_handler.set("proton_version", proton["name"])
        config_handler.save_config()

    def _pick_game_proton(self, config_handler) -> None:
        versions = self._scan_protons()
        entries: List[Optional[dict]] = [None]
        labels = ["Same as Install Proton"]
        for proton in versions:
            name = proton.get("name", "Unknown Proton")
            display = f"{name} (GE)" if proton.get("type") == "GE-Proton" else name
            entries.append(proton)
            labels.append(display)

        choice = self._prompt_choice("Game Proton", labels)
        if choice is None:
            return
        proton = entries[choice]

        if proton is None:
            config_handler.set("game_proton_path", config_handler.get("proton_path"))
            config_handler.set("game_proton_version", config_handler.get("proton_version"))
        else:
            config_handler.set("game_proton_path", str(proton["path"]))
            config_handler.set("game_proton_version", proton["name"])
        config_handler.save_config()

    def _pick_component_method(self, config_handler, current: str) -> None:
        labels = ["Native", "Winetricks", "Protontricks"]
        values = ["native", "winetricks", "system_protontricks"]
        choice = self._prompt_choice("Component Install Method", labels)
        if choice is None:
            return
        new_method = values[choice - 1]
        config_handler.set("component_installation_method", new_method)
        config_handler.save_config()

        if new_method == "system_protontricks" and current != "system_protontricks":
            from jackify.backend.services.protontricks_detection_service import (
                ProtontricksDetectionService
            )
            is_installed, _, _ = ProtontricksDetectionService().detect_protontricks(use_cache=False)
            if not is_installed:
                print(f"\n{COLOR_WARNING}Protontricks was not detected on this system. "
                      f"Install it (e.g. via Flatpak or your distro's package manager) "
                      f"before running an install with this method.{COLOR_RESET}")
                input(f"{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

    @staticmethod
    def _scan_protons() -> List[dict]:
        from jackify.backend.handlers.wine_utils import WineUtils
        try:
            return WineUtils.scan_all_proton_versions()
        except Exception as e:
            logger.warning("Failed to scan Proton versions: %s", e)
            return []

    @staticmethod
    def _is_slow_proton(proton: dict) -> bool:
        name = proton.get("name", "")
        proton_type = proton.get("type")
        if proton_type == "GE-Proton":
            return any(marker in name for marker in _SLOW_GE_MARKERS)
        if proton_type == "Valve-Proton":
            return name.startswith("Proton 9") or "9.0" in name
        return False

    @staticmethod
    def _prompt_choice(title: str, labels: List[str]) -> Optional[int]:
        print(f"\n{COLOR_INFO}{title}{COLOR_RESET}")
        for i, label in enumerate(labels, 1):
            print(f"{COLOR_SELECTION}{i}.{COLOR_RESET} {label}")
        print(f"{COLOR_SELECTION}0.{COLOR_RESET} Cancel")

        selection = input(
            f"\n{COLOR_PROMPT}Select (0-{len(labels)}): {COLOR_RESET}"
        ).strip()
        if selection == "0":
            return None
        try:
            idx = int(selection)
            if idx < 1 or idx > len(labels):
                raise ValueError()
        except ValueError:
            print(f"{COLOR_ERROR}Invalid selection.{COLOR_RESET}")
            time.sleep(1)
            return None
        return idx
