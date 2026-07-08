"""First-launch INI/anchor file seeding for Bethesda games (Mixin)."""

import os
from typing import Optional


class FilesystemFirstLaunchMixin:
    """Mixin providing per-game first-launch file seeding methods."""

    def _seed_skyrim_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """
        Pre-seed files in the Wine prefix that Skyrim SE/AE needs on first launch.

        Two files must exist before first launch to avoid USVFS and engine issues:

        1. AppData/Local/Skyrim Special Edition/Plugins.txt - empty anchor file.
           USVFS builds its VFS tree at MO2 startup. If this path does not exist,
           USVFS logs the directory as missing and skips adding Plugins.txt to the
           initial tree. It then tries to reroute the file dynamically, but a mutex
           deadlock (thread never releases the write mutex on first launch) blocks
           the reroute. The game falls through to the real filesystem, finds no
           Plugins.txt, and loads only base-game ESPs - causing a null form crash
           for any SKSE plugin that expects modlist ESPs (e.g. BladeAndBlunt.dll).
           On second launch the directory exists, USVFS initialises correctly, no crash.
           Pre-seeding an empty file gives USVFS its anchor; content is irrelevant
           because USVFS reroutes reads to the active MO2 profile's plugins.txt anyway.

        2. Documents/My Games/Skyrim Special Edition/SkyrimPrefs.ini - minimal stub.
           The CC/AE download prompt is triggered by bDownloadCC=0 (or absent) in
           SkyrimPrefs.ini. This check fires before PrivateProfileRedirector (PPR)
           hooks the Windows INI API, so the game reads the real prefix path directly,
           not the MO2 profile version. A minimal stub with bDownloadCC=1 suppresses
           the prompt. PPR redirects all subsequent reads to the active profile once
           it loads, so this stub is never read again after early engine init.
           Only created if the file does not already exist.
        """
        # Fix 1: empty Plugins.txt anchor for USVFS
        appdata_sse = os.path.join(prefix_user, "AppData", "Local", "Skyrim Special Edition")
        plugins_txt = os.path.join(appdata_sse, "Plugins.txt")
        try:
            os.makedirs(appdata_sse, exist_ok=True)
            if not os.path.exists(plugins_txt):
                open(plugins_txt, 'w').close()
                self.logger.info(f"Created Plugins.txt anchor for USVFS: {plugins_txt}")
            else:
                self.logger.debug(f"Plugins.txt already exists, skipping: {plugins_txt}")
        except Exception as e:
            self.logger.warning(f"Could not create Plugins.txt anchor: {e}")

        # Fix 2: minimal SkyrimPrefs.ini at real Documents path to suppress AE popup
        skyrimprefs_path = os.path.join(
            prefix_user, "Documents", "My Games", docs_dir_name, "SkyrimPrefs.ini"
        )
        try:
            if not os.path.exists(skyrimprefs_path):
                with open(skyrimprefs_path, 'w', encoding='utf-8') as f:
                    f.write("[General]\nbDownloadCC=1\n")
                self.logger.info(f"Created SkyrimPrefs.ini stub to suppress AE popup: {skyrimprefs_path}")
            else:
                self.logger.debug(f"SkyrimPrefs.ini already exists, skipping: {skyrimprefs_path}")
        except Exception as e:
            self.logger.warning(f"Could not create SkyrimPrefs.ini stub: {e}")

    def _seed_fo4_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """
        Pre-seed files in the Wine prefix that Fallout 4 needs on first launch.

        1. AppData/Local/Fallout4/Plugins.txt - empty anchor file for USVFS.
           Same mutex deadlock mechanism as Skyrim SE - confirmed to apply to FO4.

        INI stub for CC popup suppression is intentionally omitted until the correct
        key name in Fallout4Prefs.ini is confirmed via testing.
        """
        appdata_fo4 = os.path.join(prefix_user, "AppData", "Local", docs_dir_name)
        plugins_txt = os.path.join(appdata_fo4, "Plugins.txt")
        try:
            os.makedirs(appdata_fo4, exist_ok=True)
            if not os.path.exists(plugins_txt):
                open(plugins_txt, 'w').close()
                self.logger.info(f"Created Plugins.txt anchor for USVFS: {plugins_txt}")
            else:
                self.logger.debug(f"Plugins.txt already exists, skipping: {plugins_txt}")
        except Exception as e:
            self.logger.warning(f"Could not create Plugins.txt anchor: {e}")

    def _seed_starfield_first_launch_files(
        self, prefix_user: str, docs_dir_name: str, modlist_dir: Optional[str] = None
    ) -> None:
        """
        Pre-seed files in the Wine prefix that Starfield needs on first launch.

        1. AppData/Local/Starfield/Plugins.txt - empty anchor file for USVFS.
           Same mechanism as Skyrim SE/FO4.

        2. Documents/My Games/Starfield/StarfieldPrefs.ini and StarfieldCustom.ini -
           minimal stubs. MO2's Starfield plugin has no bundled default-ini fallback
           (unlike Skyrim/FO4, which fall back to a default ini shipped with the game).
           It lists both files as required (GameStarfield::iniFiles()) and copies both
           from this real path into the profile. On Windows they already exist because
           the user has launched vanilla Starfield at least once; a fresh Jackify
           install never does that, so MO2 finds nothing to copy from.

        3. profiles/<selected profile>/StarfieldPrefs.ini and StarfieldCustom.ini -
           same stubs, written directly into the active MO2 profile. MO2's missing-ini
           check (Profile::localSettingsEnabled) only looks at the profile folder itself,
           which starts empty regardless of step 2 above - it always warns
           "Missing profile-specific game INI files!" once unless the profile already
           has these files before MO2 ever checks. Only written if not already present,
           since a modlist's shipped profile may already carry real ini tweaks from
           the author (observed for StarfieldCustom.ini in practice).
        """
        appdata_starfield = os.path.join(prefix_user, "AppData", "Local", docs_dir_name)
        plugins_txt = os.path.join(appdata_starfield, "Plugins.txt")
        try:
            os.makedirs(appdata_starfield, exist_ok=True)
            if not os.path.exists(plugins_txt):
                open(plugins_txt, 'w').close()
                self.logger.info(f"Created Plugins.txt anchor for USVFS: {plugins_txt}")
            else:
                self.logger.debug(f"Plugins.txt already exists, skipping: {plugins_txt}")
        except Exception as e:
            self.logger.warning(f"Could not create Plugins.txt anchor: {e}")

        starfieldprefs_path = os.path.join(
            prefix_user, "Documents", "My Games", docs_dir_name, "StarfieldPrefs.ini"
        )
        try:
            if not os.path.exists(starfieldprefs_path):
                with open(starfieldprefs_path, 'w', encoding='utf-8') as f:
                    f.write("[Display]\n")
                self.logger.info(f"Created StarfieldPrefs.ini stub for first launch: {starfieldprefs_path}")
            else:
                self.logger.debug(f"StarfieldPrefs.ini already exists, skipping: {starfieldprefs_path}")
        except Exception as e:
            self.logger.warning(f"Could not create StarfieldPrefs.ini stub: {e}")

        starfieldcustom_path = os.path.join(
            prefix_user, "Documents", "My Games", docs_dir_name, "StarfieldCustom.ini"
        )
        try:
            if not os.path.exists(starfieldcustom_path):
                with open(starfieldcustom_path, 'w', encoding='utf-8') as f:
                    f.write("[General]\n")
                self.logger.info(f"Created StarfieldCustom.ini stub for first launch: {starfieldcustom_path}")
            else:
                self.logger.debug(f"StarfieldCustom.ini already exists, skipping: {starfieldcustom_path}")
        except Exception as e:
            self.logger.warning(f"Could not create StarfieldCustom.ini stub: {e}")

        if not modlist_dir:
            return

        try:
            from jackify.backend.utils.modlist_meta import _read_selected_profile
            profile_name = _read_selected_profile(modlist_dir)
        except Exception as e:
            self.logger.debug(f"Could not read selected_profile for Starfield ini pre-seed: {e}")
            return

        if not profile_name:
            self.logger.debug("No selected_profile found, skipping Starfield profile ini pre-seed")
            return

        profile_dir = os.path.join(modlist_dir, "profiles", profile_name)
        try:
            os.makedirs(profile_dir, exist_ok=True)
        except Exception as e:
            self.logger.warning(f"Could not create profile directory {profile_dir}: {e}")
            return

        for filename, stub_content in (
            ("StarfieldPrefs.ini", "[Display]\n"),
            ("StarfieldCustom.ini", "[General]\n"),
        ):
            profile_ini_path = os.path.join(profile_dir, filename)
            try:
                if not os.path.exists(profile_ini_path):
                    with open(profile_ini_path, 'w', encoding='utf-8') as f:
                        f.write(stub_content)
                    self.logger.info(f"Created {filename} stub in profile to suppress missing-ini warning: {profile_ini_path}")
                else:
                    self.logger.debug(f"{filename} already exists in profile, skipping: {profile_ini_path}")
            except Exception as e:
                self.logger.warning(f"Could not create {filename} stub in profile: {e}")

    def _seed_skyrimvr_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """
        Pre-seed files in the Wine prefix that Skyrim VR needs on first launch.

        1. AppData/Local/Skyrim VR/Plugins.txt - empty anchor file for USVFS.
           Same mutex deadlock mechanism as Skyrim SE applies to VR.

        2. Documents/My Games/Skyrim VR/SkyrimPrefs.ini - minimal stub with two keys:
           - bDownloadCC=1: suppresses the AE/CC download prompt (same engine behaviour
             as Skyrim SE; fires before PPR hooks the INI API).
           - bLoadVRPlayroom=0: prevents the game loading the Bethesda VR playroom
             tutorial on first launch. Without this, SkyrimVR skips the main menu and
             drops the user into the playroom, bypassing the modlist's startup sequence.
        """
        appdata_vr = os.path.join(prefix_user, "AppData", "Local", docs_dir_name)
        plugins_txt = os.path.join(appdata_vr, "Plugins.txt")
        try:
            os.makedirs(appdata_vr, exist_ok=True)
            if not os.path.exists(plugins_txt):
                open(plugins_txt, 'w').close()
                self.logger.info(f"Created Plugins.txt anchor for USVFS: {plugins_txt}")
            else:
                self.logger.debug(f"Plugins.txt already exists, skipping: {plugins_txt}")
        except Exception as e:
            self.logger.warning(f"Could not create Plugins.txt anchor: {e}")

        skyrimprefs_path = os.path.join(
            prefix_user, "Documents", "My Games", docs_dir_name, "SkyrimPrefs.ini"
        )
        try:
            if not os.path.exists(skyrimprefs_path):
                with open(skyrimprefs_path, 'w', encoding='utf-8') as f:
                    f.write("[General]\nbDownloadCC=1\nbLoadVRPlayroom=0\n")
                self.logger.info(f"Created SkyrimPrefs.ini stub for VR first-launch: {skyrimprefs_path}")
            else:
                self.logger.debug(f"SkyrimPrefs.ini already exists, skipping: {skyrimprefs_path}")
        except Exception as e:
            self.logger.warning(f"Could not create SkyrimPrefs.ini stub: {e}")

    def _seed_fallout4vr_first_launch_files(self, prefix_user: str, docs_dir_name: str) -> None:
        """
        Pre-seed files in the Wine prefix that Fallout 4 VR needs on first launch.

        1. AppData/Local/Fallout4VR/Plugins.txt - empty anchor file for USVFS.
           Same mutex deadlock mechanism as Skyrim SE and FO4 applies to VR.

        INI stub is intentionally omitted - the correct key name in Fallout4VRPrefs.ini
        has not been confirmed via testing.
        """
        appdata_fo4vr = os.path.join(prefix_user, "AppData", "Local", docs_dir_name)
        plugins_txt = os.path.join(appdata_fo4vr, "Plugins.txt")
        try:
            os.makedirs(appdata_fo4vr, exist_ok=True)
            if not os.path.exists(plugins_txt):
                open(plugins_txt, 'w').close()
                self.logger.info(f"Created Plugins.txt anchor for USVFS: {plugins_txt}")
            else:
                self.logger.debug(f"Plugins.txt already exists, skipping: {plugins_txt}")
        except Exception as e:
            self.logger.warning(f"Could not create Plugins.txt anchor: {e}")
