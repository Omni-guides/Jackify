"""Filter management for ModlistGalleryDialog (Mixin)."""
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox, QListWidget, QPushButton
from PySide6.QtCore import Qt
from typing import List
from jackify.backend.models.modlist_metadata import ModlistMetadata
from ..shared_theme import JACKIFY_COLOR_BLUE


class ModlistGalleryFiltersMixin:
    """Mixin providing filter management for ModlistGalleryDialog."""

    def _create_filter_panel(self) -> QWidget:
        """Create filter sidebar"""
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        panel.setFixedWidth(280)  # Slightly wider for better readability

        layout = QVBoxLayout()
        layout.setSpacing(6)

        # Title
        title = QLabel("<b>Filters</b>")
        title.setStyleSheet(f"font-size: 14px; color: {JACKIFY_COLOR_BLUE};")
        layout.addWidget(title)

        # Search box (label removed - placeholder text is clear enough)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search modlists...")
        self.search_box.setStyleSheet("QLineEdit { background: #2a2a2a; color: #fff; border: 1px solid #555; padding: 4px; }")
        self.search_box.textChanged.connect(self._apply_filters)
        layout.addWidget(self.search_box)

        # Game filter (label removed - combo box is self-explanatory)
        self.game_combo = QComboBox()
        self.game_combo.addItem("All Games", None)
        self.game_combo.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.game_combo)

        # Status filters
        self.show_official_only = QCheckBox("Show Official Only")
        self.show_official_only.stateChanged.connect(self._apply_filters)
        layout.addWidget(self.show_official_only)

        self.show_nsfw = QCheckBox("Show NSFW")
        self.show_nsfw.stateChanged.connect(self._on_nsfw_toggled)
        layout.addWidget(self.show_nsfw)

        self.hide_unavailable = QCheckBox("Hide Unavailable")
        self.hide_unavailable.setChecked(True)
        self.hide_unavailable.stateChanged.connect(self._apply_filters)
        layout.addWidget(self.hide_unavailable)

        # Tag filter
        tags_label = QLabel("Tags:")
        layout.addWidget(tags_label)
        
        self.tags_list = QListWidget()
        self.tags_list.setSelectionMode(QListWidget.MultiSelection)
        self.tags_list.setMaximumHeight(150)
        self.tags_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Remove horizontal scrollbar
        self.tags_list.setStyleSheet("QListWidget { background: #2a2a2a; color: #fff; border: 1px solid #555; }")
        self.tags_list.itemSelectionChanged.connect(self._apply_filters)
        layout.addWidget(self.tags_list)

        layout.addStretch()

        # Cancel button (not default to prevent Enter from closing)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        panel.setLayout(layout)
        return panel


    def _populate_tag_filter(self):
        """Populate tag filter with normalized tags (like Wabbajack)"""
        normalized_tags = set()
        for modlist in self.all_modlists:
            display_tags = getattr(modlist, 'normalized_tags_display', None)
            if display_tags is None:
                display_tags = self.gallery_service.normalize_tags_for_display(getattr(modlist, 'tags', []))
                modlist.normalized_tags_display = display_tags
                modlist.normalized_tags_keys = [tag.lower() for tag in display_tags]
            normalized_tags.update(display_tags)
        
        # Add special tags (like Wabbajack)
        normalized_tags.add("NSFW")
        normalized_tags.add("Featured")  # Official
        normalized_tags.add("Unavailable")
        
        self.tags_list.clear()
        for tag in sorted(normalized_tags):
            self.tags_list.addItem(tag)


    def _get_normalized_tag_display(self, modlist: ModlistMetadata) -> List[str]:
        """Return (and cache) normalized tags for display for a modlist."""
        display_tags = getattr(modlist, 'normalized_tags_display', None)
        if display_tags is None:
            display_tags = self.gallery_service.normalize_tags_for_display(getattr(modlist, 'tags', []))
            modlist.normalized_tags_display = display_tags
            modlist.normalized_tags_keys = [tag.lower() for tag in display_tags]
        return display_tags


    def _get_normalized_tag_keys(self, modlist: ModlistMetadata) -> List[str]:
        """Return (and cache) lowercase normalized tags for filtering."""
        keys = getattr(modlist, 'normalized_tags_keys', None)
        if keys is None:
            display_tags = self._get_normalized_tag_display(modlist)
            keys = [tag.lower() for tag in display_tags]
            modlist.normalized_tags_keys = keys
        return keys


    def _tag_in_modlist(self, modlist: ModlistMetadata, normalized_tag_key: str) -> bool:
        """Check if a normalized (lowercase) tag is present on a modlist."""
        keys = self._get_normalized_tag_keys(modlist)
        return any(key == normalized_tag_key for key in keys)


    def _on_nsfw_toggled(self, checked: bool):
        """Handle NSFW checkbox toggle - apply filters"""
        self._apply_filters()


    def _set_filter_controls_enabled(self, enabled: bool):
        """Enable or disable all filter controls"""
        self.search_box.setEnabled(enabled)
        self.game_combo.setEnabled(enabled)
        self.show_official_only.setEnabled(enabled)
        self.show_nsfw.setEnabled(enabled)
        self.hide_unavailable.setEnabled(enabled)
        self.tags_list.setEnabled(enabled)


    def _apply_filters(self):
        """Apply current filters to modlist display"""
        # Guard against race condition - don't filter if modlists aren't loaded yet
        if not self.all_modlists:
            return
        
        filtered = self.all_modlists

        # Search filter
        search_text = self.search_box.text().strip()
        if search_text:
            filtered = [m for m in filtered if self._matches_search(m, search_text)]

        # Game filter
        game = self.game_combo.currentData()
        if game:
            filtered = [m for m in filtered if m.gameHumanFriendly == game]

        # Status filters
        if self.show_official_only.isChecked():
            filtered = [m for m in filtered if m.official]

        if not self.show_nsfw.isChecked():
            filtered = [m for m in filtered if not m.nsfw]

        if self.hide_unavailable.isChecked():
            filtered = [m for m in filtered if m.is_available()]

        # Tag filter - modlist must have ALL selected tags (normalized like Wabbajack)
        selected_tags = [item.text() for item in self.tags_list.selectedItems()]
        if selected_tags:
            special_selected = {tag for tag in selected_tags if tag in ("NSFW", "Featured", "Unavailable")}
            normalized_selected = [
                self.gallery_service.normalize_tag_value(tag).lower()
                for tag in selected_tags
                if tag not in special_selected
            ]

            if "NSFW" in special_selected:
                filtered = [m for m in filtered if m.nsfw]
            if "Featured" in special_selected:
                filtered = [m for m in filtered if m.official]
            if "Unavailable" in special_selected:
                filtered = [m for m in filtered if not m.is_available()]

            if normalized_selected:
                filtered = [
                    m for m in filtered
                    if all(
                        self._tag_in_modlist(m, normalized_tag)
                        for normalized_tag in normalized_selected
                    )
                ]

        self.filtered_modlists = filtered
        self._update_grid()


    def _matches_search(self, modlist: ModlistMetadata, query: str) -> bool:
        """Check if modlist matches search query"""
        query_lower = query.lower()
        return (
            query_lower in modlist.title.lower() or
            query_lower in modlist.description.lower() or
            query_lower in modlist.author.lower()
        )


