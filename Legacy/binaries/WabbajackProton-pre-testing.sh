#!/usr/bin/env bash
#
##################################################################
#                                                                #
# Attempt to automate installing Wabbajack on Linux Steam/Proton #
#                                                                #
#                     v0.20 - Refactored                         #
#                                                                #
##################################################################

# Set up logging
LOGFILE="$HOME/wabbajack-via-proton-sh.log"
echo "" > "$LOGFILE"

# Script configuration
SCRIPT_VERSION="0.20"
STEAM_IS_FLATPAK=0
VERBOSE=0
CURRENT_TASK=""
TOTAL_TASKS=10
CURRENT_TASK_NUM=0
IN_MODIFICATION_PHASE=0  # Add this flag

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        *)
            display "Unknown option: $1" "$RED"
            display "Usage: $0 [-v|--verbose]" "$YELLOW"
            exit 1
            ;;
    esac
done

# URLs for resources
WABBALIST_URL="https://raw.githubusercontent.com/wabbajack-tools/mod-lists/master/README.md"
WEBVIEW_INSTALLER_URL="https://node10.sokloud.com/filebrowser/api/public/dl/yqVTbUT8/rwatch/WebView/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
SYSTEM_REG_URL="https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/system.reg.github"
USER_REG_URL="https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/user.reg.github"

# Color codes for pretty output
GREEN="\e[32m"
YELLOW="\e[33m"
RED="\e[31m"
RESET="\e[0m"

# Logging function
log() {
    local message="$1"
    local log_level="${2:-INFO}"
    local timestamp=$(date +'%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$log_level] $message" >> "$LOGFILE"
    
    # If verbose mode is enabled, also print to console
    if [[ $VERBOSE -eq 1 ]]; then
        echo "[$timestamp] [$log_level] $message"
    fi
}

# Display and logging function
display() {
    local message="$1"
    local color="${2:-$RESET}"
    # Only log to file if it's not a user prompt or selection
    if [[ ! "$message" =~ "Please select" ]] && [[ ! "$message" =~ "Enter the number" ]]; then
        log "$message"
    fi
    echo -e "${color}${message}${RESET}"
}

# Verbose logging function
verbose_log() {
    if [[ $VERBOSE -eq 1 ]]; then
        log "$1" "VERBOSE"
    fi
}

# Section header function
log_section() {
    local message="$1"
    local separator="============================================"
    log "$separator"
    log "$message"
    log "$separator"
    if [[ $VERBOSE -eq 1 ]]; then
        echo -e "${YELLOW}$separator${RESET}"
        echo -e "${YELLOW}$message${RESET}"
        echo -e "${YELLOW}$separator${RESET}"
    fi
}

# Error handling function
error_exit() {
    display "$1" "$RED"
    log "$1" "ERROR"
    cleanup_wine_procs
    exit 1
}

# Progress bar function
update_progress() {
    # Only show progress bar during modification phase
    if [[ $IN_MODIFICATION_PHASE -eq 0 ]]; then
        return
    fi
    
    local percent=$1
    local bar_length=50
    local filled_length=$((percent * bar_length / 100))
    local bar=""
    
    # Create the bar string with = for filled portions
    for ((i = 0; i < bar_length; i++)); do
        if [ $i -lt $filled_length ]; then
            bar+="="
        else
            bar+=" "
        fi
    done
    
    # Use \r to return to start of line and overwrite previous progress
    printf "\r[%-${bar_length}s] %d%% - %s" "$bar" "$percent" "$CURRENT_TASK"
}

# Set current task function
set_current_task() {
    CURRENT_TASK="$1"
    
    # Only increment and show progress during modification phase
    if [[ $IN_MODIFICATION_PHASE -eq 1 ]]; then
        # Calculate percentage based on modification phase tasks
        local total_mod_tasks=11  # Updated to account for split configure_prefix tasks
        local percent=0
        
        # Only show 100% when we're actually complete
        if [[ "$CURRENT_TASK" == "Complete" ]]; then
            percent=100
        else
            # Calculate percentage based on current task number
            percent=$((CURRENT_TASK_NUM * 100 / total_mod_tasks))
            # Ensure we don't hit 100% before completion
            if [[ $percent -ge 100 ]]; then
                percent=99
            fi
        fi
        
        # Clear the current line before updating progress
        printf "\r%-100s\r" ""
        update_progress "$percent"
        
        # Increment task counter after displaying progress
        CURRENT_TASK_NUM=$((CURRENT_TASK_NUM + 1))
    fi
}

# Download function that uses either wget or curl
download_file() {
    local url="$1"
    local output_path="$2"
    local description="${3:-file}"
    
    # Only log to file, don't display to user
    log "Downloading $description..."
    
    if command -v wget &>/dev/null; then
        if wget "$url" -O "$output_path" >>"$LOGFILE" 2>&1; then
            log "Downloaded $description successfully using wget"
            return 0
        else
            error_exit "Failed to download $description with wget"
        fi
    elif command -v curl &>/dev/null; then
        if curl -sLo "$output_path" "$url" >>"$LOGFILE" 2>&1; then
            log "Downloaded $description successfully using curl"
            return 0
        else
            error_exit "Failed to download $description with curl"
        fi
    else
        error_exit "Neither wget nor curl is available. Cannot download $description"
    fi
}

display_banner() {
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║                  Wabbajack Proton Setup v$SCRIPT_VERSION                    ║"
    echo "║                                                                  ║"
    echo "║        A tool for running Wabbajack on Linux via Proton          ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    
    echo ""
    display "This script automates setting up Wabbajack to run on Linux via Steam's Proton compatibility layer." "$YELLOW"
    echo "───────────────────────────────────────────────────────────────────"
    display "Please be aware that this is experimental software and is *NOT* supported by the Wabbajack team." "$YELLOW"
    display "If you encounter issues, please report them on GitHub or the #unofficial-linux-support channel on Discord." "$YELLOW"
    echo "───────────────────────────────────────────────────────────────────"
    display "⚠ IMPORTANT: Use this script at your own risk." "$RED"
    echo ""
    echo -e "\e[33mPress any key to continue...\e[0m"
    read -n 1 -s -r -p ""
    echo ""
}

detect_steamdeck() {
    if [ -f "/etc/os-release" ] && grep -q "steamdeck" "/etc/os-release"; then
        STEAMDECK=1
        log "Running on Steam Deck"
    else
        STEAMDECK=0
        log "NOT running on Steam Deck"
    fi
}

detect_protontricks() {
    # Only log to file, don't display to user
    log "Detecting protontricks installation..."

    if command -v protontricks >/dev/null 2>&1; then
        PROTONTRICKS_PATH=$(command -v protontricks)
        # Check if the detected binary is actually a Flatpak wrapper
        if [[ -f "$PROTONTRICKS_PATH" ]] && grep -q "flatpak run" "$PROTONTRICKS_PATH"; then
            log "Detected Protontricks is a Flatpak wrapper at $PROTONTRICKS_PATH"
            WHICH_PROTONTRICKS="flatpak"
            return 0
        else
            log "Native Protontricks found at $PROTONTRICKS_PATH"
            WHICH_PROTONTRICKS="native"
            return 0
        fi
    elif flatpak list | grep -iq protontricks; then
        log "Flatpak Protontricks is installed"
        WHICH_PROTONTRICKS="flatpak"
        return 0
    else
        log "Protontricks not found. Do you wish to install it? (y/n): "
        display "Protontricks not found. Do you wish to install it? (y/n): " "$RED"
        read -p " " answer
        if [[ $answer =~ ^[Yy]$ ]]; then
            if [[ $STEAMDECK -eq 1 ]]; then
                if flatpak install -u -y --noninteractive flathub com.github.Matoking.protontricks; then
                    WHICH_PROTONTRICKS="flatpak"
                    return 0
                else
                    display "\n\e[31mFailed to install Protontricks via Flatpak. Please install it manually and rerun this script.\e[0m" "$RED"
                    exit 1
                fi
            else
                read -p "Choose installation method: 1) Flatpak (preferred) 2) Native: " choice
                if [[ $choice =~ 1 ]]; then
                    if flatpak install -u -y --noninteractive flathub com.github.Matoking.protontricks; then
                        WHICH_PROTONTRICKS="flatpak"
                        return 0
                    else
                        display "\n\e[31mFailed to install Protontricks via Flatpak. Please install it manually and rerun this script.\e[0m" "$RED"
                        exit 1
                    fi
                else
                    display "Sorry, there are too many distros to automate this!"
                    display "Please check how to install Protontricks using your OS package manager (yum, dnf, apt, pacman, etc.)"
                    display "\e[31mProtontricks is required for this script to function. Exiting.\e[0m" "$RED"
                    exit 1
                fi
            fi
        else
            display "\e[31mProtontricks is required for this script to function. Exiting.\e[0m" "$RED"
            exit 1
        fi
    fi
}

setup_protontricks_alias() {
    set_current_task "Setting up Protontricks aliases"
    if [[ "$WHICH_PROTONTRICKS" = "flatpak" ]]; then
        local protontricks_alias_exists=$(grep "^alias protontricks=" ~/.bashrc)
        local launch_alias_exists=$(grep "^alias protontricks-launch" ~/.bashrc)

        if [[ -z "$protontricks_alias_exists" ]]; then
            display "Adding protontricks alias to ~/.bashrc" "$YELLOW"
            echo "alias protontricks='flatpak run com.github.Matoking.protontricks'" >> ~/.bashrc
            source ~/.bashrc
        else
            log "protontricks alias already exists in ~/.bashrc"
        fi

        if [[ -z "$launch_alias_exists" ]]; then
            display "Adding protontricks-launch alias to ~/.bashrc" "$YELLOW"
            echo "alias protontricks-launch='flatpak run --command=protontricks-launch com.github.Matoking.protontricks'" >> ~/.bashrc
            source ~/.bashrc
        else
            log "protontricks-launch alias already exists in ~/.bashrc"
        fi
    else
        log "Protontricks is not installed via flatpak, skipping alias creation"
    fi
}

run_protontricks() {
    # Determine the protontricks binary path
    verbose_log "Running protontricks with arguments: $*"
    
    if [ "$WHICH_PROTONTRICKS" = "flatpak" ]; then
        verbose_log "Using Flatpak protontricks"
        # Redirect Wine output to /dev/null but keep protontricks output
        if [[ "$*" == *"-c"* ]]; then
            # For Wine commands, suppress output but check exit code
            if flatpak run com.github.Matoking.protontricks "$@" >/dev/null 2>&1; then
                return 0
            else
                return 1
            fi
        else
            # For non-Wine commands, show output but redirect stderr to /dev/null
            flatpak run com.github.Matoking.protontricks "$@" 2>/dev/null
        fi
    else
        verbose_log "Using native protontricks"
        # Redirect Wine output to /dev/null but keep protontricks output
        if [[ "$*" == *"-c"* ]]; then
            # For Wine commands, suppress output but check exit code
            if protontricks "$@" >/dev/null 2>&1; then
                return 0
            else
                return 1
            fi
        else
            # For non-Wine commands, show output but redirect stderr to /dev/null
            protontricks "$@" 2>/dev/null
        fi
    fi
}

check_protontricks_version() {
    set_current_task "Checking Protontricks version"
    # Get the current version of protontricks
    local protontricks_version=$(run_protontricks -V | cut -d ' ' -f 2 | sed 's/[()]//g' | sed 's/\.[0-9]$//')
    local protontricks_version_cleaned=$(echo "$protontricks_version" | sed 's/[^0-9.]//g')
    
    log "Protontricks Version: $protontricks_version_cleaned"
    
    # Compare version strings
    if [[ "$protontricks_version_cleaned" < "1.12" ]]; then
        error_exit "Your protontricks version is too old! Update to version 1.12 or newer and rerun this script."
    fi
}

get_wabbajack_path() {
    set_current_task "Detecting Wabbajack path"
    local wabbajack_path=""
    local wabbajack_entries=()
    local app_ids=()
    local app_names=()
    local all_app_ids=()
    local all_app_names=()
    local selection=""
    local use_all_shortcuts=0

    log "Detecting Wabbajack Install Directory..."
    verbose_log "Attempting to find Wabbajack entries using protontricks -l"

    # First, try to find Wabbajack entries using protontricks
    local protontricks_entries=$(run_protontricks -l | grep -i 'Non-Steam shortcut' | grep -i wabbajack)
    verbose_log "Protontricks output: $protontricks_entries"

    if [[ -n "$protontricks_entries" ]]; then
        log "Found Wabbajack entries via protontricks (name match)"
        while IFS= read -r line; do
            local app_id=$(echo "$line" | awk '{print $NF}' | sed 's:^.\(.*\).$:\1:')
            local app_name=$(echo "$line" | sed 's/^Non-Steam shortcut: //i' | sed 's: ([0-9]*)$::')
            if [[ -n "$app_id" ]]; then
                app_ids+=("$app_id")
                app_names+=("$app_name")
                log "Found App ID: $app_id, Name: $app_name"
            fi
        done <<< "$protontricks_entries"

        echo ""
        display "Wabbajack-related Steam entries found. Please select which one you wish to configure:" "$RED"
        for i in "${!app_ids[@]}"; do
            echo "$((i + 1)). ${app_names[i]} (App ID: ${app_ids[i]})"
        done
        local extra_option=$(( ${#app_ids[@]} + 1 ))
        echo "$extra_option. List all Steam shortcuts"
        echo "Please select the entry you want to use (1-$extra_option):"
        read -r selection
        if [[ "$selection" == "$extra_option" ]]; then
            use_all_shortcuts=1
        elif [[ "$selection" =~ ^[0-9]+$ ]] && ((selection >= 1 && selection <= ${#app_ids[@]})); then
            APPID="${app_ids[$((selection - 1))]}"
            log "Selected App ID: $APPID, Name: ${app_names[$((selection - 1))]}"
        else
            use_all_shortcuts=1
        fi
    else
        use_all_shortcuts=1
    fi

    # If requested, list all Non-Steam shortcuts
    if [[ $use_all_shortcuts -eq 1 ]]; then
        local all_entries=$(run_protontricks -l | grep -i 'Non-Steam shortcut')
        if [[ -z "$all_entries" ]]; then
            error_exit "No Non-Steam shortcuts found via protontricks. Please ensure you've added your entry as a non-Steam game and run it once via Steam."
        fi
        while IFS= read -r line; do
            local app_id=$(echo "$line" | awk '{print $NF}' | sed 's:^.\(.*\).$:\1:')
            local app_name=$(echo "$line" | sed 's/^Non-Steam shortcut: //i' | sed 's: ([0-9]*)$::')
            if [[ -n "$app_id" ]]; then
                all_app_ids+=("$app_id")
                all_app_names+=("$app_name")
                log "Found App ID: $app_id, Name: $app_name (all shortcuts)"
            fi
        done <<< "$all_entries"
        echo ""
        display "All Steam shortcuts detected. Please select which one you wish to configure:" "$RED"
        for i in "${!all_app_ids[@]}"; do
            echo "$((i + 1)). ${all_app_names[i]} (App ID: ${all_app_ids[i]})"
        done
        echo "Please select the entry you want to use (1-${#all_app_ids[@]}):"
        read -r selection
        if ! [[ "$selection" =~ ^[0-9]+$ ]] || ((selection < 1 || selection > ${#all_app_ids[@]})); then
            error_exit "Invalid selection"
        fi
        APPID="${all_app_ids[$((selection - 1))]}"
        log "Selected App ID: $APPID, Name: ${all_app_names[$((selection - 1))]}"
        echo ""
        echo "If you don't see your Wabbajack entry in the list, please make sure you have added it to Steam, set the Proton version, and run it once (then closed Wabbajack)."
    fi

    # Now that we have the App ID, try to find the executable path in shortcuts.vdf
    verbose_log "Attempting to find executable path for App ID: $APPID"
    local steam_userdata_paths=(
        "$HOME/.steam/steam/userdata"
        "$HOME/.local/share/Steam/userdata"
        "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/userdata"
    )
    local wabbajack_entries=()
    for path in "${steam_userdata_paths[@]}"; do
        if [[ -d "$path" ]]; then
            verbose_log "Checking directory: $path"
            local vdf_files=$(find "$path" -name "shortcuts.vdf" 2>/dev/null)
            for vdf_file in $vdf_files; do
                if [[ "$vdf_file" == *"12345678"* ]]; then
                    verbose_log "Skipping test directory shortcuts.vdf: $vdf_file"
                    continue
                fi
                verbose_log "Checking shortcuts.vdf: $vdf_file"
                while IFS= read -r line; do
                    if [[ "$line" == */Wabbajack.exe* ]]; then
                        local path=$(echo "$line" | sed -E 's/.*"([^"*Wabbajack\\.exe[^"]*)".*$/\1/')
                        if [[ -n "$path" ]]; then
                            if [[ "$path" != *".wabbajack_test"* ]]; then
                                verbose_log "Found Wabbajack.exe path: $path"
                                wabbajack_entries+=("$path")
                            else
                                verbose_log "Skipping test directory entry: $path"
                            fi
                        fi
                    fi
                done < <(strings "$vdf_file" | grep -i "/Wabbajack.exe")
            done
        fi
    done
    readarray -t unique_entries < <(printf '%s\n' "${wabbajack_entries[@]}" | sort -u)
    wabbajack_entries=("${unique_entries[@]}")
    local entry_count=${#wabbajack_entries[@]}
    verbose_log "Found $entry_count unique Wabbajack.exe entries"
    if [[ "$entry_count" -eq 0 ]]; then
        error_exit "No Wabbajack.exe entries found in shortcuts.vdf. Please ensure you've added Wabbajack.exe as a non-Steam game and run it once via Steam."
    elif [[ "$entry_count" -gt 1 ]]; then
        echo ""
        display "Multiple Wabbajack.exe paths found, please select which one you wish to configure:" "$RED"
        local i=1
        for path in "${wabbajack_entries[@]}"; do
            echo "$i) $path"
            ((i++))
        done
        local selected_entry=""
        while [[ ! "$selected_entry" =~ ^[0-9]+$ || "$selected_entry" -lt 1 || "$selected_entry" -gt "$entry_count" ]]; do
            read -p "Enter the number of the desired entry (1-$entry_count): " selected_entry
            if [[ ! "$selected_entry" =~ ^[0-9]+$ || "$selected_entry" -lt 1 || "$selected_entry" -gt "$entry_count" ]]; then
                display "Invalid selection. Please enter a number between 1 and $entry_count" "$RED"
            fi
        done
        wabbajack_path="${wabbajack_entries[$((selected_entry - 1))]}"
        log "Selected Wabbajack path: $wabbajack_path"
        echo ""
    else
        wabbajack_path="${wabbajack_entries[0]}"
        log "Single Wabbajack path found: $wabbajack_path"
    fi
    if [[ -n "$wabbajack_path" ]]; then
        log "Using Wabbajack path: $wabbajack_path"
        APPLICATION_DIRECTORY=$(dirname "$wabbajack_path")
        log "Application Directory: $APPLICATION_DIRECTORY"
        return 0
    else
        error_exit "Failed to determine Wabbajack path"
    fi
}

detect_compatdata_path() {
    set_current_task "Detecting compatdata path"
    # Check common Steam library locations first
    local steam_paths=(
        "$HOME/.local/share/Steam/steamapps/compatdata"
        "$HOME/.steam/steam/steamapps/compatdata"
        "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata"
    )
    
    for path in "${steam_paths[@]}"; do
        if [[ -d "$path/$APPID" ]]; then
            COMPAT_DATA_PATH="$path/$APPID"
            log "compatdata Path detected: $COMPAT_DATA_PATH"
            return 0
        fi
    done
    
    # If not found in common locations, use find command with specific paths
    local found=0
    for base_path in "${steam_paths[@]}"; do
        if [[ -d "$base_path" ]]; then
            if [[ -d "$base_path/$APPID" ]]; then
                COMPAT_DATA_PATH="$base_path/$APPID"
                log "compatdata Path detected: $COMPAT_DATA_PATH"
                found=1
                break
            fi
        fi
    done
    
    if [[ $found -eq 0 ]]; then
        error_exit "Directory named '$APPID' not found in any compatdata directories. Please ensure you have started the Steam entry for Wabbajack at least once."
    fi
}

set_protontricks_perms() {
    set_current_task "Setting Protontricks permissions"
    if [ "$WHICH_PROTONTRICKS" = "flatpak" ]; then
        # Only log to file, don't display to user
        log "Setting Protontricks permissions..."
        
        # Set flatpak permission override
        flatpak override --user com.github.Matoking.protontricks --filesystem="$APPLICATION_DIRECTORY"
        
        if [[ "$STEAMDECK" = 1 ]]; then
            log "Checking for SDCard and setting permissions appropriately..."
            # Set protontricks SDCard permissions early to suppress warning
            sdcard_path=$(df -h | grep "/run/media" | awk '{print $NF}')
            log "SD Card path: $sdcard_path"
            if [[ -n "$sdcard_path" ]]; then
                flatpak override --user --filesystem="$sdcard_path" com.github.Matoking.protontricks
                log "SD Card permission set"
            fi
        fi
    else
        log "Using Native protontricks, skip setting permissions"
    fi
}

webview_installer() {
    set_current_task "Downloading WebView installer"
    log "Setting up WebView..."
    local installer_path="$APPLICATION_DIRECTORY/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
    # Download if not present
    if [ ! -f "$installer_path" ]; then
        download_file "$WEBVIEW_INSTALLER_URL" "$installer_path" "WebView Installer"
    else
        log "WebView Installer already exists, skipping download"
    fi
    # Always run the installer in the correct prefix using run_protontricks, suppressing all output
    set_current_task "Installing WebView runtime (this may take a while)..."
    log "Installing WebView..."
    if ! run_protontricks -c "wine \"$installer_path\" /silent /install" "$APPID" >/dev/null 2>&1; then
        error_exit "Failed to install WebView"
    fi
}

detect_link_steam_library() {
    local steam_library_paths=()
    local libraryfolders_vdf=""
    
    # Only log to file, don't display to user
    log "Discovering Steam libraries..."
    
    # Find libraryfolders.vdf and extract library paths
    local vdf_paths=(
        "$HOME/.steam/steam/steamapps/libraryfolders.vdf"
        "$HOME/.local/share/Steam/steamapps/libraryfolders.vdf"
        "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf"
    )
    
    for vdf_path in "${vdf_paths[@]}"; do
        if [[ -f "$vdf_path" ]]; then
            if [[ ! -r "$vdf_path" ]]; then
                log "Found libraryfolders.vdf at $vdf_path but it's not readable"
                continue
            fi
            libraryfolders_vdf="$vdf_path"
            log "Found readable libraryfolders.vdf at $vdf_path"
            break
        fi
    done
    
    if [[ -z "$libraryfolders_vdf" ]]; then
        display "Steam libraryfolders.vdf not found. Manual input required." "$RED"
        read -e -p "Enter the path to your main Steam directory: " steam_library_path
        
        while true; do
            if [[ ! -d "$steam_library_path" ]]; then
                display "Invalid path. Please enter a valid directory." "$RED"
            elif [[ ! -f "$steam_library_path/steamapps/libraryfolders.vdf" ]]; then
                display "The specified path does not appear to be a Steam directory. Do not enter a secondary Steam Library path, only the main Steam install path." "$RED"
            elif [[ ! -r "$steam_library_path/steamapps/libraryfolders.vdf" ]]; then
                display "The libraryfolders.vdf file exists but is not readable. Please check permissions." "$RED"
            else
                read -p "Confirm using '$steam_library_path' as the Steam directory path? (y/n): " -r choice
                if [[ "$choice" =~ ^[Yy]$ ]]; then
                    libraryfolders_vdf="$steam_library_path/steamapps/libraryfolders.vdf"
                    CHOSEN_LIBRARY="$steam_library_path"
                    break
                fi
            fi
            read -e -p "Enter the path to your Steam library: " steam_library_path
        done
    fi
    
    if [[ -n "$libraryfolders_vdf" ]]; then
        # Parse libraryfolders.vdf
        while IFS= read -r line; do
            if [[ "$line" =~ \"path\" ]]; then
                local path=$(echo "$line" | sed 's/.*"\(.*\)".*/\1/')
                if [[ -d "$path" && -r "$path" ]]; then
                    steam_library_paths+=("$path")
                    log "Found valid Steam library at: $path"
                else
                    log "Found Steam library path but it's not accessible: $path"
                fi
            fi
        done < <(grep "\"path\"" "$libraryfolders_vdf")
        
        if [[ ${#steam_library_paths[@]} -gt 0 ]]; then
            # Use the first library path found as the chosen library
            CHOSEN_LIBRARY="${steam_library_paths[0]}"
            log "Selected Steam library: $CHOSEN_LIBRARY"
        else
            error_exit "No accessible Steam library paths found in libraryfolders.vdf"
        fi
    else
        error_exit "Steam library not found"
    fi
}

configure_steam_libraries() {
    set_current_task "Configuring Steam libraries"
    # Only log to file, don't display to user
    log "Configuring Steam libraries..."
    
    # Make directories
    local steam_config_directory="$CHOSEN_LIBRARY/steamapps/compatdata/$APPID/pfx/drive_c/Program Files (x86)/Steam/config"
    log "Creating directory $steam_config_directory"
    
    mkdir -p "$steam_config_directory" || error_exit "Failed to create directory $steam_config_directory"
    
    # Copy or symlink libraryfolders.vdf to config directory
    if [[ "$CHOSEN_LIBRARY" == "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" ]]; then
        STEAM_IS_FLATPAK=1
        # For Flatpak Steam, adjust the paths accordingly
        log "Symlinking libraryfolders.vdf to config directory for Flatpak Steam"
        ln -sf "$CHOSEN_LIBRARY/config/libraryfolders.vdf" "$steam_config_directory/libraryfolders.vdf" || 
            log "Failed to symlink libraryfolders.vdf (Flatpak Steam)"
    else
        log "Symlinking libraryfolders.vdf to config directory"
        ln -sf "$CHOSEN_LIBRARY/config/libraryfolders.vdf" "$steam_config_directory/libraryfolders.vdf" || 
            log "Failed to symlink libraryfolders.vdf"
    fi
    
    # Backup existing libraryfolders.vdf if it exists
    local pfx_libraryfolders="$CHOSEN_LIBRARY/steamapps/compatdata/$APPID/pfx/drive_c/Program Files (x86)/Steam/steamapps/libraryfolders.vdf"
    if [[ -f "$pfx_libraryfolders" ]]; then
        mv "$pfx_libraryfolders" "${pfx_libraryfolders}.bak" || log "Failed to backup libraryfolders.vdf"
    fi
}

create_dotnet_cache_dir() {
    set_current_task "Setting up .NET cache directory"
    # Only log to file, don't display to user
    log "Setting up .NET cache directory..."
    
    local user_name=$(whoami)
    local cache_dir="$APPLICATION_DIRECTORY/home/$user_name/.cache/dotnet_bundle_extract"
    
    # Check if the directory already exists
    if [ -d "$cache_dir" ]; then
        log "Directory already exists: $cache_dir, skipping..."
        return 0
    fi
    
    # Create the directory
    mkdir -p "$cache_dir" || error_exit "Failed to create directory: $cache_dir"
    log "Directory successfully created: $cache_dir"
}

cleanup_wine_procs() {
    # Only log to file, don't display to user
    log "Cleaning up any hanging Wine processes..."
    
    # Find and kill processes
    local processes=$(pgrep -f "WabbajackProton.exe|renderer=vulkan|win7|win10|ShowDotFiles|MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe")
    if [[ -n "$processes" ]]; then
        echo "$processes" | xargs -r kill -9
        log "Processes killed successfully"
    else
        log "No matching wine processes found"
    fi
}

# Show detection summary and ask for confirmation
show_detection_summary() {
    echo ""
    echo "───────────────────────────────────────────────────────────────────"
    echo -e "\e[1mDetection Summary:\e[0m" | tee -a "$LOGFILE"
    echo -e "===================" | tee -a "$LOGFILE"
    echo -e "Wabbajack Path: \e[32m$APPLICATION_DIRECTORY\e[0m" | tee -a "$LOGFILE"
    echo -e "Steam App ID: \e[32m$APPID\e[0m" | tee -a "$LOGFILE"
    echo -e "Compatdata Path: \e[32m$COMPAT_DATA_PATH\e[0m" | tee -a "$LOGFILE"
    echo -e "Steam Library: \e[32m$CHOSEN_LIBRARY\e[0m" | tee -a "$LOGFILE"
    echo -e "Protontricks: \e[32m$WHICH_PROTONTRICKS\e[0m" | tee -a "$LOGFILE"
    
    # Show Steam Deck status if detected
    if [[ $STEAMDECK -eq 1 ]]; then
        echo -e "Running on: \e[32mSteam Deck\e[0m" | tee -a "$LOGFILE"
    fi
    
    # Show SD Card status if detected
    if [[ "$CHOSEN_LIBRARY" == "/run/media"* ]] || [[ "$APPLICATION_DIRECTORY" == "/run/media"* ]]; then
        echo -e "SD Card: \e[32mDetected\e[0m" | tee -a "$LOGFILE"
    fi
    echo "───────────────────────────────────────────────────────────────────"
    
    # Show confirmation with retry loop
    while true; do
        read -rp $'\e[32mDo you want to proceed with the installation? (y/N)\e[0m ' proceed
        
        if [[ $proceed =~ ^[Yy]$ ]]; then
            break
        elif [[ $proceed =~ ^[Nn]$ ]] || [[ -z $proceed ]]; then
            log "Installation cancelled by user"
            display "Installation cancelled." "$YELLOW"
            cleanup_wine_procs
            exit 0
        fi
        
        display "Please enter 'y' for yes or 'n' for no." "$YELLOW"
    done
    
    # Add padding after user confirmation
    echo ""
}

# --- Discovery Phase ---
discovery_phase() {
    # All detection, user input, and variable gathering
    display_banner
    log_section "Initial Setup"
    cleanup_wine_procs
    CURRENT_TASK_NUM=0
    IN_MODIFICATION_PHASE=0
    log_section "Environment Detection"
    detect_steamdeck
    detect_protontricks
    setup_protontricks_alias
    check_protontricks_version
    log_section "Path Detection"
    get_wabbajack_path
    detect_compatdata_path
    detect_link_steam_library
    show_detection_summary
}

# --- Configuration Phase ---
configuration_phase() {
    # All actions that change the system, using only variables set above
    IN_MODIFICATION_PHASE=1
    CURRENT_TASK_NUM=0
    log_section "Environment Configuration"
    set_protontricks_perms
    set_current_task "Applying initial system.reg (phase 1)"
    download_file "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/main/files/system.reg.wj.win7" "$COMPAT_DATA_PATH/pfx/system.reg" "Phase 1 system.reg"
    webview_installer
    set_current_task "Applying final system.reg and user.reg"
    download_file "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/main/files/system.reg.wj" "$COMPAT_DATA_PATH/pfx/system.reg" "Final system.reg"
    download_file "https://raw.githubusercontent.com/Omni-guides/Wabbajack-Modlist-Linux/main/files/user.reg.wj" "$COMPAT_DATA_PATH/pfx/user.reg" "Final user.reg"
    configure_steam_libraries
    create_dotnet_cache_dir
    log_section "Final Cleanup"
    cleanup_wine_procs
    set_current_task "Complete"
    echo -e "\n"
    echo "───────────────────────────────────────────────────────────────────"
    log_section "Setup Complete"
    display "✓ Installation completed successfully!" "$GREEN"
    echo -e "\n📝 Next Steps:"
    echo "  • Launch Wabbajack through Steam"
    echo "  • When Wabbajack opens, verify you can log in to Nexus from the Settings option"
    echo "  • Begin downloading and installing your modlist"
    echo -e "\n💡 If you encounter any issues:"
    echo "  • Check the log file at: $LOGFILE"
    echo "  • Join the #unofficial-linux-support channel on the Wabbajack Discord"
    echo "  • Ensure you've followed all modlist-specific requirements"
    echo "───────────────────────────────────────────────────────────────────"
    echo -e "\n"
    if [[ $STEAM_IS_FLATPAK -eq 1 ]]; then
        display "Flatpak Steam is in use. You may need to add a permissions override so that Wabbajack can access the directories." "$YELLOW"
        display "For example, if you wanted to install a modlist to /home/user/Games/Skyrim/Modlistname, you would need to run:" "$YELLOW"
        display "flatpak override --user com.valvesoftware.Steam --filesystem=\"/home/user/Games\"" "$YELLOW"
    fi
    echo -e "\n${YELLOW}⚠️  IMPORTANT: For best compatibility, add the following line to the Launch Options of your Wabbajack Steam entry:${RESET}"
    echo -e "\n${GREEN}PROTON_USE_WINED3D=1 %command%${RESET}\n"
    echo -e "This can help resolve certain graphics issues with Wabbajack running under Proton."
    exit 0
}

# --- Main Execution ---
main() {
    log_section "Script version $SCRIPT_VERSION started at: $(date +'%Y-%m-%d %H:%M:%S')"
    if [[ $VERBOSE -eq 1 ]]; then
        display "Verbose mode enabled" "$YELLOW"
    fi
    # Discovery Phase
    discovery_phase
    # Configuration Phase
    configuration_phase
}

# Run the main function
main 
