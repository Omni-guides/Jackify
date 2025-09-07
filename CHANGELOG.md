# Jackify Changelog

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