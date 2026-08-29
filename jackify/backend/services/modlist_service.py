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
            from ..services.platform_detection_service import PlatformDetectionService
            # Initialize with proper dependencies and centralized Steam Deck detection
            platform_service = PlatformDetectionService.get_instance()
            self._modlist_handler = ModlistHandler(steamdeck=platform_service.is_steamdeck)
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

                elif game_type_lower == 'skyrimvr':
                    raw_modlists = [m for m in raw_modlists if 'skyrim vr' in m.get('game', '').lower()]

                elif game_type_lower == 'fallout4vr':
                    raw_modlists = [m for m in raw_modlists if 'fallout 4 vr' in m.get('game', '').lower()]

                elif game_type_lower == 'cp2077':
                    raw_modlists = [m for m in raw_modlists if 'cyberpunk' in m.get('game', '').lower()]

                elif game_type_lower == 'bg3':
                    raw_modlists = [m for m in raw_modlists if "baldur" in m.get('game', '').lower()]

                elif game_type_lower == 'other':
                    # Exclude all main category games to show only "Other" games
                    main_category_keywords = ['skyrim', 'fallout 4', 'fallout new vegas', 'oblivion', 'starfield', 'enderal', 'cyberpunk', "baldur's gate", 'skyrim vr', 'fallout 4 vr']
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

    def configure_modlist_post_steam(self, context: ModlistContext,
                                   progress_callback=None,
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
                'skip_confirmation': True,
                'appid': getattr(context, 'app_id', None),
                'engine_installed': getattr(context, 'engine_installed', False),  # Path manipulation flag
                'download_dir': str(context.download_dir) if getattr(context, 'download_dir', None) else None,
                'modlist_source': getattr(context, 'modlist_source', None),
                'suppress_completion_banner': True,
            }
            
            debug_callback(f"Configuration context built: {config_context}")

            from ..handlers.subprocess_utils import suspend_baloo, resume_baloo
            suspend_baloo()
            try:
                # Call the working configuration-only method
                debug_callback("Calling run_modlist_configuration_phase")
                success = modlist_menu.run_modlist_configuration_phase(
                    config_context, status_callback=progress_callback, gui_mode=True
                )
                debug_callback(f"Configuration phase result: {success}")
                context.steam_restart_needed = config_context.get('steam_restart_needed', False)
                context.mounts_app_name = config_context.get('mounts_app_name', '')
                context.mounts_exe_path = config_context.get('mounts_exe_path', '')
                context.mounts_dl_path = config_context.get('mounts_dl_path', '')

                # Configure ENB for Linux compatibility (non-blocking)
                # Do this BEFORE completion callback so we can pass detection status
                enb_detected = False
                try:
                    from ..handlers.enb_handler import ENBHandler
                    enb_handler = ENBHandler()
                    enb_success, enb_message, enb_detected = enb_handler.configure_enb_for_linux(context.install_dir)
                    
                    if enb_message:
                        if enb_success:
                            logger.info(enb_message)
                            if progress_callback:
                                progress_callback(enb_message)
                        else:
                            logger.warning(enb_message)
                            # Non-blocking: continue workflow even if ENB config fails
                except Exception as e:
                    logger.warning(f"ENB configuration skipped due to error: {e}")
                    # Continue workflow - ENB config is optional
                
                # Store ENB detection status in context for GUI to use
                context.enb_detected = enb_detected
                
                if completion_callback:
                    if success:
                        debug_callback("Core configuration complete, calling completion callback")
                        # Pass ENB detection status through callback
                        completion_callback(True, "Core configuration complete", context.name, enb_detected)
                    else:
                        debug_callback("Configuration failed, calling completion callback with failure")
                        completion_callback(False, "Configuration failed", context.name, False)
                
                return success
                
            finally:
                resume_baloo()

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
                completion_callback(False, f"Configuration failed: {e}", context.name, False)
            
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

    def _validate_install_context(self, context: ModlistContext) -> bool:
        """Validate that the installation context is complete and valid.

        Args:
            context: The context to validate

        Returns:
            True if valid, False otherwise
        """
        from jackify.backend.services.install_validation import validate_install_request
        issues = validate_install_request(
            modlist_name=context.name,
            install_dir=str(context.install_dir) if context.install_dir else None,
            download_dir=str(context.download_dir) if context.download_dir else None,
            nexus_api_key=context.nexus_api_key,
            game_type=context.game_type,
        )
        errors = [i for i in issues if i.severity == 'error']
        for issue in errors:
            logger.error(issue.message)
        return not errors
