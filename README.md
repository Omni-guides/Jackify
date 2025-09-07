# Jackify
A modlist installer and manager for Wabbajack modlists on Linux

Jackify enables seamless installation and configuration of Wabbajack modlists on Linux systems, providing automated Steam shortcut creation and Proton prefix configuration.

## Introduction
Thank you for your interest in Jackify - the next step, and a giant leap forward from my automated Wabbajack and modlist post-install scripts. So, Jackify - What is it?

Jackify is an almost Linux-native application written in Python, with a GUI produced with PySide6, and a full featured CLI interface if preferred. More info on the "almost" can be found in the full Introduction Wiki page. Currently, there are two main functions that Jackify will perform at this stage of development:

- Install Wabbajack modlists using jackify-engine (more on jackify-engine in the full Introduction wiki linked above).
- Fully automate the configuration of the Steam shortcut, modlist paths, prefix components, launch options and various other tweaks required to run Wabbajack Modlists on Linux.
- With both of the above combined, Jackify provides an end-to-end modlist installation and configuration process, automatically.

## Features
- Linux-First Python Application: Designed specifically for Linux with minimal external dependencies
- Complete Modlist Workflow: Install from scratch, configure pre-downloaded modlists, or reconfigure existing modlists installations in Steam
- Comprehensive Modlist Support: Support for Skyrim, Fallout 4, Fallout New Vegas, Oblivion, Starfield, Enderal and more
- Automated Steam Integration: Automatic Steam shortcut creation with complete Proton configuration
- Professional Interface: Both GUI and CLI interfaces with identical features

## Quick Start

### Requirements

#### For AppImage (Recommended)
- Linux system (Most modern distributions supported)
- Steam installed and configured, Proton Experimental available
- Python 3.10+ (built for Ubuntu 22.04 LTS compatibility)

#### For Source Installation
- Linux system (Most modern distributions supported)
- Steam installed and configured, Proton Experimental available
- Python 3.8+ (for source installation)

### Installation

#### Recommended: Download AppImage (Easy!)
```bash
# Download latest release
wget https://github.com/your-repo/jackify/releases/latest/Jackify.AppImage
chmod +x Jackify.AppImage
./Jackify.AppImage
```

#### Advanced: From Source (Not Recommended)
Note: We strongly recommend using the AppImage above. Source installation is for developers only.

```bash
git clone https://github.com/your-repo/jackify.git
cd jackify/src
pip install -r requirements.txt
python -m jackify.frontends.gui  # GUI mode
python -m jackify.frontends.cli  # CLI mode
```

## Usage

### GUI Mode
Launch the GUI AppImage as above, then navigate through the interface:

1. Select "Modlist Tasks" → "Install a Modlist" (or your desired option)
2. Choose your game type and modlist
3. Set the installation and download directories
4. Enter your Nexus API key and select your resolution
5. Let Jackify handle the rest

### CLI Mode
```bash
./Jackify.AppImage --cli
```
Follow the interactive prompts to configure and install modlists.

## Supported Games
- Skyrim Special Edition
- Fallout 4
- Fallout New Vegas
- Oblivion
- Starfield
- Enderal
- Other Games (Cyberpunk 2077, Baldur's Gate 3, and more - Download and Install only for now)

## Architecture
Jackify follows a clean separation between frontend and backend:

- Backend Services: Pure business logic with no UI dependencies
- Frontend Interfaces: CLI and GUI implementations using shared backend
- Native Engine: Powered by jackify-engine (custom fork of wabbajack-cli.exe) for optimal performance and compatibility
- Steam Integration: Direct Steam shortcuts.vdf manipulation for creating and modifying Steam shortcuts

## Configuration
Configuration files are stored in:

- Jackify Related: ~/Jackify/
- jackify-engine config: ~/.config/jackify/

## Development
Development and contribution guidelines coming soon.

## License
This project is licensed under the GPLv3 License - see the LICENSE file for details.

## Contributing
At this early stage of development, where basic functionality is the primary focus, I'd prefer to use GitHub Issues to suggest improvements, rather tha PRs. This will likely change in the future.

## Support
- Issues: Report bugs and request features via GitHub Issues
- Documentation: See the Wiki for detailed guides
- Community: Join the community in the #unofficial-linux-help channel of the Official Wabbajack discord server - https://discord.gg/wabbajack

## Acknowledgments
- Wabbajack team for the modlist ecosystem, and wabbajack-cli.exe
- Linux and Steam Deck gaming communities
- Modlist Authors for their tireless effort in creating modlists in the first place

---

**Jackify** - Bringing Wabbajack modlist management to Linux