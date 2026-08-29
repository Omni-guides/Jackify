"""
Install Wabbajack Application Command
Provides CLI interface for automated Wabbajack installation
Uses backend service for complete workflow orchestration
"""

import logging
from pathlib import Path

from jackify.backend.services.automated_prefix_service import AutomatedPrefixService
from jackify.backend.services.wabbajack_installer_service import WabbajackInstallerService
from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET, COLOR_INFO, COLOR_SUCCESS, COLOR_ERROR


class InstallWabbajackCommand:
    """CLI command for installing Wabbajack application"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def run(self):
        """Execute Wabbajack installation workflow using backend service"""
        print(f"\n{COLOR_INFO}=== Install Wabbajack Application ==={COLOR_RESET}\n")
        print("This will download and configure Wabbajack.exe via Proton.")
        print("Wabbajack will be added to your Steam library as a non-Steam game.\n")

        # Prompt for installation directory
        default_dir = str(Path.home() / "Games" / "Wabbajack")
        install_dir_input = input(
            f"{COLOR_PROMPT}Installation directory [{default_dir}]: {COLOR_RESET}"
        ).strip()

        install_dir = Path(install_dir_input) if install_dir_input else Path(default_dir)

        # Prompt for shortcut name
        shortcut_name = "Wabbajack"
        shortcut_input = input(
            f"{COLOR_PROMPT}Shortcut name [{shortcut_name}]: {COLOR_RESET}"
        ).strip()
        if shortcut_input:
            shortcut_name = shortcut_input

        # Confirm installation with Steam restart warning
        print(f"\n{COLOR_INFO}Installation directory: {install_dir}{COLOR_RESET}")
        print(f"{COLOR_INFO}Shortcut name: {shortcut_name}{COLOR_RESET}")
        print(f"\n{COLOR_PROMPT}{'='*60}{COLOR_RESET}")
        print(f"{COLOR_PROMPT}Important: Steam will be restarted during installation.{COLOR_RESET}")
        print(f"{COLOR_PROMPT}Please do not manually start or close Steam until installation is complete.{COLOR_RESET}")
        print(f"{COLOR_PROMPT}{'='*60}{COLOR_RESET}")
        confirm = input(f"\n{COLOR_PROMPT}Proceed with installation? (Y/n): {COLOR_RESET}").strip().lower()

        if confirm == 'n':
            print("Installation cancelled.")
            return

        existing_appid = None
        candidate_exe = install_dir / "Wabbajack.exe"
        prefix_service = AutomatedPrefixService()
        conflict_result = prefix_service.handle_existing_shortcut_conflict(
            shortcut_name, str(candidate_exe), str(install_dir)
        )
        if isinstance(conflict_result, list):
            print(f"\n{COLOR_INFO}Jackify found an existing Steam shortcut for this Wabbajack setup:{COLOR_RESET}")
            existing = conflict_result[0]
            print(f"  Name: {existing.get('name', shortcut_name)}")
            print(f"  Executable: {existing.get('exe', '')}")
            print(f"  Start Directory: {existing.get('startdir', '')}")
            print(f"\n{COLOR_PROMPT}Options:{COLOR_RESET}")
            print("  1. Use existing shortcut (recommended)")
            print("  2. Choose a different shortcut name")
            print("  0. Cancel")
            choice = input(f"{COLOR_PROMPT}Enter choice (0-2): {COLOR_RESET}").strip()
            if choice == "1":
                existing_appid = existing.get('appid')
                if not existing_appid:
                    print(f"{COLOR_ERROR}Could not determine the Steam AppID for the existing shortcut.{COLOR_RESET}")
                    return
                print(f"{COLOR_INFO}Reusing existing Steam shortcut with AppID {existing_appid}.{COLOR_RESET}")
            elif choice == "2":
                new_name = input(
                    f"{COLOR_PROMPT}New shortcut name (or 'q' to cancel): {COLOR_RESET}"
                ).strip()
                if not new_name or new_name.lower() == 'q':
                    print("Installation cancelled.")
                    return
                if new_name == shortcut_name:
                    print(f"{COLOR_ERROR}Please enter a different name to resolve the conflict.{COLOR_RESET}")
                    return
                shortcut_name = new_name
            else:
                print("Installation cancelled.")
                return

        # Execute installation using backend service
        print(f"\n{COLOR_INFO}Starting Wabbajack installation...{COLOR_RESET}\n")

        service = WabbajackInstallerService()
        
        def progress_callback(message: str, percentage: int):
            step_num = int((percentage / 100) * 12) if percentage < 100 else 12
            print(f"{COLOR_INFO}[{step_num}/12] {message}{COLOR_RESET}")

        def log_callback(message: str):
            if "ERROR" in message or "WARNING" in message or "Failed" in message:
                print(f"{COLOR_ERROR}{message}{COLOR_RESET}")
            elif "successfully" in message.lower() or "created" in message.lower() or "installed" in message.lower():
                print(f"{COLOR_SUCCESS}{message}{COLOR_RESET}")
            else:
                print(f"{COLOR_INFO}{message}{COLOR_RESET}")

        success, app_id, launch_options, gog_count, time_taken, error_msg = service.install_wabbajack(
            install_folder=install_dir,
            shortcut_name=shortcut_name,
            enable_gog=True,
            existing_appid=int(existing_appid) if existing_appid else None,
            progress_callback=progress_callback,
            log_callback=log_callback
        )

        if success:
            print(f"\n{COLOR_SUCCESS}{'='*60}{COLOR_RESET}")
            print(f"{COLOR_SUCCESS}Wabbajack installation complete!{COLOR_RESET}")
            print(f"{COLOR_SUCCESS}{'='*60}{COLOR_RESET}\n")

            print(f"{COLOR_INFO}Installation directory: {install_dir}{COLOR_RESET}")
            print(f"{COLOR_INFO}Steam AppID: {app_id}{COLOR_RESET}")
            if time_taken:
                print(f"{COLOR_INFO}Time taken: {time_taken}{COLOR_RESET}")
            
            # Show launch options note (matches GUI)
            if launch_options and "STEAM_COMPAT_MOUNTS" in launch_options:
                print(f"\n{COLOR_INFO}Note: To access other drives, add paths to launch options (Steam → Properties).{COLOR_RESET}")
                print(f"{COLOR_INFO}Append with colons: STEAM_COMPAT_MOUNTS=\"/existing:/new/path\" %command%{COLOR_RESET}")
            elif not launch_options:
                print(f"\n{COLOR_INFO}Note: To access other drives, add to launch options (Steam → Properties):{COLOR_RESET}")
                print(f"{COLOR_INFO}STEAM_COMPAT_MOUNTS=\"/path/to/directory\" %command%{COLOR_RESET}")
            
            print(f"\n{COLOR_INFO}Next steps:{COLOR_RESET}")
            print(f"  1. Find '{shortcut_name}' in your Steam library")
            print(f"  2. Launch Wabbajack from Steam")
        else:
            print(f"\n{COLOR_ERROR}Installation failed: {error_msg}{COLOR_RESET}")
            print(f"{COLOR_INFO}Check logs for details{COLOR_RESET}")

        input(f"\n{COLOR_PROMPT}Press Enter to continue...{COLOR_RESET}")

