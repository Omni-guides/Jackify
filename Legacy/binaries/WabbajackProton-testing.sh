#!/usr/bin/env bash
#
##################################################################
#                                                                #
# Attempt to automate installing Wabbajack on Linux Steam/Proton #
#                                                                #
#              Alpha v0.19 - Omni, from 25/01/25                 #
#                                                                #
##################################################################

# - v0.01 - Initial script structure.
# - v0.02 - Added functions for most features
# - v0.03 - Completed initial functions
# - v0.04 - Added handling of WebP Installer
# - v0.05 - Switched out installing WebP in favour of dll + .reg files
# - v0.06 - Tidied up some ordering of commands, plus output style differences.
# - v0.07 - Replaced troublesome win7/win10 protontricks setting with swapping out .reg files. Also much faster.
# - v0.08 - Added listing of Wabbajack Steam entries, with selection, if more than one "Wabbajack" named entry found.
# - v0.09 - Initial support for Flatpak Steam libraries
# - v0.10 - Better detection of flatpak protontricks (Bazzite has a wrapper that made it look like native protontricks)
# - v0.11 - Better handling of the Webview Installer
# - v0.12 - Added further support for Flatpak Steam, including override requirement message.
# - v0.13 - Fixed incorrect protontricks-launch command for installing Webview using native protontricks.
# - v0.14 - Fallback support to curl if wget is not found on the system.
# - v0.15 - Add a check/creation of protontricks alias entries, for troubleshooting and future use.
# - v0.16 - Replaced Wabbajack.exe and Steam Library detection to instead use shortcuts.vdf and libraryfolders.vdf to extrapolate, removing ambiguity and user input requirement.
# - v0.17 - Modified the path related functions to handle spaces in the path name.
# - v0.18 - Fixed Wabbajack.exe detection that was causing "blank" options being displayed (e.g if the entry in Steam was left as "Wabbajack.exe" then it would wrongly show up as a blank line.)
# - v0.19 - Changed WebView instller download URL.

# Current Script Version (alpha)
script_ver=0.19

# Today's date
date=$(date +"%d%m%y")

# Set up and blank logs
LOGFILE=$HOME/wabbajack-via-proton-sh.log
echo "" >$LOGFILE
#set -x

######################
# Fancy banner thing #
######################

if [ -f "/usr/bin/toilet" ]; then
	toilet -t -f smmono12 -F border:metal "Omni-Guides (alpha)"
else
	echo "=================================================================================================="
	echo "|  #######  ##     ## ##    ## ####          ######   ##     ## #### ########   ########  ###### |"
	echo "| ##     ## ###   ### ###   ##  ##          ##    ##  ##     ##  ##  ##     ## ##       ##    ## |"
	echo "| ##     ## #### #### ####  ##  ##          ##        ##     ##  ##  ##     ## ##       ##       |"
	echo "| ##     ## ## ### ## ## ## ##  ##  ####### ##   #### ##     ##  ##  ##     ## ######    ######  |"
	echo "| ##     ## ##     ## ##  ####  ##          ##    ##  ##     ##  ##  ##     ## ##             ## |"
	echo "| ##     ## ##     ## ##   ###  ##          ##    ##  ##     ##  ##  ##     ## ##       ##    ## |"
	echo "|  #######  ##     ## ##    ## ####          ######    #######  #### ########   ########  ###### |"
	echo "============================================================================~~--(alpha)--~~======="
fi

#########
# Intro #
#########

echo ""
echo -e "This is an experimental script - an attempt to automate as much as possible of the process of getting"
echo -e "Wabbajack running on Linux via Proton through Steam. Please be aware that stability of the Wabbajack "
echo -e "application is not guaranteed. Please use at your own risk and accept that in the worst case, you may "
echo -e "have to remove and re-add the WabbaJack entry in Steam. You can report back to me via GitHub or the "
echo -e "Official Wabbajack Discord if you discover an issue with this script. Any other feedback, positive"
echo -e "or negative, is also most welcome."

echo -e "\e[32m\nPress any key to continue...\e[0m"
echo
read -n 1 -s -r -p ""

#############
# Functions #
#############

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

	# Check if "which protontricks" outputs a valid path
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
	else
		echo -e "Non-Flatpak Protontricks not found. Checking flatpak..." >>$LOGFILE 2>&1
		if flatpak list | grep -iq protontricks; then
			echo -e "Flatpak Protontricks is already installed." >>$LOGFILE 2>&1
			which_protontricks=flatpak
		else
			echo -e "\e[31m\n** Protontricks not found. Do you wish to install it? (y/n): **\e[0m"
			read -p " " answer
			if [[ $answer =~ ^[Yy]$ ]]; then
				if [[ $steamdeck -eq 1 ]]; then
					flatpak install -u -y --noninteractive flathub com.github.Matoking.protontricks
					which_protontricks=flatpak
				else
					read -p "Choose installation method: 1) Flatpak (preferred) 2) Native: " choice
					if [[ $choice =~ 1 ]]; then
						flatpak install -u -y --noninteractive flathub com.github.Matoking.protontricks
						which_protontricks=flatpak
					else
						echo -e "\nSorry, there are too many distros to automate this!" | tee -a $LOGFILE
						echo -e "Please check how to install Protontricks using your OS package manager (yum, dnf, apt, pacman, etc.)" | tee -a $LOGFILE
					fi
				fi
			fi
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
			echo "alias protontricks='flatpak run com.github.Matoking.protontricks'" >>~/.bashrc
			source ~/.bashrc
		else
			echo "protontricks alias already exists in ~/.bashrc" >>"$LOGFILE" 2>&1
		fi

		if [[ -z "$launch_alias_exists" ]]; then
			echo -e "\nAdding protontricks-launch alias to ~/.bashrc"
			echo "alias protontricks-launch='flatpak run --command=protontricks-launch com.github.Matoking.protontricks'" >>~/.bashrc
			source ~/.bashrc
		else
			echo "protontricks-launch alias already exists in ~/.bashrc" >>"$LOGFILE" 2>&1
		fi
	else
		echo "Protontricks is not installed via flatpak, skipping alias creation." >>"$LOGFILE" 2>&1
	fi
}

#############################
# Run protontricks commands #
#############################

run_protontricks() {
	# Determine the protontricks binary path
	if [ "$which_protontricks" = "flatpak" ]; then
		protontricks_bin="flatpak run com.github.Matoking.protontricks"
	else
		protontricks_bin="protontricks"
	fi

	# Construct and execute the command using eval to preserve quotes
	$protontricks_bin "$@"
}

###############################
# Detect Protontricks Version #
###############################

protontricks_version() {

	# Get the current version of protontricks
	protontricks_version=$(run_protontricks -V | cut -d ' ' -f 2 | sed 's/[()]//g' | sed 's/\.[0-9]$//')

	# Remove any non-numeric characters from the version number
	protontricks_version_cleaned=$(echo "$protontricks_version" | sed 's/[^0-9.]//g')

	echo "Protontricks Version Cleaned = $protontricks_version_cleaned" >>$LOGFILE 2>&1

	# Compare version strings directly using simple string comparison
	if [[ "$protontricks_version_cleaned" < "1.12" ]]; then
		echo "Your protontricks version is too old! Update to version 1.12 or newer and rerun this script. If 'flatpak run com.github.Matoking.protontricks -V' returns 'unknown', then please update via flatpak." | tee -a $LOGFILE
		cleaner_exit
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

###########################
# Get Wabbajack Directory #
###########################

get_wabbajack_path() {
    local wabbajack_path=""
    local wabbajack_entries=()
    local selected_entry=""

    echo -e "\e[33m \nDetecting Wabbajack Install Directory..\e[0m" | tee -a "$LOGFILE"

    # Find all entries with Wabbajack.exe
    local entries_string=$(strings ~/.steam/steam/userdata/*/config/shortcuts.vdf | grep "/Wabbajack.exe")

    if [[ -z "$entries_string" ]]; then
        echo "No Wabbajack.exe entries found in shortcuts.vdf."
        echo "Please ensure Steam is installed and you have added Wabbajack.exe as a non-Steam game." | tee -a "$LOGFILE"
        echo "Please run Wabbajack.exe once via Steam to register it." | tee -a "$LOGFILE"
        return 1 # Indicate failure
    fi

    # Store each entry in an array to handle spaces
    while IFS= read -r entry; do
        local path=$(echo "$entry" | grep -oE '"[^"]+"' | head -n 1 | tr -d '"')
        wabbajack_entries+=("$path")
    done <<<"$entries_string"

    local entry_count=${#wabbajack_entries[@]}
    if [[ "$entry_count" -gt 1 ]]; then
        echo -e "\e[31m \nMultiple Wabbajack.exe paths found, please select which one you wish to configure: \e[0m" | tee -a "$LOGFILE"
        local i=1
        for path in "${wabbajack_entries[@]}"; do
            echo "$i) $path" | tee -a "$LOGFILE"
            ((i++))
        done

        # Prompt user to select an entry
        read -p "Enter the number of the desired entry: " selected_entry

        if [[ ! "$selected_entry" =~ ^[0-9]+$ || "$selected_entry" -lt 1 || "$selected_entry" -gt "$((entry_count))" ]]; then
            echo "Invalid selection." | tee -a "$LOGFILE"
            return 1 # Indicate failure
        fi

        # Extract the selected entry
        wabbajack_path="${wabbajack_entries[$((selected_entry - 1))]}"
    else
        # Single matching entry
        wabbajack_path="${wabbajack_entries[0]}"
    fi

    if [[ -n "$wabbajack_path" ]]; then
        echo "Wabbajack path: $wabbajack_path" >>"$LOGFILE" 2>&1
        application_directory=$(dirname "$wabbajack_path")
        echo "Application Directory: $application_directory" >>"$LOGFILE" 2>&1
        return 0 # Indicate success
    else
        echo "Failed to determine Wabbajack path." | tee -a "$LOGFILE"
        return 1 # Indicate failure
    fi

    echo "Wabbajack Path: $wabbajack_path"
    echo "Application Directory: $application_directory"
}

##################################################
# Detect Wabbajack entry in steam and get App ID #
##################################################

set_appid() {
	wabbajack_entries=$(run_protontricks -l | grep -i 'Non-Steam shortcut' | grep -i wabbajack)

	if [[ -z "$wabbajack_entries" ]]; then
		echo "No Wabbajack entries found. Please ensure your entry in steam contains 'Wabbajack' in some way.." | tee -a $LOGFILE
		exit 1
	fi

	IFS=$'\n' read -d '' -r -a entries_array <<<"$wabbajack_entries"

	if [[ ${#entries_array[@]} -gt 1 ]]; then
		echo -e "\e[31m \nMultiple Wabbajack entries found in Steam, please select which one you wish to configure: \e[0m"

		for i in "${!entries_array[@]}"; do
			stripped_entry=$(echo "${entries_array[i]}" | sed 's/^Non-Steam shortcut: //i')
			echo "$((i + 1)). $stripped_entry"
		done

		echo "Please select the entry you want to use (1-${#entries_array[@]}):"
		read -r selection

		if ! [[ "$selection" =~ ^[0-9]+$ ]] || ((selection < 1 || selection > ${#entries_array[@]})); then
			echo "Invalid selection." | tee -a $LOGFILE
			exit 1
		fi

		selected_entry="${entries_array[$((selection - 1))]}"
	else
		selected_entry="${entries_array[0]}"
	fi

	APPID=$(echo "$selected_entry" | awk {'print $NF'} | sed 's:^.\(.*\).$:\1:')

	echo "Wabbajack App ID:" $APPID >>$LOGFILE 2>&1

	# If $APPID is empty, produce an error
	if [[ -z "$APPID" ]]; then
		echo "APPID empty, something went wrong.." | tee -a $LOGFILE
		exit 1
	fi
}

####################################
# Detect compatdata Directory Path #
####################################

detect_compatdata_path() {

	# Check common Steam library locations first
	for path in "$HOME/.local/share/Steam/steamapps/compatdata" "$HOME/.steam/steam/steamapps/compatdata" "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata"; do
		if [[ -d "$path/$APPID" ]]; then
			compat_data_path="$path/$APPID"
			echo -e "compatdata Path detected: $compat_data_path" >>$LOGFILE 2>&1
			break
		fi
	done

	# If not found in common locations, use find command
	if [[ -z "$compat_data_path" ]]; then
		find / -type d -name "compatdata" 2>/dev/null | while read -r compatdata_dir; do
			if [[ -d "$compatdata_dir/$APPID" ]]; then
				compat_data_path="$compatdata_dir/$appid"
				echo -e "compatdata Path detected: $compat_data_path" >>$LOGFILE 2>&1
				break
			fi
		done
	fi

	if [[ -z "$compat_data_path" ]]; then
		echo "Directory named '$APPID' not found in any compatdata directories."
		echo -e "Please ensure you have started the Steam entry for the modlist at least once, even if it fails.."
	else
		echo "Found compatdata directory with '$APPID': $compat_data_path" >>$LOGFILE 2>&1
	fi
}

#####################################################
# Set protontricks permissions on Wabbajack Directory #
#####################################################

set_protontricks_perms() {

    if [ "$which_protontricks" = "flatpak" ]; then
        echo -e "\e[33m \nSetting Protontricks permissions... \e[0m" | tee -a "$LOGFILE"

        # Set flatpak permission override, quoting the path
        flatpak override --user com.github.Matoking.protontricks --filesystem="$application_directory"

        if [[ "$steamdeck" = 1 ]]; then
            echo -e "\e[33m \nChecking for SDCard and setting permissions appropriately..\e[0m" | tee -a "$LOGFILE"
            # Set protontricks SDCard permissions early to suppress warning
            sdcard_path=$(df -h | grep "/run/media" | awk '{print $NF}')
            echo "$sdcard_path" >>"$LOGFILE" 2>&1
            # Quote the SD card path
            flatpak override --user --filesystem="$sdcard_path" com.github.Matoking.protontricks
            echo -e " Done." >>"$LOGFILE" 2>&1
        fi
    else
        echo -e "Using Native protontricks, skip setting permissions" >>"$LOGFILE" 2>&1
    fi

}

#####################################
# Enable Visibility of (.)dot files #
#####################################

enable_dotfiles() {

	echo $APPID >>$LOGFILE 2>&1
	echo -ne "\e[33m \nEnabling visibility of (.)dot files... \e[0m" | tee -a $LOGFILE

	# Check if already settings
	dotfiles_check=$(run_protontricks -c 'WINEDEBUG=-all wine reg query "HKEY_CURRENT_USER\Software\Wine" /v ShowDotFiles' $APPID 2>/dev/null | grep ShowDotFiles | awk '{gsub(/\r/,""); print $NF}')

	printf '%s\n' "$dotfiles_check" >>$LOGFILE 2>&1

	if [[ "$dotfiles_check" = "Y" ]]; then
		printf '%s\n' "DotFiles already enabled... skipping" | tee -a $LOGFILE
	else

		if run_protontricks -c 'WINEDEBUG=-all wine reg add "HKEY_CURRENT_USER\Software\Wine" /v ShowDotFiles /d Y /f' $APPID 2>/dev/null; then
			echo "Done!" >>$LOGFILE 2>&1
		else
			echo -e "\e[31mError: Failed to enable dot files visibility.\e[0m" | tee -a $LOGFILE
			exit 1
		fi
	fi

}

##############################
# Download WebView Installer #
##############################

webview_installer() {
    echo -e "\e[33m\nDownloading WebView Installer...\e[0m"

    local installer_path="$application_directory/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"
    local download_url="https://node10.sokloud.com/filebrowser/api/public/dl/yqVTbUT8/rwatch/WebView/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe"

    # Check if installer already exists
    if [ -f "$installer_path" ]; then
        echo "WebView Installer already exists, skipping download."
        return 0
    fi

    # Check for wget and use it if available
    if command -v wget &>/dev/null; then
        if wget "$download_url" -O "$installer_path" >>"$LOGFILE" 2>&1; then
            echo "Download completed successfully."
            return 0
        else
            echo -e "\e[31mError: Failed to download WebView Installer with wget.\e[0m"
            return 1
        fi
    # Check for curl and use it if wget is not available
    elif command -v curl &>/dev/null; then
        if curl -sLo "$installer_path" "$download_url" >>"$LOGFILE" 2>&1; then
            echo "Download completed successfully."
            return 0
        else
            echo -e "\e[31mError: Failed to download WebView Installer with curl.\e[0m"
            return 1
        fi
    else
        echo -e "\e[31mError: Neither wget nor curl is available. Cannot download WebView Installer.\e[0m"
        return 1
    fi
}

####################
# Configure Prefix #
####################

configure_prefix() {
    echo -e "\e[33m\nChanging the default renderer used..\e[0m" | tee -a "$LOGFILE"
    if run_protontricks "$APPID" settings renderer=vulkan >>"$LOGFILE" 2>&1; then
        echo "Renderer changed to Vulkan." >>"$LOGFILE" 2>&1
    else
        echo -e "\e[31mError: Failed to change renderer.\e[0m" | tee -a "$LOGFILE"
        exit 1
    fi

    # Copy in place win10 based system.reg
    echo -e "\e[33m\nChange the default prefix version to win10..\e[0m" | tee -a "$LOGFILE"
    local system_reg_win10_url="https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/system.reg.win10"
    local system_reg_win10_path="$compat_data_path/pfx/system.reg"

    if command -v wget &>/dev/null; then
        wget "$system_reg_win10_url" -O "$system_reg_win10_path" >>"$LOGFILE" 2>&1
    elif command -v curl &>/dev/null; then
        curl -sLo "$system_reg_win10_path" "$system_reg_win10_url" >>"$LOGFILE" 2>&1
    else
        echo -e "\e[31mError: Neither wget nor curl is available. Cannot download system.reg.win10.\e[0m" | tee -a "$LOGFILE"
        exit 1
    fi
    echo "Prefix version changed to win10." >>"$LOGFILE" 2>&1

    # Install WebView
    echo -e "\e[33m\nInstalling Webview, this can take a while, please be patient..\e[0m" | tee -a "$LOGFILE"
    if [ "$which_protontricks" = "flatpak" ]; then
        /usr/bin/flatpak run --command=protontricks-launch com.github.Matoking.protontricks --appid "$APPID" "$application_directory/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe" /silent /install >>"$LOGFILE" 2>&1
    else
        protontricks-launch --appid "$APPID" "$application_directory/MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe" /silent /install >>"$LOGFILE" 2>&1
    fi

    # Copy in place WebP .dll
    echo -e "\e[33m\nConfiguring WebP..\e[0m" | tee -a "$LOGFILE"
    local webp_32_url="https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/WebpWICCodec.dll-32"
    local webp_64_url="https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/WebpWICCodec.dll-64"
    local webp_32_path="$compat_data_path/pfx/drive_c/Program Files (x86)/WebP Codec/WebpWICCodec.dll"
    local webp_64_path="$compat_data_path/pfx/drive_c/Program Files/WebP Codec/WebpWICCodec.dll"

    if mkdir -p "$compat_data_path/pfx/drive_c/Program Files (x86)/WebP Codec" && mkdir -p "$compat_data_path/pfx/drive_c/Program Files/WebP Codec"; then
        if command -v wget &>/dev/null; then
            wget "$webp_32_url" -O "$webp_32_path" >>"$LOGFILE" 2>&1 && wget "$webp_64_url" -O "$webp_64_path" >>"$LOGFILE" 2>&1
        elif command -v curl &>/dev/null; then
            curl -sLo "$webp_32_path" "$webp_32_url" >>"$LOGFILE" 2>&1 && curl -sLo "$webp_64_path" "$webp_64_url" >>"$LOGFILE" 2>&1
        else
            echo -e "\e[31mError: Neither wget nor curl is available. Cannot download WebP dlls.\e[0m" | tee -a "$LOGFILE"
            exit 1
        fi
        echo "WebP configured successfully." | tee -a "$LOGFILE"
    else
        echo -e "\e[31mError: Failed to configure WebP.\e[0m" | tee -a "$LOGFILE"
        exit 1
    fi

    # Backup system.reg and user.reg
    cp "$compat_data_path/pfx/system.reg" "$compat_data_path/pfx/system.reg.orig"
    cp "$compat_data_path/pfx/user.reg" "$compat_data_path/pfx/user.reg.orig"

    # Copy in system.reg and user.reg
    echo -e "\e[33m\nConfiguring Registry..\e[0m" | tee -a "$LOGFILE"
    local system_reg_url="https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/system.reg.github"
    local user_reg_url="https://github.com/Omni-guides/Wabbajack-Modlist-Linux/raw/refs/heads/main/files/user.reg.github"
    local system_reg_path="$compat_data_path/pfx/system.reg"
    local user_reg_path="$compat_data_path/pfx/user.reg"

    if command -v wget &>/dev/null; then
        wget "$system_reg_url" -O "$system_reg_path" >>"$LOGFILE" 2>&1 && wget "$user_reg_url" -O "$user_reg_path" >>"$LOGFILE" 2>&1
    elif command -v curl &>/dev/null; then
        curl -sLo "$system_reg_path" "$system_reg_url" >>"$LOGFILE" 2>&1 && curl -sLo "$user_reg_path" "$user_reg_url" >>"$LOGFILE" 2>&1
    else
        echo -e "\e[31mError: Neither wget nor curl is available. Cannot download registry files.\e[0m" | tee -a "$LOGFILE"
        exit 1
    fi
    echo "Registry configured successfully." | tee -a "$LOGFILE"
}

#################################
# Detect and Link Steam Library #
#################################

detect_link_steam_library() {
	local steam_library_paths=()
	local chosen_library=""
	local libraryfolders_vdf=""

	echo -e "\e[33m\nDiscovering Steam libraries..\e[0m"

	# Find libraryfolders.vdf and extract library paths
	if [[ -f "$HOME/.steam/steam/steamapps/libraryfolders.vdf" ]]; then
		libraryfolders_vdf="$HOME/.steam/steam/steamapps/libraryfolders.vdf"
	elif [[ -f "$HOME/.local/share/Steam/steamapps/libraryfolders.vdf" ]]; then
		libraryfolders_vdf="$HOME/.local/share/Steam/steamapps/libraryfolders.vdf"
	elif [[ -f "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf" ]]; then
		libraryfolders_vdf="$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/libraryfolders.vdf"
	else
		echo -e "\e[31m\nSteam libraryfolders.vdf not found. Please check the installation.\e[0m" | tee -a "$LOGFILE"
		read -e -p "Enter the path to your main Steam directory: " steam_library_path
		while true; do
			if [[ ! -d "$steam_library_path" ]]; then
				echo -e "\e[31m\nInvalid path.\e[0m Please enter a valid directory." | tee -a "$LOGFILE"
			elif [[ ! -f "$steam_library_path/steamapps/libraryfolders.vdf" ]]; then
				echo -e "\e[31m\nThe specified path does not appear to be a Steam directory. Please check the path and try again. Do not enter the path for a secondary Steam Library, only the path for your actual Steam install.\e[0m" | tee -a "$LOGFILE"
			else
				read -p "Confirm using '$steam_library_path' as the Steam directory path? (y/n): " -r choice
				if [[ "$choice" =~ ^[Yy]$ ]]; then
					libraryfolders_vdf="$steam_library_path/steamapps/libraryfolders.vdf"
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
				steam_library_paths+=("$path")
			fi
		done < <(grep "\"path\"" "$libraryfolders_vdf")

		if [[ ${#steam_library_paths[@]} -gt 0 ]]; then
			# Use the first library path found as the chosen library
			chosen_library="${steam_library_paths[0]}"
			echo "Steam library found at: $chosen_library" >>"$LOGFILE" 2>&1
			configure_steam_libraries || {
				echo -e "\e[31m\nFailed to configure Steam libraries. Exiting.\e[0m" | tee -a "$LOGFILE"
				exit 1
			}
		else
			echo -e "\e[31m\nNo Steam library paths found in libraryfolders.vdf.\e[0m" | tee -a "$LOGFILE"
			exit 1
		fi
	else
		echo -e "\e[31m\nSteam library not found. Please check the installation.\e[0m" | tee -a "$LOGFILE"
		exit 1
	fi
}

configure_steam_libraries() {
	echo -e "\e[33m\nConfiguring Steam libraries..\e[0m"

	# Make directories
	steam_config_directory="$chosen_library/steamapps/compatdata/$APPID/pfx/drive_c/Program Files (x86)/Steam/config"
	echo -e "Creating directory $steam_config_directory" >>$LOGFILE 2>&1
	mkdir -p "$steam_config_directory" || {
		echo -e "\e[31m\nFailed to create directory $steam_config_directory. Exiting.\e[0m" | tee -a $LOGFILE
		exit 1
	}

	# Copy or symlink libraryfolders.vdf to config directory
	if [[ "$chosen_library" == "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" ]]; then
		steam_is_flatpak=1
		# For Flatpak Steam, adjust the paths accordingly
		echo -e "Symlinking libraryfolders.vdf to config directory for Flatpak" >>$LOGFILE 2>&1
		ln -s "$chosen_library/config/libraryfolders.vdf" "$steam_config_directory/libraryfolders.vdf" >>$LOGFILE 2>&1 || {
			echo -e "\e[31m\nFailed to symlink libraryfolders.vdf (Flatpak Steam).\e[0m" >>$LOGFILE 2>&1 | tee -a $LOGFILE
		}
	else
		echo -e "Symlinking libraryfolders.vdf to config directory" >>$LOGFILE 2>&1
		ln -s "$chosen_library/config/libraryfolders.vdf" "$steam_config_directory/libraryfolders.vdf" >>$LOGFILE 2>&1 || {
			echo -e "\e[31m\nFailed to symlink libraryfolders.vdf.\e[0m" >>$LOGFILE 2>&1 | tee -a $LOGFILE
		}
	fi

	mv "$chosen_library/steamapps/compatdata/$APPID/pfx/drive_c/Program Files (x86)/Steam/steamapps/libraryfolders.vdf" \
		"$chosen_library/steamapps/compatdata/$APPID/pfx/drive_c/Program Files (x86)/Steam/steamapps/libraryfolders.vdf.bak" >>$LOGFILE 2>&1 || {
		echo -e "\e[31m\nFailed to backup libraryfolders.vdf.\e[0m" >>$LOGFILE 2>&1
	}
}

##########################################
# Create dotnet_bundle_extract directory #
##########################################

create_dotnet_cache_dir() {
    local user_name=$(whoami)
    local cache_dir="$application_directory/home/$user_name/.cache/dotnet_bundle_extract"

    # Check if the directory already exists
    if [ -d "$cache_dir" ]; then
        echo "Directory already exists: $cache_dir, skipping..." >>"$LOGFILE" 2>&1
        return 0
    fi

    # Create the directory
    mkdir -p "$cache_dir"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create directory: $cache_dir" >&2
        exit 1
    fi

    echo "Directory successfully created: $cache_dir" >>"$LOGFILE" 2>&1
}

##########################
# Cleanup Wine Processes #
##########################

cleanup_wine_procs() {

	# Find and kill processes containing "WabbajackProton.exe" or "renderer"
	processes=$(pgrep -f "WabbajackProton.exe|renderer=vulkan|win7|win10|ShowDotFiles|MicrosoftEdgeWebView2RuntimeInstallerX64-WabbajackProton.exe")
	if [[ -n "$processes" ]]; then
		echo "$processes" | xargs -r kill -9
		echo "Processes killed successfully." >>$LOGFILE 2>&1
	else
		echo "No matching wine processes found." >>$LOGFILE 2>&1
	fi

}

#####################
# Exit more cleanly #
#####################

cleaner_exit() {

	if [[ "$steamdeck" != "1" ]]; then
		if [ -f /usr/binwineserver ]; then
			wineserver -k
			exit 1
		else
			exit 1
		fi
	else
		exit 1
	fi

}

####################
# END OF FUNCTIONS #
####################

#######################
# Note Script Version #
#######################

echo -e "Script Version $script_ver" >>$LOGFILE 2>&1

######################
# Note Date and Time #
######################

echo -e "Script started at: $(date +'%Y-%m-%d %H:%M:%S')" >>$LOGFILE 2>&1

#########################################
# pre-emptively clean up wine processes #
#########################################

cleanup_wine_procs

#############################
# Detect if running on deck #
#############################

detect_steamdeck

###########################################
# Detect Protontricks (flatpak or native) #
###########################################

detect_protontricks

#############################
# Create protontricks alias #
#############################

protontricks_alias

###############################
# Detect Protontricks Version #
###############################

protontricks_version

##########################################
# Create protontricks alias in ~/.bashrc #
##########################################

protontricks_alias

###########################
# Get Wabbajack Directory #
###########################

get_wabbajack_path

###########################
# Set APPID and run steps #
###########################

set_appid

####################################
# Detect compatdata Directory Path #
####################################

detect_compatdata_path

#####################################################
# Set protontricks permissions on Modlist Directory #
#####################################################

set_protontricks_perms

#####################################
# Enable Visibility of (.)dot files #
#####################################

enable_dotfiles

##########################################
# Download and install WebView Installer #
##########################################

webview_installer

####################
# Configure Prefix #
####################

configure_prefix

#################################
# Detect and Link Steam Library #
#################################

detect_link_steam_library

##########################################
# Create dotnet_bundle_extract directory #
##########################################

create_dotnet_cache_dir

##########################
# Cleanup Wine Processes #
##########################

cleanup_wine_procs

########
# Exit #
########

echo -e "\e[32m\nSet up complete.\e[0m"

if [[ $steam_is_flatpak -eq 1 ]]; then
	echo -e "\e[33m\nFlatpak Steam is in use, you may need to add a permissions override so that Wabbajack can access the directories.\e[0m"
	echo -e "\e[33m\nFor example, if you wanted to install the modlist to /home/user/Games/Skyrim/Modlistname, then you would need to run something like:\e[0m"
	echo -e "\e[33m\nflatpak override --user com.valvesoftware.Steam --filesystem="/home/user/Games"\e[0m"
fi
cleaner_exit
