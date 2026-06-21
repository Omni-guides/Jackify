"""GUI configuration phase methods for ModlistInstallCLI (Mixin)."""
import logging
import os

logger = logging.getLogger(__name__)


class ModlistOperationsConfigurationGUIMixin:
    """Mixin providing GUI configuration phase methods."""

    def configuration_phase_gui_mode(self, context,
                                     progress_callback=None,
                                     completion_callback=None):
        """
        GUI-friendly configuration phase that uses callbacks instead of prompts.

        Args:
            context: Configuration context dict with modlist details
            progress_callback: Called with progress messages (str)
            completion_callback: Called when configuration completes (success, message, modlist_name)
        """
        try:
            original_gui_mode = os.environ.get('JACKIFY_GUI_MODE')

            try:
                config_context = {
                    'name': context.get('modlist_name', ''),
                    'path': context.get('install_dir', ''),
                    'mo2_exe_path': context.get('mo2_exe_path', ''),
                    'modlist_value': context.get('modlist_value'),
                    'modlist_source': context.get('modlist_source'),
                    'resolution': context.get('resolution'),
                    'skip_confirmation': True,
                }

                existing_app_id = context.get('app_id')
                if existing_app_id:
                    config_context['appid'] = existing_app_id

                if progress_callback:
                    progress_callback("Running modlist configuration...")

                from jackify.backend.handlers.menu_handler import ModlistMenuHandler
                from jackify.backend.handlers.config_handler import ConfigHandler

                config_handler = ConfigHandler()
                modlist_menu = ModlistMenuHandler(config_handler)
                result = modlist_menu.run_modlist_configuration_phase(config_context)

                if result:
                    if completion_callback:
                        completion_callback(True, "Core configuration complete", config_context['name'])
                    return True
                else:
                    if completion_callback:
                        completion_callback(False, "Configuration failed", config_context['name'])
                    return False

            finally:
                if original_gui_mode is not None:
                    os.environ['JACKIFY_GUI_MODE'] = original_gui_mode
                else:
                    os.environ.pop('JACKIFY_GUI_MODE', None)

        except Exception as e:
            error_msg = f"Configuration failed: {str(e)}"
            if completion_callback:
                completion_callback(False, error_msg, context.get('modlist_name', 'Unknown'))
            return False
