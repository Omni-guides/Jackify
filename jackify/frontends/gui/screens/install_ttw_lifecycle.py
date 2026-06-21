"""Window lifecycle and resize handlers for InstallTTWScreen (Mixin)."""
from PySide6.QtCore import QTimer, QSize, Qt
from PySide6.QtGui import QResizeEvent
import logging
logger = logging.getLogger(__name__)
from ..utils import set_responsive_minimum

class TTWLifecycleMixin:
    """Mixin providing window lifecycle and resize management for InstallTTWScreen."""

    def force_collapsed_state(self):
        """Force the screen into its collapsed state regardless of prior layout.

        This is used to resolve timing/race conditions when navigating here from
        the end of the Install Modlist workflow, ensuring the UI opens collapsed
        just like when launched from Additional Tasks.
        """
        try:
            from PySide6.QtCore import Qt as _Qt
            # Ensure checkbox is unchecked without emitting user-facing signals
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            # Apply collapsed layout explicitly
            self._toggle_console_visibility(_Qt.Unchecked)
            # Inform parent window to collapse height
            try:
                self.resize_request.emit('collapse')
            except Exception:
                pass
        except Exception:
            pass

    def resizeEvent(self, event):
        """Handle window resize to prioritize form over console"""
        super().resizeEvent(event)
        self._adjust_console_for_form_priority()

    def _adjust_console_for_form_priority(self):
        """Console now dynamically fills available space with stretch=1, no manual calculation needed"""
        # The console automatically fills remaining space due to stretch=1 in the layout
        # Remove any fixed height constraints to allow natural stretching
        self.console.setMaximumHeight(16777215)  # Reset to default maximum
        # Only enforce a small minimum when details are shown; keep 0 when collapsed
        if self.console.isVisible():
            self.console.setMinimumHeight(50)
        else:
            self.console.setMinimumHeight(0)

    def showEvent(self, event):
        """Called when the widget becomes visible"""
        super().showEvent(event)
        logger.debug(f"TTW showEvent - integration_mode={self._integration_mode}")
        
        # Check TTW_Linux_Installer status asynchronously (non-blocking) after screen opens
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._check_ttw_installer_status)

        # Ensure initial collapsed layout each time this screen is opened
        try:
            from PySide6.QtCore import Qt as _Qt
            # On Steam Deck: keep expanded layout and hide the details toggle
            try:
                is_steamdeck = False
                # Check our own system_info first
                if self.system_info and getattr(self.system_info, 'is_steamdeck', False):
                    is_steamdeck = True
                # Fallback to checking parent window's system_info
                elif not self.system_info:
                    parent = self.window()
                    if parent and hasattr(parent, 'system_info') and getattr(parent.system_info, 'is_steamdeck', False):
                        is_steamdeck = True

                if is_steamdeck:
                    logger.debug("Steam Deck detected, keeping expanded")
                    # Force expanded state and hide checkbox
                    if self.show_details_checkbox.isVisible():
                        self.show_details_checkbox.setVisible(False)
                    # Show console with proper sizing for Steam Deck
                    self.console.setVisible(True)
                    self.console.show()
                    self.console.setMinimumHeight(200)
                    self.console.setMaximumHeight(16777215)  # Remove height limit
                    return
            except Exception as e:
                logger.debug(f"Steam Deck check exception: {e}")
                pass
            logger.debug(f"Checkbox checked={self.show_details_checkbox.isChecked()}")
            if self.show_details_checkbox.isChecked():
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
            
            logger.debug("Calling _toggle_console_visibility(Unchecked)")
            self._toggle_console_visibility(_Qt.Unchecked)
            # Force the window to compact height to eliminate bottom whitespace
            main_window = self.window()
            logger.debug(f"main_window={main_window}, size={main_window.size() if main_window else None}")
            if main_window:
                # Save original geometry once
                if self._saved_geometry is None:
                    self._saved_geometry = main_window.geometry()
                    logger.debug(f"Saved geometry: {self._saved_geometry}")
                if self._saved_min_size is None:
                    self._saved_min_size = main_window.minimumSize()
                    logger.debug(f"Saved min size: {self._saved_min_size}")

                # Fixed compact size - same as menu screens
                from PySide6.QtCore import QSize
                # On Steam Deck, keep fullscreen; on other systems, set normal window state
                if not (hasattr(main_window, 'system_info') and main_window.system_info.is_steamdeck):
                    main_window.showNormal()
                # First, completely unlock the window
                main_window.setMinimumSize(QSize(0, 0))
                main_window.setMaximumSize(QSize(16777215, 16777215))
                # Only set minimum size - DO NOT RESIZE
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
                # Notify parent to ensure compact
                try:
                    self.resize_request.emit('collapse')
                    logger.debug("Emitted resize_request collapse signal")
                except Exception as e:
                    logger.debug(f"Exception emitting signal: {e}")
                    pass
        except Exception as e:
            logger.debug(f"showEvent exception: {e}")
            import traceback
            logger.debug(f"{traceback.format_exc()}")
            pass

    def hideEvent(self, event):
        """Called when the widget becomes hidden - restore window size constraints"""
        super().hideEvent(event)
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                # Clear any size constraints that might have been set to prevent affecting other screens
                # Important when console is expanded
                main_window.setMaximumSize(QSize(16777215, 16777215))
                main_window.setMinimumSize(QSize(0, 0))
                logger.debug("Install TTW hideEvent - cleared window size constraints")
        except Exception as e:
            logger.debug(f"hideEvent exception: {e}")
            pass

