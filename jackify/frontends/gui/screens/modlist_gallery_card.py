"""Visual card representing a single modlist."""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
from jackify.backend.models.modlist_metadata import ModlistMetadata
from ..shared_theme import JACKIFY_COLOR_BLUE
from .modlist_gallery_image_manager import ImageManager

class ModlistCard(QFrame):
    """Visual card representing a single modlist"""
    clicked = Signal(ModlistMetadata)

    def __init__(self, metadata: ModlistMetadata, image_manager: ImageManager, is_steamdeck: bool = False):
        super().__init__()
        self.metadata = metadata
        self.image_manager = image_manager
        self.is_steamdeck = is_steamdeck
        self._setup_ui()

    def _setup_ui(self):
        """Set up the card UI"""
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setCursor(Qt.PointingHandCursor)
        # Matches the Dashboard card's hover treatment - brighter, thicker border rather than
        # a size change, since these cards are fixed-size inside a reflowing grid too.
        # Selector must be the class name, not "QFrame" - QLabel is itself a QFrame subclass,
        # so a bare "QFrame" rule cascades onto every label in the card, not just the card.
        self.setStyleSheet(
            "ModlistCard { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; } "
            "ModlistCard:hover { background-color: #333333; border: 1px solid #5a9fd6; }"
        )
        
        # Steam Deck-specific sizing (1280x800 screen)
        if self.is_steamdeck:
            self.setFixedSize(250, 245)  # Smaller cards for Steam Deck
            image_width, image_height = 230, 130  # Smaller images, maintaining 16:9 ratio
        else:
            self.setFixedSize(300, 292)  # Standard size
            image_width, image_height = 280, 158  # Standard image size
        
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 8, 10, 8)  # Reduced vertical margins
        layout.setSpacing(6)  # Reduced spacing between elements

        # Image (widescreen aspect ratio like Wabbajack)
        self.image_label = QLabel()
        self.image_label.setFixedSize(image_width, image_height)  # 16:9 aspect ratio
        self.image_label.setStyleSheet("background: #333; border-radius: 4px;")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(True)  # Use Qt's automatic scaling - this works best
        self.image_label.setText("")
        layout.addWidget(self.image_label)

        # Title row with badges (Official, NSFW, UNAVAILABLE)
        title_row = QHBoxLayout()
        title_row.setSpacing(4)

        title = QLabel(self.metadata.title)
        title.setWordWrap(True)
        title.setFont(QFont("Sans", 12, QFont.Bold))
        title.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE};")
        title.setMaximumHeight(40)
        title_row.addWidget(title, stretch=1)

        # Store reference to unavailable badge for dynamic updates
        self.unavailable_badge = None
        if not self.metadata.is_available():
            self.unavailable_badge = QLabel("UNAVAILABLE")
            self.unavailable_badge.setStyleSheet("background: #666; color: white; padding: 2px 6px; font-size: 9px; border-radius: 3px;")
            self.unavailable_badge.setFixedHeight(20)
            title_row.addWidget(self.unavailable_badge, alignment=Qt.AlignTop | Qt.AlignRight)

        if self.metadata.official:
            official_badge = QLabel("OFFICIAL")
            official_badge.setStyleSheet("background: #2a5; color: white; padding: 2px 6px; font-size: 9px; border-radius: 3px;")
            official_badge.setFixedHeight(20)
            title_row.addWidget(official_badge, alignment=Qt.AlignTop | Qt.AlignRight)

        if self.metadata.nsfw:
            nsfw_badge = QLabel("NSFW")
            nsfw_badge.setStyleSheet("background: #d44; color: white; padding: 2px 6px; font-size: 9px; border-radius: 3px;")
            nsfw_badge.setFixedHeight(20)
            title_row.addWidget(nsfw_badge, alignment=Qt.AlignTop | Qt.AlignRight)

        layout.addLayout(title_row)

        # Author
        author = QLabel(f"by {self.metadata.author}")
        author.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(author)

        # Game
        game = QLabel(self.metadata.gameHumanFriendly)
        game.setStyleSheet("color: #ccc; font-size: 10px;")
        layout.addWidget(game)

        # Sizes (Download, Install, Total)
        if self.metadata.sizes:
            size_info = QLabel(
                f"Download: {self.metadata.sizes.downloadSizeFormatted} | "
                f"Install: {self.metadata.sizes.installSizeFormatted} | "
                f"Total: {self.metadata.sizes.totalSizeFormatted}"
            )
            size_info.setStyleSheet("color: #999; font-size: 10px;")
            size_info.setWordWrap(True)  # Allow wrapping if text is too long
            layout.addWidget(size_info)

        self.setLayout(layout)

        # Load image
        self._load_image()

    def _create_placeholder(self):
        """Create a placeholder pixmap for cards without images"""
        # Create placeholder matching the image label size (Steam Deck or standard)
        image_size = self.image_label.size()
        placeholder = QPixmap(image_size)
        placeholder.fill(QColor("#333"))
        
        # Draw a simple icon/text on the placeholder
        painter = QPainter(placeholder)
        painter.setPen(QColor("#666"))
        painter.setFont(QFont("Sans", 10))
        painter.drawText(placeholder.rect(), Qt.AlignCenter, "No Image")
        painter.end()
        
        # Show placeholder immediately
        self.image_label.setPixmap(placeholder)

    def _load_image(self):
        """Load image using centralized image manager - use large images and scale down for quality"""
        # Get large image for card - scale down for better quality than small images
        pixmap = self.image_manager.get_image(self.metadata, self._on_image_loaded, size="large")
        
        if pixmap and not pixmap.isNull():
            # Image was in cache - display immediately (should be instant)
            self._display_image(pixmap)
        else:
            # Image needs to be downloaded - show placeholder
            self._create_placeholder()
    
    def _on_image_loaded(self, pixmap: QPixmap):
        """Callback when image is loaded from network"""
        if pixmap and not pixmap.isNull():
            self._display_image(pixmap)
    
    def _display_image(self, pixmap: QPixmap):
        """Display image - use best method based on aspect ratio"""
        if pixmap.isNull():
            return
        
        label_size = self.image_label.size()
        label_aspect = label_size.width() / label_size.height()  # 16:9 = ~1.778
        
        # Calculate image aspect ratio
        image_aspect = pixmap.width() / pixmap.height() if pixmap.height() > 0 else label_aspect
        
        # If aspect ratios are close (within 5%), use Qt's automatic scaling for best quality
        # Otherwise, manually scale with cropping to avoid stretching
        aspect_diff = abs(image_aspect - label_aspect) / label_aspect
        
        if aspect_diff < 0.05:  # Within 5% of 16:9
            # Close to correct aspect - use Qt's automatic scaling (best quality)
            self.image_label.setScaledContents(True)
            self.image_label.setPixmap(pixmap)
        else:
            # Different aspect - manually scale with cropping (no stretching)
            self.image_label.setScaledContents(False)
            scaled_pixmap = pixmap.scaled(
                label_size.width(),
                label_size.height(),
                Qt.KeepAspectRatioByExpanding,  # Crop instead of stretch
                Qt.SmoothTransformation  # High quality
            )
            self.image_label.setPixmap(scaled_pixmap)
    
    def _update_availability_badge(self):
        """Update unavailable badge visibility based on current availability status"""
        is_unavailable = not self.metadata.is_available()
        
        # Find title row layout (it's the 2nd layout item: image at 0, title_row at 1)
        main_layout = self.layout()
        if main_layout and main_layout.count() >= 2:
            title_row = main_layout.itemAt(1).layout()
            if title_row:
                if is_unavailable and self.unavailable_badge is None:
                    # Need to add badge to title row (before Official/NSFW badges)
                    self.unavailable_badge = QLabel("UNAVAILABLE")
                    self.unavailable_badge.setStyleSheet("background: #666; color: white; padding: 2px 6px; font-size: 9px; border-radius: 3px;")
                    self.unavailable_badge.setFixedHeight(20)
                    # Insert after title (index 1) but before other badges
                    # Find first badge position (if any exist)
                    insert_index = 1  # After title widget
                    for i in range(title_row.count()):
                        item = title_row.itemAt(i)
                        if item and item.widget() and isinstance(item.widget(), QLabel):
                            widget_text = item.widget().text()
                            if widget_text in ("OFFICIAL", "NSFW"):
                                insert_index = i
                                break
                    title_row.insertWidget(insert_index, self.unavailable_badge, alignment=Qt.AlignTop | Qt.AlignRight)
                elif not is_unavailable and self.unavailable_badge is not None:
                    # Need to remove badge from title row
                    title_row.removeWidget(self.unavailable_badge)
                    self.unavailable_badge.setParent(None)
                    self.unavailable_badge = None

    def mousePressEvent(self, event):
        """Handle click on card"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.metadata)
        super().mousePressEvent(event)
