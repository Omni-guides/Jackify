"""
Modlist Properties popout for the Lifecycle Dashboard.

Reuses modlist_gallery_detail.py's structural pattern (full-width banner image with an
overlaid text panel, content body below) instead of inventing a fourth dialog shape - this is
Jackify's "Properties" screen the same way Steam has one: management actions (Reconfigure,
artwork, Proton version, Uninstall), not a launch surface. Launch stays on the dashboard card
itself as a small overlay icon.
"""
import logging
from typing import Optional

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from jackify.backend.models.game_types import GAME_DISPLAY_NAMES
from jackify.backend.services.dashboard_images import (
    get_cached_image_path,
    get_modlist_specific_art_path,
    get_steam_grid_art_path,
    save_image_from_path,
)
from jackify.backend.services.crash_log_service import get_extender_name, supports_crash_logs
from jackify.backend.services.dashboard_status import STATUS_UPDATE_AVAILABLE
from jackify.backend.services.install_registry import InstallEntry
from ..services.message_service import MessageService
from ..shared_theme import COLOR_BTN_BACK, COLOR_BTN_INSTALL, JACKIFY_COLOR_BLUE
from ..utils import get_screen_geometry, set_responsive_minimum

logger = logging.getLogger(__name__)


class _BannerLabel(QLabel):
    """Banner that re-crops on its own resize - the dialog's resizeEvent fires before the
    layout has resized this label, so cropping from there uses a stale width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source: Optional[QPixmap] = None

    def set_source(self, pixmap: Optional[QPixmap]):
        self._source = pixmap
        self._rescale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._source is None or self._source.isNull():
            return
        target = self.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = self._source.scaled(
            target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        x = max(0, (scaled.width() - target.width()) // 2)
        y = max(0, (scaled.height() - target.height()) // 2)
        cropped = scaled.copy(x, y, target.width(), target.height())

        # A center-crop against the dialog's flush top edge (no titlebar gap) reads as an
        # abrupt cut, especially when the source art has content near its own top edge - a
        # short fade into black eases the transition without a hard line.
        fade_height = min(40, target.height())
        if fade_height > 0:
            painter = QPainter(cropped)
            gradient = QLinearGradient(0, 0, 0, fade_height)
            gradient.setColorAt(0.0, QColor(0, 0, 0, 140))
            gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(0, 0, target.width(), fade_height, gradient)
            painter.end()

        self.setPixmap(cropped)


class _ElidedValueLabel(QLabel):
    """Single-line detail value: elided to fit, full text on hover, click to copy.

    Never wraps - a wrapped path makes the row height depend on path length and dialog width,
    which clipped the grid. Elides in the middle to keep the drive root and the folder name.
    """
    clicked = Signal()

    def __init__(self, text: str, copy_text: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._full_text = text
        # Hover shows what a click will copy
        self.setToolTip(copy_text if copy_text is not None else text)
        self.setCursor(Qt.PointingHandCursor)
        # Ignored width, or a long path widens the dialog instead of eliding
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(self.fontMetrics().height() + 2)
        self._apply_elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self):
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, max(0, self.width()))
        if elided != self.text():
            super().setText(elided)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# Same rationale as playbook_automation_controller.py's _ORPHANED_WORKERS: this dialog is
# short-lived and can be closed while a background thread is still running (Proton change,
# Run Verification). Both threads below are constructed unparented (never parent=self) so
# Qt's C++ ownership can't tear one down mid-run when the dialog itself is destroyed - this
# set is the Python-side equivalent, keeping a live reference until the thread actually
# finishes instead of letting it get garbage collected the moment the dialog closes.
_ORPHANED_THREADS: set = set()


def _park_if_running(thread: Optional[QThread]) -> None:
    if thread is not None and thread.isRunning():
        _ORPHANED_THREADS.add(thread)
        thread.finished.connect(lambda t=thread: _ORPHANED_THREADS.discard(t))


class _ProtonChangeThread(QThread):
    finished_change = Signal(bool, str)

    def __init__(self, appid: str, proton_version: str, parent=None):
        super().__init__(parent)
        self._appid = appid
        self._proton_version = proton_version

    def run(self):
        from jackify.backend.services.modlist_properties_service import change_proton_version
        try:
            success, message = change_proton_version(self._appid, self._proton_version)
        except Exception as e:
            logger.error("Proton version change failed: %s", e, exc_info=True)
            success, message = False, str(e)
        self.finished_change.emit(success, message)


class ModlistPropertiesDialog(QDialog):
    """install_id, action - reuses the same action vocabulary the dashboard card used to emit
    directly (configure/open_dir/uninstall), so the dashboard's existing dispatch handles it
    unchanged. Artwork and Proton version are handled entirely inside this dialog instead, since
    neither needs the dashboard's own navigation or threaded uninstall flow."""
    action_requested = Signal(str, str)
    artwork_changed = Signal(str)  # install_id - card thumbnail needs a refresh

    def __init__(self, entry: InstallEntry, status_text: str, proton_version: Optional[str],
                 status: str = "", parent=None):
        super().__init__(parent)
        self._entry = entry
        self._status = status
        self._proton_thread: Optional[_ProtonChangeThread] = None
        self._verify_thread: Optional["VerifierThread"] = None
        self._copy_hint: Optional[QLabel] = None
        self.setWindowTitle(entry.modlist_name)
        set_responsive_minimum(self, min_width=640, min_height=560)
        self._apply_initial_size()
        self._setup_ui(status_text, proton_version)

    def done(self, result):
        """Funnel point for accept()/reject()/window-close alike. A running background
        thread must survive the dialog closing - see _ORPHANED_THREADS above."""
        _park_if_running(self._proton_thread)
        _park_if_running(self._verify_thread)
        super().done(result)

    def _apply_initial_size(self):
        _, _, screen_width, screen_height = get_screen_geometry(self)
        width, height = 700, 640
        if screen_width:
            width = min(width, max(640, screen_width - 40))
        if screen_height:
            height = min(height, max(560, screen_height - 40))
        self.resize(width, height)

    def _setup_ui(self, status_text: str, proton_version: Optional[str]):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        banner_container = QFrame()
        banner_container.setFrameShape(QFrame.NoFrame)
        banner_container.setStyleSheet("background: #000; border: none;")
        banner_layout = QVBoxLayout()
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.setSpacing(0)
        banner_container.setLayout(banner_layout)

        self.banner_label = _BannerLabel()
        self.banner_label.setMinimumHeight(140)
        self.banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Not setScaledContents - it fills by distorting. Scaled to cover and cropped instead.
        self.banner_label.setStyleSheet("background: #1a1a1a; border: none;")
        self.banner_label.setAlignment(Qt.AlignCenter)
        self._refresh_banner()
        banner_layout.addWidget(self.banner_label, stretch=1)

        # Body below is sized to its own content (stretch=0) - any leftover dialog height goes
        # to the banner instead of being spread as blank gaps between body's own rows.
        main_layout.addWidget(banner_container, stretch=1)

        body = QWidget()
        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(24, 8, 24, 10)
        body_layout.setSpacing(10)
        body.setLayout(body_layout)

        # Title sits below the artwork rather than on it. The Dashboard image is user-supplied
        # and often not a wide banner, so a panel over a fixed-height crop read as a black bar
        # cutting the image rather than as an overlay.
        title = QLabel(self._entry.modlist_name)
        title.setFont(QFont("Sans", 20, QFont.Bold))
        title.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE};")
        title.setWordWrap(True)

        game_display = GAME_DISPLAY_NAMES.get(self._entry.game_type, self._entry.game_type) if self._entry.game_type else "Unknown game"
        subtitle_bits = [game_display, status_text]
        if self._entry.installed_version:
            subtitle_bits.insert(1, f"v{self._entry.installed_version}")
        subtitle = QLabel(" · ".join(subtitle_bits))
        subtitle.setStyleSheet("color: #ccc; font-size: 13px;")

        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(title)
        heading.addWidget(subtitle)
        body_layout.addLayout(heading)

        body_layout.addWidget(self._build_details_section())

        proton_row = QHBoxLayout()
        proton_row.setSpacing(8)
        proton_row.addWidget(QLabel("Proton Version:"))
        self._proton_combo = QComboBox()
        self._populate_proton_combo(proton_version)
        proton_row.addWidget(self._proton_combo, stretch=1)
        self._proton_apply_btn = QPushButton("Apply")
        self._proton_apply_btn.setEnabled(bool(self._entry.appid))
        self._proton_apply_btn.clicked.connect(self._on_apply_proton)
        proton_row.addWidget(self._proton_apply_btn)
        body_layout.addLayout(proton_row)
        self._proton_status_label = QLabel("")
        self._proton_status_label.setStyleSheet("color: #999; font-size: 11px;")
        # An empty QLabel still reserves its line-height - hidden until there is a real
        # status message to show, so it does not leave a permanent blank gap.
        self._proton_status_label.setVisible(False)
        body_layout.addWidget(self._proton_status_label)

        # Smaller font on this row and the one below - at the default size these buttons
        # truncated on the Steam Deck's smaller effective width (found live 2026-08-29).
        _ACTION_BTN_FONT = "font-size: 12px;"

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        artwork_btn = QPushButton("Change Dashboard Image...")
        artwork_btn.setStyleSheet(_ACTION_BTN_FONT)
        artwork_btn.setToolTip(
            "Change the image shown on this modlist's Dashboard card.\n"
            "Does not affect the artwork Steam shows for the shortcut."
        )
        artwork_btn.clicked.connect(self._on_change_artwork)
        action_row.addWidget(artwork_btn)
        reconfigure_btn = QPushButton("Reconfigure")
        reconfigure_btn.setStyleSheet(_ACTION_BTN_FONT)
        reconfigure_btn.clicked.connect(self._on_reconfigure)
        action_row.addWidget(reconfigure_btn)
        open_dir_btn = QPushButton("Open Install Directory")
        open_dir_btn.setStyleSheet(_ACTION_BTN_FONT)
        open_dir_btn.clicked.connect(self._on_open_dir)
        action_row.addWidget(open_dir_btn)
        if supports_crash_logs(self._entry.game_type):
            extender = get_extender_name(self._entry.game_type)
            open_logs_btn = QPushButton(f"Open {extender} Log Directory")
            open_logs_btn.setStyleSheet(_ACTION_BTN_FONT)
            open_logs_btn.clicked.connect(self._on_open_extender_logs)
            action_row.addWidget(open_logs_btn)
        body_layout.addLayout(action_row)

        bottom_row = QHBoxLayout()
        uninstall_btn = QPushButton("Uninstall this list")
        uninstall_btn.setStyleSheet(
            "QPushButton { background-color: #7a2020; color: white; border: none; border-radius: 4px; "
            "font-weight: bold; font-size: 12px; padding: 8px 16px; } "
            "QPushButton:hover { background-color: #942828; }"
        )
        uninstall_btn.clicked.connect(self._on_uninstall)
        bottom_row.addWidget(uninstall_btn)
        remove_btn = QPushButton("Remove from List")
        remove_btn.setToolTip(
            "Removes this modlist from Jackify's tracked list only.\n"
            "The Steam shortcut, Proton prefix and files are left untouched."
        )
        remove_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_BTN_BACK}; color: white; border: none; "
            "border-radius: 4px; font-weight: bold; font-size: 12px; padding: 8px 16px; } "
            "QPushButton:hover { background-color: #5a6578; }"
        )
        remove_btn.clicked.connect(self._on_remove_from_list)
        bottom_row.addWidget(remove_btn)
        # Permanent, not conditional - greyed out when no update is available rather than
        # appearing/disappearing, so its position is predictable.
        update_btn = QPushButton("Update")
        update_btn.setToolTip("Reinstall to the newer version available on the gallery.")
        update_btn.setEnabled(self._status == STATUS_UPDATE_AVAILABLE)
        update_btn.setStyleSheet(
            f"QPushButton {{ background-color: {JACKIFY_COLOR_BLUE}; color: white; "
            "border: none; border-radius: 4px; font-weight: bold; font-size: 12px; padding: 8px 16px; } "
            "QPushButton:hover:enabled { background-color: #5a8fd6; } "
            "QPushButton:disabled { background-color: #333; color: #666; }"
        )
        update_btn.clicked.connect(self._on_update)
        bottom_row.addWidget(update_btn)
        verify_btn = QPushButton("Run Verification")
        verify_btn.setToolTip("Check this modlist's install for common configuration problems.")
        verify_btn.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_BTN_INSTALL}; color: white; "
            "border: none; border-radius: 4px; font-weight: bold; font-size: 12px; padding: 8px 16px; } "
            "QPushButton:hover { background-color: #2a75c8; }"
        )
        verify_btn.clicked.connect(self._on_run_verification)
        bottom_row.addWidget(verify_btn)
        bottom_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_ACTION_BTN_FONT)
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)
        body_layout.addLayout(bottom_row)

        main_layout.addWidget(body, stretch=0)
        self.setLayout(main_layout)

    def _build_details_section(self) -> QWidget:
        """Two-column label/value grid of what Jackify knows about this install."""
        from jackify.backend.services.modlist_properties_details import build_detail_fields

        container = QFrame()
        container.setStyleSheet(
            "QFrame { background-color: #232323; border: 1px solid #383838; border-radius: 6px; }"
        )
        # Preferred lets the frame squeeze below its sizeHint and clip every row
        container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        grid = QGridLayout()
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        container.setLayout(grid)

        try:
            fields = build_detail_fields(self._entry)
        except Exception as e:
            logger.error("Could not build properties detail fields: %s", e, exc_info=True)
            fields = []

        for row, field in enumerate(fields):
            label = QLabel(f"{field.label}:")
            label.setStyleSheet("color: #999; font-size: 12px; border: none;")
            if field.hint:
                label.setToolTip(field.hint)
            grid.addWidget(label, row, 0)

            value = _ElidedValueLabel(field.display, copy_text=field.copy_value)
            if field.hint:
                value.setToolTip(f"{field.copy_value}\n\n{field.hint}")
            value.setStyleSheet("color: #ddd; font-size: 12px; border: none;")
            value.clicked.connect(
                lambda text=field.copy_value, name=field.label: self._copy_detail(name, text)
            )
            grid.addWidget(value, row, 1)

        self._copy_hint = QLabel("Click any value to copy it")
        self._copy_hint.setStyleSheet("color: #777; font-size: 11px; border: none;")
        grid.addWidget(self._copy_hint, len(fields), 0, 1, 2)

        return container

    def _copy_detail(self, field_name: str, text: str):
        """Copy a detail value and confirm in place."""
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._copy_hint.setText(f"Copied {field_name} to clipboard")
        self._copy_hint.setStyleSheet(
            f"color: {JACKIFY_COLOR_BLUE}; font-size: 11px; border: none;"
        )
        QTimer.singleShot(2000, self._reset_copy_hint)

    def _reset_copy_hint(self):
        if self._copy_hint is None:
            return
        try:
            self._copy_hint.setText("Click any value to copy it")
            self._copy_hint.setStyleSheet("color: #777; font-size: 11px; border: none;")
        except RuntimeError:
            # Dialog closed inside the 2s window
            self._copy_hint = None

    def _refresh_banner(self):
        # Same source order as the Dashboard card. Checking only the cached image made the
        # popout claim there was no artwork for a modlist whose card was showing some.
        for source in (
            get_cached_image_path(self._entry.install_id),
            get_modlist_specific_art_path(self._entry.install_dir),
            get_steam_grid_art_path(self._entry.appid) if self._entry.appid else None,
        ):
            if not source:
                continue
            pixmap = QPixmap(str(source))
            if not pixmap.isNull():
                self.banner_label.set_source(pixmap)
                return
        self.banner_label.set_source(None)
        self.banner_label.setPixmap(QPixmap())
        self.banner_label.setText("No artwork set")
        self.banner_label.setStyleSheet(
            "background: #1a1a1a; border: none; color: #666; font-size: 14px;"
        )

    def _populate_proton_combo(self, current: Optional[str]):
        from jackify.backend.services.modlist_properties_service import list_available_proton_versions
        versions = list_available_proton_versions()
        if current and current not in versions:
            versions = [current] + versions
        self._proton_combo.addItems(versions or (["Unknown"] if not current else [current]))
        if current:
            idx = self._proton_combo.findText(current)
            if idx >= 0:
                self._proton_combo.setCurrentIndex(idx)

    def _on_apply_proton(self):
        version = self._proton_combo.currentText()
        if not version or not self._entry.appid:
            return
        from jackify.shared.messages import STEAM_RESTART_WARNING
        reply = MessageService.question(
            self,
            "Restart Steam?",
            f"Changing the Proton version requires restarting Steam.\n\n{STEAM_RESTART_WARNING} Continue?",
            safety_level="medium",
        )
        if reply == QMessageBox.No:
            return
        self._proton_apply_btn.setEnabled(False)
        self._proton_status_label.setText("Applying (Steam will restart)...")
        self._proton_status_label.setVisible(True)
        # Unparented deliberately - see _ORPHANED_THREADS above.
        self._proton_thread = _ProtonChangeThread(self._entry.appid, version)
        self._proton_thread.finished_change.connect(self._on_proton_changed)
        self._proton_thread.start()

    def _on_proton_changed(self, success: bool, message: str):
        self._proton_apply_btn.setEnabled(True)
        if success:
            self._proton_status_label.setText(message or "Proton version updated.")
        else:
            self._proton_status_label.setText(f"Failed: {message}")

    def _on_change_artwork(self):
        from pathlib import Path
        start_dir = str(Path.home() / "Downloads")
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose artwork for \"{self._entry.modlist_name}\"",
            start_dir, "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        if save_image_from_path(self._entry.install_id, path) is None:
            return
        self._refresh_banner()
        self.artwork_changed.emit(self._entry.install_id)

    def _on_reconfigure(self):
        self.action_requested.emit(self._entry.install_id, "configure")
        self.accept()

    def _on_run_verification(self):
        """Same verifier as Additional Tasks & Tools' Run Install Verifier, minus the modlist
        picker step - this dialog already identifies which modlist."""
        from jackify.backend.services.install_verifier_service import resolve_pfx_for_appid

        pfx = resolve_pfx_for_appid(self._entry.appid) if self._entry.appid else None
        if not pfx:
            MessageService.warning(
                self, "Prefix Not Found",
                f"The Proton prefix for '{self._entry.modlist_name}' was not found.\n\n"
                "Launch the modlist from Steam at least once to create the prefix.",
            )
            return

        from pathlib import Path
        from ..screens.install_verifier_mixin import VerifierThread

        progress_dlg = QDialog(self)
        progress_dlg.setWindowTitle("Verifying...")
        progress_dlg.setModal(True)
        prog_layout = QVBoxLayout(progress_dlg)
        prog_layout.addWidget(QLabel(
            f"Running verifier for '{self._entry.modlist_name}'...\nThis may take a moment."
        ))
        progress_dlg.setFixedSize(340, 100)
        progress_dlg.show()

        # Unparented deliberately - see _ORPHANED_THREADS above.
        self._verify_thread = VerifierThread(
            pfx, Path(self._entry.install_dir), self._entry.game_type, self._entry.appid,
            self._entry.modlist_name,
        )

        def _on_done(results):
            progress_dlg.accept()
            self._verify_thread = None
            if results is None:
                MessageService.critical(
                    self, "Verifier Error",
                    "The verifier encountered an error and could not complete.",
                )
                return
            from .verification_results_dialog import VerificationResultsDialog
            dlg = VerificationResultsDialog(results, parent=self)
            dlg.exec()

        self._verify_thread.finished.connect(_on_done)
        self._verify_thread.start()

    def _on_update(self):
        self.action_requested.emit(self._entry.install_id, "update")
        self.accept()

    def _on_open_dir(self):
        self.action_requested.emit(self._entry.install_id, "open_dir")

    def _on_open_extender_logs(self):
        self.action_requested.emit(self._entry.install_id, "open_extender_logs")

    def _on_uninstall(self):
        # Confirmation (typed DELETE) happens on the dashboard side, same as it did when
        # Uninstall lived in the card's own "..." menu - not duplicated here.
        self.action_requested.emit(self._entry.install_id, "uninstall")
        self.accept()

    def _on_remove_from_list(self):
        # Confirmation happens on the dashboard side, same as Uninstall above.
        self.action_requested.emit(self._entry.install_id, "remove_from_list")
        self.accept()
