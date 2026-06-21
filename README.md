![Jackify Banner](assets/images/readme/Jackify_Github_Banner.png)

<div align="center">

[Wiki](https://github.com/Omni-guides/Jackify/wiki) | [Nexus](https://www.nexusmods.com/site/mods/1427) | [Download](https://www.nexusmods.com/site/mods/1427?tab=files) | [Wabbajack Discord](https://discord.gg/wabbajack) | [Jackify Issues](https://github.com/Omni-guides/Jackify/issues) | [Ko-fi](https://ko-fi.com/omni1)

</div>

---

# Jackify

Jackify is a Linux application for installing and configuring Wabbajack modlists on Linux and Steam Deck. It provides a complete end-to-end workflow (downloading, installing, Steam shortcut creation, Proton prefix setup, and post-install configuration) through both a GUI and a full-featured CLI.

## Features

- **Complete Modlist Workflow**: Install from scratch, configure a pre-downloaded modlist, or reconfigure an existing modlist already in Steam
- **Game Support**: Skyrim, Fallout 4, Fallout New Vegas, Oblivion, Starfield, Enderal, and more
- **Automated Steam Integration**: Steam shortcut creation with full Proton configuration
- **GUI and CLI**: Both interfaces provide identical functionality

## Disclaimer

**Jackify is a hobby project in early Alpha development. Use at your own risk.**

- **No Warranty**: This software is provided "as is" without any warranty or guarantee of functionality
- **Alpha Software**: Features may be incomplete, unstable, or change without notice
- **Best Effort Support**: Support is provided on a best-effort basis through community channels
- **Data Safety**: Always back up your important data before using Jackify
- **System Compatibility**: Functionality on your specific system is not guaranteed
- **A successful installation does not guarantee a working modlist**: Linux introduces hardware, driver, and system-specific variables that cannot be accounted for. If your modlist installs successfully but does not run correctly, seek help in [#unofficial-linux-help](https://discord.gg/wabbajack) on the Wabbajack Discord. Do not contact the modlist author unless they explicitly support Linux.
- **Not all modlists can be fully automated**: Some modlists (e.g. Fallout New Vegas lists) require manual steps that Jackify cannot automate (or I have not automated yet). Always check the Install Guide of the Modlist itself to see what could be needed.
- **Most Modlists are not officially supported on Linux**: Jackify makes a best effort to get modlists running, but compatibility is not guaranteed and will vary between modlists, hardware, and system configuration

## Requirements

- Linux system (most modern distributions will work)
- Steam installed and configured (**the Snap version of Steam is not supported**)
- **Protontricks** (required for modlist configuration)
  - See [Installing Additional Tools](https://github.com/Omni-guides/Jackify/wiki/Installing-Additional-Tools#installing-protontricks)
- **GE-Proton 10-14**: While other Proton versions may work, GE-Proton 10-14 is highly recommended for ENB compatibility
  - See [Installing Additional Tools](https://github.com/Omni-guides/Jackify/wiki/Installing-Additional-Tools#installing-ge-proton)
- **Nexus Mods account** (Premium required for fully automated downloads; Non-Premium supported with manual browser steps)
  - See the [User Guide](https://github.com/Omni-guides/Jackify/wiki/User-Guide) for full details on the options available
- **FUSE2 compatibility (libfuse.so.2) is required for AppImage execution**
- **IF YOU ARE USING an Ubuntu/Debian-based distro** (Ubuntu, Kubuntu, Linux Mint, Pop!_OS, Zorin OS, elementary OS, and others): Qt platform plugin library
  - `sudo apt install libxcb-cursor-dev`

## Installation Quick Start

1. Download the latest release from [Nexus Mods](https://www.nexusmods.com/site/mods/1427?tab=files)
2. Extract the AppImage from the 7z archive
3. Make it executable and run:

```bash
chmod +x Jackify.AppImage
./Jackify.AppImage
```

For CLI mode: `./Jackify.AppImage --cli`

To verify your download, each release includes a `SHA256SUMS` file on the [GitHub releases page](https://github.com/Omni-guides/Jackify/releases/latest). Download it into the same folder as the AppImage, then run:

```bash
sha256sum -c SHA256SUMS
```

You should see `Jackify.AppImage: OK`. If you see a failure, do not run the file.

For a full step-by-step guide with screenshots, see the [User Guide](https://github.com/Omni-guides/Jackify/wiki/User-Guide).

## Supported Games

- Skyrim Special Edition
- Fallout 4
- Fallout New Vegas
- Oblivion
- Starfield
- Enderal
- Other games (Cyberpunk 2077, Baldur's Gate 3, and more): download and install support only for now; full automation coming in the future

## Architecture

Jackify follows a clean separation between frontend and backend:

- **Backend Services**: Pure business logic with no UI dependencies
- **Frontend Interfaces**: CLI and GUI implementations sharing the same backend
- **Native Engine**: Powered by jackify-engine (custom fork of wabbajack-cli) for optimal Linux performance and compatibility. Texconv for hash-matched texture conversion requires Proton.
- **Steam Integration**: Direct Steam shortcuts.vdf manipulation for shortcut creation and management

All Jackify relted files and configuration data is are stored in `~/Jackify/` and `~/.config/jackify/`.

## Contributing

At this early stage of development, I'd prefer GitHub Issues for bug reports and suggestions rather than PRs. This will likely change as the project matures. See the CONTRIBUTING document for more details.

## Future Plans (not guaranteed)

- Continue to expand supported games for fully automated configuration
- GUI refinements
- Dark/Light theme support

## Legacy Guides

The original bash scripts and step-by-step manual installation guides are preserved in the [Legacy Guides](https://github.com/Omni-guides/Jackify/wiki/Legacy-Wiki-Home) for those who prefer them or need a fallback.

## License

This project is licensed under the GPLv3 License. See the LICENSE file for details.

## Support

- **Bugs and feature requests**: [GitHub Issues](https://github.com/Omni-guides/Jackify/issues)
- **Documentation**: [Wiki](https://github.com/Omni-guides/Jackify/wiki)
- **Community**: [#unofficial-linux-help](https://discord.gg/wabbajack) on the Wabbajack Discord

## Acknowledgments

- Wabbajack team for the modlist ecosystem and wabbajack-cli
- Linux and Steam Deck gaming communities
- Modlist authors for their tireless work

---

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/D1D8H8WBD)
