"""
Summary progress widget for phase display (e.g. Queuing Archives 123/456).
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QSizePolicy
from PySide6.QtCore import Qt, QTimer

from jackify.frontends.gui.shared_theme import JACKIFY_COLOR_BLUE


class SummaryProgressWidget(QWidget):
    """Single-row summary widget matching FileProgressItem layout."""

    def __init__(self, phase_name: str, current_step: int, max_steps: int, parent=None):
        super().__init__(parent)
        self.phase_name = phase_name
        self.current_step = current_step
        self.max_steps = max_steps
        self._target_step = current_step
        self._target_max = max_steps
        self._display_step = float(current_step)
        self._display_max = float(max_steps)
        self._interpolation_timer = QTimer(self)
        self._interpolation_timer.timeout.connect(self._interpolate_counter)
        self._interpolation_timer.setInterval(16)
        self._interpolation_timer.start()
        self._setup_ui()
        self._update_display()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        op_label = QLabel("»")
        op_label.setFixedWidth(20)
        op_label.setAlignment(Qt.AlignCenter)
        op_label.setStyleSheet(f"color: {JACKIFY_COLOR_BLUE}; font-weight: bold;")
        layout.addWidget(op_label)

        self.text_label = QLabel()
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.text_label.setStyleSheet("color: #ccc; font-size: 11px;")
        layout.addWidget(self.text_label, 1)

        self.percent_label = QLabel()
        self.percent_label.setFixedWidth(40)
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent_label.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(self.percent_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setFixedWidth(80)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #444;
                border-radius: 2px;
                background-color: #1a1a1a;
            }}
            QProgressBar::chunk {{
                background-color: {JACKIFY_COLOR_BLUE};
                border-radius: 1px;
            }}
        """)
        layout.addWidget(self.progress_bar)

    def _interpolate_counter(self):
        step_diff = self._target_step - self._display_step
        if abs(step_diff) < 0.5:
            self._display_step = self._target_step
        else:
            self._display_step += step_diff * 0.2

        max_diff = self._target_max - self._display_max
        if abs(max_diff) < 0.5:
            self._display_max = self._target_max
        else:
            self._display_max += max_diff * 0.2

        self._update_display()

    def _update_display(self):
        display_step = int(round(self._display_step))
        display_max = int(round(self._display_max))

        if display_max > 0:
            self.text_label.setText(f"{self.phase_name} ({display_step}/{display_max})")
            pct = int(display_step / display_max * 100)
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.percent_label.setText(f"{pct}%")
        else:
            self.text_label.setText(self.phase_name)
            self.progress_bar.setValue(0)
            self.percent_label.setText("")

    def update_progress(self, current_step: int, max_steps: int):
        self._target_step = current_step
        self._target_max = max_steps
        self.current_step = current_step
        self.max_steps = max_steps
