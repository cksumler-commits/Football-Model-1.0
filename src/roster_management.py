from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)

from PySide6.QtCore import Qt

from PySide6.QtWidgets import QTableWidgetItem

from roster_membership_management import (
    RosterMembershipManagementDialog,
)



class RosterManagementDialog(QDialog):

    def __init__(self, organization_id, get_connection, parent=None):
        super().__init__(parent)

        self.organization_id = organization_id
        self.get_connection = get_connection

        self.setWindowTitle("Roster Management")
        self.resize(900, 600)

        self.build_ui()
        self.load_teams()

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        title = QLabel("Roster Management")
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold;"
        )
        main_layout.addWidget(title)

        description = QLabel(
            "Create and manage team rosters by season."
        )
        description.setStyleSheet("color: gray;")
        main_layout.addWidget(description)

        # Team and season selection
        selection_layout = QHBoxLayout()

        selection_layout.addWidget(QLabel("Team:"))

        self.team_selector = QComboBox()
        self.team_selector.currentIndexChanged.connect(
            self.refresh_rosters
        )
        selection_layout.addWidget(self.team_selector)

        selection_layout.addWidget(QLabel("Season:"))

        self.season_input = QSpinBox()
        self.season_input.setRange(1900, 2200)
        self.season_input.setValue(2026)
        selection_layout.addWidget(self.season_input)

        self.create_roster_button = QPushButton(
            "Create Roster"
        )
        self.create_roster_button.clicked.connect(
            self.create_roster
        )
        selection_layout.addWidget(
            self.create_roster_button
        )

        selection_layout.addStretch()

        main_layout.addLayout(selection_layout)

        # Roster table
        self.roster_table = QTableWidget(0, 3)

        self.roster_table.setHorizontalHeaderLabels(
            ["Season", "Status", "Created"]
        )

        self.roster_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )

        self.roster_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )

        self.roster_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self.roster_table.setAlternatingRowColors(True)

        self.roster_table.horizontalHeader().setStretchLastSection(
            True
        )

        main_layout.addWidget(self.roster_table)
        self.roster_table.itemSelectionChanged.connect(
            self.update_manage_members_button
            )

        # Actions
        # Actions

        action_layout = QHBoxLayout()

        self.manage_members_button = QPushButton(
                "Manage Roster Members"
        )

        self.manage_members_button.clicked.connect(
        self.manage_roster_members
                )

        self.manage_members_button.setEnabled(False)

        self.archive_button = QPushButton(
            "Archive Selected Roster"
            )

        self.archive_button.clicked.connect(
            self.archive_roster
            )

        self.refresh_button = QPushButton("Refresh")

        self.refresh_button.clicked.connect(
            self.refresh_rosters
                )

        close_button = QPushButton("Close")

        close_button.clicked.connect(
            self.accept
                )

        action_layout.addWidget(
            self.manage_members_button
                )

        action_layout.addWidget(
            self.archive_button
                )

        action_layout.addWidget(
            self.refresh_button
                )

        action_layout.addStretch()

        action_layout.addWidget(
            close_button
                )

        main_layout.addLayout(action_layout)

        self.status_label = QLabel("Ready.")
        main_layout.addWidget(self.status_label)

    # --------------------------------------------------
    # Load Teams
    # --------------------------------------------------

    def load_teams(self):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, name
                        FROM teams
                        WHERE organization_id = %s
                        ORDER BY name
                        """,
                        (self.organization_id,),
                    )

                    teams = cur.fetchall()

            self.team_selector.clear()

            for team_id, team_name in teams:
                self.team_selector.addItem(
                    team_name,
                    team_id,
                )

            if not teams:
                self.status_label.setText(
                    "No teams found. Create a team first."
                )

            else:
                self.refresh_rosters()

        except Exception as error:
            QMessageBox.critical(
                self,
                "Team Load Error",
                f"Could not load teams:\n\n{error}",
            )

    # --------------------------------------------------
    # Refresh Rosters
    # --------------------------------------------------

    def refresh_rosters(self, *args):
        team_id = self.team_selector.currentData()

        self.roster_table.setRowCount(0)

        if team_id is None:
            return

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id,
                            season,
                            status,
                            created_at
                        FROM team_rosters
                        WHERE organization_id = %s
                          AND team_id = %s
                        ORDER BY season DESC
                        """,
                        (
                            self.organization_id,
                            team_id,
                        ),
                    )

                    rosters = cur.fetchall()

            for roster in rosters:
                roster_id, season, status, created_at = roster

                row = self.roster_table.rowCount()
                self.roster_table.insertRow(row)

                values = [
                    str(season),
                    status.title(),
                    str(created_at),
                ]

                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)

                    if column == 0:
                        item.setData(
                             Qt.ItemDataRole.UserRole,
                            roster_id,
                        )

                    self.roster_table.setItem(
                        row,
                        column,
                        item,
                    )

            self.roster_table.resizeColumnsToContents()

            self.status_label.setText(
                f"{len(rosters)} roster(s) loaded."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Roster Load Error",
                f"Could not load rosters:\n\n{error}",
            )

    # --------------------------------------------------
    # Create Roster
    # --------------------------------------------------

    def create_roster(self):
        team_id = self.team_selector.currentData()
        season = self.season_input.value()

        if team_id is None:
            QMessageBox.warning(
                self,
                "Team Required",
                "Select a team before creating a roster.",
            )
            return

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO team_rosters (
                            organization_id,
                            team_id,
                            season,
                            status
                        )
                        VALUES (%s, %s, %s, 'active')
                        RETURNING id
                        """,
                        (
                            self.organization_id,
                            team_id,
                            season,
                        ),
                    )

                    roster_id = cur.fetchone()[0]

            self.refresh_rosters()

            self.status_label.setText(
                f"Created roster for {season}."
            )

        except Exception as error:
            QMessageBox.warning(
                self,
                "Roster Creation Error",
                (
                    "Could not create this roster.\n\n"
                    "A roster for this team and season may "
                    "already exist.\n\n"
                    f"Details: {error}"
                ),
            )

    # --------------------------------------------------
    # Archive Roster
    # --------------------------------------------------

    def archive_roster(self):
        selected_row = self.roster_table.currentRow()

        if selected_row < 0:
            QMessageBox.information(
                self,
                "Select a Roster",
                "Select a roster before archiving it.",
            )
            return

        item = self.roster_table.item(selected_row, 0)

        if item is None:
            return

        roster_id = item.data(
            Qt.ItemDataRole.UserRole
        )

        season = item.text()

        answer = QMessageBox.question(
            self,
            "Confirm Archive",
            (
                f"Archive the {season} roster?\n\n"
                "The roster will remain in the database "
                "but will no longer be active."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE team_rosters
                        SET status = 'archived',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND organization_id = %s
                        """,
                        (
                            roster_id,
                            self.organization_id,
                        ),
                    )

                    if cur.rowcount != 1:
                        raise ValueError(
                            "Roster not found or no longer available."
                        )

            self.refresh_rosters()

            self.status_label.setText(
                f"Archived the {season} roster."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Roster Archive Error",
                f"Could not archive roster:\n\n{error}",
            )

    # --------------------------------------------------
# Manage Roster Members
# --------------------------------------------------

    def update_manage_members_button(self):

        selected_row = self.roster_table.currentRow()

        self.manage_members_button.setEnabled(
            selected_row >= 0
        )


    def manage_roster_members(self):

        selected_row = self.roster_table.currentRow()

        if selected_row < 0:
            QMessageBox.information(
                self,
                "Select a Roster",
                "Select a roster before managing its members.",
            )
            return

        roster_item = self.roster_table.item(
            selected_row,
            0,
        )

        if roster_item is None:
            return

        roster_id = roster_item.data(
            Qt.ItemDataRole.UserRole
        )

        season = int(roster_item.text())

        team_name = self.team_selector.currentText()

        if roster_id is None:
            QMessageBox.warning(
                self,
                "Roster Error",
                "Could not determine the selected roster.",
            )
            return

        dialog = RosterMembershipManagementDialog(
            self.organization_id,
            roster_id,
            team_name,
            season,
            self.get_connection,
            self,
        )

        dialog.exec()