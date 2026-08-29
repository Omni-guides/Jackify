"""Discovery phase methods for ModlistInstallCLI (Mixin)."""
import logging
from typing import Optional, Dict

from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET

logger = logging.getLogger(__name__)


class ModlistOperationsDiscoveryMixin:
    """Mixin providing modlist discovery phase methods."""

    def run_discovery_phase(self, context_override=None, gui_mode: bool = False) -> Optional[Dict]:
        """
        Run the discovery phase: prompt for all required info, and validate inputs.
        Returns a context dict with all collected info, or None if cancelled.
        Accepts context_override for pre-filled values (e.g., for Tuxborn/machineid flow).

        In GUI mode this only validates that the context is already complete - the GUI never
        supplies missing fields interactively. The interactive CLI prompt flow lives in
        frontends/cli/menus/modlist_discovery.py, not here.
        """
        self.logger.info("Starting modlist discovery phase (restored logic).")
        print(f"\n{COLOR_PROMPT}--- Wabbajack Modlist Install: Discovery Phase ---{COLOR_RESET}")

        if context_override:
            self.context.update(context_override)
            if 'resolution' in context_override:
                self.context['resolution'] = context_override['resolution']
        else:
            self.context = {}

        if self.context.get('machineid'):
            required_keys = ['modlist_name', 'install_dir', 'download_dir', 'nexus_api_key']
        else:
            required_keys = ['modlist_name', 'install_dir', 'download_dir', 'nexus_api_key', 'game_type']
        has_modlist = self.context.get('modlist_value') or self.context.get('machineid')
        missing = [k for k in required_keys if not self.context.get(k)]
        if gui_mode:
            if missing or not has_modlist:
                self.logger.error(f"Missing required arguments for GUI workflow: {', '.join(missing)}")
                if not has_modlist:
                    self.logger.error("Missing modlist_value or machineid for GUI workflow.")
                self.logger.error("This workflow must be fully non-interactive. Please report this as a bug if you see this message.")
                return None
            self.logger.info("All required context present in GUI mode, skipping prompts.")
            return self.context

        from jackify.frontends.cli.menus.modlist_discovery import run_interactive_discovery
        return run_interactive_discovery(self)
