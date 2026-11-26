
import sys
import traceback
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from roster_import_parser import parse_roster_clipboard


class EditableRosterTable(QTableWidget):
    """
    Roster preview table with basic spreadsheet-style keyboard actions.

    Supports:
    - Double-click / type to edit a cell.
    - Ctrl+C to copy a cell.
    - Ctrl+X to cut a cell.
    - Ctrl+V to paste into a cell.
    - Delete / Backspace to clear a cell.

    This intentionally operates on one selected cell at a time.
    """

    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self.cut_source = None

    def keyPressEvent(self, event):
        current = self.currentItem()

        if current is None:
            super().keyPressEvent(event)
            return

        row = current.row()
        column = current.column()

        if event.matches(QKeySequence.StandardKey.Copy):
            QApplication.clipboard().setText(current.text())
            self.cut_source = None
            event.accept()
            return

        if event.matches(QKeySequence.StandardKey.Cut):
            QApplication.clipboard().setText(current.text())
            self.cut_source = (row, column)
            event.accept()
            return

        if event.matches(QKeySequence.StandardKey.Paste):
            pasted_text = QApplication.clipboard().text()

            source = self.cut_source
            self.cut_source = None

            # Clear the original cell when this is an internal cut/paste.
            if source is not None and source != (row, column):
                source_row, source_column = source
                source_item = self.item(source_row, source_column)

                if source_item is not None:
                    source_item.setText("")

            current.setText(pasted_text)
            self.setCurrentCell(row, column)
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            current.setText("")
            self.cut_source = None
            event.accept()
            return

        super().keyPressEvent(event)


class RosterImportDialog(QDialog):

    STANDARD_FIELDS = {
        "Jersey Number": "jersey_number",
        "Full Name": "full_name",
        "Position": "position",
        "Height": "height",
        "Weight": "weight",
        "Classification": "classification",
        "Hometown": "hometown",
        "High School": "high_school",
        "Previous School": "previous_school",
        "Major": "major",
        "Transfer Status": "transfer_status",
        "Experience": "experience",
        "Social Links": "social_links",
    }

    PREVIEW_COLUMNS = [
        ("Jersey", "jersey_number"),
        ("Name", "full_name"),
        ("Position", "position"),
        ("Class", "classification"),
        ("Height", "height"),
        ("Weight", "weight"),
        ("Hometown", "hometown"),
        ("High School", "high_school"),
        ("Previous School", "previous_school"),
        ("Major", "major"),
        ("Transfer Status", "transfer_status"),
        ("Experience", "experience"),
        ("Social Links", "social_links"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Load Roster Data")
        self.resize(1350, 850)

        self.import_result = None
        self.base_records = []
        self.records = []

        # User's column-level mapping decisions.
        self.column_mapping_overrides = {}
        self.mapping_controls = {}

        # Individual cell corrections.
        # Key: (record_index, field_name)
        # Value: manually entered text, including "" for a cleared cell.
        self.cell_edits = {}

        # Prevent itemChanged from treating table population as user edits.
        self._updating_player_table = False

        # Maps visible preview columns to their underlying record fields.
        self.player_table_columns = []

        self.build_ui()
        self.showMaximized()

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        title = QLabel("Load Roster Data")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        main_layout.addWidget(title)

        description = QLabel(
            "Copy a roster from a supported source, then load "
            "the clipboard to extract and preview its player data."
        )
        description.setWordWrap(True)
        main_layout.addWidget(description)

        control_layout = QHBoxLayout()

        self.load_clipboard_button = QPushButton("Read Clipboard")
        self.load_clipboard_button.clicked.connect(self.load_clipboard)
        control_layout.addWidget(self.load_clipboard_button)

        self.clear_button = QPushButton("Clear Preview")
        self.clear_button.clicked.connect(self.clear_preview)
        control_layout.addWidget(self.clear_button)

        control_layout.addStretch()

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        control_layout.addWidget(self.close_button)

        main_layout.addLayout(control_layout)

        summary_title = QLabel("Import Summary")
        summary_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        main_layout.addWidget(summary_title)

        self.summary_label = QLabel("No roster data loaded.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "padding: 8px;"
            "background-color: #eeeeee;"
            "border-radius: 4px;"
        )
        main_layout.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ------------------------------
        # Column Mapping
        # ------------------------------

        mapping_widget = QWidget()
        mapping_layout = QVBoxLayout(mapping_widget)
        mapping_layout.setContentsMargins(0, 0, 0, 0)

        mapping_title = QLabel("Column Mapping & Review")
        mapping_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        mapping_layout.addWidget(mapping_title)

        mapping_description = QLabel(
            "Choose what each source column represents. "
            "Assign standard fields, create custom fields, "
            "ignore columns, or leave them unresolved."
        )
        mapping_description.setWordWrap(True)
        mapping_layout.addWidget(mapping_description)

        self.mapping_table = QTableWidget()
        self.mapping_table.setColumnCount(4)
        self.mapping_table.setHorizontalHeaderLabels([
            "Source Column",
            "Sample Values",
            "Current Assignment",
            "Your Assignment",
        ])

        self.mapping_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        mapping_header = self.mapping_table.horizontalHeader()
        mapping_header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        mapping_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        mapping_header.setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        mapping_header.setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )

        mapping_layout.addWidget(self.mapping_table)

        self.mapping_status_label = QLabel(
            "No user mapping decisions yet."
        )
        mapping_layout.addWidget(self.mapping_status_label)

        splitter.addWidget(mapping_widget)

        # ------------------------------
        # Player Preview
        # ------------------------------

        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        preview_title = QLabel("Extracted Players")
        preview_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        preview_layout.addWidget(preview_title)

        preview_instructions = QLabel(
            "Edit individual cells by double-clicking them. "
            "You can also use Ctrl+C, Ctrl+X, Ctrl+V, and Delete "
            "to copy, move, paste, or clear a cell."
        )
        preview_instructions.setWordWrap(True)
        preview_layout.addWidget(preview_instructions)

        self.player_table = EditableRosterTable(0, 9)
        self.player_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self.player_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.player_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.player_table.setAlternatingRowColors(True)

        self.player_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.player_table.horizontalHeader().setStretchLastSection(True)

        self.player_table.itemChanged.connect(
            self.handle_player_cell_changed
        )

        preview_layout.addWidget(self.player_table)

        splitter.addWidget(preview_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([350, 500])

        main_layout.addWidget(splitter, 1)

        # ------------------------------
        # Parsing Details
        # ------------------------------

        details_title = QLabel("Parsing Details")
        details_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        main_layout.addWidget(details_title)

        self.details_label = QLabel("Waiting for clipboard data.")
        self.details_label.setWordWrap(True)
        self.details_label.setMaximumHeight(65)
        self.details_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        main_layout.addWidget(self.details_label)

    # --------------------------------------------------
    # Clipboard Loading
    # --------------------------------------------------

    def load_clipboard(self):
        self.load_clipboard_button.setEnabled(False)
        self.load_clipboard_button.setText("Reading Clipboard...")

        try:
            result = parse_roster_clipboard()

            self.import_result = result
            self.base_records = deepcopy(result.get("records", []))
            self.records = deepcopy(self.base_records)

            self.column_mapping_overrides = {}
            self.mapping_controls = {}
            self.cell_edits = {}

            self.populate_mapping_table()
            self.apply_column_mapping_overrides()
            self.update_summary()
            self.update_parsing_details()

        except Exception as error:
            traceback.print_exc()

            QMessageBox.critical(
                self,
                "Clipboard Import Error",
                f"Unable to read roster data:\n\n{error}",
            )

        finally:
            self.load_clipboard_button.setEnabled(True)
            self.load_clipboard_button.setText("Read Clipboard")

    # --------------------------------------------------
    # Column Discovery Helpers
    # --------------------------------------------------

    def get_parser_mapping(self):
        if not self.import_result:
            return {}

        analysis = self.import_result.get("analysis") or {}

        return (
            self.import_result.get("column_mapping")
            or analysis.get("mapping")
            or {}
        )

    def get_column_aliases(self, column_index):
        column_number = column_index + 1

        return {
            f"Unresolved Column {column_number}",
            f"custom_{column_number}",
            f"custom_column_{column_number}",
        }

    def get_record_column_value(self, record, column_index, raw_row=None):
        """
        Retrieve a value associated with a source column.

        The original raw row is preferred. If unavailable, check the
        unresolved/custom aliases retained by the parser.
        """

        if isinstance(raw_row, (list, tuple)):
            if column_index < len(raw_row):
                value = raw_row[column_index]

                if value is not None and str(value).strip():
                    return value

        custom_fields = record.get("custom_fields") or {}

        for alias in self.get_column_aliases(column_index):
            value = custom_fields.get(alias)

            if value is not None and str(value).strip():
                return value

        return None

    def discover_column_count(self):
        raw_rows = self.import_result.get("table_rows") or []

        column_count = max(
            (
                len(row)
                for row in raw_rows
                if isinstance(row, (list, tuple))
            ),
            default=0,
        )

        for record in self.base_records:
            custom_fields = record.get("custom_fields") or {}

            for key in custom_fields:
                key_text = str(key).strip()
                column_number = None

                prefixes = (
                    "Unresolved Column ",
                    "custom_column_",
                    "custom_",
                )

                for prefix in prefixes:
                    if key_text.startswith(prefix):
                        suffix = key_text[len(prefix):]

                        try:
                            column_number = int(suffix)
                        except ValueError:
                            column_number = None

                        break

                if column_number and column_number > 0:
                    column_count = max(column_count, column_number)

        return column_count

    # --------------------------------------------------
    # Mapping Helpers
    # --------------------------------------------------

    def normalize_assignment(self, assignment):
        """Convert parser mapping formats into a simple field name."""

        if isinstance(assignment, dict):
            assignment = (
                assignment.get("field")
                or assignment.get("standard_field")
                or assignment.get("custom_field")
                or assignment.get("field_name")
                or assignment.get("name")
            )

        if assignment is None:
            return None

        return str(assignment).strip() or None

    def get_parser_assignment(self, column_index):
        parser_mapping = self.get_parser_mapping()

        assignment = parser_mapping.get(
            column_index,
            parser_mapping.get(str(column_index)),
        )

        return self.normalize_assignment(assignment)

    def get_decision_fields(self, decision):
        """
        Return the record fields affected by a mapping decision.

        Standard mappings affect their standard field.
        Custom mappings affect their named custom field.
        """

        if not decision:
            return set()

        decision_type = decision.get("type")

        if decision_type == "standard":
            field_name = decision.get("field")
            return {field_name} if field_name else set()

        if decision_type == "custom":
            field_name = decision.get("field_name", "").strip()
            return {field_name} if field_name else set()

        return set()

    def get_column_affected_fields(self, column_index, new_decision=None):
        """
        Determine which fields could be changed by remapping a column.

        Includes the parser's original assignment, the user's previous
        assignment, unresolved aliases, and the proposed new assignment.
        """

        fields = set()

        parser_assignment = self.get_parser_assignment(column_index)

        if parser_assignment:
            fields.add(parser_assignment)

        old_decision = self.column_mapping_overrides.get(column_index)
        fields.update(self.get_decision_fields(old_decision))

        if new_decision:
            fields.update(self.get_decision_fields(new_decision))

        fields.update(self.get_column_aliases(column_index))

        return fields

    def find_conflicting_cell_edits(self, affected_fields):
        """Find manual cell edits that overlap the affected fields."""

        conflicts = []

        for edit_key, value in self.cell_edits.items():
            record_index, field_name = edit_key

            if field_name in affected_fields:
                conflicts.append((edit_key, value))

        return conflicts

    def confirm_mapping_change(self, column_index, new_decision):
        """
        Warn before a mapping change can affect manually edited fields.

        Returns:
            True  -> apply the mapping change
            False -> do not apply the mapping change
        """

        affected_fields = self.get_column_affected_fields(
            column_index,
            new_decision,
        )

        conflicts = self.find_conflicting_cell_edits(affected_fields)

        if not conflicts:
            return True

        column_label = f"Column {column_index + 1}"

        field_names = sorted({
            field_name
            for (record_index, field_name), value in conflicts
        })

        examples = []

        for (record_index, field_name), value in conflicts[:5]:
            player_name = "Unknown player"

            if 0 <= record_index < len(self.records):
                player_name = (
                    self.records[record_index].get("full_name")
                    or player_name
                )

            shown_value = value if value else "(cleared)"

            examples.append(
                f"{player_name} — {field_name}: {shown_value}"
            )

        message = (
            f"You have manually edited {len(conflicts)} cell(s) "
            f"in fields that may be affected by changing {column_label}.\n\n"
            f"Affected fields: {', '.join(field_names)}\n\n"
            f"Examples:\n"
            + "\n".join(examples)
            + "\n\nWhat would you like to do?"
        )

        box = QMessageBox(self)
        box.setWindowTitle("Manual Edits Detected")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(message)

        keep_button = box.addButton(
            "Keep Edits — Skip This Column",
            QMessageBox.ButtonRole.RejectRole,
        )

        update_button = box.addButton(
            "Update Mapping — Discard Conflicting Edits",
            QMessageBox.ButtonRole.DestructiveRole,
        )

        cancel_button = box.addButton(
            "Cancel",
            QMessageBox.ButtonRole.NoRole,
        )

        box.setDefaultButton(keep_button)
        box.exec()

        clicked = box.clickedButton()

        if clicked == update_button:
            # Remove only corrections that overlap the fields this
            # particular column mapping can affect.
            for edit_key, value in conflicts:
                self.cell_edits.pop(edit_key, None)

            return True

        # Keep Edits and Cancel both prevent this mapping change.
        return False

    # --------------------------------------------------
    # Column Mapping Table
    # --------------------------------------------------

    def populate_mapping_table(self):
        self.mapping_table.setRowCount(0)
        self.mapping_controls = {}

        if not self.import_result:
            return

        raw_rows = self.import_result.get("table_rows") or []
        parser_mapping = self.get_parser_mapping()

        header_result = self.import_result.get("header_result") or {}
        headers = header_result.get("headers") or []

        column_count = self.discover_column_count()

        field_options = [
            "Leave Unresolved",
            *self.STANDARD_FIELDS.keys(),
            "Custom Field",
            "Ignore Column",
        ]

        for column_index in range(column_count):
            source_name = ""

            if column_index < len(headers):
                source_name = str(headers[column_index]).strip()

            if not source_name:
                source_name = f"Column {column_index + 1}"

            # Gather sample values from raw rows and extracted records.
            samples = []
            seen = set()

            for raw_row in raw_rows:
                if not isinstance(raw_row, (list, tuple)):
                    continue

                if column_index >= len(raw_row):
                    continue

                value = raw_row[column_index]

                if value is None:
                    continue

                value = str(value).strip()

                if value and value not in seen:
                    samples.append(value)
                    seen.add(value)

                if len(samples) >= 3:
                    break

            if len(samples) < 3:
                for record in self.base_records:
                    value = self.get_record_column_value(
                        record,
                        column_index,
                    )

                    if value is None:
                        continue

                    value = str(value).strip()

                    if value and value not in seen:
                        samples.append(value)
                        seen.add(value)

                    if len(samples) >= 3:
                        break

            sample_text = (
                " | ".join(samples)
                if samples
                else "(No values found)"
            )

            parser_assignment = parser_mapping.get(
                column_index,
                parser_mapping.get(str(column_index)),
            )
            parser_assignment = self.normalize_assignment(
                parser_assignment
            )

            current_assignment = (
                parser_assignment or "Unresolved"
            )

            row_index = self.mapping_table.rowCount()
            self.mapping_table.insertRow(row_index)

            self.mapping_table.setItem(
                row_index,
                0,
                QTableWidgetItem(source_name),
            )
            self.mapping_table.setItem(
                row_index,
                1,
                QTableWidgetItem(sample_text),
            )
            self.mapping_table.setItem(
                row_index,
                2,
                QTableWidgetItem(current_assignment),
            )

            assignment_combo = QComboBox()
            assignment_combo.addItems(field_options)

            custom_input = QLineEdit()
            custom_input.setPlaceholderText("Enter custom field name")

            existing_override = self.column_mapping_overrides.get(
                column_index
            )

            if existing_override:
                override_type = existing_override.get("type")

                if override_type == "standard":
                    field_name = existing_override.get("field")

                    display_name = next(
                        (
                            label
                            for label, value in self.STANDARD_FIELDS.items()
                            if value == field_name
                        ),
                        "Leave Unresolved",
                    )

                    assignment_combo.setCurrentText(display_name)

                elif override_type == "custom":
                    assignment_combo.setCurrentText("Custom Field")
                    custom_input.setText(
                        existing_override.get("field_name", "")
                    )

                elif override_type == "ignore":
                    assignment_combo.setCurrentText("Ignore Column")

            else:
                display_name = next(
                    (
                        label
                        for label, value in self.STANDARD_FIELDS.items()
                        if value == parser_assignment
                    ),
                    None,
                )

                if display_name:
                    assignment_combo.setCurrentText(display_name)

            custom_input.setEnabled(
                assignment_combo.currentText() == "Custom Field"
            )

            # Connect only after initial widget values are established.
            assignment_combo.currentIndexChanged.connect(
                lambda _, index=column_index,
                combo=assignment_combo,
                custom=custom_input:
                    self.handle_column_mapping_change(
                        index,
                        combo,
                        custom,
                    )
            )

            custom_input.editingFinished.connect(
                lambda index=column_index,
                combo=assignment_combo,
                custom=custom_input:
                    self.handle_custom_field_change(
                        index,
                        combo,
                        custom.text(),
                    )
            )

            assignment_widget = QWidget()
            assignment_layout = QVBoxLayout(assignment_widget)
            assignment_layout.setContentsMargins(4, 4, 4, 4)
            assignment_layout.addWidget(assignment_combo)
            assignment_layout.addWidget(custom_input)

            self.mapping_table.setCellWidget(
                row_index,
                3,
                assignment_widget,
            )

            self.mapping_controls[column_index] = {
                "combo": assignment_combo,
                "custom_input": custom_input,
            }

        self.mapping_table.resizeRowsToContents()
        self.update_mapping_status()

    # --------------------------------------------------
    # Mapping Handlers
    # --------------------------------------------------

    def get_decision_from_selection(self, selection, custom_text=""):
        if selection in self.STANDARD_FIELDS:
            return {
                "type": "standard",
                "field": self.STANDARD_FIELDS[selection],
            }

        if selection == "Custom Field":
            field_name = custom_text.strip()

            if field_name:
                return {
                    "type": "custom",
                    "field_name": field_name,
                }

            return None

        if selection == "Ignore Column":
            return {"type": "ignore"}

        return None

    def restore_mapping_control(self, column_index):
        """Restore the visible controls to the last accepted mapping."""

        controls = self.mapping_controls.get(column_index)

        if not controls:
            return

        combo = controls["combo"]
        custom_input = controls["custom_input"]

        previous = self.column_mapping_overrides.get(column_index)

        if previous is None:
            parser_assignment = self.get_parser_assignment(column_index)

            display_name = next(
                (
                    label
                    for label, value in self.STANDARD_FIELDS.items()
                    if value == parser_assignment
                ),
                "Leave Unresolved",
            )

            combo.blockSignals(True)
            combo.setCurrentText(display_name)
            combo.blockSignals(False)

            custom_input.blockSignals(True)
            custom_input.clear()
            custom_input.blockSignals(False)

        elif previous.get("type") == "standard":
            field_name = previous.get("field")

            display_name = next(
                (
                    label
                    for label, value in self.STANDARD_FIELDS.items()
                    if value == field_name
                ),
                "Leave Unresolved",
            )

            combo.blockSignals(True)
            combo.setCurrentText(display_name)
            combo.blockSignals(False)

        elif previous.get("type") == "custom":
            combo.blockSignals(True)
            combo.setCurrentText("Custom Field")
            combo.blockSignals(False)

            custom_input.blockSignals(True)
            custom_input.setText(previous.get("field_name", ""))
            custom_input.blockSignals(False)

        elif previous.get("type") == "ignore":
            combo.blockSignals(True)
            combo.setCurrentText("Ignore Column")
            combo.blockSignals(False)

        custom_input.setEnabled(
            combo.currentText() == "Custom Field"
        )

    def handle_column_mapping_change(
        self,
        column_index,
        combo,
        custom_input,
    ):
        selection = combo.currentText()

        custom_input.setEnabled(selection == "Custom Field")

        new_decision = self.get_decision_from_selection(
            selection,
            custom_input.text(),
        )

        if selection == "Custom Field" and new_decision is None:
            # The user has selected Custom Field but has not named it yet.
            return

        if not self.confirm_mapping_change(
            column_index,
            new_decision,
        ):
            self.restore_mapping_control(column_index)
            return

        if new_decision is None:
            self.column_mapping_overrides.pop(column_index, None)
        else:
            self.column_mapping_overrides[column_index] = new_decision

        self.apply_column_mapping_overrides()
        self.update_mapping_status()

    def handle_custom_field_change(
        self,
        column_index,
        combo,
        value,
    ):
        if combo.currentText() != "Custom Field":
            return

        field_name = value.strip()

        if not field_name:
            return

        new_decision = {
            "type": "custom",
            "field_name": field_name,
        }

        current_decision = self.column_mapping_overrides.get(
            column_index
        )

        if current_decision == new_decision:
            return

        if not self.confirm_mapping_change(
            column_index,
            new_decision,
        ):
            self.restore_mapping_control(column_index)
            return

        self.column_mapping_overrides[column_index] = new_decision

        self.apply_column_mapping_overrides()
        self.update_mapping_status()

    # --------------------------------------------------
    # Remove Previous Assignments
    # --------------------------------------------------

    def remove_matching_value(self, record, field_name, components):
        """Remove a standard or custom value only when it matches."""

        if field_name in record:
            old_value = record.get(field_name)

            if (
                old_value is not None
                and str(old_value).strip() in components
            ):
                record.pop(field_name, None)

        custom_fields = record.get("custom_fields") or {}

        if field_name in custom_fields:
            old_value = custom_fields.get(field_name)

            if (
                old_value is not None
                and str(old_value).strip() in components
            ):
                custom_fields.pop(field_name, None)

        record["custom_fields"] = custom_fields

    def remove_previous_column_assignment(
        self,
        record,
        column_index,
        raw_value,
    ):
        """Remove old parser and user-mapping representations."""

        if raw_value is None:
            return

        raw_text = str(raw_value).strip()

        if not raw_text:
            return

        # Keep the complete original cell as one value, but also use
        # components when checking whether the parser stored part of it.
        components = {raw_text}

        split_text = (
            raw_text.replace("|", "/")
            .replace(";", "/")
        )

        components.update(
            part.strip()
            for part in split_text.split("/")
            if part.strip()
        )

        parser_assignment = self.get_parser_assignment(column_index)

        if parser_assignment:
            self.remove_matching_value(
                record,
                parser_assignment,
                components,
            )

        previous_override = self.column_mapping_overrides.get(
            column_index
        )

        for field_name in self.get_decision_fields(previous_override):
            self.remove_matching_value(
                record,
                field_name,
                components,
            )

        custom_fields = record.get("custom_fields") or {}

        for alias in self.get_column_aliases(column_index):
            old_value = custom_fields.get(alias)

            if (
                old_value is not None
                and str(old_value).strip() in components
            ):
                custom_fields.pop(alias, None)

        record["custom_fields"] = custom_fields

    # --------------------------------------------------
    # Apply User Mappings and Cell Edits
    # --------------------------------------------------

    def apply_cell_edits(self):
        """Reapply manual corrections after rebuilding mapped records."""

        for (record_index, field_name), value in self.cell_edits.items():
            if not (0 <= record_index < len(self.records)):
                continue

            record = self.records[record_index]

            if field_name == "__duplicates__":
                continue

            if field_name in self.STANDARD_FIELDS.values():
                record[field_name] = value
            else:
                custom_fields = record.setdefault("custom_fields", {})
                custom_fields[field_name] = value

    def apply_column_mapping_overrides(self):
        """
        Rebuild records from parser output, apply column mappings,
        then reapply manual cell edits.
        """

        if not self.import_result:
            return

        raw_rows = self.import_result.get("table_rows") or []

        self.records = deepcopy(self.base_records)

        for column_index, decision in list(
            self.column_mapping_overrides.items()
        ):
            decision_type = decision.get("type")

            for record_index, record in enumerate(self.records):
                raw_row = (
                    raw_rows[record_index]
                    if record_index < len(raw_rows)
                    else None
                )

                raw_value = self.get_record_column_value(
                    record,
                    column_index,
                    raw_row,
                )

                if raw_value is None:
                    continue

                raw_value = str(raw_value).strip()

                if not raw_value:
                    continue

                self.remove_previous_column_assignment(
                    record,
                    column_index,
                    raw_value,
                )

                custom_fields = record.setdefault("custom_fields", {})

                if decision_type == "standard":
                    field_name = decision.get("field")

                    if field_name:
                        record[field_name] = raw_value

                elif decision_type == "custom":
                    field_name = decision.get("field_name", "").strip()

                    if field_name:
                        custom_fields[field_name] = raw_value

                elif decision_type == "ignore":
                    # The old parser/custom representation was removed.
                    pass

        # Manual cell corrections always apply after column mappings.
        self.apply_cell_edits()

        self.populate_player_table()
        self.update_summary()

    def update_mapping_status(self):
        total_columns = self.mapping_table.rowCount()
        resolved_columns = len(self.column_mapping_overrides)

        self.mapping_status_label.setText(
            f"User decisions: {resolved_columns} / "
            f"{total_columns} columns"
        )

    def get_user_column_mapping(self):
        return {
            column: decision.copy()
            for column, decision
            in self.column_mapping_overrides.items()
        }

    # --------------------------------------------------
    # Player Preview
    # --------------------------------------------------

    def get_preview_value(self, record, field_name):
        if field_name == "__duplicates__":
            duplicate_columns = record.get("duplicate_columns") or []

            duplicate_values = [
                f"{duplicate.get('field', '')}: "
                f"{duplicate.get('value', '')}"
                for duplicate in duplicate_columns
            ]

            return " | ".join(duplicate_values)

        if field_name in self.STANDARD_FIELDS.values():
            if field_name == "height":
                return (
                    record.get("height")
                    or record.get("height_inches")
                )

            if field_name == "weight":
                return (
                    record.get("weight")
                    or record.get("weight_lbs")
                )

            return record.get(field_name)

        custom_fields = record.get("custom_fields") or {}
        return custom_fields.get(field_name)

    def populate_player_table(self):
        self._updating_player_table = True

        try:
            custom_column_names = []

            for record in self.records:
                custom_fields = record.get("custom_fields") or {}

                for field_name in custom_fields:
                    if field_name not in custom_column_names:
                        custom_column_names.append(field_name)

            columns = list(self.PREVIEW_COLUMNS)

            columns.extend(
                (field_name, field_name)
                for field_name in custom_column_names
            )

            columns.append(("Duplicate Data", "__duplicates__"))

            self.player_table_columns = columns

            self.player_table.clear()
            self.player_table.setRowCount(0)
            self.player_table.setColumnCount(len(columns))

            self.player_table.setHorizontalHeaderLabels(
                [label for label, field in columns]
            )

            for record_index, record in enumerate(self.records):
                row_index = self.player_table.rowCount()
                self.player_table.insertRow(row_index)

                for column_index, (label, field_name) in enumerate(columns):
                    value = self.get_preview_value(record, field_name)

                    display_value = (
                        str(value)
                        if value is not None
                        else ""
                    )

                    item = QTableWidgetItem(display_value)

                    flags = (
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )

                    # Duplicate information is informational and read-only.
                    if field_name != "__duplicates__":
                        flags |= Qt.ItemFlag.ItemIsEditable

                    item.setFlags(flags)

                    # Mark cells that have been manually corrected.
                    if (record_index, field_name) in self.cell_edits:
                        item.setToolTip("Manually edited")
                        item.setBackground(Qt.GlobalColor.yellow)

                    self.player_table.setItem(
                        row_index,
                        column_index,
                        item,
                    )

            self.player_table.resizeRowsToContents()
            self.player_table.resizeColumnsToContents()

        finally:
            self._updating_player_table = False

    def handle_player_cell_changed(self, item):
        """Save an individual cell edit separately from parser output."""

        if self._updating_player_table:
            return

        row_index = item.row()
        column_index = item.column()

        if not (0 <= row_index < len(self.records)):
            return

        if not (0 <= column_index < len(self.player_table_columns)):
            return

        label, field_name = self.player_table_columns[column_index]

        if field_name == "__duplicates__":
            return

        new_value = item.text()

        # Store even an empty string. This matters when a user clears
        # an incorrectly assigned cell and later changes a column mapping.
        self.cell_edits[(row_index, field_name)] = new_value

        record = self.records[row_index]

        if field_name in self.STANDARD_FIELDS.values():
            record[field_name] = new_value
        else:
            custom_fields = record.setdefault("custom_fields", {})
            custom_fields[field_name] = new_value

        item.setToolTip("Manually edited")
        item.setBackground(Qt.GlobalColor.yellow)

        self.update_summary()

    # --------------------------------------------------
    # Import Summary
    # --------------------------------------------------

    def update_summary(self):
        result = self.import_result

        if not result:
            return

        record_count = len(self.records)
        source = result.get("source") or "Unknown"

        readiness = result.get("import_readiness", "not_ready")

        readiness_labels = {
            "ready": "Ready",
            "needs_review": "Needs Review",
            "not_ready": "Not Ready",
        }

        readiness_text = readiness_labels.get(
            readiness,
            readiness,
        )

        required_status = result.get(
            "required_field_status",
            {},
        ) or {}

        required_labels = {
            "jersey_number": "Jersey Number",
            "full_name": "Player Name",
            "position": "Position",
        }

        required_text = []

        for field, label in required_labels.items():
            present = required_status.get(field, False)
            status = "Found" if present else "Missing"

            required_text.append(f"{label}: {status}")

        summary = (
            f"Records Extracted: {record_count}\n"
            f"Source: {source}\n"
            f"Import Readiness: {readiness_text}\n"
            f"Manual Cell Edits: {len(self.cell_edits)}\n"
            f"{' | '.join(required_text)}"
        )

        self.summary_label.setText(summary)

    # --------------------------------------------------
    # Parsing Details
    # --------------------------------------------------

    def update_parsing_details(self):
        result = self.import_result

        if not result:
            return

        details = []

        pipeline_type = result.get("pipeline_type")

        if pipeline_type:
            details.append(f"Pipeline: {pipeline_type}")

        table_rows = result.get("table_rows") or []

        details.append(
            f"Table Rows Detected: {len(table_rows)}"
        )

        column_mapping = result.get("column_mapping") or {}

        details.append(
            f"Suggested Column Mappings: {len(column_mapping)}"
        )

        if result.get("has_ambiguities"):
            details.append(
                "Warning: Some columns have ambiguous mappings."
            )

        if result.get("has_custom_columns"):
            details.append(
                "Unmapped/custom data was detected and preserved."
            )

        missing_fields = result.get("missing_required_fields") or []

        if missing_fields:
            details.append(
                "Missing required fields: "
                + ", ".join(missing_fields)
            )

        errors = result.get("errors") or []

        if errors:
            details.append(
                "Errors:\n" + "\n".join(errors)
            )

        self.details_label.setText(
            "\n".join(details)
            if details
            else "No additional parsing information available."
        )

    # --------------------------------------------------
    # Clear Preview
    # --------------------------------------------------

    def clear_preview(self):
        self.import_result = None
        self.base_records = []
        self.records = []

        self.column_mapping_overrides = {}
        self.mapping_controls = {}
        self.cell_edits = {}
        self.player_table_columns = []

        self.player_table.setRowCount(0)
        self.player_table.setColumnCount(0)
        self.mapping_table.setRowCount(0)

        self.mapping_status_label.setText(
            "No user mapping decisions yet."
        )

        self.summary_label.setText("No roster data loaded.")
        self.details_label.setText("Waiting for clipboard data.")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    dialog = RosterImportDialog()
    dialog.exec()

    sys.exit(0)
