
import sys
import traceback
from pathlib import Path
from unittest import result

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pdf_structure_analyzer import analyze_pdf_structure



class PDFAnalysisWorker(QThread):
    """Runs PDF analysis without freezing the interface."""

    progress = Signal(int, int, str)
    result_ready = Signal(str, object)
    error_ready = Signal(str, str)

    def __init__(self, pdf_paths):
        super().__init__()
        self.pdf_paths = list(pdf_paths)

    def run(self):
        total = len(self.pdf_paths)

        for index, pdf_path in enumerate(self.pdf_paths, start=1):
            filename = Path(pdf_path).name

            self.progress.emit(index, total, filename)

            try:
                result = analyze_pdf_structure(pdf_path)
                self.result_ready.emit(pdf_path, result)

            except Exception:
                error_details = traceback.format_exc()
                self.error_ready.emit(pdf_path, error_details)


class PDFAnalysisTestWindow(QMainWindow):
    """Standalone interface for testing the universal PDF analyzer."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Universal PDF Analysis - Test Workspace")
        self.resize(1200, 800)

        self.worker = None
        self.analysis_summaries = []

        self.setup_ui()

    # ======================================================
    # USER INTERFACE
    # ======================================================

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        # --------------------------------------------------
        # HEADER
        # --------------------------------------------------

        title = QLabel("Universal PDF Analysis")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold;"
        )

        subtitle = QLabel(
            "Select multiple PDF documents and evaluate "
            "the structural analysis engine."
        )
        subtitle.setStyleSheet("color: #888888;")

        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        # --------------------------------------------------
        # FILE SELECTION
        # --------------------------------------------------

        file_header = QHBoxLayout()

        file_label = QLabel("Selected PDF Documents")
        file_label.setStyleSheet(
            "font-size: 15px; font-weight: bold;"
        )

        file_header.addWidget(file_label)
        file_header.addStretch()

        self.add_button = QPushButton("Add PDFs")
        self.add_button.clicked.connect(self.add_pdfs)

        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_selected)

        self.clear_button = QPushButton("Clear All")
        self.clear_button.clicked.connect(self.clear_files)

        file_header.addWidget(self.add_button)
        file_header.addWidget(self.remove_button)
        file_header.addWidget(self.clear_button)

        main_layout.addLayout(file_header)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.file_list.setMinimumHeight(140)

        main_layout.addWidget(self.file_list)

        self.file_count_label = QLabel("0 documents selected")
        self.file_count_label.setStyleSheet("color: #888888;")

        main_layout.addWidget(self.file_count_label)

        # --------------------------------------------------
        # ANALYSIS CONTROLS
        # --------------------------------------------------

        control_layout = QHBoxLayout()

        self.analyze_button = QPushButton("Analyze PDFs")
        self.analyze_button.setMinimumHeight(38)

        self.analyze_button.setStyleSheet(
            """
            QPushButton {
                background-color: #2463a6;
                color: white;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 5px;
            }

            QPushButton:disabled {
                background-color: #555555;
            }
            """
        )

        self.analyze_button.clicked.connect(self.start_analysis)

        self.status_label = QLabel("Ready")

        control_layout.addWidget(self.analyze_button)
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()

        main_layout.addLayout(control_layout)

        # --------------------------------------------------
        # PROGRESS BAR
        # --------------------------------------------------

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        main_layout.addWidget(self.progress_bar)

        # --------------------------------------------------
        # RESULTS
        # --------------------------------------------------

        results_label = QLabel("Batch Analysis Results")
        results_label.setStyleSheet(
            "font-size: 15px; font-weight: bold;"
        )

        main_layout.addWidget(results_label)

        self.results_output = QPlainTextEdit()
        self.results_output.setReadOnly(True)

        self.results_output.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )

        self.results_output.setPlaceholderText(
            "Your consolidated PDF analysis report "
            "will appear here after processing."
        )

        self.results_output.setStyleSheet(
            """
            QPlainTextEdit {
                font-family: Consolas, monospace;
                font-size: 9pt;
            }
            """
        )

        main_layout.addWidget(self.results_output, stretch=1)

    # ======================================================
    # FILE MANAGEMENT
    # ======================================================

    def add_pdfs(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDF Documents",
            "",
            "PDF Documents (*.pdf)",
        )

        if not file_paths:
            return

        existing_paths = {
            self.file_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.file_list.count())
        }

        added_count = 0

        for file_path in file_paths:
            normalized_path = str(Path(file_path).resolve())

            if normalized_path in existing_paths:
                continue

            item = QListWidgetItem(Path(file_path).name)

            item.setToolTip(normalized_path)

            item.setData(
                Qt.ItemDataRole.UserRole,
                normalized_path,
            )

            self.file_list.addItem(item)

            existing_paths.add(normalized_path)
            added_count += 1

        self.update_file_count()

        if added_count:
            self.status_label.setText(
                f"Added {added_count} document(s)."
            )

    def remove_selected(self):
        selected_items = self.file_list.selectedItems()

        for item in selected_items:
            row = self.file_list.row(item)
            self.file_list.takeItem(row)

        self.update_file_count()

    def clear_files(self):
        self.file_list.clear()

        self.update_file_count()

        self.status_label.setText(
            "File selection cleared."
        )

    def update_file_count(self):
        count = self.file_list.count()

        self.file_count_label.setText(
            f"{count} document(s) selected"
        )

        self.analyze_button.setEnabled(count > 0)

    # ======================================================
    # ANALYSIS
    # ======================================================

    def start_analysis(self):
        if self.worker is not None and self.worker.isRunning():
            return

        pdf_paths = [
            self.file_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.file_list.count())
        ]

        if not pdf_paths:
            QMessageBox.information(
                self,
                "No PDFs Selected",
                "Please select at least one PDF document.",
            )
            return

        # Reset previous session data.
        self.results_output.clear()
        self.analysis_summaries.clear()

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            "UNIVERSAL PDF ANALYSIS TEST SESSION"
        )

        self.results_output.appendPlainText(
            f"Documents selected: {len(pdf_paths)}"
        )

        self.results_output.appendPlainText(
            "=" * 110
        )

        # Configure progress.
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(pdf_paths))

        # Disable file controls during processing.
        self.set_controls_enabled(False)

        self.status_label.setText(
            "Starting analysis..."
        )

        # Create worker.
        self.worker = PDFAnalysisWorker(pdf_paths)

        self.worker.progress.connect(
            self.update_progress
        )

        self.worker.result_ready.connect(
            self.display_result
        )

        self.worker.error_ready.connect(
            self.display_error
        )

        self.worker.finished.connect(
            self.analysis_finished
        )

        self.worker.start()

    def update_progress(self, current, total, filename):
        self.progress_bar.setValue(current)

        self.status_label.setText(
            f"Analyzing {current}/{total}: {filename}"
        )

    # ======================================================
    # RESULT COLLECTION
    # ======================================================

    def display_result(self, pdf_path, result):
        """
        Collects document metrics without printing
        detailed diagnostics for every PDF.
        """

        filename = Path(pdf_path).name

        # Handle unexpected analyzer output.
        if not isinstance(result, dict):
            self.analysis_summaries.append({
                "filename": filename,
                "status": "ERROR",
                "error": (
                    f"Unexpected result type: "
                    f"{type(result).__name__}"
                ),
            })
            return

        pages = result.get("pages", [])

        summary = {
            "filename": filename,
            "status": "SUCCESS",

            "pages": result.get(
                "page_count",
                len(pages),
            ),

            "model": result.get(
                "document_model_version",
                "Unknown",
            ),

            "tables": 0,
            "containers": 0,
            "regions": 0,

            "lines": 0,
            "unassigned": 0,

            "cells": 0,
            "populated": 0,

            "high": 0,
            "medium": 0,
            "low": 0,
            "unknown": 0,

            "fallback": 0,
        }

        # --------------------------------------------------
        # COLLECT DOCUMENT METRICS
        # --------------------------------------------------

        for page in pages:
            summary["tables"] += page.get(
                "table_count", 0
            )

            summary["containers"] += page.get(
                "container_count", 0
            )

            summary["regions"] += page.get(
                "text_region_count", 0
            )

            summary["lines"] += page.get(
                "text_line_count", 0
            )

            summary["unassigned"] += len(
                page.get("unassigned_text", [])
            )

            # Collect assignment diagnostics.
            diagnostics = page.get(
                "diagnostics", {}
            )

            assignment = diagnostics.get(
                "assignment", {}
            )

            if isinstance(assignment, dict):
                summary["fallback"] += assignment.get(
                    "fallback_assigned_lines", 0
                )

            # Collect cell information.
            for table in page.get("tables", []):
                for row in table.get("rows", []):
                    for cell in row.get("cells", []):
                        summary["cells"] += 1

                        if cell.get("text", "").strip():
                            summary["populated"] += 1

                        confidence = cell.get(
                            "assignment_confidence"
                        )

                        if confidence in (
                            "high",
                            "medium",
                            "low",
                        ):
                            summary[confidence] += 1
                        else:
                            summary["unknown"] += 1

        # --------------------------------------------------
        # CALCULATE TEXT COVERAGE
        # --------------------------------------------------

        summary["coverage"] = (
            (
                summary["lines"]
                - summary["unassigned"]
            )
            / summary["lines"] * 100
            if summary["lines"] else 0
        )

        # --------------------------------------------------
        # IDENTIFY DOCUMENT STRUCTURE
        # --------------------------------------------------

        if summary["tables"] and summary["containers"]:
            summary["layout"] = "Mixed"

        elif summary["tables"]:
            summary["layout"] = "Table-based"

        elif summary["containers"]:
            summary["layout"] = "Container-based"

        elif summary["regions"]:
            summary["layout"] = "Text-based"

        else:
            summary["layout"] = "Empty/Graphical"

        # --------------------------------------------------
        # STORE SUMMARY
        # --------------------------------------------------

        self.analysis_summaries.append(summary)

    def display_error(self, pdf_path, error_details):
        """
        Records failed documents without stopping
        the remaining analysis batch.
        """

        filename = Path(pdf_path).name

        error_lines = error_details.strip().splitlines()

        short_error = (
            error_lines[-1]
            if error_lines
            else "Unknown error"
        )

        self.analysis_summaries.append({
            "filename": filename,
            "status": "ERROR",
            "error": short_error,
        })

    # ======================================================
    # FINAL BATCH REPORT
    # ======================================================

    def analysis_finished(self):
        self.set_controls_enabled(True)

        self.status_label.setText(
            "Analysis session finished."
        )

        summaries = self.analysis_summaries

        successful = [
            item for item in summaries
            if item.get("status") == "SUCCESS"
        ]

        failed = [
            item for item in summaries
            if item.get("status") == "ERROR"
        ]

        # --------------------------------------------------
        # SESSION TOTALS
        # --------------------------------------------------

        total_pages = sum(
            item["pages"] for item in successful
        )

        total_tables = sum(
            item["tables"] for item in successful
        )

        total_containers = sum(
            item["containers"] for item in successful
        )

        total_regions = sum(
            item["regions"] for item in successful
        )

        total_lines = sum(
            item["lines"] for item in successful
        )

        total_unassigned = sum(
            item["unassigned"] for item in successful
        )

        total_cells = sum(
            item["cells"] for item in successful
        )

        total_populated = sum(
            item["populated"] for item in successful
        )

        total_fallback = sum(
            item["fallback"] for item in successful
        )

        overall_coverage = (
            (
                total_lines - total_unassigned
            ) / total_lines * 100
            if total_lines else 0
        )

        # --------------------------------------------------
        # REPORT HEADER
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            "PDF ANALYSIS — BATCH SUMMARY"
        )

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            f"Documents processed: {len(summaries)} | "
            f"Successful: {len(successful)} | "
            f"Failed: {len(failed)}"
        )

        self.results_output.appendPlainText(
            f"Total pages: {total_pages}"
        )

        # --------------------------------------------------
        # STRUCTURE TOTALS
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "DETECTED STRUCTURES"
        )

        self.results_output.appendPlainText(
            f"Tables: {total_tables} | "
            f"Containers: {total_containers} | "
            f"Text regions: {total_regions}"
        )

        # --------------------------------------------------
        # TEXT PROCESSING TOTALS
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "TEXT PROCESSING"
        )

        self.results_output.appendPlainText(
            f"Extracted lines: {total_lines} | "
            f"Unassigned lines: {total_unassigned} | "
            f"Coverage: {overall_coverage:.1f}%"
        )

        # --------------------------------------------------
        # TABLE TOTALS
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "TABLE PROCESSING"
        )

        if total_cells:
            cell_rate = (
                total_populated / total_cells * 100
            )

            self.results_output.appendPlainText(
                f"Populated cells: "
                f"{total_populated}/{total_cells} "
                f"({cell_rate:.1f}%)"
            )

        else:
            self.results_output.appendPlainText(
                "Table population: N/A — "
                "no table cells detected."
            )

        self.results_output.appendPlainText(
            f"Fallback assignments: {total_fallback}"
        )

        # --------------------------------------------------
        # DOCUMENT COMPARISON
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "-" * 110
        )

        self.results_output.appendPlainText(
            "DOCUMENT COMPARISON"
        )

        self.results_output.appendPlainText(
            "-" * 110
        )

        header = (
            f"{'DOCUMENT':<34}"
            f"{'PAGES':>6}"
            f"{'LAYOUT':>17}"
            f"{'T/C/R':>12}"
            f"{'COVERAGE':>11}"
            f"{'CELLS':>13}"
            f"{'FALLBACK':>10}"
            f"{'REVIEW':>10}"
        )

        self.results_output.appendPlainText(header)

        self.results_output.appendPlainText(
            "-" * 110
        )

        for item in summaries:
            filename = item["filename"][:32]

            # Failed documents.
            if item.get("status") == "ERROR":
                self.results_output.appendPlainText(
                    f"{filename:<34}  ANALYSIS FAILED"
                )

                self.results_output.appendPlainText(
                    f"  Error: {item.get('error', 'Unknown error')}"
                )

                continue

            # Table population.
            cell_display = (
                f"{item['populated']}/{item['cells']}"
                if item["cells"]
                else "N/A"
            )

            # Review indicators.
            review = (
                f"U{item['unassigned']}"
                f"/L{item['low']}"
                f"/E{item['cells'] - item['populated']}"
            )

            # Structure counts.
            structure_counts = (
                f"{item['tables']}/"
                f"{item['containers']}/"
                f"{item['regions']}"
            )

            coverage_display = (
                f"{item['coverage']:.1f}%"
            )

            self.results_output.appendPlainText(
                f"{filename:<34}"
                f"{item['pages']:>6}"
                f"{item['layout']:>17}"
                f"{structure_counts:>12}"
                f"{coverage_display:>11}"
                f"{cell_display:>13}"
                f"{item['fallback']:>10}"
                f"{review:>10}"
            )

        # --------------------------------------------------
        # CONFIDENCE TOTALS
        # --------------------------------------------------

        if total_cells:
            total_high = sum(
                item["high"] for item in successful
            )

            total_medium = sum(
                item["medium"] for item in successful
            )

            total_low = sum(
                item["low"] for item in successful
            )

            total_unknown = sum(
                item["unknown"] for item in successful
            )

            self.results_output.appendPlainText("")

            self.results_output.appendPlainText(
                "CELL ASSIGNMENT CONFIDENCE"
            )

            self.results_output.appendPlainText(
                f"High: {total_high} | "
                f"Medium: {total_medium} | "
                f"Low: {total_low} | "
                f"Unknown: {total_unknown}"
            )

        # --------------------------------------------------
        # REVIEW KEY
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "REVIEW KEY:"
        )

        self.results_output.appendPlainText(
            "U = Unassigned text lines"
        )

        self.results_output.appendPlainText(
            "L = Low-confidence cell assignments"
        )

        self.results_output.appendPlainText(
            "E = Empty table cells"
        )

        self.results_output.appendPlainText(
            "T/C/R = Tables / Containers / Text regions"
        )

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "Text coverage measures lines not marked "
            "unassigned. It does not verify correct placement."
        )

        # --------------------------------------------------
        # COMPLETION
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            "TEST SESSION FINISHED"
        )

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.worker = None

    # ======================================================
    # WORKER STATE
    # ======================================================

    def set_controls_enabled(self, enabled):
        self.add_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)

        self.file_list.setEnabled(enabled)

        self.analyze_button.setEnabled(
            enabled and self.file_list.count() > 0
        )

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(
                self,
                "Analysis Running",
                "Wait for the current analysis to finish "
                "before closing this window.",
            )

            event.ignore()
            return

        event.accept()


def main():
    app = QApplication(sys.argv)

    window = PDFAnalysisTestWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
