
import copy
from dataclasses import fields

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from roster_import_parser import (
    parse_table_records,
    parse_inferred_headerless_records,
    interpret_compound_roster_cells,
    extract_compound_components,
)


STANDARD_FIELDS = {
    "jersey_number": "Jersey Number",
    "full_name": "Player Name",
    "position": "Position",
    "height": "Height",
    "weight": "Weight",
    "classification": "Class",
    "major": "Major",
    "hometown": "Hometown",
    "high_school": "High School",
    "previous_school": "Previous School",
    "transfer_status": "Transfer Status",
    "experience": "Experience",
    "social_links": "Social Links",
}

IGNORE_FIELD = "__ignore__"
CUSTOM_FIELD = "__custom__"

FIELD_OPTIONS = [
    ("Ignore Column", IGNORE_FIELD),
    ("Custom Field", CUSTOM_FIELD),
] + [
    (label, field)
    for field, label in STANDARD_FIELDS.items()
]


class RosterImportMappingDialog(QDialog):
    """
    Allows users to correct source-column mappings and preview
    rebuilt roster records without writing anything to the database.
    """

    def __init__(self, import_result, parent=None):
        super().__init__(parent)

        self.original_result = copy.deepcopy(import_result)
        self.import_result = None
        self.records = []

        self.pipeline_type = self.original_result.get(
            "pipeline_type"
        )

        self.rows = self.original_result.get("table_rows", [])
        self.header_result = self.original_result.get(
            "header_result"
        )

        self.mapping_widgets = {}

        self.setWindowTitle("Map Roster Import Columns")
        self.resize(1150, 750)

        self.build_ui()
        self.populate_mapping_table()
        self.rebuild_preview()

    def build_ui(self):
        layout = QVBoxLayout(self)

        heading = QLabel("Review and Correct Column Mappings")
        heading.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(heading)

        instructions = QLabel(
            "Review the source columns, inspect their sample values, "
            "and select where each column should be stored. "
            "Your original extracted data will remain unchanged."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.mapping_table = QTableWidget()
        self.mapping_table.setColumnCount(4)
        self.mapping_table.setHorizontalHeaderLabels([
            "Source Column",
            "Sample Values",
            "Suggested Mapping",
            "Destination",
        ])

        self.mapping_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.mapping_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.mapping_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.mapping_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.mapping_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.mapping_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )

        layout.addWidget(self.mapping_table)

        preview_heading = QLabel("Rebuilt Player Preview")
        preview_heading.setStyleSheet(
            "font-size: 16px; font-weight: bold;"
        )
        layout.addWidget(preview_heading)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.preview_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.preview_table)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )

        self.button_box.button(
            QDialogButtonBox.StandardButton.Apply
        ).setText("Apply Mappings")

        self.button_box.button(
            QDialogButtonBox.StandardButton.Apply
            ).clicked.connect(self.apply_mappings)

        self.button_box.rejected.connect(self.reject)

        layout.addWidget(self.button_box)

    def get_source_columns(self):
        """
        Returns source-column metadata:
        index, label, sample values, and original mapping.
        """

        if not self.rows:
            return []

        max_columns = max(len(row) for row in self.rows)

        if self.pipeline_type == "headered":
            headers = self.header_result.get("headers", [])
            header_index = self.header_result.get(
                "header_index", 0
            )

            original_mapping = self.original_result.get(
                "column_mapping", {}
            )

            columns = []

            for index in range(max_columns):
                if index < len(headers):
                    label = str(headers[index]).strip()
                    if not label:
                        label = f"Column {index + 1}"
                else:
                    label = f"Unlabeled Column {index + 1}"

                samples = []

                for row_index, row in enumerate(self.rows):
                    if row_index == header_index:
                        continue

                    if index < len(row):
                        value = str(row[index]).strip()
                        if value and value not in samples:
                            samples.append(value)

                    if len(samples) >= 4:
                        break

                columns.append({
                    "index": index,
                    "label": label,
                    "samples": samples,
                    "mapping": original_mapping.get(index),
                })

            return columns

        original_mapping = self.original_result.get(
            "analysis", {}
        ).get("mapping", {})

        columns = []

        for index in range(max_columns):
            samples = []

            for row in self.rows:
                if index < len(row):
                    value = str(row[index]).strip()
                    if value and value not in samples:
                        samples.append(value)

                if len(samples) >= 4:
                    break

            columns.append({
                "index": index,
                "label": f"Column {index + 1}",
                "samples": samples,
                "mapping": original_mapping.get(index),
            })

        return columns

    def get_mapping_description(self, mapping):
        if isinstance(mapping, dict):
            return mapping.get("custom_field", "Custom Field")

        if mapping:
            return STANDARD_FIELDS.get(
                mapping,
                str(mapping)
            )

        return "Unmapped"


    def populate_mapping_table(self):
        columns = self.get_source_columns()

        self.mapping_table.setRowCount(len(columns))

        for row_index, column in enumerate(columns):
            index = column["index"]
            mapping = column["mapping"]

        # Source column name
            source_item = QTableWidgetItem(column["label"])
            source_item.setData(
                Qt.ItemDataRole.UserRole,
                index
            )

        # Sample values
            sample_text = " | ".join(column["samples"])

        # Original suggested mapping
            suggested_item = QTableWidgetItem(
                self.get_mapping_description(mapping)
            )

            self.mapping_table.setItem(
                row_index, 0, source_item
            )
            self.mapping_table.setItem(
                row_index, 1,
                QTableWidgetItem(sample_text)
            )
            self.mapping_table.setItem(
                row_index, 2, suggested_item
            )

        # Destination dropdown
            combo = QComboBox()

            for label, value in FIELD_OPTIONS:
                combo.addItem(label, value)

            if isinstance(mapping, dict):
                selected_value = CUSTOM_FIELD
            elif mapping in STANDARD_FIELDS:
                selected_value = mapping
            else:
                selected_value = CUSTOM_FIELD

            combo_index = combo.findData(selected_value)

            if combo_index >= 0:
                combo.setCurrentIndex(combo_index)

        # Custom field name editor
            custom_name = QLineEdit()

            if isinstance(mapping, dict):
                custom_name.setText(
                    mapping.get("custom_field", "")
            )
            elif not mapping:
                custom_name.setText(column["label"])

            custom_name.setPlaceholderText(
                "Enter custom field name"
            )

            custom_name.setEnabled(
                selected_value == CUSTOM_FIELD
            )

        # Update preview when destination changes
            combo.currentIndexChanged.connect(
                self.rebuild_preview
            )

            combo.currentIndexChanged.connect(
                lambda _, c=combo, n=custom_name:
                n.setEnabled(c.currentData() == CUSTOM_FIELD)
            )

            custom_name.textChanged.connect(
                self.rebuild_preview
         )

        # Keep references to the actual widgets
            self.mapping_widgets[index] = {
                "combo": combo,
                "custom_name": custom_name,
            }

        # Put both controls inside one container
            from PySide6.QtWidgets import QWidget

            container = QVBoxLayout()
            container.setContentsMargins(4, 4, 4, 4)
            container.addWidget(combo)
            container.addWidget(custom_name)

            widget = QWidget()
            widget.setLayout(container)

        # Insert the container ONCE.
            self.mapping_table.setCellWidget(
                row_index, 3, widget
            )

            self.mapping_table.setRowHeight(
                row_index, 75
            )

    def get_updated_mapping(self):
        mapping = {}

        for column_index, widgets in self.mapping_widgets.items():
            combo = widgets["combo"]
            custom_name = widgets["custom_name"]

            selected = combo.currentData()

            if selected == IGNORE_FIELD:
                continue

            if selected == CUSTOM_FIELD:
                name = custom_name.text().strip()

                if not name:
                    name = f"Custom Column {column_index + 1}"

                mapping[column_index] = {
                    "custom_field": name
                }
            else:
                mapping[column_index] = selected

        return mapping

    def rebuild_preview(self):
        try:
            mapping = self.get_updated_mapping()

            if self.pipeline_type == "headered":
                records = parse_table_records(
                    self.rows,
                    self.header_result,
                    mapping,
                )

                print("\n--- HEADERED COMPOUND HEADER DEBUG ---")
                print("HEADER RESULT:", repr(self.header_result))
                print("MAPPING:", repr(mapping))
                print("FIRST SOURCE ROW:", repr(self.rows[0] if self.rows else None))
                print("FIRST PARSED RECORD:", repr(records[0] if records else None))
                print("--- END HEADER DEBUG ---\n")

            elif self.pipeline_type == "headerless":
                analysis = copy.deepcopy(
                    self.original_result.get("analysis") or {}
                )

                analysis["mapping"] = {
                    index: (
                        value["custom_field"]
                        if isinstance(value, dict)
                        else value
                    )
                    for index, value in mapping.items()
                }

                # Preserve original inference metadata.
                records = parse_inferred_headerless_records(
                    self.rows,
                    analysis,
                )

                records = interpret_compound_roster_cells(
                    self.rows,
                    records,
                    analysis,
                )

            else:
                records = []

            self.records = records
            self.component_candidates = extract_compound_components(
                rows=self.rows,
                records=self.records,
                column_mapping=mapping,
                header_result=self.header_result,
                pipeline_type=self.pipeline_type,
                )

            print("\n--- COMPONENT EXTRACTION TEST ---")
            print("Pipeline:", self.pipeline_type)
            print("Players:", len(self.records))
            print("Extracted components:", len(self.component_candidates))

            for component in self.component_candidates:
                if (
                    component["player_name"] == "Akram Elnagmi"
                    or component["record_index"] == 0
                    ):
                    print({
            "player": component["player_name"],
            "source_column": component["source_column_name"],
            "original_cell": component["original_cell_value"],
            "component": component["component_value"],
            "suggestion": component["suggested_field"],
            "reason": component["suggestion_reason"],
            "status": component["review_status"],
        })

            print("--- END COMPONENT EXTRACTION TEST ---\n")




            self.populate_preview_table()

            self.status_label.setText(
                f"Players detected: {len(records)}"
            )

        except Exception as error:
            self.records = []
            self.status_label.setText(
                f"Preview error: {error}"
            )


    def populate_preview_table(self):
        fields = [
        "jersey_number",
        "full_name",
        "position",
        "classification",
        "height",
        "weight",
        "hometown",
        "high_school",
        "previous_school",
        "major",
        "transfer_status",
        "experience",
        ]

    # Collect every custom field found in the rebuilt records.
        custom_fields = []

        for record in self.records:
            for field_name in record.get("custom_fields", {}):
                if field_name not in custom_fields:
                    custom_fields.append(field_name)

    # Combine standard and custom fields.
        all_fields = fields + custom_fields

        headers = [
            STANDARD_FIELDS.get(field, field)
            for field in all_fields
        ]

        self.preview_table.setColumnCount(len(all_fields))
        self.preview_table.setHorizontalHeaderLabels(headers)
        self.preview_table.setRowCount(len(self.records))

        for row_index, record in enumerate(self.records):
            for column_index, field in enumerate(all_fields):

                if field in fields:
                    value = record.get(field)
                else:
                    value = record.get(
                    "custom_fields", {}
                    ).get(field)

                if value is None:
                    value = ""

                self.preview_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(str(value))
             )

    def apply_mappings(self):
        print("\n--- MAPPING DIAGNOSTIC ---")
        print("UPDATED MAPPING:", self.get_updated_mapping())
        print("FIRST REBUILT RECORD:", self.records[0] if self.records else None)
        required_fields = [
            "jersey_number",
            "full_name",
            "position",
        ]

        missing = [
            field
            for field in required_fields
            if not any(record.get(field) for record in self.records)
        ]

        if missing:
            names = ", ".join(
                STANDARD_FIELDS[field]
                for field in missing
            )

            QMessageBox.warning(
                self,
                "Required Fields Missing",
                "The following required fields have no values:\n\n"
                + names
                + "\n\nCorrect the mappings before applying."
            )
            return

        self.import_result = copy.deepcopy(
            self.original_result
        )

        self.import_result["records"] = self.records
        self.import_result["column_mapping"] = (
            self.get_updated_mapping()
        )

        self.import_result["import_readiness"] = "needs_review"

        self.accept()
