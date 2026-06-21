"""Post-install UI feedback management for InstallModlistScreen (Mixin)."""
import logging
import re
import time
from typing import Optional

from PySide6.QtCore import QTimer

from jackify.shared.progress_models import InstallationProgress, InstallationPhase, FileProgress, OperationType

logger = logging.getLogger(__name__)


class PostInstallFeedbackMixin:
    """Mixin providing post-install progress tracking and UI feedback for InstallModlistScreen."""

    def _build_post_install_sequence(self):
        """
        Define the ordered steps for post-install (Jackify-managed) operations.

        These steps represent Jackify's automated Steam integration and configuration workflow
        that runs AFTER the jackify-engine completes modlist installation. Progress is shown as
        "X/Y" in the progress banner and Activity window.

        The post-install steps are:
        1. Preparing Steam integration - Initial setup before creating Steam shortcut
        2. Creating Steam shortcut - Add modlist to Steam library with proper Proton settings
        3. Restarting Steam - Restart Steam to make shortcut visible and create AppID
        4. Creating Proton prefix - Launch temporary batch file to initialize Proton prefix
        5. Verifying Steam setup - Confirm prefix exists and Proton version is correct
        6. Steam integration complete - Steam setup finished successfully
        7. Installing Wine components - Install vcrun, dotnet, and other Wine dependencies
        8. Applying registry files - Import .reg files for game configuration
        9. Installing .NET fixes - Apply .NET framework workarounds if needed
        10. Enabling dotfiles - Make hidden config files visible in file manager
        11. Setting permissions - Ensure modlist files have correct permissions
        12. Backing up configuration - Create backup of ModOrganizer.ini
        13. Finalising Jackify configuration - All post-install steps complete
        """
        return [
            {
                'id': 'prepare',
                'label': "Preparing Steam integration",
                'keywords': [
                    "starting automated steam setup",
                    "starting configuration phase",
                    "starting configuration"
                ],
            },
            {
                'id': 'steam_shortcut',
                'label': "Creating Steam shortcut",
                'keywords': [
                    "creating steam shortcut",
                    "steam shortcut created successfully"
                ],
            },
            {
                'id': 'steam_restart',
                'label': "Restarting Steam",
                'keywords': [
                    "restarting steam",
                    "steam restarted successfully"
                ],
            },
            {
                'id': 'proton_prefix',
                'label': "Creating Proton prefix",
                'keywords': [
                    "creating proton prefix",
                    "proton prefix created successfully",
                    "temporary batch file launched",
                    "verifying prefix creation"
                ],
            },
            {
                'id': 'steam_verify',
                'label': "Verifying Steam setup",
                'keywords': [
                    "verifying setup",
                    "verifying prefix",
                    "setup verification completed",
                    "detecting actual appid",
                    "steam configuration complete"
                ],
            },
            {
                'id': 'steam_complete',
                'label': "Steam integration complete",
                'keywords': [
                    "steam integration complete",
                    "steam integration",
                    "steam configuration complete!"
                ],
            },
            {
                'id': 'wine_components',
                'label': "Installing Wine components",
                'keywords': [
                    "installing wine components",
                    "wine components",
                    "vcrun",
                    "dotnet",
                    "running winetricks",
                ],
            },
            {
                'id': 'registry_files',
                'label': "Applying registry files",
                'keywords': [
                    "applying registry",
                    "importing registry",
                    ".reg file",
                    "registry files",
                ],
            },
            {
                'id': 'dotnet_fixes',
                'label': "Installing .NET fixes",
                'keywords': [
                    "dotnet fix",
                    ".net fix",
                    "installing .net",
                ],
            },
            {
                'id': 'enable_dotfiles',
                'label': "Enabling dotfiles",
                'keywords': [
                    "enabling dotfiles",
                    "dotfiles",
                    "hidden files",
                ],
            },
            {
                'id': 'set_permissions',
                'label': "Setting permissions",
                'keywords': [
                    "setting permissions",
                    "chmod",
                    "permissions",
                ],
            },
            {
                'id': 'backup_config',
                'label': "Backing up configuration",
                'keywords': [
                    "backing up",
                    "modorganizer.ini",
                    "backup",
                ],
            },
            {
                'id': 'vnv_root_mods',
                'label': "VNV: Copying root mods",
                'keywords': [
                    "step 1/3: copying root mods",
                    "copying root mods to game directory",
                    "root mods:",
                ],
            },
            {
                'id': 'vnv_4gb_patch',
                'label': "VNV: Applying 4GB patch",
                'keywords': [
                    "step 2/3: downloading and running 4gb patcher",
                    "downloading fnv4gb",
                    "downloading:",
                    "fetching file list",
                    "running 4gb patcher",
                    "4gb patcher:",
                ],
            },
            {
                'id': 'vnv_bsa_decompress',
                'label': "VNV: Decompressing BSA files",
                'keywords': [
                    "step 3/3: downloading and running bsa decompressor",
                    "downloading:",
                    "fetching file list",
                    "running bsa decompressor",
                    "decompressing bsa files:",
                    "bsa decompression:",
                ],
            },
            {
                'id': 'final_config',
                'label': "Performing final tasks",
                'keywords': [
                    "digicert",
                    "certificate",
                    "windows version",
                    "windows 11",
                    "mscoree",
                    "tool compat",
                    "nemesis setup",
                    "applying tool",
                    "symlink",
                ],
            },
            {
                'id': 'config_finalize',
                'label': "Finalising Jackify configuration",
                'keywords': [
                    "configuration completed successfully",
                    "configuration complete",
                    "manual steps validation failed",
                    "configuration failed",
                    "vnv post-install completed successfully"
                ],
            },
        ]

    def _begin_post_install_feedback(self):
        """Reset trackers and surface post-install progress in collapsed mode."""
        self._post_install_active = True
        self._post_install_current_step = 0
        self._post_install_last_label = "Preparing Steam integration"
        total = max(1, self._post_install_total_steps)
        self._update_post_install_ui(self._post_install_last_label, 0, total)
        self.cancel_btn.setVisible(False)
        self.cancel_install_btn.setVisible(True)

    def _handle_post_install_progress(self, message: str):
        """Translate backend progress messages into collapsed-mode feedback."""
        if not self._post_install_active or not message:
            if not self._post_install_active and message:
                logger.debug("[PULSE] _handle_post_install_progress skipped - post_install_active=False, msg=%r", message[:60])
            return

        text = message.strip()
        if not text:
            return

        if any(kw in text.lower() for kw in ['wine', 'vcrun', 'dotnet', 'winetricks', 'component']):
            logger.debug("[PULSE] progress msg (wine-related): %r, step=%s, timer_active=%s",
                text[:80], getattr(self, '_post_install_current_step', 'N/A'),
                bool(getattr(self, '_component_install_timer', None) and
                     getattr(self._component_install_timer, 'isActive', lambda: False)()))

        if text.startswith("[NATIVE_DL] "):
            parts = text.split(None, 3)
            if len(parts) == 4:
                _, component, pct_str, speed_str = parts
                try:
                    if not hasattr(self, '_native_component_progress'):
                        self._native_component_progress = {}
                    self._native_component_progress[component] = (float(pct_str), float(speed_str))
                except ValueError:
                    pass
            return
        if text.startswith("[NATIVE_INSTALL] "):
            component = text[17:].strip()
            if hasattr(self, '_native_component_progress'):
                self._native_component_progress.pop(component, None)
            done = getattr(self, '_native_done_components', 0)
            self._current_native_component = component
            self._native_done_components = done + 1
            if hasattr(self, '_component_install_list') and self._component_install_list:
                total = len(self._component_install_list)
                remaining = max(0, total - (done + 1))
                suffix = f" ({remaining} remaining)" if remaining > 0 else ""
                self.file_progress_list.update_files(
                    [FileProgress(filename=f"Wine component: {component}{suffix}", operation=OperationType.UNKNOWN, percent=0.0)],
                    current_phase=None,
                )
            return

        normalized = text.lower()
        total = max(1, self._post_install_total_steps)
        matched = False
        matched_step = None

        # Check for wine components completion first
        if "wine components verified" in normalized or "wine components installed" in normalized:
            self._stop_component_install_pulse()

        for idx, step in enumerate(self._post_install_sequence, start=1):
            if any(keyword in normalized for keyword in step['keywords']):
                matched = True
                matched_step = idx
                # Always update to the highest step we've seen (don't go backwards)
                if idx >= self._post_install_current_step:
                    # Stop pulser when moving away from wine_components step
                    if self._post_install_current_step > 0:
                        prev_step = self._post_install_sequence[self._post_install_current_step - 1]
                        if prev_step['id'] == 'wine_components' and step['id'] != 'wine_components':
                            self._stop_component_install_pulse()
                        if prev_step['id'] == 'vnv_bsa_decompress' and step['id'] != 'vnv_bsa_decompress':
                            self._stop_bsa_decompress_pulse()

                    self._post_install_current_step = idx
                    self._post_install_last_label = step['label']

                    # Wine components: pulser manages Activity window directly.
                    # Must remove summary widget so pulser items display immediately
                    # (otherwise the 0.5s hold blocks update_files from adding items).
                    if step['id'] == 'wine_components':
                        logger.debug("[PULSE] wine_components step matched, msg=%r", text[:80])
                        self.file_progress_list.clear_summary()
                        self.progress_indicator.set_status(
                            "Installing Wine components...",
                            int((self._post_install_current_step / total) * 100)
                        )
                        timer_active = hasattr(self, '_component_install_timer') and self._component_install_timer and self._component_install_timer.isActive()
                        logger.debug("[PULSE] timer_active=%s", timer_active)
                        if not timer_active:
                            self._start_component_install_pulse()
                        # Always check for component list updates (may come in later messages)
                        comp_list = self._parse_wine_components_message(text)
                        logger.debug("[PULSE] comp_list=%s", comp_list)
                        if comp_list:
                            self._start_component_install_pulse_with_components(comp_list)
                        break

                    if step['id'] == 'vnv_bsa_decompress':
                        self._start_bsa_decompress_pulse()

                # Keep Activity window in sync with progress banner
                # If we're already in wine_components step, check for component list updates
                # Skip _update_post_install_ui() for wine_components - pulser manages Activity window directly
                if step['id'] == 'wine_components':
                    comp_list = self._parse_wine_components_message(text)
                    if comp_list:
                        self._start_component_install_pulse_with_components(comp_list)
                    # Don't call _update_post_install_ui() - it would clear the component items
                    break
                
                # CRITICAL: If pulser is active (wine components still installing), don't update progress banner
                # Keep it on "Installing Wine components..." until pulser stops
                if getattr(self, '_component_install_timer', None) and self._component_install_timer.isActive():
                    # Find wine_components step and keep banner on that
                    wine_step = None
                    wine_step_idx = None
                    for wine_idx, wine_s in enumerate(self._post_install_sequence, start=1):
                        if wine_s['id'] == 'wine_components':
                            wine_step = wine_s
                            wine_step_idx = wine_idx
                            break
                    if wine_step:
                        # Update step counter internally but keep banner on wine components
                        # Filter out winetricks/protontricks internal messages from detail
                        filtered_detail = text
                        if text and any(keyword in text.lower() for keyword in ['perl:', 'wine:', 'winetricks:', 'protontricks:']):
                            filtered_detail = None
                        self._update_post_install_ui(
                            wine_step['label'],
                            wine_step_idx,
                            total,
                            detail=filtered_detail
                        )
                        break
                
                self._update_post_install_ui(step['label'], self._post_install_current_step, total, detail=text)
                break

        # If no match but we have a current step, update with that step (not a new one)
        # Skip when pulser is active -- it manages Activity window directly
        if not matched and self._post_install_current_step > 0:
            # CRITICAL: If pulser is active, we're still installing wine components
            # Keep progress banner on "Installing Wine components..." regardless of step counter
            if getattr(self, '_component_install_timer', None) and self._component_install_timer.isActive():
                # Find wine_components step in sequence
                wine_step = None
                wine_step_idx = None
                for idx, step in enumerate(self._post_install_sequence, start=1):
                    if step['id'] == 'wine_components':
                        wine_step = step
                        wine_step_idx = idx
                        break
                
                if wine_step:
                    # Always check for component list updates, even if message doesn't match keywords
                    comp_list = self._parse_wine_components_message(text)
                    if comp_list:
                        self._start_component_install_pulse_with_components(comp_list)
                    # Update progress banner to show wine components installation (pulser manages Activity window directly)
                    # Filter out winetricks/protontricks internal messages from detail
                    filtered_detail = text
                    if text and any(keyword in text.lower() for keyword in ['perl:', 'wine:', 'winetricks:', 'protontricks:']):
                        filtered_detail = None
                    total = len(self._post_install_sequence)
                    self._update_post_install_ui(
                        wine_step['label'],
                        wine_step_idx,
                        total,
                        detail=filtered_detail
                    )
                    return
            
            # Check if we're in wine_components step (by step counter)
            current_step = self._post_install_sequence[self._post_install_current_step - 1] if self._post_install_current_step > 0 else None
            if current_step and current_step['id'] == 'wine_components':
                # Always check for component list updates, even if message doesn't match keywords
                comp_list = self._parse_wine_components_message(text)
                if comp_list:
                    self._start_component_install_pulse_with_components(comp_list)
                # Update progress banner to keep it current (pulser manages Activity window directly)
                # Filter out winetricks/protontricks internal messages from detail
                filtered_detail = text
                if text and any(keyword in text.lower() for keyword in ['perl:', 'wine:', 'winetricks:', 'protontricks:']):
                    filtered_detail = None
                total = len(self._post_install_sequence)
                self._update_post_install_ui(
                    current_step['label'],
                    self._post_install_current_step,
                    total,
                    detail=filtered_detail
                )
                return
            
            if not getattr(self, '_component_install_timer', None):
                label = self._post_install_last_label or "Post-installation"
                # Filter out winetricks/protontricks internal messages from detail
                filtered_detail = text
                if text and any(keyword in text.lower() for keyword in ['perl:', 'wine:', 'winetricks:', 'protontricks:']):
                    filtered_detail = None
                self._update_post_install_ui(label, self._post_install_current_step, total, detail=filtered_detail)

    def _strip_timestamp_prefix(self, text: str) -> str:
        """Remove timestamp prefix like '[00:03:15]' from text."""
        # Match timestamps like [00:03:15], [01:23:45], etc.
        timestamp_pattern = r'^\[\d{2}:\d{2}:\d{2}\]\s*'
        return re.sub(timestamp_pattern, '', text)

    def _update_post_install_ui(self, label: str, step: int, total: int, detail: Optional[str] = None):
        """Update progress indicator + activity summary for post-install steps."""
        display_label = label
        if detail:
            clean_detail = self._strip_timestamp_prefix(detail.strip())
            if clean_detail:
                if any(keyword in clean_detail.lower() for keyword in ['perl:', 'wine:', '/usr/bin/', 'winetricks:', 'protontricks:']):
                    pass
                elif clean_detail.lower().startswith(label.lower()):
                    display_label = clean_detail
                else:
                    display_label = clean_detail
        total = max(1, total)
        step_clamped = max(0, min(step, total))
        overall_percent = (step_clamped / total) * 100.0

        progress_state = InstallationProgress(
            phase=InstallationPhase.FINALIZE,
            phase_name=display_label,
            phase_step=step_clamped,
            phase_max_steps=total,
            overall_percent=overall_percent
        )
        self.progress_indicator.update_progress(progress_state)

        # When the component pulse timer is active, it owns the Activity window.
        # Writing a summary widget here would block the heartbeat's file items via the 0.5s hold.
        if getattr(self, '_component_install_timer', None) and self._component_install_timer.isActive():
            return

        summary_info = {
            'current_step': step_clamped,
            'max_steps': total,
        }
        self.file_progress_list.update_files([], current_phase=display_label, summary_info=summary_info)

    def _end_post_install_feedback(self, success: bool):
        """Mark the end of post-install feedback."""
        if not self._post_install_active:
            return
        self._stop_component_install_pulse()
        self._stop_bsa_decompress_pulse()
        total = max(1, self._post_install_total_steps)
        final_step = total if success else max(0, self._post_install_current_step)
        label = "Post-installation complete" if success else "Post-installation stopped"
        self._update_post_install_ui(label, final_step, total)
        self._post_install_active = False
        self._post_install_last_label = label
        self.cancel_btn.setVisible(True)
        self.cancel_install_btn.setVisible(False)

    def _parse_wine_components_message(self, text: str):
        """Extract list of wine component names from backend status message, or None."""
        if "installing wine components:" not in text.lower() and "installing wine components via protontricks:" not in text.lower():
            return None
        match = re.search(r"installing wine components(?:\s+via protontricks)?:\s*(.+)", text, re.IGNORECASE)
        if not match:
            return None
        raw = match.group(1).strip()
        if not raw:
            return None
        return [c.strip() for c in raw.split(",") if c.strip()]

    def _start_component_install_pulse(self):
        """Start pulsing Activity item for Wine component installation."""
        logger.debug("[PULSE] _start_component_install_pulse called, post_install_active=%s", getattr(self, '_post_install_active', 'N/A'))
        self.file_progress_list.update_or_add_item("__wine_components__", "Installing Wine components...", 0.0)
        if not getattr(self, '_component_install_timer', None):
            self._component_install_timer = QTimer(self)
            self._component_install_timer.timeout.connect(self._component_install_heartbeat)
        self._component_install_timer.start(100)
        self._component_install_start_time = time.time()
        logger.debug("[PULSE] component install timer started")

    def _start_component_install_pulse_with_components(self, components: list):
        """Show queued count; heartbeat switches to per-component display as each starts."""
        logger.debug("[PULSE] _start_component_install_pulse_with_components called, components=%s", components)
        self._component_install_list = components
        self._native_total_components = len(components)
        self._native_done_components = 0
        self._current_native_component = None
        self.file_progress_list.update_or_add_item(
            "__wine_components__",
            f"Wine components: {len(components)} queued",
            0.0,
        )

    def _component_install_heartbeat(self):
        """Heartbeat to keep component install item pulsing."""
        if not hasattr(self, '_component_install_start_time') or not self._component_install_start_time:
            logger.debug("[PULSE] heartbeat fired but no start_time, skipping")
            return
        current = getattr(self, '_current_native_component', None)
        if hasattr(self, '_component_install_list') and self._component_install_list:
            total = len(self._component_install_list)
            done = getattr(self, '_native_done_components', 0)
            dl_state = getattr(self, '_native_component_progress', {})
            if current:
                if current in dl_state:
                    pct, speed = dl_state[current]
                    label = f"Wine component: {current} | {pct:.0f}% ({speed:.1f} MB/s)"
                    op = OperationType.DOWNLOAD
                    pct_val = pct
                else:
                    remaining = max(0, total - done)
                    suffix = f" ({remaining} remaining)" if remaining > 0 else ""
                    label = f"Wine component: {current}{suffix}"
                    op = OperationType.UNKNOWN
                    pct_val = 0.0
                self.file_progress_list.update_files(
                    [FileProgress(filename=label, operation=op, percent=pct_val)],
                    current_phase=None,
                )
            else:
                self.file_progress_list.update_or_add_item(
                    "__wine_components__",
                    f"Wine components: {total} queued",
                    0.0,
                )
        else:
            self.file_progress_list.update_or_add_item("__wine_components__", "Installing Wine components...", 0.0)

    def _stop_component_install_pulse(self):
        """Stop the component install pulsing timer."""
        if hasattr(self, '_component_install_timer') and self._component_install_timer:
            self._component_install_timer.stop()
            self._component_install_timer = None
        if hasattr(self, '_component_install_list'):
            del self._component_install_list
        if hasattr(self, '_native_component_progress'):
            del self._native_component_progress

    def _start_bsa_decompress_pulse(self):
        """Keep the Activity window alive during long BSA decompression runs."""
        self.file_progress_list.update_or_add_item("__vnv_bsa__", "VNV: Decompressing BSA files...", 0.0)
        if not getattr(self, '_bsa_decompress_timer', None):
            self._bsa_decompress_timer = QTimer(self)
            self._bsa_decompress_timer.timeout.connect(self._bsa_decompress_heartbeat)
        self._bsa_decompress_timer.start(250)

    def _bsa_decompress_heartbeat(self):
        self.file_progress_list.update_or_add_item("__vnv_bsa__", "VNV: Decompressing BSA files...", 0.0)

    def _stop_bsa_decompress_pulse(self):
        if hasattr(self, '_bsa_decompress_timer') and self._bsa_decompress_timer:
            self._bsa_decompress_timer.stop()
            self._bsa_decompress_timer = None
