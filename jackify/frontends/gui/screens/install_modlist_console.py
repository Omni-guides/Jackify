"""Console output management for InstallModlistScreen (Mixin)."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QSizePolicy, QApplication
from PySide6.QtGui import QTextCursor
from jackify.frontends.gui.services.message_service import MessageService


class ConsoleOutputMixin:
    """Mixin providing console output and scroll tracking for InstallModlistScreen."""

    def _toggle_console_visibility(self, state):
        """R&D: Toggle console visibility only
        
        When "Show Details" is checked:
            - Show Console (below tabs)
            - Expand window height
        When "Show Details" is unchecked:
            - Hide Console
            - Collapse window height
        
        Note: Activity and Process Monitor tabs are always available via tabs.
        """
        is_checked = (state == Qt.Checked)
        
        # Get main window reference (like TTW screen)
        main_window = None
        try:
            app = QApplication.instance()
            if app:
                main_window = app.activeWindow()
                # Try to find the actual main window (parent of stacked widget)
                if self.stacked_widget and self.stacked_widget.parent():
                    main_window = self.stacked_widget.parent()
        except Exception:
            pass
        
        # Save geometry on first expand (like TTW screen)
        if is_checked and main_window and self._saved_geometry is None:
            try:
                self._saved_geometry = main_window.geometry()
                self._saved_min_size = main_window.minimumSize()
            except Exception:
                pass
        
        if is_checked:
            # Keep upper section height consistent - don't change it
            # Prevent buttons from being cut off
            try:
                if hasattr(self, 'upper_section_widget') and self.upper_section_widget is not None:
                    # Maintain consistent height - ALWAYS use the stored fixed height
                    # Never recalculate - use the exact same height calculated in showEvent
                    if hasattr(self, '_upper_section_fixed_height') and self._upper_section_fixed_height is not None:
                        self.upper_section_widget.setMaximumHeight(self._upper_section_fixed_height)
                        self.upper_section_widget.setMinimumHeight(self._upper_section_fixed_height)  # Lock it
                    # If somehow not stored, it should have been set in showEvent - don't recalculate here
                    self.upper_section_widget.updateGeometry()
            except Exception:
                pass
            # Show console
            self.console.setVisible(True)
            self.console.show()
            self.console.setMinimumHeight(200)
            self.console.setMaximumHeight(16777215)  # Remove height limit
            try:
                self.console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                # Set stretch on console in its layout to fill space
                console_layout = self.console.parent().layout()
                if console_layout:
                    console_layout.setStretchFactor(console_layout.indexOf(self.console), 1)
                    # Restore spacing when console is visible
                    console_layout.setSpacing(4)
            except Exception:
                pass
            try:
                # Set spacing in console_and_buttons_layout when console is visible
                if hasattr(self, 'console_and_buttons_layout'):
                    self.console_and_buttons_layout.setSpacing(4)  # Small gap between console and buttons
                # Set stretch on console_and_buttons_widget to fill space when expanded
                if hasattr(self, 'console_and_buttons_widget'):
                    self.main_overall_vbox.setStretchFactor(self.console_and_buttons_widget, 1)
                    # Allow expansion when console is visible - remove fixed height constraint
                    self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                    # Clear fixed height by setting min/max (setFixedHeight sets both, so we override it)
                    self.console_and_buttons_widget.setMinimumHeight(0)
                    self.console_and_buttons_widget.setMaximumHeight(16777215)
                    self.console_and_buttons_widget.updateGeometry()
            except Exception:
                pass
            
            # Notify parent to expand - let main window handle resizing
            try:
                self.resize_request.emit('expand')
            except Exception:
                pass
        else:
            # Keep upper section height consistent - use same constraint
            # Prevent buttons from being cut off
            try:
                if hasattr(self, 'upper_section_widget') and self.upper_section_widget is not None:
                    # Use the same stored fixed height for consistency
                    # ALWAYS use the stored height - never recalculate to avoid drift
                    if hasattr(self, '_upper_section_fixed_height') and self._upper_section_fixed_height is not None:
                        self.upper_section_widget.setMaximumHeight(self._upper_section_fixed_height)
                        self.upper_section_widget.setMinimumHeight(self._upper_section_fixed_height)  # Lock it
                    # If somehow not stored, it should have been set in showEvent - don't recalculate here
                    self.upper_section_widget.updateGeometry()
            except Exception:
                pass
            # Hide console and ensure it takes zero space
            self.console.setVisible(False)
            self.console.setMinimumHeight(0)
            self.console.setMaximumHeight(0)
            # Use Ignored size policy so it doesn't participate in layout calculations
            self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            try:
                # Remove stretch from console_and_buttons_widget when collapsed
                if hasattr(self, 'console_and_buttons_widget'):
                    self.main_overall_vbox.setStretchFactor(self.console_and_buttons_widget, 0)
                    # Set fixed height when console is hidden
                    self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    # Calculate height based on buttons only (console takes 0 space)
                    button_height = 0
                    if hasattr(self, 'console_and_buttons_layout'):
                        for i in range(self.console_and_buttons_layout.count()):
                            item = self.console_and_buttons_layout.itemAt(i)
                            if item and item.widget() and item.widget() != self.console:
                                button_height = max(button_height, item.widget().sizeHint().height())
                    self.console_and_buttons_widget.setFixedHeight(button_height + 8)  # Add small padding
                    # Clear spacing when console is hidden
                    if hasattr(self, 'console_and_buttons_layout'):
                        self.console_and_buttons_layout.setSpacing(0)
            except Exception:
                pass
            
            # Notify parent to collapse - let main window handle resizing
            try:
                self.resize_request.emit('collapse')
            except Exception:
                pass

    def on_installation_output(self, message):
        """Handle regular output from installation thread"""
        # Filter out internal status messages from user console
        if message.strip().startswith('[Jackify]'):
            # Log internal messages to file but don't show in console
            self._write_to_log_file(message)
            return
        
        msg_lower = message.lower()
        # Engine informational line; keep in debug log only to reduce user-facing noise.
        if (
            'contains files with foreign characters' in msg_lower and
            'using proton 7z.exe for extraction' in msg_lower
        ):
            self._write_to_log_file(message)
            return
        
        # Detect known engine bugs and provide helpful guidance
        if 'destination array was not long enough' in msg_lower or \
           ('argumentexception' in msg_lower and 'downloadmachineurl' in msg_lower):
            # Known bug in jackify-engine 0.4.0 during .wabbajack download
            if not hasattr(self, '_array_error_notified'):
                self._array_error_notified = True
                guidance = (
                    "\n[Jackify] Engine Error Detected: Buffer size issue during .wabbajack download.\n"
                    "[Jackify] This is a known bug in jackify-engine 0.4.0.\n"
                    "[Jackify] Workaround: Delete any partial .wabbajack files in your downloads directory and try again.\n"
                )
                self._safe_append_text(guidance)
        
        # Always write output to the console buffer - visibility is controlled by the Show
        # Details checkbox separately, not by whether we write to it
        self._safe_append_text(message)

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
            QTimer.singleShot(100, self._reset_manual_scroll_if_at_bottom)

    def _reset_manual_scroll_if_at_bottom(self):
        """Reset manual scroll flag if user is still at bottom after delay"""
        scrollbar = self.console.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 1:
            self._user_manually_scrolled = False

    def _safe_append_text(self, text):
        """
        Append text with professional auto-scroll behavior.

        Handles carriage return (\\r) for in-place updates and newline (\\n) for new lines.
        """
        # Write all messages to log file (including internal messages)
        self._write_to_log_file(text)

        # Filter out internal status messages from user console display
        if text.strip().startswith('[Jackify]'):
            # Internal messages are logged but not shown in user console
            return

        # Check if this is a carriage return update (should replace last line)
        if '\r' in text and '\n' not in text:
            # Carriage return - replace last line
            self._replace_last_console_line(text.replace('\r', ''))
            return

        # Handle mixed \r\n or just \n - normal append
        # Clean up any remaining \r characters
        clean_text = text.replace('\r', '')

        scrollbar = self.console.verticalScrollBar()
        # Check if user was at bottom BEFORE adding text
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)

        # Add the text
        self.console.append(clean_text)

        # Auto-scroll if user was at bottom and hasn't manually scrolled
        # Re-check bottom state after text addition for better reliability
        if (was_at_bottom and not self._user_manually_scrolled) or \
           (not self._user_manually_scrolled and scrollbar.value() >= scrollbar.maximum() - 2):
            scrollbar.setValue(scrollbar.maximum())
            # Ensure user can still manually scroll up during rapid updates
            if scrollbar.value() == scrollbar.maximum():
                self._was_at_bottom = True

    def _is_similar_progress_line(self, text):
        """Check if this line is a similar progress update to the last line"""
        if not hasattr(self, '_last_console_line') or not self._last_console_line:
            return False

        # Don't deduplicate if either line contains important markers
        important_markers = [
            'complete',
            'failed',
            'error',
            'warning',
            'starting',
            '===',
            '---',
            'SUCCESS',
            'FAILED',
        ]

        text_lower = text.lower()
        last_lower = self._last_console_line.lower()

        for marker in important_markers:
            if marker.lower() in text_lower or marker.lower() in last_lower:
                return False

        # Patterns that indicate this is a progress line that should replace the previous
        # These are the status lines that update rapidly with changing numbers
        progress_patterns = [
            'Installing files',
            'Extracting files',
            'Downloading:',
            'Building BSAs',
            'Validating',
        ]

        # Check if both current and last line contain the same progress pattern
        # AND the lines are actually different (not exact duplicates)
        for pattern in progress_patterns:
            if pattern in text and pattern in self._last_console_line:
                # Only deduplicate if the numbers/progress changed (not exact duplicate)
                if text.strip() != self._last_console_line.strip():
                    return True

        # Special case: texture conversion status is embedded in Installing files lines
        # Match lines like "Installing files X/Y (A/B) - Converting textures: N/M"
        if '- Converting textures:' in text and '- Converting textures:' in self._last_console_line:
            if text.strip() != self._last_console_line.strip():
                return True

        return False

    def _replace_last_console_line(self, text):
        """Replace the last line in the console with new text"""
        scrollbar = self.console.verticalScrollBar()
        was_at_bottom = (scrollbar.value() >= scrollbar.maximum() - 1)

        # Move cursor to end and select the last line
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.LineUnderCursor)
        cursor.removeSelectedText()
        cursor.deletePreviousChar()  # Remove the newline

        # Insert the new text
        self.console.append(text)

        # Track this line
        self._last_console_line = text

        # Restore scroll position
        if was_at_bottom or not self._user_manually_scrolled:
            scrollbar.setValue(scrollbar.maximum())

    def _write_to_log_file(self, message):
        """Write message to workflow log file with timestamp"""
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(self.modlist_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            # Logging should never break the workflow
            pass
