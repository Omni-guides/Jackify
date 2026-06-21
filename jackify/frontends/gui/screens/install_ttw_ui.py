"""UI helper methods for InstallTTWScreen (Mixin)."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor, QColor
from PySide6.QtWidgets import QSizePolicy
import logging
import time
# Runtime imports to avoid circular dependencies
from ..utils import set_responsive_minimum  # Runtime import

logger = logging.getLogger(__name__)

class TTWUIMixin:
    """Mixin providing UI helper methods for InstallTTWScreen."""

    def _setup_scroll_tracking(self):
        """Set up scroll tracking for professional auto-scroll behavior"""
        scrollbar = self.console.verticalScrollBar()
        scrollbar.sliderPressed.connect(self._on_scrollbar_pressed)
        scrollbar.sliderReleased.connect(self._on_scrollbar_released)
        scrollbar.valueChanged.connect(self._on_scrollbar_value_changed)

    def _on_scrollbar_pressed(self):
        """User started manually scrolling"""
        self._user_manually_scrolled = True

    def _on_scrollbar_released(self):
        """User finished manually scrolling"""
        self._user_manually_scrolled = False

    def _on_scrollbar_value_changed(self):
        """Track if user is at bottom of scroll area"""
        scrollbar = self.console.verticalScrollBar()
        # Use tolerance to account for rounding and rapid updates
        self._was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 1
        
        # If user manually scrolls to bottom, reset manual scroll flag
        if self._was_at_bottom and self._user_manually_scrolled:
            # Small delay to allow user to scroll away if they want
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._reset_manual_scroll_if_at_bottom)
    
    def _reset_manual_scroll_if_at_bottom(self):
        """Reset manual scroll flag if user is still at bottom after delay"""
        scrollbar = self.console.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 1:
            self._user_manually_scrolled = False

    def _on_show_details_toggled(self, checked: bool):
        from PySide6.QtCore import Qt as _Qt
        self._toggle_console_visibility(_Qt.Checked if checked else _Qt.Unchecked)

    def _toggle_console_visibility(self, state):
        """Toggle console visibility and resize main window"""
        is_checked = (state == Qt.Checked)
        main_window = self.window()

        if not main_window:
            return

        # Check if we're on Steam Deck
        is_steamdeck = False
        if self.system_info and getattr(self.system_info, 'is_steamdeck', False):
            is_steamdeck = True
        elif not self.system_info and main_window and hasattr(main_window, 'system_info'):
            is_steamdeck = getattr(main_window.system_info, 'is_steamdeck', False)

        # Console height when expanded
        console_height = 300

        if is_checked:
            # Show console
            self.console.setVisible(True)
            self.console.show()
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)
            try:
                self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            except Exception:
                pass
            try:
                self.main_overall_vbox.setStretchFactor(self.console, 1)
            except Exception:
                pass

            # On Steam Deck, skip window resizing - keep default Steam Deck window size
            if is_steamdeck:
                logger.debug("Steam Deck detected, skipping window resize in _toggle_console_visibility")
                return

            # Restore main window to normal size (clear any compact constraints)
            # On Steam Deck, keep fullscreen; on other systems, set normal window state
            if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                main_window.showNormal()
            main_window.setMaximumHeight(16777215)
            main_window.setMinimumHeight(0)
            # Restore original minimum size so the window can expand normally
            try:
                if self._saved_min_size is not None:
                    main_window.setMinimumSize(self._saved_min_size)
            except Exception:
                pass
            # Prefer exact original geometry if known
            if self._saved_geometry is not None:
                main_window.setGeometry(self._saved_geometry)
            else:
                expanded_min = 900
                current_size = main_window.size()
                target_height = max(expanded_min, 900)
                main_window.setMinimumHeight(expanded_min)
                main_window.resize(current_size.width(), target_height)
            try:
                # Encourage layouts to recompute sizes
                self.main_overall_vbox.invalidate()
                self.updateGeometry()
            except Exception:
                pass
            # Notify parent to expand
            try:
                self.resize_request.emit('expand')
            except Exception:
                pass
        else:
            # Hide console fully (removes it from layout sizing)
            self.console.setVisible(False)
            self.console.hide()
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            try:
                # Make the hidden console contribute no expand pressure
                self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            except Exception:
                pass
            try:
                self.main_overall_vbox.setStretchFactor(self.console, 0)
            except Exception:
                pass

            # On Steam Deck, skip window resizing to keep maximized state
            if is_steamdeck:
                logger.debug("Steam Deck detected, skipping window resize in collapse branch")
                return

            # Use fixed compact height for consistency across all workflow screens
            compact_height = 620
            # On Steam Deck, keep fullscreen; on other systems, set normal window state
            if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                main_window.showNormal()
            # Set minimum height but no maximum to allow user resizing
            try:
                from PySide6.QtCore import QSize
                set_responsive_minimum(main_window, min_width=960, min_height=compact_height)
                main_window.setMaximumSize(QSize(16777215, 16777215))  # No maximum
            except Exception:
                pass

            # Resize to compact height to avoid leftover space
            current_size = main_window.size()
            main_window.resize(current_size.width(), compact_height)
            # Notify parent to collapse
            try:
                self.resize_request.emit('collapse')
            except Exception:
                pass

    def _update_ttw_activity(self, current, total, percent):
        """Update Activity window with TTW installation progress"""
        try:
            # Determine current phase based on progress
            if not hasattr(self, '_ttw_current_phase'):
                self._ttw_current_phase = None

            # Use current phase name or default
            phase_name = self._ttw_current_phase or "Processing"
            
            # Update or add activity item showing current progress with phase name and counters
            # Don't include percentage in label - progress bar shows it
            label = f"{phase_name}: {current:,}/{total:,}"
            self.file_progress_list.update_or_add_item(
                item_id="ttw_progress",
                label=label,
                progress=percent
            )
        except Exception:
            pass

    def _update_ttw_phase(self, phase_name, current=None, total=None, percent=0):
        """Update Activity window with current TTW installation phase and optional progress"""
        try:
            self._ttw_current_phase = phase_name
            
            # Build label with phase name and counters if provided
            # Don't include percentage in label - progress bar shows it
            if current is not None and total is not None:
                label = f"{phase_name}: {current:,}/{total:,}"
            else:
                label = phase_name
            
            # Update or add activity item
            self.file_progress_list.update_or_add_item(
                item_id="ttw_phase",
                label=label,
                progress=percent
            )
        except Exception:
            pass

    def _safe_append_text(self, text, color=None):
        """Append text with professional auto-scroll behavior
        
        Args:
            text: Text to append
            color: Optional HTML color code (e.g., '#f44336' for red) to format the text
        """
        # Write all messages to log file (including internal messages)
        self._write_to_log_file(text)
        
        # Filter out internal status messages from user console display
        if text.strip().startswith('[Jackify]'):
            # Internal messages are logged but not shown in user console
            return
            
        scrollbar = self.console.verticalScrollBar()
        # Check if user was at bottom BEFORE adding text
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)  # Allow 1px tolerance
        
        # Format text with color if provided
        if color:
            # Escape HTML special characters
            escaped_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            formatted_text = f'<span style="color: {color};">{escaped_text}</span>'
            # Use insertHtml for colored text (QTextEdit supports HTML in append when using RichText)
            cursor = self.console.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.console.setTextCursor(cursor)
            self.console.insertHtml(formatted_text + '<br>')
        else:
            # Add plain text
            self.console.append(text)
        
        # Auto-scroll if user was at bottom and hasn't manually scrolled
        # Re-check bottom state after text addition for better reliability
        if (was_at_bottom and not self._user_manually_scrolled) or \
           (not self._user_manually_scrolled and scrollbar.value() >= scrollbar.maximum() - 2):
            scrollbar.setValue(scrollbar.maximum())
            # Ensure user can still manually scroll up during rapid updates
            if scrollbar.value() == scrollbar.maximum():
                self._was_at_bottom = True

    def _update_progress_line(self, text):
        """Update progress - just append, don't try to replace (simpler and safer)"""
        # Simplified: Just append progress lines instead of trying to replace
        # Avoids Qt cursor SystemError
        # Only show in details mode to avoid spam
        if self.show_details_checkbox.isChecked():
            self._safe_append_text(text)
        # Always track for Activity window updates (handled separately)
        self._ttw_progress_line_text = text

    def _update_ttw_elapsed_time(self):
        """Update status banner with elapsed time"""
        if hasattr(self, 'ttw_start_time'):
            elapsed = int(time.time() - self.ttw_start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            self.status_banner.setText(f"Processing Tale of Two Wastelands installation... Elapsed: {minutes}m {seconds}s")

