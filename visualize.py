import sys
import os
import json
import bazaarFetch
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableView, QLineEdit, QLabel, QPushButton, QHeaderView,
    QStatusBar, QGroupBox, QStyledItemDelegate
)
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
)
from PySide6.QtGui import QColor, QFont, QCursor

# ---- Bookmark persistence path (same dir as this script) ----
BOOKMARKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookmarks.json")

# ---- Column definitions ----
# Last column 'bookmarked' is the ☆/★ toggle
COLUMNS = [
    ('product_id',        'Item'),
    ('buy_price',         'Buy Price'),
    ('sell_price',        'Sell Price'),
    ('margin',            'Margin'),
    ('margin_percent',    'Margin %'),
    ('buy_volume',        'Buy Vol'),
    ('sell_volume',       'Sell Vol'),
    ('buy_moving_week',   'Buy Vol (7d)'),
    ('sell_moving_week',  'Sell Vol (7d)'),
    ('price_stability',   'Price Stab.'),
    ('volume_stability',  'Vol Stab.'),
    ('is_spike',          'Spike'),
    ('bookmarked',        '★'),
]

# Pre-computed column key -> index map
_COL_INDEX = {key: i for i, (key, _) in enumerate(COLUMNS)}

# ---- Bookmark helpers ----

def load_bookmarks():
    """Load bookmarked product IDs from JSON file."""
    if os.path.exists(BOOKMARKS_FILE):
        try:
            with open(BOOKMARKS_FILE, 'r') as f:
                return set(json.load(f))
        except (json.JSONDecodeError, TypeError):
            return set()
    return set()

def save_bookmarks(bookmarks_set):
    """Save bookmarked product IDs to JSON file."""
    with open(BOOKMARKS_FILE, 'w') as f:
        json.dump(list(bookmarks_set), f)

# ---- Dark theme stylesheet ----
DARK_STYLE = """
QMainWindow {
    background-color: #1a1a2e;
}
QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
QTableView {
    background-color: #16213e;
    alternate-background-color: #1a1a2e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    gridline-color: #0f3460;
    selection-background-color: #533483;
    selection-color: #ffffff;
    padding: 2px;
}
QTableView::item {
    padding: 4px 8px;
}
QHeaderView::section {
    background-color: #0f3460;
    color: #e94560;
    padding: 6px 8px;
    border: none;
    border-bottom: 2px solid #e94560;
    font-weight: bold;
    font-size: 12px;
}
QLineEdit {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 6px 12px;
    color: #e0e0e0;
    font-size: 13px;
}
QLineEdit:focus {
    border: 1px solid #e94560;
}
QPushButton {
    background-color: #e94560;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: bold;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #ff6b81;
}
QPushButton:pressed {
    background-color: #c0392b;
}
QGroupBox {
    border: 1px solid #0f3460;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: bold;
    color: #e94560;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QLabel {
    color: #a0a0b0;
    font-size: 12px;
}
QStatusBar {
    background-color: #0f3460;
    color: #a0a0b0;
    font-size: 12px;
}
QScrollBar:vertical {
    background-color: #1a1a2e;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #533483;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


class BazaarTableModel(QAbstractTableModel):
    """Table model holding bazaar data + bookmark state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self._bookmarks = load_bookmarks()

    def set_data(self, items):
        """Replace all data and refresh the view. Merges bookmark state."""
        self.beginResetModel()
        # Inject bookmark flag into each row dict
        for item in items:
            item['bookmarked'] = item['product_id'] in self._bookmarks
        self._data = items
        self.endResetModel()

    def raw_row(self, row):
        """Direct access to the underlying dict for a row (used by proxy)."""
        return self._data[row]

    def toggle_bookmark(self, row):
        """Toggle bookmark for a row and persist to disk."""
        if row < 0 or row >= len(self._data):
            return
        item = self._data[row]
        pid = item['product_id']
        is_bookmarked = not item.get('bookmarked', False)
        item['bookmarked'] = is_bookmarked

        # Update persistent set
        if is_bookmarked:
            self._bookmarks.add(pid)
        else:
            self._bookmarks.discard(pid)
        save_bookmarks(self._bookmarks)

        # Notify view that the bookmark column changed
        bm_col = _COL_INDEX['bookmarked']
        idx = self.index(row, bm_col)
        self.dataChanged.emit(idx, idx)

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col_key = COLUMNS[index.column()][0]
        value = self._data[row].get(col_key)

        if role == Qt.DisplayRole:
            if col_key == 'bookmarked':
                return '★' if value else '☆'
            if col_key == 'is_spike':
                return '⚠️ SPIKE' if value else '—'
            if col_key == 'margin_percent':
                return f"{value:.1f}%"
            if col_key in ('buy_price', 'sell_price', 'margin'):
                return f"{value:,.1f}"
            if col_key in ('buy_volume', 'sell_volume', 'buy_moving_week', 'sell_moving_week'):
                return f"{value:,}"
            if col_key in ('price_stability', 'volume_stability'):
                return f"{value}/100"
            return str(value)

        # Color coding
        if role == Qt.ForegroundRole:
            if col_key == 'bookmarked':
                return QColor('#f1c40f') if value else QColor('#555555')
            if col_key in ('price_stability', 'volume_stability'):
                if value >= 70:
                    return QColor('#2ecc71')
                elif value >= 40:
                    return QColor('#f39c12')
                else:
                    return QColor('#e74c3c')
            if col_key == 'is_spike' and value:
                return QColor('#e74c3c')
            if col_key in ('margin', 'margin_percent'):
                raw = self._data[row].get(col_key, 0)
                if raw > 0:
                    return QColor('#2ecc71')
                elif raw < 0:
                    return QColor('#e74c3c')

        # Center the bookmark star, right-align other numeric columns
        if role == Qt.TextAlignmentRole:
            if col_key == 'bookmarked':
                return Qt.AlignCenter
            if col_key != 'product_id':
                return Qt.AlignRight | Qt.AlignVCenter

        # Font size for the bookmark star
        if role == Qt.FontRole:
            if col_key == 'bookmarked':
                font = QFont()
                font.setPointSize(14)
                return font

        # Sort role returns raw value for proper numeric sorting
        if role == Qt.UserRole:
            if col_key == 'is_spike':
                return 1 if value else 0
            if col_key == 'bookmarked':
                return 1 if value else 0
            return value

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section][1]
        return None


class NumericSortProxy(QSortFilterProxyModel):
    """
    Proxy model: sorts numerically via UserRole, filters via direct dict access.
    Filters are batched — call apply_all() once after setting search/ranges.
    Supports bookmarks-only mode.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ''
        self._filters = {}  # col_key -> (min_val, max_val)
        self._bookmarks_only = False  # When True, only show bookmarked items

    # --- Setters (do NOT trigger invalidation — call apply_all() after) ---

    def set_search(self, text):
        self._search_text = text.lower()

    def set_range_filter(self, col_key, min_val, max_val):
        self._filters[col_key] = (min_val, max_val)

    def set_bookmarks_only(self, enabled):
        self._bookmarks_only = enabled

    def clear_all(self):
        self._filters.clear()
        self._search_text = ''
        # Note: bookmarks_only is NOT cleared here (it's a view toggle)

    def apply_all(self):
        """Single invalidation point."""
        self.invalidateRowsFilter()

    # --- Sorting ---

    def lessThan(self, left, right):
        left_data = self.sourceModel().data(left, Qt.UserRole)
        right_data = self.sourceModel().data(right, Qt.UserRole)

        if left_data is None:
            return True
        if right_data is None:
            return False

        try:
            return float(left_data) < float(right_data)
        except (ValueError, TypeError):
            return str(left_data) < str(right_data)

    # --- Filtering (reads dict directly for speed) ---

    def filterAcceptsRow(self, source_row, source_parent):
        row_data = self.sourceModel().raw_row(source_row)

        # Bookmarks-only mode
        if self._bookmarks_only:
            if not row_data.get('bookmarked', False):
                return False

        # Search filter on product_id
        if self._search_text:
            pid = row_data.get('product_id', '')
            if self._search_text not in pid.lower():
                return False

        # Range filters
        for col_key, (min_val, max_val) in self._filters.items():
            val = row_data.get(col_key, 0)
            try:
                val = float(val) if val is not None else 0
            except (ValueError, TypeError):
                continue
            if min_val is not None and val < min_val:
                return False
            if max_val is not None and val > max_val:
                return False

        return True


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bazaar Flipper")
        self.setMinimumSize(1200, 700)
        self.resize(1650, 900)

        # ---- Debounce timer: waits 300ms after last input before filtering ----
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._do_apply_filters)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # --- Top bar: Search + Bookmarks toggle + Refresh ---
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        search_label = QLabel("Search:")
        search_label.setStyleSheet("font-size: 14px; color: #e0e0e0;")
        self.warn_text = QLabel("You are not using a api key! Get one from hypixel developer portal, and put it on .env file as API_KEY")
        self.warn_text.setStyleSheet("color: #e0e0e0; font-size: 16px; font-weight: bold;")
        self.warn_text.hide()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type item name to search")
        self.search_input.setMinimumWidth(350)
        self.search_input.textChanged.connect(self._schedule_filter)

        # Bookmarks toggle button
        self.bookmarks_btn = QPushButton("☆ Bookmarks")
        self.bookmarks_btn.setFixedWidth(140)
        self.bookmarks_btn.setCheckable(True)
        self.bookmarks_btn.setStyleSheet("""
            QPushButton {
                background-color: #533483;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #6c44a0; }
            QPushButton:checked {
                background-color: #f1c40f;
                color: #1a1a2e;
            }
            QPushButton:checked:hover {
                background-color: #f9e154;
            }
        """)
        self.bookmarks_btn.toggled.connect(self._on_bookmarks_toggled)

        # Refresh button
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedWidth(120)
        self.refresh_btn.clicked.connect(self.refresh_data)

        top_bar.addWidget(search_label)
        top_bar.addWidget(self.search_input)
        top_bar.addStretch()
        top_bar.addWidget(self.warn_text)
        top_bar.addWidget(self.bookmarks_btn)
        top_bar.addWidget(self.refresh_btn)
        main_layout.addLayout(top_bar)

        # --- Filter panel (two rows to fit more filters) ---
        filter_group = QGroupBox("Filters")
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)

        self.filter_inputs = {}

        # Separate buy vol, sell vol, 7d volumes, price, margin filters
        for label, col_key in [
            ("Buy Vol", "buy_volume"),
            ("Sell Vol", "sell_volume"),
            ("Buy Vol (7d)", "buy_moving_week"),  
            ("Sell Vol (7d)", "sell_moving_week"), 
            ("Price", "buy_price"),
            ("Margin", "margin"),
        ]:
            section = QVBoxLayout()
            section_label = QLabel(label)
            section_label.setStyleSheet("color: #e94560; font-weight: bold; font-size: 13px;")
            section.addWidget(section_label)

            row = QHBoxLayout()
            min_input = QLineEdit()
            min_input.setPlaceholderText("Min")
            min_input.setFixedWidth(80)
            max_input = QLineEdit()
            max_input.setPlaceholderText("Max")
            max_input.setFixedWidth(80)

            min_input.textChanged.connect(self._schedule_filter)
            max_input.textChanged.connect(self._schedule_filter)

            row.addWidget(QLabel("Min:"))
            row.addWidget(min_input)
            row.addWidget(QLabel("Max:"))
            row.addWidget(max_input)

            section.addLayout(row)
            filter_layout.addLayout(section)
            self.filter_inputs[col_key] = (min_input, max_input)

        # Clear filters button
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(80)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #533483;
                font-size: 12px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #6c44a0; }
        """)
        clear_btn.clicked.connect(self.clear_filters)
        filter_layout.addStretch()
        filter_layout.addWidget(clear_btn, alignment=Qt.AlignBottom)

        filter_group.setLayout(filter_layout)
        main_layout.addWidget(filter_group)

        # --- Table view ---
        self.table_model = BazaarTableModel()
        self.proxy_model = NumericSortProxy()
        self.proxy_model.setSourceModel(self.table_model)

        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        # Resize numeric columns to content, bookmark column fixed width
        for col_idx in range(1, len(COLUMNS)):
            col_key = COLUMNS[col_idx][0]
            if col_key == 'bookmarked':
                self.table_view.setColumnWidth(col_idx, 40)
                self.table_view.horizontalHeader().setSectionResizeMode(col_idx, QHeaderView.Fixed)
            else:
                self.table_view.horizontalHeader().setSectionResizeMode(col_idx, QHeaderView.ResizeToContents)

        # Handle clicks on the bookmark column
        self.table_view.clicked.connect(self._on_table_clicked)

        main_layout.addWidget(self.table_view)

        # --- Status bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready — click Refresh to load data")

        # Initial data load
        QTimer.singleShot(100, self.refresh_data)

    # ---- Bookmark click handler ----

    def _on_table_clicked(self, proxy_index):
        """Toggle bookmark when user clicks the ★ column."""
        col_key = COLUMNS[proxy_index.column()][0]
        if col_key != 'bookmarked':
            return

        # Map proxy row back to source row
        source_index = self.proxy_model.mapToSource(proxy_index)
        self.table_model.toggle_bookmark(source_index.row())

        # If in bookmarks-only mode, re-filter to hide un-bookmarked items
        if self.bookmarks_btn.isChecked():
            self.proxy_model.apply_all()
            self._update_count()

    # ---- Bookmarks toggle ----

    def _on_bookmarks_toggled(self, checked):
        """Switch between all items and bookmarks-only view."""
        if checked:
            self.bookmarks_btn.setText("★ Bookmarks")
        else:
            self.bookmarks_btn.setText("☆ Bookmarks")

        self.proxy_model.set_bookmarks_only(checked)
        self.proxy_model.apply_all()
        self._update_count()

    # ---- Debounce ----

    def _schedule_filter(self):
        self._debounce_timer.start()

    def _do_apply_filters(self):
        """Called once after 300ms of no input. Batch-applies all filters."""
        self.proxy_model.set_search(self.search_input.text())

        for col_key, (min_input, max_input) in self.filter_inputs.items():
            min_val = None
            max_val = None
            try:
                t = min_input.text().strip()
                if t:
                    min_val = float(t)
            except ValueError:
                pass
            try:
                t = max_input.text().strip()
                if t:
                    max_val = float(t)
            except ValueError:
                pass
            self.proxy_model.set_range_filter(col_key, min_val, max_val)

        self.proxy_model.apply_all()
        self._update_count()

    # ---- Refresh ----

    def refresh_data(self):
        self.status_bar.showMessage("Fetching data from Hypixel API...")
        self.refresh_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            bazaarFetch.invalidate_cache()
            # Check if there is an API error before parsing items
            raw_data = bazaarFetch.get_bazaar_data()
            if isinstance(raw_data, dict) and raw_data.get('success') == False:
                self.status_bar.showMessage(f"Error: {raw_data.get('cause', 'Unknown Error')}")
                self.warn_text.setVisible(True)
                self.table_model.set_data([])
                return
            
            self.warn_text.setVisible(False)
            items = bazaarFetch.get_all_items_summary()

            # Filter out items with 0 buy AND 0 sell price
            items = [item for item in items if item['buy_price'] > 0 or item['sell_price'] > 0]

            self.table_model.set_data(items)
            self._do_apply_filters()

            count = self.proxy_model.rowCount()
            total = len(items)
            self.status_bar.showMessage(f"Loaded {total} items • Showing {count} after filters")
        except Exception as e:
            self.status_bar.showMessage(f"Error: {e}")
        finally:
            self.refresh_btn.setEnabled(True)

    # ---- Clear ----

    def clear_filters(self):
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)

        for min_input, max_input in self.filter_inputs.values():
            min_input.blockSignals(True)
            max_input.blockSignals(True)
            min_input.clear()
            max_input.clear()
            min_input.blockSignals(False)
            max_input.blockSignals(False)

        self.proxy_model.clear_all()
        self.proxy_model.apply_all()
        self._update_count()

    def _update_count(self):
        count = self.proxy_model.rowCount()
        total = self.table_model.rowCount()
        mode = " (bookmarks)" if self.bookmarks_btn.isChecked() else ""
        self.status_bar.showMessage(f"Showing {count} of {total} items{mode}")


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
