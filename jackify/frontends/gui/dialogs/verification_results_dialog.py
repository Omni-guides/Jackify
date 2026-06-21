"""Verification results dialog shown after install/configure workflows."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QClipboard, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QVBoxLayout,
)

logger = logging.getLogger(__name__)

_COLOR_FAIL = "#e05050"
_COLOR_WARN = "#f0c040"
_COLOR_OK   = "#3fd0ea"
_COLOR_DIM  = "#888888"


def _html_row(prefix: str, color: str, msg: str) -> str:
    safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<span style="color:{color}; font-family:monospace;">'
        f'<b>{prefix}</b>&nbsp;{safe}'
        f'</span><br>'
    )


class VerificationResultsDialog(QDialog):
    """Shows the output of verify_install.py after a workflow completes."""

    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installation Verification")
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(600)

        self._results = results
        n_pass = len(results.passes)
        n_warn = len(results.warnings)
        n_fail = len(results.failures)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # --- Headline ---
        if n_fail:
            headline = f"[FAIL]  {n_fail} failure{'s' if n_fail != 1 else ''}, {n_warn} warning{'s' if n_warn != 1 else ''}, {n_pass} passed"
            h_color = _COLOR_FAIL
        elif n_warn:
            headline = f"[WARN]  {n_warn} warning{'s' if n_warn != 1 else ''}, {n_pass} passed"
            h_color = _COLOR_WARN
        else:
            headline = f"[OK]  All {n_pass} checks passed"
            h_color = _COLOR_OK

        headline_label = QLabel(headline)
        headline_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {h_color};"
        )
        layout.addWidget(headline_label)

        # --- Issues view (always visible) ---
        self._issues_view = QTextEdit()
        self._issues_view.setReadOnly(True)
        self._issues_view.setStyleSheet(
            "QTextEdit { background: #1e1e1e; border: 1px solid #444; "
            "border-radius: 4px; font-size: 12px; padding: 6px; }"
        )
        self._issues_view.setHtml(self._build_issues_html(results))
        self._issues_view.setMinimumHeight(80)
        self._issues_view.setMaximumHeight(220)
        layout.addWidget(self._issues_view)

        # --- Full report view (hidden by default) ---
        self._full_view = QTextEdit()
        self._full_view.setReadOnly(True)
        self._full_view.setStyleSheet(
            "QTextEdit { background: #1a1a1a; border: 1px solid #333; "
            "border-radius: 4px; font-size: 11px; padding: 6px; }"
        )
        self._full_view.setHtml(self._build_full_html(results))
        self._full_view.setMinimumHeight(160)
        self._full_view.setMaximumHeight(300)
        self._full_view.setVisible(False)
        layout.addWidget(self._full_view)

        # --- Button row ---
        btn_row = QHBoxLayout()

        self._toggle_btn = QPushButton("Show all checks")
        self._toggle_btn.setFixedWidth(130)
        self._toggle_btn.setStyleSheet(
            "QPushButton { font-size: 11px; color: #ccc; background: #3a3a3a; "
            "border: 1px solid #555; border-radius: 4px; padding: 4px 8px; }"
            "QPushButton:hover { background: #4a4a4a; color: #fff; }"
        )
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_full_report)
        btn_row.addWidget(self._toggle_btn)

        btn_row.addStretch()

        copy_btn = QPushButton("Copy Report")
        copy_btn.setFixedWidth(110)
        copy_btn.setToolTip("Copy plain-text report to clipboard")
        copy_btn.clicked.connect(self._copy_report)
        btn_row.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        self.adjustSize()

    # ------------------------------------------------------------------

    def _build_issues_html(self, results) -> str:
        lines = []
        for msg in results.failures:
            lines.append(_html_row("[FAIL]", _COLOR_FAIL, msg))
        for msg in results.warnings:
            lines.append(_html_row("[WARN]", _COLOR_WARN, msg))
        if not results.failures and not results.warnings:
            lines.append(_html_row("[OK]", _COLOR_OK, "No issues found. Your modlist is correctly configured."))
        return "".join(lines)

    def _build_full_html(self, results) -> str:
        lines = []
        if results.failures:
            lines.append(f'<span style="color:{_COLOR_DIM}; font-size:10px;">FAILURES</span><br>')
            for msg in results.failures:
                lines.append(_html_row("[FAIL]", _COLOR_FAIL, msg))
            lines.append("<br>")
        if results.warnings:
            lines.append(f'<span style="color:{_COLOR_DIM}; font-size:10px;">WARNINGS</span><br>')
            for msg in results.warnings:
                lines.append(_html_row("[WARN]", _COLOR_WARN, msg))
            lines.append("<br>")
        if results.passes:
            lines.append(f'<span style="color:{_COLOR_DIM}; font-size:10px;">PASSED</span><br>')
            for msg in results.passes:
                lines.append(_html_row("[OK]  ", _COLOR_OK, msg))
        components = getattr(results, "installed_components", [])
        if components:
            lines.append("<br>")
            lines.append(f'<span style="color:{_COLOR_DIM}; font-size:10px;">INSTALLED COMPONENTS ({len(components)})</span><br>')
            for c in components:
                method = c.get("method", "unknown")
                method_color = _COLOR_OK if method == "native" else _COLOR_DIM
                safe_name = c["name"].replace("&", "&amp;").replace("<", "&lt;")
                lines.append(
                    f'<span style="font-family:monospace; font-size:11px;">'
                    f'{safe_name}'
                    f'&nbsp;<span style="color:{method_color}; font-size:10px;">({method})</span>'
                    f'</span><br>'
                )
        return "".join(lines)

    def _build_plain_text(self) -> str:
        r = self._results
        n_pass = len(r.passes)
        n_warn = len(r.warnings)
        n_fail = len(r.failures)

        lines = ["Jackify - Installation Verification", "=" * 40]
        if n_fail:
            lines.append(f"RESULT: FAILED  ({n_fail} failures, {n_warn} warnings, {n_pass} passed)")
        elif n_warn:
            lines.append(f"RESULT: WARNING  ({n_warn} warnings, {n_pass} passed)")
        else:
            lines.append(f"RESULT: OK  (all {n_pass} checks passed)")
        lines.append("")

        if r.failures:
            lines.append("FAILURES:")
            for msg in r.failures:
                lines.append(f"  [FAIL] {msg}")
            lines.append("")
        if r.warnings:
            lines.append("WARNINGS:")
            for msg in r.warnings:
                lines.append(f"  [WARN] {msg}")
            lines.append("")
        if r.passes:
            lines.append("PASSED:")
            for msg in r.passes:
                lines.append(f"  [OK]   {msg}")
        components = getattr(r, "installed_components", [])
        if components:
            lines.append("")
            lines.append("INSTALLED COMPONENTS:")
            for c in components:
                lines.append(f"  {c['name']} ({c.get('method', 'unknown')})")

        return "\n".join(lines)

    def _toggle_full_report(self):
        visible = self._full_view.isVisible()
        self._full_view.setVisible(not visible)
        self._toggle_btn.setText("Hide all checks" if not visible else "Show all checks")
        self.adjustSize()

    def _copy_report(self):
        QGuiApplication.clipboard().setText(self._build_plain_text())
