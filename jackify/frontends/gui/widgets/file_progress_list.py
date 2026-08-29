"""
File Progress List Widget

Displays a list of files currently being processed (downloaded, extracted, etc.)
with individual progress indicators.
R&D NOTE: This is experimental code for investigation purposes.
"""

from typing import Optional
import logging
import shiboken6
import time

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QHBoxLayout, QSizePolicy
)
from PySide6.QtCore import Qt, QSize, QTimer, QThread, Signal

from jackify.shared.progress_models import FileProgress, OperationType

from .summary_progress_widget import SummaryProgressWidget
from .file_progress_item import FileProgressItem

__all__ = ['SummaryProgressWidget', 'FileProgressItem', 'FileProgressList']


class _CpuWorker(QThread):
    """Background worker for CPU usage sampling - keeps psutil off the main thread."""
    result = Signal(str)
    caches_updated = Signal(object, object, float)  # process_cache, child_cache, smoothed_pct

    def __init__(self, last_pct, process_cache, child_cache):
        super().__init__()
        self._last_pct = last_pct
        self._process_cache = process_cache
        self._child_cache = dict(child_cache) if child_cache else {}

    def run(self):
        try:
            import psutil, os

            if self._process_cache is None:
                self._process_cache = psutil.Process(os.getpid())
                # Establish baseline (blocking, but only once and in background)
                self._process_cache.cpu_percent(interval=0.1)

            num_cpus = psutil.cpu_count() or 1
            total_cpu = self._process_cache.cpu_percent(interval=None) / num_cpus

            current_child_pids = set()
            try:
                for child in self._process_cache.children(recursive=True):
                    try:
                        current_child_pids.add(child.pid)
                        if child.pid not in self._child_cache:
                            # Baseline in background - no longer blocks main thread
                            child.cpu_percent(interval=0.1)
                            self._child_cache[child.pid] = child
                            continue
                        total_cpu += self._child_cache[child.pid].cpu_percent(interval=None) / num_cpus
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                for pid in set(self._child_cache.keys()) - current_child_pids:
                    del self._child_cache[pid]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            jackify_names = [
                'jackify-engine', 'texconv', 'texdiag', 'directxtex',
                'texconv_jackify', 'texdiag_jackify', 'directxtex_jackify',
                '7z', '7zz', 'bsarch', 'wine', 'wine64', 'wine64-preloader',
                'steam-run', 'proton',
            ]
            tracked_pids = {self._process_cache.pid} | current_child_pids
            try:
                for proc in psutil.process_iter(['name', 'pid', 'cmdline']):
                    try:
                        if proc.pid in tracked_pids:
                            continue
                        proc_name = proc.info.get('name', '').lower()
                        cmdline_str = ' '.join(proc.info.get('cmdline', []) or []).lower()
                        is_jackify = any(n in proc_name for n in jackify_names)
                        if not is_jackify and cmdline_str:
                            is_jackify = any(n in cmdline_str for n in jackify_names)
                            if not is_jackify:
                                is_jackify = any(f'{n}.exe' in cmdline_str for n in jackify_names)
                            if not is_jackify:
                                is_jackify = 'jackify' in cmdline_str and any(
                                    t in cmdline_str for t in ['engine', 'tools', 'binaries']
                                )
                        if is_jackify:
                            if proc.pid not in self._child_cache:
                                proc.cpu_percent(interval=0.1)
                                self._child_cache[proc.pid] = proc
                                continue
                            total_cpu += self._child_cache[proc.pid].cpu_percent(interval=None) / num_cpus
                            tracked_pids.add(proc.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, TypeError):
                        pass
            except Exception:
                pass

            if self._last_pct > 0:
                total_cpu = self._last_pct * 0.3 + total_cpu * 0.7
            display = min(100.0, total_cpu)
            self.result.emit(f"CPU: {display:.0f}%")
            self.caches_updated.emit(self._process_cache, self._child_cache, total_cpu)

        except Exception:
            self.result.emit("")


def _debug_log(message):
    from jackify.backend.handlers.config_handler import ConfigHandler
    if ConfigHandler().get('debug_mode', False):
        logger.debug(message)


class FileProgressList(QWidget):
    """
    Widget displaying a list of files currently being processed.
    Shows individual progress for each file.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_items: dict[str, FileProgressItem] = {}
        self._summary_widget: Optional[SummaryProgressWidget] = None
        self._last_phase: Optional[str] = None
        self._transition_label: Optional[QLabel] = None
        self._last_summary_time: float = 0.0
        self._summary_hold_duration: float = 0.5
        self._last_summary_update: float = 0.0
        self._summary_update_interval: float = 0.1

        self._setup_ui()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        self.cpu_label = QLabel("")
        self.cpu_label.setStyleSheet("color: #888; font-size: 11px; margin-bottom: 2px;")
        self.cpu_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addStretch()
        header_layout.addWidget(self.cpu_label, 0)
        layout.addLayout(header_layout)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #222;
                border: 1px solid #444;
                border-radius: 4px;
            }
            QListWidget::item {
                border-bottom: 1px solid #2a2a2a;
                padding: 2px;
            }
            QListWidget::item:selected {
                background-color: #2a2a2a;
            }
        """)
        self.list_widget.setMinimumSize(QSize(300, 20))
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.list_widget, stretch=1)

        self._last_update_time = 0.0

        # CPU usage tracking - worker thread to avoid blocking the main thread
        self._cpu_timer = QTimer(self)
        self._cpu_timer.timeout.connect(self._start_cpu_worker)
        self._cpu_timer.setInterval(2000)
        self._last_cpu_percent = 0.0
        self._cpu_process_cache = None
        self._child_process_cache = {}
        self._cpu_worker = None

    def update_files(self, file_progresses: list[FileProgress], current_phase: str = None, summary_info: dict = None):
        current_time = time.time()

        # Throttle for large file lists
        if len(file_progresses) > 50:
            if current_time - self._last_update_time < 0.1:
                return
            self._last_update_time = current_time

        # Summary widget path (Installing phase etc.)
        if summary_info and not file_progresses:
            current_step = summary_info.get('current_step', 0)
            max_steps    = summary_info.get('max_steps', 0)
            phase_name   = current_phase or "Installing files"

            summary_widget_valid = self._summary_widget and shiboken6.isValid(self._summary_widget)
            if not summary_widget_valid:
                self._summary_widget = None

            if self._summary_widget:
                if current_time - self._last_summary_update < self._summary_update_interval:
                    return
                self._summary_widget.update_progress(current_step, max_steps)
                if self._summary_widget.phase_name != phase_name:
                    self._summary_widget.phase_name = phase_name
                    self._summary_widget._update_display()
                self._last_summary_update = current_time
                return

            self._clear_item_widgets()
            self.list_widget.clear()
            self._file_items.clear()

            self._summary_widget = SummaryProgressWidget(phase_name, current_step, max_steps)
            summary_item = QListWidgetItem()
            summary_item.setSizeHint(self._summary_widget.sizeHint())
            summary_item.setData(Qt.UserRole, "__summary__")
            self.list_widget.addItem(summary_item)
            self.list_widget.setItemWidget(summary_item, self._summary_widget)
            self._last_summary_time = current_time
            self._last_summary_update = current_time
            return

        # Remove stale summary widget
        if self._summary_widget:
            if current_time - self._last_summary_time >= self._summary_hold_duration:
                self._remove_keyed_item("__summary__")
                self._summary_widget = None
            else:
                return

        # Remove transition label
        if self._transition_label:
            self._remove_keyed_item("__transition__")
            self._transition_label = None

        if not file_progresses:
            if current_phase and self._last_phase and current_phase != self._last_phase:
                self._show_transition_message(current_phase)
            else:
                self._clear_item_widgets()
                self.list_widget.clear()
                self._file_items.clear()
            if current_phase:
                self._last_phase = current_phase
            return

        # Resolve phase label from operations if not provided
        if not current_phase and file_progresses:
            operations = [fp.operation for fp in file_progresses if fp.operation != OperationType.UNKNOWN]
            if operations:
                counts = {}
                for op in operations:
                    counts[op] = counts.get(op, 0) + 1
                phase_map = {
                    OperationType.DOWNLOAD: "Downloading",
                    OperationType.EXTRACT:  "Extracting",
                    OperationType.VALIDATE: "Validating",
                    OperationType.INSTALL:  "Installing",
                }
                current_phase = phase_map.get(max(counts, key=counts.get), "")

        # Build stable key set from incoming data
        current_keys = set()
        for fp in file_progresses:
            current_keys.add(self._stable_key(fp))

        # Remove items no longer active
        for item_key in list(self._file_items.keys()):
            if item_key not in current_keys:
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item and item.data(Qt.UserRole) == item_key:
                        widget = self.list_widget.itemWidget(item)
                        if widget:
                            self.list_widget.removeItemWidget(item)
                        self.list_widget.takeItem(i)
                        break
                del self._file_items[item_key]

        # Update existing or add new items
        for file_progress in file_progresses:
            item_key = self._stable_key(file_progress)

            if item_key in self._file_items:
                item_widget = self._file_items[item_key]
                if shiboken6.isValid(item_widget):
                    try:
                        item_widget.update_progress(file_progress)
                        continue
                    except RuntimeError:
                        del self._file_items[item_key]
                else:
                    del self._file_items[item_key]

            item_widget = FileProgressItem(file_progress)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, item_key)
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)
            self._file_items[item_key] = item_widget

        if current_phase:
            self._last_phase = current_phase

    def update_or_add_item(self, item_id: str, label: str, progress: float = 0.0):
        file_progress = FileProgress(
            filename=label,
            operation=OperationType.DOWNLOAD if progress > 0 else OperationType.UNKNOWN,
            percent=progress,
            current_size=0,
            total_size=0,
            stable_key=item_id,
        )
        self.update_files([file_progress], current_phase=None)

    def clear_summary(self):
        if self._summary_widget:
            self._remove_keyed_item("__summary__")
            self._summary_widget = None

    def clear(self):
        self._clear_item_widgets()
        self.list_widget.clear()
        self._file_items.clear()
        self._summary_widget = None
        self._transition_label = None
        self._last_phase = None
        self.stop_cpu_tracking()
        self.cpu_label.setText("")

    def start_cpu_tracking(self):
        if not self._cpu_timer.isActive():
            self._cpu_timer.start()
            self._start_cpu_worker()

    def stop_cpu_tracking(self):
        self._cpu_timer.stop()
        worker = self._cpu_worker
        if worker is None:
            return
        self._cpu_worker = None
        if not worker.isRunning():
            return
        worker.wait(2000)
        if worker.isRunning():
            # psutil scan (baselining new child processes) didn't finish in time.
            # Dropping the last Python reference to a still-running QThread makes
            # Qt abort ("QThread: Destroyed while thread is still running") - let
            # it finish naturally and clean itself up instead.
            worker.finished.connect(worker.deleteLater)

    def _start_cpu_worker(self):
        # Skip if a worker is already running to avoid pileup
        if self._cpu_worker and self._cpu_worker.isRunning():
            return
        self._cpu_worker = _CpuWorker(self._last_cpu_percent, self._cpu_process_cache, self._child_process_cache)
        self._cpu_worker.result.connect(self._on_cpu_result)
        self._cpu_worker.caches_updated.connect(self._on_cpu_caches)
        self._cpu_worker.start()

    def _on_cpu_result(self, text: str):
        self.cpu_label.setText(text)

    def _on_cpu_caches(self, process_cache, child_cache, smoothed_pct):
        self._cpu_process_cache = process_cache
        self._child_process_cache = child_cache
        self._last_cpu_percent = smoothed_pct

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _stable_key(fp: FileProgress) -> str:
        if fp.stable_key:
            return fp.stable_key
        if 'Installing Files:' in fp.filename:
            return "__installing_files__"
        if 'Converting Texture:' in fp.filename:
            return f"__texture_{fp.filename.split('(')[0].strip()}__"
        if fp.filename.startswith('BSA:'):
            return f"__bsa_{fp.filename.split('(')[0].strip()}__"
        if fp.filename.startswith('Wine component:'):
            rest = fp.filename.split(':', 1)[1].strip()
            comp_id = rest.split('|')[0].strip() if '|' in rest else rest
            return f"__wine_comp_{comp_id}__"
        return fp.filename

    def _clear_item_widgets(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                widget = self.list_widget.itemWidget(item)
                if widget:
                    self.list_widget.removeItemWidget(item)

    def _remove_keyed_item(self, key: str):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.UserRole) == key:
                widget = self.list_widget.itemWidget(item)
                if widget:
                    self.list_widget.removeItemWidget(item)
                self.list_widget.takeItem(i)
                break

    def _show_transition_message(self, new_phase: str):
        self._clear_item_widgets()
        self.list_widget.clear()
        self._file_items.clear()

        if self._transition_label is None or not shiboken6.isValid(self._transition_label):
            self._transition_label = QLabel()
            self._transition_label.setAlignment(Qt.AlignCenter)
            self._transition_label.setStyleSheet("color: #888; font-style: italic; padding: 20px;")
        self._transition_label.setText(f"Preparing {new_phase.lower()}...")

        transition_item = QListWidgetItem()
        transition_item.setSizeHint(self._transition_label.sizeHint())
        transition_item.setData(Qt.UserRole, "__transition__")
        self.list_widget.addItem(transition_item)
        self.list_widget.setItemWidget(transition_item, self._transition_label)

