"""
Setup Mod Organizer 2 Command

CLI interface for downloading and configuring a standalone MO2 instance.
"""

import logging
from pathlib import Path

from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
from jackify.backend.services.mo2_setup_service import MO2SetupService, _is_dangerous_path
from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_SUCCESS, COLOR_ERROR

logger = logging.getLogger(__name__)


class SetupMO2Command:
    """CLI command for standalone MO2 setup"""

    def run(self):
        """Execute the MO2 setup workflow"""
        print(f"\n{COLOR_INFO}=== Setup Mod Organizer 2 ==={COLOR_RESET}\n")
        print("Downloads the latest MO2 release, adds it to Steam, and configures a Proton prefix.")
        print("Steam will be restarted during this process.\n")

        # Install directory
        default_dir = str(Path.home() / "ModOrganizer2")
        dir_input = input(
            f"{COLOR_PROMPT}Installation directory [{default_dir}]: {COLOR_RESET}"
        ).strip()
        install_dir = Path(dir_input) if dir_input else Path(default_dir)

        # Danger check
        if _is_dangerous_path(install_dir):
            print(f"{COLOR_ERROR}Refusing to install to a dangerous directory: {install_dir}{COLOR_RESET}")
            input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return

        # Non-empty directory warning
        if install_dir.exists() and any(install_dir.iterdir()):
            print(f"\n{COLOR_ERROR}[WARN] Directory is not empty: {install_dir}{COLOR_RESET}")
            confirm = input(
                f"{COLOR_PROMPT}Files may be overwritten. Continue anyway? (y/N): {COLOR_RESET}"
            ).strip().lower()
            if confirm != 'y':
                print("Cancelled.")
                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                return

        # Shortcut name
        default_name = "Mod Organizer 2"
        name_input = input(
            f"{COLOR_PROMPT}Steam shortcut name [{default_name}]: {COLOR_RESET}"
        ).strip()
        shortcut_name = name_input if name_input else default_name

        # Confirm
        print(f"\n{COLOR_INFO}Install directory: {install_dir}{COLOR_RESET}")
        print(f"{COLOR_INFO}Shortcut name: {shortcut_name}{COLOR_RESET}")
        confirm = input(
            f"\n{COLOR_PROMPT}Proceed? (Y/n): {COLOR_RESET}"
        ).strip().lower()
        if confirm == 'n':
            print("Cancelled.")
            input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
            return

        existing_appid = None
        candidate_exe = install_dir / "ModOrganizer.exe"
        prefix_service = AutomatedPrefixService()
        conflict_result = prefix_service.handle_existing_shortcut_conflict(
            shortcut_name, str(candidate_exe), str(install_dir)
        )
        if isinstance(conflict_result, list):
            print(f"\n{COLOR_INFO}Jackify found an existing Steam shortcut for this Mod Organizer 2 setup:{COLOR_RESET}")
            existing = conflict_result[0]
            print(f"  Name: {existing.get('name', shortcut_name)}")
            print(f"  Executable: {existing.get('exe', '')}")
            print(f"  Start Directory: {existing.get('startdir', '')}")
            print(f"\n{COLOR_PROMPT}Options:{COLOR_RESET}")
            print("  1. Use existing shortcut (recommended)")
            print("  2. Choose a different shortcut name")
            print("  0. Cancel")
            conflict_choice = input(f"{COLOR_PROMPT}Enter choice (0-2): {COLOR_RESET}").strip()
            if conflict_choice == "1":
                existing_appid = existing.get('appid')
                if not existing_appid:
                    print(f"{COLOR_ERROR}Could not determine the Steam AppID for the existing shortcut.{COLOR_RESET}")
                    input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                    return
                print(f"{COLOR_INFO}Reusing existing Steam shortcut with AppID {existing_appid}.{COLOR_RESET}")
            elif conflict_choice == "2":
                new_name = input(
                    f"{COLOR_PROMPT}New shortcut name (or 'q' to cancel): {COLOR_RESET}"
                ).strip()
                if not new_name or new_name.lower() == 'q':
                    print("Cancelled.")
                    input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                    return
                if new_name == shortcut_name:
                    print(f"{COLOR_ERROR}Please enter a different name to resolve the conflict.{COLOR_RESET}")
                    input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                    return
                shortcut_name = new_name
            else:
                print("Cancelled.")
                input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
                return

        print(f"\n{COLOR_INFO}Starting MO2 setup...{COLOR_RESET}\n")

        def _progress(msg: str):
            print(f"{COLOR_INFO}  {msg}{COLOR_RESET}")

        service = MO2SetupService()
        success, app_id, error_msg = service.setup_mo2(
            install_dir=install_dir,
            shortcut_name=shortcut_name,
            existing_appid=int(existing_appid) if existing_appid else None,
            progress_callback=_progress,
        )

        if success:
            print(f"\n{COLOR_SUCCESS}{'='*60}{COLOR_RESET}")
            print(f"{COLOR_SUCCESS}MO2 setup complete!{COLOR_RESET}")
            print(f"{COLOR_SUCCESS}{'='*60}{COLOR_RESET}")
            print(f"{COLOR_INFO}Steam AppID: {app_id}{COLOR_RESET}")
            print(f"{COLOR_INFO}Launch Mod Organizer 2 from your Steam library.{COLOR_RESET}")
        else:
            print(f"\n{COLOR_ERROR}MO2 setup failed: {error_msg}{COLOR_RESET}")
            print(f"{COLOR_INFO}Check logs for details.{COLOR_RESET}")

        input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")
