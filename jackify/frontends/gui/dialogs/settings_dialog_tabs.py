"""
Settings dialog tab creation: General and Advanced tabs.
"""

import os
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
    QComboBox, QGroupBox, QFormLayout, QGridLayout, QSpinBox, QRadioButton, QButtonGroup,
    QToolButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

logger = logging.getLogger(__name__)


class SettingsDialogTabsMixin:
    """Mixin providing _create_general_tab and _create_advanced_tab for SettingsDialog."""

    def _create_general_tab(self):
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)

        dir_group = QGroupBox("Directory Paths")
        dir_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        dir_layout = QFormLayout()
        dir_group.setLayout(dir_layout)
        self.install_dir_edit = QLineEdit(self.config_handler.get("modlist_install_base_dir", ""))
        self.install_dir_edit.setToolTip("Default directory for modlist installations.")
        self.install_dir_btn = QPushButton()
        self.install_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
        self.install_dir_btn.setToolTip("Browse for directory")
        self.install_dir_btn.setFixedWidth(32)
        self.install_dir_btn.clicked.connect(lambda: self._pick_directory(self.install_dir_edit))
        install_dir_row = QHBoxLayout()
        install_dir_row.addWidget(self.install_dir_edit)
        install_dir_row.addWidget(self.install_dir_btn)
        dir_layout.addRow(QLabel("Install Base Dir:"), install_dir_row)
        self.download_dir_edit = QLineEdit(self.config_handler.get("modlist_downloads_base_dir", ""))
        self.download_dir_edit.setToolTip("Default directory for modlist downloads.")
        self.download_dir_btn = QPushButton()
        self.download_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
        self.download_dir_btn.setToolTip("Browse for directory")
        self.download_dir_btn.setFixedWidth(32)
        self.download_dir_btn.clicked.connect(lambda: self._pick_directory(self.download_dir_edit))
        download_dir_row = QHBoxLayout()
        download_dir_row.addWidget(self.download_dir_edit)
        download_dir_row.addWidget(self.download_dir_btn)
        dir_layout.addRow(QLabel("Downloads Base Dir:"), download_dir_row)

        from jackify.shared.paths import get_jackify_data_dir
        current_jackify_dir = str(get_jackify_data_dir())
        self.jackify_data_dir_edit = QLineEdit(current_jackify_dir)
        self.jackify_data_dir_edit.setToolTip("Directory for Jackify data (logs, downloads, temp files). Default: ~/Jackify")
        self.jackify_data_dir_btn = QPushButton()
        self.jackify_data_dir_btn.setIcon(QIcon.fromTheme("folder-open"))
        self.jackify_data_dir_btn.setToolTip("Browse for directory")
        self.jackify_data_dir_btn.setFixedWidth(32)
        self.jackify_data_dir_btn.clicked.connect(lambda: self._pick_directory(self.jackify_data_dir_edit))
        jackify_data_dir_row = QHBoxLayout()
        jackify_data_dir_row.addWidget(self.jackify_data_dir_edit)
        jackify_data_dir_row.addWidget(self.jackify_data_dir_btn)
        reset_jackify_dir_btn = QPushButton("Reset")
        reset_jackify_dir_btn.setToolTip("Reset to default (~/ Jackify)")
        reset_jackify_dir_btn.setFixedWidth(50)
        reset_jackify_dir_btn.clicked.connect(lambda: self.jackify_data_dir_edit.setText(str(Path.home() / "Jackify")))
        jackify_data_dir_row.addWidget(reset_jackify_dir_btn)
        dir_layout.addRow(QLabel("Jackify Data Dir:"), jackify_data_dir_row)
        general_layout.addWidget(dir_group)
        general_layout.addSpacing(12)

        proton_group = QGroupBox("Proton Version Settings")
        proton_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        proton_layout = QVBoxLayout()
        proton_group.setLayout(proton_layout)
        install_proton_layout = QHBoxLayout()
        self.install_proton_dropdown = QComboBox()
        self.install_proton_dropdown.setToolTip("Proton version for modlist installation and texture processing (requires fast Proton)")
        self.install_proton_dropdown.setMinimumWidth(200)
        install_refresh_btn = QPushButton("\u21BB")
        install_refresh_btn.setFixedSize(30, 30)
        install_refresh_btn.setToolTip("Refresh install Proton version list")
        install_refresh_btn.clicked.connect(self._refresh_install_proton_dropdown)
        install_proton_layout.addWidget(QLabel("Install Proton:"))
        install_proton_layout.addWidget(self.install_proton_dropdown)
        install_proton_layout.addWidget(install_refresh_btn)
        install_proton_layout.addStretch()
        game_proton_layout = QHBoxLayout()
        self.game_proton_dropdown = QComboBox()
        self.game_proton_dropdown.setToolTip("Proton version for game shortcuts (can be any Proton 9+)")
        self.game_proton_dropdown.setMinimumWidth(200)
        game_refresh_btn = QPushButton("\u21BB")
        game_refresh_btn.setFixedSize(30, 30)
        game_refresh_btn.setToolTip("Refresh game Proton version list")
        game_refresh_btn.clicked.connect(self._refresh_game_proton_dropdown)
        game_proton_layout.addWidget(QLabel("Game Proton:"))
        game_proton_layout.addWidget(self.game_proton_dropdown)
        game_proton_layout.addWidget(game_refresh_btn)
        game_proton_layout.addStretch()
        proton_layout.addLayout(install_proton_layout)
        proton_layout.addLayout(game_proton_layout)
        self._populate_install_proton_dropdown()
        self._populate_game_proton_dropdown()
        general_layout.addWidget(proton_group)
        general_layout.addSpacing(12)

        from jackify.frontends.gui.services.message_service import MessageService
        oauth_group = QGroupBox("Nexus Authentication")
        oauth_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        oauth_layout = QVBoxLayout()
        oauth_group.setLayout(oauth_layout)
        oauth_status_layout = QHBoxLayout()
        self.oauth_status_label = QLabel("Checking...")
        self.oauth_status_label.setStyleSheet("color: #ccc;")
        self.oauth_btn = QPushButton("Authorise")
        self.oauth_btn.setMaximumWidth(100)
        self.oauth_btn.clicked.connect(self._handle_oauth_click)
        oauth_status_layout.addWidget(QLabel("Status:"))
        oauth_status_layout.addWidget(self.oauth_status_label)
        oauth_status_layout.addWidget(self.oauth_btn)
        oauth_status_layout.addStretch()
        oauth_layout.addLayout(oauth_status_layout)
        self._update_oauth_status()
        general_layout.addWidget(oauth_group)
        general_layout.addSpacing(12)

        debug_group = QGroupBox("Enable Debug")
        debug_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        debug_layout = QVBoxLayout()
        debug_group.setLayout(debug_layout)
        self.debug_checkbox = QCheckBox("Enable debug mode (requires restart)")
        self.debug_checkbox.setChecked(self.config_handler.get('debug_mode', False))
        self.debug_checkbox.setToolTip("Enable verbose debug logging. Requires Jackify restart to take effect.")
        self.debug_checkbox.setStyleSheet("color: #fff;")
        debug_layout.addWidget(self.debug_checkbox)
        general_layout.addWidget(debug_group)
        general_layout.addStretch()
        self.tab_widget.addTab(general_tab, "General")

    def _create_advanced_tab(self):
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        auth_group = QGroupBox("Nexus Authentication")
        auth_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        auth_layout = QVBoxLayout()
        auth_group.setLayout(auth_layout)
        api_layout = QHBoxLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        api_key = self.config_handler.get_api_key()
        self.api_key_edit.setText(api_key if api_key else "")
        self.api_key_edit.setToolTip("Your Nexus API Key (legacy authentication method)")
        self.api_key_edit.editingFinished.connect(self._on_api_key_changed)
        self.api_show_btn = QToolButton()
        self.api_show_btn.setCheckable(True)
        self.api_show_btn.setIcon(QIcon.fromTheme("view-visible"))
        self.api_show_btn.setToolTip("Show or hide your API key")
        self.api_show_btn.toggled.connect(self._toggle_api_key_visibility)
        clear_api_btn = QPushButton("Clear")
        clear_api_btn.clicked.connect(self._clear_api_key)
        clear_api_btn.setMaximumWidth(60)
        api_layout.addWidget(QLabel("API Key:"))
        api_layout.addWidget(self.api_key_edit)
        api_layout.addWidget(self.api_show_btn)
        api_layout.addWidget(clear_api_btn)
        auth_layout.addLayout(api_layout)
        advanced_layout.addWidget(auth_group)
        advanced_layout.addSpacing(12)


        self.resource_settings_path = os.path.expanduser("~/.config/jackify/resource_settings.json")
        self.resource_settings = self._load_json(self.resource_settings_path)
        self.resource_edits = {}
        resource_group = QGroupBox("Resource Limits")
        resource_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        resource_outer_layout = QVBoxLayout()
        resource_group.setLayout(resource_outer_layout)
        if not self.resource_settings:
            info_label = QLabel("Resource Limit settings will be generated once a modlist install action is performed")
            info_label.setStyleSheet("color: #aaa; font-style: italic; padding: 20px; font-size: 11pt;")
            info_label.setWordWrap(True)
            info_label.setAlignment(Qt.AlignCenter)
            info_label.setMinimumHeight(60)
            resource_outer_layout.addWidget(info_label)
        else:
            resource_grid = QGridLayout()
            resource_grid.setVerticalSpacing(4)
            resource_grid.setHorizontalSpacing(8)
            resource_grid.setColumnMinimumWidth(2, 40)
            resource_grid.addWidget(self._bold_label("Resource"), 0, 0, 1, 1, Qt.AlignLeft)
            resource_grid.addWidget(self._bold_label("Max Tasks"), 0, 1, 1, 1, Qt.AlignLeft)
            resource_grid.addWidget(self._bold_label("Resource"), 0, 3, 1, 1, Qt.AlignLeft)
            resource_grid.addWidget(self._bold_label("Max Tasks"), 0, 4, 1, 1, Qt.AlignLeft)
            resource_items = list(self.resource_settings.items())
            bandwidth_kb = 0
            if "Downloads" in self.resource_settings:
                bandwidth_kb = self.resource_settings["Downloads"].get("MaxThroughput", 0) // 1024 or 0
            left_row = 1
            for k, v in resource_items[:4]:
                try:
                    resource_grid.addWidget(QLabel(f"{k}:", parent=self), left_row, 0, 1, 1, Qt.AlignLeft)
                    max_tasks_spin = QSpinBox()
                    max_tasks_spin.setMinimum(1)
                    max_tasks_spin.setMaximum(128)
                    max_tasks_spin.setValue(v.get('MaxTasks', 16))
                    max_tasks_spin.setToolTip("Maximum number of concurrent tasks for this resource.")
                    max_tasks_spin.setFixedWidth(100)
                    resource_grid.addWidget(max_tasks_spin, left_row, 1)
                    self.resource_edits[k] = (None, max_tasks_spin)
                    left_row += 1
                except Exception as e:
                    self.logger.error("Failed to create widgets for resource '%s': %s", k, e)
                    continue
            right_row = 1
            for k, v in resource_items[4:]:
                try:
                    resource_grid.addWidget(QLabel(f"{k}:", parent=self), right_row, 3, 1, 1, Qt.AlignLeft)
                    max_tasks_spin = QSpinBox()
                    max_tasks_spin.setMinimum(1)
                    max_tasks_spin.setMaximum(128)
                    max_tasks_spin.setValue(v.get('MaxTasks', 16))
                    max_tasks_spin.setToolTip("Maximum number of concurrent tasks for this resource.")
                    max_tasks_spin.setFixedWidth(100)
                    resource_grid.addWidget(max_tasks_spin, right_row, 4)
                    self.resource_edits[k] = (None, max_tasks_spin)
                    right_row += 1
                except Exception as e:
                    self.logger.error("Failed to create widgets for resource '%s': %s", k, e)
                    continue
            if "Downloads" in self.resource_settings:
                resource_grid.addWidget(QLabel("Bandwidth Limit:", parent=self), right_row, 3, 1, 1, Qt.AlignLeft)
                self.bandwidth_spin = QSpinBox()
                self.bandwidth_spin.setMinimum(0)
                self.bandwidth_spin.setMaximum(1000000)
                self.bandwidth_spin.setValue(bandwidth_kb)
                self.bandwidth_spin.setSuffix(" KB/s")
                self.bandwidth_spin.setFixedWidth(100)
                self.bandwidth_spin.setToolTip("Set the maximum download speed for modlist downloads. 0 = unlimited.")
                bandwidth_widget_layout = QHBoxLayout()
                bandwidth_widget_layout.setContentsMargins(0, 0, 0, 0)
                bandwidth_widget_layout.addWidget(self.bandwidth_spin)
                bandwidth_note = QLabel("(0 = unlimited)")
                bandwidth_note.setStyleSheet("color: #aaa; font-size: 9pt;")
                bandwidth_widget_layout.addWidget(bandwidth_note)
                bandwidth_widget_layout.addStretch()
                bandwidth_container = QWidget()
                bandwidth_container.setLayout(bandwidth_widget_layout)
                resource_grid.addWidget(bandwidth_container, right_row, 4, 1, 1, Qt.AlignLeft)
            else:
                self.bandwidth_spin = None
            resource_grid.setColumnStretch(5, 1)
            resource_outer_layout.addLayout(resource_grid)
        advanced_layout.addWidget(resource_group)

        component_group = QGroupBox("Advanced Tool Options")
        component_group.setStyleSheet("QGroupBox { border: 1px solid #555; border-radius: 6px; margin-top: 8px; padding: 8px; background: #23282d; } QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; font-weight: bold; color: #fff; }")
        component_layout = QVBoxLayout()
        component_group.setLayout(component_layout)
        component_layout.addWidget(QLabel("Wine Components Installation:"))
        self.component_method_group = QButtonGroup()
        component_method_layout = QVBoxLayout()
        current_method = self.config_handler.get('component_installation_method', 'native')
        if current_method == 'bundled_protontricks':
            current_method = 'system_protontricks'
        self.native_radio = QRadioButton("Native (Default)")
        self.native_radio.setChecked(current_method == 'native')
        self.native_radio.setToolTip(
            "Install components directly, without winetricks or protontricks, falling back to "
            "bundled winetricks only for the handful of components not yet supported natively."
        )
        self.component_method_group.addButton(self.native_radio, 0)
        component_method_layout.addWidget(self.native_radio)
        self.winetricks_radio = QRadioButton("Winetricks")
        self.winetricks_radio.setChecked(current_method == 'winetricks')
        self.winetricks_radio.setToolTip("Use bundled winetricks for every component, bypassing the native installer entirely.")
        self.component_method_group.addButton(self.winetricks_radio, 1)
        component_method_layout.addWidget(self.winetricks_radio)
        self.protontricks_radio = QRadioButton("Protontricks")
        self.protontricks_radio.setChecked(current_method == 'system_protontricks')
        self.protontricks_radio.setToolTip(
            "Use system-installed protontricks (flatpak or native) for every component, "
            "bypassing the native installer entirely."
        )
        self.component_method_group.addButton(self.protontricks_radio, 2)
        component_method_layout.addWidget(self.protontricks_radio)
        component_layout.addLayout(component_method_layout)

        self.auto_tool_compat_checkbox = QCheckBox("Apply tool compatibility settings during install/configure")
        self.auto_tool_compat_checkbox.setChecked(self.config_handler.get('auto_tool_compat', True))
        self.auto_tool_compat_checkbox.setToolTip(
            "Automatically apply Wine registry fixes for xEdit, Pandora, and DLL overrides "
            "at the end of every install or configure workflow. Disable if you find it adds "
            "noticeable delay."
        )
        self.auto_tool_compat_checkbox.setStyleSheet("color: #fff;")
        component_layout.addWidget(self.auto_tool_compat_checkbox)

        self.force_github_updates_checkbox = QCheckBox("Use GitHub as update source (bypass Nexus CDN)")
        self.force_github_updates_checkbox.setChecked(self.config_handler.get('force_github_updates', False))
        self.force_github_updates_checkbox.setToolTip(
            "Always download Jackify updates directly from GitHub Releases instead of Nexus CDN. "
            "Enable this if self-updates fail or stall. GitHub delivers the AppImage directly; "
            "Nexus delivers a .7z archive that Jackify must extract."
        )
        self.force_github_updates_checkbox.setStyleSheet("color: #fff;")
        component_layout.addWidget(self.force_github_updates_checkbox)

        self.clf3_default_checkbox = QCheckBox("Use CLF3 as default install engine")
        self.clf3_default_checkbox.setToolTip(
            "Use CLF3 (SulfurNitride) as the default engine for all installs. "
            "CLF3 will be downloaded automatically if not already installed. "
            "You can still override this per-install on the Install screen."
        )
        self.clf3_default_checkbox.setStyleSheet("color: #fff;")
        try:
            from jackify.backend.services.tool_registry import get_active_engine_id
            self.clf3_default_checkbox.setChecked(get_active_engine_id() == "clf3")
        except Exception:
            pass
        component_layout.addWidget(self.clf3_default_checkbox)

        advanced_layout.addWidget(component_group)
        advanced_layout.addStretch()
        self.tab_widget.addTab(advanced_tab, "Advanced")
