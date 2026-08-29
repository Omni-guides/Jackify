"""
Shared back/cancel behavior for screens with Show Details.

All screens that have a Cancel/Back button and optional Show Details checkbox
should use this mixin so the main window consistently collapses when leaving.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QSizePolicy
from ..utils import set_responsive_minimum


class ScreenBackMixin:
    """
    Mixin providing shared go_back() and collapse_show_details_before_leave().

    Requires on self: resize_request (Signal(str)), stacked_widget, main_menu_index.
    Optional: show_details_checkbox, _toggle_console_visibility (for collapse).
    """

    def request_return_target(self, index):
        """
        One-shot override for the next go_back() call, then cleared.

        Lets a screen reachable from more than one place (e.g. Configure Existing from both
        the Modlist Tasks menu and the Lifecycle Dashboard) return to wherever it was actually
        opened from instead of always landing on main_menu_index. The caller that navigates
        here via the *normal* route must clear any stale override left over from a previous
        visit via the special route - see modlist_tasks.py's configure_existing_modlist branch.
        """
        self._return_target_override = index

    def go_back(self):
        """Navigate back to main menu (or a one-shot override target) and request main window
        collapse."""
        self.resize_request.emit("collapse")
        try:
            main_window = self.window()
            if main_window:
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
        except Exception:
            pass
        if getattr(self, "stacked_widget", None) is not None:
            target = getattr(self, "_return_target_override", None)
            self._return_target_override = None
            self.stacked_widget.setCurrentIndex(target if target is not None else self.main_menu_index)

    def collapse_show_details_before_leave(self):
        """
        If Show Details is expanded, collapse it so the main window shrinks
        before we leave. Call this from cancel_and_cleanup (or any exit path)
        before go_back().
        """
        main_window = self.window()
        is_steamdeck = bool(
            getattr(main_window, "system_info", None)
            and getattr(main_window.system_info, "is_steamdeck", False)
        )
        if not hasattr(self, "show_details_checkbox") or not self.show_details_checkbox.isChecked():
            return
        self.show_details_checkbox.blockSignals(True)
        self.show_details_checkbox.setChecked(False)
        self.show_details_checkbox.blockSignals(False)
        if not is_steamdeck and hasattr(self, "_toggle_console_visibility"):
            self._toggle_console_visibility(Qt.Unchecked)

    def force_collapsed_details_state(self, resize_mode: str = "compact"):
        """
        Normalize Show Details state when a screen is opened/reset.

        Some screens still manage console visibility locally instead of through a
        single shared widget module. This helper forces the collapsed state in a
        way that is safe across those implementations.
        """
        try:
            if hasattr(self, "show_details_checkbox"):
                self.show_details_checkbox.blockSignals(True)
                self.show_details_checkbox.setChecked(False)
                self.show_details_checkbox.blockSignals(False)
        except Exception:
            pass

        try:
            if hasattr(self, "console"):
                self.console.setVisible(False)
                self.console.setMinimumHeight(0)
                self.console.setMaximumHeight(0)
                self.console.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        except Exception:
            pass

        try:
            if hasattr(self, "console_and_buttons_widget"):
                self.console_and_buttons_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.console_and_buttons_widget.setFixedHeight(50)
                self.console_and_buttons_widget.updateGeometry()
        except Exception:
            pass

        try:
            if hasattr(self, "main_overall_vbox") and hasattr(self, "console"):
                self.main_overall_vbox.setStretchFactor(self.console, 0)
        except Exception:
            pass

        try:
            if hasattr(self, "resize_request"):
                self.resize_request.emit(resize_mode)
        except Exception:
            pass
