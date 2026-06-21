"""
Main window geometry and resize mixin.
Window flags, save/restore geometry, compact mode, responsive minimum, resize handling.
"""

from PySide6.QtWidgets import QMainWindow, QApplication
from PySide6.QtCore import Qt, QTimer, QRect

from jackify.frontends.gui.utils import get_screen_geometry, set_responsive_minimum
import logging

logger = logging.getLogger(__name__)
ENABLE_WINDOW_HEIGHT_ANIMATION = False

class MainWindowGeometryMixin:
    """Mixin for window geometry, save/restore, compact mode, and resize behavior."""

    def _apply_standard_window_flags(self):
        window_flags = self.windowFlags()
        window_flags |= (
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        window_flags &= ~Qt.CustomizeWindowHint
        self.setWindowFlags(window_flags)

    def _restore_geometry(self):
        width, height = self._calculate_initial_window_size()
        height = min(height, self._compact_height)
        self.resize(width, height)
        self._center_on_screen(width, height)

    def _save_geometry_on_quit(self):
        if self._is_compact_mode():
            self._save_geometry()
        else:
            from PySide6.QtCore import QSettings
            settings = QSettings("Jackify", "Jackify")
            settings.remove("windowGeometry")

    def _is_compact_mode(self) -> bool:
        try:
            if hasattr(self, 'wabbajack_installer_screen') and hasattr(self.wabbajack_installer_screen, 'show_details_checkbox'):
                if self.wabbajack_installer_screen.show_details_checkbox.isChecked():
                    return False
            if hasattr(self, 'install_mo2_screen') and hasattr(self.install_mo2_screen, 'show_details_checkbox'):
                if self.install_mo2_screen.show_details_checkbox.isChecked():
                    return False
            if hasattr(self, 'install_modlist_screen') and hasattr(self.install_modlist_screen, 'show_details_checkbox'):
                if self.install_modlist_screen.show_details_checkbox.isChecked():
                    return False
            if hasattr(self, 'install_ttw_screen') and hasattr(self.install_ttw_screen, 'show_details_checkbox'):
                if self.install_ttw_screen.show_details_checkbox.isChecked():
                    return False
            if hasattr(self, 'configure_new_modlist_screen') and hasattr(self.configure_new_modlist_screen, 'show_details_checkbox'):
                if self.configure_new_modlist_screen.show_details_checkbox.isChecked():
                    return False
            if hasattr(self, 'configure_existing_modlist_screen') and hasattr(self.configure_existing_modlist_screen, 'show_details_checkbox'):
                if self.configure_existing_modlist_screen.show_details_checkbox.isChecked():
                    return False
        except Exception:
            pass
        return True

    def _save_geometry(self):
        from PySide6.QtCore import QSettings
        settings = QSettings("Jackify", "Jackify")
        settings.setValue("windowGeometry", self.saveGeometry())

    def apply_responsive_minimum(self, min_width: int = 1100, min_height: int = 600):
        set_responsive_minimum(self, min_width=min_width, min_height=min_height, margin=self._window_margin)

    def _calculate_initial_window_size(self):
        _, _, screen_width, screen_height = get_screen_geometry(self)
        if not screen_width or not screen_height:
            return (self._base_min_width, self._base_min_height)
        width = min(
            max(self._base_min_width, int(screen_width * 0.85)),
            screen_width - self._window_margin
        )
        height = min(
            max(self._base_min_height, int(screen_height * 0.75)),
            screen_height - self._window_margin
        )
        return (width, height)

    def _center_on_screen(self, width: int, height: int):
        _, _, screen_width, screen_height = get_screen_geometry(self)
        if not screen_width or not screen_height:
            return
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.move(x, y)

    def _ensure_within_available_geometry(self):
        from PySide6.QtCore import QRect
        _, _, screen_width, screen_height = get_screen_geometry(self)
        if not screen_width or not screen_height:
            return
        current_geometry = self.geometry()
        new_width = min(current_geometry.width(), screen_width - self._window_margin)
        new_height = min(current_geometry.height(), screen_height - self._window_margin)
        new_width = max(new_width, self.minimumWidth())
        new_height = max(new_height, self.minimumHeight())
        new_x = min(max(current_geometry.x(), 0), screen_width - new_width)
        new_y = min(max(current_geometry.y(), 0), screen_height - new_height)
        self.setGeometry(new_x, new_y, new_width, new_height)

    def _on_resize_event_geometry(self, event):
        super().resizeEvent(event)
        if self._is_compact_mode():
            if not hasattr(self, '_geometry_save_timer'):
                self._geometry_save_timer = QTimer()
                self._geometry_save_timer.setSingleShot(True)
                self._geometry_save_timer.timeout.connect(self._save_geometry)
            self._geometry_save_timer.stop()
            self._geometry_save_timer.start(500)

    def _geometry_show_event(self, event):
        super().showEvent(event)
        if not self._initial_show_adjusted:
            self._initial_show_adjusted = True
            if not (hasattr(self, 'system_info') and self.system_info.is_steamdeck):
                self.setWindowState(Qt.WindowNoState)
                self.apply_responsive_minimum(self._base_min_width, self._base_min_height)
                self._ensure_within_available_geometry()

    def _maintain_fullscreen_on_deck(self, index):
        if hasattr(self, 'system_info') and self.system_info.is_steamdeck:
            if not self.isMaximized():
                self.showMaximized()

    def _on_child_resize_request(self, mode: str):
        logger.debug(f"_on_child_resize_request called with mode='{mode}', current_size={self.size()}")
        try:
            if self.system_info and self.system_info.is_steamdeck:
                logger.debug("Steam Deck detected, ignoring resize request")
                try:
                    if hasattr(self, 'install_ttw_screen') and self.install_ttw_screen.show_details_checkbox:
                        self.install_ttw_screen.show_details_checkbox.setVisible(False)
                except Exception:
                    pass
                return
        except Exception:
            pass
        if mode == "expand":
            target_height = self._compact_height + self._details_extra_height
            self._resize_height(target_height)
        elif mode == "collapse" or mode == "compact":
            self._resize_height(self._compact_height)
        else:
            self.apply_responsive_minimum(self._base_min_width, self._base_min_height)

    def _resize_height(self, requested_height: int):
        target_height = self._clamp_height_to_screen(requested_height)
        self.apply_responsive_minimum(self._base_min_width, self._base_min_height)
        if ENABLE_WINDOW_HEIGHT_ANIMATION:
            self._animate_height(target_height)
            return
        geom = self.geometry()
        new_y = geom.y()
        _, _, _, screen_height = get_screen_geometry(self)
        max_bottom = max(self._base_min_height, screen_height - self._window_margin)
        if new_y + target_height > max_bottom:
            new_y = max(0, max_bottom - target_height)
        self._programmatic_resize = True
        self.setGeometry(geom.x(), new_y, geom.width(), target_height)
        QTimer.singleShot(100, lambda: setattr(self, '_programmatic_resize', False))

    def _clamp_height_to_screen(self, requested_height: int) -> int:
        _, _, _, screen_height = get_screen_geometry(self)
        available = max(self._base_min_height, screen_height - self._window_margin)
        return max(self._base_min_height, min(requested_height, available))

    def _animate_height(self, target_height: int, duration_ms: int = 180):
        try:
            from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect
        except Exception:
            before = self.size()
            self._programmatic_resize = True
            self.resize(self.size().width(), target_height)
            logger.debug(f"Animated fallback resize from {before} to {self.size()}")
            QTimer.singleShot(100, lambda: setattr(self, '_programmatic_resize', False))
            return
        start_rect = self.geometry()
        end_rect = QRect(start_rect.x(), start_rect.y(), start_rect.width(), self._clamp_height_to_screen(target_height))
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            would_be_bottom = start_rect.y() + target_height
            if would_be_bottom > screen_geometry.bottom():
                new_y = screen_geometry.bottom() - target_height
                if new_y < screen_geometry.top():
                    new_y = screen_geometry.top()
                end_rect.moveTop(new_y)
        self._resize_anim = QPropertyAnimation(self, b"geometry")
        self._resize_anim.setDuration(duration_ms)
        self._resize_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._resize_anim.setStartValue(start_rect)
        self._resize_anim.setEndValue(end_rect)
        self._programmatic_resize = True
        self._resize_anim.finished.connect(lambda: setattr(self, '_programmatic_resize', False))
        self._resize_anim.start()
