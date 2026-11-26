
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)


class NewRosterPlayerDialog(QDialog):

    def __init__(self, organization_id, get_connection, parent=None):
        super().__init__(parent)

        self.organization_id = organization_id
        self.get_connection = get_connection
        self.player_id = None

        self.setWindowTitle("Create New Player")
        self.resize(400, 220)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.full_name_input = QLineEdit()
        self.first_name_input = QLineEdit()
        self.last_name_input = QLineEdit()

        form.addRow("Full Name:", self.full_name_input)
        form.addRow("First Name:", self.first_name_input)
        form.addRow("Last Name:", self.last_name_input)

        layout.addLayout(form)

        button_layout = QHBoxLayout()

        save_button = QPushButton("Create Player")
        save_button.clicked.connect(self.create_player)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

    def create_player(self):

        full_name = self.full_name_input.text().strip()
        first_name = self.first_name_input.text().strip() or None
        last_name = self.last_name_input.text().strip() or None

        if not full_name:
            QMessageBox.warning(
                self,
                "Name Required",
                "Enter the player's full name.",
            )
            return

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO players (
                            organization_id,
                            full_name,
                            first_name,
                            last_name
                        )
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            self.organization_id,
                            full_name,
                            first_name,
                            last_name,
                        ),
                    )

                    self.player_id = cur.fetchone()[0]

            self.accept()

        except Exception as error:
            QMessageBox.critical(
                self,
                "Player Creation Error",
                f"Could not create player:\n\n{error}",
            )


class RosterMembershipManagementDialog(QDialog):

    def __init__(
        self,
        organization_id,
        roster_id,
        team_name,
        season,
        get_connection,
        parent=None,
    ):
        super().__init__(parent)

        self.organization_id = organization_id
        self.roster_id = roster_id
        self.team_name = team_name
        self.season = season
        self.get_connection = get_connection

        self.selected_membership_id = None

        self.setWindowTitle(
            f"Roster Players - {team_name} ({season})"
        )
        self.resize(1100, 750)

        self.build_ui()
        self.load_players()
        self.refresh_memberships()

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def build_ui(self):

        main_layout = QVBoxLayout(self)

        title = QLabel(
            f"{self.team_name} - {self.season} Roster"
        )
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold;"
        )
        main_layout.addWidget(title)

        description = QLabel(
            "Manage players and their season-specific roster information."
        )
        description.setStyleSheet("color: gray;")
        main_layout.addWidget(description)

        # Search and archived filter

        search_layout = QHBoxLayout()

        search_layout.addWidget(QLabel("Search:"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search roster players..."
        )
        self.search_input.textChanged.connect(
            self.refresh_memberships
        )

        search_layout.addWidget(self.search_input)

        self.show_archived_checkbox = QCheckBox(
            "Show archived players"
        )
        self.show_archived_checkbox.toggled.connect(
            self.refresh_memberships
        )

        search_layout.addWidget(
            self.show_archived_checkbox
        )

        main_layout.addLayout(search_layout)

        # Membership table

        self.membership_table = QTableWidget(0, 6)

        self.membership_table.setHorizontalHeaderLabels([
            "Jersey",
            "Player",
            "Height",
            "Weight",
            "Classification",
            "Status",
        ])

        self.membership_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )

        self.membership_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )

        self.membership_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self.membership_table.setAlternatingRowColors(True)

        self.membership_table.horizontalHeader().setStretchLastSection(
            True
        )

        self.membership_table.cellClicked.connect(
            self.load_selected_membership
        )

        main_layout.addWidget(self.membership_table)

        # Membership editor

        editor_title = QLabel("Roster Membership Editor")
        editor_title.setStyleSheet(
            "font-size: 17px; font-weight: bold;"
        )
        main_layout.addWidget(editor_title)

        form = QFormLayout()

        # Player selection

        player_layout = QHBoxLayout()

        self.player_selector = QComboBox()
        player_layout.addWidget(self.player_selector)

        self.create_player_button = QPushButton(
            "Create New Player"
        )
        self.create_player_button.clicked.connect(
            self.open_new_player_dialog
        )
        player_layout.addWidget(self.create_player_button)

        form.addRow("Player:", player_layout)

        # Jersey number

        self.jersey_input = QLineEdit()
        self.jersey_input.setMaxLength(10)
        self.jersey_input.setPlaceholderText(
            "Example: 00"
        )
        form.addRow("Jersey Number:", self.jersey_input)

        # Height

        height_layout = QHBoxLayout()

        self.height_feet_input = QSpinBox()
        self.height_feet_input.setRange(0, 8)
        self.height_feet_input.setSuffix(" ft")

        self.height_inches_input = QSpinBox()
        self.height_inches_input.setRange(0, 11)
        self.height_inches_input.setSuffix(" in")

        height_layout.addWidget(self.height_feet_input)
        height_layout.addWidget(self.height_inches_input)

        form.addRow("Height:", height_layout)

        # Weight

        self.weight_input = QSpinBox()
        self.weight_input.setRange(0, 500)
        self.weight_input.setSpecialValueText("Not entered")
        self.weight_input.setSuffix(" lbs")

        form.addRow("Weight:", self.weight_input)

        # Classification

        self.classification_input = QComboBox()
        self.classification_input.setEditable(True)

        self.classification_input.addItems([
            "Freshman",
            "Redshirt Freshman",
            "Sophomore",
            "Redshirt Sophomore",
            "Junior",
            "Redshirt Junior",
            "Senior",
            "Redshirt Senior",
            "Graduate",
        ])

        self.classification_input.setCurrentIndex(-1)

        form.addRow(
            "Classification:",
            self.classification_input,
        )

        # Optional information

        self.major_input = QLineEdit()
        self.hometown_input = QLineEdit()
        self.high_school_input = QLineEdit()
        self.previous_school_input = QLineEdit()

        form.addRow("Major:", self.major_input)
        form.addRow("Hometown:", self.hometown_input)
        form.addRow("High School:", self.high_school_input)
        form.addRow("Previous School:", self.previous_school_input)

        main_layout.addLayout(form)

        # Buttons

        button_layout = QHBoxLayout()

        self.new_button = QPushButton("New Membership")
        self.new_button.clicked.connect(
            self.clear_form
        )

        self.save_button = QPushButton("Save Membership")
        self.save_button.clicked.connect(
            self.save_membership
        )

        self.archive_button = QPushButton(
            "Archive Selected Membership"
        )
        self.archive_button.clicked.connect(
            self.archive_or_restore_membership
        )

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(
            self.refresh_memberships
        )

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        button_layout.addWidget(self.new_button)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.archive_button)
        button_layout.addWidget(self.refresh_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)

        main_layout.addLayout(button_layout)

        self.status_label = QLabel("Ready.")
        main_layout.addWidget(self.status_label)

    # --------------------------------------------------
    # Load Available Players
    # --------------------------------------------------

    def load_players(self, select_player_id=None):

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    SELECT id, full_name
                    FROM players
                    WHERE organization_id = %s
                      AND archived_at IS NULL
                    ORDER BY full_name
                    """,
                        (self.organization_id,),
                    )

                    players = cur.fetchall()

            self.player_selector.clear()

        # Placeholder: require intentional selection
            self.player_selector.addItem(
                "Select a player...",
                None,
            )

            for player_id, full_name in players:
                self.player_selector.addItem(
                    full_name,
                    player_id,
                )

        # Select a specific player when requested
            if select_player_id is not None:
                index = self.player_selector.findData(
                    select_player_id
                )

                if index >= 0:
                    self.player_selector.setCurrentIndex(index)

            else:
                self.player_selector.setCurrentIndex(0)

        except Exception as error:
            QMessageBox.critical(
                self,
                "Player Load Error",
                f"Could not load players:\n\n{error}",
            )


    # --------------------------------------------------
    # Create Player Without Leaving Roster
    # --------------------------------------------------

    def open_new_player_dialog(self):

        dialog = NewRosterPlayerDialog(
            self.organization_id,
            self.get_connection,
            self,
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_players(
                select_player_id=dialog.player_id
            )

            self.player_selector.setEnabled(True)

            self.status_label.setText(
                "New player created and selected."
            )

    # --------------------------------------------------
    # Refresh Memberships
    # --------------------------------------------------

    def refresh_memberships(
        self,
        *args,
        select_membership_id=None,
    ):

        search_text = self.search_input.text().strip()
        show_archived = self.show_archived_checkbox.isChecked()

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:

                    query = """
                        SELECT
                            rm.id,
                            rm.player_id,
                            rm.jersey_number,
                            p.full_name,
                            rm.height_inches,
                            rm.weight_lbs,
                            rm.classification,
                            rm.archived_at
                        FROM roster_memberships rm
                        JOIN players p
                          ON p.id = rm.player_id
                         AND p.organization_id = rm.organization_id
                        WHERE rm.organization_id = %s
                          AND rm.roster_id = %s
                    """

                    parameters = [
                        self.organization_id,
                        self.roster_id,
                    ]

                    if not show_archived:
                        query += """
                            AND rm.archived_at IS NULL
                        """

                    if search_text:
                        query += """
                            AND (
                                p.full_name ILIKE %s
                                OR rm.jersey_number ILIKE %s
                                OR rm.classification ILIKE %s
                            )
                        """

                        pattern = f"%{search_text}%"
                        parameters.extend([
                            pattern,
                            pattern,
                            pattern,
                        ])

                    query += """
                        ORDER BY
                            CASE
                                WHEN rm.jersey_number ~ '^[0-9]+$'
                                THEN CAST(rm.jersey_number AS INTEGER)
                                ELSE NULL
                            END NULLS LAST,
                            p.full_name
                    """

                    cur.execute(query, parameters)
                    memberships = cur.fetchall()

            self.membership_table.setRowCount(0)

            for membership in memberships:

                (
                    membership_id,
                    player_id,
                    jersey_number,
                    full_name,
                    height_inches,
                    weight_lbs,
                    classification,
                    archived_at,
                ) = membership

                row = self.membership_table.rowCount()
                self.membership_table.insertRow(row)

                if height_inches:
                    height_text = (
                        f"{height_inches // 12}'"
                        f"{height_inches % 12}\""
                    )
                else:
                    height_text = ""

                status = (
                    "Archived"
                    if archived_at is not None
                    else "Active"
                )

                values = [
                    jersey_number or "",
                    full_name,
                    height_text,
                    str(weight_lbs) if weight_lbs else "",
                    classification or "",
                    status,
                ]

                for column, value in enumerate(values):

                    item = QTableWidgetItem(str(value))

                    if column == 0:
                        item.setData(
                            Qt.ItemDataRole.UserRole,
                            membership_id,
                        )

                    if column == 1:
                        item.setData(
                            Qt.ItemDataRole.UserRole,
                            player_id,
                        )

                    self.membership_table.setItem(
                        row,
                        column,
                        item,
                    )

            self.membership_table.resizeColumnsToContents()

            if select_membership_id is not None:

                for row in range(
                    self.membership_table.rowCount()
                ):

                    item = self.membership_table.item(row, 0)

                    if (
                        item
                        and item.data(Qt.ItemDataRole.UserRole)
                        == select_membership_id
                    ):
                        self.membership_table.selectRow(row)
                        self.load_selected_membership(row, 0)
                        break

            self.status_label.setText(
                f"{len(memberships)} roster membership(s) loaded."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Roster Load Error",
                f"Could not load roster memberships:\n\n{error}",
            )

    # --------------------------------------------------
    # Load Selected Membership
    # --------------------------------------------------

    def load_selected_membership(self, row, column=0):

        item = self.membership_table.item(row, 0)

        if item is None:
            return

        membership_id = item.data(
            Qt.ItemDataRole.UserRole
        )

        player_item = self.membership_table.item(row, 1)

        if membership_id is None or player_item is None:
            return

        player_id = player_item.data(
            Qt.ItemDataRole.UserRole
        )

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            jersey_number,
                            height_inches,
                            weight_lbs,
                            classification,
                            major,
                            hometown,
                            high_school,
                            previous_school
                        FROM roster_memberships
                        WHERE id = %s
                          AND organization_id = %s
                          AND roster_id = %s
                        """,
                        (
                            membership_id,
                            self.organization_id,
                            self.roster_id,
                        ),
                    )

                    membership = cur.fetchone()

            if membership is None:
                return

            self.selected_membership_id = membership_id

            (
                jersey_number,
                height_inches,
                weight_lbs,
                classification,
                major,
                hometown,
                high_school,
                previous_school,
            ) = membership

            # Preserve the full player list while editing.
# Select the player belonging to this membership.

            player_index = self.player_selector.findData(
                player_id
                )

            if player_index >= 0:
                self.player_selector.setCurrentIndex(
                    player_index
                    )

            self.player_selector.setEnabled(False)
            self.create_player_button.setEnabled(False)

            self.jersey_input.setText(
                jersey_number or ""
            )

            height_inches = height_inches or 0

            self.height_feet_input.setValue(
                height_inches // 12
            )

            self.height_inches_input.setValue(
                height_inches % 12
            )

            self.weight_input.setValue(
                weight_lbs or 0
            )

            self.classification_input.setCurrentText(
                classification or ""
            )

            self.major_input.setText(major or "")
            self.hometown_input.setText(hometown or "")
            self.high_school_input.setText(high_school or "")
            self.previous_school_input.setText(
                previous_school or ""
            )

            status = self.membership_table.item(row, 5).text()

            if status == "Archived":
                self.archive_button.setText(
                    "Restore Selected Membership"
                )
            else:
                self.archive_button.setText(
                    "Archive Selected Membership"
                )

            self.status_label.setText(
                f"Editing membership ID {membership_id}."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Membership Load Error",
                f"Could not load membership:\n\n{error}",
            )

    # --------------------------------------------------
    # Clear Form
    # --------------------------------------------------

    def clear_form(self):

        self.selected_membership_id = None
        # Reload the complete player list and reset selection
        self.load_players()

        self.membership_table.clearSelection()

        self.player_selector.setEnabled(True)
        self.create_player_button.setEnabled(True)

        self.jersey_input.clear()

        self.height_feet_input.setValue(0)
        self.height_inches_input.setValue(0)
        self.weight_input.setValue(0)

        self.classification_input.setCurrentIndex(-1)
        self.classification_input.setEditText("")

        self.major_input.clear()
        self.hometown_input.clear()
        self.high_school_input.clear()
        self.previous_school_input.clear()

        self.archive_button.setText(
            "Archive Selected Membership"
        )

        self.status_label.setText(
            "New membership. Select a player and enter roster information."
        )

    # --------------------------------------------------
    # Save Membership
    # --------------------------------------------------

    def save_membership(self):

        player_id = self.player_selector.currentData()

        if player_id is None:
            QMessageBox.warning(
                self,
                "Player Required",
                "Select or create a player first.",
            )
            return

        jersey_number = (
            self.jersey_input.text().strip() or None
        )

        height_inches = (
            self.height_feet_input.value() * 12
            + self.height_inches_input.value()
        )

        height_inches = height_inches or None

        weight_lbs = self.weight_input.value() or None

        classification = (
            self.classification_input.currentText().strip()
            or None
        )

        major = self.major_input.text().strip() or None
        hometown = self.hometown_input.text().strip() or None
        high_school = self.high_school_input.text().strip() or None
        previous_school = (
            self.previous_school_input.text().strip() or None
        )

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:

                    if self.selected_membership_id is None:

                        cur.execute(
                            """
                            SELECT id, archived_at
                            FROM roster_memberships
                            WHERE organization_id = %s
                              AND roster_id = %s
                              AND player_id = %s
                            """,
                            (
                                self.organization_id,
                                self.roster_id,
                                player_id,
                            ),
                        )

                        existing = cur.fetchone()

                        if existing is not None:
                            if existing[1] is not None:
                                raise ValueError(
                                    "This player already has an archived "
                                    "membership in this roster. Enable "
                                    "'Show archived players' and restore "
                                    "that membership instead."
                                )

                            raise ValueError(
                                "This player is already on this roster."
                            )

                        cur.execute(
                            """
                            INSERT INTO roster_memberships (
                                organization_id,
                                roster_id,
                                player_id,
                                jersey_number,
                                height_inches,
                                weight_lbs,
                                classification,
                                major,
                                hometown,
                                high_school,
                                previous_school
                            )
                            VALUES (
                                %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s
                            )
                            RETURNING id
                            """,
                            (
                                self.organization_id,
                                self.roster_id,
                                player_id,
                                jersey_number,
                                height_inches,
                                weight_lbs,
                                classification,
                                major,
                                hometown,
                                high_school,
                                previous_school,
                            ),
                        )

                        membership_id = cur.fetchone()[0]
                        message = "Roster membership created."

                    else:

                        cur.execute(
                            """
                            UPDATE roster_memberships
                            SET
                                jersey_number = %s,
                                height_inches = %s,
                                weight_lbs = %s,
                                classification = %s,
                                major = %s,
                                hometown = %s,
                                high_school = %s,
                                previous_school = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND organization_id = %s
                              AND roster_id = %s
                            RETURNING id
                            """,
                            (
                                jersey_number,
                                height_inches,
                                weight_lbs,
                                classification,
                                major,
                                hometown,
                                high_school,
                                previous_school,
                                self.selected_membership_id,
                                self.organization_id,
                                self.roster_id,
                            ),
                        )

                        result = cur.fetchone()

                        if result is None:
                            raise ValueError(
                                "Roster membership not found."
                            )

                        membership_id = result[0]
                        message = "Roster membership updated."

            self.refresh_memberships(
                select_membership_id=membership_id
            )

            self.status_label.setText(message)

        except Exception as error:
            QMessageBox.critical(
                self,
                "Membership Save Error",
                f"Could not save membership:\n\n{error}",
            )

    # --------------------------------------------------
    # Archive / Restore Membership
    # --------------------------------------------------

    def archive_or_restore_membership(self):

        if self.selected_membership_id is None:
            QMessageBox.information(
                self,
                "Select a Membership",
                "Select a roster membership first.",
            )
            return

        selected_row = self.membership_table.currentRow()

        if selected_row < 0:
            return

        status_item = self.membership_table.item(
            selected_row,
            5,
        )

        if status_item is None:
            return

        is_archived = status_item.text() == "Archived"

        player_name = self.membership_table.item(
            selected_row,
            1,
        ).text()

        if is_archived:
            action = "restore"
            confirmation = (
                f"Restore {player_name} to this roster?"
            )
        else:
            action = "archive"
            confirmation = (
                f"Archive {player_name} from this roster?\n\n"
                "Their player identity and other roster memberships "
                "will remain unchanged."
            )

        answer = QMessageBox.question(
            self,
            f"Confirm {action.title()}",
            confirmation,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:

                    if is_archived:
                        cur.execute(
                            """
                            UPDATE roster_memberships
                            SET archived_at = NULL,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND organization_id = %s
                              AND roster_id = %s
                            """,
                            (
                                self.selected_membership_id,
                                self.organization_id,
                                self.roster_id,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE roster_memberships
                            SET archived_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND organization_id = %s
                              AND roster_id = %s
                            """,
                            (
                                self.selected_membership_id,
                                self.organization_id,
                                self.roster_id,
                            ),
                        )

                    if cur.rowcount != 1:
                        raise ValueError(
                            "Membership not found or unavailable."
                        )

            self.clear_form()
            self.refresh_memberships()

            self.status_label.setText(
                f"{player_name} membership {action}d."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Membership Update Error",
                f"Could not {action} membership:\n\n{error}",
            )
