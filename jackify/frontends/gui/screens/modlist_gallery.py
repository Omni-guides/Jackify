"""
Enhanced Modlist Gallery Screen for Jackify GUI.

Provides visual browsing, filtering, and selection of modlists using
rich metadata from jackify-engine.
"""
import warnings
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QScrollArea, QGridLayout,
    QFrame, QSizePolicy, QDialog, QTextEdit, QTextBrowser, QMessageBox, QListWidget
)
from PySide6.QtCore import Qt, Signal, QSize, QThread, QUrl, QTimer, QObject
from PySide6.QtGui import QPixmap, QFont, QPainter, QColor, QTextOption, QPalette
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from pathlib import Path
from typing import List, Optional, Dict
from collections import deque
import random

from jackify.backend.services.modlist_gallery_service import ModlistGalleryService
from jackify.backend.models.modlist_metadata import ModlistMetadata, ModlistMetadataResponse
from ..shared_theme import JACKIFY_COLOR_BLUE
from ..utils import get_screen_geometry, set_responsive_minimum
from .modlist_gallery_image_manager import ImageManager
from .modlist_gallery_card import ModlistCard
from .modlist_gallery_detail import ModlistDetailDialog
from .modlist_gallery_filters import ModlistGalleryFiltersMixin
from .modlist_gallery_loading import ModlistGalleryLoadingMixin


class ModlistGalleryDialog(ModlistGalleryFiltersMixin, ModlistGalleryLoadingMixin, QDialog):
    """Enhanced modlist gallery dialog with visual browsing"""
    modlist_selected = Signal(ModlistMetadata)

    def __init__(self, game_filter: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Modlist")
        self.setModal(True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#111111"))
        self.setPalette(palette)
        
        # Detect Steam Deck
        from jackify.backend.services.platform_detection_service import PlatformDetectionService
        platform_service = PlatformDetectionService.get_instance()
        self.is_steamdeck = platform_service.is_steamdeck
        
        # Responsive sizing for different screen sizes (especially Steam Deck 1280x800)
        min_height = 650 if self.is_steamdeck else 700
        set_responsive_minimum(self, min_width=1100 if self.is_steamdeck else 1200, min_height=min_height)
        self._apply_initial_size()

        self.gallery_service = ModlistGalleryService()
        self.image_manager = ImageManager(self.gallery_service)
        self.all_modlists: List[ModlistMetadata] = []
        self.filtered_modlists: List[ModlistMetadata] = []
        self.game_filter = game_filter
        self.selected_metadata: Optional[ModlistMetadata] = None
        self.all_cards: Dict[str, ModlistCard] = {}  # Dict keyed by machineURL for quick lookup
        self._validation_update_timer = None  # Timer for background validation updates

        self._setup_ui()
        # Disable filter controls during initial load to prevent race conditions
        self._set_filter_controls_enabled(False)
        # Lazy load - fetch modlists when dialog is shown

    def _apply_initial_size(self):
        """Ensure dialog fits on screen while maximizing usable space."""
        _, _, screen_width, screen_height = get_screen_geometry(self)
        width = 1400
        height = 800
        
        if self.is_steamdeck or (screen_width and screen_width <= 1280):
            width = min(width, 1200)
            height = min(height, 750)
        
        if screen_width:
            width = min(width, max(1000, screen_width - 40))
        if screen_height:
            height = min(height, max(640, screen_height - 40))
        
        self.resize(width, height)

    def showEvent(self, event):
        """Fetch modlists when dialog is first shown"""
        super().showEvent(event)
        if not self.all_modlists:
            # Start loading in background thread for instant dialog appearance
            self._load_modlists_async()

    def _setup_ui(self):
        """Set up the gallery UI"""
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Left sidebar (filters)
        filter_panel = self._create_filter_panel()
        main_layout.addWidget(filter_panel)

        # Right content area (modlist grid)
        self.content_area = self._create_content_area()
        main_layout.addWidget(self.content_area, stretch=1)

        self.setLayout(main_layout)

    def _create_content_area(self) -> QWidget:
        """Create modlist grid content area"""
        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Status label (subtle, top-right) - hidden during initial loading (popup shows instead)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 10px;")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        layout.addWidget(self.status_label)

        # Scroll area for modlist cards
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Grid container for cards
        self.grid_widget = QWidget()
        # Don't use WA_StaticContents - we need resize events to recalculate columns
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(8)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_widget.setLayout(self.grid_layout)

        self.scroll_area.setWidget(self.grid_widget)
        layout.addWidget(self.scroll_area)

        container.setLayout(layout)
        return container

    def _update_grid(self):
        """Update grid by removing all cards and re-adding only visible ones"""
        # CRITICAL: Guard against race condition - don't update if cards aren't ready yet
        if not self.all_cards:
            return
        
        # Disable updates during grid update
        self.grid_widget.setUpdatesEnabled(False)
        
        try:
            # Remove all cards from layout
            # CRITICAL FIX: Properly remove all widgets to prevent overlapping
            # Iterate backwards to avoid index shifting issues
            for i in range(self.grid_layout.count() - 1, -1, -1):
                item = self.grid_layout.takeAt(i)
                widget = item.widget() if item else None
                if widget:
                    # Hide widget during removal to prevent visual artifacts
                    widget.hide()
                del item
            
            # Force layout update to ensure all widgets are removed
            self.grid_layout.update()

            # Calculate number of columns based on available width
            # Get the scroll area width (accounting for filter panel ~280px + margins)
            scroll_area = self.grid_widget.parent()
            if scroll_area and hasattr(scroll_area, 'viewport'):
                available_width = scroll_area.viewport().width()
            else:
                # Fallback: estimate based on dialog width minus filter panel
                available_width = self.width() - 280 - 32  # Filter panel + margins
            
            if available_width <= 0:
                # Fallback if width not yet calculated
                available_width = 900 if not self.is_steamdeck else 700
            
            # Card width + spacing between cards
            if self.is_steamdeck:
                card_width = 250
            else:
                card_width = 300
            
            card_spacing = 8
            # Calculate how many columns fit
            columns = max(1, int((available_width + card_spacing) / (card_width + card_spacing)))
            
            # Limit to reasonable max (4 columns on large screens, 3 on Steam Deck)
            if not self.is_steamdeck:
                columns = min(columns, 4)
            else:
                columns = min(columns, 3)

            # Preserve randomized order (already shuffled in _load_modlists)
            # Add visible cards to grid in order
            for idx, modlist in enumerate(self.filtered_modlists):
                row = idx // columns
                col = idx % columns
                
                card = self.all_cards.get(modlist.machineURL)
                if card:
                    # Safety check: ensure widget is not already in the layout
                    # (shouldn't happen after proper removal above, but defensive programming)
                    already_in_layout = False
                    for i in range(self.grid_layout.count()):
                        item = self.grid_layout.itemAt(i)
                        if item and item.widget() == card:
                            # Widget is already in layout - this shouldn't happen, but handle it
                            already_in_layout = True
                            self.grid_layout.removeWidget(card)
                            break
                    
                    # Ensure widget is visible and add to grid
                    if not already_in_layout or card.isHidden():
                        card.show()
                    self.grid_layout.addWidget(card, row, col)
            
            # Set column stretch - don't stretch card columns, but add a spacer column
            for col in range(columns):
                self.grid_layout.setColumnStretch(col, 0)  # Cards are fixed width
            # Add a stretch column after cards to fill remaining space (centers the grid)
            if columns < 4:
                self.grid_layout.setColumnStretch(columns, 1)
        finally:
            # Re-enable updates
            self.grid_widget.setUpdatesEnabled(True)
            self.grid_widget.update()

        # Update status
        self.status_label.setText(f"Showing {len(self.filtered_modlists)} modlists")

    def resizeEvent(self, event):
        """Handle dialog resize to recalculate grid columns"""
        super().resizeEvent(event)
        # Recalculate columns when dialog is resized
        if hasattr(self, 'filtered_modlists') and self.filtered_modlists:
            self._update_grid()

    def _on_modlist_clicked(self, metadata: ModlistMetadata):
        """Handle modlist card click - show detail dialog"""
        dialog = ModlistDetailDialog(metadata, self.image_manager, self)
        dialog.install_requested.connect(self._on_install_requested)
        dialog.exec()

    def _on_install_requested(self, metadata: ModlistMetadata):
        """Handle install request from detail dialog"""
        self.selected_metadata = metadata
        self.modlist_selected.emit(metadata)
        self.accept()

    def closeEvent(self, event):
        """Stop background threads before the dialog is destroyed."""
        # Stop the loading dot animation timer first
        timer = getattr(self, '_loading_dot_timer', None)
        if timer is not None:
            timer.stop()

        # Kill any in-progress engine subprocess so the loader thread exits
        # naturally and releases the engine call lock.
        if hasattr(self, 'gallery_service'):
            self.gallery_service.cancel()

        for attr in ('_loader_thread', '_validation_thread'):
            thread = getattr(self, attr, None)
            if thread is None:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    thread.disconnect()
                except Exception:
                    pass
            if thread.isRunning():
                # Give the thread time to exit naturally after cancel().
                # Only fall back to terminate() if it is still stuck after that.
                if not thread.wait(2000):
                    thread.terminate()
                    thread.wait(1000)

        # Abort any pending image network requests
        if hasattr(self, 'image_manager'):
            try:
                self.image_manager.network_manager.clearConnectionCache()
            except Exception:
                pass

        super().closeEvent(event)

# Re-export for backward compatibility
__all__ = ['ImageManager', 'ModlistCard', 'ModlistDetailDialog', 'ModlistGalleryDialog']

