"""
Manual Download Dialog

Shown when the engine requires manual downloads (non-premium or forced-manual
archives). Displays all pending items in a scrollable table, manages browser
tab concurrency, and coordinates with ManualDownloadManager.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QFileDialog, QSizePolicy,
)
from PySide6.QtGui import QFont

from jackify.backend.services.manual_download_manager import ManualDownloadManager, DownloadItem
from jackify.backend.handlers.config_handler import ConfigHandler
from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    'pending':       'Pending',
    'browser_opened': 'Browser Opened',
    'validating':    'Validating...',
    'complete':      'Complete',
    'deferred':      'Deferred',
    'skipped':       'Skipped',
    'error':         'Error',
}

_STATUS_COLOURS = {
    'pending':       '#808080',
    'browser_opened': '#3fd0ea',
    'validating':    '#f0c040',
    'complete':      '#3fd0ea',
    'deferred':      '#f0c040',
    'skipped':       '#888',
    'error':         '#e05050',
}

# Column indices
_COL_MOD   = 0
_COL_NAME  = 1
_COL_SIZE  = 2
_COL_STATUS = 3


def _fmt_size(n: int) -> str:
    if n <= 0:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class _SizeTableItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by raw byte count stored in UserRole."""
    def __lt__(self, other: 'QTableWidgetItem') -> bool:
        try:
            return int(self.data(Qt.UserRole) or 0) < int(other.data(Qt.UserRole) or 0)
        except (TypeError, ValueError):
            return super().__lt__(other)


class _Bridge(QObject):
    """Tiny bridge so worker-thread callbacks can update the Qt table safely."""
    item_updated = Signal(object)  # DownloadItem
    all_done = Signal(int, int)    # completed, skipped


class ManualDownloadDialog(QDialog):
    """
    Displays all pending manual downloads and coordinates the download workflow.
    Non-modal so the install log remains visible.
    """

    def __init__(
        self,
        manager: ManualDownloadManager,
        modlist_name: str = '',
        watch_directory: Optional[Path] = None,
        concurrent_limit: int = 2,
        parent=None,
    ):
        super().__init__(parent)
        self._manager = manager
        self._modlist_name = modlist_name
        self._watch_dir = watch_directory or (Path.home() / 'Downloads')
        self._paused = False
        self._started = False
        self._initial_concurrent_limit = max(1, min(5, int(concurrent_limit)))

        # Row index by file_name for fast updates
        self._row_map: dict[str, int] = {}

        # Bridge for thread-safe table updates
        self._bridge = _Bridge()
        self._bridge.item_updated.connect(self._on_item_updated_slot)
        self._bridge.all_done.connect(self._on_all_done_slot)

        # Preserve any existing manager callbacks so workflow controllers still
        # receive completion events after the dialog updates its own UI.
        prev_item_updated = self._manager._on_item_updated
        prev_all_done = self._manager._on_all_done

        def _emit_item_updated(item):
            self._bridge.item_updated.emit(item)
            if prev_item_updated:
                prev_item_updated(item)

        def _emit_all_done(completed: int, skipped: int):
            self._bridge.all_done.emit(completed, skipped)
            if prev_all_done:
                prev_all_done(completed, skipped)

        self._manager._on_item_updated = _emit_item_updated
        self._manager._on_all_done = _emit_all_done

        self.setWindowTitle("Manual Downloads Required")
        self.setMinimumSize(760, 500)
        self.setModal(False)
        self._build_ui()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._started:
            # Keep the workflow idle until the user explicitly clicks Start.
            # Start backend services in paused mode so watcher/precheck are ready
            # without opening browser tabs yet.
            self._paused = False
            self._manager.pause()
            self._manager.start()
            self._start_pause_btn.setText("Start")
            self._progress_label.setText("Ready - click Start to begin opening download tabs")

    def load_items(self, items: list[DownloadItem]) -> None:
        """
        Populate or refresh the table from a list of DownloadItems.
        On subsequent loop iterations the manager passes its full item list
        (including previously-completed rows), so we update existing rows and
        append only genuinely new ones rather than rebuilding the table.
        """
        new_items = [i for i in items if i.file_name not in self._row_map]
        existing_items = [i for i in items if i.file_name in self._row_map]

        # Update existing rows without disabling updates (usually few on repeat iterations)
        for item in existing_items:
            self._update_row(self._row_map[item.file_name], item)

        # Batch-insert new rows with viewport updates suspended to avoid O(n²) repaints
        if new_items:
            self._table.setSortingEnabled(False)
            self._table.setUpdatesEnabled(False)
            try:
                start_row = self._table.rowCount()
                self._table.setRowCount(start_row + len(new_items))
                for i, item in enumerate(new_items):
                    self._fill_row(start_row + i, item)
            finally:
                self._table.setUpdatesEnabled(True)
                self._table.setSortingEnabled(True)
                self._rebuild_row_map()
                self._table.viewport().update()

        self._refresh_header()
        # If user already started the workflow and engine enters another manual loop,
        # continue opening tabs for newly-pending items automatically.
        if self._started and not self._paused:
            self._manager.resume()

    def update_item(self, item: DownloadItem) -> None:
        """Called from any thread - bridges to Qt slot."""
        self._bridge.item_updated.emit(item)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Header
        hdr = QFrame()
        hdr.setFrameShape(QFrame.StyledPanel)
        hdr.setStyleSheet("QFrame { background: #1e2228; border-radius: 8px; border: 1px solid #333; }")
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(12, 10, 12, 10)
        hdr_layout.setSpacing(6)

        self._title_label = QLabel(f"Modlist: {self._modlist_name or 'Unknown'}")
        self._title_label.setStyleSheet("color: #e0e0e0; font-size: 14px; font-weight: 600;")
        hdr_layout.addWidget(self._title_label)

        self._progress_label = QLabel("Preparing...")
        self._progress_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        hdr_layout.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid #444; border-radius: 4px; background: #2c2c2c; "
            f"height: 12px; color: #d7e3f4; font-weight: 600; }}"
            f"QProgressBar::chunk {{ background: {JACKIFY_COLOR_BLUE}; border-radius: 3px; }}"
        )
        hdr_layout.addWidget(self._progress_bar)
        root.addWidget(hdr)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(['Mod', 'File', 'Size', 'Status'])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 130)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self._table.setStyleSheet(
            "QTableWidget { background: #1a1d23; alternate-background-color: #1e2228; "
            "color: #d0d0d0; gridline-color: #333; border: 1px solid #333; border-radius: 4px; }"
            "QHeaderView::section { background: #252830; color: #aaa; border: none; "
            "padding: 4px; font-size: 11px; }"
        )
        root.addWidget(self._table)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.setSpacing(12)

        ctrl.addWidget(QLabel("Concurrent tabs:"))
        self._concurrent_spin = QSpinBox()
        self._concurrent_spin.setRange(1, 5)
        self._concurrent_spin.setValue(self._initial_concurrent_limit)
        self._concurrent_spin.setFixedWidth(60)
        self._concurrent_spin.valueChanged.connect(self._on_concurrent_changed)
        ctrl.addWidget(self._concurrent_spin)

        ctrl.addSpacing(16)
        ctrl.addWidget(QLabel("Watch folder:"))
        self._folder_label = QLabel(str(self._watch_dir))
        self._folder_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._folder_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        ctrl.addWidget(self._folder_label)

        folder_btn = QPushButton("...")
        folder_btn.setFixedSize(32, 28)
        folder_btn.clicked.connect(self._on_pick_folder)
        ctrl.addWidget(folder_btn)

        root.addLayout(ctrl)

        watch_hint = QLabel(
            "Jackify watches this folder for newly downloaded archives, validates them, "
            "then moves valid files into your modlist downloads folder automatically. "
            "Double-click a row (or use Open Selected) to reopen a URL if you closed a tab."
        )
        watch_hint.setWordWrap(True)
        watch_hint.setStyleSheet("color: #8f98a3; font-size: 11px;")
        root.addWidget(watch_hint)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._retry_btn = QPushButton("Retry Deferred (0)")
        self._retry_btn.setEnabled(False)
        self._retry_btn.clicked.connect(self._on_retry_skipped)
        btn_row.addWidget(self._retry_btn)

        self._defer_btn = QPushButton("Defer Selected")
        self._defer_btn.clicked.connect(self._on_defer_selected)
        btn_row.addWidget(self._defer_btn)

        self._open_selected_btn = QPushButton("Open Selected")
        self._open_selected_btn.clicked.connect(self._on_open_selected)
        btn_row.addWidget(self._open_selected_btn)

        self._scan_now_btn = QPushButton("Scan Now")
        self._scan_now_btn.setToolTip(
            "Re-scan the watch directory for already-downloaded files.\n"
            "Use this if a file downloaded successfully but was not detected automatically."
        )
        self._scan_now_btn.clicked.connect(self._on_scan_now)
        btn_row.addWidget(self._scan_now_btn)

        btn_row.addStretch()

        self._start_pause_btn = QPushButton("Start")
        self._start_pause_btn.clicked.connect(self._on_start_pause_clicked)
        btn_row.addWidget(self._start_pause_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background: #7f2020; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #9b2828; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _fill_row(self, row: int, item: DownloadItem) -> None:
        """Populate cells for a pre-allocated row (row must already exist in the table)."""
        from PySide6.QtGui import QColor
        mod_cell = QTableWidgetItem(item.mod_name)
        mod_cell.setData(Qt.UserRole, item.file_name)  # stable ID for row lookups after sort
        self._table.setItem(row, _COL_MOD, mod_cell)
        self._table.setItem(row, _COL_NAME, QTableWidgetItem(item.file_name))
        size_cell = _SizeTableItem(_fmt_size(item.expected_size))
        size_cell.setData(Qt.UserRole, item.expected_size)
        self._table.setItem(row, _COL_SIZE, size_cell)
        colour = _STATUS_COLOURS.get(item.status, '#808080')
        status_cell = QTableWidgetItem(_STATUS_LABELS.get(item.status, item.status))
        status_cell.setForeground(QColor(colour))
        tooltip_parts = [p for p in (item.download_reason, item.error_message) if p]
        if tooltip_parts:
            status_cell.setToolTip("\n".join(tooltip_parts))
        self._table.setItem(row, _COL_STATUS, status_cell)

    def _update_row(self, row: int, item: DownloadItem) -> None:
        from PySide6.QtGui import QColor
        status_cell = self._table.item(row, _COL_STATUS)
        if status_cell:
            status_cell.setText(_STATUS_LABELS.get(item.status, item.status))
            status_cell.setForeground(QColor(_STATUS_COLOURS.get(item.status, '#808080')))
            tooltip_parts = [p for p in (item.download_reason, item.error_message) if p]
            status_cell.setToolTip("\n".join(tooltip_parts))

    def _rebuild_row_map(self) -> None:
        self._row_map.clear()
        for row in range(self._table.rowCount()):
            cell = self._table.item(row, _COL_MOD)
            if cell:
                file_name = cell.data(Qt.UserRole)
                if file_name:
                    self._row_map[file_name] = row

    def _sync_pending_order_to_visual(self) -> None:
        visual_order: dict[str, int] = {}
        for row in range(self._table.rowCount()):
            cell = self._table.item(row, _COL_MOD)
            if cell:
                file_name = cell.data(Qt.UserRole)
                if file_name:
                    visual_order[file_name] = row
        with self._manager._lock:
            self._manager._items.sort(key=lambda i: visual_order.get(i.file_name, 999999))

    def _refresh_header(self) -> None:
        items = self._manager.items
        total = len(items)
        complete = sum(1 for i in items if i.status == 'complete')
        skipped = sum(1 for i in items if i.status == 'skipped')
        remaining = total - complete - skipped

        pct = int(complete / total * 100) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._progress_label.setText(
            f"{complete} of {total} complete  |  {skipped} deferred  |  {remaining} remaining"
        )
        self._retry_btn.setText(f"Retry Deferred ({skipped})")
        self._retry_btn.setEnabled(skipped > 0)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_header_clicked(self, logical_index: int) -> None:
        self._rebuild_row_map()
        self._sync_pending_order_to_visual()

    def _on_item_updated_slot(self, item: DownloadItem) -> None:
        row = self._row_map.get(item.file_name)
        if row is not None:
            self._update_row(row, item)
        self._refresh_header()

    def _on_concurrent_changed(self, value: int) -> None:
        self._manager.set_concurrent_limit(value)
        try:
            cfg = ConfigHandler()
            cfg.set("manual_download_concurrent_limit", int(value))
            cfg.save_config()
        except Exception:
            logger.debug("Could not persist manual_download_concurrent_limit", exc_info=True)

    def _on_pick_folder(self) -> None:
        from jackify.frontends.gui.utils import browse_directory
        chosen = browse_directory(self, "Select watch folder", str(self._watch_dir))
        if chosen:
            from jackify.backend.services.download_watcher_service import WatcherConfig
            self._watch_dir = Path(chosen)
            self._folder_label.setText(chosen)
            self._manager._watch_dir = self._watch_dir
            self._manager._watcher._config.watch_directory = self._watch_dir
            try:
                cfg = ConfigHandler()
                cfg.set("manual_download_watch_directory", str(self._watch_dir))
                cfg.save_config()
            except Exception:
                logger.debug("Could not persist manual_download_watch_directory", exc_info=True)

    def _on_start_pause_clicked(self) -> None:
        if not self._started:
            self._started = True
            self._paused = False
            self._start_pause_btn.setText("Pause")
            self._manager.resume()
            return

        if not self._paused:
            self._paused = True
            self._start_pause_btn.setText("Resume")
            self._manager.pause()
        else:
            self._paused = False
            self._start_pause_btn.setText("Pause")
            self._manager.resume()

    def _on_retry_skipped(self) -> None:
        with self._manager._lock:
            for item in self._manager._items:
                if item.status in ('deferred', 'skipped'):
                    item.status = 'pending'
                    item.needs_user_retry = False
                    row = self._row_map.get(item.file_name)
                    if row is not None:
                        self._update_row(row, item)
        self._manager._open_next_tabs()
        self._refresh_header()

    def _on_defer_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        file_item = self._table.item(row, _COL_NAME)
        if file_item is None:
            return
        file_name = file_item.text().strip()
        if not file_name:
            return
        self._manager.skip_item(file_name)

    def _on_open_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        file_item = self._table.item(row, _COL_NAME)
        if file_item is None:
            return
        file_name = file_item.text().strip()
        if not file_name:
            return
        self._manager.reopen_item(file_name)

    def _on_scan_now(self) -> None:
        self._scan_now_btn.setEnabled(False)
        self._scan_now_btn.setText("Scanning...")
        self._manager.force_rescan()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: (
            self._scan_now_btn.setEnabled(True),
            self._scan_now_btn.setText("Scan Now"),
        ))

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        file_item = self._table.item(row, _COL_NAME)
        if file_item is None:
            return
        file_name = file_item.text()
        if not file_name:
            return
        self._manager.reopen_item(file_name)

    def _on_all_done_slot(self, completed: int, skipped: int) -> None:
        from PySide6.QtCore import QTimer
        self._progress_label.setText(
            f"All downloads complete ({completed} accepted, {skipped} deferred) - closing..."
        )
        # Raise now while the dialog is still visible so the user sees the completion state
        self._raise_main_window()
        QTimer.singleShot(2000, self._close_and_refocus)

    def _close_and_refocus(self) -> None:
        self.close()
        # Closing a non-modal dialog can hand focus back to whatever was behind it
        self._raise_main_window()

    def _raise_main_window(self) -> None:
        try:
            win = self.window()
            if win:
                win.raise_()
                win.activateWindow()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        # Don't stop the manager on close - install continues
        event.accept()
