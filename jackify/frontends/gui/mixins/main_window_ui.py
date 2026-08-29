"""
Main window UI setup mixin.
Stacked widget, screens, bottom bar, screen change handling.

Screens 1-9 are lazy-initialised: placeholder QWidgets are inserted at startup
and swapped for real screens on first navigation. The Modlist Dashboard (index 12) is the
app's home screen, shown on startup; MainMenu (index 0) is still built but no longer
navigated to from anywhere - kept in place rather than deleted while the tabbed-navigation
change beds in.

A persistent AppHeader (logo banner + tab bar + separator, see widgets/app_header.py) sits
above the stacked widget itself, visible only across the three tabbed destinations
(Modlists/Additional Tasks/Tools Hub) so switching between them doesn't read as a full screen
change - only the body below the header's separator line changes.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QSizePolicy,
)
from PySide6.QtCore import Qt

from jackify import __version__
from jackify.frontends.gui.widgets.feature_placeholder import FeaturePlaceholder

logger = logging.getLogger(__name__)


class _LazyPlaceholder(QWidget):
    """Sentinel widget used in place of a not-yet-initialised screen."""


class MainWindowUIMixin:
    """Mixin for main window UI: stacked widget, screens, bottom bar."""

    def _setup_ui(self, dev_mode=False):
        self._dev_mode = dev_mode
        self.stacked_widget = QStackedWidget()

        # Only MainMenu is created eagerly (always shown first).
        from jackify.frontends.gui.screens import MainMenu
        self.main_menu = MainMenu(stacked_widget=self.stacked_widget, dev_mode=dev_mode)
        self.stacked_widget.addWidget(self.main_menu)          # index 0

        # Indexes 1-13: insert lightweight placeholders now; real screens on demand.
        for _ in range(13):
            self.stacked_widget.addWidget(_LazyPlaceholder())

        # Factory map: index -> callable that creates and caches the real screen.
        self._screen_factories = {
            1: self._make_feature_placeholder,
            2: self._make_modlist_tasks_screen,
            3: self._make_additional_tasks_screen,
            4: self._make_install_modlist_screen,
            5: self._make_install_ttw_screen,
            6: self._make_configure_new_modlist_screen,
            7: self._make_wabbajack_installer_screen,
            8: self._make_configure_existing_modlist_screen,
            9: self._make_install_mo2_screen,
            10: self._make_third_party_tools_screen,
            11: self._make_configure_tool_config_screen,
            12: self._make_modlist_dashboard_screen,
            13: self._make_game_downgrade_screen,
        }

        from jackify.frontends.gui.widgets.app_header import AppHeader
        self._app_header = AppHeader(self.stacked_widget)

        self.stacked_widget.currentChanged.connect(self._lazy_init_screen)
        self.stacked_widget.currentChanged.connect(self._debug_screen_change)
        self.stacked_widget.currentChanged.connect(self._maintain_fullscreen_on_deck)
        self.stacked_widget.currentChanged.connect(self._sync_app_header)

        bottom_bar = QWidget()
        bottom_bar_layout = QHBoxLayout()
        bottom_bar_layout.setContentsMargins(10, 2, 10, 2)
        bottom_bar_layout.setSpacing(0)
        bottom_bar.setLayout(bottom_bar_layout)
        bottom_bar.setFixedHeight(32)
        bottom_bar.setStyleSheet("background-color: #181818; border-top: 1px solid #222;")

        # Three-zone layout (left / center / right) with equal stretch factors on the
        # outer zones, so the center zone (Ko-fi) stays visually centered on the bar
        # regardless of how wide the version label or Settings/About block are.
        left_zone = QWidget()
        left_zone_layout = QHBoxLayout(left_zone)
        left_zone_layout.setContentsMargins(0, 0, 0, 0)
        version_label = QLabel(f"Jackify v{__version__}")
        version_label.setStyleSheet("color: #bbb; font-size: 13px;")
        left_zone_layout.addWidget(version_label, alignment=Qt.AlignLeft)
        left_zone_layout.addStretch(1)
        bottom_bar_layout.addWidget(left_zone, 1)

        kofi_link = QLabel('<a href="#" style="color:#3fd0ea; text-decoration:none;">Support on Ko-fi</a>')
        kofi_link.setStyleSheet("color: #3fd0ea; font-size: 13px;")
        kofi_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        kofi_link.setOpenExternalLinks(False)
        kofi_link.linkActivated.connect(lambda: self._open_url("https://ko-fi.com/omni1"))
        kofi_link.setToolTip("Support Jackify development")
        bottom_bar_layout.addWidget(kofi_link, 0, alignment=Qt.AlignCenter)

        right_zone = QWidget()
        right_zone_layout = QHBoxLayout(right_zone)
        right_zone_layout.setContentsMargins(0, 0, 0, 0)
        right_zone_layout.addStretch(1)
        settings_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">Settings</a>')
        settings_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        settings_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        settings_btn.setOpenExternalLinks(False)
        settings_btn.linkActivated.connect(self.open_settings_dialog)
        right_zone_layout.addWidget(settings_btn, alignment=Qt.AlignRight)
        about_btn = QLabel('<a href="#" style="color:#6cf; text-decoration:none;">About</a>')
        about_btn.setStyleSheet("color: #6cf; font-size: 13px; padding-right: 8px;")
        about_btn.setTextInteractionFlags(Qt.TextBrowserInteraction)
        about_btn.setOpenExternalLinks(False)
        about_btn.linkActivated.connect(self.open_about_dialog)
        right_zone_layout.addWidget(about_btn, alignment=Qt.AlignRight)
        bottom_bar_layout.addWidget(right_zone, 1)

        central_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._app_header)
        main_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(bottom_bar)
        self.stacked_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        self.stacked_widget.setCurrentIndex(12)  # Modlist Dashboard - the app's home screen
        self._check_protontricks_on_startup()
        self._start_tools_update_check()

    def _sync_app_header(self, index: int) -> None:
        """Keep the persistent header visible only across the three tabbed destinations
        (Modlists/Additional Tasks/Tools Hub), hidden on deeper workflow screens reached
        from within them - and update which tab reads as active."""
        from jackify.frontends.gui.widgets.app_header import AppHeader
        if AppHeader.is_tabbed_index(index):
            self._app_header.set_active(index)
            self._app_header.setVisible(True)
        else:
            self._app_header.setVisible(False)

    def _start_tools_update_check(self) -> None:
        """Check installed tools/engines for updates at startup, independent of whether the
        user has ever visited Tools Hub (that screen is lazily created on first visit) - so
        the tab's attention dot is accurate from first launch rather than only appearing
        after the user happens to open Tools Hub once."""
        from jackify.backend.services.tool_registry import ToolRegistry
        from jackify.frontends.gui.mixins.thread_registry import register_managed_thread
        from jackify.frontends.gui.screens.tools_hub_threads import VersionCheckThread

        self._startup_tool_statuses = {
            s.definition.tool_id: s for s in ToolRegistry().get_all_statuses()
        }
        logger.info(
            "Startup tools update check: %s",
            {tid: s.installed_version for tid, s in self._startup_tool_statuses.items()},
        )
        self._startup_version_thread = VersionCheckThread()
        self._startup_version_thread.version_ready.connect(self._on_startup_tool_version_ready)
        register_managed_thread(self._startup_version_thread)
        self._startup_version_thread.start()

    def _on_startup_tool_version_ready(self, tool_id: str, tag: str) -> None:
        status = self._startup_tool_statuses.get(tool_id)
        logger.info(
            "Startup tools update check: %s latest=%s installed=%s",
            tool_id, tag, status.installed_version if status else None,
        )
        if not status or not status.installed or not status.installed_version or tag == "unknown":
            return
        if tag.lstrip("v") != status.installed_version.lstrip("v"):
            logger.info("Startup tools update check: flagging Tools Hub tab (%s has an update)", tool_id)
            self._app_header.set_needs_attention(10, True)

    def _lazy_init_screen(self, index: int) -> None:
        """Swap placeholder at *index* for the real screen on first visit."""
        if index == 0:
            return
        widget = self.stacked_widget.widget(index)
        if not isinstance(widget, _LazyPlaceholder):
            return
        factory = self._screen_factories.get(index)
        if factory is None:
            return
        real_screen = factory()
        # Block signals for the entire swap including setCurrentWidget so that:
        # (a) Qt's auto-current-change on removeWidget doesn't cascade into the
        #     other placeholders via a re-entrant _lazy_init_screen call, and
        # (b) setCurrentWidget does not fire a second currentChanged - the outer
        #     currentChanged (which triggered this lazy init) is still being
        #     dispatched and will reach _debug_screen_change with the real screen
        #     already in place, so reset_screen_to_defaults runs exactly once.
        self.stacked_widget.blockSignals(True)
        self.stacked_widget.removeWidget(widget)
        widget.deleteLater()
        self.stacked_widget.insertWidget(index, real_screen)
        self.stacked_widget.setCurrentWidget(real_screen)
        self.stacked_widget.blockSignals(False)

    def _make_feature_placeholder(self):
        screen = FeaturePlaceholder(stacked_widget=self.stacked_widget)
        self.feature_placeholder = screen
        return screen

    def _make_modlist_tasks_screen(self):
        from jackify.frontends.gui.screens import ModlistTasksScreen
        screen = ModlistTasksScreen(
            stacked_widget=self.stacked_widget, main_menu_index=0, dev_mode=self._dev_mode
        )
        self.modlist_tasks_screen = screen
        return screen

    def _make_additional_tasks_screen(self):
        from jackify.frontends.gui.screens import AdditionalTasksScreen
        screen = AdditionalTasksScreen(
            stacked_widget=self.stacked_widget,
            system_info=self.system_info, install_mo2_screen_index=9,
            game_downgrade_screen_index=13,
        )
        self.additional_tasks_screen = screen
        return screen

    def _make_game_downgrade_screen(self):
        from jackify.frontends.gui.screens.game_downgrade_screen import GameDowngradeScreen
        screen = GameDowngradeScreen(stacked_widget=self.stacked_widget, additional_tasks_index=3)
        self.game_downgrade_screen = screen
        return screen

    def _make_install_modlist_screen(self):
        from jackify.frontends.gui.screens import InstallModlistScreen
        screen = InstallModlistScreen(
            stacked_widget=self.stacked_widget, main_menu_index=2, system_info=self.system_info
        )
        self.install_modlist_screen = screen
        try:
            screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        return screen

    def _make_install_ttw_screen(self):
        from jackify.frontends.gui.screens.install_ttw import InstallTTWScreen
        screen = InstallTTWScreen(
            stacked_widget=self.stacked_widget, main_menu_index=3, system_info=self.system_info
        )
        self.install_ttw_screen = screen
        try:
            screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        return screen

    def _make_configure_new_modlist_screen(self):
        from jackify.frontends.gui.screens import ConfigureNewModlistScreen
        screen = ConfigureNewModlistScreen(
            stacked_widget=self.stacked_widget, main_menu_index=2, system_info=self.system_info
        )
        self.configure_new_modlist_screen = screen
        try:
            screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        return screen

    def _make_wabbajack_installer_screen(self):
        from jackify.frontends.gui.screens.wabbajack_installer import WabbajackInstallerScreen
        screen = WabbajackInstallerScreen(
            stacked_widget=self.stacked_widget, additional_tasks_index=3, system_info=self.system_info
        )
        self.wabbajack_installer_screen = screen
        try:
            screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        return screen

    def _make_configure_existing_modlist_screen(self):
        from jackify.frontends.gui.screens import ConfigureExistingModlistScreen
        screen = ConfigureExistingModlistScreen(
            stacked_widget=self.stacked_widget, main_menu_index=2, system_info=self.system_info
        )
        self.configure_existing_modlist_screen = screen
        try:
            screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        return screen

    def _make_install_mo2_screen(self):
        from jackify.frontends.gui.screens.install_mo2_screen import InstallMO2Screen
        screen = InstallMO2Screen(
            stacked_widget=self.stacked_widget, additional_tasks_index=3, system_info=self.system_info
        )
        self.install_mo2_screen = screen
        try:
            screen.resize_request.connect(self._on_child_resize_request)
        except Exception:
            pass
        return screen

    def _make_third_party_tools_screen(self):
        from jackify.frontends.gui.screens.tools_hub import ToolsHubScreen
        screen = ToolsHubScreen(
            stacked_widget=self.stacked_widget, ttw_screen_index=5,
        )
        self.third_party_tools_screen = screen
        self._app_header.add_action_widget(screen.update_all_button, tab_index=10)
        return screen

    def _make_configure_tool_config_screen(self):
        from jackify.frontends.gui.screens.configure_tool_config_screen import ConfigureToolConfigScreen
        screen = ConfigureToolConfigScreen(
            stacked_widget=self.stacked_widget, additional_tasks_index=3,
        )
        self.configure_tool_config_screen = screen
        return screen

    def _make_modlist_dashboard_screen(self):
        from jackify.frontends.gui.screens.modlist_dashboard import ModlistDashboardScreen
        screen = ModlistDashboardScreen(
            stacked_widget=self.stacked_widget, configure_existing_index=8,
            dashboard_index=12, install_modlist_index=4, configure_new_index=6,
        )
        self.modlist_dashboard_screen = screen
        self._app_header.add_action_widget(screen.refresh_button, tab_index=12)
        self._app_header.add_action_widget(screen.check_updates_button, tab_index=12)
        return screen

    def _debug_screen_change(self, index):
        try:
            idx = int(index) if index is not None else 0
            widget = self.stacked_widget.widget(idx)
        except (OverflowError, TypeError, ValueError):
            widget = self.stacked_widget.currentWidget()
            idx = None
        if widget and hasattr(widget, 'reset_screen_to_defaults'):
            widget.reset_screen_to_defaults()
        from jackify.backend.handlers.config_handler import ConfigHandler
        config_handler = ConfigHandler()
        if not config_handler.get('debug_mode', False):
            return
        if idx is None:
            return
        try:
            screen_names = {
                0: "Main Menu",
                1: "Feature Placeholder",
                2: "Modlist Tasks Menu",
                3: "Additional Tasks Menu",
                4: "Install Modlist Screen",
                5: "Install TTW Screen",
                6: "Configure New Modlist",
                7: "Wabbajack Installer",
                8: "Configure Existing Modlist",
                9: "Install MO2 Screen",
                10: "Third Party Tools",
                11: "Configure Tool Compatibility",
            }
            screen_name = screen_names.get(idx, f"Unknown Screen (Index {idx})")
            widget = self.stacked_widget.widget(idx)
        except (OverflowError, TypeError, ValueError):
            return
        widget_class = widget.__class__.__name__ if widget else "None"
        logger.debug(f"Screen changed to Index {idx}: {screen_name} (Widget: {widget_class})")
        if idx == 4:
            logger.debug("Install Modlist Screen details:")
            logger.debug(f"  Widget type: {type(widget)}")
            logger.debug(f"  Widget file: {widget.__class__.__module__}")
            if hasattr(widget, 'windowTitle'):
                logger.debug(f"  Window title: {widget.windowTitle()}")
            if hasattr(widget, 'layout'):
                layout = widget.layout()
                if layout:
                    logger.debug(f"  Layout type: {type(layout)}")
                    logger.debug(f"  Layout children count: {layout.count()}")
