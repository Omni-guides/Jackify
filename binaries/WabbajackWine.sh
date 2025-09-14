#!/usr/bin/env bash
#
##############################################################
#                                                            #
# Attempt to automate installing Wabbajack on Linux via Wine #
#                                                            #
#            Alpha v0.13 - Omni, from 08/02/25               #
#                                                            #
##############################################################

# - v0.01 - Initial script structure.
# - v0.02 - Added function for detecting the wine version.
# - v0.02 - Added function for setting Wabbajack directry path.
# - v0.02 - Added function for setting wine prefix path.
# - v0.02 - Added function to create the Wabbajack directory and wine prefix.
# - v0.03 - Added function to download required .exe files.
# - v0.03 - Added function to install and configure WebView and set up Wabbajack Application entry.
# - v0.04 - Added function to try to detect the Steam library.
# - v0.04 - Added function to create a Desktop item.
# - v0.04 - Added function to ask if Wabbajack should be started now.
# - v0.05 - Tweak to wine version comparison removing the requirement for 'bc'.
# - v0.06 - Remove references to $HOME for downloading and installing WebView.
# - v0.07 - Added capture of spaces in provided directory name - unsupported.
# - v0.08 - Added colouring to the text output to better distinguish questions, warnings and informationals.
# - v0.09 - Reworked the steam library detection to include confirmation if library detected, user defined path as desired.
# - v0.10 - Completely replace Steam Library symlink with modified copy of libraryfolders.vdf - this should handle all Steam Libraries, and not just the default library
# - v0.11 - create a dotnet_bundle_extract directory which seems required on some distros (harmless on others)
# - v0.12 - Fixed incorrect path in Desktop Shortcut creation (thanks valkari)
# - v0.13 - Modified Wine Version detection so that Wine 10 as well as future versions should be handled correctly.

# Current Script Version (alpha)
script_ver=0.13

# Today's date
date=$(date +"%d%m%y")

# Set up and blank logs
LOGFILE=$HOME/wabbajack-via-wine-sh.log
echo "" >$HOME/wabbajack-via-wine-sh.log
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
echo -e "Wabbajack running on Linux. Please be aware that stability of the Wabbajack application is not guaranteed."
echo -e "Please use at your own risk and accept that in the worst case, you may have to re-run this script to "
echo -e "create a new prefix for WabbaJack. You can report back to me via GitHub or the Official Wabbajack Discord"
echo -e "if you discover an issue with this script. Any other feedback, positive or negative, is also most welcome."

echo -e "\e[32m\nPress any key to continue...\e[0m"
echo
read -n 1 -s -r -p ""

#############
# Functions #
#############

######################################
# Detect Wine and winetricks version #
######################################

detect_wine_version() {
    # Which version of wine is installed?
    wine_binary=$(which wine)
    echo -e "Wine Binary Path: $wine_binary" >>$LOGFILE 2>&1

    # Extract the Wine version numbers
    wine_version=$(wine --version | grep -oE '[0-9]+\.[0-9]+')
    echo -e "Wine Version: $wine_version" >>$LOGFILE 2>&1

    # Split major and minor version
    major_version=$(echo "$wine_version" | cut -d. -f1)
    minor_version=$(echo "$wine_version" | cut -d. -f2)

    # Convert to integers for proper numerical comparison
    if (( major_version < 9 )) || (( major_version == 9 && minor_version < 15 )); then
        echo -e "Wabbajack requires Wine newer than 9.15. Please arrange this on your system and rerun this script."
        exit 0
    else
        echo -e "Wine version $wine_version, should be fine" >>$LOGFILE 2>&1
    fi

    # Is winetricks installed?
    if [[ $(which winetricks) ]]; then
        echo -e "Winetricks found at: $(which winetricks)" >>$LOGFILE 2>&1
    else
        echo -e "Winetricks not detected. Please arrange this on your system and rerun this script."
        exit 0
    fi
}

###########################
# Get Wabbajack Directory #
###########################

get_wineprefix_and_application_directory() {
    local application_directory_prompt="Enter the path where you want to store your application directory: "

    while true; do
        # Prompt for the application directory
        read -e -p "$application_directory_prompt" application_directory
        echo

        # Check for spaces in the directory path
        if [[ $application_directory =~ " " ]]; then
            # Suggest an alternative path without spaces
            local suggested_path="${application_directory// /_}"
            echo -e "\e[31m\nWARNING:\e[0m Spaces in directory paths can cause compatibility issues with some applications."
            echo -e "\e[32m\nWould you like to use the following path instead: $suggested_path? (y/n)\e[0m"
            read -r confirm
            echo

            if [[ $confirm == "y" || $confirm == "Y" ]]; then
                application_directory="$suggested_path"
                break  # Break out of the outer loop
            elif [[ $confirm == "n" || $confirm == "N" ]]; then
                continue  # Loop back to the beginning
            else
                echo -e "\e[31m\nInvalid input.\e[0m Please enter 'y' or 'n'."
            fi
        fi

        # Confirm the application directory
        while true; do
            echo -e "\e[32m\nAre you sure you want to store the application directory in \"$application_directory\"? (y/n): \e[0m"
            read -r confirm
            echo

            if [[ $confirm == "y" || $confirm == "Y" ]]; then
                # Check for existing application directory and warn
                break 2 # Break out of both loops
            elif [[ $confirm == "n" || $confirm == "N" ]]; then
                break # Break out of the inner loop, continue the outer loop
            else
                echo -e "\e[31m\nInvalid input.\e[0m Please enter 'y' or 'n'."
            fi
        done
    done

    local wineprefix_prompt="Do you want to create the Wine prefix in the default location (\"$application_directory/.wine\")? (y/n): "

    # Ask about the default Wine prefix location
    read -e -p "$wineprefix_prompt" confirm

    if [[ $confirm == "y" || $confirm == "Y" ]]; then
        # Set the Wine prefix in the default location
        export wineprefix="$application_directory/.wine"
    else
        # Call the get_wineprefix function to get the custom Wine prefix
        set_wineprefix
    fi

    echo "Application Directory Path: $application_directory." >>$LOGFILE 2>&1
    echo "Wine Prefix Path: $wineprefix" >>$LOGFILE 2>&1
}

###################
# Set Wine Prefix #
###################

set_wineprefix() {

	local wineprefix_prompt="Enter the path where you want to store your Wine prefix: "

	while true; do
		# Prompt for the path, allowing tab completion
		read -e -p "$wineprefix_prompt" wineprefix
		echo

		# Confirm the path
		while true; do
			echo -e "\e[32m\nAre you sure you want to store the Wine prefix in \"$wineprefix\"? (y/n): \e[0m"
			read -r confirm
			echo

			if [[ $confirm == "y" || $confirm == "Y" ]]; then
				break
			elif [[ $confirm == "n" || $confirm == "N" ]]; then
				read -e -p "$wineprefix_prompt" wineprefix
			else
				echo -e "\e[31m\nInvalid input.\e[0m Please enter 'y' or 'n'."
			fi
		done

		# Check for existing .wine directory
		if [[ -d "$wineprefix/.wine" ]]; then
			echo -e "\e[31m\nWARNING:\e[0m This will overwrite any existing directory in \"$wineprefix/.wine\"."
			while true; do
				echo "Continue? (y/n): "
				read -r confirm
				echo

				if [[ $confirm == "y" || $confirm == "Y" ]]; then
					break
				elif [[ $confirm == "n" || $confirm == "N" ]]; then
					read -e -p "$wineprefix_prompt" wineprefix
				else
					echo -e "\e[31m\nInvalid input.\e[0m Please enter 'y' or 'n'."
				fi
			done
		else
			break
		fi
	done

	echo

	# Set the wineprefix variable
	export wineprefix

}

#########################################
# Create Wabbajack Directory and prefix #
#########################################

create_wine_environment() {
	# Create the application directory if it doesn't exist
	mkdir -p "$application_directory"

	# Check if the Wine prefix exists and delete it if necessary
	if [[ -d "$wineprefix" ]]; then
		rm -rf "$wineprefix"
	fi

	# Create the Wine prefix directory
	mkdir -p "$wineprefix"

	# Set the WINEPREFIX variable and run wineboot
	export WINEPREFIX="$wineprefix"
	#export WINEDLLOVERRIDES="mscoree=d;mshtml=d"
	wineboot >>$LOGFILE 2>&1
}

########################################################
# Download Webview Installer and Wabbajack Application #
########################################################

download_apps() {

  echo -e "\e[33m\nDownloading Wabbajack Application...\e[0m"

  # Check if Wabbajack.exe exists and skip download if so
  if ! [ -f "$application_directory/Wabbajack.exe" ]; then
    wget https://github.com/wabbajack-tools/wabbajack/releases/latest/download/Wabbajack.exe -O "$application_directory/Wabbajack.exe"
    # Set as executable
    chmod +x "$application_directory/Wabbajack.exe"
  else
    echo "Wabbajack.exe already exists, skipping download."
  fi

  echo -e "\e[33m\nDownloading WebView Installer...\e[0m"

  # Check if MicrosoftEdgeWebView2RuntimeInstallerX64.exe exists and skip download if so
  if ! [ -f "$application_directory/MicrosoftEdgeWebView2RuntimeInstallerX64.exe" ]; then
    wget https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/6d376ab4-4a07-4679-8918-e0dc3c0735c8/MicrosoftEdgeWebView2RuntimeInstallerX64.exe -O "$application_directory/MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
  else
    echo "MicrosoftEdgeWebView2RuntimeInstallerX64.exe already exists, skipping download."
  fi

}

############################################
# Install WebView, configure Wine settings #
############################################

install_and_configure() {

	# set based on distro? harware?...
	echo -e "\e[33m\nChanging the default renderer used..\e[0m" >>$LOGFILE 2>&1
	WINEPREFIX=$wineprefix winetricks renderer=vulkan >>$LOGFILE 2>&1

	# Install WebView
	echo -e "\e[33m\nInstalling Webview, this can take a while, please be patient..\e[0m" >>$LOGFILE 2>&1
	WINEPREFIX=$wineprefix wine $application_directory/MicrosoftEdgeWebView2RuntimeInstallerX64.exe >>$LOGFILE 2>&1

	# Change prefix version
	echo -e "\e[33m\nChange the default prefix version to win7..\e[0m" >>$LOGFILE 2>&1
	WINEPREFIX=$wineprefix winecfg -v win7 >>$LOGFILE 2>&1

	# Add Wabbajack as an application
	echo -e "\e[33m\nAdding Wabbajack Application to customise settings..\e[0m" >>$LOGFILE 2>&1
	cat <<EOF >$application_directory/WJApplication.reg
Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\Software\Wine\AppDefaults\Wabbajack.exe]
"Version"="win10"
EOF

	WINEPREFIX=$wineprefix wine regedit $application_directory/WJApplication.reg >>$LOGFILE 2>&1

	echo
}

#################################
# Detect and Link Steam Library #
#################################

detect_link_steam_library() {
    # Possible Steam library locations
    steam_library_locations=(
        "$HOME/.local/share/Steam"
        #"$HOME/.steam/steam/steamapps"
        "$HOME/Library/Application Support/Steam"
        "/opt/steam"
        "/usr/share/Steam"
        "/usr/local/share/Steam"
    )

    # Function to check if a directory is a Steam library
    is_steam_library() {
        local location="$1"

        if [[ -d "$location" ]]; then
            if find "$location/steamapps" -type f -name "libraryfolders.vdf" -print | grep -q "$location/steamapps/libraryfolders.vdf"; then
                return 0
            fi
        fi

        return 1
    }

    echo -e "\e[33mDiscovering Steam libraries..\e[0m"

    # Find the first valid Steam library location
    for location in "${steam_library_locations[@]}"; do
        if is_steam_library "$location"; then
            read -p "Found Steam install at '$location' Is this path correct for your Steam install? (y/n): " -r choice
            if [[ "$choice" =~ ^[Yy]$ ]]; then
                chosen_library="$location"
                break
            fi
        fi
    done

    # If no library was found or the user declined, ask for a custom path
    if [[ -z "$chosen_library" ]]; then
        read -e -p "Enter the path to your main Steam directory: " steam_library_path
        while true; do
            if [[ ! -d "$steam_library_path" ]]; then
                echo -e "\e[31m\nInvalid path.\e[0m Please enter a valid directory."
            elif ! is_steam_library "$steam_library_path"; then
                echo -e "\e[31m\nThe specified path does not appear to be a Steam directory. Please check the path and try again. Do not enter the path for a secondary Steam Library, only the path for your actual Steam install.\e[0m"
            else
                read -p "Confirm using '$steam_library_path' as the Steam directory path? (y/n): " -r choice
                if [[ "$choice" =~ ^[Yy]$ ]]; then
                    chosen_library="$steam_library_path"
                    break
                fi
            fi
            read -e -p "Enter the path to your Steam library: " steam_library_path
        done
    fi

    # If a valid library was found, print its location and create the symlink
    if [[ -n "$chosen_library" ]]; then
        echo "Steam library found at: $chosen_library" >>$LOGFILE 2>&1
        configure_steam_libraries
    else
        echo -e "\e[31m\nSteam library not found. Please check the installation.\e[0m"
    fi

}

configure_steam_libraries() {

# Make directories
#wineprefix=/home/deck/WJTest
steam_config_directory="$wineprefix/drive_c/Program Files (x86)/Steam/config"
echo -e "Creating directory $steam_config_directory" >>$LOGFILE 2>&1
mkdir -p "$steam_config_directory"

# copy real libraryfolders.vdf to config directory
echo -e "Copying libraryfolders.vdf to config directory" >>$LOGFILE 2>&1
cp  "$chosen_library/config/libraryfolders.vdf" "$steam_config_directory/."

# Edit this new libraryfolders.vdf file to convert linux path to Z:\ path with double backslashes

sed -E 's|("path"[[:space:]]+)"(/)|\1"Z:\\\\|; s|/|\\\\|g' "$steam_config_directory/libraryfolders.vdf" > "$steam_config_directory/libraryfolders2.vdf"
cp "$steam_config_directory/libraryfolders2.vdf" "$steam_config_directory/libraryfolders.vdf"
rm "$steam_config_directory/libraryfolders2.vdf"

}

##########################################
# Create dotnet_bundle_extract directory #
##########################################

create_dotnet_cache_dir() {
  local user_name=$(whoami)
  local cache_dir="$application_directory/home/$user_name/.cache/dotnet_bundle_extract"

  mkdir -p "$cache_dir"
}

############################
# Create Desktop Shortcut? #
############################

create_desktop_shortcut() {
	echo -e "\e[32m\nDo you want to create a desktop shortcut for Wabbajack? (y/n):\e[0m"
	read -r create_shortcut

	if [[ $create_shortcut == "y" || $create_shortcut == "Y" ]]; then
		desktop_file="$HOME/Desktop/Wabbajack.desktop"
		cat >"$desktop_file" <<EOF
[Desktop Entry]
Name=Wabbajack
Exec=env HOME="$HOME" WINEPREFIX=$wineprefix wine $application_directory/Wabbajack.exe
Type=Application
StartupNotify=true
Path=$application_directory
Icon=$application_directory/Wabbajack.ico
EOF
		chmod +x "$desktop_file"
		echo -e "\e[33m\nDesktop shortcut created at $desktop_file\e[0m"
		#Grab an icon for it
		wget -q -O $application_directory/Wabbajack.ico https://raw.githubusercontent.com/wabbajack-tools/wabbajack/main/Wabbajack.Launcher/Assets/wabbajack.ico
	fi

}

####################
# Start Wabbajack? #
####################

start_wabbajack() {

	echo -e "\e[32m\nDo you want to start Wabbajack now? (y/n):\e[0m"
	read -r start_wabbajack

	if [[ $start_wabbajack == "y" || $start_wabbajack == "Y" ]]; then
		# Run Wabbajack
		echo -e "\e[33m\nStarting Wabbajack...\e[0m"
		cd $application_directory
		WINEPREFIX=$wineprefix WINEDEBUG=-all wine $application_directory/Wabbajack.exe >>$LOGFILE 2>&1
	fi
}

#####################
# Run the Functions #
#####################

# Detect Wine and winetricks version
detect_wine_version

# Get Wabbajack Directory
get_wineprefix_and_application_directory

# Create Wabbajack Directory
create_wine_environment

# Download Webview Installer and Wabbajack Application
download_apps

# Install WebView, configure Wine settings
install_and_configure

# Detect and Link Steam Library
detect_link_steam_library

# Create dotnet_bundle_extract directory
create_dotnet_cache_dir

# Create Desktop Shortcut?
create_desktop_shortcut

# Start Wabbajack?
start_wabbajack

echo -e "\e[32m\nSet up complete.\e[0m"

exit
