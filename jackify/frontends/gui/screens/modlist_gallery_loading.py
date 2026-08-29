"""Loading and data management for ModlistGalleryDialog (Mixin)."""
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PySide6.QtGui import QFont
from typing import List, Dict
import random
import logging
from jackify.backend.models.modlist_metadata import ModlistMetadata
from ..shared_theme import JACKIFY_COLOR_BLUE
from .modlist_gallery_card import ModlistCard

logger = logging.getLogger(__name__)


class ModlistGalleryLoadingMixin:
    """Mixin providing loading and data management for ModlistGalleryDialog."""

    def _load_modlists_async(self):
        """Load modlists in background thread for instant dialog appearance"""
        from PySide6.QtCore import QThread, Signal
        from PySide6.QtGui import QFont

        # Hide status label during loading (popup dialog will show instead)
        self.status_label.setVisible(False)
        
        # Show loading overlay directly in content area (simpler than separate dialog)
        self._loading_overlay = QWidget(self.content_area)
        self._loading_overlay.setStyleSheet("""
            QWidget {
                background-color: rgba(35, 35, 35, 240);
                border-radius: 8px;
            }
        """)
        overlay_layout = QVBoxLayout()
        overlay_layout.setContentsMargins(30, 20, 30, 20)
        overlay_layout.setSpacing(12)
        
        self._loading_label = QLabel("Loading modlists")
        self._loading_label.setAlignment(Qt.AlignCenter)
        # Set fixed width to prevent text shifting when dots animate
        # Width accommodates "Loading modlists..." (longest version)
        self._loading_label.setFixedWidth(220)
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self._loading_label.setFont(font)
        self._loading_label.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-size: 14px; font-weight: bold;")
        overlay_layout.addWidget(self._loading_label)
        
        self._loading_overlay.setLayout(overlay_layout)
        self._loading_overlay.setFixedSize(300, 120)
        
        # Animate dots in loading message
        self._loading_dot_count = 0
        self._loading_dot_timer = QTimer()
        self._loading_dot_timer.timeout.connect(self._animate_loading_dots)
        self._loading_dot_timer.start(500)  # Update every 500ms
        
        # Position overlay in center of content area
        def position_overlay():
            if getattr(self, '_loading_overlay', None) is None:
                return
            if hasattr(self, 'content_area') and self.content_area.isVisible():
                content_width = self.content_area.width()
                content_height = self.content_area.height()
                x = (content_width - 300) // 2
                y = (content_height - 120) // 2
                self._loading_overlay.move(x, y)
                self._loading_overlay.show()
                self._loading_overlay.raise_()
        
        # Delay slightly to ensure content_area is laid out
        QTimer.singleShot(50, position_overlay)

        class ModlistLoaderThread(QThread):
            """Background thread to load modlist metadata"""
            finished = Signal(object, object)  # metadata_response, error_message

            def __init__(self, gallery_service):
                super().__init__()
                self.gallery_service = gallery_service

            def run(self):
                try:
                    import time
                    start_time = time.time()

                    # Fetch metadata (CPU-intensive work happens here in background)
                    # Skip search index initially for faster loading - can be loaded later if user searches
                    metadata_response = self.gallery_service.fetch_modlist_metadata(
                        include_validation=False,
                        include_search_index=False,  # Skip for faster initial load
                        sort_by="title"
                    )

                    elapsed = time.time() - start_time
                    import logging
                    logger = logging.getLogger(__name__)
                    if elapsed < 0.5:
                        logger.debug(f"Gallery metadata loaded from cache in {elapsed:.2f}s")
                    else:
                        logger.info(f"Gallery metadata fetched from engine in {elapsed:.2f}s")

                    self.finished.emit(metadata_response, None)
                except Exception as e:
                    self.finished.emit(None, str(e))

        # Create and start background thread
        self._loader_thread = ModlistLoaderThread(self.gallery_service)
        self._loader_thread.finished.connect(self._on_modlists_loaded)
        self._loader_thread.start()


    def _animate_loading_dots(self):
        """Animate dots in loading message"""
        if hasattr(self, '_loading_label') and self._loading_label:
            self._loading_dot_count = (self._loading_dot_count + 1) % 4
            dots = "." * self._loading_dot_count
            # Pad with spaces to keep text width constant (prevents shifting)
            padding = " " * (3 - self._loading_dot_count)
            self._loading_label.setText(f"Loading modlists{dots}{padding}")


    def _on_modlists_loaded(self, metadata_response, error_message):
        """Handle modlist metadata loaded in background thread (runs in GUI thread)"""
        import random
        from PySide6.QtGui import QFont

        # Stop animation timer and close loading overlay
        if hasattr(self, '_loading_dot_timer') and self._loading_dot_timer:
            self._loading_dot_timer.stop()
            self._loading_dot_timer = None
        
        if hasattr(self, '_loading_overlay') and self._loading_overlay:
            self._loading_overlay.hide()
            self._loading_overlay.deleteLater()
            self._loading_overlay = None
        
        self.status_label.setVisible(True)

        if error_message:
            self.status_label.setText(f"Error loading modlists: {error_message}")
            return

        if not metadata_response:
            self.status_label.setText("Failed to load modlists")
            return

        try:
            # Get all modlists
            all_modlists = metadata_response.modlists

            # RANDOMIZE the order each time gallery opens (like Wabbajack)
            random.shuffle(all_modlists)

            self.all_modlists = all_modlists

            # Precompute normalized tags for display/filtering
            for modlist in self.all_modlists:
                normalized_display = self.gallery_service.normalize_tags_for_display(getattr(modlist, 'tags', []))
                modlist.normalized_tags_display = normalized_display
                modlist.normalized_tags_keys = [tag.lower() for tag in normalized_display]

            # Temporarily disconnect to prevent triggering during setup
            self.game_combo.currentIndexChanged.disconnect(self._apply_filters)

            # Populate game filter
            games = sorted(set(m.gameHumanFriendly for m in self.all_modlists))
            for game in games:
                self.game_combo.addItem(game, game)

            # If dialog was opened with a game filter, pre-select it
            if self.game_filter:
                index = self.game_combo.findData(self.game_filter)
                if index >= 0:
                    self.game_combo.setCurrentIndex(index)

            self._populate_tag_filter()

            # Create cards immediately (will show placeholders for images not in cache)
            self._create_all_cards()

            # Preload cached images in background (non-blocking)
            self.status_label.setText("Loading images...")
            QTimer.singleShot(0, self._preload_cached_images_async)

            # Reconnect filter handler
            self.game_combo.currentIndexChanged.connect(self._apply_filters)

            # Enable filter controls now that data is loaded
            self._set_filter_controls_enabled(True)

            # Apply filters (will show all modlists for selected game initially)
            self._apply_filters()

            # Start background validation update (non-blocking)
            self._start_validation_update()

        except Exception as e:
            self.status_label.setText(f"Error processing modlists: {str(e)}")


    def _load_modlists(self):
        """DEPRECATED: Synchronous loading - replaced by _load_modlists_async()"""
        from PySide6.QtWidgets import QApplication

        self.status_label.setText("Loading modlists...")
        QApplication.processEvents()  # Update UI immediately

        # Fetch metadata (will use cache if valid)
        # Skip validation initially for faster loading - can be added later if needed
        try:
            metadata_response = self.gallery_service.fetch_modlist_metadata(
                include_validation=False,  # Skip validation for faster initial load
                include_search_index=True,  # Include mod search index for mod filtering
                sort_by="title"
            )

            if metadata_response:
                # Get all modlists
                all_modlists = metadata_response.modlists
                
                # RANDOMIZE the order each time gallery opens (like Wabbajack)
                # Prevent gaming via alphabetical ordering
                random.shuffle(all_modlists)
                
                self.all_modlists = all_modlists

                # Precompute normalized tags for display/filtering (matches upstream Wabbajack)
                for modlist in self.all_modlists:
                    normalized_display = self.gallery_service.normalize_tags_for_display(getattr(modlist, 'tags', []))
                    modlist.normalized_tags_display = normalized_display
                    modlist.normalized_tags_keys = [tag.lower() for tag in normalized_display]

                # Temporarily disconnect to prevent triggering during setup
                self.game_combo.currentIndexChanged.disconnect(self._apply_filters)

                # Populate game filter
                games = sorted(set(m.gameHumanFriendly for m in self.all_modlists))
                for game in games:
                    self.game_combo.addItem(game, game)

                # If dialog was opened with a game filter, pre-select it
                if self.game_filter:
                    index = self.game_combo.findData(self.game_filter)
                    if index >= 0:
                        self.game_combo.setCurrentIndex(index)

                self._populate_tag_filter()

                # Create cards immediately (will show placeholders for images not in cache)
                self._create_all_cards()
                
                # Preload cached images in background (non-blocking)
                # Images will appear as they're loaded
                self.status_label.setText("Loading images...")
                QTimer.singleShot(0, self._preload_cached_images_async)

                # Reconnect filter handler
                self.game_combo.currentIndexChanged.connect(self._apply_filters)

                # Apply filters (will show all modlists for selected game initially)
                self._apply_filters()
                
                # Start background validation update (non-blocking)
                self._start_validation_update()
            else:
                self.status_label.setText("Failed to load modlists")
        except Exception as e:
            self.status_label.setText(f"Error loading modlists: {str(e)}")


    def _preload_cached_images_async(self):
        """Preload cached images asynchronously - images appear as they load"""
        from PySide6.QtWidgets import QApplication
        
        preloaded = 0
        total = len(self.all_modlists)
        
        for idx, modlist in enumerate(self.all_modlists):
            cache_key = modlist.machineURL
            
            # Skip if already in cache
            if cache_key in self.image_manager.pixmap_cache:
                continue
            
            # Preload large images for cards (scale down for better quality)
            cached_path = self.gallery_service.get_cached_image_path(modlist, "large")
            if cached_path and cached_path.exists():
                try:
                    pixmap = QPixmap(str(cached_path))
                    if not pixmap.isNull():
                        cache_key_large = f"{cache_key}_large"
                        self.image_manager.pixmap_cache[cache_key_large] = pixmap
                        preloaded += 1
                        
                        # Update card immediately if it exists
                        card = self.all_cards.get(cache_key)
                        if card:
                            card._display_image(pixmap)
                except Exception:
                    pass
            
            # Process events every 10 images to keep UI responsive
            if idx % 10 == 0 and idx > 0:
                QApplication.processEvents()
        
        # Update status (subtle, user-friendly)
        modlist_count = len(self.filtered_modlists)
        if modlist_count == 1:
            self.status_label.setText("1 modlist")
        else:
            self.status_label.setText(f"{modlist_count} modlists")

    def _create_all_cards(self):
        """Create cards for all modlists and store in dict"""
        # Clear existing cards
        self.all_cards.clear()
        
        # Disable updates during card creation to prevent individual renders
        self.grid_widget.setUpdatesEnabled(False)
        self.setUpdatesEnabled(False)
        
        try:
            # Create all cards - images should be in memory cache from preload
            # so _load_image() will find them instantly
            for modlist in self.all_modlists:
                card = ModlistCard(modlist, self.image_manager, is_steamdeck=self.is_steamdeck)
                card.clicked.connect(self._on_modlist_clicked)
                self.all_cards[modlist.machineURL] = card
        finally:
            # Re-enable updates - single render for all cards
            self.setUpdatesEnabled(True)
            self.grid_widget.setUpdatesEnabled(True)


    def _refresh_metadata(self):
        """Force refresh metadata from jackify-engine"""
        self.status_label.setText("Refreshing metadata...")
        self.gallery_service.clear_cache()
        self._load_modlists()


    def _start_validation_update(self):
        """Start background validation update to get availability status"""
        # Update validation in background thread to avoid blocking UI
        class ValidationUpdateThread(QThread):
            finished_signal = Signal(object)  # Emits updated metadata response
            
            def __init__(self, gallery_service):
                super().__init__()
                self.gallery_service = gallery_service
            
            def run(self):
                try:
                    # Fetch with validation (slower, but in background)
                    metadata_response = self.gallery_service.fetch_modlist_metadata(
                        include_validation=True,
                        include_search_index=False,
                        sort_by="title"
                    )
                    self.finished_signal.emit(metadata_response)
                except Exception:
                    self.finished_signal.emit(None)
        
        self._validation_thread = ValidationUpdateThread(self.gallery_service)
        self._validation_thread.finished_signal.connect(self._on_validation_updated)
        self._validation_thread.start()


    def _on_validation_updated(self, metadata_response):
        """Update modlists with validation data when background fetch completes"""
        if not metadata_response:
            return
        
        # Create lookup dict for validation data
        validation_map = {}
        for modlist in metadata_response.modlists:
            if modlist.validation:
                validation_map[modlist.machineURL] = modlist.validation
        
        # Update existing modlists with validation data
        updated_count = 0
        for modlist in self.all_modlists:
            if modlist.machineURL in validation_map:
                modlist.validation = validation_map[modlist.machineURL]
                updated_count += 1
                
                # Update card if it exists
                card = self.all_cards.get(modlist.machineURL)
                if card:
                    # Update unavailable badge visibility
                    card._update_availability_badge()
        
        # Re-apply filters to update availability filtering
        if updated_count > 0:
            self._apply_filters()


