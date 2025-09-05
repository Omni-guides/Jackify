"""
Tuxborn Command

CLI command for the Tuxborn Automatic Installer.
Extracted from the original jackify-cli.py.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional

# Import the backend services we'll need
from jackify.backend.models.modlist import ModlistContext
from jackify.shared.colors import COLOR_INFO, COLOR_ERROR, COLOR_RESET

logger = logging.getLogger(__name__)


class TuxbornCommand:
    """Handler for the tuxborn-auto CLI command."""
    
    def __init__(self, backend_services, system_info):
        """Initialize with backend services.
        
        Args:
            backend_services: Dictionary of backend service instances
            system_info: System information (steamdeck flag, etc.)
        """
        self.backend_services = backend_services
        self.system_info = system_info
    
    def add_args(self, parser):
        """Add tuxborn-auto arguments to the main parser.
        
        Args:
            parser: The main ArgumentParser
        """
        parser.add_argument(
            "--tuxborn-auto", 
            action="store_true", 
            help="Run the Tuxborn Automatic Installer non-interactively (for GUI integration)"
        )
        parser.add_argument(
            "--install-dir", 
            type=str, 
            help="Install directory for Tuxborn (required with --tuxborn-auto)"
        )
        parser.add_argument(
            "--download-dir", 
            type=str, 
            help="Downloads directory for Tuxborn (required with --tuxborn-auto)"
        )
        parser.add_argument(
            "--modlist-name", 
            type=str, 
            default="Tuxborn", 
            help="Modlist name (optional, defaults to 'Tuxborn')"
        )
    
    def execute(self, args) -> int:
        """Execute the tuxborn-auto command.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        logger.info("Starting Tuxborn Automatic Installer (GUI integration mode)")
        
        try:
            # Set up logging redirection (copied from original)
            self._setup_tee_logging()
            
            # Build context from args
            context = self._build_context_from_args(args)
            
            # Validate required fields
            if not self._validate_context(context):
                return 1
            
            # Use legacy implementation for now - will migrate to backend services later
            result = self._execute_legacy_tuxborn(context)
            
            logger.info("Finished Tuxborn Automatic Installer")
            return result
            
        except Exception as e:
            logger.error(f"Failed to run Tuxborn installer: {e}")
            print(f"{COLOR_ERROR}Tuxborn installation failed: {e}{COLOR_RESET}")
            return 1
        finally:
            # Restore stdout/stderr
            self._restore_stdout_stderr()
    
    def _build_context_from_args(self, args) -> dict:
        """Build context dictionary from command arguments.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Context dictionary
        """
        install_dir = getattr(args, 'install_dir', None)
        download_dir = getattr(args, 'download_dir', None)
        modlist_name = getattr(args, 'modlist_name', 'Tuxborn')
        machineid = 'Tuxborn/Tuxborn'
        
        # Try to get API key from saved config first, then environment variable
        from jackify.backend.services.api_key_service import APIKeyService
        api_key_service = APIKeyService()
        api_key = api_key_service.get_saved_api_key()
        if not api_key:
            api_key = os.environ.get('NEXUS_API_KEY')
        
        resolution = getattr(args, 'resolution', None)
        mo2_exe_path = getattr(args, 'mo2_exe_path', None)
        skip_confirmation = True  # Always true in GUI mode
        
        context = {
            'machineid': machineid,
            'modlist_name': modlist_name,
            'install_dir': install_dir,
            'download_dir': download_dir,
            'nexus_api_key': api_key,
            'skip_confirmation': skip_confirmation,
            'resolution': resolution,
            'mo2_exe_path': mo2_exe_path,
        }
        
        # PATCH: Always set modlist_value and modlist_source for Tuxborn workflow
        context['modlist_value'] = 'Tuxborn/Tuxborn'
        context['modlist_source'] = 'identifier'
        
        return context
    
    def _validate_context(self, context: dict) -> bool:
        """Validate Tuxborn context.
        
        Args:
            context: Tuxborn context dictionary
            
        Returns:
            True if valid, False otherwise
        """
        required_keys = ['modlist_name', 'install_dir', 'download_dir', 'nexus_api_key']
        missing = [k for k in required_keys if not context.get(k)]
        
        if missing:
            print(f"{COLOR_ERROR}Missing required arguments for --tuxborn-auto.\\n"
                  f"--install-dir, --download-dir, and NEXUS_API_KEY (env, 32+ chars) are required.{COLOR_RESET}")
            return False
        
        return True
    
    def _setup_tee_logging(self):
        """Set up TEE logging (copied from original implementation)."""
        import shutil
        
        # TEE logging setup & log rotation (copied from original)
        class TeeStdout:
            def __init__(self, *files):
                self.files = files
            def write(self, data):
                for f in self.files:
                    f.write(data)
                    f.flush()
            def flush(self):
                for f in self.files:
                    f.flush()
        
        log_dir = Path.home() / "Jackify" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        workflow_log_path = log_dir / "tuxborn_workflow.log"
        
        # Log rotation: keep last 3 logs, 1KB each (for testing)
        max_logs = 3
        max_size = 1024  # 1KB for testing
        if workflow_log_path.exists() and workflow_log_path.stat().st_size > max_size:
            for i in range(max_logs, 0, -1):
                prev = log_dir / f"tuxborn_workflow.log.{i-1}" if i > 1 else workflow_log_path
                dest = log_dir / f"tuxborn_workflow.log.{i}"
                if prev.exists():
                    if dest.exists():
                        dest.unlink()
                    prev.rename(dest)
        
        self.workflow_log = open(workflow_log_path, 'a')
        self.orig_stdout, self.orig_stderr = sys.stdout, sys.stderr
        sys.stdout = TeeStdout(sys.stdout, self.workflow_log)
        sys.stderr = TeeStdout(sys.stderr, self.workflow_log)
    
    def _restore_stdout_stderr(self):
        """Restore original stdout/stderr."""
        if hasattr(self, 'orig_stdout'):
            sys.stdout = self.orig_stdout
            sys.stderr = self.orig_stderr
        if hasattr(self, 'workflow_log'):
            self.workflow_log.close()
    
    def _execute_legacy_tuxborn(self, context: dict) -> int:
        """Execute Tuxborn using legacy implementation.
        
        Args:
            context: Tuxborn context dictionary
            
        Returns:
            Exit code
        """
        # Import backend services
        from jackify.backend.core.modlist_operations import ModlistInstallCLI
        from jackify.backend.handlers.menu_handler import MenuHandler
        
        # Create legacy handler instances
        menu_handler = MenuHandler()
        modlist_cli = ModlistInstallCLI(
            menu_handler=menu_handler, 
            steamdeck=self.system_info.get('is_steamdeck', False)
        )
        
        confirmed_context = modlist_cli.run_discovery_phase(context_override=context)
        if confirmed_context:
            menu_handler.logger.info("Tuxborn discovery confirmed by GUI. Proceeding to configuration/installation.")
            modlist_cli.configuration_phase()
            
            # Handle GUI integration prompts (copied from original)
            print('[PROMPT:RESTART_STEAM]')
            if os.environ.get('JACKIFY_GUI_MODE'):
                input()  # Wait for GUI to send confirmation, no CLI prompt
            else:
                answer = input('Restart Steam automatically now? (Y/n): ')
                # ... handle answer as before ...
            
            print('[PROMPT:MANUAL_STEPS]')
            if os.environ.get('JACKIFY_GUI_MODE'):
                input()  # Wait for GUI to send confirmation, no CLI prompt
            else:
                input('Once you have completed ALL the steps above, press Enter to continue...')
            
            return 0
        else:
            menu_handler.logger.info("Tuxborn discovery/confirmation cancelled or failed (GUI mode).")
            print(f"{COLOR_INFO}Tuxborn installation cancelled or not confirmed.{COLOR_RESET}")
            return 1 