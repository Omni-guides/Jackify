"""
Modlist Service

High-level service for modlist operations, orchestrating various handlers.
"""

import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from ..models.modlist import ModlistContext, ModlistInfo
from ..models.configuration import SystemInfo

logger = logging.getLogger(__name__)


class ModlistService:
    """Service for managing modlist operations."""
    
    def __init__(self, system_info: SystemInfo):
        """Initialize the modlist service.
        
        Args:
            system_info: System information context
        """
        self.system_info = system_info
        
        # Handlers will be initialized when needed
        self._modlist_handler = None
        self._wabbajack_handler = None
        self._filesystem_handler = None
        
    def _get_modlist_handler(self):
        """Lazy initialization of modlist handler."""
        if self._modlist_handler is None:
            from ..handlers.modlist_handler import ModlistHandler
            # Initialize with proper dependencies
            self._modlist_handler = ModlistHandler()
        return self._modlist_handler
    
    def _get_wabbajack_handler(self):
        """Lazy initialization of wabbajack handler."""
        if self._wabbajack_handler is None:
            from ..handlers.wabbajack_handler import InstallWabbajackHandler
            # Initialize with proper dependencies
            self._wabbajack_handler = InstallWabbajackHandler()
        return self._wabbajack_handler
    
    def _get_filesystem_handler(self):
        """Lazy initialization of filesystem handler."""
        if self._filesystem_handler is None:
            from ..handlers.filesystem_handler import FileSystemHandler
            self._filesystem_handler = FileSystemHandler()
        return self._filesystem_handler
    
    def list_modlists(self, game_type: Optional[str] = None) -> List[ModlistInfo]:
        """List available modlists.
        
        Args:
            game_type: Optional filter by game type
            
        Returns:
            List of available modlists
        """
        logger.info(f"Listing modlists for game_type: {game_type}")
        
        try:
            # Use the working ModlistInstallCLI to get modlists from engine
            from ..core.modlist_operations import ModlistInstallCLI
            
            # Use new SystemInfo pattern
            modlist_cli = ModlistInstallCLI(self.system_info)
            
            # Get all modlists and do client-side filtering for better control
            raw_modlists = modlist_cli.get_all_modlists_from_engine(game_type=None)
            
            # Apply client-side filtering based on game_type
            if game_type:
                game_type_lower = game_type.lower()
                
                if game_type_lower == 'skyrim':
                    # Include both "Skyrim" and "Skyrim Special Edition" and "Skyrim VR"
                    raw_modlists = [m for m in raw_modlists if 'skyrim' in m.get('game', '').lower()]
                    
                elif game_type_lower == 'fallout4':
                    raw_modlists = [m for m in raw_modlists if 'fallout 4' in m.get('game', '').lower()]
                    
                elif game_type_lower == 'falloutnv':
                    raw_modlists = [m for m in raw_modlists if 'fallout new vegas' in m.get('game', '').lower()]
                    
                elif game_type_lower == 'oblivion':
                    raw_modlists = [m for m in raw_modlists if 'oblivion' in m.get('game', '').lower() and 'remastered' not in m.get('game', '').lower()]
                    
                elif game_type_lower == 'starfield':
                    raw_modlists = [m for m in raw_modlists if 'starfield' in m.get('game', '').lower()]
                    
                elif game_type_lower == 'oblivion_remastered':
                    raw_modlists = [m for m in raw_modlists if 'oblivion remastered' in m.get('game', '').lower()]
                    
                elif game_type_lower == 'enderal':
                    raw_modlists = [m for m in raw_modlists if 'enderal' in m.get('game', '').lower()]
                    
                elif game_type_lower == 'other':
                    # Exclude all main category games to show only "Other" games
                    main_category_keywords = ['skyrim', 'fallout 4', 'fallout new vegas', 'oblivion', 'starfield', 'enderal']
                    def is_main_category(game_name):
                        game_lower = game_name.lower()
                        return any(keyword in game_lower for keyword in main_category_keywords)
                    
                    raw_modlists = [m for m in raw_modlists if not is_main_category(m.get('game', ''))]
            
            # Convert to ModlistInfo objects with enhanced metadata
            modlists = []
            for m_info in raw_modlists:
                modlist_info = ModlistInfo(
                    id=m_info.get('id', ''),
                    name=m_info.get('name', m_info.get('id', '')),  # Use name from enhanced data
                    game=m_info.get('game', ''),
                    description='',  # Engine doesn't provide description yet
                    version='',      # Engine doesn't provide version yet  
                    size=f"{m_info.get('download_size', '')}|{m_info.get('install_size', '')}|{m_info.get('total_size', '')}"  # Store all three sizes
                )
                
                # Add enhanced metadata as additional properties
                if hasattr(modlist_info, '__dict__'):
                    modlist_info.__dict__.update({
                        'download_size': m_info.get('download_size', ''),
                        'install_size': m_info.get('install_size', ''),
                        'total_size': m_info.get('total_size', ''),
                        'machine_url': m_info.get('machine_url', ''),  # Store machine URL for installation
                        'status_down': m_info.get('status_down', False),
                        'status_nsfw': m_info.get('status_nsfw', False)
                    })
                
                # No client-side filtering needed - engine handles it
                modlists.append(modlist_info)
            
            logger.info(f"Found {len(modlists)} modlists")
            return modlists
            
        except Exception as e:
            logger.error(f"Failed to list modlists: {e}")
            raise
    
    def install_modlist(self, context: ModlistContext, 
                       progress_callback=None, 
                       output_callback=None) -> bool:
        """Install a modlist (ONLY installation, no configuration).
        
        This method only runs the engine installation phase.
        Configuration must be called separately after Steam setup.
        
        Args:
            context: Modlist installation context
            progress_callback: Optional callback for progress updates
            output_callback: Optional callback for output/logging
            
        Returns:
            True if installation successful, False otherwise
        """
        logger.info(f"Installing modlist (INSTALLATION ONLY): {context.name}")
        
        try:
            # Validate context
            if not self._validate_install_context(context):
                logger.error("Invalid installation context")
                return False

            # Prepare directories
            fs_handler = self._get_filesystem_handler()
            fs_handler.ensure_directory(context.install_dir)
            fs_handler.ensure_directory(context.download_dir)

            # Use the working ModlistInstallCLI for discovery phase only
            from ..core.modlist_operations import ModlistInstallCLI
            
            # Use new SystemInfo pattern
            modlist_cli = ModlistInstallCLI(self.system_info)
            
            # Build context for ModlistInstallCLI
            install_context = {
                'modlist_name': context.name,
                'install_dir': context.install_dir,
                'download_dir': context.download_dir,
                'nexus_api_key': context.nexus_api_key,
                'game_type': context.game_type,
                'modlist_value': context.modlist_value,
                'resolution': getattr(context, 'resolution', None),
                'skip_confirmation': True  # Service layer should be non-interactive
            }
            
            # Set GUI mode for non-interactive operation
            import os
            original_gui_mode = os.environ.get('JACKIFY_GUI_MODE')
            os.environ['JACKIFY_GUI_MODE'] = '1'
            
            try:
                # Run discovery phase with pre-filled context
                confirmed_context = modlist_cli.run_discovery_phase(context_override=install_context)
                if not confirmed_context:
                    logger.error("Discovery phase failed or was cancelled")
                    return False
                
                # Now run ONLY the installation part (NOT configuration)
                success = self._run_installation_only(
                    confirmed_context, 
                    progress_callback=progress_callback,
                    output_callback=output_callback
                )
                
                if success:
                    logger.info("Modlist installation completed successfully (configuration will be done separately)")
                    return True
                else:
                    logger.error("Modlist installation failed")
                    return False
                
            finally:
                # Restore original GUI mode
                if original_gui_mode is not None:
                    os.environ['JACKIFY_GUI_MODE'] = original_gui_mode
                else:
                    os.environ.pop('JACKIFY_GUI_MODE', None)
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to install modlist {context.name}: {error_message}")
            
            # Check for file descriptor limit issues and attempt to handle them
            from .resource_manager import handle_file_descriptor_error
            try:
                if any(indicator in error_message.lower() for indicator in ['too many open files', 'emfile', 'resource temporarily unavailable']):
                    result = handle_file_descriptor_error(error_message, "modlist installation")
                    if result['auto_fix_success']:
                        logger.info(f"File descriptor limit increased automatically. {result['recommendation']}")
                    elif result['error_detected']:
                        logger.warning(f"File descriptor limit issue detected but automatic fix failed. {result['recommendation']}")
                        if result['manual_instructions']:
                            distro = result['manual_instructions']['distribution']
                            logger.info(f"Manual ulimit increase instructions available for {distro} distribution")
            except Exception as resource_error:
                logger.debug(f"Error checking for resource limit issues: {resource_error}")
            
            return False

    def _run_installation_only(self, context, progress_callback=None, output_callback=None) -> bool:
        """Run only the installation phase using the engine (COPIED FROM WORKING CODE)."""
        import subprocess
        import os
        import sys
        from pathlib import Path
        from ..core.modlist_operations import get_jackify_engine_path
        
        try:
            # COPIED EXACTLY from working Archive_Do_Not_Write/modules/modlist_install_cli.py
            
            # Process paths (copied from working code)
            install_dir_context = context['install_dir']
            if isinstance(install_dir_context, tuple):
                actual_install_path = Path(install_dir_context[0])
                if install_dir_context[1]:
                    actual_install_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_install_path = Path(install_dir_context)
            install_dir_str = str(actual_install_path)
            
            download_dir_context = context['download_dir']  
            if isinstance(download_dir_context, tuple):
                actual_download_path = Path(download_dir_context[0])
                if download_dir_context[1]:
                    actual_download_path.mkdir(parents=True, exist_ok=True)
            else:
                actual_download_path = Path(download_dir_context)
            download_dir_str = str(actual_download_path)
            
            api_key = context['nexus_api_key']
            
            # Path to the engine binary (copied from working code)
            engine_path = get_jackify_engine_path()
            engine_dir = os.path.dirname(engine_path)
            if not os.path.isfile(engine_path) or not os.access(engine_path, os.X_OK):
                if output_callback:
                    output_callback(f"Jackify Install Engine not found or not executable at: {engine_path}")
                return False
            
            # Build command (copied from working code) 
            cmd = [engine_path, 'install']
            modlist_value = context.get('modlist_value')
            if modlist_value and modlist_value.endswith('.wabbajack') and os.path.isfile(modlist_value):
                cmd += ['-w', modlist_value]
            elif modlist_value:
                cmd += ['-m', modlist_value]
            elif context.get('machineid'):
                cmd += ['-m', context['machineid']]
            cmd += ['-o', install_dir_str, '-d', download_dir_str]
            
            # Check for debug mode and add --debug flag
            from ..handlers.config_handler import ConfigHandler
            config_handler = ConfigHandler()
            debug_mode = config_handler.get('debug_mode', False)
            if debug_mode:
                cmd.append('--debug')
                logger.debug("DEBUG: Added --debug flag to jackify-engine command")
            
            # NOTE: API key is passed via environment variable only, not as command line argument
            
            # Store original environment values (copied from working code)
            original_env_values = {
                'NEXUS_API_KEY': os.environ.get('NEXUS_API_KEY'),
                'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': os.environ.get('DOTNET_SYSTEM_GLOBALIZATION_INVARIANT')
            }
            
            try:
                # Environment setup (copied from working code)
                if api_key:
                    os.environ['NEXUS_API_KEY'] = api_key
                elif 'NEXUS_API_KEY' in os.environ:
                    del os.environ['NEXUS_API_KEY']
                    
                os.environ['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = "1"
                
                pretty_cmd = ' '.join([f'"{arg}"' if ' ' in arg else arg for arg in cmd])
                if output_callback:
                    output_callback(f"Launching Jackify Install Engine with command: {pretty_cmd}")
                
                # Temporarily increase file descriptor limit for engine process
                from jackify.backend.handlers.subprocess_utils import increase_file_descriptor_limit
                success, old_limit, new_limit, message = increase_file_descriptor_limit()
                if output_callback:
                    if success:
                        output_callback(f"File descriptor limit: {message}")
                    else:
                        output_callback(f"File descriptor limit warning: {message}")
                
                # Subprocess call (copied from working code)  
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False, env=None, cwd=engine_dir)
                
                # Output processing (copied from working code)
                buffer = b''
                while True:
                    chunk = proc.stdout.read(1)
                    if not chunk:
                        break
                    buffer += chunk
                    
                    if chunk == b'\n':
                        line = buffer.decode('utf-8', errors='replace')
                        if output_callback:
                            output_callback(line.rstrip())
                        buffer = b''
                    elif chunk == b'\r':
                        line = buffer.decode('utf-8', errors='replace')
                        if output_callback:
                            output_callback(line.rstrip())
                        buffer = b''
                
                if buffer:
                    line = buffer.decode('utf-8', errors='replace')
                    if output_callback:
                        output_callback(line.rstrip())
                
                proc.wait()
                if proc.returncode != 0:
                    if output_callback:
                        output_callback(f"Jackify Install Engine exited with code {proc.returncode}.")
                    return False
                else:
                    if output_callback:
                        output_callback("Installation completed successfully")
                    return True
                    
            finally:
                # Restore environment (copied from working code)
                for key, original_value in original_env_values.items():
                    if original_value is not None:
                        os.environ[key] = original_value
                    else:
                        if key in os.environ:
                            del os.environ[key]
                            
        except Exception as e:
            error_msg = f"Error running Jackify Install Engine: {e}"
            logger.error(error_msg)
            if output_callback:
                output_callback(error_msg)
            return False
    
    def configure_modlist_post_steam(self, context: ModlistContext, 
                                   progress_callback=None,
                                   manual_steps_callback=None,
                                   completion_callback=None) -> bool:
        """Configure a modlist after Steam setup is complete.
        
        This method should only be called AFTER:
        1. Modlist installation is complete
        2. Steam shortcut has been created
        3. Steam has been restarted
        4. Manual Proton steps have been completed
        
        Args:
            context: Modlist context with updated app_id
            progress_callback: Optional callback for progress updates
            manual_steps_callback: Called when manual steps needed
            completion_callback: Called when configuration is complete
            
        Returns:
            True if configuration successful, False otherwise
        """
        logger.info(f"Configuring modlist after Steam setup: {context.name}")
        
        # Check if debug mode is enabled and create debug callback
        from ..handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        debug_mode = config_handler.get('debug_mode', False)
        
        def debug_callback(message):
            """Send debug message to GUI if debug mode is enabled"""
            if debug_mode and progress_callback:
                progress_callback(f"[DEBUG] {message}")
        
        debug_callback(f"Starting configuration for {context.name}")
        debug_callback(f"Debug mode enabled: {debug_mode}")
        debug_callback(f"Install directory: {context.install_dir}")
        debug_callback(f"Resolution: {getattr(context, 'resolution', 'Not set')}")
        debug_callback(f"App ID: {getattr(context, 'app_id', 'Not set')}")
        
        # Set up a custom logging handler to capture backend DEBUG messages
        gui_log_handler = None
        if debug_mode and progress_callback:
            import logging
            
            class GuiLogHandler(logging.Handler):
                def __init__(self, callback):
                    super().__init__()
                    self.callback = callback
                    self.setLevel(logging.DEBUG)
                
                def emit(self, record):
                    try:
                        msg = self.format(record)
                        if record.levelno == logging.DEBUG:
                            self.callback(f"[DEBUG] {msg}")
                        elif record.levelno >= logging.WARNING:
                            self.callback(f"[{record.levelname}] {msg}")
                    except Exception:
                        pass
            
            gui_log_handler = GuiLogHandler(progress_callback)
            gui_log_handler.setFormatter(logging.Formatter('%(message)s'))
            
            # Add the GUI handler to key backend loggers
            backend_logger_names = [
                'jackify.backend.handlers.menu_handler',
                'jackify.backend.handlers.modlist_handler',
                'jackify.backend.handlers.install_wabbajack_handler',
                'jackify.backend.handlers.wabbajack_handler',
                'jackify.backend.handlers.shortcut_handler',
                'jackify.backend.handlers.protontricks_handler',
                'jackify.backend.handlers.validation_handler',
                'jackify.backend.handlers.resolution_handler'
            ]
            
            for logger_name in backend_logger_names:
                backend_logger = logging.getLogger(logger_name)
                backend_logger.addHandler(gui_log_handler)
                backend_logger.setLevel(logging.DEBUG)
            
            debug_callback("GUI logging handler installed for backend services")
        
        try:
            # COPY THE WORKING LOGIC: Use menu handler for configuration only
            from ..handlers.menu_handler import ModlistMenuHandler
            
            # Initialize handlers (same as working code)
            modlist_menu = ModlistMenuHandler(config_handler)
            
            # Build configuration context (copied from working code)
            config_context = {
                'name': context.name,
                'path': str(context.install_dir),
                'mo2_exe_path': str(context.install_dir / 'ModOrganizer.exe'),
                'resolution': getattr(context, 'resolution', None),
                'skip_confirmation': True,  # Service layer should be non-interactive
                'manual_steps_completed': True,  # Manual steps were done in GUI
                'appid': getattr(context, 'app_id', None),  # Use updated app_id from Steam
                'engine_installed': getattr(context, 'engine_installed', False)  # Path manipulation flag
            }
            
            debug_callback(f"Configuration context built: {config_context}")
            debug_callback("Setting up GUI mode and stdout redirection")
            
            # Set GUI mode for proper callback handling
            import os
            original_gui_mode = os.environ.get('JACKIFY_GUI_MODE')
            original_stdout = None
            
            try:
                # Force GUI mode to prevent input prompts
                os.environ['JACKIFY_GUI_MODE'] = '1'
                
                # CRITICAL FIX: Redirect print output to capture progress messages
                import sys
                from io import StringIO
                
                # Create a custom stdout that forwards to GUI
                class GuiRedirectStdout:
                    def __init__(self, callback):
                        self.callback = callback
                        self.buffer = ""
                        
                    def write(self, text):
                        if self.callback and text.strip():
                            # Convert ANSI codes to HTML for colored GUI output
                            try:
                                from ...frontends.gui.utils import ansi_to_html
                                # Clean up carriage returns but preserve ANSI colors
                                clean_text = text.replace('\r', '').strip()
                                if clean_text and clean_text != "Current Task: ":
                                    # Convert ANSI to HTML for colored display
                                    html_text = ansi_to_html(clean_text)
                                    self.callback(html_text)
                            except ImportError:
                                # Fallback: strip ANSI codes if ansi_to_html not available
                                import re
                                clean_text = re.sub(r'\x1b\[[0-9;]*[mK]', '', text)
                                clean_text = clean_text.replace('\r', '').strip()
                                if clean_text and clean_text != "Current Task: ":
                                    self.callback(clean_text)
                        return len(text)
                        
                    def flush(self):
                        pass
                
                # Redirect stdout to capture print statements
                if progress_callback:
                    original_stdout = sys.stdout
                    sys.stdout = GuiRedirectStdout(progress_callback)
                
                # Call the working configuration-only method
                debug_callback("Calling run_modlist_configuration_phase")
                success = modlist_menu.run_modlist_configuration_phase(config_context)
                debug_callback(f"Configuration phase result: {success}")
                
                # Restore stdout before calling completion callback
                if original_stdout:
                    sys.stdout = original_stdout
                    original_stdout = None
                
                if completion_callback:
                    if success:
                        debug_callback("Configuration completed successfully, calling completion callback")
                        completion_callback(True, "Configuration completed successfully!", context.name)
                    else:
                        debug_callback("Configuration failed, calling completion callback with failure")
                        completion_callback(False, "Configuration failed", context.name)
                
                return success
                
            finally:
                # Always restore stdout and environment
                if original_stdout:
                    sys.stdout = original_stdout
                    
                if original_gui_mode is not None:
                    os.environ['JACKIFY_GUI_MODE'] = original_gui_mode
                else:
                    os.environ.pop('JACKIFY_GUI_MODE', None)
                
                # Remove GUI log handler to avoid memory leaks
                if gui_log_handler:
                    for logger_name in [
                        'jackify.backend.handlers.menu_handler',
                        'jackify.backend.handlers.modlist_handler',
                        'jackify.backend.handlers.install_wabbajack_handler',
                        'jackify.backend.handlers.wabbajack_handler',
                        'jackify.backend.handlers.shortcut_handler',
                        'jackify.backend.handlers.protontricks_handler',
                        'jackify.backend.handlers.validation_handler',
                        'jackify.backend.handlers.resolution_handler'
                    ]:
                        backend_logger = logging.getLogger(logger_name)
                        backend_logger.removeHandler(gui_log_handler)
            
        except Exception as e:
            logger.error(f"Failed to configure modlist {context.name}: {e}")
            if completion_callback:
                completion_callback(False, f"Configuration failed: {e}", context.name)
            
            # Clean up GUI log handler on exception
            if gui_log_handler:
                for logger_name in [
                    'jackify.backend.handlers.menu_handler',
                    'jackify.backend.handlers.modlist_handler',
                    'jackify.backend.handlers.install_wabbajack_handler',
                    'jackify.backend.handlers.wabbajack_handler',
                    'jackify.backend.handlers.shortcut_handler',
                    'jackify.backend.handlers.protontricks_handler',
                    'jackify.backend.handlers.validation_handler',
                    'jackify.backend.handlers.resolution_handler'
                ]:
                    backend_logger = logging.getLogger(logger_name)
                    backend_logger.removeHandler(gui_log_handler)
            
            return False

    def configure_modlist(self, context: ModlistContext, 
                         progress_callback=None, 
                         manual_steps_callback=None,
                         completion_callback=None,
                         output_callback=None) -> bool:
        """Configure a modlist after installation.
        
        Args:
            context: Modlist context
            progress_callback: Optional callback for progress updates
            manual_steps_callback: Optional callback for manual steps
            completion_callback: Optional callback for completion
            output_callback: Optional callback for output/logging
            
        Returns:
            True if configuration successful, False otherwise
        """
        logger.info(f"Configuring modlist: {context.name}")
        
        try:
            # Use the working ModlistMenuHandler for configuration
            from ..handlers.menu_handler import ModlistMenuHandler
            from ..handlers.config_handler import ConfigHandler
            
            config_handler = ConfigHandler()
            modlist_menu = ModlistMenuHandler(config_handler)
            
            # Build configuration context
            config_context = {
                'name': context.name,
                'path': str(context.install_dir),
                'mo2_exe_path': str(context.install_dir / 'ModOrganizer.exe'),
                'resolution': getattr(context, 'resolution', None),
                'skip_confirmation': True,  # Service layer should be non-interactive
                'manual_steps_completed': False
            }
            
            # Run the complete configuration phase
            success = modlist_menu.run_modlist_configuration_phase(config_context)
            
            if success:
                logger.info("Modlist configuration completed successfully")
                if completion_callback:
                    completion_callback(True, "Configuration completed successfully", context.name)
            else:
                logger.warning("Modlist configuration had issues")
                if completion_callback:
                    completion_callback(False, "Configuration failed", context.name)
                
            return success
            
        except Exception as e:
            logger.error(f"Failed to configure modlist {context.name}: {e}")
            return False
    
    def _validate_install_context(self, context: ModlistContext) -> bool:
        """Validate that the installation context is complete and valid.
        
        Args:
            context: The context to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not context.name:
            logger.error("Modlist name is required")
            return False
        
        if not context.install_dir:
            logger.error("Install directory is required")
            return False
        
        if not context.download_dir:
            logger.error("Download directory is required")
            return False
        
        if not context.nexus_api_key:
            logger.error("Nexus API key is required")
            return False
        
        if not context.game_type:
            logger.error("Game type is required")
            return False
        
        return True 