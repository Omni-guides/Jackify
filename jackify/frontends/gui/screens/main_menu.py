"""
MainMenu screen for Jackify GUI (Refactored)
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtGui import QPixmap, QFont
from PySide6.QtCore import Qt
import os
from ..shared_theme import JACKIFY_COLOR_BLUE, LOGO_PATH, DISCLAIMER_TEXT

class MainMenu(QWidget):
    def __init__(self, stacked_widget=None, dev_mode=False):
        super().__init__()
        self.stacked_widget = stacked_widget
        self.dev_mode = dev_mode
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.setContentsMargins(50, 50, 50, 50)
        layout.setSpacing(20)

        # Title
        title = QLabel("<b>Jackify</b>")
        title.setStyleSheet(f"font-size: 24px; color: {JACKIFY_COLOR_BLUE};")
        title.setAlignment(Qt.AlignHCenter)
        layout.addWidget(title)

        # Description
        desc = QLabel(
            "Manage your modlists with native Linux tools. "
            "Choose from the options below to install, "
            "configure, or manage modlists."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #ccc;")
        desc.setAlignment(Qt.AlignHCenter)
        layout.addWidget(desc)

        # Separator
        layout.addSpacing(16)
        sep = QLabel()
        sep.setFixedHeight(2)
        sep.setStyleSheet("background: #fff;")
        layout.addWidget(sep)
        layout.addSpacing(16)

        # Menu buttons
        button_width = 400
        button_height = 60
        MENU_ITEMS = [
            ("Modlist Tasks", "modlist_tasks", "Manage your modlists with native Linux tools"),
            ("Coming Soon...", "coming_soon", "More features coming soon!"),
        ]
        if self.dev_mode:
            MENU_ITEMS.append(("Hoolamike Tasks", "hoolamike_tasks", "Manage Hoolamike modding tools"))
            MENU_ITEMS.append(("Additional Tasks", "additional_tasks", "Additional utilities and tools"))
        MENU_ITEMS.append(("Exit Jackify", "exit_jackify", "Close the application"))
        
        for label, action_id, description in MENU_ITEMS:
            # Main button
            btn = QPushButton(label)
            btn.setFixedSize(button_width, 50)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #4a5568;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 14px;
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
            btn.clicked.connect(lambda checked, a=action_id: self.menu_action(a))
            
            # Button container with proper alignment
            btn_container = QWidget()
            btn_layout = QVBoxLayout()
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(4)
            btn_layout.setAlignment(Qt.AlignHCenter)
            btn_layout.addWidget(btn)
            
            # Description label with proper alignment
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignHCenter)
            desc_label.setStyleSheet("color: #999; font-size: 12px;")
            desc_label.setWordWrap(True)
            desc_label.setFixedWidth(button_width)  # Match button width for proper alignment
            btn_layout.addWidget(desc_label)
            
            btn_container.setLayout(btn_layout)
            layout.addWidget(btn_container)

        # Disclaimer
        layout.addSpacing(20)
        disclaimer = QLabel(DISCLAIMER_TEXT)
        disclaimer.setWordWrap(True)
        disclaimer.setAlignment(Qt.AlignCenter)
        disclaimer.setStyleSheet("color: #666; font-size: 10px;")
        disclaimer.setFixedWidth(button_width)
        layout.addWidget(disclaimer, alignment=Qt.AlignHCenter)

        self.setLayout(layout)

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
        elif action_id == "return_main_menu":
            # This is the main menu, so do nothing
            pass
        elif self.stacked_widget:
            self.stacked_widget.setCurrentIndex(2)  # Placeholder for now 