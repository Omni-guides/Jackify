# Jackify

**Native Linux modlist installer and manager for Wabbajack modlists**

Jackify enables seamless installation and configuration of Wabbajack modlists on Linux systems, providing automated Steam integration and Proton prefix management without requiring Windows dependencies.

## Features

- **Native Linux Support**: Pure Linux implementation with no Wine/Windows dependencies for core operations
- **Automated Steam Integration**: Automatic Steam shortcut creation with proper Proton configuration
- **Comprehensive Modlist Support**: Support for Skyrim, Fallout 4, Fallout New Vegas, Oblivion, Starfield, and more
- **Professional Interface**: Both CLI and GUI interfaces with enhanced modlist selection and metadata display
- **Steam Deck Optimized**: Full Steam Deck support with controller-friendly interface
- **Advanced Filtering**: Smart categorization with NSFW filtering and game-specific organization

## Quick Start

### Requirements

- Linux system (Steam Deck supported)
- Steam installed and configured
- Python 3.8+ (for source installation)

### Installation

#### AppImage (Recommended)
```bash
# Download latest release
wget https://github.com/your-repo/jackify/releases/latest/jackify.AppImage
chmod +x jackify.AppImage
./jackify.AppImage
```

#### From Source
```bash
git clone https://github.com/your-repo/jackify.git
cd jackify/src
pip install -r requirements.txt
python -m jackify.frontends.gui  # GUI mode
python -m jackify.frontends.cli  # CLI mode
```

## Usage

### GUI Mode
Launch the GUI and navigate through the intuitive interface:
1. Select "Modlist Tasks" → "Install a Modlist"
2. Choose your game type and modlist
3. Configure installation and download directories
4. Enter your Nexus API key
5. Let Jackify handle the rest

### CLI Mode
```bash
python -m jackify.frontends.cli
```
Follow the interactive prompts to configure and install modlists.

## Supported Games

- **Skyrim Special Edition** (88+ modlists)
- **Fallout 4** (22+ modlists)
- **Fallout New Vegas** (13+ modlists)
- **Oblivion**
- **Starfield**
- **Enderal**
- **Other Games** (Cyberpunk 2077, Baldur's Gate 3, and more)

## Architecture

Jackify follows a clean separation between frontend and backend:

- **Backend Services**: Pure business logic with no UI dependencies
- **Frontend Interfaces**: CLI and GUI implementations using shared backend
- **Native Engine**: Powered by jackify-engine for optimal performance
- **Steam Integration**: Direct Steam shortcuts.vdf manipulation

## Configuration

Configuration files are stored in:
- **Linux**: `~/.config/jackify/`
- **Steam Deck**: `~/.config/jackify/`

## Development

### Building from Source
```bash
cd src
pip install -r requirements-packaging.txt
pyinstaller jackify.spec
```

### Running Tests
```bash
python -m pytest tests/
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests for any improvements.

## Support

- **Issues**: Report bugs and request features via GitHub Issues
- **Documentation**: See the Wiki for detailed guides
- **Community**: Join our community discussions

## Acknowledgments

- Wabbajack team for the modlist ecosystem
- jackify-engine developers
- Steam Deck and Linux gaming community

---

**Jackify** - Bringing professional modlist management to Linux