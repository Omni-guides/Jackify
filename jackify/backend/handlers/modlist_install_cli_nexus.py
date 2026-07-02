"""Nexus and engine methods for ModlistInstallCLI (Mixin)."""
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from jackify.shared.colors import COLOR_ERROR, COLOR_INFO, COLOR_RESET

logger = logging.getLogger(__name__)


class ModlistInstallCLINexusMixin:
    """Mixin providing Nexus API and engine methods."""

    def _get_nexus_api_key(self) -> Optional[str]:
        return self.context.get('nexus_api_key')

    def get_all_modlists_from_engine(self, game_type=None):
        """
        Call the Jackify engine with 'list-modlists' and return a list of modlist dicts.
        Each dict should have at least 'id', 'game', 'download_size', 'install_size', 'total_size', and status flags.
        
        Args:
            game_type (str, optional): Filter by game type (e.g., "Skyrim", "Fallout New Vegas")
        """
        from .modlist_install_cli import get_jackify_engine_path

        engine_executable = get_jackify_engine_path()
        engine_dir = os.path.dirname(engine_executable)
        if not os.path.exists(engine_executable):
            print(f"{COLOR_ERROR}Error: jackify-install-engine not found at expected location.{COLOR_RESET}")
            print(f"{COLOR_INFO}Expected: {engine_executable}{COLOR_RESET}")
            return []
        env = os.environ.copy()
        env["DOTNET_SYSTEM_GLOBALIZATION_INVARIANT"] = "1"
        command = [engine_executable, 'list-modlists', '--show-all-sizes', '--show-machine-url']
        
        # Add game filter if specified
        if game_type:
            command.extend(['--game', game_type])
        try:
            result = subprocess.run(
                command,
                capture_output=True, text=True, check=True,
                env=env, cwd=engine_dir
            )
            lines = result.stdout.splitlines()
            modlists = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('Loading') or line.startswith('Loaded'):
                    continue
                
                # Parse the new format: [STATUS] Modlist Name - Game - Download|Install|Total - MachineURL
                # STATUS indicators: [DOWN], [NSFW], or both [DOWN] [NSFW]
                
                # Extract status indicators
                status_down = '[DOWN]' in line
                status_nsfw = '[NSFW]' in line
                
                # Remove status indicators to get clean line
                clean_line = line.replace('[DOWN]', '').replace('[NSFW]', '').strip()
                
                # Split from right to handle modlist names with dashes
                # Format: "NAME - GAME - SIZES - MACHINE_URL"
                parts = clean_line.rsplit(' - ', 3)  # Split from right, max 3 splits = 4 parts
                if len(parts) != 4:
                    continue  # Skip malformed lines
                
                modlist_name = parts[0].strip()
                game_name = parts[1].strip()
                sizes_str = parts[2].strip()
                machine_url = parts[3].strip()
                
                # Parse sizes: "Download|Install|Total" (e.g., "203GB|130GB|333GB")
                size_parts = sizes_str.split('|')
                if len(size_parts) != 3:
                    continue  # Skip if sizes don't match expected format
                
                download_size = size_parts[0].strip()
                install_size = size_parts[1].strip()
                total_size = size_parts[2].strip()
                
                # Skip if any required data is missing
                if not modlist_name or not game_name or not machine_url:
                    continue
                
                modlists.append({
                    'id': modlist_name,  # Use modlist name as ID for compatibility
                    'name': modlist_name,
                    'game': game_name,
                    'download_size': download_size,
                    'install_size': install_size, 
                    'total_size': total_size,
                    'machine_url': machine_url,  # Store machine URL for installation
                    'status_down': status_down,
                    'status_nsfw': status_nsfw
                })
            return modlists
        except subprocess.CalledProcessError as e:
            self.logger.error(f"list-modlists failed. Code: {e.returncode}")
            if e.stdout: self.logger.error(f"Engine stdout:\n{e.stdout}")
            if e.stderr: self.logger.error(f"Engine stderr:\n{e.stderr}")
            print(f"{COLOR_ERROR}Failed to fetch modlist list. Engine error (Code: {e.returncode}).{COLOR_ERROR}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching modlists: {e}", exc_info=True)
            print(f"{COLOR_ERROR}Unexpected error fetching modlists: {e}{COLOR_ERROR}")
            return []

    def _enhance_nexus_error(self, line: str) -> str:
        """Enhance Nexus download error messages by adding the mod URL for easier troubleshooting."""
        from jackify.backend.utils.engine_error_parser import nexus_url_from_error_line
        url = nexus_url_from_error_line(line)
        if url:
            return f"{line}\n  Nexus URL: {url}"
        return line

