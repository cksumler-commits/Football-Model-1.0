from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)


class PlayerManagementDialog(QDialog):

    def __init__(self, organization_id, get_connection, parent=None):
        super().__init__(parent)

        self.organization_id = organization_id
        self.get_connection = get_connection
        self.selected_player_id = None

        self.setWindowTitle("Player Management")
        self.resize(950, 600)

        self.build_ui()
        self.refresh_players()

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        title = QLabel("Player Management")
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold;"
        )
        main_layout.addWidget(title)

        description = QLabel(
            "Manage player identities independently "
            "of teams and seasons."
        )
        description.setStyleSheet("color: gray;")
        main_layout.addWidget(description)

        # Search
        search_layout = QHBoxLayout()

        search_layout.addWidget(QLabel("Search:"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search players by name..."
        )
        self.search_input.textChanged.connect(
            self.refresh_players
        )

        search_layout.addWidget(self.search_input)

        self.show_archived_checkbox = QCheckBox(
            "Show archived players"
        )
        self.show_archived_checkbox.toggled.connect(
            self.refresh_players
        )

        search_layout.addWidget(
            self.show_archived_checkbox
        )

        main_layout.addLayout(search_layout)

        # Player table
        self.player_table = QTableWidget(0, 4)

        self.player_table.setHorizontalHeaderLabels(
            ["Full Name", "First Name", "Last Name", "Status"]
        )

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

        self.player_table.horizontalHeader().setStretchLastSection(
            True
        )

        self.player_table.cellClicked.connect(
            self.load_selected_player
        )

        main_layout.addWidget(self.player_table)

        # Player editor
        editor_layout = QHBoxLayout()

        self.full_name_input = QLineEdit()
        self.full_name_input.setPlaceholderText(
            "Full name (required)"
        )

        self.first_name_input = QLineEdit()
        self.first_name_input.setPlaceholderText(
            "First name (optional)"
        )

        self.last_name_input = QLineEdit()
        self.last_name_input.setPlaceholderText(
            "Last name (optional)"
        )

        editor_layout.addWidget(self.full_name_input)
        editor_layout.addWidget(self.first_name_input)
        editor_layout.addWidget(self.last_name_input)

        main_layout.addLayout(editor_layout)

        # Buttons
        button_layout = QHBoxLayout()

        self.new_button = QPushButton("New Player")
        self.new_button.clicked.connect(
            self.clear_form
        )

        self.save_button = QPushButton("Save Player")
        self.save_button.clicked.connect(
            self.save_player
        )

        self.archive_button = QPushButton(
            "Archive Selected Player"
        )
        self.archive_button.clicked.connect(
            self.archive_or_restore_player
        )

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(
            self.refresh_players
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
    # Refresh Players
    # --------------------------------------------------

    def refresh_players(self, *args, select_player_id=None):
        search_text = self.search_input.text().strip()
        show_archived = (
            self.show_archived_checkbox.isChecked()
        )

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:

                    query = """
                        SELECT
                            id,
                            full_name,
                            COALESCE(first_name, ''),
                            COALESCE(last_name, ''),
                            archived_at
                        FROM players
                        WHERE organization_id = %s
                    """

                    parameters = [self.organization_id]

                    if not show_archived:
                        query += """
                            AND archived_at IS NULL
                        """

                    if search_text:
                        query += """
                            AND (
                                full_name ILIKE %s
                                OR first_name ILIKE %s
                                OR last_name ILIKE %s
                            )
                        """

                        search_pattern = (
                            f"%{search_text}%"
                        )

                        parameters.extend([
                            search_pattern,
                            search_pattern,
                            search_pattern,
                        ])

                    query += """
                        ORDER BY full_name
                    """

                    cur.execute(query, parameters)
                    players = cur.fetchall()

            self.player_table.setRowCount(0)

            for player in players:
                (
                    player_id,
                    full_name,
                    first_name,
                    last_name,
                    archived_at,
                ) = player

                row = self.player_table.rowCount()
                self.player_table.insertRow(row)

                status = (
                    "Archived"
                    if archived_at is not None
                    else "Active"
                )

                values = [
                    full_name,
                    first_name,
                    last_name,
                    status,
                ]

                for column, value in enumerate(values):
                    item = QTableWidgetItem(
                        str(value or "")
                    )

                    if column == 0:
                        item.setData(
                            Qt.ItemDataRole.UserRole,
                            player_id,
                        )

                    self.player_table.setItem(
                        row,
                        column,
                        item,
                    )

            self.player_table.resizeColumnsToContents()

            if select_player_id is not None:
                for row in range(
                    self.player_table.rowCount()
                ):
                    item = self.player_table.item(row, 0)

                    if (
                        item
                        and item.data(
                            Qt.ItemDataRole.UserRole
                        ) == select_player_id
                    ):
                        self.player_table.selectRow(row)
                        self.load_selected_player(row, 0)
                        break

            self.status_label.setText(
                f"{len(players)} player(s) loaded."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Player Load Error",
                f"Could not load players:\n\n{error}",
            )

    # --------------------------------------------------
    # Load Selected Player
    # --------------------------------------------------

    def load_selected_player(self, row, column=0):
        item = self.player_table.item(row, 0)

        if item is None:
            return

        player_id = item.data(
            Qt.ItemDataRole.UserRole
        )

        if player_id is None:
            return

        self.selected_player_id = player_id

        self.full_name_input.setText(
            self.player_table.item(row, 0).text()
        )

        self.first_name_input.setText(
            self.player_table.item(row, 1).text()
        )

        self.last_name_input.setText(
            self.player_table.item(row, 2).text()
        )

        status = self.player_table.item(
            row, 3
        ).text()

        if status == "Archived":
            self.archive_button.setText(
                "Restore Selected Player"
            )
        else:
            self.archive_button.setText(
                "Archive Selected Player"
            )

        self.status_label.setText(
            f"Editing player ID {player_id}."
        )

    # --------------------------------------------------
    # Clear Form
    # --------------------------------------------------

    def clear_form(self):
        self.selected_player_id = None

        self.player_table.clearSelection()

        self.full_name_input.clear()
        self.first_name_input.clear()
        self.last_name_input.clear()

        self.archive_button.setText(
            "Archive Selected Player"
        )

        self.full_name_input.setFocus()

        self.status_label.setText(
            "New player. Enter information and save."
        )

    # --------------------------------------------------
    # Save Player
    # --------------------------------------------------

    def save_player(self):
        full_name = (
            self.full_name_input.text().strip()
        )

        first_name = (
            self.first_name_input.text().strip()
            or None
        )

        last_name = (
            self.last_name_input.text().strip()
            or None
        )

        if not full_name:
            QMessageBox.warning(
                self,
                "Name Required",
                "Enter a player's full name.",
            )
            self.full_name_input.setFocus()
            return

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:

                    if self.selected_player_id is None:

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

                        player_id = cur.fetchone()[0]

                        message = (
                            f"Created player: {full_name}"
                        )

                    else:

                        cur.execute(
                            """
                            UPDATE players
                            SET
                                full_name = %s,
                                first_name = %s,
                                last_name = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND organization_id = %s
                            RETURNING id
                            """,
                            (
                                full_name,
                                first_name,
                                last_name,
                                self.selected_player_id,
                                self.organization_id,
                            ),
                        )

                        result = cur.fetchone()

                        if result is None:
                            raise ValueError(
                                "Player not found in your organization."
                            )

                        player_id = result[0]

                        message = (
                            f"Updated player: {full_name}"
                        )

            self.refresh_players(
                select_player_id=player_id
            )

            self.status_label.setText(message)

        except Exception as error:
            QMessageBox.critical(
                self,
                "Player Save Error",
                f"Could not save player:\n\n{error}",
            )

    # --------------------------------------------------
    # Archive / Restore
    # --------------------------------------------------

    def archive_or_restore_player(self):
        if self.selected_player_id is None:
            QMessageBox.information(
                self,
                "Select a Player",
                "Select a player first.",
            )
            return

        selected_row = (
            self.player_table.currentRow()
        )

        if selected_row < 0:
            return

        status_item = self.player_table.item(
            selected_row, 3
        )

        if status_item is None:
            return

        is_archived = (
            status_item.text() == "Archived"
        )

        player_name = (
            self.full_name_input.text().strip()
        )

        if is_archived:
            action = "restore"
            new_archived_at = None
            confirmation_text = (
                f"Restore {player_name}?\n\n"
                "The player will become active again."
            )
        else:
            action = "archive"
            new_archived_at = "CURRENT_TIMESTAMP"
            confirmation_text = (
                f"Archive {player_name}?\n\n"
                "The player identity will be preserved."
            )

        answer = QMessageBox.question(
            self,
            f"Confirm {action.title()}",
            confirmation_text,
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
                            UPDATE players
                            SET archived_at = NULL,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND organization_id = %s
                            """,
                            (
                                self.selected_player_id,
                                self.organization_id,
                            ),
                        )

                    else:
                        cur.execute(
                            """
                            UPDATE players
                            SET archived_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND organization_id = %s
                            """,
                            (
                                self.selected_player_id,
                                self.organization_id,
                            ),
                        )

                    if cur.rowcount != 1:
                        raise ValueError(
                            "Player not found or unavailable."
                        )

            self.clear_form()
            self.refresh_players()

            self.status_label.setText(
                f"{player_name} {action}d."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Player Update Error",
                f"Could not {action} player:\n\n{error}",
            )