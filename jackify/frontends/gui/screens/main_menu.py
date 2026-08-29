"""
MainMenu screen for Jackify GUI (Refactored)
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtCore import Qt
import os
from ..shared_theme import JACKIFY_COLOR_BLUE, LOGO_PATH, DISCLAIMER_TEXT, COLOR_SEPARATOR
from ..utils import set_responsive_minimum

_TOOLS_HUB_ACTION = "third_party_tools"
_UPDATE_COLOUR = "#f0c040"
_NORMAL_DESC_COLOUR = "#999"

class MainMenu(QWidget):
    def __init__(self, stacked_widget=None, dev_mode=False):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.dev_mode = dev_mode
        self._tools_hub_btn: QPushButton = None
        self._tools_hub_desc: QLabel = None
        self._tools_hub_desc_original: str = ""
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(12)

        # Header zone with fixed height for consistent layout across all menu screens
        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        # Title
        title = QLabel("<b>Jackify</b>")
        title.setStyleSheet(f"font-size: 20px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        header_layout.addWidget(title)

        header_layout.addSpacing(10)

        # Description area with fixed height
        desc = QLabel(
            "Manage your modlists with native Linux tools. "
            "Choose from the options below to install, "
            "configure, or manage modlists."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc; font-size: 13px;")
        desc.setAlignment(Qt.AlignHCenter)
        desc.setMaximumHeight(50)  # Fixed height for description zone
        header_layout.addWidget(desc)

        header_layout.addSpacing(12)

        # Separator
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background: {COLOR_SEPARATOR};")
        header_layout.addWidget(sep)

        header_layout.addSpacing(10)

        header_widget.setLayout(header_layout)
        header_widget.setFixedHeight(120)  # Fixed total header height
        layout.addWidget(header_widget)

        # Menu buttons
        button_width = 400
        button_height = 40
        MENU_ITEMS = [
            ("Modlist Tasks", "modlist_tasks", "Manage your modlists with native Linux tools"),
            ("Modlist Dashboard", "modlist_dashboard", "View, launch, and manage installed modlists"),
            ("Additional Tasks", "additional_tasks", "Verifier, diagnostics, Nexus OAuth, and more"),
            ("Tools Hub", "third_party_tools", "Install and manage additional engines and modding tools"),
            ("Exit Jackify", "exit_jackify", "Close the application"),
        ]
        
        for label, action_id, description in MENU_ITEMS:
            btn = QPushButton(label)
            btn.setFixedSize(button_width, button_height)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(lambda checked, a=action_id: self.menu_action(a))

            btn_container = QWidget()
            btn_layout = QVBoxLayout()
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(3)
            btn_layout.setAlignment(Qt.AlignHCenter)
            btn_layout.addWidget(btn)

            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignHCenter)
            desc_label.setStyleSheet(f"color: {_NORMAL_DESC_COLOUR}; font-size: 11px;")
            desc_label.setWordWrap(True)
            desc_label.setFixedWidth(button_width)
            btn_layout.addWidget(desc_label)

            btn_container.setLayout(btn_layout)
            layout.addWidget(btn_container)

            if action_id == _TOOLS_HUB_ACTION:
                self._tools_hub_btn = btn
                self._tools_hub_desc = desc_label
                self._tools_hub_desc_original = description

        # Disclaimer
        layout.addSpacing(12)
        disclaimer = QLabel(DISCLAIMER_TEXT)
        disclaimer.setWordWrap(True)
        disclaimer.setAlignment(Qt.AlignCenter)
        disclaimer.setStyleSheet("color: #666; font-size: 10px;")
        disclaimer.setFixedWidth(button_width)
        layout.addWidget(disclaimer, alignment=Qt.AlignHCenter)

        self.setLayout(layout)

    def showEvent(self, event):
        """Called when the widget becomes visible - ensure minimum size only"""
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

    def _btn_style(self, highlight: bool = False) -> str:
        border = f"1px solid {_UPDATE_COLOUR}" if highlight else "none"
        return f"""
            QPushButton {{
                background-color: #4a5568;
                color: white;
                border: {border};
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
                text-align: center;
            }}
            QPushButton:hover {{ background-color: #5a6578; }}
            QPushButton:pressed {{ background-color: {JACKIFY_COLOR_BLUE}; }}
        """

    def notify_tool_updates(self, has_updates: bool) -> None:
        if not self._tools_hub_btn or not self._tools_hub_desc:
            return
        if has_updates:
            self._tools_hub_btn.setStyleSheet(self._btn_style(highlight=True))
            self._tools_hub_desc.setText("Updates available")
            self._tools_hub_desc.setStyleSheet(f"color: {_UPDATE_COLOUR}; font-size: 11px; font-weight: bold;")
        else:
            self._tools_hub_btn.setStyleSheet(self._btn_style(highlight=False))
            self._tools_hub_desc.setText(self._tools_hub_desc_original)
            self._tools_hub_desc.setStyleSheet(f"color: {_NORMAL_DESC_COLOUR}; font-size: 11px;")

    def menu_action(self, action_id):
        if action_id == "exit_jackify":
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
        elif action_id == "coming_soon":
            # Show a friendly message about upcoming features
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox(self)
            msg.setWindowTitle("Coming Soon")
            msg.setText("More features are coming in future releases!\n\nFor now, you can install and configure any modlist using the 'Modlist Tasks' button.")
            msg.setIcon(QMessageBox.Information)
            msg.exec()
        elif action_id == "modlist_tasks" and self.stacked_widget:
            self.stacked_widget.setCurrentIndex(2)
        elif action_id == "additional_tasks" and self.stacked_widget:
            self.stacked_widget.setCurrentIndex(3)
        elif action_id == "third_party_tools" and self.stacked_widget:
            self.stacked_widget.setCurrentIndex(10)
        elif action_id == "modlist_dashboard" and self.stacked_widget:
            self.stacked_widget.setCurrentIndex(12)
        elif action_id == "return_main_menu":
            pass
        elif self.stacked_widget:
            self.stacked_widget.setCurrentIndex(1)  # Default to placeholder 