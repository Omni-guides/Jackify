# Jackify Changelog

## v0.7.2 - TTW Linux Installer 0.2.0
**Release Date:** 2026-07-18

### TTW Linux Installer now uses latest available
Previously the TTW Linux Installer was locked to v0.0.7 due to the change in output format beyond that version. Now Jackify can make use of the most up to date version of TTW Linux Installer

### Fixes
- Fixed Proton prefix creation being reported as failed when it was actually still finishing in the background (most likely on the first run of a newly installed Proton build), which could block install/configure entirely even though retrying immediately would work.
- Moved the "Check for Updates" action out of the About dialog into a dedicated button in the Tools Hub, which now lights up automatically when an update is available.
- Fixed a rare case where Synthesis's required NuGet security certificate import could silently drop a certificate during setup, causing NU3028/NU3037 signature errors on patcher compilation with no clear cause. Certificate import is now verified after writing and automatically retried if incomplete, and the post-install check will flag it clearly if it ever still happens.
- Fixed Synthesis still being able to spawn a very large number of concurrent dotnet.exe patcher builds on large modlists, which could exhaust system memory. Patcher build concurrency is now capped.
- Switched .NET 9 SDK to .NET 10 SDK for compatibility with newer Synthesis and patcher versions.
- Automatically updates Synthesis version during install - This fixes an issue where Synthesis' patcher list failing to load entirely on any modlist that includes it. The cause of the issue is the list of available patchers is fetched live from a GitHub-hosted directory outside Jackify's or the modlist's control, and a recent update to that directory broke compatibility with older bundled Synthesis versions. Jackify now automatically updates a modlist's bundled Synthesis to a known-compatible version during setup, and defaults its "MO2 Mode" build-safety setting off, since Linux has no equivalent to the "launch outside MO2" step it otherwise asks for.
- Synthesis's game data path is now filled in automatically during setup, instead of sometimes being left blank until set manually in Synthesis itself.
- Fixed Enderal Special Edition modlists not receiving xEdit, Pandora, and Synthesis compatibility fixes, and the post-install check incorrectly warning about them as missing.
- Fixed an occasional crash when the modlist gallery finished loading faster than its loading overlay could appear.
- Fixed the crash-report dialog itself failing to appear after certain unhandled errors.

---

## v0.7.1.1 - Synthesis, Starfield, and Stability Fixes
**Release Date:** 2026-07-08

### Fixes
- Fixed vcrun2022/vcrun2012 native component installs leaving Wine's own runtime DLLs in effect instead of the real ones, causing DLL load failures in some situations.
- Fixed instances where Synthesis under Proton spawning huge numbers of dotnet processes and running the system out of memory during patcher compilation.
- Improved Synthesis' required NuGet security certificate installation.
- Fixed a related NuGet signature validation failure (NU3037/NU3028) affecting some patchers that depend on older signed packages.
- Fixed Starfield modlists failing to launch on first use and showing a MO2 warning about missing profile INI files. Added recognition for Oblivion Remastered.
- Fixed the resolution dropdown being duplicated across three separate screens, and added detection of the actual connected screen resolutions.
- Fixed an intermittent crash when closing the install/configure window while CPU usage tracking was still running in the background.
- Fixed the archive download progress total sometimes shrinking or climbing indefinitely during large downloads.
- Fixed some modlists showing a "Failed to start the helper application: nxmhandler.exe" error when closing MO2.

---

## v0.7.1 - Remote Manifest System, Stability Fixes
**Release Date:** 2026-07-02

### Remote Manifest System
Jackify can now receive updated instructions without a new release. Tool definitions, problem mods, and compatibility data are fetched from a remote manifest hosted on github at runtime. The first use of this is automatic "problem mod" detection: a JSON-based manifest identifies mods known to cause issues under Proton and the specific action needed for each - disabling the mod, creating directories it expects to exist, etc - applied automatically during the install, with the affected list shown in the success window. The manifest can be updated centrally as new problem mods are identified (or removed), without needing to publish a new Jackify version, or any action by the user. This modular, manifest-based approach will be expanded upon in future versions of Jackify.

### Fixes
- Improved reliability of vcrun2022 and vcrun2012 native component installation, resolving DLL load failures in modlists that need them.
- Synthesis's required NuGet security certificate is no longer skipped on modlists that also use NetScriptFramework (NSF/CSF).
- Problem mod fixes that create extra directories (e.g. Dialogue History) are no longer applied unless the mod is actually present in your modlist.
- Proton auto-detection no longer selects GE-Proton 9.x when a current version is available. Old GE-Proton builds are now ranked below current Valve Proton releases.
- Closing the modlist gallery before it finishes loading no longer prevents it from loading again without restarting Jackify.
- Fixed intermittent crashes when closing screens or dialogs during installation and configuration workflows.
- Fixed ownership check incorrectly flagging modlist files as broken when they are owned by a supplementary group (e.g. autologin). The suggested fix command also showed the wrong group name.
- If Nexus API key decryption fails, Jackify now prompts you to re-authenticate rather than quietly using a garbage key.
- Permissions check on large installs no longer walks the entire directory tree when everything is already correct.
- Tools Hub: tools marked hidden in the remote manifest now disappear immediately on refresh rather than on next restart.
- Tools Hub: tools with no GitHub release (Nexus-only) now fall back to manual download rather than failing silently.
- Standalone MO2 setup now correctly uses Jackify's bundled 7z rather than requiring one to be installed system-wide.
- Manual download dialog now comes to the front automatically when it opens during a non-premium install.
- Failed downloads now report the mod name and reason in the error rather than a generic failure message.
- Wabbajack installer now warns that Steam will close any running game during installation.
- Update checks against the GitHub API now respect a `GITHUB_TOKEN` env var and cache the result for 24 hours - useful on shared IPs that hit the unauthenticated rate limit.

---

## v0.7 - Tools Hub, Engine Choice, NXM Link Handling, Native Component Install, NSF/CSF Support
**Release Date:** 21/06/26

### Engine Choice and Tools Hub
- jackify-engine is no longer stored in the Jackify repository. It is fetched from GitHub during the AppImage build and can be updated independently via the Jackify Tools Hub without requiring a new Jackify release.
- EXPERIMENTAL: Choose between jackify-engine (hash-matched with Wabbajack, proven) and CLF3 (faster install, not hash-matched with Wabbajack). Use the **Use Experimental Engine** checkbox on the Install Modlist screen, or switch permanently via the Tools Hub.
- A new Tools Hub available from Additional Tasks: download, update, downgrade a growing list of additional tools such as TTW Linux Installer and Radium Textures, as well as install engines.

### NXM Link Handling
- Jackify can become the registered nxm:// handler for your system.
- Clicking a Nexus "Mod Manager Download" or "Vortex" button link while MO2 is open routes the download directly to MO2 in your active modlist prefix.
- If MO2 is not running, the link opens Jackify to a standalone dialog to select which modlist to send the download to.

### .NET Script Framework (NSF) / Custom Skills Framework (CSF) Support
- Skyrim 1.5.97 Modlists using NetScriptFramework and Custom Skills Framework are now detected automatically. dotnet48 is installed via the bundled winetricks verb after Wine Mono is removed, then the prefix is configured so CSF's menu loads correctly.

### Native Wine Component Installer
- Direct-source installation for d3dcompiler, xact, vcrun2022, vcrun2012, and dotnet 6/7/8. Components are downloaded directly from Microsoft/Mozilla and extracted or installed.
- winetricks and protontricks remain as fallback for any component not handled natively. All being well, first step towards removing the hard requirement of protontricks.

### Install Verification
- After install and configure workflows complete, Jackify verifies that the Wine prefix, Steam shortcut, and Proton compatibility tool are all correctly in place. Results are shown in the success dialog with a breakdown of any issues found. Up to 100 checks are performed depending on the game type and modlist contents.
- Verification can be run on an existing Modlist at any time from the Additional Tools menu.

### Diagnostics Bundle
- Export a diagnostics bundle (logs, system info, config summary) from Additional Tasks. Attach to bug reports to speed up support.

### GOG and Epic Games via Heroic
- Both jackify-engine and Jackify should now detect games installed via Heroic Launcher (GOG and Epic), including both native and Flatpak Heroic installations - note that the Modlist itself HAS to support the GOG/Epic version of the base game, and not many do - there is nothing I can do about this.
- GOG/Epic versions of FO3/FNV should now be usable for TTW generation.

### Fixes
- Configure Existing Modlist now correctly updates `STEAM_COMPAT_MOUNTS` in your Steam shortcut's launch options to include MO2's download_directory so that it is accessible inside MO2.
- Jackify Download Manager manual download columns are now sortable, including numeric sort for file sizes.
- SD card game path detection no longer incorrectly requires a `/Games/` component in the path.
- Download directory should now correctly show the in-Proton path and not the Linux FS path, which was corrupting the download_directory path in MO2.
- Proton version selection now scans installed versions dynamically. Proton 11 (and any future version) is found and ranked correctly.
- Steam grid artwork: if a modlist ships a partial SteamIcons directory, missing slots are now filled from SteamGridDB rather than left blank.
- FO4VR: vcrun2012 applied automatically during tool configuration, as per community suggestion.
- Fallout 4: Creation Kit missing-files error is now detected correctly, rather than stating Skyrim CK is missing.
- Improved cancellation during Wine component installation. Now terminates winetricks and Wine subprocesses immediately rather than waiting for them to finish.
- Fixed: Manual downloads could open the same download link a second time within seconds if the file was still being written to disk when the watcher first detected it.
- Fixed: Files that finished downloading were sometimes not picked up by the watch folder scanner, leaving items stuck on "pending" and requiring manual intervention.
- Added a "Scan Now" button to the manual download dialog to force an immediate re-scan of the watch directory without waiting for the next automatic poll.
- JContainers64.dll Linux crash fix: Skyrim SE modlists using SKSE 1.6.1170 with JContainers are detected automatically during configuration. The incompatible DLL is replaced with a Linux-compatible build, with the original backed up.

### Engine (0.5.6)
- Heroic Launcher game detection (GOG + Epic, native and Flatpak).
- Fixed case-duplicate archive entries causing hash-mismatch failures on Linux when archives contain files differing only in case.
- Fixed garbled progress lines where tails of longer messages bled through on carriage-return output.

---

## v0.6.0.1 - Hotfix
**Release Date:** 24/04/26

- Resolved some issues with the integration of jackify-engine 0.5.4.

---

## v0.6 - Game Support Expansion, Modding Tool Support, Post-Install Quality
**Release Date:** 20/04/26

### New Game Support
- Additional Game Support - Post-Install automation for BG3, Skyrim VR, and Fallout 4 VR.
- Skyrim VR / Fallout 4 VR: if your modlist needs additional steps you know of, that Jackify does not yet handle, please open an issue on GitHub with your modlist name and the additional steps required. I cannot testing FO4VR directly as I dont own the game.

### Modding Tool Support
- Initial compatibility settings for xEdit, Synthesis, and Pandora are applied automatically during install and configure. Re-apply any time via "Configure Tool Compatibility" in Additional Tasks.

### Steam Shortcut Graphics
- Steam grid artwork now automatically applied to each shortcut, populating all five slots correctly (portrait, landscape, hero, logo, tenfoot).

### First-Launch Reliability
- First Launch Fixes - Skyrim SE modlists should now launch cleanly first time. No more first-launch crash, incorrect AE/CC popup display, initial NXM prompt in MO2, character creation issues, and wrong initial save location.

### Fixes
- Configuration no longer wipes game install paths. Registry writes are now targeted rather than full-prefix replacements.
- Fixed crashes on shutdown caused by force-killing background threads.

### Logging
- Console output reduced to errors only. All informational output goes to the log file and Show Details panel.

### Engine (0.5.4)
- Fixed Nexus sessions silently expiring after installs longer than ~1 hour. The engine now persists refreshed OAuth tokens so you stay logged in across long installs.
- Fixed large downloads hanging indefinitely if a Nexus CDN connection stalled mid-transfer. Downloads now recover automatically and resume from where they left off.
- Removed the disk space pre-flight check, which was incorrectly blocking installs for users with sufficient space. Out-of-disk conditions are still caught and reported if they actually occur.

---

## v0.5.0.4 - Hotfix
**Release Date:** 29/03/26

- Fixed self-update failing silently due to the downloaded archive overwriting the extraction target before the update helper could apply it.
- Engine updated to 0.5.3. NAME_MAX pre-flight check removed (was incorrectly blocking installs on standard filesystems). eCryptFS/fscrypt users still receive an error at the point of failure.
- Fixed Google Drive downloads failing. The Wabbajack CDN proxy was returning a cached broken response for some files; the engine now detects the hash mismatch, retries direct, and constructs a `drive.usercontent.google.com` URL with `confirm=t` to bypass the virus-scan warning page.
- Fixed focus stealing from other windows during the Wine component install phase.
- Fixed a crash on window close from a leaked focus-reclaim timer.
- Baloo file indexer suspended during install and config phases on KDE. No-op elsewhere.
- Fixed Flatpak protontricks install failing on fresh Steam Decks due to Flathub not being registered at user scope.

## v0.5.0.3 - Hotfix
**Release Date:** 23/03/26

- Engine updated to 0.5.2.
- Fixed manual downloads getting stuck on "Browser Opened" when the expected filename has a leading numeric prefix (e.g. `1_filename.zip`) that is absent from the browser-saved file. Both the live download watcher and the startup precheck scan now handle this correctly.
- Fixed "Continue Anyway" on the disk space warning having no effect. The flag was missing from the CLI argument parser, and a separate engine-level registration bug caused it to be rejected regardless. Both are now resolved. The dialog also correctly displays separate download and install space requirements and notes when both paths share the same drive.
- Fixed FNV, FO3, and Enderal modlists losing their game registry paths after configuration. The curated registry files applied during the configuration phase overwrite the Wine prefix registry entirely, wiping the game install paths injected earlier. Jackify now re-injects the correct paths immediately after the curated files are applied.
- Improved detection and guidance for modlists that require the Skyrim Special Edition Creation Kit. If the engine reports missing Creation Kit files, Jackify now surfaces step-by-step instructions for installing and first-launching the Creation Kit via Steam so the required files are in place before retrying.
- Filesystem filename length limit (NAME_MAX) no longer hard-blocks installation on standard filesystems. The check previously triggered incorrectly on ext4/btrfs/XFS. For users on encrypted home directories where the limit is genuinely reduced, Jackify now shows a warning dialog listing the affected files with a "Continue Anyway" option.
- Archive index errors now produce an actionable failure message identifying the specific archive to delete and re-download, rather than a bare engine exception.
- TTW installer temporary working files are now cleaned up after each TTW installation run. These files were previously never removed and could accumulate several GB per install attempt.
- Each GitHub release now includes a `SHA256SUMS` file for verifying your download. See the README for instructions.

## v0.5.0.2 - Hotfix
**Release Date:** 15/03/26

- Disk space warning at install start is no longer a hard block. If the pre-flight check fires before any download or install progress has started, Jackify now shows a warning dialog with the required and available space, a note that modlist updates typically need far less space than a fresh install, and a "Continue Anyway" option. Cancelling still aborts normally.
- Engine: fixed a false-positive in the pre-flight filename length check that could incorrectly trigger on modlist paths using backslash separators.
- Engine: temp folder cleanup at the end of install no longer crashes an otherwise successful installation if a BSA or temp directory is still locked.

## v0.5.0.1 - Hotfix
**Release Date:** 13/03/26

- Fixed Proton prefix creation failing for users who previously had Flatpak Steam installed but have since switched to native Steam.
- Fixed Configure Existing Modlist mangling binary and working directory paths for modlists using a `StockGame` folder (no space variant).

## v0.5.0 - Non-Premium Support, Modlist Update Handling and Overall Reliability Improvements
**Release Date:** 13/03/26

### New in v0.5.0
- Full non-premium install support in both GUI and CLI. Feedback is welcome on this new feature, both positive and negative
- New Jackify Download Manager for Non-Premium accounts, or files Jackify cannot auto-download.
- Improved modlist update handling so existing installs are detected more reliably and Jackify can reuse the existing setup instead of creating duplicate Steam shortcuts.
- Improved Viva New Vegas automation across GUI and CLI paths.
- Improved Wabbajack and Mod Organizer 2 standalone installation workflows.
- Better guidance when Skyrim AE/CC content is missing.
- Further improvements on user-facing logging and error handling

### Manual Download Improvements
- Handles manual downloads more smoothly from start to finish:
  - opens required links for you in your system Browser
  - watches your download folder
  - verifies files and moves them to the correct location automatically,continues with the rest of the modlist install when ready
- Better controls in both GUI and CLI:
  - pause/resume download flows, or defer individual archives (useful if one is temporarily unavailable)
  - retry deferred items
  - reopen file links
  - change concurrent browser tab count
  - change watch folder
- Deferred items (e.g temporarily unavailable) are retried correctly on later retry/recheck passes.

### Update and Install Reliability
- Worked to improve feature parity between the GUI and CLI frontends, tidying up a few edge cases where CLI behavior did not yet match GUI workflows closely enough.
- Improved update messaging (clearer wording on success/failure).
- Better cancellation handling so stopping a workflow is less likely to leave background processes running.
- Better focus recovery after Steam restart in key workflows.
- Better handling when both Flatpak and native Steam are installed: Jackify now prefers the Steam install that actually contains your installed games, with safe fallback rules if both look valid.
- Install Proton selection now self-heals on startup if the configured Proton was removed, automatically falling back to the best available installed Proton.
- For `/var/home`-based installs (for example Bazzite layouts), ModOrganizer.ini path basis is now aligned so executable/working/game paths resolve correctly.

### Nexus Authentication
- OAuth protocol handler desktop file is now updated if the registered AppImage path no longer matches the current location, preventing silent callback failures after the AppImage is moved or renamed.
- OAuth waiting dialog now includes a "Paste callback URL" button for manual fallback if the browser does not dispatch the jackify:// callback automatically.

### Logging and Error Quality
- Better targeted guidance when required prerequisites or content are missing.
- Improved logging around updater source selection (Nexus/GitHub fallback behavior).
- Better error context while keeping sensitive tokens/keys redacted.
- Install failure fallback now surfaces recent actionable engine output (and resource-limit warnings) instead of only a generic exit-code message.

### Updated jackify-engine to 0.5.0:
- Improved non-premium/manual-download support through a structured manual-download protocol that lets Jackify pause, guide the user, recheck files, and continue installation cleanly once required archives are present.
- Better pre-flight validation before large downloads begin, including earlier checks for game availability, disk space, and filesystem path-length limits.
- More accurate structured error handling for installation failures, with better classification of storage, permission, network, authentication, and validation issues.

---

## v0.4.0 - Error Handling Rewrite
**Release Date:** 2026-02-25

### New Features
- Structured error handling across GUI and CLI with typed `JackifyError` dialogs (clear message, suggested action, numbered recovery steps, optional technical detail).
- Structured engine error receiver: stderr JSON errors are parsed and mapped to user-facing error types, with exit-code fallback.
- Nexus account tier indicator in Settings OAuth (`[Premium]` / `[Free]`) with cached status checks.
- Modlist metadata support via `.jackify_meta.json`, written after install and used by configure workflows.
- TTW eligibility workflow expanded:
  - Configure New / Configure Existing can trigger TTW workflow when eligible.
  - CLI `configure-modlist` now prompts TTW when eligible.
- FO3 support in configure workflows, including prefix/registry handling.
- Standalone MO2 setup in Additional Tasks (GUI and CLI).

### Bug Fixes
- Proton auto-detection reliability improved, including GE-Proton ranking and fallback behavior.
- Added detection support for system-packaged Proton layouts (Issue #162).
- Download stall false positives reduced by checking byte advancement instead of speed readout alone.
- Flatpak Steam access handling improved with install-directory override support.
- TTW installer output directory is pre-populated to the modlist location.
- Unknown game fallback behavior improved so Wine component installation can continue where appropriate.

### Improvements
- GUI debug log naming standardised to `jackify-debug.log`.
- Error reporting/logging flow cleaned up to improve user  facing info and hopefully ease support.
- "Lazy" GUI screen initialization (main menu first, other screens on demand).
- Proton handling improved with Valve Proton fallback when GE-Proton is unavailable.
- FNV/FO3/Enderal registry injection now attempts canonical `C:\Program Files (x86)\Steam\steamapps\common\<Game>` paths via in-prefix symlink, with fallback to real `Z:/D:` paths if symlink creation fails. Looking forward to feedback on this one if anyone still has their FNV launcher only show "Install" instead of "Play".

### Engine Updates
- jackify-engine updated to `0.4.8`.
- Archive download progress improvements (remaining size + ETA).
- Download speed reporting reliability improvements on Linux.
- ZIP extraction fixes for Cyrillic filenames.

---

## v0.3.0 - Codebase Refactoring
**Release Date:** 2026-02-06

### Technical Improvements
- **Code Architecture**: Refactored 13 large files (1000-5000 lines each) into 50+ focused modules using mixin pattern. All main files now under 600 lines.

### Bug Fixes
- **Configure New Modlist GUI**: Fixed window not shrinking when Show Details unchecked
- **CLI Wabbajack Installer**: Added missing installation command to CLI menu
- **Wabbajack Installer**: Fixed installation to non-primary disk

### Improvements
- **Wabbajack Install - Honour Install Proton**: Wabbajack installer now uses the user's selected Install Proton from Settings (same as modlist install/configure). Previously hardcoded to Proton Experimental. Fallback to Proton Experimental when no selection or path invalid.
- **STEAM_COMPAT_MOUNTS (Issue #155)**: Launch options now include mountpoints for both the modlist install path and the download path when known, so MO2 can access game and downloads on different drives. Uses new mountpoint helper and passes install_dir/download_dir through the Install a Modlist workflow.
- **MO2 download_directory (Issue #154)**: When configuring after Install a Modlist, Jackify now sets `download_directory` in ModOrganizer.ini to the correct Wine path (Z: or D: on SD card) so MO2 finds the download folder. Configure New and Configure Existing continue to leave or blank the key as before.
- **Winetricks / Protontricks**: For Flatpak Steam, use protontricks only. Winetricks alone struggles with the flatpak sandbox.
- **Wine Component Animation**: Added pulser animation for individual wine component installation progress in Configure Existing and Install Modlist workflows
- **Wabbajack Installer Log Rotation**: Added log rotation for Wabbajack installer workflow logs

---

## v0.2.2.2 - ModOrganizer.ini Path Fixes for SD Card Installations
**Release Date:** 2026-01-28

### Bug Fixes
- **ModOrganizer.ini Path Mangling**: Fixed incorrect drive letter assignment when modlist is on SD card but vanilla game is on internal storage. Now uses gamePath drive letter as source of truth for vanilla game paths.
- **Proton Config Name Mismatch (Issues #150, #151)**: Fixed incorrect Proton names written to Steam config.vdf CompatToolMapping. Naive string conversion produced wrong names (e.g., `proton_9.0_(beta)` instead of `proton_9`). Now resolves correct internal names from `compatibilitytool.vdf` (third-party) or App ID mapping (Valve Proton). CachyOS and other community Proton builds in `compatibilitytools.d/` are now detected and selectable.
- **Removed Lorerim/Lost Legacy Proton Override**: No longer forces Proton 9 for specific modlists. ENB compatibility warnings are handled by the success dialog instead.

### Engine Updates
- **jackify-engine 0.4.7**: Fixed incorrect quoting/escaping of MO2 `customExecutables` by writing clean, unquoted Proton `Z:\...` paths in `ModOrganizer.ini`. This eliminates engine-side quote corruption that previously triggered SD card path mangling issues.

### Improvements
- **Improved Wine Component install debug log output**: Will now print the full command being used for winetricks and protontricks when debug mode is enabled, making it easier to reproduce issues manually.

---

## v0.2.2.1 - TTW Installer Pinning and Configure New Modlist CLI Fix
**Release Date:** 2026-01-24

### Bug Fixes
- **Configure New Modlist CLI**: Fixed manual Proton setup prompts appearing in CLI. Now uses automated prefix workflow like the install command.
- **TTW_Linux_Installer Version Pinning**: Pinned to v0.0.7. Will re-introduce latest version following more testing.

---

## v0.2.2 - VNV Automation and First-Launch Improvements
**Release Date:** 2026-01-21

### Major Features
- **Viva New Vegas Post-Install Automation (experimental)**: Full automated workflow for the Viva New Vegas modlist. Handles root files copying, 4GB patcher, and BSA decompression as per the VNV install guide. This is an initial pass at automating this, so considered experimental.
- **Game Directory Pre-Creation**: Automatically creates My Documents/My Games and AppData/Local directories for some. Prevents some first-launch failures where games can't initialize under Proton. Supports Skyrim SE, FNV, FO4, Oblivion, Oblivion Remastered, Enderal, and Starfield so far.

### Bug Fixes
- **Configure Existing Modlist**: Fixed AttributeError when VNV automation check runs after configuration completes
- **Enderal Directory Creation**: Fixed bug where Enderal My Documents directory was created for all modlists instead of only Enderal

### Improvements
- **Winetricks Bundling**: Implemented Wine wrapper scripts that replicate protontricks' environment setup for improved reliability

---

## v0.2.1.1 - Bug Fixes and Improvements
**Release Date:** 2026-01-15

### Critical Bug Fixes
- **AppImage Crash on Steam Deck**: Fixed `NameError: name 'Tuple' is not defined` that prevented AppImage from launching on Steam Deck. Added missing `Tuple` import to `progress_models.py`

### Bug Fixes
- **Menu Routing**: Fixed "Configure Existing Modlist (In Steam)" opening wrong section (was routing to Wabbajack Installer instead of Configure Existing screen)
- **TTW Install Dialogue**: Fixed incorrect account reference (changed "mod.db" to "ModPub" to match actual download source)
- **Duplicate Method**: Removed duplicate `_handle_missing_downloader_error` method in winetricks handler
- **Issue #142**: Removed sudo execution from modlist configuration - now auto-fixes permissions when possible, provides manual instructions only when sudo required
- **Issue #133**: Updated VDF library to 4.0 for improved Steam file format compatibility (protontricks 1.13.1+ support)

### Features
- **Wine Component Error Handling**: Enhanced error messages for missing downloaders with platform-specific installation instructions (SteamOS/Steam Deck vs other distros)

### Dependencies
- **VDF Library**: Updated from PyPI vdf 3.4 to actively maintained solsticegamestudios/vdf 4.0 (used by Gentoo)
- **Winetricks**: Removed bundled downloaders that caused segfaults on some systems - now uses system-provided downloaders (aria2c/wget/curl)

---

## v0.2.1 - Wabbajack Installer and ENB Support
**Release Date:** 2025-01-12
Y
### Major Features
- **Automated Wabbajack Installation**: While I work on Non-Premium support, there is still a call for Wabbajack via Proton. The existing legacy bash script has been proving troublesome for some users, so I've added this as a new feature within Jackify. My aim is still to not need this in future, once Jackify can cover Non-Premium accounts.
- **ENB Detection and Configuration**: Automatic detection and configuration of `enblocal.ini` with `LinuxVersion=true` for all supported games
- **ENB Proton Warning**: Dedicated dialog with Proton version recommendations when ENB is detected

### Critical Bug Fixes
- **OAuth Token Stale State**: Re-check authentication before engine launch to prevent stale token errors after revocation
- **FNV SD Card Registry**: Fixed launcher not recognizing game on SD cards (uses `D:` drive for SD, `Z:` for internal)
- **CLI FILE_PROGRESS Spam**: Filter verbose output to preserve single-line progress updates
- **Steam Double Restart**: Removed legacy code causing double restart during configuration
- **TTW Installer lz4**: Fixed bundled lz4 detection by setting correct working directory

### Improvements
- **Winetricks Bundling**: Bundled critical dependencies (wget, sha256sum, unzip, 7z) for improved reliability
- **UI/UX**: Removed per-file download speeds to match Wabbajack upstream
- **Code Cleanup**: Removed PyInstaller references, use AppImage detection only
- **Wabbajack Installer UI**: Removed unused Process Monitor tab, improved Activity window with detailed step information
- **Steam AppID Overflow Fix**: Changed AppID handling to string type to prevent overflow errors with large Steam AppIDs

---

## v0.2.0.10 - Registry & Hashing Fixes
**Release Date:** 2025-01-04

### Engine Updates
- **jackify-engine 0.4.5**: Fixed archive extraction with backslashes (including pattern matching), data directory path configuration, and removed post-download .wabbajack hash validation. Engine now auto-refreshes OAuth tokens during long installations via `NEXUS_OAUTH_INFO` environment variable.

### Critical Bug Fixes
- **InstallationThread Crash**: Fixed crash during installation with error "'InstallationThread' object has no attribute 'auth_service'". Premium detection diagnostics code assumed auth_service existed but it was never passed to the thread. Affects all users when Premium detection (including false positives) is triggered.
- **Install Start Hang**: Fixed missing `oauth_info` parameter that prevented modlist installs from starting (hung at "Starting modlist installation...")
- **OAuth Token Auto-Refresh**: Fixed OAuth tokens expiring during long modlist installations. Jackify now refreshes tokens with 15-minute buffer before passing to engine. Engine receives full OAuth state via `NEXUS_OAUTH_INFO` environment variable, enabling automatic token refresh during multi-hour downloads. Fixes "Token has expired" errors that occurred 60 minutes into installations.
- **ShowDotFiles Registry Format**: Fixed Wine registry format bug causing hidden files to remain hidden in prefixes. Python string escaping issue wrote single backslash instead of double backslash in `[Software\\Wine]` section header. Added auto-detection and fix for broken format from curated registry files.
- **Dotnet4 Registry Fixes**: Confirmed universal dotnet4.x registry fixes (`*mscoree=native` and `OnlyUseLatestCLR=1`) are applied in all three workflows (Install, Configure New, Configure Existing) across both CLI and GUI interfaces
- **Proton Path Configuration**: Fixed `proton_path` writing invalid "auto" string to config.json - now uses `null` instead, preventing jackify-engine from receiving invalid paths

### Improvements
- **Wine Binary Detection**: Enhanced detection with recursive fallback search within Proton directory when expected paths don't exist (handles different Proton version structures)
- Added Jackify version logging at workflow start
- Fixed GUI log file rotation to only run in debug mode

---

## v0.2.0.9 - Critical Configuration Fixes
**Release Date:** 2025-12-31

### Bug Fixes
- Fixed AppID conversion bug causing Configure Existing failures
- Fixed missing MessageService import crash in Configure Existing
- Fixed RecursionError in config_handler.py logger
- Fixed winetricks automatic fallback to protontricks (was silently failing)

### Improvements
- Added detailed progress indicators for configuration workflows
- Fixed progress bar completion showing 100% instead of 95%
- Removed debug logging noise from file progress widget
- Enhanced Premium detection diagnostics for Issue #111
- Flatpak protontricks now auto-granted cache access for faster subsequent installs

---

## v0.2.0.8 - Bug Fixes and Improvements
**Release Date:** 2025-12-29

### Bug Fixes
- Fixed Configure New/Existing/TTW screens missing Activity tab and progress updates
- Fixed cancel/back buttons crashing in Configure workflows

### Improvements
- Install directory now auto-appends modlist name when selected from gallery

### Known Issues
- Mod filter temporarily disabled in gallery due to technical issue (tag and game filters still work)

---

## v0.2.0.7 - Critical Auth Fix
**Release Date:** 2025-12-28

### Critical Bug Fixes
- **OAuth Token Loss**: Fixed version comparison bug that was deleting OAuth tokens every time settings were saved (affects users on v0.2.0.4+)
- Fixed internal import paths for improved stability

---

## v0.2.0.6 - Premium Detection and Engine Update
**Release Date:** 2025-12-28

**IMPORTANT:** If you are on v0.2.0.5, automatic updates will not work. You must manually download and install v0.2.0.6.

### Engine Updates
- **jackify-engine 0.4.4**: Latest engine version with improvements

### Critical Bug Fixes
- **Auto-Update System**: Fixed broken update dialog import that prevented automatic updates
- **Premium Detection**: Fixed false Premium errors caused by overly-broad detection pattern triggering on jackify-engine 0.4.3's userinfo JSON output
- **Custom Data Directory**: Fixed AppImage always creating ~/Jackify on startup, even when user configured a custom jackify_data_dir
- **Proton Auto-Selection**: Fixed auto-selection writing invalid "auto" string to config on detection failure

### Quality Improvements
- Added pre-build import validator to prevent broken imports from reaching production

---

## v0.2.0.5 - Emergency OAuth Fix
**Release Date:** 2025-12-24

### Critical Bug Fixes
- **OAuth Authentication**: Fixed regression in v0.2.0.4 that prevented OAuth token encryption/decryption, breaking Nexus authentication for users

---

## v0.2.0.4 - Bugfixes & Improvements
**Release Date:** 2025-12-23

### Engine Updates
- **jackify-engine 0.4.3**: Fixed case sensitivity issues, archive extraction crashes, and improved error messages

### Bug Fixes
- Fixed modlist gallery metadata showing outdated versions (now always fetches fresh data)
- Fixed hardcoded ~/Jackify paths preventing custom data directory settings
- Fixed update check blocking GUI startup
- Improved Steam restart reliability (3-minute timeout, better error handling)
- Fixed Protontricks Flatpak installation on Steam Deck

### Backend Changes
- GPU texture conversion now always enabled (config setting deprecated)

### UI Improvements
- Redesigned modlist detail view to show more of hero image
- Improved gallery loading with animated feedback and faster initial load

---

## v0.2.0.3 - Engine Bugfix & Settings Cleanup
**Release Date:** 2025-12-21

### Engine Updates
- **jackify-engine 0.4.3**: Bugfix release

### UI Improvements
- **Settings Dialog**: Removed GPU disable toggle - GPU usage is now always enabled (the disable option was non-functional)

---

## v0.2.0.2 - Emergency Engine Bugfix
**Release Date:** 2025-12-18

### Engine Updates
- **jackify-engine 0.4.2**: Fixed OOM issue with jackify-engine 0.4.1 due to array size

---

## v0.2.0.1 - Critical Bugfix Release
**Release Date:** 2025-12-15

### Critical Bug Fixes
- **Directory Safety Validation**: Fixed data loss bug where directories with only a `downloads/` folder were incorrectly identified as valid modlist directories
- **Flatpak Steam Restart**: Fixed Steam restart failures on Ubuntu/PopOS by removing incompatible `-foreground` flag and increasing startup wait

### Bug Fixes
- **External Links**: Fixed Ko-fi, GitHub, and Nexus links not opening on some distros using xdg-open with clean environment
- **TTW Console Output**: Filtered standalone "OK"/"DONE" noise messages from TTW installation console
- **Activity Window**: Fixed progress display updates in TTW Installer and other workflows
- **Wine Component Installation**: Added status feedback during component installation showing component list
- **Progress Parser**: Added defensive checks to prevent segfaults from malformed engine output
- **Progress Parser Speed Info**: Fixed 'OperationType' object has no attribute 'lower' error by converting enum to string value when extracting speed info from timestamp status patterns

### Improvements
- **Default Wine Components**: Added dxvk to default component list for better graphics compatibility
- **TTW Installer UI**: Show version numbers in status displays

### Engine Updates
- **jackify-engine 0.4.1**: Download reliability fixes, BSA case sensitivity handling, external drive I/O limiting, GPU detection caching, and texture processing performance improvements

---

## v0.2.0 - Modlist Gallery, OAuth Authentication & Performance Improvements
**Release Date:** 2025-12-06

### Major Features

#### Modlist Selection Gallery
Complete overhaul of modlist selection (First pass):

**Core Features:**
- Card-based Modlist Selection browser with modlist images, titles, authors and metadata
- Game-specific filtering automatically applied based on selected game type
- Details per card: download/install/total sizes, tags, version, badges
- Async image loading from GitHub with local 7-day caching
- Detail view with full descriptions, banner images, and external links
- Selected modlist automatically populates Install Modlist workflow

**Search and Filtering:**
- Text search across modlist names and descriptions
- Multi-select tag filtering with normalized tags
- Show Official Only, Show NSFW, Hide Unavailable toggles
- Mod search capability - find modlists containing specific Nexus mods
- Randomised card ordering

**Performance:**
- Gallery images loading from cache
- Background metadata and image preloading when Install Modlist screen opens
- Efficient rendering - cards created once, filters toggle visibility
- Non-blocking UI with concurrent image downloads

**Steam Deck Optimized:**
- Dynamic card sizing (e.g 250x270 on Steam Deck, larger on desktop)
- Responsive grid layout (up to 4 columns on large screens, 3 on Steam Deck)
- Optimized spacing and padding for 1280x800 displays

#### OAuth 2.0 Authentication
Modern authentication for Nexus Mods with secure token management:

- One-click browser-based authorization with PKCE security
- Automatic token refresh with encrypted storage
- Authorisation status indicator on Install Modlist screen
- Works in both GUI and CLI workflows

#### Compact Mode UI Redesign
Streamlined interface with dynamic window management:

- Default compact mode with optional Details view
- Activity window tab (default), across all workflow screens
- Process Monitor tab still available 
- Show Details toggle for console output when needed

### Critical Fixes

### Replaced TTW Installer
- Replaced the previous TTW Installer due to complexities with its config file

#### GPU Texture Conversion (jackify-engine 0.4.0)
- Fixed GPU not being used for BC7/BC6H texture conversions
- Previous versions fell back to CPU-only despite GPU availability
- Added GPU toggle in Settings (enabled by default)

#### Winetricks Compatibility & Protontricks
- Fixed bundled winetricks path incompatibility
- Hopefully fixed winetricks in cases where it failed to download components
- For now, Jackify still defaults to bundled winetricks (Protontricks toggle in settings)

#### Steam Restart Reliability
- Enhanced Steam Restart so that is now hopefully works more reliably on all distros
- Fixed Flatpak detection blocking normal Steam start methods

### Technical Improvements

- Proton version usage clarified: Install Proton for installation/texture processing, Game Proton for shortcuts
- Centralised Steam detection in SystemInfo
- ConfigHandler refactored to always read fresh from disk
- Removed obsolete dotnet4.x code
- Enhanced Flatpak Steam compatdata detection with proper VDF parsing

### Bug Fixes

- TTW installation UI performance (batched output processing, non-blocking operations)
- Activity window animations (removed custom timers, Qt native rendering)
- Timer reset when returning from TTW screen
- Fixed bandwidth limit KB/s to bytes conversion
- Fixed AttributeError in AutomatedPrefixService.restart_steam()

### Engine Updates
- jackify-engine 0.4.0 with GPU texture conversion fixes and refactored file progress reporting

---

## v0.1.7.1 - Wine Component Verification & Flatpak Steam Fixes
**Release Date:** November 11, 2025

### Critical Bug Fixes
- **FIXED: Wine Component Installation Verification** - Jackify now verifies components are actually installed before reporting success

### Bug Fixes
- **Steam Deck SD Card Paths**: Fixed ModOrganizer.ini path corruption on SD card installs using regex-based stripping
- **Flatpak Steam Detection**: Fixed libraryfolders.vdf path detection for Flatpak Steam installations
- **Flatpak Steam Restart**: Steam restart service now properly detects and controls Flatpak Steam
- **Path Manipulation**: Fixed path corruption in Configure Existing/New Modlist (paths with spaces)

### Improvements
- Added network diagnostics before winetricks fallback to protontricks
- Enhanced component installation logging with verification status
- Added GE-Proton 10-14 recommendation to success message (ENB compatibility note for Valve's Proton 10)

### Engine Updates
- **jackify-engine 0.3.18**: Archive extraction fixes for Windows symlinks, bandwidth limiting fix, improved error messages

---

## v0.1.7 - TTW Automation & Bug Fixes
**Release Date:** November 1, 2025

### Major Features
- **TTW (Tale of Two Wastelands) Installation and Automation**
laf  - TTW Installation function using Hoolamike application - https://github.com/Niedzwiedzw/hoolamike
  - Automated workflow for TTW installation and integration into FNV modlists, where possible
  - Automatic detection of TTW-compatible modlists
  - User prompt after modlist installation with option to install TTW
  - Automated integration: file copying, load order updates, modlist.txt updates
  - Available in both CLI and GUI workflows

### Bug Fixes
- **Registry UTF-8 Decode Error**: Fixed crash during dotnet4.x installation when Wine outputs binary data
- **Python 3.10 Compatibility**: Fixed startup crash on Python 3.10 systems
- **TTW Steam Deck Layout**: Fixed window sizing issues on Steam Deck when entering/exiting TTW screen
- **TTW Integration Status**: Added visible status banner updates during modlist integration for collapsed mode
- **TTW Accidental Input Protection**: Added 3-second countdown to TTW installation prompt to prevent accidental dismissal
- **Settings Persistence**: Settings changes now persist correctly across workflows
- **Steam Deck Keyboard Input**: Fixed keyboard input failure on Steam Deck
- **Application Close Crash**: Fixed crash when closing application on Steam Deck
- **Winetricks Diagnostics**: Enhanced error detection with automatic fallback

---

## v0.1.6.6 - AppImage Bundling Fix
**Release Date:** October 29, 2025

### Bug Fixes
- **Fixed AppImage bundling issue** causing legacy code to be retained in rare circumstances

---

## v0.1.6.5 - Steam Deck SD Card Path Fix
**Release Date:** October 27, 2025

### Bug Fixes
- **Fixed Steam Deck SD card path manipulation** when jackify-engine installed
- **Fixed Ubuntu Qt platform plugin errors** by bundling XCB libraries
- **Added Flatpak GE-Proton detection** and protontricks installation choices
- **Extended Steam Deck SD card timeouts** for slower I/O operations

---

## v0.1.6.4 - Flatpak Steam Detection Hotfix
**Release Date:** October 24, 2025

### Critical Bug Fixes
- **FIXED: Flatpak Steam Detection**: Added support for `/data/Steam/` directory structure used by some Flatpak Steam installations
- **IMPROVED: Steam Path Detection**: Now checks all known Flatpak Steam directory structures for maximum compatibility

---

## v0.1.6.3 - Emergency Hotfix
**Release Date:** October 23, 2025

### Critical Bug Fixes
- **FIXED: Proton Detection for Custom Steam Libraries**: Now properly reads all Steam libraries from libraryfolders.vdf
- **IMPROVED: Registry Wine Binary Detection**: Uses user's configured Proton for better compatibility
- **IMPROVED: Error Handling**: Registry fixes now provide clear warnings if they fail instead of breaking entire workflow

---

## v0.1.6.2 - Minor Bug Fixes
**Release Date:** October 23, 2025

### Bug Fixes
- **Improved dotnet4.x Compatibility**: Universal registry fixes for better modlist compatibility
- **Fixed Proton 9 Override**: A bug meant that modlists with spaces in the name weren't being overridden correctly
- **Removed PageFileManager Plugin**: Eliminates Linux PageFile warnings

---

## v0.1.6.1 - Fix dotnet40 install and expand Game Proton override
**Release Date:** October 21, 2025

### Bug Fixes
- **Fixed dotnet40 Installation Failures**: Resolved widespread .NET Framework installation issues affecting multiple modlists
- **Added Lost Legacy Proton 9 Override**: Automatic ENB compatibility for Lost Legacy modlist
- **Fixed Symlinked Downloads**: Automatically handles symlinked download directories to avoid Wine compatibility issues

---

## v0.1.6 - Lorerim Proton Support
**Release Date:** October 16, 2025

### New Features
- **Lorerim Proton Override**: Automatically selects Proton 9 for Lorerim installations (GE-Proton9-27 preferred)
- **Engine Update**: jackify-engine v0.3.17

---

## v0.1.5.3 - Critical Bug Fixes
**Release Date:** October 2, 2025

### Critical Bug Fixes
- **Fixed Multi-User Steam Detection**: Properly reads loginusers.vdf and converts SteamID64 to SteamID3 for accurate user identification
- **Fixed dotnet40 Installation Failures**: Hybrid approach uses protontricks for dotnet40 (reliable), winetricks for other components (fast)
- **Fixed dotnet8 Installation**: Now properly handled by winetricks instead of unimplemented pass statement
- **Fixed D: Drive Detection**: SD card detection now only applies to Steam Deck systems, not regular Linux systems
- **Fixed SD Card Mount Patterns**: Replaced hardcoded mmcblk0p1 references with dynamic path detection
- **Fixed Debug Restart UX**: Replaced PyInstaller detection with AppImage detection for proper restart behavior

---

## v0.1.5.2 - Proton Configuration & Engine Updates
**Release Date:** September 30, 2025

### Critical Bug Fixes
- **Fixed Proton Version Selection**: Wine component installation now properly honors user-selected Proton version from Settings dialog
  - Previously, changing from GE-Proton to Proton Experimental in settings would still use the old version for component installation
  - Fixed ConfigHandler to reload fresh configuration from disk instead of using stale cache
  - Updated all Proton path retrieval across codebase to use fresh-reading methods

### Engine Updates
- **jackify-engine v0.3.16**: Updated to latest engine version with important reliability improvements
  - **Sanity Check Fallback**: Added Proton 7z.exe fallback for case sensitivity extraction failures
  - **Enhanced Error Messages**: Improved texconv/texdiag error messages to include original texture file names and conversion parameters

### Technical Improvements
- Enhanced configuration system reliability for multi-instance scenarios
- Improved error diagnostics for texture processing operations
- Fix Qt platform plugin discovery in AppImage distribution for improved compatibility

---

## v0.1.5.1 - Bug Fixes
**Release Date:** September 28, 2025

### Bug Fixes
- Fixed Steam user detection in multi-user environments
- Fixed controls not re-enabling after workflow errors
- Fixed screen state persistence between workflows

---

## v0.1.5 - Winetricks Integration & Enhanced Compatibility
**Release Date:** September 26, 2025

### Major Improvements
- **Winetricks Integration**: Replaced protontricks with bundled winetricks for faster, more reliable wine component installation
- **Enhanced SD Card Detection**: Dynamic detection of SD card mount points supports both `/run/media/mmcblk0p1` and `/run/media/deck/UUID` patterns
- **Smart Proton Detection**: Comprehensive GE-Proton support with detection in both steamapps/common and compatibilitytools.d directories
- **Steam Deck SD Card Support**: Fixed path handling for SD card installations on Steam Deck

### User Experience
- **No Focus Stealing**: Wine component installation runs in background without disrupting user workflow
- **Popup Suppression**: Eliminated wine GUI popups while maintaining functionality
- **GUI Navigation**: Fixed navigation issues after Tuxborn workflow removal

### Bug Fixes
- **CLI Configure Existing**: Fixed AppID detection with signed-to-unsigned conversion, removing protontricks dependency
- **GE-Proton Validation**: Fixed validation to support both Valve Proton and GE-Proton directory structures
- **Resolution Override**: Eliminated hardcoded 2560x1600 fallbacks that overrode user Steam Deck settings
- **VDF Case-Sensitivity**: Added case-insensitive parsing for Steam shortcuts fields
- **Cabextract Bundling**: Bundled cabextract binary to resolve winetricks dependency issues
- **ModOrganizer.ini Path Format**: Fixed missing backslash in gamePath format for proper Windows path structure
- **SD Card Binary Paths**: Corrected binary paths to use D: drive mapping instead of raw Linux paths for SD card installs
- **Proton Fallback Logic**: Enhanced fallback when user-selected Proton version is missing or invalid

#Y- **Settings Persistence**: Improved configuration saving with verification and logging
- **System Wine Elimination**: Comprehensive audit ensures Jackify never uses system wine installations
- **Winetricks Reliability**: Fixed vcrun2022 installation failures and wine app crashes
- **Enderal Registry Injection**: Switched from launch options to registry injection approach
- **Proton Path Detection**: Uses actual Steam libraries from libraryfolders.vdf instead of hardcoded paths

### Technical Improvements
- **Self-contained Cache**: Relocated winetricks cache to jackify_data_dir for better isolation

---

## v0.1.4 - GE-Proton Support and Performance Optimization
**Release Date:** September 22, 2025

### New Features
- **GE-Proton Detection**: Automatic detection and prioritization of GE-Proton versions
- **User-selectable Proton version**: Settings dialog displays all available Proton versions with type indicators

### Engine Updates
- **jackify-engine v0.3.15**: Reads Proton configuration from config.json, adds degree symbol handling for special characters, removes Wine fallback (Proton now required)

### Technical Improvements
- **Smart Priority**: GE-Proton 10+ → Proton Experimental → Proton 10 → Proton 9
- **Auto-Configuration**: Fresh installations automatically select optimal Proton version

### Bug Fixes
- **Steam VDF Compatibility**: Fixed case-sensitivity issues with Steam shortcuts.vdf parsing for Configure Existing Modlist workflows

---

## v0.1.3 - Enhanced Proton Support and System Compatibility
**Release Date:** September 21, 2025

### New Features
- **Enhanced Proton Detection**: Automatic fallback system with priority: Experimental → Proton 10 → Proton 9
- **Guided Proton Installation**: Professional auto-install dialog with Steam protocol integration for missing Proton versions
- **Enderal Game Support**: Added Enderal to supported games list with special handling for Somnium modlist structure
- **Proton Version Leniency**: Accept any Proton version 9+ instead of requiring Experimental

### UX Improvements
- **Resolution System Overhaul**: Eliminated hardcoded 2560x1600 fallbacks across all screens
- **Steam Deck Detection**: Proper 1280x800 default resolution with 1920x1080 fallback for desktop
- **Leave Unchanged Logic**: Fixed resolution setting to actually preserve existing user configurations

### Technical Improvements
- **Resolution Utilities**: New `shared/resolution_utils.py` with centralized resolution management
- **Protontricks Detection**: Enhanced detection for both native and Flatpak protontricks installations
- **Real-time Monitoring**: Progress tracking for Proton installation with directory stability detection

### Bug Fixes
- **Somnium Support**: Automatic detection of `files/ModOrganizer.exe` structure in edge-case modlists
- **Steam Protocol Integration**: Reliable triggering of Proton installation via `steam://install/` URLs
- **Manual Fallback**: Clear instructions and recheck functionality when auto-install fails

---

## v0.1.2 - About Dialog and System Information
**Release Date:** September 16, 2025

### New Features
- **About Dialog**: System information display with OS, kernel, desktop environment, and display server detection
- **Engine Version Detection**: Real-time jackify-engine version reporting
- **Update Integration**: Check for Updates functionality within About dialog
- **Support Tools**: Copy system info for troubleshooting
- **Configurable Jackify Directory**: Users can now customize the Jackify data directory location via Settings

### UX Improvements
- **Control Management**: Form controls are now disabled during install/configure workflows to prevent user conflicts (only Cancel remains active)
- **Auto-Accept Steam Restart**: Optional checkbox to automatically accept Steam restart dialogs for unattended workflows
- **Layout Optimization**: Resolution dropdown and Steam restart option share the same line for better space utilization

### Bug Fixes
- **Resolution Handler**: Fixed regression in resolution setting for Fallout 4 and other games when modlists use vanilla game directories instead of traditional "Stock Game" folders
- **DXVK Configuration**: Fixed dxvk.conf creation failure when modlists point directly to vanilla game installations
- **CLI Resolution Setting**: Fixed missing resolution prompting in CLI Install workflow

### Engine Updates
- **jackify-engine v0.3.14**: Updated to support configurable Jackify data directory, improved Nexus API error handling with better 404/403 responses, and enhanced error logging for troubleshooting

---

## v0.1.1 - Self-Updater Implementation
**Release Date:** September 17, 2025

### New Features
- **Self-Updater System**: Complete automatic update mechanism for Jackify AppImages
  - **GitHub Integration**: Automatic detection of new releases from GitHub
  - **GUI Update Dialog**: Professional update notification with Jackify theme styling
  - **CLI Update Command**: `--update` flag for manual update checks and installation
  - **Startup Checks**: Automatic update detection on application launch
  - **User Control**: Skip version, remind later, and download & install options

### Technical Implementation
- **UpdateService**: Core service handling version detection, download, and installation
- **Full AppImage Replacement**: Reliable update mechanism using helper scripts
- **User-Writable Directories**: All update files stored in `~/Jackify/updates/` for consistency with existing directory structure
- **Progress Indication**: Download progress bars for both GUI and CLI
- **Error Handling**: Graceful fallbacks and comprehensive error messages

### Security Enhancements
- **AppImage Validation**: Prevents accidental updating of other AppImages when running from development environments
- **Path Verification**: Validates target AppImage contains "jackify" in filename before applying updates

### User Experience
- **Seamless Updates**: Users receive notifications when updates are available
- **Professional Interface**: Update dialog matches Jackify's visual theme
- **Flexible Options**: Users can choose when and how to update
- **No External Dependencies**: Works on all systems including SteamOS and immutable OSes

### Bug Fixes
- **Path Regression Fix**: Resolved regression where Configure New/Existing Modlist workflows were creating malformed paths
  - Fixed duplicate steamapps/common path generation
  - Corrected Steam library root path detection
  - Removed broken duplicate PathHandler causing path duplication
- **Enhanced Download Error Messages**: Added Nexus mod URLs to failed download errors for easier troubleshooting
  - Automatically appends direct Nexus mod page links
  - Supports all major games (Skyrim, Fallout 4, FNV, Oblivion, Starfield)

---

## v0.1.0.1 - Engine Update and Stability Improvements
**Release Date:** September 14, 2025

### Engine Updates
- **jackify-engine v0.3.13**: Major stability and resource management improvements
  - **Wine Prefix Cleanup**: Automatic cleanup of ~281MB Wine prefix directories after each modlist installation
  - **Manual Download Handling**: Fixed installation crashes when manual downloads are required
  - **Enhanced Error Messaging**: Detailed mod information for failed downloads (Nexus ModID/FileID, Google Drive, HTTP sources)
  - **Resource Settings Compliance**: Fixed resource settings not being respected during VFS and Installer operations
  - **VFS Crash Prevention**: Fixed KeyNotFoundException crashes during "Priming VFS" phase with missing archives
  - **Creation Club File Handling**: Fixed incorrect re-download attempts for Creation Club files
  - **BSA Extraction Fix**: Fixed DirectoryNotFoundException during BSA building operations

### Improvements
- **Disk Space Management**: No more accumulation of Wine prefix directories consuming hundreds of MB per installation
- **Clean Error Handling**: Manual download requirements now show clear summary instead of stack traces  
- **Better Resource Control**: Users can now properly control CPU usage during installation via resource_settings.json

### Bug Fixes
- **Download System**: Fixed GoogleDrive and MEGA download regressions
- **Configuration Integration**: MEGA tokens properly stored in Jackify's config directory structure
- **Installation Reliability**: Enhanced error handling prevents crashes with missing or corrupted archives

---

## v0.1.0 - First Public Release  
**Release Date:** September 11, 2025

**MILESTONE**: Jackify is now ready for public release! This marks the transition from private development to open-source availability.

### Major Milestone Features
- **Native Linux Engine**: jackify-engine v0.3.12+ providing optimal performance without Wine dependencies
- **Dual Interface**: Full-featured GUI and interactive CLI for all user preferences  
- **Steam Deck Optimized**: Native Steam integration with proper Proton configuration
- **Comprehensive Modlist Support**: Wide compatibility with Wabbajack modlists
- **Production Ready**: Stable, tested, and ready for community use

### Recent Critical Fixes
- **Steam Deck Proton Setting**: Fixed critical bug where Proton version was not being set for shortcuts on Steam Deck
  - Root cause: Steam AppID caching conflicts with deterministic AppID generation
  - Solution: Reverted to random AppID generation to avoid cache conflicts
  - Also fixes long-standing "Installed Locally" visibility issue
- **ProtontricksHandler Steam Deck Detection**: Fixed hardcoded steamdeck=False parameter

### New Features  
- **Ko-Fi Support Links**: Added official Ko-Fi support links using official brand colors
  - Centered link in bottom status bar: "♥ Support on Ko-fi"
  - Subtle link in success dialogs: "Enjoying Jackify? Support development ♥"
  - Uses official Ko-Fi blue color (#72A5F2) from brand guidelines

### Improvements
- **Process Monitor**: Updated to show texconv.exe processes and removed obsolete compressonator references
- **Terminal Output**: Suppressed GPU driver detection messages in normal mode (still visible with --debug)

---

## v0.0.32 - Engine Update and FNV Simplification  
**Release Date:** September 8, 2025

### Engine Update
- **jackify-engine v0.3.12**: Fixed file extraction encoding issues

### Improvements  
- **FNV Modlists**: Simplified configuration using registry injection instead of launch options
- **Code Cleanup**: Removed special-case launch option handling for FNV

---

## v0.0.31 - Pre-Alpha Polish Update
**Release Date:** September 7, 2025

### Engine Update
- **jackify-engine Updated**: Latest engine version with improved compatibility and performance

### Bug Fixes
- **GUI Startup Warning**: Fixed cosmetic "No shortcuts found pointing to 'ModOrganizer.exe'" warning appearing on GUI startup
  - Changed warning level to debug-only to reduce console noise for normal users
  - Warning still available for debugging when debug mode is enabled

---

## v0.0.30 - FNV/Enderal Support and better Modlist Selection
**Release Date:** September 5, 2025

### Major Features
- **FNV and Enderal Modlist Support**: Complete implementation for Fallout New Vegas and Enderal modlists
  - Automatic detection via nvse_loader.exe and Enderal Launcher.exe
  - Wine components routing to vanilla game compatdata (AppID 22380 for FNV, 933480 for Enderal)
  - Proper launch options with STEAM_COMPAT_DATA_PATH before Steam restart
  - Skip DXVK.conf creation for special games using vanilla compatdata
- **Enhanced Configuration Output**: Improved visual consistency with proper section headers and timing phases

### Bug Fixes
- **Process Cleanup**: Fixed critical bug where jackify-engine processes weren't terminated when GUI window closes unexpectedly
  - Added cleanup() method to ModlistOperations class for graceful process termination
  - Enhanced cleanup_processes() methods across all GUI screens
  - Integrated with existing main GUI cleanup infrastructure
- **Enderal Support**: Fixed Enderal modlists incorrectly showing "unsupported game" dialog
  - Added Enderal to supported games lists across codebase
  - Updated WabbajackParser with proper Enderal game type mappings
- **Configuration Formatting**: Resolved output formatting inconsistencies between phases

### Improved Modlist Selection Interface
- **Table Layout**: Replaced simple list with organized table showing Modlist Name, Download Size, Install Size, and Total Size in separate columns
- **Server-Side Filtering**: Improved performance by filtering modlists at the engine level instead of client-side
- **NSFW Checkbox**: Added "Show NSFW" checkbox in modlist selection (defaults to hidden)
- **Enhanced Status Indicators**: Clear indicators for unavailable modlists ([DOWN] with strikethrough) and adult content ([NSFW] in red)
- **Download Size Information**: Display all three size metrics (Download | Install | Total) to help users plan storage requirements
- **This is the first step towards a vastly improved Modlist Selection, with more to come soon.**
- **Making use of the updated jackify-engine features, such as --game and --show-all-sizes flags**

### Technical Improvements
- **Special Game Detection**: Detection system using multiple fallback mechanisms
`- **Timing System**: Implemented phase separation with proper timing resets between Installation and Configuration phases
- **Thread Management**: Improved cleanup of ConfigThread instances across configure screens

---

## v0.0.29 - STL tidy-up, jackify-engine 0.3.10 and bug fixes
**Release Date:** August 31, 2025

### Major Features
- **STL Dependency Completely Removed**: Removed the remaining steamtinkerlaunch traces.
- **Cross-Distribution Compatibility**: Fixed settings menu and API link compatibility issues

### Engine Updates
- **jackify-engine 0.3.10**: Improvements to manual download handling and error clarity
- **Manual Download Detection**: Phase 1 system for detecting files requiring manual download with user-friendly summaries
- **Enhanced Error Handling**: Clear distinction between corrupted files, download failures, and hash mismatches
- **Automatic Cleanup**: Corrupted files automatically deleted with clear guidance on root cause
- **Better User Experience**: Numbered download instructions with exact URLs - I will be improving manual downloads in future, but this is a first step.

### Technical Improvements
- **Compatibility Fixes**: Resolved UnboundLocalError in settings menu and Qt library conflicts
- **Steam Shortcut Fix**: Fixed regression with Steam shortcut creation


---

## v0.0.28 - Conditional Path Manipulation and Engine Update
**Release Date:** August 30, 2025

### Major Features
- **Conditional Path Manipulation**: Install a Modlist and Tuxborn Auto workflows now skip redundant path manipulation since jackify-engine 0.3.7 outputs correct paths directly
- **Workflow Optimization**: Configure New/Existing modlists retain path manipulation for manual installations
- **Engine Architecture**: Leverages jackify-engine's improved ModOrganizer.ini path handling

### Engine Updates
- **jackify-engine 0.3.8**: Enhanced ModOrganizer.ini path generation eliminates need for post-processing in engine-based workflows

### Technical Improvements
- **Selective Path Processing**: Added `engine_installed` flag to ModlistContext for workflow differentiation
- **Build System**: AppImage builds now use dynamic version extraction from source

### Bug Fixes
- **Path Corruption Prevention**: Eliminates redundant path manipulation that could introduce corruption
- **Version Consistency**: Fixed AppImage builds to use correct version numbers automatically
- **Steam Restart Reliability**: Improved Steam restart success rate by using aggressive pkill approach instead of unreliable steam -shutdown command
- **Settings Menu Compatibility**: Fixed UnboundLocalError for 'row' variable when resource_settings is empty
- **API Link Compatibility**: Replaced QDesktopServices with subprocess-based URL opening to resolve Qt library conflicts in PyInstaller environments

---

## v0.0.27 - Workflow Architecture Cleanup and Bug Fixes
**Release Date:** August 27, 2025

### Bug Fixes
- **Duplicate Shortcut Creation**: Fixed automated workflows creating multiple Steam shortcuts for the same modlist
- **GUI Workflow Optimization**: Removed manual shortcut creation from Tuxborn Installer and Configure New Modlist workflows
- **Workflow Consistency**: All three main workflows (Install Modlist, Configure New Modlist, Tuxborn Installer) now use unified automated approach

### Code Architecture Improvements
- **Legacy Code Removal**: Eliminated unused ModlistGUIService (42KB) that was creating maintenance overhead
- **Simplified Navigation**: ModlistTasksScreen now functions as pure navigation menu to existing workflows
- **Clean Architecture**: Removed obsolete service imports, initializations, and cleanup methods
- **Code Quality**: Eliminated "tombstone comments" and unused service references

### Deferred Features (Available in Future Release)

#### OAuth 2.0 Authentication for Nexus Mods
**Status:** Fully implemented but disabled pending Nexus Mods approval

The OAuth 2.0 authentication system has been fully developed and tested, but is temporarily disabled in v0.1.8 as we await approval from Nexus Mods for our OAuth application. The backend code remains intact and will be re-enabled immediately upon approval.

**Features (ready for deployment):**
- **Secure OAuth 2.0 + PKCE Flow**: Modern authentication to replace API key dependency
- **Encrypted Token Storage**: Tokens stored using Fernet encryption with automatic refresh
- **GUI Integration**: Clean status display on Install Modlist screen with authorize/revoke functionality
- **CLI Integration**: OAuth menu in Additional Tasks for command-line users
- **API Key Fallback**: Optional legacy API key support (configurable in Settings)
- **Unified Auth Service**: Single authentication layer supporting both OAuth and API key methods

**Current Limitation:** Awaiting Nexus approval for `jackify://oauth/callback` custom URI. Once approved, OAuth will be enabled as the primary authentication method with API key as optional fallback.

### Technical Details
- **Single Shortcut Creation Path**: All workflows now use `run_working_workflow()` → `create_shortcut_with_native_service()`
- **Service Layer Cleanup**: Removed dual codepath architecture in favor of proven automated workflows
- **Import Optimization**: Cleaned up unused service imports across GUI components

## v0.0.26 - Distribution Optimization and STL Integration Polish
**Release Date:** August 20, 2025

### Major Improvements
- **AppImage Size Optimization**: Implemented PyInstaller-style pre-filtering for PySide6 components, reducing AppImage size from 246M to 93M (62% reduction)
- **STL Distribution Integration**: Fixed SteamTinkerLaunch bundling and path detection for both PyInstaller and AppImage builds
- **Build Process Optimization**: Replaced inefficient "install everything then delete" approach with selective component installation

### Technical Improvements
- **Pre-filtering Architecture**: Only install essential PySide6 modules (QtCore, QtGui, QtWidgets, QtNetwork, QtConcurrent, QtOpenGL) and their corresponding Qt libraries
- **Unified STL Path Detection**: Created `get_stl_path()` function for consistent STL location across all environments
- **AppImage Build Optimization**: Selective copying of Qt libraries, plugins, and data files instead of full installation
- **PyInstaller Integration**: Fixed STL bundling using `binaries` instead of `datas` for proper execute permissions

### Bug Fixes
- **AppImage STL Path Resolution**: Fixed STL not found errors in AppImage runtime environment
- **PyInstaller STL Permissions**: Resolved permission denied errors for bundled STL binary
- **Build Script Paths**: Corrected STL source path in AppImage build script
- **Icon Display**: Re-added PyInstaller icon configuration for proper logo display

### Performance Improvements
- **AppImage Size**: Reduced from 246M to 93M (smaller than PyInstaller's 120M)
- **Build Efficiency**: Eliminated wasteful post-deletion operations in favor of pre-filtering
- **Dependency Management**: Streamlined PySide6 component selection for optimal size

---

## v0.0.25 - Shortcut Creation and Configuration Automation
**Release Date:** August 19, 2025

### Major Features
- **Fully Automated Shortcut Creation**: Complete automated prefix creation workflow using SteamTinkerLaunch. Jackify can now create the required new shortcut, set it's proton version, create the prefix and set Launch Options automatically. No more Manual Steps required.

### Technical Improvements
- **STL-based Prefix Creation**: Replace manual prefix setup with automated STL workflow
- **Compatibility Tool Setting**: Direct VDF manipulation for Proton version configuration
- **Cancellation Process Management**: Enhanced Jackify-related process detection and termination - still more to do on this during the Modlist Configuration phase.
- **Conflict Resolution**: Added handling of shortcut conflicts and existing installations

### Bug Fixes
- **Shortcut Installation Flag**: Fix Steam shortcuts not appearing in "Installed Locally" section
- **Indentation Errors**: Fix syntax errors in modlist parsing logic

---

## v0.0.24 - Engine Performance & Stability
**Release Date:** August 16, 2025

### Engine Updates
- **jackify-engine 0.3.2**: Performance improvements regarding concurrency, and a few minor bug fixes
- **Enhanced Modlist Parsing**: Improved parsing logic for better compatibility
- **Resource Management**: Better memory and resource handling

### Bug Fixes
- **Modlist Operations**: Fix parsing errors and improve reliability
- **GUI Stability**: Resolve various UI-related issues

---

## v0.0.22 - SteamTinkerLaunch/Remove Manual Steps Investigation (Dev build only)
**Release Date:** August 13, 2025

### Research & Development
- **STL Integration Research**: Investigation into SteamTinkerLaunch integration possibilities, with the aim of removing the required Manual Steps with a fully automated process flow.
- **Proton Version Setting**: Exploration of automated Proton compatibility tool configuration for new shortcuts
- **Shortcut Creation Methods**: Analysis of different Steam shortcut creation approaches

---

## v0.0.21 - Major Engine Update & UX Overhaul
**Release Date:** August 3, 2025

### Major Features
- **jackify-engine 0.3.0**: Complete rework of the texture conversion tools, increased performance and improved compatibility
- **Texture Conversion Tools**: Now using texconv.exe via Proton for texture processing, entirely invisible to the user.

### User Experience
- **Streamlined API Key Management**: Implement silent validation
- **Interface Changes**: Cleaned up some UI elements
- **Error Handling**: Improved error dialogs and user feedback

### Technical Improvements
- **Tool Integration**: New texture processing and diagnostic tools
- **Performance Optimization**: Significant speed improvements in modlist (7zz, texconv.exe)

---

## v0.0.20 - GUI Regression Fixes
**Release Date:** July 23, 2025

### Bug Fixes
- **Fixed console scroll behavior during error output**
  - Resolved race condition in `_safe_append_text()` where scroll position was checked before text append
  - Added scroll position tolerance (±1px) to handle rounding issues
  - Implemented auto-recovery when user manually scrolls back to bottom
  - Applied fixes consistently across all GUI screens

- **Enhanced API key save functionality**
  - Added immediate visual feedback when save checkbox is toggled
  - Implemented success/failure messages with color-coded tooltips
  - Added automatic checkbox unchecking when save operations fail
  - Improved error handling with comprehensive config write permission checks

- **Added live API key validation**
  - New "Validate" button with threaded validation against Nexus API endpoint
  - Visual feedback for validation results (success/error states)
  - Enhanced security with masked logging and no plain text API key exposure
  - Maintains existing base64 encoding for stored API keys

### Engine Updates
- **jackify-engine 0.2.11**: Performance improvements and bug fixes

#### Fixed
- **Accurate DDS Texture Format Detection and Skip Logic**
  - Replaced manual DDS header parsing with BCnEncoder-based format detection for improved accuracy and parity with upstream Wabbajack.
  - Added logic to skip recompression of B8G8R8X8_UNORM textures, copying them unchanged instead (hopefully matching upstream behavior).
  - Massive performance improvement: files that previously took 15+ minutes to process now copy in seconds.
  - Fixes major texture processing performance bottleneck in ESP-embedded textures.

##### Technical Details
- B8G8R8X8_UNORM format (88) is not supported by upstream Wabbajack's ToCompressionFormat; upstream appears to skip these files entirely.
- BCnEncoder-based format detection now used for all DDS files, ensuring correct handling and skipping of unsupported formats.
- Files detected as B8G8R8X8_UNORM now trigger copy logic instead of recompression, preventing unnecessary CPU-intensive work.
- Root cause: Previous logic attempted BC7 recompression on unsupported texture formats, causing major slowdowns.

---

## v0.0.19 - Resource Management
**Release Date:** 2025-07-20

### New Features
- **Resource Management System**: Resource tracking and management
- **jackify-engine 0.2.11**: Performance and stability improvements

### Technical Improvements
- **Memory Management**: Better resource allocation and cleanup
- **Process Monitoring**: Enhanced process tracking and management

## v0.0.18 - Build System Improvements
**Release Date:** July 17, 2025

### Technical Improvements
- **Fixed PyInstaller temp directory inclusion issue**
  - Added custom PyInstaller hook to exclude temporary files from build
  - Prevents build failures when Jackify is running during build process
  - Added automatic temp directory cleanup in build script
  - Updated .gitignore to exclude temp directory from version control

## v0.0.17 - Settings Dialog & UI Improvements
**Release Date:** July 17, 2025

### User Experience
- **Streamlined Resource Limits Interface**
  - Removed "Max Throughput" column
  - Added inline "Multithreading (Experimental)" checkbox for File Extractor resource
- **Multithreading Configuration**
  - Added experimental multithreading option for 7-Zip file extraction
  - Saves `_7zzMultiThread: "on"` to resource_settings.json when enabled
  - Default state is disabled (off)

### Technical Improvements
- **UI Scaling Implementation**
  - Fixed vertical scaling issues on Steam Deck (1280x800) and low-resolution displays
  - Implemented form-priority dynamic scaling across all 4 GUI screens
  - Form elements now maintain minimum 280px height to ensure full visibility
  - Console now dynamically shrinks to accommodate form needs instead of vice versa
  - Added resize event handling for real-time scaling adjustments
- **API Key URL Regression Fix**
  - Fixed API key acquisition URLs not opening browser on Linux systems
  - Replaced unreliable automatic external link handling with manual QDesktopServices integration
  - Affects both Install Modlist and Tuxborn Auto workflows

### Engine Updates
- **jackify-engine 0.2.7**: Performance improvements and bug fixes
#### Fixed
- **Excessive logging when resuming aborted installations**
  - Suppressed `DirectoryNotFoundException` warnings when re-running on previously aborted install directories
  - Moved these warnings to debug level while preserving retry behavior
  - Reduces noise when resuming installations without affecting functionality

#### Changed
- **Texture compression performance optimization**
  - Reduced BC7, BC6H, and BC5 compression quality settings from aggressive max quality to balanced levels
  - Disabled channel weighting and adjusted compression speed settings
  - Matches upstream Wabbajack's balanced compression approach for significantly faster texture processing
  - Addresses extremely long compression times for large texture files

## v0.0.16 - Steam Restart & User Experience
**Release Date:** July 16, 2025

### Bug Fixes
- **Fixed Steam interface not opening after restart in PyInstaller DIST mode**
  - Added comprehensive environment cleaning to `steam_restart_service.py` 
  - Prevents PyInstaller environment variables from contaminating Steam subprocess calls
  - Resolves issue where Steam interface wouldn't open after restart in three workflows requiring steam restarts

### User Experience
- **Reduced popup timeout from 5 seconds to 3 seconds**
  - Updated success dialogs and message service for faster user interaction
  - Affects OK/Cancel buttons on confirmation popups
- **Fixed Install Modlist form reset issue**
  - Form no longer resets when users select game type/modlist after filling out fields
  - Preserves user input during modlist selection workflow

### Workflow Improvements
- **Fixed misleading cancellation messages**
  - Users who cancel workflows now see proper cancellation message instead of "Install Failed"
  - Added cancellation detection logic similar to existing Tuxborn installer

### Security
- **Added SSL certificate verification to all HTTP requests**
  - All `requests.get()` calls now include `verify=True` parameter
  - Improves security of downloads from GitHub APIs and other external sources
  - Zero impact on functionality, pure security hardening
- **Removed hardcoded test paths**
  - Cleaned up development test paths from `wabbajack_handler.py`
  - Improved code hygiene and security posture

### Technical Improvements
- Enhanced environment variable cleaning in steam restart service
- Improved error handling and user feedback in workflow cancellation
- Consolidated timeout handling across GUI components

---

## v0.0.15 - GUI Workflow Logging Refactor
**Release Date:** July 15, 2025

### Major Fixes
- **GUI Workflow Logging Refactor**: Complete overhaul of logging behavior across all 4 GUI workflows
  - Fixed premature log rotation that was creating .1 files before workflows started
  - Moved log rotation from screen initialization to workflow execution start
  - Eliminated early log file creation in Install Modlist and Configure Existing workflows
  - All workflows now have proper log rotation timing and clean startup behavior

### Technical Improvements
- **Backend Service Integration**: Removed remaining CLI subprocess calls from Configure New Modlist workflow
  - Replaced CLI-based configuration with direct backend service calls
  - Unified manual steps validation across all workflows using backend services
  - Improved consistency between Tuxborn Automatic and Configure New Modlist workflows

### Technical Details
- **Thread Safety**: Preserved thread cleanup improvements in all workflows
- **Error Handling**: Improved error handling and user feedback during workflow failures
- **Code Consistency**: Unified patterns across all 4 workflows for maintainability

This release completes the logging refactor that was blocking development workflow.

## v0.0.14 - User Experience & Steam Restart
**Release Date:** July 9, 2025

### User Experience
- Introduced protection from accidental confirmations etc due to focus-stealing popups: All user-facing dialogs (info, warnings, confirmations) now use the new MessageService with safety levels (LOW, MEDIUM, HIGH) to prevent focus-stealing and accidental confirmation.
- Steam restart workflow improvements: Unified and hardened the logic for restarting Steam and handling post-restart manual steps in all workflows (Tuxborn Installer, Install Modlist, Configure New/Existing Modlist).

## v0.0.13 - Directory Safety & Configuration
**Release Date:** July 8, 2025

### New Features
- **Directory Safety System:** Prevents installation to dangerous system directories; adds install directory markers for validation.
- **Warning Dialogs:** Custom Jackify-themed warning dialogs for unsafe operations.

### Bug Fixes
- Fixed 'TuxbornInstallerScreen' object has no attribute 'context' errors.

### Technical Improvements
- **Configuration Persistence:** Debug mode and other settings persist across sessions.
- **Upgraded jackify-engine to 0.2.6, which includes:**

### Engine Updates
- **jackify-engine 0.2.6**: Performance improvements and enhanced user feedback

#### Added
- **Enhanced user feedback during long-running operations**
  - Single-line progress updates for extraction, texture conversion, and BSA building phases
  - Real-time progress counters showing current/total items (e.g., "Converting Textures (123/456): filename.dds")
  - Smart filename truncation to prevent line wrapping in narrow console windows
  - Carriage return-based progress display for cleaner console output

#### Fixed
- **Temp directory cleanup after installation**
  - Added explicit disposal of temporary file manager to ensure `__temp__` directory is properly cleaned up
  - Prevents accumulation of temporary files in modlist install directories
  - Cleanup occurs whether installation succeeds or fails

#### Changed
- **Console output improvements**
  - Progress updates now use single-line format with carriage returns for better user experience
  - Maintains compatibility with Jackify's output parsing system
  - Preserves all existing logging and error reporting functionality

## v0.0.12 - Success Dialog & UI Improvements
**Release Date:** July 7, 2025

### New Features
* Redesigned the workflow completion (“Success”) dialog. 
* Added an application icon, bundled with the PyInstaller build. Assets are now stored in a dedicated assets/ directory.
* Added fallback to pkill for instances where `steam -shutdown` wasn't working.

### User Experience
* All main workflows (Install, Tuxborn Auto, Configure New, Configure Existing) now use the updated SuccessDialog and display the correct game type.
* Improved field validation and error handling before starting installs.
* Changed text on pop up when user cancels workflow, was previously reusing Failed Install dialog.
* Upgraded jackify-engine to latest build (v.0.2.5)
* Temporarily hid the non-primary workflow functions from both GUI and CLI FE's.

### Bug Fixes
* Fixed missing app icon in PyInstaller builds by updating the spec file and asset paths.
* Scroll Bar behaviour - should be much better now

## v0.0.11 - Configurable Directories & Game Support
**Release Date:** July 4, 2025

### New Features
- **Configurable Base Directories**: Users can now customize default install and download base directories via `~/.config/jackify/config.json`
  - `modlist_install_base_dir`: Default `/home/user/Games`
  - `modlist_downloads_base_dir`: Default `/home/user/Games/Modlist_Downloads`
- **Enhanced Game Type Support**: Added support for new game types
  - Starfield
  - Oblivion Remastered
  - Improved game type detection and categorization
- **Unsupported Game Handling**: Clear warnings for unsupported games (e.g., Cyberpunk 2077)
  - GUI: Pop-up alert with user confirmation
  - CLI: Matching warning message with user confirmation
- **Simplified Directory Autofill**:
  - Clean default paths without guessing or appending modlist names
  - Consistent behavior across all configuration-based screens

### Technical Improvements
- **DXVK Configuration**: fixed malformed dxvk.conf contents
  - Now generates: `dxvk.enableGraphicsPipelineLibrary = False`
- **UI/UX Improvements**:
  - Removed redundant "Return to Main Menu" buttons
  - Improved dialog spacing, button order, and color consistency

### Bug Fixes
- **Game Type Filtering**: Fixed modlists appearing in multiple categories by improving matching logic
- **CLI/GUI Parity**: Unified backend service usage for consistent behavior across interfaces

## v0.0.10 - Previous Development Version
**Release Date:** Early Development
- Core CLI features implemented for running Wabbajack modlists on Linux.
- Initial support for Steam Deck and native Linux environments.
- Modular handler architecture for extensibility.

## v0.0.09 and Earlier
See commit history for previous versions.
