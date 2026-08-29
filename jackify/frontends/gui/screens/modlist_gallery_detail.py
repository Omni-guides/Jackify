"""Detailed view of a modlist with install option."""
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QSize, QEvent
from PySide6.QtGui import QPixmap, QFont, QPainter, QColor
from jackify.backend.models.modlist_metadata import ModlistMetadata
from ..shared_theme import JACKIFY_COLOR_BLUE
from ..utils import get_screen_geometry, set_responsive_minimum
from .modlist_gallery_image_manager import ImageManager

class ModlistDetailDialog(QDialog):
    """Detailed view of a modlist with install option"""
    install_requested = Signal(ModlistMetadata)

    def __init__(self, metadata: ModlistMetadata, image_manager: ImageManager, parent=None):
        super().__init__(parent)
        self.metadata = metadata
        self.image_manager = image_manager
        self.setWindowTitle(metadata.title)
        set_responsive_minimum(self, min_width=900, min_height=640)
        self._apply_initial_size()
        self._setup_ui()

    def _apply_initial_size(self):
        """Ensure dialog size fits current screen."""
        _, _, screen_width, screen_height = get_screen_geometry(self)
        width = 1000
        height = 760
        if screen_width:
            width = min(width, max(880, screen_width - 40))
        if screen_height:
            height = min(height, max(640, screen_height - 40))
        self.resize(width, height)

    def _setup_ui(self):
        """Set up detail dialog UI with modern layout matching Wabbajack style"""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        # --- Banner area with full-width text overlay ---
        # Container so we can place a semi-opaque text panel over the banner image
        banner_container = QFrame()
        banner_container.setFrameShape(QFrame.NoFrame)
        banner_container.setStyleSheet("background: #000; border: none;")
        banner_layout = QVBoxLayout()
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_layout.setSpacing(0)
        banner_container.setLayout(banner_layout)

        # Banner image at top with 16:9 aspect ratio (like Wabbajack)
        self.banner_label = QLabel()
        # Height will be calculated based on width to maintain 16:9 ratio
        self.banner_label.setMinimumHeight(200)
        self.banner_label.setStyleSheet("background: #1a1a1a; border: none;")
        self.banner_label.setAlignment(Qt.AlignCenter)
        self.banner_label.setText("Loading image...")
        banner_layout.addWidget(self.banner_label)

        # Gradient scrim across the full width rather than a bounded card. A rounded box with
        # its own border read as a panel pasted onto the artwork; the gradient darkens into the
        # image, so there is no edge to notice.
        #
        # Child of the banner label, positioned by hand, not placed in the layout: the label is
        # given a 16:9 height that exceeds the row the layout allots it, so anything the layout
        # positions "under" the image lands part-way up it instead of at its foot.
        self.banner_text_panel = QFrame(self.banner_label)
        self.banner_text_panel.setFrameShape(QFrame.NoFrame)
        self.banner_text_panel.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 rgba(0, 0, 0, 0), stop:0.35 rgba(0, 0, 0, 140), stop:1 rgba(0, 0, 0, 225)); "
            "border: none; }"
        )
        self.banner_text_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        banner_text_layout = QVBoxLayout()
        banner_text_layout.setContentsMargins(24, 40, 24, 20)
        banner_text_layout.setSpacing(6)
        self.banner_text_panel.setLayout(banner_text_layout)
        # Panel height now exceeds the text's own sizeHint (grows with the banner);
        # push the text to the bottom of that extra space instead of letting it float.
        banner_text_layout.addStretch(1)

        self.banner_label.installEventFilter(self)

        # Title only (badges moved to tags section below)
        title = QLabel(self.metadata.title)
        title.setFont(QFont("Sans", 24, QFont.Bold))
        title.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE};")
        title.setWordWrap(True)
        banner_text_layout.addWidget(title)

        # Only sizes in overlay (minimal info on image)
        if self.metadata.sizes:
            sizes_text = (
                f"<span style='color: #aaa;'>Download:</span> {self.metadata.sizes.downloadSizeFormatted} • "
                f"<span style='color: #aaa;'>Install:</span> {self.metadata.sizes.installSizeFormatted} • "
                f"<span style='color: #aaa;'>Total:</span> {self.metadata.sizes.totalSizeFormatted}"
            )
            sizes_label = QLabel(sizes_text)
            sizes_label.setStyleSheet("color: #fff; font-size: 13px;")
            banner_text_layout.addWidget(sizes_label)

        # Add full-width transparent container at bottom of banner
        main_layout.addWidget(banner_container)

        # Content area with padding (tags + description + bottom bar)
        content_widget = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(16)
        content_widget.setLayout(content_layout)

        # Metadata line (version, author, game) - moved below image
        metadata_line_parts = []
        if self.metadata.version:
            metadata_line_parts.append(f"<span style='color: #aaa;'>version</span> {self.metadata.version}")
        metadata_line_parts.append(f"<span style='color: #aaa;'>by</span> {self.metadata.author}")
        metadata_line_parts.append(f"<span style='color: #aaa;'>•</span> {self.metadata.gameHumanFriendly}")
        
        if self.metadata.maintainers and len(self.metadata.maintainers) > 0:
            maintainers_text = ", ".join(self.metadata.maintainers)
            if maintainers_text != self.metadata.author:  # Only show if different from author
                metadata_line_parts.append(f"<span style='color: #aaa;'>•</span> Maintained by {maintainers_text}")
        
        metadata_line = QLabel(" ".join(metadata_line_parts))
        metadata_line.setStyleSheet("color: #fff; font-size: 14px;")
        metadata_line.setWordWrap(True)
        content_layout.addWidget(metadata_line)

        # Tags row (includes status badges moved from overlay)
        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(6)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        
        # Add status badges first (UNAVAILABLE, Unofficial)
        if not self.metadata.is_available():
            unavailable_badge = QLabel("UNAVAILABLE")
            unavailable_badge.setStyleSheet("background: #666; color: white; padding: 6px 12px; font-size: 11px; border-radius: 4px;")
            tags_layout.addWidget(unavailable_badge)
        
        if not self.metadata.official:
            unofficial_badge = QLabel("Unofficial")
            unofficial_badge.setStyleSheet("background: #666; color: white; padding: 6px 12px; font-size: 11px; border-radius: 4px;")
            tags_layout.addWidget(unofficial_badge)
        
        # Add regular tags
        tags_to_render = getattr(self.metadata, 'normalized_tags_display', self.metadata.tags or [])
        if tags_to_render:
            for tag in tags_to_render:
                tag_badge = QLabel(tag)
                # Match Wabbajack tag styling
                if tag.lower() == "nsfw":
                    tag_badge.setStyleSheet("background: #d44; color: white; padding: 6px 12px; font-size: 11px; border-radius: 4px;")
                elif tag.lower() == "official" or tag.lower() == "featured":
                    tag_badge.setStyleSheet("background: #2a5; color: white; padding: 6px 12px; font-size: 11px; border-radius: 4px;")
                else:
                    tag_badge.setStyleSheet("background: #3a3a3a; color: #ccc; padding: 6px 12px; font-size: 11px; border-radius: 4px;")
                tags_layout.addWidget(tag_badge)
        
        tags_layout.addStretch()
        content_layout.addLayout(tags_layout)

        # Description section
        desc_label = QLabel("<b style='color: #aaa; font-size: 14px;'>Description:</b>")
        content_layout.addWidget(desc_label)

        # Use QTextEdit with explicit line counting to force scrollbar
        self.desc_text = QTextEdit()
        self.desc_text.setReadOnly(True)
        self.desc_text.setPlainText(self.metadata.description or "No description provided.")
        # Compact description area; scroll when content is long
        self.desc_text.setFixedHeight(120)
        self.desc_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.desc_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.desc_text.setLineWrapMode(QTextEdit.WidgetWidth)
        self.desc_text.setStyleSheet("""
            QTextEdit {
                background: #2a2a2a;
                color: #fff;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }
        """)

        content_layout.addWidget(self.desc_text)

        main_layout.addWidget(content_widget)

        # Bottom bar with Links (left) and Action buttons (right)
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(24, 16, 24, 24)
        bottom_bar.setSpacing(12)
        
        # Links section on the left
        links_layout = QHBoxLayout()
        links_layout.setSpacing(10)
        
        if self.metadata.links and (self.metadata.links.discordURL or self.metadata.links.websiteURL or self.metadata.links.readme):
            links_label = QLabel("<b style='color: #aaa; font-size: 14px;'>Links:</b>")
            links_layout.addWidget(links_label)
            
            if self.metadata.links.discordURL:
                discord_btn = QPushButton("Discord")
                discord_btn.setStyleSheet("""
                    QPushButton {
                        background: #5865F2;
                        color: white;
                        padding: 8px 16px;
                        border: none;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background: #4752C4;
                    }
                    QPushButton:pressed {
                        background: #3C45A5;
                    }
                """)
                discord_btn.clicked.connect(lambda: self._open_url(self.metadata.links.discordURL))
                links_layout.addWidget(discord_btn)
            
            if self.metadata.links.websiteURL:
                website_btn = QPushButton("Website")
                website_btn.setStyleSheet("""
                    QPushButton {
                        background: #3a3a3a;
                        color: white;
                        padding: 8px 16px;
                        border: none;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background: #4a4a4a;
                    }
                    QPushButton:pressed {
                        background: #2a2a2a;
                    }
                """)
                website_btn.clicked.connect(lambda: self._open_url(self.metadata.links.websiteURL))
                links_layout.addWidget(website_btn)
            
            if self.metadata.links.readme:
                readme_btn = QPushButton("Readme")
                readme_btn.setStyleSheet("""
                    QPushButton {
                        background: #3a3a3a;
                        color: white;
                        padding: 8px 16px;
                        border: none;
                        border-radius: 6px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background: #4a4a4a;
                    }
                    QPushButton:pressed {
                        background: #2a2a2a;
                    }
                """)
                readme_url = self._convert_raw_github_url(self.metadata.links.readme)
                readme_btn.clicked.connect(lambda: self._open_url(readme_url))
                links_layout.addWidget(readme_btn)
        
        bottom_bar.addLayout(links_layout)
        bottom_bar.addStretch()

        # Action buttons on the right

        cancel_btn = QPushButton("Close")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a;
                color: white;
                padding: 8px 16px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #4a4a4a;
            }
            QPushButton:pressed {
                background: #2a2a2a;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        bottom_bar.addWidget(cancel_btn)

        install_btn = QPushButton("Install Modlist")
        install_btn.setDefault(True)
        if not self.metadata.is_available():
            install_btn.setEnabled(False)
            install_btn.setToolTip("This modlist is currently unavailable")
            install_btn.setStyleSheet("""
                QPushButton {
                    background: #555;
                    color: #999;
                    padding: 8px 16px;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 12px;
                }
            """)
        else:
            install_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {JACKIFY_COLOR_BLUE};
                    color: white;
                    padding: 8px 16px;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background: #4a9eff;
                }}
                QPushButton:pressed {{
                    background: #3a8eef;
                }}
            """)
        install_btn.clicked.connect(self._on_install_clicked)
        bottom_bar.addWidget(install_btn)

        main_layout.addLayout(bottom_bar)
        self.setLayout(main_layout)
        
        # Load banner image
        self._load_banner_image()

    def _load_banner_image(self):
        """Load large banner image for detail view"""
        if not self.metadata.images or not self.metadata.images.large:
            self.banner_label.setText("No image available")
            self.banner_label.setStyleSheet("background: #1a1a1a; color: #666; border: none;")
            return
        
        # Try to get large image from cache or download (for detail view banner)
        pixmap = self.image_manager.get_image(self.metadata, self._on_banner_loaded, size="large")
        
        if pixmap and not pixmap.isNull():
            # Image was in cache - display immediately
            self._display_banner(pixmap)
        else:
            # Show placeholder while downloading
            placeholder = QPixmap(self.banner_label.size())
            placeholder.fill(QColor("#1a1a1a"))
            painter = QPainter(placeholder)
            painter.setPen(QColor("#666"))
            painter.setFont(QFont("Sans", 12))
            painter.drawText(placeholder.rect(), Qt.AlignCenter, "Loading image...")
            painter.end()
            self.banner_label.setPixmap(placeholder)
    
    def _on_banner_loaded(self, pixmap: QPixmap):
        """Callback when banner image is loaded"""
        if pixmap and not pixmap.isNull():
            self._display_banner(pixmap)
    
    def eventFilter(self, obj, event):
        if obj is getattr(self, 'banner_label', None) and event.type() == QEvent.Resize:
            self._position_banner_scrim()
        return super().eventFilter(obj, event)

    def _position_banner_scrim(self):
        """Pin the scrim to the foot of the banner image, full width.

        Height scales with the banner itself (not just the text content) so the
        gradient still reads on tall/bright images instead of being confined to a
        thin band the text barely needs.
        """
        if not hasattr(self, 'banner_text_panel'):
            return
        height = max(
            self.banner_text_panel.sizeHint().height(),
            int(self.banner_label.height() * 0.4),
        )
        self.banner_text_panel.setGeometry(
            0, max(0, self.banner_label.height() - height), self.banner_label.width(), height
        )

    def resizeEvent(self, event):
        """Handle dialog resize to maintain 16:9 aspect ratio for banner"""
        super().resizeEvent(event)
        # Update banner height to maintain 16:9 aspect ratio
        if hasattr(self, 'banner_label'):
            width = self.width()
            height = int(width / 16 * 9)  # 16:9 aspect ratio
            self.banner_label.setFixedHeight(height)
            # Redisplay image if we have one
            if hasattr(self, '_current_banner_pixmap'):
                self._display_banner(self._current_banner_pixmap)
    
    def _display_banner(self, pixmap: QPixmap):
        """Display banner image with proper 16:9 aspect ratio (like Wabbajack)"""
        # Store pixmap for resize events
        self._current_banner_pixmap = pixmap
        
        # Calculate 16:9 aspect ratio height
        width = self.width() if self.width() > 0 else 1000
        target_height = int(width / 16 * 9)
        self.banner_label.setFixedHeight(target_height)
        
        # Scale image to fill width while maintaining aspect ratio (UniformToFill behavior)
        # Crops if needed, no stretch
        scaled_pixmap = pixmap.scaled(
            width,
            target_height,
            Qt.KeepAspectRatioByExpanding,  # Fill the area, cropping if needed
            Qt.SmoothTransformation
        )
        self.banner_label.setPixmap(scaled_pixmap)
        self.banner_label.setText("")

    def _convert_raw_github_url(self, url: str) -> str:
        """Convert raw GitHub URLs to rendered blob URLs for better user experience"""
        if not url:
            return url

        if "raw.githubusercontent.com" in url:
            url = url.replace("raw.githubusercontent.com", "github.com")
            url = url.replace("/master/", "/blob/master/")
            url = url.replace("/main/", "/blob/main/")

        return url

    def _on_install_clicked(self):
        """Handle install button click"""
        self.install_requested.emit(self.metadata)
        self.accept()

    def _open_url(self, url: str):
        """Open URL with clean environment to avoid AppImage library conflicts."""
        import subprocess
        import os

        env = os.environ.copy()

        # Remove AppImage-specific environment variables
        appimage_vars = [
            'LD_LIBRARY_PATH',
            'PYTHONPATH',
            'PYTHONHOME',
            'QT_PLUGIN_PATH',
            'QML2_IMPORT_PATH',
        ]

        if 'APPIMAGE' in env or 'APPDIR' in env:
            for var in appimage_vars:
                if var in env:
                    del env[var]

        subprocess.Popen(
            ['xdg-open', url],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
