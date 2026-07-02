"""
Additional Tasks & Tools Screen

Additional tools and automation. Follows the same pattern as ModlistTasksScreen.
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from jackify.backend.models.configuration import SystemInfo
from ..shared_theme import JACKIFY_COLOR_BLUE
from ..utils import set_responsive_minimum
from ..mixins.thread_lifecycle_mixin import ThreadLifecycleMixin

logger = logging.getLogger(__name__)


class AdditionalTasksScreen(ThreadLifecycleMixin, QWidget):
    """Additional Tasks screen for automation and standalone tools."""

    def __init__(self, stacked_widget=None, main_menu_index=0, system_info: Optional[SystemInfo] = None,
                 install_mo2_screen_index: int = 9):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.main_menu_index = main_menu_index
        self.system_info = system_info or SystemInfo(is_steamdeck=False)
        self.install_mo2_screen_index = install_mo2_screen_index
        
        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface following ModlistTasksScreen pattern"""
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(12)  # Match main menu spacing
        
        # Header section
        self._setup_header(layout)
        
        # Menu buttons section
        self._setup_menu_buttons(layout)
        
        # Bottom spacer
        layout.addStretch()
        self.setLayout(layout)

    def _setup_header(self, layout):
        """Set up the header section"""
        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        # Title
        title = QLabel("<b>Additional Tasks & Tools</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        header_layout.addSpacing(10)

        # Description area with fixed height
        desc = QLabel("Wabbajack installer, MO2 setup, and additional tools.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(50)  # Fixed height for description zone
        header_layout.addWidget(desc)

        header_layout.addSpacing(12)

        # Separator
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setFixedWidth(400)  # Match button width
        sep.setStyleSheet("background: #fff;")
        header_layout.addWidget(sep, alignment=Qt.AlignHCenter)

        header_layout.addSpacing(10)

        header_widget.setLayout(header_layout)
        header_widget.setFixedHeight(120)  # Fixed total header height
        layout.addWidget(header_widget)
    
    def _setup_menu_buttons(self, layout):
        """Set up the menu buttons section"""
        # Menu options
        MENU_ITEMS = [
            ("Run Install Verifier", "run_verifier", "Check an installed modlist for common configuration problems"),
            ("Configure Tool Compatibility", "tool_config", "Apply xEdit, Pandora and DLL fixes to an existing modlist prefix"),
            ("Setup Mod Organizer 2", "setup_mo2", "Download and configure a standalone MO2 instance"),
            ("Install Wabbajack", "wabbajack_install", "Install Wabbajack.exe via Proton (automated setup)"),
            ("Create Diagnostic Bundle", "diagnostic_bundle", "Package logs and system info for support reporting"),
            ("Return to Main Menu", "return_main_menu", "Go back to the main menu"),
        ]
        
        # Create grid layout for buttons (mirror ModlistTasksScreen pattern)
        button_grid = QGridLayout()
        button_grid.setSpacing(12)
        button_grid.setAlignment(Qt.AlignHCenter)

        button_width = 400
        button_height = 40

        for i, (label, action_id, description) in enumerate(MENU_ITEMS):
            # Create button
            btn = QPushButton(label)
            btn.setFixedSize(button_width, button_height)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #4a5568;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: bold;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background-color: #5a6578;
                }}
                QPushButton:pressed {{
                    background-color: {JACKIFY_COLOR_BLUE};
                }}
            """)
            btn.clicked.connect(lambda checked, a=action_id: self._handle_button_click(a))

            # Description label
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignHCenter)
            desc_label.setStyleSheet("color: #999; font-size: 11px;")
            desc_label.setWordWrap(True)
            desc_label.setFixedWidth(button_width)

            # Add to grid (button row, then description row)
            button_grid.addWidget(btn, i * 2, 0, Qt.AlignHCenter)
            button_grid.addWidget(desc_label, i * 2 + 1, 0, Qt.AlignHCenter)

        layout.addLayout(button_grid)

    # Removed _create_menu_button; using same pattern as ModlistTasksScreen

    def _handle_button_click(self, action_id):
        """Handle button clicks"""
        if action_id == "run_verifier":
            self._run_install_verifier()
        elif action_id == "wabbajack_install":
            self._show_wabbajack_installer()
        elif action_id == "setup_mo2":
            self._show_mo2_setup()
        elif action_id == "tool_config":
            self._show_tool_config()
        elif action_id == "diagnostic_bundle":
            self._run_diagnostic_bundle()
        elif action_id == "return_main_menu":
            self._return_to_main_menu()

    def _show_wabbajack_installer(self):
        """Navigate to Wabbajack installer screen"""
        if self.stacked_widget:
            # Navigate to Wabbajack installer screen (index 7)
            self.stacked_widget.setCurrentIndex(7)

    def _show_mo2_setup(self):
        """Navigate to standalone MO2 setup screen"""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.install_mo2_screen_index)

    def _show_tool_config(self):
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(11)

    def _run_install_verifier(self):
        """Prompt user to pick a modlist, run the verifier, and show results."""
        from ..services.message_service import MessageService
        try:
            from jackify.backend.services.install_verifier_service import _load_verifier
            verifier_mod = _load_verifier()
            modlists = verifier_mod.discover_installed_modlists()
        except Exception as e:
            MessageService.critical(
                self,
                "Verifier Error",
                f"Could not load install verifier: {e}",
            )
            return

        if not modlists:
            MessageService.information(
                self,
                "No Modlists Found",
                "No installed modlists were found in Steam shortcuts.\n\n"
                "Ensure ModOrganizer.exe shortcuts exist in Steam for your modlists.",
            )
            return

        from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel, QHBoxLayout
        picker = QDialog(self)
        picker.setWindowTitle("Select Modlist to Verify")
        picker.setMinimumWidth(480)
        picker.setMinimumHeight(260)
        picker_layout = QVBoxLayout(picker)
        picker_layout.addWidget(QLabel("Select a modlist to verify:"))

        lw = QListWidget()
        for m in modlists:
            pfx_ok = m["pfx"] and m["pfx"].is_dir()
            suffix = "" if pfx_ok else " (prefix not found)"
            item = QListWidgetItem(f"{m['name']}{suffix}")
            item.setData(1000, m)
            lw.addItem(item)
        lw.setCurrentRow(0)
        picker_layout.addWidget(lw)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Run Verifier")
        cancel_btn = QPushButton("Cancel")
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        picker_layout.addLayout(btn_row)

        ok_btn.clicked.connect(picker.accept)
        cancel_btn.clicked.connect(picker.reject)
        lw.itemDoubleClicked.connect(lambda _: picker.accept())

        if picker.exec() != QDialog.Accepted:
            return

        selected_item = lw.currentItem()
        if not selected_item:
            return
        selected = selected_item.data(1000)

        pfx = selected.get("pfx")
        if not pfx or not pfx.is_dir():
            MessageService.warning(
                self,
                "Prefix Not Found",
                f"The Proton prefix for '{selected['name']}' was not found.\n\n"
                "Launch the modlist from Steam at least once to create the prefix.",
            )
            return

        from PySide6.QtCore import QThread, Signal as _Signal

        class _VerifierThread(QThread):
            done = _Signal(object)

            def __init__(self, verifier_module, entry, parent=None):
                super().__init__(parent)
                self._verifier = verifier_module
                self._entry = entry

            def run(self):
                try:
                    r = self._verifier.run_verification(
                        pfx=self._entry["pfx"],
                        modlist_dir=self._entry["modlist_dir"],
                        game_type=self._entry["game_type"],
                        appid=self._entry["appid"],
                        modlist_name=self._entry.get("name", ""),
                    )
                except Exception as exc:
                    logger.warning("On-demand verifier error: %s", exc)
                    r = None
                self.done.emit(r)

        from jackify.frontends.gui.services.message_service import MessageService as _MS
        progress_dlg = QDialog(self)
        progress_dlg.setWindowTitle("Verifying...")
        progress_dlg.setModal(True)
        prog_layout = QVBoxLayout(progress_dlg)
        prog_layout.addWidget(QLabel(f"Running verifier for '{selected['name']}'...\nThis may take a moment."))
        progress_dlg.setFixedSize(340, 100)
        progress_dlg.show()

        self._verifier_ondemand_thread = _VerifierThread(verifier_mod, selected, parent=self)

        def _on_done(results):
            progress_dlg.accept()
            self._verifier_ondemand_thread = None
            if results is None:
                MessageService.critical(
                    self,
                    "Verifier Error",
                    "The verifier encountered an error and could not complete.",
                )
                return
            from jackify.frontends.gui.dialogs.verification_results_dialog import VerificationResultsDialog
            dlg = VerificationResultsDialog(results, parent=self)
            dlg.exec()

        self._verifier_ondemand_thread.done.connect(_on_done)
        self._verifier_ondemand_thread.start()

    def _run_diagnostic_bundle(self):
        """Open the diagnostic bundle dialog; bundle is only created when the user confirms."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
        )
        from PySide6.QtCore import QThread, Signal as _Signal

        class _BundleThread(QThread):
            done = _Signal(object, str)  # (bundle_path or None, error_msg)

            def run(self):
                try:
                    from jackify.backend.services.diagnostic_service import build_bundle
                    path = build_bundle()
                    self.done.emit(path, "")
                except Exception as exc:
                    self.done.emit(None, str(exc))

        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnostic Bundle")
        dlg.setMinimumWidth(600)
        dlg.setMinimumHeight(220)
        dlg.setStyleSheet("QDialog { background: #181818; color: #fff; }")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        status_label = QLabel("Package logs and system info into a file for support reporting.")
        layout.addWidget(status_label)

        path_box = QTextEdit()
        path_box.setReadOnly(True)
        path_box.setMinimumHeight(60)
        path_box.setVisible(False)
        layout.addWidget(path_box)

        btn_row = QHBoxLayout()
        create_btn = QPushButton("Create Bundle")
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(create_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        cancel_btn.clicked.connect(dlg.reject)

        def _on_create():
            create_btn.setEnabled(False)
            cancel_btn.setEnabled(False)
            status_label.setText("Collecting logs and system info...")
            self._diag_thread = _BundleThread(parent=self)
            self._diag_thread.done.connect(_on_done)
            self._diag_thread.start()

        def _on_done(bundle_path, error):
            self._diag_thread = None
            cancel_btn.setEnabled(True)
            cancel_btn.setText("Close")
            if not bundle_path:
                status_label.setText(f"Failed: {error}")
                return
            status_label.setText("Bundle created:")
            path_box.setPlainText(str(bundle_path))
            path_box.setVisible(True)

        create_btn.clicked.connect(_on_create)
        dlg.exec()

    def _return_to_main_menu(self):
        """Return to main menu"""
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(self.main_menu_index)

    def showEvent(self, event):
        """Called when the widget becomes visible - resize to compact size"""
        super().showEvent(event)
        try:
            main_window = self.window()
            if main_window:
                from PySide6.QtCore import QSize
                # Only set minimum size - DO NOT RESIZE
                main_window.setMaximumSize(QSize(16777215, 16777215))
                set_responsive_minimum(main_window, min_width=960, min_height=420)
                # DO NOT resize - let window stay at current size
        except Exception:
            pass