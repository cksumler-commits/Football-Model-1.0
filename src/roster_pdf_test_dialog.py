
import sys
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
    QPlainTextEdit,
    QMessageBox,
    QSplitter,
)

from roster_pdf_import import analyze_pdf, OUTPUT_HEADERS


class RosterPDFTestWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Roster PDF Testing")
        self.resize(1450, 850)

        self.current_file = None
        self.current_analysis = None
        self.current_records = []

        self.build_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        # ----------------------------------------------------
        # FILE SELECTION
        # ----------------------------------------------------

        controls = QHBoxLayout()

        self.open_button = QPushButton("Select PDF")
        self.open_button.clicked.connect(self.select_pdf)

        self.file_label = QLabel("No PDF selected")
        self.file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        controls.addWidget(self.open_button)
        controls.addWidget(self.file_label, 1)

        main_layout.addLayout(controls)

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        summary_group = QGroupBox("PDF Analysis")
        summary_layout = QHBoxLayout(summary_group)

        self.layout_label = QLabel("Layout: —")
        self.page_label = QLabel("Pages: —")
        self.word_label = QLabel("Words: —")
        self.player_label = QLabel("Players: —")
        self.status_label = QLabel("Waiting for PDF")

        for label in (
            self.layout_label,
            self.page_label,
            self.word_label,
            self.player_label,
            self.status_label,
        ):
            label.setStyleSheet("font-weight: bold; padding: 5px;")
            summary_layout.addWidget(label)

        main_layout.addWidget(summary_group)

        # ----------------------------------------------------
        # PLAYER TABLE
        # ----------------------------------------------------

        splitter = QSplitter(Qt.Orientation.Vertical)

        table_group = QGroupBox("Reconstructed Player Records")
        table_layout = QVBoxLayout(table_group)

        self.player_table = QTableWidget()
        self.player_table.setColumnCount(len(OUTPUT_HEADERS))
        self.player_table.setHorizontalHeaderLabels(OUTPUT_HEADERS)

        self.player_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.player_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.player_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.player_table.setAlternatingRowColors(True)

        header = self.player_table.horizontalHeader()
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        header.setStretchLastSection(True)

        self.player_table.itemSelectionChanged.connect(
            self.show_selected_player
        )

        table_layout.addWidget(self.player_table)
        splitter.addWidget(table_group)

        # ----------------------------------------------------
        # DETAILS AND RAW TEXT
        # ----------------------------------------------------

        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)

        details_group = QGroupBox("Selected Player")
        details_layout = QVBoxLayout(details_group)

        self.details_text = QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setPlaceholderText(
            "Select a player record above."
        )

        details_layout.addWidget(self.details_text)

        raw_group = QGroupBox("PDF Text and Diagnostics")
        raw_layout = QVBoxLayout(raw_group)

        self.raw_text = QPlainTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )

        raw_layout.addWidget(self.raw_text)

        bottom_layout.addWidget(details_group, 1)
        bottom_layout.addWidget(raw_group, 2)

        splitter.addWidget(bottom_widget)
        splitter.setSizes([500, 300])

        main_layout.addWidget(splitter, 1)

    # ========================================================
    # FILE SELECTION
    # ========================================================

    def select_pdf(self):
        pdf_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select roster PDF",
            str(Path.home()),
            "PDF Files (*.pdf)"
        )

        if not pdf_path:
            return

        self.load_pdf(pdf_path)

    # ========================================================
    # PDF ANALYSIS
    # ========================================================

    def load_pdf(self, pdf_path):
        self.current_file = Path(pdf_path)

        self.file_label.setText(str(self.current_file))

        self.player_table.setRowCount(0)
        self.details_text.clear()
        self.raw_text.clear()

        self.current_records = []
        self.current_analysis = None

        self.status_label.setText("Analyzing...")

        try:
            result = analyze_pdf(self.current_file)

            self.current_analysis = result
            self.current_records = result["records"]

            self.update_summary()
            self.populate_table()
            self.show_pdf_diagnostics()

            if result["layout"] == "unknown":
                if result["has_selectable_text"]:
                    self.status_label.setText(
                        "Unknown layout - text recovered"
                    )
                else:
                    self.status_label.setText(
                        "No selectable text - OCR may be needed"
                    )
            elif result["records"]:
                self.status_label.setText(
                    "Supported layout - records reconstructed"
                )
            else:
                self.status_label.setText(
                    "Layout recognized - no players reconstructed"
                )

        except Exception as error:
            self.status_label.setText("PDF analysis failed")

            QMessageBox.critical(
                self,
                "PDF Analysis Error",
                f"{type(error).__name__}: {error}"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    def update_summary(self):
        result = self.current_analysis

        if not result:
            return

        self.layout_label.setText(
            f"Layout: {result['layout'].upper()}"
        )

        self.page_label.setText(
            f"Pages: {result['page_count']}"
        )

        self.word_label.setText(
            f"Words: {result['total_words']}"
        )

        self.player_label.setText(
            f"Players: {len(result['records'])}"
        )

    # ========================================================
    # PLAYER TABLE
    # ========================================================

    def populate_table(self):
        records = self.current_records

        self.player_table.setRowCount(len(records))

        for row_index, record in enumerate(records):
            for column_index, field in enumerate(OUTPUT_HEADERS):
                value = record.get(field, "") or ""

                item = QTableWidgetItem(str(value))
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemFlag.ItemIsEditable
                )

                if not value.strip():
                    item.setBackground(QColor("#F8D7DA"))
                    item.setForeground(QColor("#842029"))
                    item.setToolTip(
                        "No value was extracted for this field."
                    )

                self.player_table.setItem(
                    row_index,
                    column_index,
                    item
                )

        self.player_table.resizeRowsToContents()

    def show_selected_player(self):
        selected = self.player_table.selectionModel().selectedRows()

        if not selected:
            return

        row = selected[0].row()
        record = self.current_records[row]

        lines = [
            f"RECORD: {row + 1}",
            "",
        ]

        for field in OUTPUT_HEADERS:
            value = record.get(field, "") or "[BLANK]"
            lines.append(f"{field}: {value}")

        self.details_text.setPlainText("\n".join(lines))

    # ========================================================
    # RAW PDF TEXT AND DIAGNOSTICS
    # ========================================================

    def show_pdf_diagnostics(self):
        result = self.current_analysis

        if not result:
            return

        lines = []

        lines.append(f"FILE: {result['file_name']}")
        lines.append(f"DETECTED LAYOUT: {result['layout']}")
        lines.append(f"PAGES: {result['page_count']}")
        lines.append(f"TOTAL WORDS: {result['total_words']}")
        lines.append(
            f"SELECTABLE TEXT: "
            f"{'YES' if result['has_selectable_text'] else 'NO'}"
        )

        lines.append("")
        lines.append("=" * 75)
        lines.append("EXTRACTION SUMMARY")
        lines.append("=" * 75)

        records = result["records"]

        if records:
            blank_counts = Counter()
            jersey_counts = Counter()

            for record in records:
                for field in OUTPUT_HEADERS:
                    if not (record.get(field) or "").strip():
                        blank_counts[field] += 1

                jersey = (record.get("Jersey Number") or "").strip()
                if jersey:
                    jersey_counts[jersey] += 1

            lines.append(f"PLAYER RECORDS: {len(records)}")
            lines.append("")
            lines.append("BLANK VALUES BY FIELD:")

            for field in OUTPUT_HEADERS:
                lines.append(
                    f"  {field}: {blank_counts[field]}"
                )

            duplicates = {
                jersey: count
                for jersey, count in jersey_counts.items()
                if count > 1
            }

            lines.append("")
            lines.append("REPEATED JERSEY NUMBERS:")

            if duplicates:
                for jersey, count in sorted(duplicates.items()):
                    lines.append(f"  #{jersey}: {count} players")
            else:
                lines.append("  None detected")

        else:
            lines.append("NO PLAYER RECORDS RECONSTRUCTED.")
            lines.append(
                "The PDF text is displayed below for layout inspection."
            )

        lines.append("")
        lines.append("=" * 75)
        lines.append("EXTRACTED PDF TEXT BY PAGE")
        lines.append("=" * 75)

        for page in result["pages"]:
            lines.append("")
            lines.append(
                f"PAGE {page['page_number']} "
                f"({page['width']} x {page['height']})"
            )
            lines.append(f"WORDS: {page['word_count']}")
            lines.append("-" * 75)

            if page["text"].strip():
                lines.append(page["text"].strip())
            else:
                lines.append(
                    "[No selectable text found on this page]"
                )

        self.raw_text.setPlainText("\n".join(lines))


def main():
    app = QApplication(sys.argv)

    window = RosterPDFTestWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
