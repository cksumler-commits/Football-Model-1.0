
import json
import sys
from pathlib import Path

import pymupdf

from PySide6.QtCore import Qt, QSize, QRectF, Signal, QThread
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdf_structure_analyzer import analyze_pdf_structure


# ============================================================
# ANALYSIS WORKER
# ============================================================

class PDFAnalysisWorker(QThread):
    """Run PDF structure analysis without blocking the interface."""

    result_ready = Signal(object)
    error_ready = Signal(str)

    def __init__(self, pdf_path):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self):
        try:
            result = analyze_pdf_structure(self.pdf_path)
            self.result_ready.emit(result)

        except Exception as error:
            self.error_ready.emit(str(error))


# ============================================================
# GEOMETRY HELPERS
# ============================================================

def get_bbox(value):
    """Read a bounding box from supported analyzer formats."""

    if not isinstance(value, dict):
        return None

    bbox = value.get("bbox")

    if isinstance(bbox, dict):
        if bbox.get("type") == "rectangle":
            bbox = bbox.get("coordinates")

    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None

    try:
        x0, y0, x1, y1 = [float(item) for item in bbox]
    except (TypeError, ValueError):
        return None

    if x1 <= x0 or y1 <= y0:
        return None

    return [x0, y0, x1, y1]


def bbox_area(bbox):
    if not bbox:
        return 0

    return max(0, bbox[2] - bbox[0]) * max(
        0, bbox[3] - bbox[1]
    )


def point_inside_bbox(x, y, bbox):
    if not bbox:
        return False

    return (
        bbox[0] <= x <= bbox[2]
        and bbox[1] <= y <= bbox[3]
    )


def get_boundary_coordinate(boundary, axis):
    """Extract one coordinate from a numeric or dictionary boundary."""

    if isinstance(boundary, (int, float)):
        return float(boundary)

    if not isinstance(boundary, dict):
        return None

    possible_keys = (
        ("y", "center_y", "top_y")
        if axis == "y"
        else ("x", "center_x", "left_x")
    )

    for key in possible_keys:
        value = boundary.get(key)

        if isinstance(value, (int, float)):
            return float(value)

    return None


def get_cell_bbox(table, row_index, column_index):
    """
    Retrieve actual cell geometry when available.

    Filled-cell tables retain their original rectangle geometry.
    Ruled tables may expose usable row and column boundaries.
    No equal-width cell positions are invented.
    """

    filled_rows = table.get("filled_rows", [])

    if row_index < len(filled_rows):
        rectangles = filled_rows[row_index].get(
            "rectangles", []
        )

        rectangles = sorted(
            rectangles,
            key=lambda rectangle: (
                get_bbox(rectangle) or [0, 0, 0, 0]
            )[0],
        )

        if column_index < len(rectangles):
            return get_bbox(rectangles[column_index])

    row_boundaries = table.get("row_boundaries", [])
    column_boundaries = table.get("column_boundaries", [])

    row_values = [
        get_boundary_coordinate(item, "y")
        for item in row_boundaries
    ]

    column_values = [
        get_boundary_coordinate(item, "x")
        for item in column_boundaries
    ]

    if (
        len(row_values) >= 2
        and len(column_values) >= 2
        and all(value is not None for value in row_values)
        and all(value is not None for value in column_values)
    ):
        row_values = sorted(set(row_values))
        column_values = sorted(set(column_values))

        if (
            row_index + 1 < len(row_values)
            and column_index + 1 < len(column_values)
        ):
            return [
                column_values[column_index],
                row_values[row_index],
                column_values[column_index + 1],
                row_values[row_index + 1],
            ]

    return None


# ============================================================
# PAGE OBJECT COLLECTION
# ============================================================

def collect_page_objects(page_data):
    """Build a common list of selectable page structures."""

    objects = []

    def add_object(
        object_type,
        label,
        data,
        bbox=None,
        parent_label=None,
    ):
        objects.append({
            "type": object_type,
            "label": label,
            "data": data,
            "bbox": bbox or get_bbox(data),
            "parent_label": parent_label,
        })

    # --------------------------------------------------------
    # TABLES AND CELLS
    # --------------------------------------------------------

    for table_index, table in enumerate(
        page_data.get("tables", [])
    ):
        table_label = (
            f"Table {table_index + 1} "
            f"({table.get('structure_type', 'unknown')})"
        )

        add_object(
            "table",
            table_label,
            table,
            get_bbox(table),
        )

        for row_index, row in enumerate(
            table.get("rows", [])
        ):
            for cell_index, cell in enumerate(
                row.get("cells", [])
            ):
                cell_bbox = get_cell_bbox(
                    table,
                    row_index,
                    cell_index,
                )

                cell_label = (
                    f"Row {row_index + 1}, "
                    f"Column {cell_index + 1}"
                )

                add_object(
                    "cell",
                    cell_label,
                    cell,
                    cell_bbox,
                    table_label,
                )

    # --------------------------------------------------------
    # OUTLINED CONTAINERS
    # --------------------------------------------------------

    for index, container in enumerate(
        page_data.get("containers", [])
    ):
        add_object(
            "container",
            f"Container {index + 1}",
            container,
        )

    # --------------------------------------------------------
    # SEPARATOR REGIONS
    # --------------------------------------------------------

    for index, region in enumerate(
        page_data.get("separator_regions", [])
    ):
        add_object(
            "separator",
            f"Separator region {index + 1}",
            region,
        )

    # --------------------------------------------------------
    # GENERIC TEXT REGIONS
    # --------------------------------------------------------

    for index, region in enumerate(
        page_data.get("text_regions", [])
    ):
        add_object(
            "text_region",
            f"Text region {index + 1}",
            region,
        )

    # --------------------------------------------------------
    # UNASSIGNED TEXT
    # --------------------------------------------------------

    for index, line in enumerate(
        page_data.get("unassigned_text", [])
    ):
        add_object(
            "unassigned",
            f"Unassigned line {index + 1}: "
            f"{line.get('text', '')[:55]}",
            line,
        )

    return objects


# ============================================================
# PDF PAGE CANVAS
# ============================================================

class PDFPageCanvas(QWidget):
    """Display the original PDF page with selectable overlays."""

    object_selected = Signal(object)

    def __init__(self):
        super().__init__()

        self.pixmap = QPixmap()
        self.page_width = 1
        self.page_height = 1

        self.objects = []
        self.selected_object = None

        self.show_tables = True
        self.show_cells = True
        self.show_containers = True
        self.show_regions = True
        self.show_unassigned = True

        self.setMinimumWidth(600)
        self.setMouseTracking(True)

    def sizeHint(self):
        if self.page_width <= 0:
            return QSize(900, 1100)

        ratio = self.page_height / self.page_width

        return QSize(900, int(900 * ratio))

    def set_page(self, pixmap, width, height, objects):
        self.pixmap = pixmap
        self.page_width = max(1, width)
        self.page_height = max(1, height)
        self.objects = objects
        self.selected_object = None

        self.updateGeometry()
        self.update()

    def set_selected_object(self, selected_object):
        self.selected_object = selected_object
        self.update()

    def set_overlay_options(
        self,
        tables,
        cells,
        containers,
        regions,
        unassigned,
    ):
        self.show_tables = tables
        self.show_cells = cells
        self.show_containers = containers
        self.show_regions = regions
        self.show_unassigned = unassigned

        self.update()

    def get_draw_rectangle(self):
        if self.pixmap.isNull():
            return QRectF()

        widget_width = self.width()
        widget_height = self.height()

        image_ratio = (
            self.pixmap.width() / self.pixmap.height()
        )

        available_ratio = widget_width / max(1, widget_height)

        if available_ratio > image_ratio:
            draw_height = widget_height
            draw_width = draw_height * image_ratio
        else:
            draw_width = widget_width
            draw_height = draw_width / image_ratio

        offset_x = (widget_width - draw_width) / 2
        offset_y = (widget_height - draw_height) / 2

        return QRectF(
            offset_x,
            offset_y,
            draw_width,
            draw_height,
        )

    def object_is_visible(self, obj):
        object_type = obj["type"]

        if object_type == "table":
            return self.show_tables

        if object_type == "cell":
            return self.show_cells

        if object_type == "container":
            return self.show_containers

        if object_type in {"separator", "text_region"}:
            return self.show_regions

        if object_type == "unassigned":
            return self.show_unassigned

        return False

    def get_object_color(self, object_type):
        colors = {
            "table": QColor(40, 130, 255),
            "cell": QColor(0, 190, 170),
            "container": QColor(180, 90, 230),
            "separator": QColor(230, 160, 30),
            "text_region": QColor(230, 190, 40),
            "unassigned": QColor(240, 65, 65),
        }

        return colors.get(
            object_type,
            QColor(255, 255, 255),
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(35, 35, 35))

        if self.pixmap.isNull():
            painter.end()
            return

        draw_rect = self.get_draw_rectangle()

        painter.drawPixmap(
            draw_rect.toRect(),
            self.pixmap,
        )

        scale_x = draw_rect.width() / self.page_width
        scale_y = draw_rect.height() / self.page_height

        for obj in self.objects:
            if not obj["bbox"]:
                continue

            if not self.object_is_visible(obj):
                continue

            bbox = obj["bbox"]

            x = draw_rect.x() + bbox[0] * scale_x
            y = draw_rect.y() + bbox[1] * scale_y
            width = (bbox[2] - bbox[0]) * scale_x
            height = (bbox[3] - bbox[1]) * scale_y

            rectangle = QRectF(x, y, width, height)

            is_selected = (
                self.selected_object is obj
            )

            color = self.get_object_color(obj["type"])

            if is_selected:
                pen = QPen(
                    QColor(255, 255, 255),
                    3,
                )
            else:
                pen = QPen(color, 1.5)

            painter.setPen(pen)

            fill_color = QColor(color)
            fill_color.setAlpha(
                45 if not is_selected else 75
            )

            painter.setBrush(fill_color)
            painter.drawRect(rectangle)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.pixmap.isNull():
            return

        draw_rect = self.get_draw_rectangle()

        if not draw_rect.contains(event.position()):
            return

        scale_x = self.page_width / draw_rect.width()
        scale_y = self.page_height / draw_rect.height()

        page_x = (
            event.position().x() - draw_rect.x()
        ) * scale_x

        page_y = (
            event.position().y() - draw_rect.y()
        ) * scale_y

        matching_objects = [
            obj
            for obj in self.objects
            if obj["bbox"]
            and self.object_is_visible(obj)
            and point_inside_bbox(
                page_x,
                page_y,
                obj["bbox"],
            )
        ]

        if not matching_objects:
            return

        # Prefer the smallest containing object.
        matching_objects.sort(
            key=lambda obj: bbox_area(obj["bbox"])
        )

        selected = matching_objects[0]

        self.set_selected_object(selected)
        self.object_selected.emit(selected)


# ============================================================
# MAIN INSPECTION WINDOW
# ============================================================

class PDFInspectionWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "PDF Structure Inspection"
        )

        self.resize(1500, 950)

        self.pdf_path = None
        self.pdf_document = None
        self.analysis_result = None
        self.worker = None

        self.current_page_index = 0
        self.current_objects = []

        self.build_interface()

    # --------------------------------------------------------
    # INTERFACE
    # --------------------------------------------------------

    def build_interface(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        # ----------------------------------------------------
        # FILE SELECTION
        # ----------------------------------------------------

        file_layout = QHBoxLayout()

        self.path_label = QLabel(
            "No PDF selected"
        )
        self.path_label.setWordWrap(True)

        self.browse_button = QPushButton(
            "Select PDF"
        )
        self.browse_button.clicked.connect(
            self.select_pdf
        )

        self.analyze_button = QPushButton(
            "Analyze PDF"
        )
        self.analyze_button.clicked.connect(
            self.start_analysis
        )
        self.analyze_button.setEnabled(False)

        file_layout.addWidget(self.path_label, 1)
        file_layout.addWidget(self.browse_button)
        file_layout.addWidget(self.analyze_button)

        main_layout.addLayout(file_layout)

        # ----------------------------------------------------
        # PAGE NAVIGATION
        # ----------------------------------------------------

        navigation_layout = QHBoxLayout()

        self.previous_button = QPushButton(
            "Previous Page"
        )
        self.previous_button.clicked.connect(
            self.previous_page
        )
        self.previous_button.setEnabled(False)

        self.page_label = QLabel(
            "Page: -"
        )

        self.next_button = QPushButton(
            "Next Page"
        )
        self.next_button.clicked.connect(
            self.next_page
        )
        self.next_button.setEnabled(False)

        navigation_layout.addWidget(
            self.previous_button
        )
        navigation_layout.addWidget(
            self.page_label
        )
        navigation_layout.addWidget(
            self.next_button
        )
        navigation_layout.addStretch()

        main_layout.addLayout(navigation_layout)

        # ----------------------------------------------------
        # OVERLAY FILTERS
        # ----------------------------------------------------

        overlay_layout = QHBoxLayout()

        self.table_checkbox = QCheckBox("Tables")
        self.table_checkbox.setChecked(True)

        self.cell_checkbox = QCheckBox("Cells")
        self.cell_checkbox.setChecked(True)

        self.container_checkbox = QCheckBox(
            "Containers"
        )
        self.container_checkbox.setChecked(True)

        self.region_checkbox = QCheckBox(
            "Text regions"
        )
        self.region_checkbox.setChecked(True)

        self.unassigned_checkbox = QCheckBox(
            "Unassigned text"
        )
        self.unassigned_checkbox.setChecked(True)

        for checkbox in (
            self.table_checkbox,
            self.cell_checkbox,
            self.container_checkbox,
            self.region_checkbox,
            self.unassigned_checkbox,
        ):
            checkbox.stateChanged.connect(
                self.update_overlay_options
            )
            overlay_layout.addWidget(checkbox)

        overlay_layout.addStretch()
        main_layout.addLayout(overlay_layout)

        # ----------------------------------------------------
        # MAIN SPLITTER
        # ----------------------------------------------------

        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        # Original PDF page viewer.
        self.canvas = PDFPageCanvas()
        self.canvas.object_selected.connect(
            self.handle_canvas_selection
        )

        self.page_scroll = QScrollArea()
        self.page_scroll.setWidget(self.canvas)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        splitter.addWidget(self.page_scroll)

        # ----------------------------------------------------
        # RIGHT SIDE: STRUCTURE AND DETAILS
        # ----------------------------------------------------

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.structure_tree = QTreeWidget()
        self.structure_tree.setHeaderLabel(
            "Detected Page Structures"
        )
        self.structure_tree.itemClicked.connect(
            self.handle_tree_selection
        )

        right_layout.addWidget(
            self.structure_tree,
            3,
        )

        self.details_label = QLabel(
            "Select a structure to inspect its details."
        )

        self.details_label.setWordWrap(True)
        right_layout.addWidget(self.details_label)

        self.details_text = QPlainTextEdit()
        self.details_text.setReadOnly(True)

        right_layout.addWidget(
            self.details_text,
            2,
        )

        splitter.addWidget(right_panel)

        splitter.setSizes([950, 500])

        main_layout.addWidget(splitter, 1)

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        self.status_label = QLabel(
            "Select a PDF to begin."
        )

        main_layout.addWidget(self.status_label)

    # --------------------------------------------------------
    # PDF SELECTION
    # --------------------------------------------------------

    def select_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PDF",
            "",
            "PDF Files (*.pdf)",
        )

        if not path:
            return

        self.pdf_path = Path(path)

        self.path_label.setText(
            str(self.pdf_path)
        )

        self.analyze_button.setEnabled(True)

        self.status_label.setText(
            "PDF selected. Ready to analyze."
        )

    # --------------------------------------------------------
    # ANALYSIS
    # --------------------------------------------------------

    def start_analysis(self):
        if not self.pdf_path:
            return

        if self.worker and self.worker.isRunning():
            return

        self.analyze_button.setEnabled(False)
        self.browse_button.setEnabled(False)

        self.status_label.setText(
            "Analyzing PDF. Please wait..."
        )

        self.worker = PDFAnalysisWorker(
            self.pdf_path
        )

        self.worker.result_ready.connect(
            self.analysis_finished
        )

        self.worker.error_ready.connect(
            self.analysis_failed
        )

        self.worker.start()

    def analysis_finished(self, result):
        self.analysis_result = result

        try:
            if self.pdf_document is not None:
                self.pdf_document.close()

            self.pdf_document = pymupdf.open(
                str(self.pdf_path)
            )

        except Exception as error:
            self.analysis_failed(
                f"Could not open PDF for rendering: {error}"
            )
            return

        self.current_page_index = 0

        self.analyze_button.setEnabled(True)
        self.browse_button.setEnabled(True)

        self.load_current_page()

        self.status_label.setText(
            f"Analysis complete: "
            f"{result.get('page_count', 0)} pages. "
            f"Navigate pages and select structures to inspect."
        )

    def analysis_failed(self, message):
        self.analyze_button.setEnabled(True)
        self.browse_button.setEnabled(True)

        self.status_label.setText(
            "Analysis failed."
        )

        QMessageBox.critical(
            self,
            "PDF Analysis Error",
            message,
        )

    # --------------------------------------------------------
    # PAGE NAVIGATION
    # --------------------------------------------------------

    def previous_page(self):
        if self.current_page_index <= 0:
            return

        self.current_page_index -= 1
        self.load_current_page()

    def next_page(self):
        if not self.analysis_result:
            return

        page_count = len(
            self.analysis_result.get("pages", [])
        )

        if self.current_page_index >= page_count - 1:
            return

        self.current_page_index += 1
        self.load_current_page()

    # --------------------------------------------------------
    # LOAD PAGE
    # --------------------------------------------------------

    def load_current_page(self):
        if not self.analysis_result or not self.pdf_document:
            return

        pages = self.analysis_result.get("pages", [])

        if not pages:
            return

        page_data = pages[self.current_page_index]

        original_page = self.pdf_document.load_page(
            self.current_page_index
        )

        # Render the original PDF page.
        matrix = pymupdf.Matrix(1.5, 1.5)

        pix = original_page.get_pixmap(
            matrix=matrix,
            alpha=False,
        )

        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()

        page_pixmap = QPixmap.fromImage(image)

        page_width = original_page.rect.width
        page_height = original_page.rect.height

        self.current_objects = collect_page_objects(
            page_data
        )

        self.canvas.set_page(
            page_pixmap,
            page_width,
            page_height,
            self.current_objects,
        )

        self.populate_structure_tree()

        page_number = self.current_page_index + 1
        page_count = len(pages)

        self.page_label.setText(
            f"Page {page_number} of {page_count}"
        )

        self.previous_button.setEnabled(
            self.current_page_index > 0
        )

        self.next_button.setEnabled(
            self.current_page_index < page_count - 1
        )

        self.details_label.setText(
            "Select a structure to inspect its details."
        )

        self.details_text.clear()

        self.update_overlay_options()

        self.page_scroll.verticalScrollBar().setValue(0)
        self.page_scroll.horizontalScrollBar().setValue(0)

    # --------------------------------------------------------
    # STRUCTURE TREE
    # --------------------------------------------------------

    def populate_structure_tree(self):
        self.structure_tree.clear()

        categories = {
            "table": self.structure_tree.invisibleRootItem(),
            "container": self.structure_tree.invisibleRootItem(),
            "separator": self.structure_tree.invisibleRootItem(),
            "text_region": self.structure_tree.invisibleRootItem(),
            "unassigned": self.structure_tree.invisibleRootItem(),
        }

        category_items = {}

        category_names = {
            "table": "Tables and Cells",
            "container": "Outlined Containers",
            "separator": "Separator Regions",
            "text_region": "Generic Text Regions",
            "unassigned": "Unassigned Text",
        }

        for category, name in category_names.items():
            item = QTreeWidgetItem([name])
            self.structure_tree.addTopLevelItem(item)
            category_items[category] = item

        table_items = {}

        for obj in self.current_objects:
            object_type = obj["type"]

            if object_type == "cell":
                parent_label = obj["parent_label"]

                parent_item = table_items.get(
                    parent_label
                )

                if parent_item is None:
                    continue

                item = QTreeWidgetItem([
                    obj["label"]
                ])

                item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    obj,
                )

                parent_item.addChild(item)
                continue

            item = QTreeWidgetItem([
                obj["label"]
            ])

            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                obj,
            )

            category_items[object_type].addChild(item)

            if object_type == "table":
                table_items[obj["label"]] = item

        for category_item in category_items.values():
            category_item.setExpanded(True)

        self.structure_tree.expandAll()

    # --------------------------------------------------------
    # SELECTION
    # --------------------------------------------------------

    def handle_tree_selection(self, item, column):
        obj = item.data(
            0,
            Qt.ItemDataRole.UserRole,
        )

        if not obj:
            return

        self.select_object(obj)

    def handle_canvas_selection(self, obj):
        self.select_object(obj)

    def select_object(self, obj):
        self.canvas.set_selected_object(obj)

        data = obj.get("data", {})

        self.details_label.setText(
            f"Selected: {obj['type']} — {obj['label']}"
        )

        details = {
            "type": obj["type"],
            "label": obj["label"],
            "bounding_box": obj.get("bbox"),
            "data": data,
        }

        self.details_text.setPlainText(
            json.dumps(
                details,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )

    # --------------------------------------------------------
    # OVERLAY FILTERS
    # --------------------------------------------------------

    def update_overlay_options(self):
        self.canvas.set_overlay_options(
            self.table_checkbox.isChecked(),
            self.cell_checkbox.isChecked(),
            self.container_checkbox.isChecked(),
            self.region_checkbox.isChecked(),
            self.unassigned_checkbox.isChecked(),
        )

    # --------------------------------------------------------
    # SHUTDOWN
    # --------------------------------------------------------

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(
                self,
                "Analysis Running",
                "Wait for PDF analysis to finish before closing.",
            )

            event.ignore()
            return

        if self.pdf_document is not None:
            self.pdf_document.close()

        event.accept()


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

def main():
    app = QApplication(sys.argv)

    window = PDFInspectionWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
