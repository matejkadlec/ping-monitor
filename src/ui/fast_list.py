"""
A one-column QTableView set up to look and behave like a list.

QListView lays out every row again on each insert or removal and asks the
(Python) model about every row while doing so: ~66 ms per ping with an hour of
pings at 1 s, ~290 ms at the 200,000-row cap. A table view with fixed row
heights does the same work in a few milliseconds at any size.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHeaderView, QTableView, QWidget


class FastListView(QTableView):
    def __init__(self, row_height: Callable[[], int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row_height = row_height
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.setTabKeyNavigation(False)
        self.horizontalHeader().hide()
        self.horizontalHeader().setStretchLastSection(True)
        vertical = self.verticalHeader()
        vertical.hide()
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setMinimumSectionSize(1)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QTableView { background: transparent; border: none; outline: none; }")
        self.apply_row_height()

    def apply_row_height(self) -> None:
        """Call after a UI scale change."""
        self.verticalHeader().setDefaultSectionSize(self._row_height())

    def moveCursor(self, action, modifiers):  # noqa: N802 - Qt naming
        # In a table, Home / End move within the row; in a list they go to the
        # first / last row (what Ctrl+Home / Ctrl+End do in a table).
        if action in (QAbstractItemView.CursorAction.MoveHome, QAbstractItemView.CursorAction.MoveEnd):
            modifiers = modifiers | Qt.KeyboardModifier.ControlModifier
        return super().moveCursor(action, modifiers)
