"""The report-a-problem dialog.

Shows exactly what will be posted before anything leaves the machine, because
the repository is public and the report carries details of this computer.
"""

from __future__ import annotations

import logging
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from espec_burnin.core.diagnostics import Report, issue_url, read_log_tail
from espec_burnin.core.trail import TRAIL
from espec_burnin.ui.widgets import button

log = logging.getLogger(__name__)

class ReportDialog(QDialog):
    """Pick bug or improvement, describe it, see what will be sent, post it."""

    def __init__(self, context: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Report a problem or an idea")
        self.setMinimumWidth(620)

        self.report = Report(
            context=context, trail=TRAIL.lines(), log_tail=read_log_tail()
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QLabel("What would you like to report?")
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        self.bug = QRadioButton("A bug — the program did something wrong")
        self.improvement = QRadioButton("An improvement — something would work better")
        self.bug.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.bug)
        group.addButton(self.improvement)
        layout.addWidget(self.bug)
        layout.addWidget(self.improvement)
        self.bug.toggled.connect(self._refresh)

        self.summary = QLineEdit()
        self.summary.setPlaceholderText("One line: what went wrong, or what would help")
        self.summary.textChanged.connect(self._refresh)
        layout.addWidget(self.summary)

        self.description = QPlainTextEdit()
        self.description.setPlaceholderText(
            "What were you doing, and what did you see? Anything you already tried."
        )
        self.description.setMinimumHeight(110)
        self.description.textChanged.connect(self._refresh)
        layout.addWidget(self.description)

        self.note = QLabel(
            "The details below are collected automatically and go with the report, "
            "including which screens you opened and which buttons you pressed. "
            "Edit anything you like — what is posted is what this box says. This "
            "repository is public, so check you are happy with it; paths under "
            "your home folder are shortened to <code>~</code>."
        )
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.RichText)
        self.note.setObjectName("Subtitle")
        layout.addWidget(self.note)

        # Editable, not just visible. The report is about to be posted to a
        # public repository under the user's name; being able to add a line or
        # take one out is the difference between showing someone their data
        # and letting them decide about it.
        self.preview = QPlainTextEdit()
        self.preview.setMinimumHeight(180)
        self._edited = False
        self._loading = False
        self.preview.textChanged.connect(self._preview_edited)
        layout.addWidget(self.preview, 1)

        # Built from the shared button so the three read as the same kind of
        # control. They used to be a filled one and two bare words.
        buttons = QDialogButtonBox()
        self.post = button("Open GitHub to post it", "open", "primary")
        buttons.addButton(self.post, QDialogButtonBox.AcceptRole)
        self.copy = button("Copy to clipboard", "copy")
        buttons.addButton(self.copy, QDialogButtonBox.ActionRole)
        buttons.addButton(button("Cancel", "cancel"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._post)
        buttons.rejected.connect(self.reject)
        self.copy.clicked.connect(self._copy)
        layout.addWidget(buttons)

        self._refresh()

    # -- assembling ----------------------------------------------------------
    def _current(self) -> Report:
        self.report.kind = "bug" if self.bug.isChecked() else "improvement"
        self.report.summary = self.summary.text()
        self.report.description = self.description.toPlainText()
        return self.report

    def _preview_edited(self) -> None:
        """Once it has been touched by hand, the program stops rewriting it."""
        if not self._loading:
            self._edited = True
            self.note.setText(
                "You have edited the report below. What is posted is exactly "
                "what it says now."
            )

    def _text(self) -> str:
        """What will actually be posted."""
        if self._edited:
            return self.preview.toPlainText()
        report = self._current()
        return f"{report.title}\n\n{report.body()}"

    def _refresh(self) -> None:
        self.post.setEnabled(bool(self.summary.text().strip()))
        if self._edited:
            return
        report = self._current()
        self._loading = True
        try:
            self.preview.setPlainText(f"{report.title}\n\n{report.body()}")
        finally:
            self._loading = False

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._text())
        QMessageBox.information(
            self, "Copied",
            "The whole report is on your clipboard. Paste it into a new issue.",
        )

    def _post(self) -> None:
        report = self._current()
        url, trimmed = issue_url(report, edited=self._text() if self._edited else None)

        # On the clipboard either way: if the log had to be dropped to fit the
        # address bar, the full text is still one paste away.
        QGuiApplication.clipboard().setText(self._text())

        if not webbrowser.open(url):
            QMessageBox.warning(
                self, "Could not open your browser",
                "The full report is on your clipboard. Open the repository's "
                "Issues page and paste it into a new issue.",
            )
            return

        if trimmed:
            QMessageBox.information(
                self, "One thing to paste",
                "GitHub is open with the report filled in, but it was too long "
                "for the address bar so the log lines were left out. The full "
                "report is on your clipboard if you want to paste it instead.",
            )
        self.accept()
