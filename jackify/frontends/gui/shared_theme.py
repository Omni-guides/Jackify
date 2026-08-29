"""
Jackify GUI theme and shared constants
"""
import os
from typing import Optional

JACKIFY_COLOR_BLUE = "#3fd0ea"  # Official Jackify blue
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')
LOGO_PATH = os.path.join(ASSETS_DIR, 'jackify_logo.png')
BANNER_PATH = os.path.join(ASSETS_DIR, 'jackify_banner.png')  # transparent background
DISCLAIMER_TEXT = (
    "Jackify is provided as-is. Back up your modlist and game data before making changes. "
    "The developers are not responsible for data loss or other issues arising from its use."
)

# Card/panel button colors, previously redeclared independently per screen.
COLOR_BTN_INSTALL = "#1a5fa8"
COLOR_BTN_LAUNCH = "#1a5fa8"
COLOR_BTN_UPDATE = "#4a5568"
COLOR_BTN_BACK = "#4a5568"
COLOR_BTN_SET_ACTIVE = "#4a5568"
COLOR_BTN_DISABLED = "#333"

# Header/menu separator line, previously a hardcoded literal repeated in main_menu.py
# and app_header.py.
COLOR_SEPARATOR = "#fff"

# Card-style QGroupBox panel, previously an identical literal repeated six times in
# settings_dialog_tabs.py and absent (default Fusion style) in about_dialog.py.
GROUP_BOX_STYLE = (
    "QGroupBox { border: 1px solid #3a3a3a; border-radius: 6px; margin-top: 8px; "
    "padding: 8px; background: #2a2a2a; } "
    "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; "
    f"font-weight: bold; color: {JACKIFY_COLOR_BLUE}; }}"
)

# Flat underline-tab look used by the persistent header (modlist_dashboard_tabs.py's
# custom QPushButton tabs) and shared here so a real QTabBar (e.g. Settings) can match it
# instead of drawing Qt's default boxy tab style.
COLOR_TAB_ACTIVE_BG = "#232323"
COLOR_TAB_INACTIVE_TEXT = "#999"
COLOR_TAB_HOVER_BG = "#2a2a2a"

TAB_BAR_STYLE = (
    "QTabWidget::pane { border: 1px solid #3a3a3a; background: #232323; } "
    "QTabBar::tab { background: transparent; color: " + COLOR_TAB_INACTIVE_TEXT + "; "
    "border: none; border-bottom: 2px solid transparent; "
    "border-top-left-radius: 6px; border-top-right-radius: 6px; "
    "font-size: 13px; font-weight: bold; padding: 6px 18px; margin-right: 4px; } "
    "QTabBar::tab:selected { background: " + COLOR_TAB_ACTIVE_BG + "; color: " + JACKIFY_COLOR_BLUE + "; "
    "border-bottom: 2px solid " + JACKIFY_COLOR_BLUE + "; } "
    "QTabBar::tab:hover:!selected { background: " + COLOR_TAB_HOVER_BG + "; color: " + JACKIFY_COLOR_BLUE + "; }"
)


def btn_style(colour: str, disabled: bool = False, width: Optional[int] = None) -> str:
    """Stylesheet for a card/panel action button.

    width=None reproduces the Dashboard card's original compact style (padding 4px 2px,
    no min-width); passing a width reproduces Tools Hub's style (padding 4px 8px, a
    min-width). Both shapes are kept so migrating callers doesn't change existing layouts.
    """
    bg = COLOR_BTN_DISABLED if disabled else colour
    hover = "#444" if disabled else colour
    fg = "#666" if disabled else "white"
    if width is not None:
        return (
            f"QPushButton {{ background-color: {bg}; color: {fg}; "
            f"border: none; border-radius: 4px; font-size: 11px; font-weight: bold; "
            f"padding: 4px 8px; min-width: {width}px; }}"
            f"QPushButton:hover {{ background-color: {hover}; }}"
        )
    return (
        f"QPushButton {{ background-color: {bg}; color: {fg}; "
        f"border: none; border-radius: 4px; font-size: 11px; font-weight: bold; "
        f"padding: 4px 2px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
    )


def apply_dark_palette(app) -> None:
    """
    Force a consistent dark look regardless of the desktop's own Qt/GTK theme.

    Every screen already paints its own dark backgrounds via inline stylesheets - those
    assume a dark base underneath. Without this, the app inherits whatever palette the
    desktop environment hands it (e.g. a light GTK theme on Gnome), which shows through
    behind/between the per-widget styling and looks broken. Fusion is used because it is
    the one Qt style that fully honors a custom QPalette instead of delegating to the
    platform theme.
    """
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QStyleFactory

    app.setStyle(QStyleFactory.create("Fusion"))

    palette = QPalette()
    window = QColor("#1e1e1e")
    base = QColor("#181818")
    panel = QColor("#2a2a2a")
    text = QColor("#e0e0e0")
    disabled_text = QColor("#777777")
    accent = QColor(JACKIFY_COLOR_BLUE)

    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, panel)
    palette.setColor(QPalette.ToolTipBase, panel)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, panel)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor("#ff5555"))
    palette.setColor(QPalette.Link, accent)
    palette.setColor(QPalette.Highlight, accent)
    palette.setColor(QPalette.HighlightedText, QColor("#0a0a0a"))
    palette.setColor(QPalette.PlaceholderText, disabled_text)

    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, disabled_text)

    app.setPalette(palette)