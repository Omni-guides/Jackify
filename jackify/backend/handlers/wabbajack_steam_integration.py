"""Steam integration methods for InstallWabbajackHandler (Mixin)."""
import logging
import os

from .status_utils import clear_status, show_status
from jackify.shared.colors import COLOR_ERROR, COLOR_INFO, COLOR_PROMPT, COLOR_RESET

logger = logging.getLogger(__name__)


class WabbajackSteamIntegrationMixin:
    """Mixin providing Steam shortcut and restart methods."""

    def _create_steam_shortcut(self) -> bool:
        """
        Creates the Steam shortcut for Wabbajack using the ShortcutHandler.

        Returns:
            bool: True on success, False otherwise.
        """
        if not self.shortcut_name or not self.install_path:
            self.logger.error("Cannot create shortcut: Missing shortcut name or install path.")
            return False

        self.logger.info(f"Creating Steam shortcut '{self.shortcut_name}'...")
        executable_path = str(self.install_path / "Wabbajack.exe")

        from ..services.native_steam_service import NativeSteamService
        steam_service = NativeSteamService()

        success, app_id = steam_service.create_shortcut_with_proton(
            app_name=self.shortcut_name,
            exe_path=executable_path,
            start_dir=os.path.dirname(executable_path),
            launch_options="PROTON_USE_WINED3D=1 %command%",
            tags=["Jackify", "Wabbajack"],
            proton_version="proton_experimental"
        )

        if success and app_id:
            self.initial_appid = app_id
            self.logger.info(f"Shortcut created successfully with initial AppID: {self.initial_appid}")
            return True
        else:
            self.logger.error("Failed to create Steam shortcut via ShortcutHandler.")
            print(f"{COLOR_ERROR}Error: Failed to create the Steam shortcut for Wabbajack.{COLOR_RESET}")
            return False

    def _display_manual_proton_steps(self):
        """Displays the detailed manual steps required for Proton setup."""
        if not self.shortcut_name:
            self.logger.error("Cannot display manual steps: shortcut_name not set.")
            self.logger.error("Internal Error: Shortcut name missing.")
            return

        print(f"\n{COLOR_PROMPT}--- Manual Proton Setup Required ---{COLOR_RESET}")
        print("Please complete the following steps in Steam:")
        print(f"  1. Locate the '{COLOR_INFO}{self.shortcut_name}{COLOR_RESET}' entry in your Steam Library")
        print("  2. Right-click and select 'Properties'")
        print("  3. Switch to the 'Compatibility' tab")
        print("  4. Check the box labeled 'Force the use of a specific Steam Play compatibility tool'")
        print("  5. Select 'Proton - Experimental' from the dropdown menu")
        print("  6. Close the Properties window")
        print(f"  7. Launch '{COLOR_INFO}{self.shortcut_name}{COLOR_RESET}' from your Steam Library")
        print("  8. Wait for Wabbajack to download its files and fully load")
        print("  9. Once Wabbajack has fully loaded, CLOSE IT completely and return here")
        print(f"{COLOR_PROMPT}------------------------------------{COLOR_RESET}")

    def _handle_steam_restart_and_manual_steps(self) -> bool:
        """Handles Steam restart and manual steps prompt, but no extra confirmation."""
        self.logger.info("Handling Steam restart and manual steps prompt.")
        clear_status()
        print("\n───────────────────────────────────────────────────────────────────")
        print(f"{COLOR_INFO}Manual Steps Required:{COLOR_RESET} After Steam restarts, follow the on-screen instructions to set Proton Experimental.")
        print("───────────────────────────────────────────────────────────────────")
        self.logger.info("Attempting secure Steam restart...")
        show_status("Restarting Steam")
        if not hasattr(self, 'shortcut_handler') or not self.shortcut_handler:
            self.logger.critical("ShortcutHandler not initialized in InstallWabbajackHandler!")
            self.logger.error("Internal Error: Shortcut handler not available for restart.")
            return False
        if self.shortcut_handler.secure_steam_restart():
            self.logger.info("Secure Steam restart successful.")
            clear_status()
            self._display_manual_proton_steps()
            print()
            input(f"{COLOR_PROMPT}Once you have completed ALL the steps above, press Enter to continue...{COLOR_RESET}")
            self.logger.info("User confirmed completion of manual steps.")
            return True
        else:
            self.logger.error("Secure Steam restart failed.")
            clear_status()
            print(f"\n{COLOR_ERROR}Error: Steam restart failed.{COLOR_RESET}")
            print("Please try restarting Steam manually:")
            print("1. Exit Steam completely (Steam -> Exit or right-click tray icon -> Exit)")
            print("2. Wait a few seconds")
            print("3. Start Steam again")
            print("\nAfter restarting, you MUST perform the manual Proton setup steps:")
            self._display_manual_proton_steps()
            print(f"\n{COLOR_ERROR}You will need to re-run this Jackify option after completing these steps.{COLOR_RESET}")
            print("───────────────────────────────────────────────────────────────────")
            return False

    def _redetect_appid(self) -> bool:
        """
        Re-detects the AppID for the shortcut after Steam restart.

        Returns:
            bool: True if AppID is found, False otherwise.
        """
        if not self.shortcut_name:
            self.logger.error("Cannot redetect AppID: shortcut_name not set.")
            return False

        self.logger.info(f"Re-detecting AppID for shortcut '{self.shortcut_name}'...")
        try:
            if not hasattr(self, 'protontricks_handler') or not self.protontricks_handler:
                self.logger.critical("ProtontricksHandler not initialized in InstallWabbajackHandler!")
                self.logger.error("Internal Error: Protontricks handler not available.")
                return False

            all_shortcuts = self.protontricks_handler.list_non_steam_shortcuts()

            if not all_shortcuts:
                self.logger.error("Protontricks listed no non-Steam shortcuts.")
                return False

            found_appid = None
            for name, appid in all_shortcuts.items():
                if name.lower() == self.shortcut_name.lower():
                    found_appid = appid
                    break

            if found_appid:
                self.final_appid = found_appid
                self.logger.info(f"Successfully re-detected AppID: {self.final_appid}")
                if self.initial_appid and self.initial_appid != self.final_appid:
                    self.logger.info(f"AppID changed after Steam restart: {self.initial_appid} -> {self.final_appid}")
                elif not self.initial_appid:
                    self.logger.warning("Initial AppID was not set, cannot compare.")
                return True
            else:
                self.logger.error(f"Shortcut '{self.shortcut_name}' not found in protontricks list after restart.")
                return False

        except Exception as e:
            self.logger.error(f"Error re-detecting AppID: {e}", exc_info=True)
            return False
