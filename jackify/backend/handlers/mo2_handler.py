import shutil
import subprocess
import requests
from pathlib import Path
import re
import time
import os
from .ui_colors import COLOR_PROMPT, COLOR_SELECTION, COLOR_RESET, COLOR_INFO, COLOR_ERROR, COLOR_SUCCESS, COLOR_WARNING
from .status_utils import show_status, clear_status
from jackify.shared.ui_utils import print_section_header, print_subsection_header

class MO2Handler:
    """
    Handles downloading and installing Mod Organizer 2 (MO2) using system 7z.
    """
    def __init__(self, menu_handler):
        self.menu_handler = menu_handler
        # Import shortcut handler from menu_handler if available
        self.shortcut_handler = getattr(menu_handler, 'shortcut_handler', None)

    def _is_dangerous_path(self, path: Path) -> bool:
        # Block /, /home, /root, and the user's home directory
        home = Path.home().resolve()
        dangerous = [Path('/'), Path('/home'), Path('/root'), home]
        return any(path.resolve() == d for d in dangerous)

    def install_mo2(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        # Banner display handled by frontend
        print_section_header('Mod Organizer 2 Installation')
        # 1. Check for 7z
        if not shutil.which('7z'):
            print(f"{COLOR_ERROR}[ERROR] 7z is not installed. Please install it (e.g., sudo apt install p7zip-full).{COLOR_RESET}\n")
            return False
        # 2. Prompt for install location
        default_dir = Path.home() / "ModOrganizer2"
        prompt = f"Enter the full path where Mod Organizer 2 should be installed (default: {default_dir}, enter 'q' to cancel)"
        install_dir = self.menu_handler.get_directory_path(
            prompt_message=prompt,
            default_path=default_dir,
            create_if_missing=False,
            no_header=True
        )
        if not install_dir:
            print(f"\n{COLOR_INFO}Installation cancelled by user.{COLOR_RESET}\n")
            return False
        # Safety: Block dangerous paths
        if self._is_dangerous_path(install_dir):
            print(f"\n{COLOR_ERROR}Refusing to install to a dangerous directory: {install_dir}{COLOR_RESET}\n")
            return False
        # 3. Ask if user wants to add MO2 to Steam
        add_to_steam = input(f"Add Mod Organizer 2 as a custom Steam shortcut for Proton? (Y/n): ").strip().lower()
        add_to_steam = (add_to_steam == '' or add_to_steam.startswith('y'))
        shortcut_name = None
        if add_to_steam:
            shortcut_name = input(f"Enter a name for your new Steam shortcut (default: Mod Organizer 2): ").strip()
            if not shortcut_name:
                shortcut_name = "Mod Organizer 2"
        print_subsection_header('Configuration Phase')
        time.sleep(0.5)
        # 4. Create directory if needed, handle existing contents
        if not install_dir.exists():
            try:
                install_dir.mkdir(parents=True, exist_ok=True)
                show_status(f"Created directory: {install_dir}")
            except Exception as e:
                print(f"{COLOR_ERROR}[ERROR] Could not create directory: {e}{COLOR_RESET}\n")
                return False
        else:
            files = list(install_dir.iterdir())
            if files:
                print(f"Warning: The directory '{install_dir}' is not empty.")
                print("Warning: This will permanently delete all files in the folder. Type 'DELETE' to confirm:")
                confirm = input("").strip()
                if confirm != 'DELETE':
                    print(f"{COLOR_INFO}Cancelled by user. Please choose a different directory if you want to keep existing files.{COLOR_RESET}\n")
                    return False
                for f in files:
                    try:
                        if f.is_dir():
                            shutil.rmtree(f)
                        else:
                            f.unlink()
                    except Exception as e:
                        print(f"{COLOR_ERROR}Failed to delete {f}: {e}{COLOR_RESET}")
                show_status(f"Deleted all contents of {install_dir}")

        # 5. Fetch latest MO2 release info from GitHub
        show_status("Fetching latest Mod Organizer 2 release info...")
        try:
            response = requests.get("https://api.github.com/repos/ModOrganizer2/modorganizer/releases/latest", timeout=15, verify=True)
            response.raise_for_status()
            release = response.json()
        except Exception as e:
            print(f"{COLOR_ERROR}[ERROR] Failed to fetch MO2 release info: {e}{COLOR_RESET}\n")
            return False

        # 6. Find the correct .7z asset (exclude -pdbs, -src, etc)
        asset = None
        for a in release.get('assets', []):
            name = a['name']
            if re.match(r"Mod\.Organizer-\d+\.\d+(\.\d+)?\.7z$", name):
                asset = a
                break
        if not asset:
            print(f"{COLOR_ERROR}[ERROR] Could not find main MO2 .7z asset in latest release.{COLOR_RESET}\n")
            return False

        # 7. Download the archive
        show_status(f"Downloading {asset['name']}...")
        archive_path = install_dir / asset['name']
        try:
            with requests.get(asset['browser_download_url'], stream=True, timeout=60, verify=True) as r:
                r.raise_for_status()
                with open(archive_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
        except Exception as e:
            print(f"{COLOR_ERROR}[ERROR] Failed to download MO2 archive: {e}{COLOR_RESET}\n")
            return False

        # 8. Extract using 7z (suppress noisy output)
        show_status(f"Extracting to {install_dir}...")
        try:
            result = subprocess.run(['7z', 'x', str(archive_path), f'-o{install_dir}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode != 0:
                print(f"{COLOR_ERROR}[ERROR] Extraction failed: {result.stderr.decode(errors='ignore')}{COLOR_RESET}\n")
                return False
        except Exception as e:
            print(f"{COLOR_ERROR}[ERROR] Extraction failed: {e}{COLOR_RESET}\n")
            return False

        # 9. Validate extraction
        mo2_exe = next(install_dir.glob('**/ModOrganizer.exe'), None)
        if not mo2_exe:
            print(f"{COLOR_ERROR}[ERROR] ModOrganizer.exe not found after extraction. Please check extraction.{COLOR_RESET}\n")
            return False
        else:
            show_status(f"MO2 installed at: {mo2_exe.parent}")

        # 10. Add to Steam if requested
        if add_to_steam and self.shortcut_handler:
            show_status("Creating Steam shortcut...")
            try:
                from ..services.native_steam_service import NativeSteamService
                steam_service = NativeSteamService()
                
                success, app_id = steam_service.create_shortcut_with_proton(
                    app_name=shortcut_name,
                    exe_path=str(mo2_exe),
                    start_dir=str(mo2_exe.parent),
                    launch_options="%command%",
                    tags=["Jackify"],
                    proton_version="proton_experimental"
                )
                if not success or not app_id:
                    print(f"{COLOR_ERROR}[ERROR] Failed to create Steam shortcut.{COLOR_RESET}\n")
                else:
                    show_status(f"Steam shortcut created for '{COLOR_INFO}{shortcut_name}{COLOR_RESET}'.")
                    # Restart Steam and show manual steps (reuse logic from Configure Modlist)
                    print("\n───────────────────────────────────────────────────────────────────")
                    print(f"{COLOR_INFO}Important:{COLOR_RESET} Steam needs to restart to detect the new shortcut.")
                    print("This process involves several manual steps after the restart.")
                    restart_choice = input(f"\n{COLOR_PROMPT}Restart Steam automatically now? (Y/n): {COLOR_RESET}").strip().lower()
                    if restart_choice != 'n':
                        if hasattr(self.shortcut_handler, 'secure_steam_restart'):
                            print("Restarting Steam...")
                            self.shortcut_handler.secure_steam_restart()
                    print("\nAfter restarting, you MUST perform the manual Proton setup steps:")
                    print(f"  1. Locate '{COLOR_INFO}{shortcut_name}{COLOR_RESET}' in your Steam Library")
                    print("  2. Right-click and select 'Properties'")
                    print("  3. Switch to the 'Compatibility' tab")
                    print("  4. Check 'Force the use of a specific Steam Play compatibility tool'")
                    print("  5. Select 'Proton - Experimental' from the dropdown menu")
                    print("  6. Close the Properties window")
                    print(f"  7. Launch '{COLOR_INFO}{shortcut_name}{COLOR_RESET}' from your Steam Library")
                    print("  8. If Mod Organizer opens or produces any error message, that's normal")
                    print("  9. CLOSE Mod Organizer completely and return here")
                    print("───────────────────────────────────────────────────────────────────\n")
            except Exception as e:
                print(f"{COLOR_ERROR}[ERROR] Failed to create Steam shortcut: {e}{COLOR_RESET}\n")

        print(f"{COLOR_SUCCESS}Mod Organizer 2 has been installed successfully!{COLOR_RESET}\n")
        return True 