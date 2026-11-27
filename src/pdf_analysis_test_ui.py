
import sys
from tkinter import dialog
import traceback
from pathlib import Path
from unittest import result
from PySide6.QtCore import QRectF, QTimer, Qt

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
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
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QDialog,
    QGraphicsScene,
    QGraphicsView,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)

from pdf_structure_analyzer import analyze_pdf_structure

from pdf_document_engine import extract_page_words

from PySide6.QtGui import (
    QColor,
    QPen,
    QBrush,
    QPixmap,
    QPainter,
)
import pymupdf
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF

import re



def detect_player_entries(words, selection_bbox):
    """
    Identify candidate player entries using repeated number
    positions and vertical record boundaries.

    This is structural detection, not final player recognition.
    """

    sx0, sy0, sx1, sy1 = selection_bbox

    number_candidates = []

    # Step 1: Find possible jersey-number tokens.
    for word in words:
        text = word.get("text", "").strip()
        bbox = word.get("bbox")

        if not bbox or len(bbox) != 4:
            continue

        if not re.fullmatch(r"#?\d{1,2}", text):
            continue

        x0, y0, x1, y1 = map(float, bbox)

        number_candidates.append({
            "text": text.lstrip("#"),
            "x": x0,
            "y": (y0 + y1) / 2,
            "bbox": [x0, y0, x1, y1],
            "word": word,
        })

    if not number_candidates:
        return []

    # Step 2: Group number candidates by horizontal alignment.
    sorted_candidates = sorted(
        number_candidates,
        key=lambda item: item["x"],
    )

    x_groups = []

    for candidate in sorted_candidates:
        matching_group = None

        for group in x_groups:
            group_center = sum(
                item["x"] for item in group
            ) / len(group)

            if abs(candidate["x"] - group_center) <= 10:
                matching_group = group
                break

        if matching_group is None:
            x_groups.append([candidate])
        else:
            matching_group.append(candidate)

    # Prefer the leftmost repeated number column.
    repeated_groups = [
        group for group in x_groups
        if len(group) >= 2
    ]

    if repeated_groups:
        anchor_group = min(
            repeated_groups,
            key=lambda group: min(
                item["x"] for item in group
            ),
        )
    else:
        anchor_group = [
            min(
                number_candidates,
                key=lambda item: item["x"],
            )
        ]

    # Step 3: Sort anchors vertically and remove duplicates.
    anchors = sorted(
        anchor_group,
        key=lambda item: item["y"],
    )

    unique_anchors = []

    for anchor in anchors:
        if (
            unique_anchors
            and abs(
                anchor["y"] - unique_anchors[-1]["y"]
            ) <= 4
        ):
            continue

        unique_anchors.append(anchor)

    anchors = unique_anchors

    if not anchors:
        return []

    records = []

    # Step 4: Divide the selection into candidate record regions.
    for index, anchor in enumerate(anchors):

        if index == 0:
            top = sy0
        else:
            top = (
                anchors[index - 1]["y"] + anchor["y"]
            ) / 2

        if index == len(anchors) - 1:
            bottom = sy1
        else:
            bottom = (
                anchor["y"] + anchors[index + 1]["y"]
            ) / 2

        record_words = []

        for word in words:
            bbox = word.get("bbox")

            if not bbox or len(bbox) != 4:
                continue

            x0, y0, x1, y1 = map(float, bbox)
            center_y = (y0 + y1) / 2

            if top <= center_y < bottom:
                record_words.append(word)

        # Step 5: Reconstruct the text in the candidate record.
        line_groups = {}

        for word in record_words:
            key = (
                word.get("block_number"),
                word.get("line_number"),
            )

            line_groups.setdefault(key, []).append(word)

        reconstructed_lines = []

        for line_words in line_groups.values():
            line_words.sort(
                key=lambda item: item["bbox"][0]
            )

            reconstructed_lines.append({
                "y": min(
                    item["bbox"][1]
                    for item in line_words
                ),
                "x": min(
                    item["bbox"][0]
                    for item in line_words
                ),
                "text": " ".join(
                    item["text"]
                    for item in line_words
                ),
                "words": line_words,
            })

        reconstructed_lines.sort(
            key=lambda item: (
                item["y"],
                item["x"],
            )
        )

        entry_text = "\n".join(
            line["text"]
            for line in reconstructed_lines
        )

        # Step 6: Find the likely player name spatially.
        # Do not require matching PDF block or line identifiers.

        anchor_x = anchor["bbox"][0]
        anchor_y = anchor["y"]

        name_candidates = []

        for word in record_words:
            text = word.get("text", "").strip()
            bbox = word.get("bbox")

            if not text or not bbox or len(bbox) != 4:
                continue

            x0, y0, x1, y1 = map(float, bbox)
            word_center_y = (y0 + y1) / 2

            # Name text should be to the right of the number.
            if x0 <= anchor_x + 12:
                continue

            # Keep text reasonably close to the number vertically.
            if abs(word_center_y - anchor_y) > 30:
                continue

            # Ignore obvious numeric measurements.
            if re.fullmatch(r"[\d#./-]+", text):
                continue

            name_candidates.append({
                "text": text,
                "x": x0,
                "y": word_center_y,
                "bbox": [x0, y0, x1, y1],
            })

        # Sort spatially: top-to-bottom, then left-to-right.
        name_candidates.sort(
            key=lambda item: (
                round(item["y"], 1),
                item["x"],
            )
        )

        # Use the closest text row to the jersey number.
        name_candidate = ""

        if name_candidates:
            closest_y = min(
                name_candidates,
                key=lambda item: abs(
                    item["y"] - anchor_y
                ),
            )["y"]

            closest_row = [
                item for item in name_candidates
                if abs(item["y"] - closest_y) <= 3
            ]

            closest_row.sort(
                key=lambda item: item["x"]
            )

            name_candidate = " ".join(
                item["text"]
                for item in closest_row
            )

        records.append({
            "jersey_candidate": anchor["text"],
            "name_candidate": name_candidate,
            "entry_text": entry_text,
            "word_count": len(record_words),
            "bbox": [sx0, top, sx1, bottom],
        })

    return records



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



class SelectableGraphicsView(QGraphicsView):
    """Graphics view supporting optional rectangular selection."""

    region_selected = Signal(object)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)

        self.selection_mode = False
        self.selection_origin = None
        self.selection_rectangle = None

        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )

    def set_selection_mode(self, enabled):
        self.selection_mode = enabled

        if enabled:
            self.setDragMode(
                QGraphicsView.DragMode.NoDrag
            )
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(
                QGraphicsView.DragMode.ScrollHandDrag
            )
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if (
            self.selection_mode
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.selection_origin = self.mapToScene(
                event.position().toPoint()
            )

            if self.selection_rectangle:
                self.scene().removeItem(
                    self.selection_rectangle
                )
                self.selection_rectangle = None

            return

        super().mousePressEvent(event)


    def reset_selection(self):
        """Clear any active or previously drawn selection."""

        self.selection_origin = None
        self.selection_rectangle = None

    def mouseMoveEvent(self, event):
        if self.selection_mode and self.selection_origin:
            current_position = self.mapToScene(
                event.position().toPoint()
            )

            rectangle = QRectF(
                self.selection_origin,
                current_position,
            ).normalized()

            if self.selection_rectangle is None:
                self.selection_rectangle = self.scene().addRect(
                    rectangle,
                    QPen(QColor("#facc15"), 2),
                    QBrush(QColor(250, 204, 21, 35)),
                )
            else:
                self.selection_rectangle.setRect(rectangle)

            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self.selection_mode
            and event.button() == Qt.MouseButton.LeftButton
            and self.selection_origin is not None
        ):
            current_position = self.mapToScene(
                event.position().toPoint()
            )

            rectangle = QRectF(
                self.selection_origin,
                current_position,
            ).normalized()

            self.selection_origin = None

            if rectangle.width() > 3 and rectangle.height() > 3:
                self.region_selected.emit(rectangle)

            return

        super().mouseReleaseEvent(event)




class PDFVisualInspector(QDialog):
    """Display PDF pages, detected structures, and selected-region text."""

    RENDER_SCALE = 1.5

    OVERLAY_STYLES = {
        "tables": ("#16a34a", "Tables"),
        "containers": ("#2563eb", "Containers"),
        "separator_regions": ("#d97706", "Separator regions"),
        "text_regions": ("#9333ea", "Text regions"),
        "unassigned_text": ("#dc2626", "Unassigned text"),
    }

    def __init__(self, analysis_results, parent=None):
        super().__init__(parent)

        self.analysis_results = analysis_results
        self.current_path = None
        self.current_page_number = None

        # Original word-level extraction data for the current page.
        self.current_page_words = []

        # Structured information from the most recent selection.
        self.selected_region_data = None

        self.setWindowTitle("PDF Visual Inspector")
        self.resize(1250, 950)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --------------------------------------------------
        # DOCUMENT AND PAGE CONTROLS
        # --------------------------------------------------

        controls = QHBoxLayout()

        self.document_selector = QComboBox()

        for path, result in self.analysis_results.items():
            self.document_selector.addItem(
                result.get("file_name", Path(path).name),
                path,
            )

        self.page_selector = QSpinBox()
        self.page_selector.setMinimum(1)
        self.page_selector.setMaximum(1)

        controls.addWidget(QLabel("Document:"))
        controls.addWidget(self.document_selector, stretch=1)
        controls.addWidget(QLabel("Page:"))
        controls.addWidget(self.page_selector)

        # --------------------------------------------------
        # PDF VIEWER
        # --------------------------------------------------

        self.scene = QGraphicsScene(self)

        self.page_view = SelectableGraphicsView(self.scene)

        self.page_view.region_selected.connect(
            self.handle_region_selected
        )

        self.page_view.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        self.page_view.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )

        # --------------------------------------------------
        # REGION SELECTION
        # --------------------------------------------------

        self.select_region_button = QPushButton(
            "Select Region"
        )

        self.select_region_button.setCheckable(True)

        self.select_region_button.toggled.connect(
            self.page_view.set_selection_mode
        )

        controls.addWidget(self.select_region_button)

        layout.addLayout(controls)
        layout.addWidget(self.page_view, stretch=1)

        # --------------------------------------------------
        # DETECTION LEGEND
        # --------------------------------------------------

        self.legend_label = QLabel(
            "Green: Tables | Blue: Containers | "
            "Orange: Separator regions | "
            "Purple: Text regions | Red: Unassigned text"
        )

        layout.addWidget(self.legend_label)

        # --------------------------------------------------
        # REGION INFORMATION
        # --------------------------------------------------

        self.region_info_label = QLabel(
            "Select a region to extract its text."
        )

        layout.addWidget(self.region_info_label)

        self.region_text_output = QPlainTextEdit()
        self.region_text_output.setReadOnly(True)

        self.region_text_output.setPlaceholderText(
            "Extracted text from your selected PDF region "
            "will appear here."
        )

        self.region_text_output.setMaximumHeight(170)

        layout.addWidget(self.region_text_output)
        self.player_entries_table = QTableWidget()

        self.player_entries_table.setColumnCount(4)

        self.player_entries_table.setHorizontalHeaderLabels([
            "Jersey Candidate",
            "Name Candidate",
            "Entry Text",
            "Word Count",
            ])

        self.player_entries_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
            )

        self.player_entries_table.setWordWrap(True)

        self.player_entries_table.setMaximumHeight(230)

        layout.addWidget(self.player_entries_table)

        # --------------------------------------------------
        # SIGNALS
        # --------------------------------------------------

        self.document_selector.currentIndexChanged.connect(
            self.load_document
        )

        self.page_selector.valueChanged.connect(
            self.load_page
        )

        # --------------------------------------------------
        # INITIAL DOCUMENT
        # --------------------------------------------------

        if self.document_selector.count():
            self.load_document(0)

    def showEvent(self, event):
        """Fit the PDF after the dialog becomes visible."""

        super().showEvent(event)

        QTimer.singleShot(
            0,
            self.fit_page_to_view,
        )

    # ======================================================
    # PAGE DISPLAY
    # ======================================================

    def fit_page_to_view(self):
        """Fit the current PDF page inside the available viewport."""

        scene_rect = self.scene.sceneRect()

        if scene_rect.isNull() or scene_rect.isEmpty():
            return

        self.page_view.fitInView(
            scene_rect,
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def load_document(self, index):
        if index < 0:
            return

        path = self.document_selector.itemData(index)

        if not path:
            return

        result = self.analysis_results.get(path)

        if not result:
            return

        self.current_path = path

        page_count = result.get("page_count", 0)

        self.page_selector.blockSignals(True)

        self.page_selector.setRange(
            1,
            max(1, page_count),
        )

        self.page_selector.setValue(1)

        self.page_selector.blockSignals(False)

        self.load_page(1)

    def load_page(self, page_number):
        if not self.current_path:
            return

        result = self.analysis_results.get(
            self.current_path
        )

        if not result:
            return

        pages = result.get("pages", [])

        if not 1 <= page_number <= len(pages):
            return

        try:
            with pymupdf.open(self.current_path) as document:

                pdf_page = document[page_number - 1]

                # ------------------------------------------
                # RENDER PDF PAGE
                # ------------------------------------------

                pixmap = pdf_page.get_pixmap(
                    matrix=pymupdf.Matrix(
                        self.RENDER_SCALE,
                        self.RENDER_SCALE,
                    ),
                    alpha=False,
                )

                image = QPixmap()
                image.loadFromData(pixmap.tobytes("png"))

                if image.isNull():
                    raise RuntimeError(
                        "Could not render the selected PDF page."
                    )

                # ------------------------------------------
                # EXTRACT ORIGINAL WORD DATA
                # ------------------------------------------

                self.current_page_words = extract_page_words(
                    pdf_page
                )

                self.current_page_number = page_number

                # ------------------------------------------
                # RESET PREVIOUS SELECTION
                # ------------------------------------------

                self.page_view.reset_selection()

                self.select_region_button.setChecked(False)

                self.selected_region_data = None

                self.region_info_label.setText(
                    "Select a region to extract its text."
                )

                self.region_text_output.clear()
                self.player_entries_table.setRowCount(0)

                # ------------------------------------------
                # REBUILD SCENE
                # ------------------------------------------

                self.scene.clear()

                page_item = self.scene.addPixmap(image)

                # Convert rendered pixels back into PDF-point
                # coordinates so overlays match analyzer bboxes.

                page_item.setScale(
                    1.0 / self.RENDER_SCALE
                )

                self.draw_overlays(
                    pages[page_number - 1]
                )

                self.scene.setSceneRect(
                    page_item.sceneBoundingRect()
                )

                self.page_view.fitInView(
                    self.scene.sceneRect(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )

                self.legend_label.setText(
                    "Green: Tables | Blue: Containers | "
                    "Orange: Separator regions | "
                    "Purple: Text regions | Red: Unassigned text"
                )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Page Rendering Error",
                str(error),
            )

    # ======================================================
    # MANUAL REGION EXTRACTION
    # ======================================================

    def handle_region_selected(self, rectangle):
        """
        Extract all words intersecting the selected PDF region.

        Original word coordinates and extraction identifiers
        are preserved in selected_region_data.
        """

        selection_bbox = [
            rectangle.left(),
            rectangle.top(),
            rectangle.right(),
            rectangle.bottom(),
        ]

        selected_words = []

        sx0, sy0, sx1, sy1 = selection_bbox

        for word in self.current_page_words:

            bbox = word.get("bbox")

            if not bbox or len(bbox) != 4:
                continue

            try:
                x0, y0, x1, y1 = map(float, bbox)

            except (TypeError, ValueError):
                continue

            # Check whether the word and selection overlap.
            intersects = not (
                x1 <= sx0
                or x0 >= sx1
                or y1 <= sy0
                or y0 >= sy1
            )

            if intersects:
                selected_words.append(word)

        # ----------------------------------------------
        # GROUP WORDS INTO ORIGINAL TEXT LINES
        # ----------------------------------------------

        line_groups = {}

        for word in selected_words:

            line_key = (
                word["block_number"],
                word["line_number"],
            )

            line_groups.setdefault(
                line_key,
                [],
            ).append(word)

        reconstructed_lines = []

        for line_key, words in line_groups.items():

            # Preserve extraction order within each line.
            words.sort(
                key=lambda item: item["word_number"]
            )

            line_text = " ".join(
                word["text"]
                for word in words
            )

            line_y = min(
                word["bbox"][1]
                for word in words
            )

            line_x = min(
                word["bbox"][0]
                for word in words
            )

            reconstructed_lines.append({
                "block_number": line_key[0],
                "line_number": line_key[1],
                "text": line_text,
                "words": words,
                "y": line_y,
                "x": line_x,
            })

        # Put reconstructed lines into reading order.
        reconstructed_lines.sort(
            key=lambda item: (
                item["y"],
                item["x"],
            )
        )

        extracted_text = "\n".join(
            line["text"]
            for line in reconstructed_lines
        )

        # ----------------------------------------------
        # PRESERVE STRUCTURED SELECTION DATA
        # ----------------------------------------------

        self.selected_region_data = {
            "file_path": self.current_path,
            "page_number": self.current_page_number,

            "selection_bbox": selection_bbox,

            "word_count": len(selected_words),

            "line_count": len(reconstructed_lines),

            "text": extracted_text,

            "words": selected_words,

            "lines": reconstructed_lines,
        }

        # ----------------------------------------------
        # DISPLAY RESULTS
        # ----------------------------------------------

        self.region_info_label.setText(
            f"Page {self.current_page_number} | "
            f"Words extracted: {len(selected_words)} | "
            f"Lines reconstructed: {len(reconstructed_lines)} | "
            f"Region: X={sx0:.1f}, Y={sy0:.1f}, "
            f"Width={sx1 - sx0:.1f}, "
            f"Height={sy1 - sy0:.1f}"
        )

        if extracted_text:
            self.region_text_output.setPlainText(
                extracted_text
            )

        else:
            self.region_text_output.setPlainText(
                "No selectable text was found inside this region."
            )
                # Detect candidate player entries within this region.
        player_entries = detect_player_entries(
            selected_words,
            selection_bbox,
        )

        self.selected_region_data["player_entries"] = (
            player_entries
        )

        self.player_entries_table.setRowCount(
            len(player_entries)
        )

        for row, entry in enumerate(player_entries):

            values = [
                entry["jersey_candidate"],
                entry["name_candidate"],
                entry["entry_text"],
                str(entry["word_count"]),
            ]

            for column, value in enumerate(values):
                self.player_entries_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(value),
                )

        self.player_entries_table.resizeRowsToContents()

    # ======================================================
    # AUTOMATIC STRUCTURE OVERLAYS
    # ======================================================

    def draw_overlays(self, page_data):
        """Draw detected structures over the rendered PDF page."""

        for category, style in self.OVERLAY_STYLES.items():

            color_hex, _label = style

            items = page_data.get(category, [])

            for item in items:

                bbox = item.get("bbox")

                if not bbox or len(bbox) != 4:
                    continue

                try:
                    x0, y0, x1, y1 = map(float, bbox)

                except (TypeError, ValueError):
                    continue

                if x1 <= x0 or y1 <= y0:
                    continue

                color = QColor(color_hex)

                pen = QPen(color, 1.5)

                if category == "unassigned_text":
                    pen.setStyle(
                        Qt.PenStyle.DashLine
                    )

                brush = QBrush(
                    QColor(
                        color.red(),
                        color.green(),
                        color.blue(),
                        28,
                    )
                )

                rectangle = self.scene.addRect(
                    x0,
                    y0,
                    x1 - x0,
                    y1 - y0,
                    pen,
                    brush,
                )

                rectangle.setToolTip(
                    item.get("text", category)
                )





class PDFAnalysisTestWindow(QMainWindow):
    """Standalone interface for testing the universal PDF analyzer."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Universal PDF Analysis - Test Workspace")
        self.resize(1200, 800)

        self.worker = None
        self.analysis_summaries = []
        self.analysis_results = {}

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
        self.inspect_button = QPushButton(
    "Open Visual Inspector"
)

        self.inspect_button.setEnabled(False)

        self.inspect_button.clicked.connect(
            self.open_visual_inspector
            )

        control_layout.addWidget(self.inspect_button)

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
        self.analysis_results.clear()

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
        self.analysis_results[pdf_path] = result
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

    def open_visual_inspector(self):
        if not self.analysis_results:
            QMessageBox.information(
                self,
                "No Analysis Available",
                "Analyze at least one PDF before opening "
                "the visual inspector.",
            )
            return

        dialog = PDFVisualInspector(
            self.analysis_results,
            self,
    )

        dialog.exec()

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

        self.inspect_button.setEnabled(
            enabled and bool(self.analysis_results)
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
