"""Console output management for ConfigureExistingModlistScreen (Mixin)."""
import re
import time

from PySide6.QtCore import QTimer

from jackify.shared.progress_models import FileProgress, OperationType


class ConfigureExistingModlistConsoleMixin:
    """Mixin providing console output management for ConfigureExistingModlistScreen."""

    def _handle_progress_update(self, text):
        """Handle progress updates - update console, activity window, and progress indicator"""
        if text.startswith("[NATIVE_DL] "):
            parts = text.split(None, 3)
            if len(parts) == 4:
                _, component, pct_str, speed_str = parts
                try:
                    pct, speed = float(pct_str), float(speed_str)
                    self.file_progress_list.update_or_add_item(
                        "__native_component__",
                        f"Wine component: {component} | {pct:.0f}% ({speed:.1f} MB/s)",
                        pct,
                    )
                except ValueError:
                    pass
            return
        if text.startswith("[NATIVE_INSTALL] "):
            component = text[17:].strip()
            self._stop_component_install_pulse()
            done = getattr(self, '_native_done_components', 0)
            total = getattr(self, '_native_total_components', 0)
            remaining = max(0, total - done)
            suffix = f" ({remaining} remaining)" if remaining > 0 else ""
            self.file_progress_list.update_or_add_item(
                "__native_component__",
                f"Wine component: {component}{suffix}",
                0.0,
            )
            self.progress_indicator.set_status(f"Installing {component}...", 60)
            self._current_native_component = component
            self._native_done_components = done + 1
            return
        if text.startswith("[NATIVE_WAIT] "):
            parts = text.split(None, 2)
            if len(parts) >= 3:
                component, elapsed_s = parts[1], parts[2].strip()
                done = getattr(self, '_native_done_components', 1)
                total = getattr(self, '_native_total_components', 0)
                remaining = max(0, total - done)
                suffix = f" ({remaining} remaining)" if remaining > 0 else ""
                self.file_progress_list.update_or_add_item(
                    "__native_component__",
                    f"Wine component: {component} | {elapsed_s}s{suffix}",
                    0.0,
                )
                self.progress_indicator.set_status(f"Installing {component}... ({elapsed_s}s)", 60)
            return

        # Always append to console
        self._safe_append_text(text)

        # Parse the message to update UI widgets
        message_lower = text.lower()

        # Update progress indicator based on key status messages
        if "setting protontricks permissions" in message_lower:
            self._stop_component_install_pulse()
            self.progress_indicator.set_status("Setting permissions...", 20)
            self.file_progress_list.update_or_add_item("__phase__", "Setting permissions...", 0.0)
        elif "applying curated registry" in message_lower or "registry" in message_lower:
            self._stop_component_install_pulse()
            self.progress_indicator.set_status("Applying registry files...", 40)
            self.file_progress_list.update_or_add_item("__phase__", "Applying registry...", 0.0)
        elif (
            "installing wine components" in message_lower
            or "wine component" in message_lower
            or "vcrun" in message_lower
            or ("dotnet" in message_lower and "fix" not in message_lower)
        ):
            self.progress_indicator.set_status("Installing wine components...", 60)
            comp_list = self._parse_wine_components_message(text)
            if comp_list:
                self._native_total_components = len(comp_list)
                self._native_done_components = 0
                self.file_progress_list.update_or_add_item(
                    "__native_component__",
                    f"Wine components: {len(comp_list)} queued",
                    0.0,
                )
            elif not getattr(self, '_component_install_timer', None) or not self._component_install_timer.isActive():
                self._start_component_install_pulse()
        elif "wine components verified" in message_lower or "wine components installed" in message_lower:
            self._stop_component_install_pulse()
            self.progress_indicator.set_status("Wine components installed", 65)
            self.file_progress_list.update_or_add_item("__phase__", "Wine components installed", 0.0)
        elif "dotnet" in message_lower and "fix" in message_lower:
            self._stop_component_install_pulse()
            self.progress_indicator.set_status("Applying dotnet fixes...", 75)
            self.file_progress_list.update_or_add_item("__phase__", "Applying dotnet fixes...", 0.0)
        elif "setting ownership" in message_lower or "ownership and permissions" in message_lower:
            self._stop_component_install_pulse()
            self.progress_indicator.set_status("Setting permissions...", 85)
            self.file_progress_list.update_or_add_item("__phase__", "Setting permissions...", 0.0)
        elif "verifying" in message_lower:
            self._stop_component_install_pulse()
            self.progress_indicator.set_status("Verifying setup...", 90)
            self.file_progress_list.update_or_add_item("__phase__", "Verifying setup...", 0.0)
        elif "steam integration complete" in message_lower or "configuration complete" in message_lower:
            self._stop_component_install_pulse()
            self.progress_indicator.set_status("Configuration complete", 100)
            self.file_progress_list.update_or_add_item("__phase__", "Configuration complete", 0.0)


    def _safe_append_text(self, text):
        """Append text with professional auto-scroll behavior"""
        # Write all messages to log file
        self._write_to_log_file(text)
        
        scrollbar = self.console.verticalScrollBar()
        # Check if user was at bottom BEFORE adding text
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)  # Allow 1px tolerance
        
        # Add the text
        self.console.append(text)
        
        # Auto-scroll if user was at bottom and hasn't manually scrolled
        # Re-check bottom state after text addition for better reliability
        if (was_at_bottom and not self._user_manually_scrolled) or \
           (not self._user_manually_scrolled and scrollbar.value() >= scrollbar.maximum() - 2):
            scrollbar.setValue(scrollbar.maximum())
            # Ensure user can still manually scroll up during rapid updates
            if scrollbar.value() == scrollbar.maximum():
                self._was_at_bottom = True


    def _write_to_log_file(self, message):
        """Write message to workflow log file with timestamp"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.modlist_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

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
        """Start pulsing Activity item for Wine component installation (single generic item)."""
        self.file_progress_list.update_or_add_item("__wine_components__", "Installing Wine components...", 0.0)
        if not getattr(self, '_component_install_timer', None):
            self._component_install_timer = QTimer(self)
            self._component_install_timer.timeout.connect(self._component_install_heartbeat)
        self._component_install_timer.start(100)
        self._component_install_start_time = time.time()

    def _start_component_install_pulse_with_components(self, components: list):
        """Replace single item with one Activity entry per component, each with pulsing progress."""
        self._component_install_list = components
        progresses = [
            FileProgress(
                filename=f"Wine component: {comp}",
                operation=OperationType.UNKNOWN,
                percent=0.0,
            )
            for comp in components
        ]
        self.file_progress_list.update_files(progresses, current_phase=None)

    def _component_install_heartbeat(self):
        """Heartbeat to keep component install item(s) pulsing."""
        if not hasattr(self, '_component_install_start_time') or not self._component_install_start_time:
            return
        if hasattr(self, '_component_install_list') and self._component_install_list:
            dl_state = getattr(self, '_native_component_progress', {})
            progresses = []
            for comp in self._component_install_list:
                if comp in dl_state:
                    pct, speed = dl_state[comp]
                    progresses.append(FileProgress(
                        filename=f"Wine component: {comp} | {pct:.0f}% ({speed:.1f} MB/s)",
                        operation=OperationType.DOWNLOAD,
                        percent=pct,
                    ))
                else:
                    progresses.append(FileProgress(
                        filename=f"Wine component: {comp}",
                        operation=OperationType.UNKNOWN,
                        percent=0.0,
                    ))
            self.file_progress_list.update_files(progresses, current_phase=None)
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


