from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class TeamManagementDialog(QDialog):
    """
    Organization-scoped team management.

    Pass the existing application's get_connection function into this dialog
    rather than creating a second database configuration.
    """

    def __init__(self, organization_id, get_connection, parent=None):
        super().__init__(parent)

        self.organization_id = organization_id
        self.get_connection = get_connection
        self.selected_team_id = None

        self.setWindowTitle("Team Management")
        self.resize(900, 560)

        self.build_ui()
        self.refresh_teams()

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        heading = QLabel("Team Management")
        heading.setStyleSheet("font-size: 20px; font-weight: bold;")
        main_layout.addWidget(heading)

        content_layout = QHBoxLayout()

        # Team list
        self.team_table = QTableWidget(0, 4)
        self.team_table.setHorizontalHeaderLabels(
            ["Team Name", "Abbreviation", "Conference", "Division"]
        )
        self.team_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.team_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.team_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.team_table.setAlternatingRowColors(True)
        self.team_table.horizontalHeader().setStretchLastSection(True)
        self.team_table.cellClicked.connect(self.load_selected_team)
        content_layout.addWidget(self.team_table, 3)

        # Team editor
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)

        editor_layout.addWidget(QLabel("Team Name *"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Arkansas State")
        editor_layout.addWidget(self.name_input)

        editor_layout.addWidget(QLabel("Abbreviation"))
        self.abbreviation_input = QLineEdit()
        self.abbreviation_input.setPlaceholderText("e.g. ARST")
        editor_layout.addWidget(self.abbreviation_input)

        editor_layout.addWidget(QLabel("Conference"))
        self.conference_input = QLineEdit()
        self.conference_input.setPlaceholderText("Optional")
        editor_layout.addWidget(self.conference_input)

        editor_layout.addWidget(QLabel("Division"))
        self.division_input = QLineEdit()
        self.division_input.setPlaceholderText("Optional")
        editor_layout.addWidget(self.division_input)

        editor_layout.addSpacing(12)

        self.new_button = QPushButton("New Team")
        self.new_button.clicked.connect(self.clear_form)
        editor_layout.addWidget(self.new_button)

        self.save_button = QPushButton("Save Team")
        self.save_button.clicked.connect(self.save_team)
        editor_layout.addWidget(self.save_button)

        self.delete_button = QPushButton("Delete Team")
        self.delete_button.clicked.connect(self.delete_team)
        editor_layout.addWidget(self.delete_button)

        self.refresh_button = QPushButton("Refresh Teams")
        self.refresh_button.clicked.connect(self.refresh_teams)
        editor_layout.addWidget(self.refresh_button)

        editor_layout.addStretch()
        content_layout.addWidget(editor, 2)

        main_layout.addLayout(content_layout)

        self.status_label = QLabel("Ready.")
        main_layout.addWidget(self.status_label)

        close_layout = QHBoxLayout()
        close_layout.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_layout.addWidget(close_button)

        main_layout.addLayout(close_layout)

    def refresh_teams(self, select_team_id=None):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id,
                            name,
                            COALESCE(abbreviation, ''),
                            COALESCE(conference, ''),
                            COALESCE(division, '')
                        FROM teams
                        WHERE organization_id = %s
                        ORDER BY name
                        """,
                        (self.organization_id,),
                    )
                    teams = cur.fetchall()

            self.team_table.setRowCount(0)

            for team in teams:
                team_id, name, abbreviation, conference, division = team
                row = self.team_table.rowCount()
                self.team_table.insertRow(row)

                values = [name, abbreviation, conference, division]

                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value or ""))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, team_id)
                    self.team_table.setItem(row, column, item)

            self.team_table.resizeColumnsToContents()

            if select_team_id is not None:
                for row in range(self.team_table.rowCount()):
                    item = self.team_table.item(row, 0)
                    if item and item.data(Qt.ItemDataRole.UserRole) == select_team_id:
                        self.team_table.selectRow(row)
                        self.load_selected_team(row, 0)
                        break

            self.status_label.setText(f"{len(teams)} team(s) loaded.")

        except Exception as error:
            QMessageBox.critical(
                self,
                "Team Load Error",
                f"Could not load teams:\n\n{error}",
            )

    def load_selected_team(self, row, column=0):
        item = self.team_table.item(row, 0)

        if item is None:
            return

        team_id = item.data(Qt.ItemDataRole.UserRole)

        if team_id is None:
            return

        self.selected_team_id = team_id

        self.name_input.setText(self.team_table.item(row, 0).text())
        self.abbreviation_input.setText(self.team_table.item(row, 1).text())
        self.conference_input.setText(self.team_table.item(row, 2).text())
        self.division_input.setText(self.team_table.item(row, 3).text())

        self.status_label.setText(f"Editing team ID {team_id}.")

    def clear_form(self):
        self.selected_team_id = None
        self.team_table.clearSelection()

        self.name_input.clear()
        self.abbreviation_input.clear()
        self.conference_input.clear()
        self.division_input.clear()

        self.name_input.setFocus()
        self.status_label.setText("New team. Enter its information and save.")

    def save_team(self):
        name = self.name_input.text().strip()
        abbreviation = self.abbreviation_input.text().strip()
        conference = self.conference_input.text().strip()
        division = self.division_input.text().strip()

        if not name:
            QMessageBox.warning(
                self,
                "Team Name Required",
                "Enter a team name before saving.",
            )
            self.name_input.setFocus()
            return

        abbreviation = abbreviation or None
        conference = conference or None
        division = division or None

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    if self.selected_team_id is None:
                        cur.execute(
                            """
                            INSERT INTO teams (
                                organization_id,
                                name,
                                abbreviation,
                                conference,
                                division
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                self.organization_id,
                                name,
                                abbreviation,
                                conference,
                                division,
                            ),
                        )
                        team_id = cur.fetchone()[0]
                        message = f"Created team: {name}"

                    else:
                        cur.execute(
                            """
                            UPDATE teams
                            SET
                                name = %s,
                                abbreviation = %s,
                                conference = %s,
                                division = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                              AND organization_id = %s
                            RETURNING id
                            """,
                            (
                                name,
                                abbreviation,
                                conference,
                                division,
                                self.selected_team_id,
                                self.organization_id,
                            ),
                        )

                        result = cur.fetchone()

                        if result is None:
                            raise ValueError(
                                "The selected team was not found in your "
                                "organization. Refresh the list and try again."
                            )

                        team_id = result[0]
                        message = f"Updated team: {name}"

            self.refresh_teams(select_team_id=team_id)
            self.status_label.setText(message)

        except Exception as error:
            QMessageBox.critical(
                self,
                "Team Save Error",
                (
                    "Could not save the team.\n\n"
                    "Check that the team name isn't already being used "
                    "in your organization.\n\n"
                    f"Details: {error}"
                ),
            )

    def delete_team(self):
        if self.selected_team_id is None:
            QMessageBox.information(
                self,
                "Select a Team",
                "Select a team before deleting it.",
            )
            return

        team_name = self.name_input.text().strip()

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM team_rosters
                        WHERE team_id = %s
                          AND organization_id = %s
                        """,
                        (
                            self.selected_team_id,
                            self.organization_id,
                        ),
                    )
                    roster_count = cur.fetchone()[0]

            if roster_count > 0:
                QMessageBox.warning(
                    self,
                    "Team Cannot Be Deleted",
                    (
                        f"{team_name} has {roster_count} roster(s) attached.\n\n"
                        "Teams with roster history cannot be deleted. "
                        "Roster archiving and team lifecycle management "
                        "will be added in a later step."
                    ),
                )
                return

            answer = QMessageBox.question(
                self,
                "Confirm Team Deletion",
                (
                    f"Delete {team_name} permanently?\n\n"
                    "This cannot be undone."
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer != QMessageBox.StandardButton.Yes:
                return

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM teams
                        WHERE id = %s
                          AND organization_id = %s
                        """,
                        (
                            self.selected_team_id,
                            self.organization_id,
                        ),
                    )

                    if cur.rowcount != 1:
                        raise ValueError(
                            "The team was not found or was already deleted."
                        )

            self.clear_form()
            self.refresh_teams()
            self.status_label.setText(f"Deleted team: {team_name}")

        except Exception as error:
            QMessageBox.critical(
                self,
                "Team Delete Error",
                f"Could not delete the team:\n\n{error}",
            )
