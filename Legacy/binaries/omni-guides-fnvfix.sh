#!/usr/bin/env bash
#
###################################################
#                                                 #
# A tool for running Wabbajack modlists on Linux  #
#                                                 #
#          Beta v0.69t - Omni 03/18/2025           #
#                                                 #
###################################################

# Full Changelog can be found here: https://github.com/Omni-guides/Wabbajack-Modlist-Linux/blob/main/binaries/omni-guides-sh.changelog.txt


# Current Script Version (beta)
script_ver=0.69t

# Define modlist-specific configurations
declare -A modlist_configs=(
    ["wildlander"]="dotnet472"
    ["librum|apostasy"]="dotnet40 dotnet8"
    ["nordicsouls"]="dotnet40"
    ["livingskyrim|lsiv|ls4"]="dotnet40"
    ["lostlegacy"]="dotnet48"
)

# Set up and blank logs (simplified)
LOGFILE=$HOME/omni-guides-sh.log
echo "" >$HOME/omni-guides-sh.log

# Add our new logging function
log_status() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Always write to log file with timestamp but without color codes
    echo "[$timestamp] [$level] $(echo "$message" | sed 's/\x1b\[[0-9;]*m//g')" >> "$LOGFILE"
    
    # Only display non-DEBUG messages to the user, preserving color codes
    if [ "$level" != "DEBUG" ]; then
        echo -e "$message"
    fi
}

#set -x
#Protontricks Bug
#export PROTON_VERSION="Proton Experimental"

# Display banner
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                      Omni-Guides (beta)                          ║" 
echo "║                                                                  ║"
echo "║        A tool for running Wabbajack modlists on Linux            ║"
echo "╚══════════════════════════════════════════════════════════════════╝"

#########
# Intro #
#########
echo ""
log_status "INFO" "Omni-Guides Wabbajack Post-Install Script v$script_ver"
echo "───────────────────────────────────────────────────────────────────"
log_status "INFO" "This script automates the post-install steps for Wabbajack modlists on Linux/Steam Deck."
log_status "INFO" "It will configure your modlist location, install required components, and apply necessary fixes."
echo ""
log_status "WARN" "⚠ IMPORTANT: Use this script at your own risk."
log_status "INFO" "Please report any issues via GitHub (Omni-guides/Wabbajack-Modlist-Linux)."
echo "───────────────────────────────────────────────────────────────────"
echo -e "\e[33mPress any key to continue...\e[0m"
read -n 1 -s -r -p ""

#############
# Functions #
#############

##########################
# Cleanup Wine Processes #
##########################

cleanup_wine_procs() {

	# Find and kill processes containing various process names
	processes=$(pgrep -f "win7|win10|ShowDotFiles|protontricks")
	if [[ -n "$processes" ]]; then
		echo "$processes" | xargs kill -9
		echo "Processes killed successfully." >>$LOGFILE 2>&1
	else
		echo "No matching processes found." >>$LOGFILE 2>&1
	fi

	pkill -9 winetricks

}

#############
# Set APPID #
#############

set_appid() {

	echo "DEBUG: Extracting APPID from choice: '$choice'" >>$LOGFILE 2>&1
	APPID=$(echo "$choice" | awk -F'[()]' '{print $2}')
	echo "DEBUG: Extracted APPID: '$APPID'" >>$LOGFILE 2>&1

	#APPID=$(echo $choice | awk {'print $NF'} | sed 's:^.\(.*\).$:\1:')
	echo "APPID=$APPID" >>$LOGFILE 2>&1

	if [ -z "$APPID" ]; then
		echo "Error: APPID cannot be empty, exiting... Please tell Omni :("
		cleaner_exit
	fi

}

#############################
# Detect if running on deck #
#############################

detect_steamdeck() {
	# Steamdeck or nah?

	if [ -f "/etc/os-release" ] && grep -q "steamdeck" "/etc/os-release"; then
		steamdeck=1
		echo "Running on Steam Deck" >>$LOGFILE 2>&1
	else
		steamdeck=0
		echo "NOT A steamdeck" >>$LOGFILE 2>&1
	fi

}

###########################################
# Detect Protontricks (flatpak or native) #
###########################################

detect_protontricks() {
	echo -ne "\nDetecting if protontricks is installed..." >>$LOGFILE 2>&1

    # Check if native protontricks exists
	if command -v protontricks >/dev/null 2>&1; then
		protontricks_path=$(command -v protontricks)
		# Check if the detected binary is actually a Flatpak wrapper
		if [[ -f "$protontricks_path" ]] && grep -q "flatpak run" "$protontricks_path"; then
			echo -e "Detected Protontricks is actually a Flatpak wrapper at $protontricks_path." >>$LOGFILE 2>&1
			which_protontricks=flatpak
		else
			echo -e "Native Protontricks found at $protontricks_path." | tee -a $LOGFILE
			which_protontricks=native
			return 0 # Exit function since we confirmed native protontricks
		fi
    fi

    # If not found, check for Flatpak protontricks
		if flatpak list | grep -iq protontricks; then
			echo -e "Flatpak Protontricks is already installed." >>$LOGFILE 2>&1
			which_protontricks=flatpak
        return 0
    fi

    # If neither found, offer to install Flatpak
			echo -e "\e[31m\n** Protontricks not found. Do you wish to install it? (y/n): **\e[0m"
			read -p " " answer
			if [[ $answer =~ ^[Yy]$ ]]; then
				if [[ $steamdeck -eq 1 ]]; then
					if flatpak install -u -y --noninteractive flathub com.github.Matoking.protontricks; then
						which_protontricks=flatpak
                return 0
					else
						echo -e "\n\e[31mFailed to install Protontricks via Flatpak. Please install it manually and rerun this script.\e[0m" | tee -a $LOGFILE
						exit 1
					fi
				else
					read -p "Choose installation method: 1) Flatpak (preferred) 2) Native: " choice
					if [[ $choice =~ 1 ]]; then
						if flatpak install -u -y --noninteractive flathub com.github.Matoking.protontricks; then
							which_protontricks=flatpak
                    return 0
						else
							echo -e "\n\e[31mFailed to install Protontricks via Flatpak. Please install it manually and rerun this script.\e[0m" | tee -a $LOGFILE
							exit 1
						fi
					else
						echo -e "\nSorry, there are too many distros to automate this!" | tee -a $LOGFILE
						echo -e "Please check how to install Protontricks using your OS package manager (yum, dnf, apt, pacman, etc.)" | tee -a $LOGFILE
						echo -e "\e[31mProtontricks is required for this script to function. Exiting.\e[0m" | tee -a $LOGFILE
						exit 1
					fi
				fi
			else
				echo -e "\e[31mProtontricks is required for this script to function. Exiting.\e[0m" | tee -a $LOGFILE
				exit 1
	fi
}

#############################
# Run protontricks commands #
#############################

run_protontricks() {
    # Determine the protontricks binary path and create command array
    if [ "$which_protontricks" = "flatpak" ]; then
        local cmd=(flatpak run com.github.Matoking.protontricks)
    else
        local cmd=(protontricks)
    fi

    # Execute the command with all arguments
    "${cmd[@]}" "$@"
}

###############################
# Detect Protontricks Version #
###############################

protontricks_version() {
    # Get the current version of protontricks
    protontricks_version=$(run_protontricks -V | cut -d ' ' -f 2 | sed 's/[()]//g')

    # Remove any non-numeric characters from the version number
    protontricks_version_cleaned=$(echo "$protontricks_version" | sed 's/[^0-9.]//g')

    echo "Protontricks Version Cleaned = $protontricks_version_cleaned" >> "$LOGFILE" 2>&1

    # Split the version into digits
    IFS='.' read -r first_digit second_digit third_digit <<< "$protontricks_version_cleaned"

    # Check if the second digit is defined and greater than or equal to 12
    if [[ -n "$second_digit" && "$second_digit" -lt 12 ]]; then
        echo "Your protontricks version is too old! Update to version 1.12 or newer and rerun this script. If 'flatpak run com.github.Matoking.protontricks -V' returns 'unknown', then please update via flatpak." | tee -a "$LOGFILE"
        cleaner_exit
    fi
}

#######################################
# Detect Skyrim or Fallout 4 Function #
#######################################

detect_game() {
    # Define lookup table for games
    declare -A game_lookup=(
        ["Skyrim"]="Skyrim Special Edition"
        ["Fallout 4"]="Fallout 4"
        ["Fallout New Vegas"]="Fallout New Vegas"
        ["FNV"]="Fallout New Vegas"
        ["Oblivion"]="Oblivion"
    )

    # Try direct match first
    for pattern in "${!game_lookup[@]}"; do
        if [[ $choice == *"$pattern"* ]]; then
            gamevar="${game_lookup[$pattern]}"
            which_game="${gamevar%% *}"
            echo "Game variable set to $which_game." >>"$LOGFILE" 2>&1
            echo "Game variable: $gamevar" >>"$LOGFILE" 2>&1
            return 0
        fi
    done

    # Handle generic "Fallout" case
    if [[ $choice == *"Fallout"* ]]; then
        PS3="Please select a Fallout game (enter the number): "
        select fallout_opt in "Fallout 4" "Fallout New Vegas"; do
            if [[ -n $fallout_opt ]]; then
                gamevar="$fallout_opt"
                which_game="${gamevar%% *}"
                echo "Game variable set to $which_game." >>"$LOGFILE" 2>&1
                echo "Game variable: $gamevar" >>"$LOGFILE" 2>&1
                return 0
            else
                echo "Invalid option"
            fi
        done
    fi

    # If no match found, show selection menu
    PS3="Please select a game (enter the number): "
    select opt in "Skyrim" "Fallout 4" "Fallout New Vegas" "Oblivion"; do
        if [[ -n $opt ]]; then
            gamevar="${game_lookup[$opt]}"
            which_game="${gamevar%% *}"
            echo "Game variable set to $which_game." >>"$LOGFILE" 2>&1
            echo "Game variable: $gamevar" >>"$LOGFILE" 2>&1
            return 0
        else
            echo "Invalid option"
        fi
    done
}

###################################
# Try to detect the Steam Library #
###################################

detect_steam_library() {

	local libraryfolders_vdf="$HOME/.steam/steam/config/libraryfolders.vdf"

	if [[ ! -f "$libraryfolders_vdf" ]]; then
		echo "libraryfolders.vdf not found in ~/.steam/steam/config/. Please ensure Steam is installed." | tee -a "$LOGFILE"
		return 1
	fi

	local library_paths=()
	while IFS='' read -r line; do
		if [[ "$line" =~ \"path\" ]]; then
			local path=$(echo "$line" | sed 's/.*"path"\s*"\(.*\)"/\1/')
			if [[ -n "$path" ]]; then
				library_paths+=("$path/steamapps/common")
			fi
		fi
	done <"$libraryfolders_vdf"

	local found=0
	for library_path in "${library_paths[@]}"; do
		if [[ -d "$library_path/$gamevar" ]]; then
			steam_library="$library_path"
			found=1
			echo "Found '$gamevar' in $steam_library." >>$LOGFILE 2>&1
			break
		else
			echo "Checking $library_path: '$gamevar' not found." >>$LOGFILE 2>&1
		fi
	done

	if [[ "$found" -eq 0 ]]; then
		echo "Vanilla game not found in Steam library locations." | tee -a "$LOGFILE"

		while true; do
			echo -e "\n** Enter the path to your Vanilla $gamevar directory manually (e.g. /data/SteamLibrary/steamapps/common/$gamevar): **"
			read -e -r gamevar_input

			steam_library_input="${gamevar_input%/*}/"

			if [[ -d "$steam_library_input/$gamevar" ]]; then
				steam_library="$steam_library_input"
				echo "Found $gamevar in $steam_library_input." | tee -a "$LOGFILE"
				echo "Steam Library set to: $steam_library" >>$LOGFILE 2>&1
				break
			else
				echo "Game not found in $steam_library_input. Please enter a valid path to Vanilla $gamevar." | tee -a "$LOGFILE"
			fi
		done
	fi

	echo "Steam Library Location: $steam_library" >>$LOGFILE 2>&1

	if [[ "$steamdeck" -eq 1 && "$steam_library" == "/run/media"* ]]; then
		basegame_sdcard=1
	fi

}

#################################
# Detect Modlist Directory Path #
#################################

detect_modlist_dir_path() {
    log_status "DEBUG" "Detecting $MODLIST Install Directory..."
    local modlist_paths=()
    local choice modlist_ini_temp
    local pattern=$(echo "$MODLIST" | sed 's/ /.*\|/g')

    # Search for ModOrganizer.exe entries matching the modlist pattern
    while IFS= read -r entry; do
        modlist_paths+=("$(dirname "${entry//[\"\']/}")")
    done < <(strings ~/.steam/steam/userdata/*/config/shortcuts.vdf | grep -iE "ModOrganizer.exe" | grep -iE "$pattern")

    # If no exact matches, get all ModOrganizer.exe instances
    if [[ ${#modlist_paths[@]} -eq 0 ]]; then
        echo "No exact matches found. Searching for all ModOrganizer.exe instances..."
        while IFS= read -r entry; do
            modlist_paths+=("$(dirname "${entry//[\"\']/}")")
        done < <(strings ~/.steam/steam/userdata/*/config/shortcuts.vdf | grep -iE "ModOrganizer.exe")
    fi

    # Handle different cases based on number of paths found
    if [[ ${#modlist_paths[@]} -eq 0 ]]; then
        # No paths found - must enter manually
        echo -e "\e[34mNo ModOrganizer.exe entries found. Please enter the directory manually:\e[0m"
        read -r -e modlist_dir
    elif [[ ${#modlist_paths[@]} -eq 1 ]]; then
        # Single path found - use it directly without output
        modlist_dir="${modlist_paths[0]}"
    else
        # Multiple paths found - show selection menu
        echo "Select the ModOrganizer directory:"
        for i in "${!modlist_paths[@]}"; do
            echo -e "\e[33m$((i + 1))) ${modlist_paths[i]}\e[0m"
        done
        echo -e "\e[34m$(( ${#modlist_paths[@]} + 1 ))) Enter path manually\e[0m"

        while true; do
            read -p "Enter your choice (1-$((${#modlist_paths[@]} + 1))): " choice
            if [[ "$choice" =~ ^[0-9]+$ && "$choice" -ge 1 && "$choice" -le $(( ${#modlist_paths[@]} + 1 )) ]]; then
                if [[ "$choice" -eq $(( ${#modlist_paths[@]} + 1 )) ]]; then
                    echo -ne "\e[34mEnter the ModOrganizer directory path: \e[0m"
                    read -r -e modlist_dir
                else
                    modlist_dir="${modlist_paths[choice - 1]}"
                fi
                break
            else
                echo "Invalid selection. Please try again."
            fi
        done
    fi

    # Validate selection
    modlist_ini_temp="$modlist_dir/ModOrganizer.ini"
    while [[ ! -f "$modlist_ini_temp" ]]; do
        echo "ModOrganizer.ini not found in $modlist_dir. Please enter a valid path."
        echo -ne "\e[34mEnter the ModOrganizer directory path: \e[0m"
        read -r -e modlist_dir
        modlist_ini_temp="$modlist_dir/ModOrganizer.ini"
    done

    # Save and log results
    modlist_ini="$modlist_ini_temp"
    echo "Modlist directory: $modlist_dir" >> "$LOGFILE"
    echo "Modlist INI location: $modlist_ini" >> "$LOGFILE"
}

#####################################################
# Set protontricks permissions on Modlist Directory #
#####################################################

set_protontricks_perms() {
    if [ "$which_protontricks" = "flatpak" ]; then
        log_status "INFO" "\nSetting Protontricks permissions..."
        flatpak override --user com.github.Matoking.protontricks --filesystem="$modlist_dir"
        log_status "SUCCESS" "Done!"
        
        if [[ $steamdeck = 1 ]]; then
            log_status "WARN" "\nChecking for SDCard and setting permissions appropriately.."
            sdcard_path=$(df -h | grep "/run/media" | awk {'print $NF'})
            echo "$sdcard_path" >>$LOGFILE 2>&1
            flatpak override --user --filesystem=$sdcard_path com.github.Matoking.protontricks
            flatpak override --user --filesystem=/run/media/mmcblk0p1 com.github.Matoking.protontricks
            log_status "SUCCESS" "Done."
        fi
    else
        log_status "DEBUG" "Using Native protontricks, skip setting permissions"
    fi
}

#####################################
# Enable Visibility of (.)dot files #
#####################################

enable_dotfiles() {
    log_status "DEBUG" "APPID=$APPID"
    log_status "INFO" "\nEnabling visibility of (.)dot files..."

    # Completely redirect all output to avoid any wine debug messages
    dotfiles_check=$(WINEDEBUG=-all run_protontricks -c 'wine reg query "HKEY_CURRENT_USER\Software\Wine" /v ShowDotFiles' $APPID > /dev/null 2>&1; 
                     WINEDEBUG=-all run_protontricks -c 'wine reg query "HKEY_CURRENT_USER\Software\Wine" /v ShowDotFiles' $APPID 2>/dev/null | grep ShowDotFiles | awk '{gsub(/\r/,""); print $NF}')
    
    log_status "DEBUG" "Current dotfiles setting: $dotfiles_check"

    if [[ "$dotfiles_check" = "Y" ]]; then
        log_status "INFO" "DotFiles already enabled via registry... skipping"
    else
        # Method 2: Set registry key (standard approach)
        log_status "DEBUG" "Setting ShowDotFiles registry key..."
        WINEDEBUG=-all run_protontricks -c 'wine reg add "HKEY_CURRENT_USER\Software\Wine" /v ShowDotFiles /d Y /f' $APPID > /dev/null 2>&1
        
        # Method 3: Also try direct winecfg approach as backup
        log_status "DEBUG" "Also setting via winecfg command..."
        WINEDEBUG=-all run_protontricks -c 'winecfg /v wine' $APPID > /dev/null 2>&1
        
        # Method 4: Create user.reg entry if it doesn't exist
        log_status "DEBUG" "Ensuring user.reg has correct entry..."
        prefix_path=$(WINEDEBUG=-all run_protontricks -c 'echo $WINEPREFIX' $APPID 2>/dev/null)
        if [[ -n "$prefix_path" && -d "$prefix_path" ]]; then
            if [[ -f "$prefix_path/user.reg" ]]; then
                if ! grep -q "ShowDotFiles" "$prefix_path/user.reg" 2>/dev/null; then
                    echo '[Software\\Wine] 1603891765' >> "$prefix_path/user.reg" 2>/dev/null
                    echo '"ShowDotFiles"="Y"' >> "$prefix_path/user.reg" 2>/dev/null
                fi
            fi
        fi
        
        # Verify the setting took effect
        dotfiles_verify=$(WINEDEBUG=-all run_protontricks -c 'wine reg query "HKEY_CURRENT_USER\Software\Wine" /v ShowDotFiles' $APPID > /dev/null 2>&1;
                          WINEDEBUG=-all run_protontricks -c 'wine reg query "HKEY_CURRENT_USER\Software\Wine" /v ShowDotFiles' $APPID 2>/dev/null | grep ShowDotFiles | awk '{gsub(/\r/,""); print $NF}')
        log_status "DEBUG" "Verification check: $dotfiles_verify"
        
        log_status "SUCCESS" "Done!"
    fi
}

###############################################
# Set Windows 10 version in the proton prefix #
###############################################

set_win10_prefix() {
	WINEDEBUG=-all run_protontricks --no-bwrap $APPID win10 >/dev/null 2>&1
}

######################################
# Install Wine Components & VCRedist #
######################################

install_wine_components() {
    log_status "INFO" "Installing Wine Components... This can take some time, be patient!"
    
    # Define game-specific component sets
    local protontricks_appid="$APPID"
    local protontricks_components=()
    
    # Common components for all games
    local common_components=("fontsmooth=rgb" "xact" "xact_x64" "vcrun2022")
    
    # Game-specific configuration
    case "$gamevar" in
        "Skyrim Special Edition"|"Fallout 4")
            protontricks_components=("${common_components[@]}" "d3dcompiler_47" "d3dx11_43" "d3dcompiler_43" "dotnet6" "dotnet7")
            ;;
        "Fallout New Vegas")
            protontricks_components=("${common_components[@]}" "d3dx9_43" "d3dx9")
            protontricks_appid="22380" # Force appid for FNV
            ;;
        "Oblivion")
            protontricks_components=("${common_components[@]}" "d3dx9_43" "d3dx9")
            ;;
        *)
            echo "Unsupported game: $gamevar" | tee -a "$LOGFILE"
            return 1
            ;;
    esac

    # Log the command we're about to run
    echo "Installing components: ${protontricks_components[*]}" >>$LOGFILE 2>&1
    
    # Run the installation with progress indicator
    printf "Protontricks running... "
    
    # Try up to 3 times to install components
    local max_attempts=3
    local attempt=1
    local success=false
    
    while [[ $attempt -le $max_attempts && $success == false ]]; do
        if [[ $attempt -gt 1 ]]; then
            echo "Retry attempt $attempt/$max_attempts..." | tee -a "$LOGFILE"
            sleep 2
        fi
        
        if WINEDEBUG=-all run_protontricks --no-bwrap "$protontricks_appid" -q "${protontricks_components[@]}" >/dev/null 2>&1; then
            success=true
        else
            echo "Attempt $attempt failed, cleaning up wine processes before retry..." >>$LOGFILE 2>&1
            cleanup_wine_procs
            attempt=$((attempt+1))
        fi
    done
    
    if [[ $success == true ]]; then
        printf "Done.\n"
        log_status "SUCCESS" "Wine Component installation completed."
    else
        printf "Failed.\n"
        log_status "ERROR" "Component install failed after $max_attempts attempts."
        return 1
    fi

    # Verify installation
    log_status "DEBUG" "Verifying installed components..."
    local output
    output=$(run_protontricks --no-bwrap "$protontricks_appid" list-installed 2>/dev/null)
    
    # Clean up and deduplicate the component list
    local cleaned_output
    cleaned_output=$(echo "$output" | grep -v "Using winetricks" | sort -u | grep -v '^$')
    log_status "DEBUG" "Installed components (unique):"
    echo "$cleaned_output" >> "$LOGFILE"
    
    # Check for critical components only to avoid false negatives
    local critical_components=("vcrun2022" "xact")
    local missing_components=()
    
    for component in "${critical_components[@]}"; do
        if ! grep -q "$component" <<<"$output"; then
            missing_components+=("$component")
        fi
    done
    
    if [[ ${#missing_components[@]} -gt 0 ]]; then
        echo -e "\nWarning: Some critical components may be missing: ${missing_components[*]}" | tee -a "$LOGFILE"
        echo "Installation will continue, but you may encounter issues." | tee -a "$LOGFILE"
    else
        echo "Critical components verified successfully." >>$LOGFILE 2>&1
    fi
    
    return 0
}

############################################
# Detect default compatdata Directory Path #
############################################
default_steam_compatdata_dir() {
    # Prefer ~/.local/share/Steam if it exists
    if [[ -d "$HOME/.local/share/Steam/steamapps/compatdata" ]]; then
        echo "$HOME/.local/share/Steam/steamapps/compatdata"
    elif [[ -d "$HOME/.steam/steam/steamapps/compatdata" ]]; then
        echo "$HOME/.steam/steam/steamapps/compatdata"
    else
        # Do not create the directory; just return empty string
        echo ""
    fi
}

# Helper to get all Steam library folders from libraryfolders.vdf
get_all_steam_libraries() {
    local vdf_file="$HOME/.steam/steam/config/libraryfolders.vdf"
    local libraries=("$HOME/.local/share/Steam" "$HOME/.steam/steam")
    if [[ -f "$vdf_file" ]]; then
        while IFS='' read -r line; do
            if [[ "$line" =~ "path" ]]; then
                local path=$(echo "$line" | sed 's/.*"path"\s*"\(.*\)"/\1/')
                if [[ -n "$path" ]]; then
                    libraries+=("$path")
                fi
            fi
        done <"$vdf_file"
    fi
    echo "${libraries[@]}"
}

####################################
# Detect compatdata Directory Path #
####################################

detect_compatdata_path() {
    local appid_to_check="$APPID"
    if [[ "$gamevar" == "Fallout New Vegas" ]]; then
        appid_to_check="22380"
        local vdf_file="$HOME/.steam/steam/config/libraryfolders.vdf"
        local libraries=("$HOME/.local/share/Steam" "$HOME/.steam/steam")
        # Parse all additional libraries from the VDF
        if [[ -f "$vdf_file" ]]; then
            while IFS= read -r line; do
                if [[ "$line" =~ "path" ]]; then
                    local path=$(echo "$line" | sed -E 's/.*"path"[ \t]*"([^"]+)".*/\1/')
                    if [[ "$path" == /* ]]; then
                        libraries+=("$path")
                    else
                        libraries+=("$HOME/$path")
                    fi
                fi
            done < "$vdf_file"
        fi
        compat_data_path=""
        for lib in "${libraries[@]}"; do
            local compat_path="$lib/steamapps/compatdata/$appid_to_check"
            log_status "DEBUG" "Checking for compatdata at: $compat_path"
            if [[ -d "$compat_path" ]]; then
                compat_data_path="$compat_path"
                log_status "DEBUG" "Found FNV compatdata: $compat_data_path"
                break
            fi
        done
        if [[ -z "$compat_data_path" ]]; then
            log_status "ERROR" "Could not find compatdata directory for Fallout New Vegas (22380) in any Steam library."
            log_status "ERROR" "Please ensure you have launched the vanilla Fallout New Vegas game at least once via Steam in the correct library."
            return 1
        fi
        return 0
    fi
    # ... (existing logic for other games)
    # Check common Steam library locations first
    for path in "$HOME/.local/share/Steam/steamapps/compatdata" "$HOME/.steam/steam/steamapps/compatdata"; do
        if [[ -d "$path/$appid_to_check" ]]; then
            compat_data_path="$path/$appid_to_check"
            log_status "DEBUG" "compatdata Path detected: $compat_data_path"
            break
        fi
    done

    # If not found in common locations, use find command
    if [[ -z "$compat_data_path" ]]; then
        find / -type d -name "compatdata" 2>/dev/null | while read -r compatdata_dir; do
            if [[ -d "$compatdata_dir/$appid_to_check" ]]; then
                compat_data_path="$compatdata_dir/$appid_to_check"
                log_status "DEBUG" "compatdata Path detected: $compat_data_path"
                break
            fi
        done
    fi

    if [[ -z "$compat_data_path" ]]; then
        log_status "ERROR" "Directory named '$appid_to_check' not found in any compatdata directories."
        log_status "ERROR" "Please ensure you have started the Steam entry for the modlist at least once, even if it fails.."
    else
        log_status "DEBUG" "Found compatdata directory with '$appid_to_check': $compat_data_path"
    fi
}

#########################
# Detect Proton Version #
#########################

detect_proton_version() {
    log_status "DEBUG" "Detecting Proton version..."
    
    # Validate the compatdata path exists
    if [[ ! -d "$compat_data_path" ]]; then 
        log_status "WARN" "Compatdata directory not found at '$compat_data_path'"
        proton_ver="Unknown"
        return 1
    fi

    # First try to get Proton version from the registry
    if [[ -f "$compat_data_path/pfx/system.reg" ]]; then
        local reg_output
        reg_output=$(grep -A 3 "\"SteamClientProtonVersion\"" "$compat_data_path/pfx/system.reg" | grep "=" | cut -d= -f2 | tr -d '"' | tr -d ' ')
        
        if [[ -n "$reg_output" ]]; then
            # Keep GE versions as is, otherwise prefix with "Proton"
            if [[ "$reg_output" == *"GE"* ]]; then
                proton_ver="$reg_output"  # Keep GE versions as is
            else
                proton_ver="Proton $reg_output"
            fi
            log_status "DEBUG" "Detected Proton version from registry: $proton_ver"
            return 0
        fi
    fi

    # Fallback to config_info if registry method fails
    if [[ -f "$compat_data_path/config_info" ]]; then
        local config_ver
        config_ver=$(head -n 1 "$compat_data_path/config_info")
        if [[ -n "$config_ver" ]]; then
            # Keep GE versions as is, otherwise prefix with "Proton"
            if [[ "$config_ver" == *"GE"* ]]; then
                proton_ver="$config_ver"  # Keep GE versions as is
            else
                proton_ver="Proton $config_ver"
            fi
            log_status "DEBUG" "Detected Proton version from config_info: $proton_ver"
            return 0
        fi
    fi

    proton_ver="Unknown"
    log_status "WARN" "Could not detect Proton version"
    return 1
}

###############################
# Confirmation before running #
###############################

confirmation_before_running() {

	echo "" | tee -a $LOGFILE
	echo -e "Detail Checklist:" | tee -a $LOGFILE
	echo -e "=================" | tee -a $LOGFILE
	echo -e "Modlist: $MODLIST .....\e[32m OK.\e[0m" | tee -a $LOGFILE
	echo -e "Directory: $modlist_dir .....\e[32m OK.\e[0m" | tee -a $LOGFILE
	echo -e "Proton Version: $proton_ver .....\e[32m OK.\e[0m" | tee -a $LOGFILE
	echo -e "App ID: $APPID" | tee -a $LOGFILE

}

#################################
# chown/chmod modlist directory #
#################################

chown_chmod_modlist_dir() {
    log_status "WARN" "Changing Ownership and Permissions of modlist directory (may require sudo password)"
    
    user=$(whoami)
    group=$(id -gn)
    log_status "DEBUG" "User is $user and Group is $group"

    sudo chown -R "$user:$group" "$modlist_dir"
    sudo chmod -R 755 "$modlist_dir"
}


###############################################
# Backup ModOrganizer.ini and backup gamePath #
###############################################

backup_modorganizer() {
    log_status "DEBUG" "Backing up ModOrganizer.ini: $modlist_ini"
    cp "$modlist_ini" "$modlist_ini.$(date +"%Y%m%d_%H%M%S").bak"
    grep gamePath "$modlist_ini" | sed '/^backupPath/! s/gamePath/backupPath/' >> "$modlist_ini"
}

########################################
# Blank or set MO2 Downloads Directory #
########################################

blank_downloads_dir() {
    log_status "INFO" "\nEditing download_directory..."
    sed -i "/download_directory/c\download_directory =" "$modlist_ini"
    log_status "SUCCESS" "Done."
}

############################################
# Replace the gamePath in ModOrganizer.ini #
############################################

replace_gamepath() {
    log_status "INFO" "Setting game path in ModOrganizer.ini..."
    
    log_status "DEBUG" "Using Steam Library Path: $steam_library"
    log_status "DEBUG" "Use SDCard?: $basegame_sdcard"
    
    # Check if Modlist uses Game Root, Stock Game, etc.
    game_path_line=$(grep '^gamePath' "$modlist_ini")
    log_status "DEBUG" "Game Path Line: $game_path_line"

    if [[ "$game_path_line" == *Stock\ Game* || "$game_path_line" == *STOCK\ GAME* || "$game_path_line" == *Stock\ Game\ Folder* || "$game_path_line" == *Stock\ Folder* || "$game_path_line" == *Skyrim\ Stock* || "$game_path_line" == *Game\ Root* || $game_path_line == *root\\\\Skyrim\ Special\ Edition* ]]; then
        # Stock Game, Game Root or equivalent directory found
        log_status "INFO" "Found Game Root/Stock Game or equivalent directory, editing Game Path..."

        # Get the end of our path
        if [[ $game_path_line =~ Stock\ Game\ Folder ]]; then
            modlist_gamedir="$modlist_dir/Stock Game Folder"
            log_status "DEBUG" "Modlist Gamedir: $modlist_gamedir"
        elif [[ $game_path_line =~ Stock\ Folder ]]; then
            modlist_gamedir="$modlist_dir/Stock Folder"
        elif [[ $game_path_line =~ Skyrim\ Stock ]]; then
            modlist_gamedir="$modlist_dir/Skyrim Stock"
            log_status "DEBUG" "Modlist Gamedir: $modlist_gamedir"
        elif [[ $game_path_line =~ Game\ Root ]]; then
            modlist_gamedir="$modlist_dir/Game Root"
            log_status "DEBUG" "Modlist Gamedir: $modlist_gamedir"
        elif [[ $game_path_line =~ STOCK\ GAME ]]; then
            modlist_gamedir="$modlist_dir/STOCK GAME"
            log_status "DEBUG" "Modlist Gamedir: $modlist_gamedir"
        elif [[ $game_path_line =~ Stock\ Game ]]; then
            modlist_gamedir="$modlist_dir/Stock Game"
            log_status "DEBUG" "Modlist Gamedir: $modlist_gamedir"
        elif [[ $game_path_line =~ root\\\\Skyrim\ Special\ Edition ]]; then
            modlist_gamedir="$modlist_dir/root/Skyrim Special Edition"
            log_status "DEBUG" "Modlist Gamedir: $modlist_gamedir"
        fi

        if [[ "$modlist_sdcard" -eq "1" && "$steamdeck" -eq "1" ]]; then
            log_status "DEBUG" "Using SDCard on Steam Deck"
            modlist_gamedir_sdcard="${modlist_gamedir#*mmcblk0p1}"
            sdcard_new_path="$modlist_gamedir_sdcard"

            # Strip /run/media/deck/UUID if present
            if [[ "$sdcard_new_path" == /run/media/deck/* ]]; then
                sdcard_new_path="/${sdcard_new_path#*/run/media/deck/*/*}"
                log_status "DEBUG" "SD Card Path after stripping: $sdcard_new_path"
            fi

            new_string="@ByteArray(D:${sdcard_new_path//\//\\\\})"
            log_status "DEBUG" "New String: $new_string"
        else
            new_string="@ByteArray(Z:${modlist_gamedir//\//\\\\})"
            log_status "DEBUG" "New String: $new_string"
        fi

    elif [[ "$game_path_line" == *steamapps* ]]; then
        log_status "INFO" "Vanilla Game Directory required, editing Game Path..."
        modlist_gamedir="$steam_library/$gamevar"
        log_status "DEBUG" "Modlist Gamedir: $modlist_gamedir"
        
        if [[ "$basegame_sdcard" -eq "1" && "$steamdeck" -eq "1" ]]; then
            log_status "DEBUG" "Using SDCard on Steam Deck"
            modlist_gamedir_sdcard="${modlist_gamedir#*mmcblk0p1}"
            sdcard_new_path="$modlist_gamedir_sdcard/$gamevar"
            new_string="@ByteArray(D:${sdcard_new_path//\//\\\\})"
            log_status "DEBUG" "New String: $new_string"
        else
            new_string="@ByteArray(Z:${modlist_gamedir//\//\\\\})"
            log_status "DEBUG" "New String: $new_string"
        fi
    else
        log_status "WARN" "Neither Game Root, Stock Game or Vanilla Game directory found, Please launch MO and set path manually..."
        return 1
    fi

    # Replace the string in the file
    file_to_modify="$modlist_dir/ModOrganizer.ini"
    escaped_new_string=$(printf '%s\n' "$new_string" | sed -e 's/[\/&]/\\&/g')
    sed -i "/^gamePath/c\gamePath=$escaped_new_string" "$file_to_modify"

    log_status "SUCCESS" "Game path set successfully"
}

##########################################
# Update Executables in ModOrganizer.ini #
##########################################

update_executables() {

    # Take the line passed to the function
    echo "Original Line: $orig_line_path" >>$LOGFILE 2>&1

    skse_loc=$(echo "$orig_line_path" | cut -d '=' -f 2-)
    echo "SKSE Loc: $skse_loc" >>$LOGFILE 2>&1

    # Drive letter
    if [[ "$modlist_sdcard" -eq 1 && "$steamdeck" -eq 1 ]]; then
        echo "Using SDCard on Steam Deck" >>$LOGFILE 2>&1
        drive_letter=" = D:"
    else
        drive_letter=" = Z:"
    fi

    # Find the workingDirectory number

    binary_num=$(echo "$orig_line_path" | cut -d '=' -f -1)
    echo "Binary Num: $binary_num" >>$LOGFILE 2>&1

    # Find the equvalent workingDirectory
    justnum=$(echo "$binary_num" | cut -d '\' -f 1)
    bin_path_start=$(echo "$binary_num" | tr -d ' ' | sed 's/\\/\\\\/g')
    path_start=$(echo "$justnum\\workingDirectory" | sed 's/\\/\\\\/g')
    echo "Path Start: $path_start" >>$LOGFILE 2>&1
    # Decide on steam apps or Stock Game etc

    if [[ "$orig_line_path" == *"mods"* ]]; then
        # mods path type found
        echo -e "mods path Found" >>$LOGFILE 2>&1

        # Path Middle / modlist_dr
        if [[ "$modlist_sdcard" -eq 1 && "$steamdeck" -eq 1 ]]; then
            echo "Using SDCard on Steam Deck" >>$LOGFILE 2>&1
            drive_letter=" = D:"
            echo "$modlist_dir" >>$LOGFILE 2>&1
            path_middle="${modlist_dir#*mmcblk0p1}"
            # Strip /run/media/deck/UUID
            if [[ "$path_middle" == /run/media/*/* ]]; then
                path_middle="/${path_middle#*/run/media/*/*/*}"
                echo "Path Middle after stripping: $path_middle" >>$LOGFILE 2>&1
            fi
        else
            path_middle="$modlist_dir"
        fi

        echo "Path Middle: $path_middle" >>$LOGFILE 2>&1

        path_end=$(echo "${skse_loc%/*}" | sed 's/.*\/mods/\/mods/')
        echo "Path End: $path_end" >>$LOGFILE 2>&1
        bin_path_end=$(echo "$skse_loc" | sed 's/.*\/mods/\/mods/')
        echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1
        elif grep -q -E "(Stock Game|Game Root|STOCK GAME|Stock Game Folder|Stock Folder|Skyrim Stock|root/Skyrim Special Edition)" <<<"$orig_line_path"; then
        # STOCK GAME ROOT FOUND
        echo -e "Stock/Game Root Found" >>$LOGFILE 2>&1

        # Path Middle / modlist_dr
        if [[ "$modlist_sdcard" -eq 1 && "$steamdeck" -eq 1 ]]; then
            echo "Using SDCard on Steam Deck" >>$LOGFILE 2>&1
            drive_letter=" = D:"
            echo "Modlist Dir: $modlist_dir" >>$LOGFILE 2>&1
            path_middle="${modlist_dir#*mmcblk0p1}"
            # Strip /run/media/deck/UUID
            if [[ "$path_middle" == /run/media/*/* ]]; then
                path_middle="/${path_middle#*/run/media/*/*/*}"
                echo "Path Middle after stripping: $path_middle" >>$LOGFILE 2>&1
            fi
        else
            path_middle="$modlist_dir"
        fi
        echo "Path Middle: $path_middle" >>$LOGFILE 2>&1

        # Get the end of our path
        if [[ $orig_line_path =~ Stock\ Game ]]; then
            dir_type="stockgame"
            path_end=$(echo "${skse_loc%/*}" | sed 's/.*\/Stock Game/\/Stock Game/')
            echo "Path End: $path_end" >>$LOGFILE 2>&1
            bin_path_end=$(echo "$skse_loc" | sed 's/.*\/Stock Game/\/Stock Game/')
            echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1
        elif [[ $orig_line_path =~ Game\ Root ]]; then
            dir_type="gameroot"
            path_end=$(echo "${skse_loc%/*}" | sed 's/.*\/Game Root/\/Game Root/')
            echo "Path End: $path_end" >>$LOGFILE 2>&1
            bin_path_end=$(echo "$skse_loc" | sed 's/.*\/Game Root/\/Game Root/')
            echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1
        elif [[ $orig_line_path =~ STOCK\ GAME ]]; then
            dir_type="STOCKGAME"
            path_end=$(echo "${skse_loc%/*}" | sed 's/.*\/STOCK GAME/\/STOCK GAME/')
            echo "Path End: $path_end" >>$LOGFILE 2>&1
            bin_path_end=$(echo "$skse_loc" | sed 's/.*\/STOCK GAME/\/STOCK GAME/')
            echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1
        elif [[ $orig_line_path =~ Stock\ Folder ]]; then
            dir_type="stockfolder"
            path_end=$(echo "${skse_loc%/*}" | sed 's/.*\/Stock Folder/\/Stock Folder/')
            echo "Path End: $path_end" >>$LOGFILE 2>&1
            bin_path_end=$(echo "$skse_loc" | sed 's/.*\/Stock Folder/\/Stock Folder/')
            echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1
        elif [[ $orig_line_path =~ Skyrim\ Stock ]]; then
            dir_type="skyrimstock"
            path_end=$(echo "${skse_loc%/*}" | sed 's/.*\/Skyrim Stock/\/Skyrim Stock/')
            echo "Path End: $path_end" >>$LOGFILE 2>&1
            bin_path_end=$(echo "$skse_loc" | sed 's/.*\/Skyrim Stock/\/Skyrim Stock/')
            echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1
        elif [[ $orig_line_path =~ Stock\ Game\ Folder ]]; then
            dir_type="stockgamefolder"
            path_end=$(echo "$skse_loc" | sed 's/.*\/Stock Game Folder/\/Stock Game Folder/')
            echo "Path End: $path_end" >>$LOGFILE 2>&1
        elif [[ $orig_line_path =~ root\/Skyrim\ Special\ Edition ]]; then
            dir_type="rootskyrimse"
            path_end="/${skse_loc# }"
            echo "Path End: $path_end" >>$LOGFILE 2>&1
            bin_path_end="/${skse_loc# }"
            echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1
        fi
        elif [[ "$orig_line_path" == *"steamapps"* ]]; then
        # STEAMAPPS FOUND
        echo -e "steamapps Found" >>$LOGFILE 2>&1

        # Path Middle / modlist_dr
        if [[ "$basegame_sdcard" -eq "1" && "$steamdeck" -eq "1" ]]; then
            echo "Using SDCard on Steam Deck" >>$LOGFILE 2>&1
            path_middle="${steam_library#*mmcblk0p1}"
            drive_letter=" = D:"
        else
            echo "Steamapps Steam Library Path: $steam_library"
            path_middle=${steam_library%%steamapps*}
        fi
        echo "Path Middle: $path_middle" >>$LOGFILE 2>&1
        path_end=$(echo "${skse_loc%/*}" | sed 's/.*\/steamapps/\/steamapps/')
        echo "Path End: $path_end" >>$LOGFILE 2>&1
        bin_path_end=$(echo "$skse_loc" | sed 's/.*\/steamapps/\/steamapps/')
        echo "Bin Path End: $bin_path_end" >>$LOGFILE 2>&1

    else
        echo "No matching pattern found in the path: $orig_line_path" >>$LOGFILE 2>&1
        bail_out=1
        echo $bail_out >>$LOGFILE 2>&1

    fi

    echo "Bail Out: $bail_out" >>$LOGFILE 2>&1

    if [[ $bail_out -eq 1 ]]; then
        echo "Exiting function due to bail_out" >>$LOGFILE 2>&1
        return
    else
        # Combine them all together
        full_bin_path="$bin_path_start$drive_letter$path_middle$bin_path_end"
        echo "Full Bin Path: $full_bin_path" >>$LOGFILE 2>&1
        full_path="$path_start$drive_letter$path_middle$path_end"
        echo "Full Path: $full_path" >>$LOGFILE 2>&1

        # Replace forwardslashes with double backslashes
        new_path=${full_path//\//\\\\\\\\}
        echo "New Path: $new_path" >>$LOGFILE 2>&1

        # Convert the lines in ModOrganizer.ini, if it isn't already

        sed -i "\|^${bin_path_start}|s|^.*$|${full_bin_path}|" "$modlist_ini"
        # Convert workingDirectory entries
        sed -i "\|^${path_start}|s|^.*$|${new_path}|" "$modlist_ini"
    fi

}

#################################################
# Edit Custom binary and workingDirectory paths #
#################################################

edit_binary_working_paths() {

	grep -E -e "skse64_loader\.exe" -e "f4se_loader\.exe" "$modlist_ini" | while IFS= read -r orig_line_path; do
		update_executables
	done

}

################################
# Set or Select the Resolution #
################################

select_resolution() {
	if [ "$steamdeck" -eq 1 ]; then
		set_res="1280x800"
	else
		while true; do
			echo -e "\e[31m ** Enter your desired resolution in the format 1920x1200: ** \e[0m"
			read -p " " user_res

			# Validate the input format
			if [[ "$user_res" =~ ^[0-9]+x[0-9]+$ ]]; then
				# Ask for confirmation
				echo -e "\e[31m \n** Is $user_res your desired resolution? (y/N): ** \e[0m"
				read -p " " confirm
				if [[ "$confirm" =~ ^[Yy]$ ]]; then
					set_res="$user_res"
					break
				else
					echo "Please enter the resolution again." | tee -a $LOGFILE
				fi
			else
				echo "Invalid input format. Please enter the resolution in the format 1920x1200." | tee -a $LOGFILE
			fi
		done
	fi

	echo "Resolution set to: $set_res" | tee -a $LOGFILE
}

######################################
# Update the resolution in INI files #
######################################

update_ini_resolution() {

    echo -ne "\nEditing Resolution in prefs files... " | tee -a "$LOGFILE"

    # Find all SSEDisplayTweaks.ini files in the specified directory and its subdirectories
    ini_files=$(find "$modlist_dir" -name "SSEDisplayTweaks.ini")

    if [[ "$gamevar" == "Skyrim Special Edition" && -n "$ini_files" ]]; then
        while IFS= read -r ini_file; do
            # Use awk to replace the lines with the new values, handling spaces in paths
            awk -v res="$set_res" '/^(#?)Resolution[[:space:]]*=/ { print "Resolution=" res; next } \
                                    /^(#?)Fullscreen[[:space:]]*=/ { print "Fullscreen=false"; next } \
                                    /^(#?)#Fullscreen[[:space:]]*=/ { print "#Fullscreen=false"; next } \
                                    /^(#?)Borderless[[:space:]]*=/ { print "Borderless=true"; next } \
                                    /^(#?)#Borderless[[:space:]]*=/ { print "#Borderless=true"; next }1' "$ini_file" >"$ini_file.new"

            cp "$ini_file.new" "$ini_file"
            echo "Updated $ini_file with Resolution=$res, Fullscreen=false, Borderless=true" >>"$LOGFILE" 2>&1
            echo -e " Done." >>"$LOGFILE" 2>&1
        done <<<"$ini_files"
    elif [[ "$gamevar" == "Fallout 4" ]]; then
        echo "Not Skyrim, skipping SSEDisplayTweaks" >>"$LOGFILE" 2>&1
    fi

    ##########

    # Split $set_res into two variables
    isize_w=$(echo "$set_res" | cut -d'x' -f1)
    isize_h=$(echo "$set_res" | cut -d'x' -f2)

    # Find all instances of skyrimprefs.ini, Fallout4Prefs.ini, falloutprefs.ini, or Oblivion.ini in specified directories

    if [[ "$gamevar" == "Skyrim Special Edition" ]]; then
        ini_files=$(find "$modlist_dir/profiles" "$modlist_dir/Stock Game" "$modlist_dir/Game Root" "$modlist_dir/STOCK GAME" "$modlist_dir/Stock Game Folder" "$modlist_dir/Stock Folder" "$modlist_dir/Skyrim Stock" -iname "skyrimprefs.ini" 2>/dev/null)
    elif [[ "$gamevar" == "Fallout 4" ]]; then
        ini_files=$(find "$modlist_dir/profiles" "$modlist_dir/Stock Game" "$modlist_dir/Game Root" "$modlist_dir/STOCK GAME" "$modlist_dir/Stock Game Folder" "$modlist_dir/Stock Folder" -iname "Fallout4Prefs.ini" 2>/dev/null)
    elif [[ "$gamevar" == "Fallout New Vegas" ]]; then
        ini_files=$(find "$modlist_dir/profiles" "$modlist_dir/Stock Game" "$modlist_dir/Game Root" "$modlist_dir/STOCK GAME" "$modlist_dir/Stock Game Folder" "$modlist_dir/Stock Folder" -iname "falloutprefs.ini" 2>/dev/null)
    elif [[ "$gamevar" == "Oblivion" ]]; then
        ini_files=$(find "$modlist_dir/profiles" "$modlist_dir/Stock Game" "$modlist_dir/Game Root" "$modlist_dir/STOCK GAME" "$modlist_dir/Stock Game Folder" "$modlist_dir/Stock Folder" -iname "Oblivion.ini" 2>/dev/null)
    fi

    if [ -n "$ini_files" ]; then
        while IFS= read -r ini_file; do
            # Use awk to replace the lines with the new values in the appropriate ini file
            if [[ "$gamevar" == "Skyrim Special Edition" ]] || [[ "$gamevar" == "Fallout 4" ]] || [[ "$gamevar" == "Fallout New Vegas" ]]; then
                awk -v isize_w="$isize_w" -v isize_h="$isize_h" '/^iSize W/ { print "iSize W = " isize_w; next } \
                                                                    /^iSize H/ { print "iSize H = " isize_h; next }1' "$ini_file" >"$HOME/temp_file" && mv "$HOME/temp_file" "$ini_file"
            elif [[ "$gamevar" == "Oblivion" ]]; then
                awk -v isize_w="$isize_w" -v isize_h="$isize_h" '/^iSize W=/ { print "iSize W=" isize_w; next } \
                                                                    /^iSize H=/ { print "iSize H=" isize_h; next }1' "$ini_file" >"$HOME/temp_file" && mv "$HOME/temp_file" "$ini_file"
            fi

            echo "Updated $ini_file with iSize W=$isize_w, iSize H=$isize_h" >>"$LOGFILE" 2>&1
        done <<<"$ini_files"
    else
        echo "No suitable prefs.ini files found in specified directories. Please set manually using the INI Editor in MO2." | tee -a "$LOGFILE"
    fi

    echo -e "Done." | tee -a "$LOGFILE"

}

###################
# Edit resolution #
###################

edit_resolution() {
    if [[ -n "$selected_resolution" ]]; then
        log_status "DEBUG" "Applying resolution: $selected_resolution"
        set_res="$selected_resolution"
        update_ini_resolution
    else
        log_status "DEBUG" "Resolution setup skipped"
    fi
}

##########################
# Small additional tasks #
##########################

small_additional_tasks() {

    # Delete MO2 plugins that don't work via Proton

    file_to_delete="$modlist_dir/plugins/FixGameRegKey.py"

    if [ -e "$file_to_delete" ]; then
        rm "$file_to_delete"
        echo "File deleted: $file_to_delete" >>$LOGFILE 2>&1
    else
        echo "File does not exist: $file_to_delete" >>"$LOGFILE" 2>&1
    fi

    # Download Font to support Bethini
    wget https://github.com/mrbvrz/segoe-ui-linux/raw/refs/heads/master/font/seguisym.ttf -q -nc -O "$compat_data_path/pfx/drive_c/windows/Fonts/seguisym.ttf"

}

###############################
# Set Steam Artwork Function  #
###############################

set_steam_artwork() {
    # Only run for Tuxborn modlist
    if [[ "$MODLIST" == *"Tuxborn"* ]]; then
        log_status "DEBUG" "Setting up Steam artwork for Tuxborn..."
        
        # Source directory with artwork
        local source_dir="$modlist_dir/Steam Icons"
        
        if [[ ! -d "$source_dir" ]]; then
            log_status "WARN" "Steam Icons directory not found at $source_dir"
            return 1
        fi
        
        # Find all Steam userdata directories
        for userdata_dir in "$HOME/.local/share/Steam/userdata" "$HOME/.steam/steam/userdata"; do
            if [[ ! -d "$userdata_dir" ]]; then
                continue
            fi
            
            # Process each user ID directory
            for user_id_dir in "$userdata_dir"/*; do
                if [[ ! -d "$user_id_dir" || "$user_id_dir" == *"0"* ]]; then
                    continue  # Skip non-directories and the anonymous user
                fi
                
                # Create grid directory if it doesn't exist
                local grid_dir="$user_id_dir/config/grid"
                mkdir -p "$grid_dir"
                
                # Copy grid-tall.png to both APPID.png and APPIDp.png
                if [[ -f "$source_dir/grid-tall.png" ]]; then
                    cp "$source_dir/grid-tall.png" "$grid_dir/${APPID}.png"
                    log_status "DEBUG" "Copied grid-tall.png to ${APPID}.png"
                    cp "$source_dir/grid-tall.png" "$grid_dir/${APPID}p.png"
                    log_status "DEBUG" "Copied grid-tall.png to ${APPID}p.png"
                fi
                
                # Copy grid-hero.png to APPID_hero.png
                if [[ -f "$source_dir/grid-hero.png" ]]; then
                    cp "$source_dir/grid-hero.png" "$grid_dir/${APPID}_hero.png"
                    log_status "DEBUG" "Copied grid-hero.png to ${APPID}_hero.png"
                fi
                
                # Copy grid-logo.png to APPID_logo.png
                if [[ -f "$source_dir/grid-logo.png" ]]; then
                    cp "$source_dir/grid-logo.png" "$grid_dir/${APPID}_logo.png"
                    log_status "DEBUG" "Copied grid-logo.png to ${APPID}_logo.png"
                fi
                
                log_status "DEBUG" "Tuxborn artwork copied for user ID $(basename "$user_id_dir")"
            done
        done
        
        log_status "DEBUG" "Steam artwork setup complete for Tuxborn"
    fi
}


##########################
# Modlist Specific Steps #
##########################

modlist_specific_steps() {
    local modlist_lower=$(echo "${MODLIST// /}" | tr '[:upper:]' '[:lower:]')
    
    # Call the Steam artwork function for all modlists
    set_steam_artwork | tee -a "$LOGFILE"

    # Handle Wildlander specially due to its custom spinner animation
    if [[ "$MODLIST" == *"Wildlander"* ]]; then
        log_status "INFO" "\nRunning steps specific to \e[32m$MODLIST\e[0m. This can take some time, be patient!"
        
        # Install dotnet with spinner animation
        spinner=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
        run_protontricks --no-bwrap "$APPID" -q dotnet472 >/dev/null 2>&1 &
        
        pid=$! # Store the PID of the background process
        
        while kill -0 "$pid" >/dev/null 2>&1; do
            for i in "${spinner[@]}"; do
                echo -en "\r${i}\c"
                sleep 0.1
            done
        done
        
        wait "$pid" # Wait for the process to finish
        
        # Clear the spinner and move to the next line
        echo -en "\r\033[K" # Clear the spinner line
        
        if [[ $? -ne 0 ]]; then
            log_status "ERROR" "Component install failed with exit code $?"
        else
            log_status "SUCCESS" "Wine Component install completed successfully."
        fi
        
        new_output="$(run_protontricks --no-bwrap "$APPID" list-installed 2>/dev/null)"
        log_status "DEBUG" "Components Found: $new_output"
        return 0
    fi

    # Handle the rest of the modlists with the compact approach
    for pattern in "${!modlist_configs[@]}"; do
        if [[ "$pattern" != "wildlander" ]] && [[ "$modlist_lower" =~ ${pattern//|/|.*} ]]; then
            log_status "INFO" "\nRunning steps specific to \e[32m$MODLIST\e[0m. This can take some time, be patient!"
            
            IFS=' ' read -ra components <<< "${modlist_configs[$pattern]}"
            for component in "${components[@]}"; do
                if [[ "$component" == "dotnet8" ]]; then
                    log_status "INFO" "\nDownloading .NET 8 Runtime"
                    wget https://download.visualstudio.microsoft.com/download/pr/77284554-b8df-4697-9a9e-4c70a8b35f29/6763c16069d1ab8fa2bc506ef0767366/dotnet-runtime-8.0.5-win-x64.exe -q -nc --show-progress --progress=bar:force:noscroll -O "$HOME/Downloads/dotnet-runtime-8.0.5-win-x64.exe"
                    
                    log_status "INFO" "Installing .NET 8 Runtime...."
                    WINEDEBUG=-all run_protontricks --no-bwrap -c 'wine "$HOME/Downloads/dotnet-runtime-8.0.5-win-x64.exe" /Q' "$APPID" >/dev/null 2>&1
                    log_status "SUCCESS" "Done."
                else
                    log_status "INFO" "Installing .NET ${component#dotnet}..."
                    WINEDEBUG=-all run_protontricks --no-bwrap "$APPID" -q "$component" >/dev/null 2>&1
                    log_status "SUCCESS" "Done."
                fi
            done
            
            set_win10_prefix
            new_output="$(run_protontricks --no-bwrap "$APPID" list-installed 2>/dev/null)"
            log_status "DEBUG" "Components Found: $new_output"
            break
        fi
    done
}

######################################
# Create DXVK Graphics Pipeline file #
######################################

create_dxvk_file() {
    echo "Use SDCard for DXVK File?: $basegame_sdcard" >>"$LOGFILE" 2>&1
    echo -e "\nCreating dxvk.conf file - Checking if Modlist uses Game Root, Stock Game or Vanilla Game Directory.." >>"$LOGFILE" 2>&1

    game_path_line=$(grep '^gamePath' "$modlist_ini")
    echo "Game Path Line: $game_path_line" >>"$LOGFILE" 2>&1

    if [[ "$game_path_line" == *Stock\ Game* || "$game_path_line" == *STOCK\ GAME* || "$game_path_line" == *Stock\ Game\ Folder* || "$game_path_line" == *Stock\ Folder* || "$game_path_line" == *Skyrim\ Stock* || "$game_path_line" == *Game\ Root* ]]; then
        # Get the end of our path
        if [[ $game_path_line =~ Stock\ Game\ Folder ]]; then
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/Stock Game Folder/dxvk.conf"
        elif [[ $game_path_line =~ Stock\ Folder ]]; then
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/Stock Folder/dxvk.conf"
        elif [[ $game_path_line =~ Skyrim\ Stock ]]; then
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/Skyrim Stock/dxvk.conf"
        elif [[ $game_path_line =~ Game\ Root ]]; then
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/Game Root/dxvk.conf"
        elif [[ $game_path_line =~ STOCK\ GAME ]]; then
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/STOCK GAME/dxvk.conf"
        elif [[ $game_path_line =~ Stock\ Game ]]; then
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/Stock Game/dxvk.conf"
        elif [[ $game_path_line =~ root\\Skyrim\ Special\ Edition ]]; then
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/root/Skyrim Special Edition/dxvk.conf"
        fi

        if [[ "$modlist_sdcard" -eq "1" ]]; then
            echo "Using SDCard" >>"$LOGFILE" 2>&1
            modlist_gamedir_sdcard="${modlist_gamedir#*mmcblk0p1}"
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_gamedir/dxvk.conf"
        fi

    elif [[ "$game_path_line" == *steamapps* ]]; then
        echo -ne "Vanilla Game Directory required, editing Game Path.. " >>"$LOGFILE" 2>&1
        modlist_gamedir="$steam_library"
        echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_gamedir/dxvk.conf"
        if [[ "$basegame_sdcard" -eq "1" ]]; then
            echo "Using SDCard" >>"$LOGFILE" 2>&1
            modlist_gamedir_sdcard="${modlist_gamedir#*mmcblk0p1}"
            echo "dxvk.enableGraphicsPipelineLibrary = False" >"$modlist_dir/$gamevar/dxvk.conf"
        fi
    fi
}

#############################
# Create protontricks alias #
#############################

protontricks_alias() {
    if [[ "$which_protontricks" = "flatpak" ]]; then
        local protontricks_alias_exists=$(grep "^alias protontricks=" ~/.bashrc)
        local launch_alias_exists=$(grep "^alias protontricks-launch" ~/.bashrc)

        if [[ -z "$protontricks_alias_exists" ]]; then
            echo -e "\nAdding protontricks alias to ~/.bashrc"
            echo "alias protontricks='flatpak run com.github.Matoking.protontricks'" >> ~/.bashrc
            source ~/.bashrc
        else
            echo "protontricks alias already exists in ~/.bashrc" >> "$LOGFILE" 2>&1
        fi

        if [[ -z "$launch_alias_exists" ]]; then
            echo -e "\nAdding protontricks-launch alias to ~/.bashrc"
            echo "alias protontricks-launch='flatpak run --command=protontricks-launch com.github.Matoking.protontricks'" >> ~/.bashrc
            source ~/.bashrc
        else
            echo "protontricks-launch alias already exists in ~/.bashrc" >> "$LOGFILE" 2>&1
        fi
    else
        echo "Protontricks is not installed via flatpak, skipping alias creation." >> "$LOGFILE" 2>&1
    fi
}

############################
# FNV Launch Option Notice #
############################

fnv_launch_options() {
    log_status "DEBUG" "fnv_launch_options: gamevar='$gamevar', compat_data_path='$compat_data_path'"
    if [[ "$gamevar" == "Fallout New Vegas" ]]; then
        if [[ -n "$compat_data_path" && -d "$compat_data_path" ]]; then
            log_status "WARN" "\nFor $MODLIST, please add the following line to the Launch Options in Steam for your '$MODLIST' entry:"
            log_status "SUCCESS" "\nSTEAM_COMPAT_DATA_PATH=\"$compat_data_path\" %command%"
            log_status "WARN" "\nThis is essential for the modlist to load correctly."
        else
            log_status "ERROR" "\nCould not determine the compatdata path for Fallout New Vegas. Please manually set the correct path in the Launch Options."
        fi
    fi
}

#####################
# Exit more cleanly #
#####################

cleaner_exit() {
    # Clean up wine and winetricks processes
    cleanup_wine_procs
    log_status "DEBUG" "Cleanup complete"
    exit 1
}

####################
# END OF FUNCTIONS #
####################

#######################
# Note Script Version #
#######################

echo -e "Script Version $script_ver" >>"$LOGFILE" 2>&1

######################
# Note Date and Time #
######################

echo -e "Script started at: $(date +'%Y-%m-%d %H:%M:%S')" >>"$LOGFILE" 2>&1

#############################
# Detect if running on deck #
#############################

detect_steamdeck

###########################################
# Detect Protontricks (flatpak or native) #
###########################################

detect_protontricks

###############################
# Detect Protontricks Version #
###############################

protontricks_version

##########################################
# Create protontricks alias in ~/.bashrc #
##########################################

protontricks_alias

##############################################################
# List Skyrim and Fallout Modlists from Steam (protontricks) #
##############################################################

IFS=$'\n' readarray -t output_array < <(run_protontricks -l | tr -d $'\r' | grep -i 'Non-Steam shortcut' | grep -i 'Skyrim\|Fallout\|FNV\|Oblivion' | cut -d ' ' -f 3-)

if [[ ${#output_array[@]} -eq 0 ]]; then
    echo "" | tee -a "$LOGFILE"
    log_status "ERROR" "No modlists detected for Skyrim, Oblivion or Fallout/FNV!"
    log_status "INFO" "Please make sure your entry in Steam is something like 'Skyrim - ModlistName'"
    log_status "INFO" "or 'Fallout - ModlistName' AND that you have pressed play in Steam at least once!"
    cleaner_exit
fi

echo "" | tee -a "$LOGFILE"
echo -e "\e[33mDetected Modlists:\e[0m" | tee -a "$LOGFILE"

# Print numbered list with color
for i in "${!output_array[@]}"; do
    echo -e "\e[32m$((i + 1)))\e[0m ${output_array[$i]}"
done

# Read user selection with proper prompt
echo "───────────────────────────────────────────────────────────────────"
while true; do
    read -p $'\e[33mSelect a modlist (1-'"${#output_array[@]}"$'): \e[0m' choice_num

    # Add a debug flag at the top for easy toggling
    DEBUG_MODLIST_SELECTION=0  # Set to 1 to enable extra debug output

    # After reading user input for choice_num:
    if [[ $DEBUG_MODLIST_SELECTION -eq 1 ]]; then
        echo "[DEBUG] Raw user input: '$choice_num'" | tee -a "$LOGFILE"
    fi
    choice_num=$(echo "$choice_num" | xargs)  # Trim whitespace
    if [[ $DEBUG_MODLIST_SELECTION -eq 1 ]]; then
        echo "[DEBUG] Trimmed user input: '$choice_num'" | tee -a "$LOGFILE"
    fi

    # Before the selection validation if-statement:
    if [[ $DEBUG_MODLIST_SELECTION -eq 1 ]]; then
        echo "[DEBUG] Validating: '$choice_num' =~ ^[0-9]+$ && $choice_num -ge 1 && $choice_num -le ${#output_array[@]}" | tee -a "$LOGFILE"
    fi

    # Validate selection properly
    if [[ "$choice_num" =~ ^[0-9]+$ ]] && [[ "$choice_num" -ge 1 ]] && [[ "$choice_num" -le "${#output_array[@]}" ]]; then
        if [[ $DEBUG_MODLIST_SELECTION -eq 1 ]]; then
            echo "[DEBUG] Selection valid. Index: $((choice_num - 1)), Value: '${output_array[$((choice_num - 1))]}'" | tee -a "$LOGFILE"
        fi
        choice="${output_array[$((choice_num - 1))]}"
        MODLIST=$(echo "$choice" | cut -d ' ' -f 3- | rev | cut -d ' ' -f 2- | rev)
        log_status "DEBUG" "MODLIST: $MODLIST"
        break # Exit the loop if selection is valid
    else
        if [[ $DEBUG_MODLIST_SELECTION -eq 1 ]]; then
            echo "[DEBUG] Invalid selection. choice_num: '$choice_num', output_array length: ${#output_array[@]}" | tee -a "$LOGFILE"
        fi
        log_status "ERROR" "Invalid selection. Please enter a number between 1 and ${#output_array[@]}."
        # Removed exit 1, so the loop continues
    fi
done

# Add a newline after the selection for cleaner output
echo ""

# Initial detection phase
cleanup_wine_procs
set_appid
detect_game
detect_steam_library
detect_modlist_dir_path

# Set modlist_sdcard if required
modlist_sdcard=0
if [[ "$modlist_dir" =~ ^/run/media ]]; then
    modlist_sdcard=1
fi

# Detect compatdata path and Proton version
detect_compatdata_path
detect_proton_version
fnv_launch_options

# Get resolution preference
if [ "$steamdeck" -eq 1 ]; then
    selected_resolution="1280x800"
    log_status "INFO" "Steam Deck detected - Resolution will be set to 1280x800"
else
    echo -e "Do you wish to set the display resolution? (This can be changed manually later)"
    read -p $'\e[33mSet resolution? (y/N): \e[0m' response
    
    if [[ "$response" =~ ^[Yy]$ ]]; then
        while true; do
            read -p $'\e[33mEnter resolution (e.g., 1920x1080): \e[0m' user_res
            if [[ "$user_res" =~ ^[0-9]+x[0-9]+$ ]]; then
                selected_resolution="$user_res"
                log_status "DEBUG" "Resolution will be set to: $selected_resolution"
                break
            else
                log_status "ERROR" "Invalid format. Please use format: 1920x1080"
            fi
        done
    else
        log_status "INFO" "Resolution setup skipped"
    fi
fi

# Then show the detection summary including the resolution if set
echo -e "\n\e[1mDetection Summary:\e[0m" | tee -a "$LOGFILE"
echo -e "===================" | tee -a "$LOGFILE"
echo -e "Selected Modlist: \e[32m$MODLIST\e[0m" | tee -a "$LOGFILE"
echo -e "Game Type: \e[32m$gamevar\e[0m" | tee -a "$LOGFILE"
echo -e "Steam App ID: \e[32m$APPID\e[0m" | tee -a "$LOGFILE"
echo -e "Modlist Directory: \e[32m$modlist_dir\e[0m" | tee -a "$LOGFILE"
echo -e "Proton Version: \e[32m$proton_ver\e[0m" | tee -a "$LOGFILE"
if [[ -n "$selected_resolution" ]]; then
    echo -e "Resolution: \e[32m$selected_resolution\e[0m" | tee -a "$LOGFILE"
fi

# Show simple confirmation with minimal info
read -rp $'\e[32mDo you want to proceed with the installation? (y/N)\e[0m ' proceed

if [[ $proceed =~ ^[Yy]$ ]]; then
    # Function to update progress
    update_progress() {
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
        printf "\r[%-${bar_length}s] %d%%" "$bar" "$percent"
    }

    {
        # Add newline before progress bar starts
        echo ""
        
        # Protontricks setup (10%)
        printf "\r\033[KProgress: [%-50s] %d%% - Setting up Protontricks..." "                                                  " "10"
        set_protontricks_perms >/dev/null 2>&1
        
        # Dotfiles (20%)
        printf "\r\033[KProgress: [%-50s] %d%% - Enabling dotfiles..." "==========                                        " "20"
        enable_dotfiles >/dev/null 2>&1
        
        # Wine components (40%)
        printf "\r\033[KProgress: [%-50s] %d%% - Installing Wine components..." "====================                              " "40"
        install_wine_components >/dev/null 2>&1
        
        # Windows 10 prefix (50%)
        printf "\r\033[KProgress: [%-50s] %d%% - Setting Windows 10 prefix..." "=========================                         " "50"
        set_win10_prefix >/dev/null 2>&1
        
        # ModOrganizer configuration (70%)
        printf "\r\033[KProgress: [%-50s] %d%% - Configuring Mod Organizer..." "===================================               " "70"
        backup_modorganizer >/dev/null 2>&1
        blank_downloads_dir >/dev/null 2>&1
        replace_gamepath >/dev/null 2>&1
        edit_binary_working_paths >/dev/null 2>&1
        
        # Resolution and additional tasks (90%)
        printf "\r\033[KProgress: [%-50s] %d%% - Setting resolution and additional tasks..." "============================================      " "90"
        edit_resolution >/dev/null 2>&1
        small_additional_tasks >/dev/null 2>&1
        create_dxvk_file >/dev/null 2>&1
        
        # Final steps (100%)
        printf "\r\033[KProgress: [%-50s] %d%% - Completing installation...\n" "==================================================" "100"
        
        # Remove user-facing artwork and debug output
        # echo "" # Add spacing
        # echo "ABOUT TO CALL MODLIST_SPECIFIC_STEPS FOR: $MODLIST" | tee -a "$LOGFILE"
        modlist_specific_steps
        # echo "FINISHED CALLING MODLIST_SPECIFIC_STEPS" | tee -a "$LOGFILE"
        
        # Add two newlines after progress bar completes
        # printf "\n\n"
        
        chown_chmod_modlist_dir
        fnv_launch_options >/dev/null 2>&1
        
    } 2>>$LOGFILE
    
    # Show completion message
    {
        echo ""  # Add blank line before success message
        echo -e "\e[32m✓ Installation completed successfully!\e[0m"
        echo -e "\n📝 Next Steps:"
        echo "  • Launch your modlist through Steam"
        echo "  • When Mod Organizer opens, verify the game path is correct"
        if [[ "$gamevar" == "Skyrim Special Edition" || "$gamevar" == "Fallout 4" ]]; then
            echo "  • Run the game through SKSE/F4SE launcher"
        fi
        echo -e "\n💡 Detailed log available at: $LOGFILE\n"
    } | tee -a "$LOGFILE"

    # Show SD Card status if detected
    if [[ "$steamdeck" -eq 1 ]]; then
        # On Steam Deck, SD card is /run/media/deck/<UUID> or /run/media/mmcblk0p1
        if [[ "$modlist_dir" =~ ^/run/media/deck/[^/]+(/.*)?$ ]] || [[ "$modlist_dir" == "/run/media/mmcblk0p1"* ]]; then
            echo -e "SD Card: \e[32mDetected\e[0m" | tee -a "$LOGFILE"
        fi
    else
        # On non-Deck, just show the path if it's /run/media, but don't call it SD card
        if [[ "$modlist_dir" == "/run/media"* ]]; then
            echo -e "Removable Media: \e[33mDetected at $modlist_dir\e[0m" | tee -a "$LOGFILE"
        fi
    fi
else
    log_status "INFO" "Installation cancelled."
    cleaner_exit
fi

# After the block that prints the completion message and next steps:
# (Find the line: echo -e "\n💡 Detailed log available at: $LOGFILE\n")
# Add this immediately after:
fnv_launch_options