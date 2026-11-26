from dbm import error
from operator import index
import sys
import csv
from tkinter import dialog
import traceback
from turtle import title
from unittest import result
import psycopg

from PySide6.QtCore import Qt, QDate, QTimer

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QWidget,
    QDialog,
    QMessageBox,
    QFileDialog,
    QTableWidgetItem,

    # Layouts
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,

    # Display elements
    QLabel,
    QFrame,

    # Buttons and inputs
    QPushButton,
    QLineEdit,
    QComboBox,
    QDateEdit,
    QCheckBox,
    QSpinBox,
    QTextEdit,
    QDialogButtonBox,

    # Tables and navigation
    QTableWidget,
    QTableWidgetItem,
    QStackedWidget,
    QScrollArea,
)

from roster_management import RosterManagementDialog
from user_store import authenticate_user, create_user
from database import get_connection
from backup_manager import create_backup
from session_store import save_session, load_session, clear_session
from team_management import TeamManagementDialog
from player_management import PlayerManagementDialog



class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()

        self.user = None

        self.setWindowTitle("Football Intelligence Platform — Login")
        self.setFixedSize(380, 230)

        layout = QVBoxLayout(self)

        title = QLabel("Football Intelligence Platform")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; padding: 8px;"
        )
        layout.addWidget(title)

        layout.addWidget(QLabel("Username"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        layout.addWidget(self.username_input)

        layout.addWidget(QLabel("Password"))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.returnPressed.connect(self.login)
        layout.addWidget(self.password_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Log In")

        buttons.accepted.connect(self.login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.create_account_button = QPushButton("Create Account")
        self.create_account_button.clicked.connect(self.open_create_account)
        layout.addWidget(self.create_account_button)


    def open_create_account(self):
        dialog = CreateAccountDialog(self)
        dialog.exec()

    def login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Enter both your username and password.",
            )
            return

        try:
            user = authenticate_user(username, password)
        except Exception as error:
            QMessageBox.critical(
                self,
                "Login Error",
                f"Could not connect to the account database.\n\n{error}",
            )
            return

        if user is None:
            QMessageBox.warning(
                self,
                "Login Failed",
                "Incorrect username or password.",
            )
            self.password_input.clear()
            self.password_input.setFocus()
            return

        self.user = user
        self.accept()



class CreateGameDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Create Game")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Opponent / Game Name"))

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Example: Florida A&M 2026")
        layout.addWidget(self.name_input)

        buttons = QHBoxLayout()

        create_button = QPushButton("Create Game")
        cancel_button = QPushButton("Cancel")

        create_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        buttons.addWidget(create_button)
        buttons.addWidget(cancel_button)

        layout.addLayout(buttons)

    def get_game_name(self):
        return self.name_input.text().strip()



class GameSetupDialog(QDialog):
    def __init__(self, parent=None, game_data=None):
        super().__init__(parent)

        self.setWindowTitle("Game Setup")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        # Game name
        layout.addWidget(QLabel("Game Name"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Example: FAMU 2026")
        layout.addWidget(self.name_input)

        # Opponent
        layout.addWidget(QLabel("Opponent"))
        self.opponent_input = QLineEdit()
        self.opponent_input.setPlaceholderText("Example: Florida A&M")
        layout.addWidget(self.opponent_input)

        # Season
        layout.addWidget(QLabel("Season"))
        self.season_input = QSpinBox()
        self.season_input.setRange(2000, 2100)
        self.season_input.setValue(2026)
        layout.addWidget(self.season_input)

        # Game date
        layout.addWidget(QLabel("Game Date"))

        self.date_known = QCheckBox("I know the game date")
        layout.addWidget(self.date_known)

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setEnabled(False)
        self.date_known.toggled.connect(self.date_input.setEnabled)
        layout.addWidget(self.date_input)

        # Location
        layout.addWidget(QLabel("Location"))
        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText(
            "Example: Home, Away, or Neutral Site"
        )
        layout.addWidget(self.location_input)

        # Scouting focus
        layout.addWidget(QLabel("Scouting Focus"))
        self.focus_input = QComboBox()
        self.focus_input.addItems([
            "All",
            "Offense",
            "Defense",
            "Special Teams"
        ])
        layout.addWidget(self.focus_input)

        # General notes
        layout.addWidget(QLabel("General Notes"))
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText(
            "Enter general scouting notes about this game..."
        )
        self.notes_input.setMaximumHeight(110)
        layout.addWidget(self.notes_input)

        # Buttons
        buttons = QHBoxLayout()

        save_button = QPushButton("Save Game Setup")
        cancel_button = QPushButton("Cancel")

        save_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout.addLayout(buttons)

        # Load existing game information when editing
        if game_data:
            self.name_input.setText(game_data.get("name") or "")
            self.opponent_input.setText(game_data.get("opponent") or "")

            if game_data.get("season"):
                self.season_input.setValue(game_data["season"])

            if game_data.get("game_date"):
                self.date_known.setChecked(True)
                self.date_input.setDate(
                    QDate(
                        game_data["game_date"].year,
                        game_data["game_date"].month,
                        game_data["game_date"].day
                    )
                )

            self.location_input.setText(
                game_data.get("location") or ""
            )

            self.focus_input.setCurrentText(
                game_data.get("scouting_focus") or "All"
            )

            self.notes_input.setPlainText(
                game_data.get("general_notes") or ""
            )

    def get_game_data(self):
        return {
            "name": self.name_input.text().strip(),
            "opponent": self.opponent_input.text().strip(),
            "season": self.season_input.value(),
            "game_date": (
                self.date_input.date().toString("yyyy-MM-dd")
                if self.date_known.isChecked()
                else None
            ),
            "location": self.location_input.text().strip(),
            "scouting_focus": self.focus_input.currentText(),
            "general_notes": self.notes_input.toPlainText().strip()
        }





class CreateAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Create Account")
        self.setFixedSize(400, 320)

        layout = QVBoxLayout(self)

        title = QLabel("Create Your Account")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; padding: 8px;"
        )
        layout.addWidget(title)

        layout.addWidget(QLabel("Username"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Choose a username")
        layout.addWidget(self.username_input)

        layout.addWidget(QLabel("Password"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText(
            "At least 12 characters"
        )
        layout.addWidget(self.password_input)

        layout.addWidget(QLabel("Confirm Password"))
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.confirm_password_input.setPlaceholderText(
            "Enter the password again"
        )
        self.confirm_password_input.returnPressed.connect(
            self.create_account
        )
        layout.addWidget(self.confirm_password_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Create Account")

        buttons.accepted.connect(self.create_account)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def create_account(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        confirmation = self.confirm_password_input.text()

        if not username or not password or not confirmation:
            QMessageBox.warning(
                self,
                "Missing Information",
                "Complete all three fields.",
            )
            return

        if len(username) > 50:
            QMessageBox.warning(
                self,
                "Invalid Username",
                "Username cannot exceed 50 characters.",
            )
            return

        if len(password) < 12:
            QMessageBox.warning(
                self,
                "Password Too Short",
                "Your password must be at least 12 characters.",
            )
            return

        if password != confirmation:
            QMessageBox.warning(
                self,
                "Passwords Do Not Match",
                "Enter the same password in both password fields.",
            )
            self.confirm_password_input.clear()
            self.confirm_password_input.setFocus()
            return

        try:
            create_user(username, password)
        except ValueError as error:
            QMessageBox.warning(
                self,
                "Could Not Create Account",
                str(error),
            )
            return
        except Exception:
            QMessageBox.critical(
                self,
                "Account Creation Error",
                "The account could not be created. "
                "Check the database connection and try again.",
            )
            return

        QMessageBox.information(
            self,
            "Account Created",
            f"Account '{username}' was created successfully.",
        )
        self.accept()






def optional_int(value, field_name):
    value = value.strip()

    if value == "":
        return None

    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"{field_name} must be a whole number or left blank."
        )

class StatisticsDialog(QDialog):
    def __init__(self, game_name, organization_id, parent=None):
        self.organization_id = organization_id
        super().__init__(parent)

        self.setWindowTitle(f"Game Statistics — {game_name}")
        self.resize(450, 300)

        layout = QVBoxLayout(self)

        title = QLabel(f"STATISTICS: {game_name}")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; padding: 8px;"
        )
        layout.addWidget(title)

        self.stats_grid = QGridLayout()
        layout.addLayout(self.stats_grid)

        self.value_labels = {}

        metrics = [
            ("total", "Total Plays Recorded"),
            ("runs", "Runs"),
            ("passes", "Passes"),
            ("no_plays", "No-Plays"),
            ("untagged", "Untagged Plays"),
            ("run_pct", "Run Percentage"),
            ("pass_pct", "Pass Percentage"),
        ]

        for row, (key, label_text) in enumerate(metrics):
            name_label = QLabel(label_text + ":")
            value_label = QLabel("Loading...")

            value_label.setStyleSheet("font-weight: bold;")

            self.stats_grid.addWidget(name_label, row, 0)
            self.stats_grid.addWidget(value_label, row, 1)

            self.value_labels[key] = value_label

        self.load_statistics(game_name)

    def load_statistics(self, game_name):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
SELECT
    COUNT(*),
    COUNT(*) FILTER (
        WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
    ),
    COUNT(*) FILTER (
        WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
    ),
    COUNT(*) FILTER (
        WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'N'
    ),
    COUNT(*) FILTER (
        WHERE TRIM(COALESCE(rpn, '')) = ''
    )
FROM plays
WHERE game_name = %s
  AND organization_id = %s
""",
                        (game_name, self.organization_id),
                    )

                    total, runs, passes, no_plays, untagged = (
                        cur.fetchone()
                    )

            tagged_run_pass = runs + passes

            if tagged_run_pass:
                run_pct = f"{runs / tagged_run_pass * 100:.1f}%"
                pass_pct = f"{passes / tagged_run_pass * 100:.1f}%"
            else:
                run_pct = "N/A"
                pass_pct = "N/A"

            values = {
                "total": total,
                "runs": runs,
                "passes": passes,
                "no_plays": no_plays,
                "untagged": untagged,
                "run_pct": run_pct,
                "pass_pct": pass_pct,
            }

            for key, value in values.items():
                self.value_labels[key].setText(str(value))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Statistics Error",
                f"Could not load statistics.\n\n{error}",
            )
            self.close()



class ReportsDialog(QDialog):
    def __init__(
        self,
        game_id,
        game_name,
        organization_id,
        report_type="Game Summary",
        parent=None
    ):
        super().__init__(parent)

        self.game_id = game_id
        self.game_name = game_name
        self.organization_id = organization_id
        self.report_type = report_type

        self.setWindowTitle(
            f"{self.report_type} — {self.game_name}"
        )
        self.resize(650, 500)

        layout = QVBoxLayout(self)

        title = QLabel(
            f"{self.report_type.upper()}: {self.game_name}"
                    )
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; padding: 8px;"
        )
        layout.addWidget(title)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        layout.addWidget(self.report_text)

        export_button = QPushButton("Export Plays to CSV")
        export_button.clicked.connect(self.export_csv)
        layout.addWidget(export_button)

        self.load_report()

    def load_report(self):
        if self.report_type == "Situational Report":
            self.load_situational_report()
            return
        if self.report_type == "Offensive Report":
            self.load_offensive_report()
            return
        if self.report_type == "Defensive Report":
            self.load_defensive_report()
            return


        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                            ),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                            ),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'N'
                            ),
                            COUNT(*) FILTER (
                                WHERE TRIM(COALESCE(rpn, '')) = ''
                            ),
                            AVG(yards_gained) FILTER (
                                WHERE yards_gained IS NOT NULL
                                  AND UPPER(TRIM(COALESCE(rpn, '')))
                                      IN ('R', 'P')
                            )
                        FROM plays
WHERE game_id = %s
  AND organization_id = %s
                        """,
                        (self.game_id, self.organization_id),
                    )

                    total, runs, passes, no_plays, untagged, avg_yards = (
                        cur.fetchone()
                    )

            run_pass_total = runs + passes

            if run_pass_total:
                run_pct = runs / run_pass_total * 100
                pass_pct = passes / run_pass_total * 100
            else:
                run_pct = pass_pct = None

            def percentage(value):
                return f"{value:.1f}%" if value is not None else "N/A"

            average_text = (
                f"{avg_yards:.2f} yards"
                if avg_yards is not None
                else "N/A"
            )

            report = [
                f"Game: {self.game_name}",
                "",
                "PLAY SUMMARY",
                f"Total plays recorded: {total}",
                f"Runs: {runs}",
                f"Passes: {passes}",
                f"No-plays: {no_plays}",
                f"Untagged plays: {untagged}",
                "",
                "RUN/PASS TENDENCY",
                f"Run percentage: {percentage(run_pct)}",
                f"Pass percentage: {percentage(pass_pct)}",
                "",
                "YARDAGE",
                f"Average yards gained on recorded runs/passes: "
                f"{average_text}",
                "",
                "NOTES",
                "Run/pass percentages exclude no-plays and untagged plays.",
                "Average yardage excludes plays with missing yardage and "
                "no-plays.",
            ]

            self.report_text.setPlainText("\n".join(report))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Report Error",
                f"Could not generate the report.\n\n{error}",
            )
            self.close()

    def load_situational_report(self):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:

                    # DOWN AND DISTANCE BREAKDOWN
                    cur.execute(
                        """
                        SELECT
                            down,
                            CASE
                                WHEN distance BETWEEN 1 AND 3
                                    THEN 'Short (1-3)'
                                WHEN distance BETWEEN 4 AND 6
                                    THEN 'Medium (4-6)'
                                WHEN distance >= 7
                                    THEN 'Long (7+)'
                            END AS distance_group,
                            COUNT(*),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                            ),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                            )
                        FROM plays
                        WHERE game_id = %s
                          AND organization_id = %s
                          AND down IS NOT NULL
                          AND distance >= 1
                        GROUP BY down, distance_group
                        ORDER BY down, MIN(distance)
                        """,
                        (self.game_id, self.organization_id),
                    )

                    down_distance_rows = cur.fetchall()

                    # QUARTER BREAKDOWN
                    cur.execute(
                        """
                        SELECT
                            quarter,
                            COUNT(*),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                            ),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                            )
                        FROM plays
                        WHERE game_id = %s
                          AND organization_id = %s
                          AND quarter IS NOT NULL
                        GROUP BY quarter
                        ORDER BY quarter
                        """,
                        (self.game_id, self.organization_id),
                    )

                    quarter_rows = cur.fetchall()

                    # FIELD POSITION BREAKDOWN
                    cur.execute(
                        """
                        SELECT
                            CASE
                                WHEN yardline BETWEEN -20 AND -1
                                    THEN 'Own 1-20'
                                WHEN yardline BETWEEN -49 AND -21
                                    THEN 'Own 21-49'
                                WHEN yardline = 50
                                    THEN 'Midfield'
                                WHEN yardline BETWEEN 21 AND 49
                                    THEN 'Opp 21-49'
                                WHEN yardline BETWEEN 1 AND 20
                                    THEN 'Opp 1-20'
                            END AS field_zone,

                            CASE
                                WHEN yardline BETWEEN -20 AND -1 THEN 1
                                WHEN yardline BETWEEN -49 AND -21 THEN 2
                                WHEN yardline = 50 THEN 3
                                WHEN yardline BETWEEN 21 AND 49 THEN 4
                                WHEN yardline BETWEEN 1 AND 20 THEN 5
                            END AS zone_order,

                            COUNT(*),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                            ),
                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                            )
                        FROM plays
                        WHERE game_id = %s
                          AND organization_id = %s
                          AND yardline IS NOT NULL
                          AND yardline <> 0
                        GROUP BY field_zone, zone_order
                        ORDER BY zone_order
                        """,
                        (self.game_id, self.organization_id),
                    )

                    field_rows = cur.fetchall()

            # REPORT FORMATTING
            report = [
                f"GAME: {self.game_name}",
                "",
                "SITUATIONAL SCOUTING REPORT",
                "",
                "DOWN AND DISTANCE TENDENCIES",
            ]

            def add_tendency_section(rows, labels):
                if not rows:
                    report.append("No recorded data available.")
                    report.append("")
                    return

                for row in rows:
                    plays = row[-3]
                    runs = row[-2]
                    passes = row[-1]

                    run_pass_total = runs + passes

                    if run_pass_total:
                        run_pct = runs / run_pass_total * 100
                        pass_pct = passes / run_pass_total * 100
                    else:
                        run_pct = pass_pct = None

                    report.append(
                        f"{labels(row)} | "
                        f"Plays: {plays} | "
                        f"Runs: {runs} | "
                        f"Passes: {passes} | "
                        f"Run: {run_pct:.1f}% | "
                        f"Pass: {pass_pct:.1f}%"
                        if run_pass_total
                        else (
                            f"{labels(row)} | "
                            f"Plays: {plays} | "
                            f"Runs: {runs} | "
                            f"Passes: {passes} | "
                            "No classified run/pass plays"
                        )
                    )

                report.append("")

            # DOWN AND DISTANCE
            add_tendency_section(
                down_distance_rows,
                lambda row: f"{row[0]} Down / {row[1]}"
            )

            # QUARTER
            report.append("QUARTER BREAKDOWN")

            add_tendency_section(
                quarter_rows,
                lambda row: f"Quarter {row[0]}"
            )

            # FIELD POSITION
            report.append("FIELD POSITION BREAKDOWN")

            add_tendency_section(
                field_rows,
                lambda row: row[0]
            )

            report.extend([
                "NOTES",
                "Run/pass percentages exclude no-plays and untagged plays.",
                "Field position uses the signed yardline system, "
                "with 50 representing midfield.",
                "Distance categories: Short (1-3), Medium (4-6), "
                "Long (7+).",
            ])

            self.report_text.setPlainText("\n".join(report))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Situational Report Error",
                f"Could not generate the situational report.\n\n{error}",
            )
            self.close()


    def load_offensive_report(self):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:

                    # Overall offensive production
                    cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'N'
                        ),
                        COUNT(*) FILTER (
                            WHERE TRIM(COALESCE(rpn, '')) = ''
                        ),
                        COALESCE(SUM(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ), 0),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        MAX(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COALESCE(SUM(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ), 0),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        MAX(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, '')))
                                IN ('R', 'P')
                        )
                        FROM plays
                        WHERE game_id = %s
                        AND organization_id = %s
                        """,
                        (self.game_id, self.organization_id),
                    )

                    (
                        runs, passes, no_plays, untagged,
                        run_yards, run_avg, longest_run,
                        pass_yards, pass_avg, longest_pass,
                        overall_avg
                    ) = cur.fetchone()

                # Run/pass production by down
                    cur.execute(
                        """
                        SELECT
                        down,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        )
                    FROM plays
                    WHERE game_id = %s
                      AND organization_id = %s
                      AND down IS NOT NULL
                      AND UPPER(TRIM(COALESCE(rpn, ''))) IN ('R', 'P')
                    GROUP BY down
                    ORDER BY down
                    """,
                        (self.game_id, self.organization_id),
                    )

                    down_rows = cur.fetchall()

                # Run/pass production by quarter
                    cur.execute(
                        """
                        SELECT
                        quarter,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        )
                    FROM plays
                    WHERE game_id = %s
                      AND organization_id = %s
                      AND quarter IS NOT NULL
                      AND UPPER(TRIM(COALESCE(rpn, ''))) IN ('R', 'P')
                    GROUP BY quarter
                    ORDER BY quarter
                    """,
                        (self.game_id, self.organization_id),
                )

                    quarter_rows = cur.fetchall()

        # Formatting helpers
            def average_text(value):
                if value is None:
                    return "N/A"
                return f"{value:.2f} yards"

            def longest_text(value):
                if value is None:
                    return "N/A"
                return f"{value} yards"

            def tendency_text(runs, passes):
                total = runs + passes
                if total == 0:
                    return "No classified plays"

                run_pct = runs / total * 100
                pass_pct = passes / total * 100

                return (
                    f"Runs: {runs} ({run_pct:.1f}%) | "
                    f"Passes: {passes} ({pass_pct:.1f}%)"
                )

            # Build report
            total_plays = runs + passes
            report = [
                f"GAME: {self.game_name}",
                "",
                "OFFENSIVE SCOUTING REPORT",
                "",
                "OFFENSIVE OVERVIEW",
                f"Total classified offensive plays: {total_plays}",
                f"Run plays: {runs}",
                f"Pass plays: {passes}",
                f"Run/pass distribution: {tendency_text(runs, passes)}",
                f"Average yards per play: {average_text(overall_avg)}",
                "",
                "RUSHING PRODUCTION",
                f"Total rushing yards: {run_yards}",
                f"Average yards per run: {average_text(run_avg)}",
                f"Longest recorded run: {longest_text(longest_run)}",
                "",
                "PASSING PRODUCTION",
                f"Total passing yards: {pass_yards}",
                f"Average yards per pass: {average_text(pass_avg)}",
                f"Longest recorded pass: {longest_text(longest_pass)}",
                "",
                "RUN/PASS TENDENCIES BY DOWN",
            ]

            if down_rows:
                for row in down_rows:
                    down, down_runs, down_passes, down_run_avg, down_pass_avg = row

                    report.append(
                        f"{down} Down | "
                        f"{tendency_text(down_runs, down_passes)}"
                    )
                    report.append(
                        f"    Average yards — Run: {average_text(down_run_avg)} | "
                        f"Pass: {average_text(down_pass_avg)}"
                    )
            else:
                report.append("No down data available.")

            report.extend([
                "",
                "RUN/PASS PRODUCTION BY QUARTER",
            ])

            if quarter_rows:
                for row in quarter_rows:
                    quarter, q_runs, q_passes, q_run_avg, q_pass_avg = row

                    report.append(
                        f"Quarter {quarter} | "
                        f"{tendency_text(q_runs, q_passes)}"
                    )
                    report.append(
                        f"    Average yards — Run: {average_text(q_run_avg)} | "
                        f"Pass: {average_text(q_pass_avg)}"
                    )
            else:
                report.append("No quarter data available.")

            report.extend([
                "",
                "DATA QUALITY",
                f"No-plays recorded: {no_plays}",
                f"Untagged plays: {untagged}",
                "",
                "NOTES",
                "Run/pass tendencies exclude no-plays and untagged plays.",
            "Yardage averages exclude plays with missing yardage.",
            "Passing production represents recorded yards, not completion percentage.",
            "This report uses only fields currently recorded in the database.",
        ])

            self.report_text.setPlainText("\n".join(report))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Offensive Report Error",
                f"Could not generate the offensive report:\n{error}"
            )
            self.close()




    def load_defensive_report(self):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:

                # Overall production allowed
                    cur.execute(
                    """
                    SELECT
                        COUNT(*),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'N'
                        ),
                        COUNT(*) FILTER (
                            WHERE TRIM(COALESCE(rpn, '')) = ''
                        ),
                        COALESCE(SUM(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, '')))
                                IN ('R', 'P')
                        ), 0),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, '')))
                                IN ('R', 'P')
                        ),
                        COALESCE(SUM(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ), 0),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        MAX(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COALESCE(SUM(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ), 0),
                        AVG(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        MAX(yards_gained) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        )
                    FROM plays
                    WHERE game_id = %s
                      AND organization_id = %s
                    """,
                        (self.game_id, self.organization_id),
                    )

                    (
                        total, runs, passes, no_plays, untagged,
                        total_yards, overall_avg,
                        run_yards, run_avg, longest_run,
                        pass_yards, pass_avg, longest_pass
                    ) = cur.fetchone()

                    # Yardage allowed by down
                    cur.execute(
                        """
                        SELECT
                        down,
                        COUNT(*),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        AVG(yards_gained),
                        SUM(yards_gained)
                    FROM plays
                    WHERE game_id = %s
                      AND organization_id = %s
                      AND down IS NOT NULL
                      AND UPPER(TRIM(COALESCE(rpn, ''))) IN ('R', 'P')
                    GROUP BY down
                    ORDER BY down
                    """,
                        (self.game_id, self.organization_id),
                    )

                    down_rows = cur.fetchall()

                # Yardage allowed by quarter
                    cur.execute(
                    """
                    SELECT
                        quarter,
                        COUNT(*),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),
                        AVG(yards_gained),
                        SUM(yards_gained)
                    FROM plays
                    WHERE game_id = %s
                      AND organization_id = %s
                      AND quarter IS NOT NULL
                      AND UPPER(TRIM(COALESCE(rpn, ''))) IN ('R', 'P')
                    GROUP BY quarter
                    ORDER BY quarter
                    """,
                        (self.game_id, self.organization_id),
                    )

                    quarter_rows = cur.fetchall()

            def average_text(value):
                if value is None:
                    return "N/A"
                return f"{value:.2f} yards"

            def longest_text(value):
                if value is None:
                    return "N/A"
                return f"{value} yards"

            def percentage(value, total_plays):
                if total_plays == 0:
                    return "N/A"
                return f"{value / total_plays * 100:.1f}%"

            report = [
                f"GAME: {self.game_name}",
                "",
            "DEFENSIVE SCOUTING REPORT",
            "",
            "DEFENSIVE OVERVIEW",
            f"Total plays faced: {total}",
            f"Runs faced: {runs}",
            f"Passes faced: {passes}",
            f"No-plays: {no_plays}",
            f"Untagged plays: {untagged}",
            f"Run percentage faced: {percentage(runs, runs + passes)}",
            f"Pass percentage faced: {percentage(passes, runs + passes)}",
            "",
            "YARDAGE ALLOWED",
            f"Total recorded yards allowed: {total_yards}",
            f"Average yards allowed per play: {average_text(overall_avg)}",
            "",
            "RUSHING DEFENSE",
            f"Runs faced: {runs}",
            f"Rushing yards allowed: {run_yards}",
            f"Average yards allowed per run: {average_text(run_avg)}",
            f"Longest recorded run allowed: {longest_text(longest_run)}",
            "",
            "PASS DEFENSE",
            f"Passes faced: {passes}",
            f"Passing yards allowed: {pass_yards}",
            f"Average yards allowed per pass: {average_text(pass_avg)}",
            f"Longest recorded pass allowed: {longest_text(longest_pass)}",
            "",
            "YARDAGE ALLOWED BY DOWN",
            ]

            if down_rows:
                for row in down_rows:
                    down, plays, down_runs, down_passes, avg_yards, yards = row

                    report.append(
                        f"{down} Down | Plays: {plays} | "
                        f"Runs: {down_runs} | Passes: {down_passes}"
                    )
                    report.append(
                        f"    Total yards allowed: {yards} | "
                        f"Average yards allowed: {average_text(avg_yards)}"
                    )
            else:
                report.append("No down data available.")

            report.extend([
                "",
                "YARDAGE ALLOWED BY QUARTER",
            ])

            if quarter_rows:
                for row in quarter_rows:
                    quarter, plays, q_runs, q_passes, avg_yards, yards = row

                    report.append(
                        f"Quarter {quarter} | Plays: {plays} | "
                        f"Runs: {q_runs} | Passes: {q_passes}"
                    )
                    report.append(
                        f"    Total yards allowed: {yards} | "
                        f"Average yards allowed: {average_text(avg_yards)}"
                    )
            else:
                report.append("No quarter data available.")

            report.extend([
            "",
            "NOTES",
            "This report measures offensive production against the defense.",
            "Run/pass percentages exclude no-plays and untagged plays.",
            "Yardage averages exclude plays with missing yardage.",
            "Defensive formations, coverages, stops, and individual "
            "player performance are not currently tracked.",
            ])

            self.report_text.setPlainText("\n".join(report))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Defensive Report Error",
                f"Could not generate the defensive report:\n{error}"
            )
            self.close()







    def export_csv(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plays",
            f"{self.game_name.replace(' ', '_')}_plays.csv",
            "CSV Files (*.csv)",
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".csv"):
            file_path += ".csv"

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            id,
                            game_name,
                            series_number,
                            play_number,
                            quarter,
                            game_time,
                            down,
                            distance,
                            hash,
                            yardline,
                            rpn,
                            yards_gained,
                            result_reason,
                            created_at
                        FROM plays
                        WHERE game_id = %s AND organization_id = %s
                        ORDER BY series_number, play_number, id
                        """,
                        (self.game_id,  self.organization_id),
                    )

                    rows = cur.fetchall()
                    headers = [column.name for column in cur.description]

            with open(
                file_path,
                "w",
                newline="",
                encoding="utf-8-sig",
            ) as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(headers)
                writer.writerows(rows)

            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(rows)} plays to:\n{file_path}",
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Could not export plays.\n\n{error}",
            )




class SituationalAnalysisDialog(QDialog):
    def __init__(self, game_id, game_name, organization_id, parent=None):
        super().__init__(parent)

        self.game_id = game_id
        self.game_name = game_name
        self.organization_id = organization_id

        self.rows = []

        self.setWindowTitle(f"Situational Analysis — {game_name}")
        self.resize(850, 600)

        layout = QVBoxLayout(self)

        title = QLabel(f"SITUATIONAL TENDENCIES: {game_name}")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; padding: 8px;"
        )
        layout.addWidget(title)

        explanation = QLabel(
            "Groups recorded plays by down and distance. "
            "Only plays with recorded down and distance are included."
        )
        layout.addWidget(explanation)

        self.results = QTextEdit()
        self.results.setReadOnly(True)
        layout.addWidget(self.results)

        export_button = QPushButton("Export Tendencies to CSV")
        export_button.clicked.connect(self.export_csv)
        layout.addWidget(export_button)

        self.load_analysis()

    def load_analysis(self):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            down,
                            distance,
                            COUNT(*) AS total_plays,

                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                            ) AS runs,

                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                            ) AS passes,

                            COUNT(*) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'N'
                            ) AS no_plays,

                            COUNT(*) FILTER (
                                WHERE TRIM(COALESCE(rpn, '')) = ''
                            ) AS untagged,

                            AVG(yards_gained) FILTER (
                                WHERE UPPER(TRIM(COALESCE(rpn, '')))
                                      IN ('R', 'P')
                                  AND yards_gained IS NOT NULL
                            ) AS average_yards

                        FROM plays
                        WHERE game_id = %s
                          AND organization_id = %s
                          AND down IS NOT NULL
                          AND distance IS NOT NULL
                        GROUP BY down, distance
                        ORDER BY down, distance
                        """,
                        (self.game_id, self.organization_id),
                    )

                    self.rows = cur.fetchall()

            if not self.rows:
                self.results.setPlainText(
                    "No plays have both down and distance recorded yet."
                )
                return

            lines = [
                "DOWN & DISTANCE BREAKDOWN",
                "",
                "Down | Distance | Total | Runs | Passes | "
                "Run % | Pass % | Avg Yards",
                "-" * 78,
            ]

            for (
                down,
                distance,
                total,
                runs,
                passes,
                no_plays,
                untagged,
                average_yards,
            ) in self.rows:

                run_pass_total = runs + passes

                if run_pass_total:
                    run_pct = f"{runs / run_pass_total * 100:.1f}%"
                    pass_pct = f"{passes / run_pass_total * 100:.1f}%"
                else:
                    run_pct = "N/A"
                    pass_pct = "N/A"

                avg_text = (
                    f"{average_yards:.2f}"
                    if average_yards is not None
                    else "N/A"
                )

                lines.append(
                    f"{down} | {distance} | {total} | {runs} | "
                    f"{passes} | {run_pct} | {pass_pct} | {avg_text}"
                )

                lines.append(
                    f"    No-plays: {no_plays} | Untagged: {untagged}"
                )

            lines.extend([
                "",
                "HOW TO READ THIS",
                "Run/pass percentages exclude no-plays and untagged plays.",
                "Average yards excludes missing yardage and untagged play "
                "types.",
                "Small sample sizes can make a tendency misleading.",
            ])

            self.results.setPlainText("\n".join(lines))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Analysis Error",
                f"Could not load situational analysis.\n\n{error}",
            )
            self.close()

    def export_csv(self):
        if not self.rows:
            QMessageBox.information(
                self,
                "No Data",
                "There are no situational results to export.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Situational Analysis",
            f"game_{self.game_id}_tendencies.csv",
            "CSV Files (*.csv)",
        )

        if not file_path:
            return

        if not file_path.lower().endswith(".csv"):
            file_path += ".csv"

        try:
            with open(
                file_path,
                "w",
                newline="",
                encoding="utf-8-sig",
            ) as csv_file:
                writer = csv.writer(csv_file)

                writer.writerow([
                    "Down",
                    "Distance",
                    "Total Plays",
                    "Runs",
                    "Passes",
                    "No-Plays",
                    "Untagged",
                    "Run Percentage",
                    "Pass Percentage",
                    "Average Yards",
                ])

                for row in self.rows:
                    (
                        down,
                        distance,
                        total,
                        runs,
                        passes,
                        no_plays,
                        untagged,
                        average_yards,
                    ) = row

                    denominator = runs + passes

                    run_pct = (
                        round(runs / denominator * 100, 1)
                        if denominator else None
                    )
                    pass_pct = (
                        round(passes / denominator * 100, 1)
                        if denominator else None
                    )

                    writer.writerow([
                        down,
                        distance,
                        total,
                        runs,
                        passes,
                        no_plays,
                        untagged,
                        run_pct,
                        pass_pct,
                        (
                            round(average_yards, 2)
                            if average_yards is not None else None
                        ),
                    ])

            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(self.rows)} down-and-distance groups to:\n"
                f"{file_path}",
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Could not export tendencies.\n\n{error}",
            )


class SeasonReportsDialog(QDialog):
    def __init__(
        self,
        selected_season,
        organization_id,
        report_type="Season Summary",
        parent=None
    ):
        super().__init__(parent)

        self.selected_season = selected_season
        self.organization_id = organization_id
        self.report_type = report_type

        if selected_season == "all":
            self.season_name = "All Seasons"
        elif selected_season == "unassigned":
            self.season_name = "Unassigned Season"
        else:
            self.season_name = str(selected_season)

        self.setWindowTitle(
            f"{report_type} — {self.season_name}"
        )
        self.resize(750, 600)

        layout = QVBoxLayout(self)

        title = QLabel(
            f"{report_type.upper()}: {self.season_name}"
        )
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; padding: 8px;"
        )
        layout.addWidget(title)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        layout.addWidget(self.report_text)

        self.load_report()

    def get_season_filter(self):
        if self.selected_season == "unassigned":
            return "AND g.season IS NULL", []

        if self.selected_season == "all":
            return "", []

        return "AND g.season = %s", [self.selected_season]

    def load_report(self):
        if self.report_type == "Season Tendencies":
            self.load_season_tendencies()
        else:
            self.load_season_summary()

    def load_season_summary(self):
        try:
            season_filter, season_params = self.get_season_filter()

            with get_connection() as conn:
                with conn.cursor() as cur:

                    # Overall season production
                    cur.execute(
                        f"""
                        SELECT
                            COUNT(DISTINCT g.id),
                            COUNT(p.id),

                            COUNT(p.id) FILTER (
                                WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'R'
                            ),

                            COUNT(p.id) FILTER (
                                WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'P'
                            ),

                            COUNT(p.id) FILTER (
                                WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'N'
                            ),

                            COUNT(p.id) FILTER (
                                WHERE TRIM(COALESCE(p.rpn, '')) = ''
                            ),

                            AVG(p.yards_gained) FILTER (
                                WHERE UPPER(TRIM(COALESCE(p.rpn, '')))
                                    IN ('R', 'P')
                                  AND p.yards_gained IS NOT NULL
                            )

                        FROM games g

                        LEFT JOIN plays p
                            ON p.game_id = g.id
                           AND p.organization_id = g.organization_id

                        WHERE g.organization_id = %s
                        {season_filter}
                        """,
                        (self.organization_id, *season_params),
                    )

                    (
                        total_games,
                        total_plays,
                        runs,
                        passes,
                        no_plays,
                        untagged,
                        avg_yards
                    ) = cur.fetchone()

                    # Individual game production
                    cur.execute(
                        f"""
                        SELECT
                            g.name,
                            g.opponent,
                            g.game_date,
                            COUNT(p.id),

                            COUNT(p.id) FILTER (
                                WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'R'
                            ),

                            COUNT(p.id) FILTER (
                                WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'P'
                            ),

                            AVG(p.yards_gained) FILTER (
                                WHERE UPPER(TRIM(COALESCE(p.rpn, '')))
                                    IN ('R', 'P')
                                  AND p.yards_gained IS NOT NULL
                            )

                        FROM games g

                        LEFT JOIN plays p
                            ON p.game_id = g.id
                           AND p.organization_id = g.organization_id

                        WHERE g.organization_id = %s
                        {season_filter}

                        GROUP BY
                            g.id,
                            g.name,
                            g.opponent,
                            g.game_date

                        ORDER BY
                            g.game_date NULLS LAST,
                            g.name
                        """,
                        (self.organization_id, *season_params),
                    )

                    game_rows = cur.fetchall()

            total_games = total_games or 0
            total_plays = total_plays or 0
            runs = runs or 0
            passes = passes or 0
            no_plays = no_plays or 0
            untagged = untagged or 0

            classified = runs + passes

            if classified:
                run_pct = runs / classified * 100
                pass_pct = passes / classified * 100
            else:
                run_pct = pass_pct = None

            def percentage(value):
                return (
                    f"{value:.1f}%"
                    if value is not None
                    else "N/A"
                )

            report = [
                f"REPORT: {self.season_name}",
                "",
                "SEASON OVERVIEW",
                f"Games scouted: {total_games}",
                f"Total plays recorded: {total_plays}",
                f"Run plays: {runs}",
                f"Pass plays: {passes}",
                f"No-plays: {no_plays}",
                f"Untagged plays: {untagged}",
                "",
                "RUN/PASS DISTRIBUTION",
                f"Run percentage: {percentage(run_pct)}",
                f"Pass percentage: {percentage(pass_pct)}",
                "",
                "YARDAGE PRODUCTION",
                (
                    f"Average yards per classified play: "
                    f"{avg_yards:.2f}"
                    if avg_yards is not None
                    else "Average yards per classified play: N/A"
                ),
                "",
                "GAME-BY-GAME PRODUCTION",
            ]

            if game_rows:
                for row in game_rows:
                    (
                        game_name,
                        opponent,
                        game_date,
                        plays,
                        game_runs,
                        game_passes,
                        game_avg
                    ) = row

                    opponent_text = opponent or "Unknown opponent"

                    date_text = (
                        game_date.strftime("%Y-%m-%d")
                        if game_date
                        else "Date unavailable"
                    )

                    report.extend([
                        "",
                        f"{game_name} — {opponent_text}",
                        f"Date: {date_text}",
                        f"Total recorded plays: {plays}",
                        f"Runs: {game_runs}",
                        f"Passes: {game_passes}",
                        (
                            f"Average yards: {game_avg:.2f}"
                            if game_avg is not None
                            else "Average yards: N/A"
                        ),
                    ])
            else:
                report.append("No games available.")

            report.extend([
                "",
                "NOTES",
                "Run/pass percentages exclude no-plays and untagged plays.",
                "Average yardage excludes missing yardage and "
                "unclassified plays.",
                "This report uses only data currently recorded "
                "in the database.",
            ])

            self.report_text.setPlainText("\n".join(report))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Season Report Error",
                f"Could not generate the season summary.\n\n{error}",
            )
            self.close()

    def load_season_tendencies(self):
        try:
            season_filter, season_params = self.get_season_filter()

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        WITH selected_plays AS (
                            SELECT
                                p.down,
                                p.quarter,
                                p.yardline,
                                p.rpn,
                                p.yards_gained

                            FROM games g

                            JOIN plays p
                                ON p.game_id = g.id
                               AND p.organization_id = g.organization_id

                            WHERE g.organization_id = %s
                            {season_filter}
                              AND UPPER(TRIM(COALESCE(p.rpn, '')))
                                  IN ('R', 'P')
                        ),

                        positioned_plays AS (
                            SELECT *,
                                CASE
                                    WHEN yardline = 50
                                        THEN 'Midfield'
                                    WHEN yardline BETWEEN -20 AND -1
                                        THEN 'Own 1-20'
                                    WHEN yardline BETWEEN -49 AND -21
                                        THEN 'Own 21-49'
                                    WHEN yardline BETWEEN 1 AND 20
                                        THEN 'Opponent 1-20'
                                    WHEN yardline BETWEEN 21 AND 49
                                        THEN 'Opponent 21-49'
                                END AS field_position
                            FROM selected_plays
                        ),

                        tendency_rows AS (

                            SELECT
                                1 AS sort_group,
                                down AS sort_order,
                                down::TEXT || ' Down' AS situation,
                                COUNT(*) AS plays,

                                COUNT(*) FILTER (
                                    WHERE UPPER(TRIM(rpn)) = 'R'
                                ) AS runs,

                                COUNT(*) FILTER (
                                    WHERE UPPER(TRIM(rpn)) = 'P'
                                ) AS passes,

                                AVG(yards_gained) AS avg_yards

                            FROM selected_plays
                            WHERE down IS NOT NULL
                            GROUP BY down

                            UNION ALL

                            SELECT
                                2 AS sort_group,
                                quarter AS sort_order,
                                'Quarter ' || quarter AS situation,
                                COUNT(*) AS plays,

                                COUNT(*) FILTER (
                                    WHERE UPPER(TRIM(rpn)) = 'R'
                                ) AS runs,

                                COUNT(*) FILTER (
                                    WHERE UPPER(TRIM(rpn)) = 'P'
                                ) AS passes,

                                AVG(yards_gained) AS avg_yards

                            FROM selected_plays
                            WHERE quarter IS NOT NULL
                            GROUP BY quarter

                            UNION ALL

                            SELECT
                                3 AS sort_group,

                                CASE field_position
                                    WHEN 'Own 1-20' THEN 1
                                    WHEN 'Own 21-49' THEN 2
                                    WHEN 'Midfield' THEN 3
                                    WHEN 'Opponent 21-49' THEN 4
                                    WHEN 'Opponent 1-20' THEN 5
                                END AS sort_order,

                                field_position AS situation,
                                COUNT(*) AS plays,

                                COUNT(*) FILTER (
                                    WHERE UPPER(TRIM(rpn)) = 'R'
                                ) AS runs,

                                COUNT(*) FILTER (
                                    WHERE UPPER(TRIM(rpn)) = 'P'
                                ) AS passes,

                                AVG(yards_gained) AS avg_yards

                            FROM positioned_plays
                            WHERE field_position IS NOT NULL
                            GROUP BY field_position
                        )

                        SELECT
                            situation,
                            plays,
                            runs,
                            passes,
                            avg_yards
                        FROM tendency_rows
                        ORDER BY sort_group, sort_order
                        """,
                        (self.organization_id, *season_params),
                    )

                    results = cur.fetchall()

            report = [
                f"REPORT: {self.season_name}",
                "",
                "SEASON TENDENCIES",
                "",
            ]

            current_section = None

            section_names = {
                1: "DOWN TENDENCIES",
                2: "QUARTER TENDENCIES",
                3: "FIELD POSITION TENDENCIES",
            }

            # The query returns the situation label but not its
            # section number, so divide results by their known order.
            # Re-querying is unnecessary; identify sections by label.
            for situation, plays, runs, passes, avg_yards in results:

                if "Down" in situation:
                    section = "DOWN TENDENCIES"
                elif situation.startswith("Quarter"):
                    section = "QUARTER TENDENCIES"
                else:
                    section = "FIELD POSITION TENDENCIES"

                if section != current_section:
                    report.extend(["", section])
                    current_section = section

                run_pct = runs / plays * 100 if plays else 0
                pass_pct = passes / plays * 100 if plays else 0

                avg_text = (
                    f"{avg_yards:.2f}"
                    if avg_yards is not None
                    else "N/A"
                )

                report.append(
                    f"{situation} | "
                    f"Plays: {plays} | "
                    f"Runs: {runs} ({run_pct:.1f}%) | "
                    f"Passes: {passes} ({pass_pct:.1f}%) | "
                    f"Average yards: {avg_text}"
                )

            if not results:
                report.append("No classified run/pass data available.")

            report.extend([
                "",
                "NOTES",
                "Only plays tagged as runs or passes are included.",
                "Percentages are calculated within each situation.",
                "Field position uses the signed yardline system, "
                "with 50 representing midfield.",
            ])

            self.report_text.setPlainText("\n".join(report))

        except Exception as error:
            QMessageBox.critical(
                self,
                "Season Tendencies Error",
                f"Could not generate season tendencies.\n\n{error}",
            )
            self.close()






class FootballApp(QMainWindow):
    def __init__(self, current_user):
        super().__init__()

        self.current_user = current_user
        self.organization_id = current_user["organization_id"]

        self.setWindowTitle("Football Model 1.0")
        self.resize(1500, 850)

    # Main application layout
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

    # Main navigation
        navigation = QHBoxLayout()
        navigation.setContentsMargins(15, 12, 15, 12)
        navigation.setSpacing(10)

        app_title = QLabel("FOOTBALL MODEL 1")
        app_title.setStyleSheet(
        "font-size: 18px; font-weight: bold; padding: 5px;"
    )
        navigation.addWidget(app_title)

        navigation.addStretch()

        self.dashboard_button = QPushButton("Dashboard")
        self.games_button = QPushButton("Games")
        self.analysis_button = QPushButton("Analysis")
        self.reports_button = QPushButton("Reports")
        self.settings_button = QPushButton("Settings")

        self.nav_buttons = [
            self.dashboard_button,
            self.games_button,
            self.analysis_button,
            self.reports_button,
            self.settings_button,
        ]

        for button in self.nav_buttons:
            button.setCheckable(True)
            navigation.addWidget(button)

        main_layout.addLayout(navigation)

    # Main page container
        self.pages = QStackedWidget()
        main_layout.addWidget(self.pages)

    # Build application pages
        self.dashboard_page = self.build_dashboard_page()
        self.games_page = self.build_games_page()

        self.analysis_page = self.build_analysis_page()

        self.reports_page = self.build_reports_page()

        self.settings_page = self.build_settings_page()

        self.pages.addWidget(self.dashboard_page)
        self.pages.addWidget(self.games_page)
        self.pages.addWidget(self.analysis_page)
        self.pages.addWidget(self.reports_page)
        self.pages.addWidget(self.settings_page)

    # Navigation connections
        self.dashboard_button.clicked.connect(
            lambda: self.show_page(0)
        )
        self.games_button.clicked.connect(
            lambda: self.show_page(1)
    )
        self.analysis_button.clicked.connect(
            lambda: self.show_page(2)
        )
        self.reports_button.clicked.connect(
            lambda: self.show_page(3)
    )
        self.settings_button.clicked.connect(
            lambda: self.show_page(4)
    )

    # Start on Dashboard
        self.show_page(0)

    # Load game information

        try:
            self.refresh_games()
            self.update_dashboard()
            self.status_label.setText("Connected to PostgreSQL.")
        except Exception as error:
            QMessageBox.critical(
                self,
                "Database Connection Error",
                f"Could not connect to PostgreSQL.\n\n{error}",
            )
            self.status_label.setText("Database connection failed.")



    def build_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(18)

        title = QLabel("Dashboard")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
        "Your scouting workspace. Review games, track tendencies, "
        "and organize your football analysis."
    )
        subtitle.setStyleSheet("font-size: 14px; color: gray;")
        layout.addWidget(subtitle)

    # Overview cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(15)

        self.dashboard_game_count = QLabel("—")
        self.dashboard_play_count = QLabel("—")
        self.dashboard_report_count = QLabel("—")

        cards = [
            ("Games Scouted", self.dashboard_game_count),
            ("Plays Logged", self.dashboard_play_count),
            ("Reports Created", self.dashboard_report_count),
        ]

        for heading, value_label in cards:
            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setStyleSheet(
                "QFrame {"
                " border: 1px solid #444;"
                " border-radius: 8px;"
                " padding: 12px;"
                "}"
            )

            card_layout = QVBoxLayout(card)

            heading_label = QLabel(heading)
            heading_label.setStyleSheet(
                "font-size: 13px; color: gray; border: none;"
            )

            value_label.setStyleSheet(
                "font-size: 26px; font-weight: bold; border: none;"
            )

            card_layout.addWidget(heading_label)
            card_layout.addWidget(value_label)

            cards_layout.addWidget(card)

        layout.addLayout(cards_layout)

    # Quick actions
        actions_title = QLabel("Quick Actions")
        actions_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 10px;"
        )
        layout.addWidget(actions_title)

        actions_layout = QHBoxLayout()

        open_games_button = QPushButton("Open Games")
        open_games_button.clicked.connect(
            lambda: self.show_page(1)
        )

        create_game_button = QPushButton("Create New Game")
        create_game_button.clicked.connect(self.create_game)

        actions_layout.addWidget(open_games_button)
        actions_layout.addWidget(create_game_button)
        actions_layout.addStretch()

        layout.addLayout(actions_layout)

    # Recent activity area
        activity_title = QLabel("Recent Activity")
        activity_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 15px;"
        )
        layout.addWidget(activity_title)

        self.dashboard_activity = QLabel(
            "Your recent scouting activity will appear here."
        )
        self.dashboard_activity.setStyleSheet(
            "color: gray; padding: 15px;"
        )
        layout.addWidget(self.dashboard_activity)

        layout.addStretch()

        return page


    def build_placeholder_page(self, title_text, description_text):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)

        title = QLabel(title_text)
        title.setStyleSheet("font-size: 28px; font-weight: bold;")

        description = QLabel(description_text)
        description.setStyleSheet("font-size: 14px; color: gray;")

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addStretch()

        return page


    def show_page(self, page_index):
        self.pages.setCurrentIndex(page_index)

        for index, button in enumerate(self.nav_buttons):
            button.setChecked(index == page_index)


    def build_games_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

    # Games heading
        title = QLabel("Games")
        title.setStyleSheet("font-size: 26px; font-weight: bold;")
        layout.addWidget(title)

        layout.addWidget(
            QLabel("Manage games, log plays, and review scouting information.")
        )

    # Game selection
        game_layout = QHBoxLayout()
        game_layout.addWidget(QLabel("Game:"))

        self.game_selector = QComboBox()
        self.game_selector.setEditable(True)
        self.game_selector.setMinimumWidth(300)
        game_layout.addWidget(self.game_selector)

        load_button = QPushButton("Load Game")
        load_button.clicked.connect(self.load_game)
        game_layout.addWidget(load_button)

        create_game_button = QPushButton("Create Game")
        create_game_button.clicked.connect(self.create_game)
        game_layout.addWidget(create_game_button)

        edit_game_button = QPushButton("Edit Game Setup")
        edit_game_button.clicked.connect(self.edit_game_setup)
        game_layout.addWidget(edit_game_button)

        delete_game_button = QPushButton("Delete Game")
        delete_game_button.clicked.connect(self.delete_game)
        game_layout.addWidget(delete_game_button)

        game_layout.addStretch()
        layout.addLayout(game_layout)

    # Internal Games navigation
        self.game_tabs = QTabWidget()
        layout.addWidget(self.game_tabs)

    # ---------------------------------
    # TAB 1: PLAY LOG
    # ---------------------------------

        play_log_page = QWidget()
        play_log_layout = QVBoxLayout(play_log_page)

        self.columns = [
        "Series #",
        "Play #",
        "Quarter",
        "Time",
        "Down",
        "Distance",
        "Hash",
        "Yardline",
        "R/P/N",
        "Yards Gained",
        "Result",
        "Film Verified",
        "Database ID",
    ]

        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setColumnHidden(12, True)
        self.table.setAlternatingRowColors(True)

        self.table.setSelectionBehavior(
         QTableWidget.SelectionBehavior.SelectRows
        )

        self.table.setEditTriggers(
         QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.AnyKeyPressed
        )

        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(
            self.update_play_detail
        )

        play_log_layout.addWidget(self.table)

    # Autosave state
        self._autosave_suspended = False
        self._pending_autosave_rows = {}

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(700)
        self._autosave_timer.timeout.connect(
            self.autosave_pending_rows
        )

        self.table.cellChanged.connect(
            self.schedule_row_autosave
        )

    # Play controls
        buttons = QHBoxLayout()

        add_button = QPushButton("Add Play")
        add_button.clicked.connect(self.add_play)
        buttons.addWidget(add_button)

        save_button = QPushButton("Save Changes")
        save_button.clicked.connect(self.save_changes)
        buttons.addWidget(save_button)

        reload_button = QPushButton("Reload Game")
        reload_button.clicked.connect(self.load_game)
        buttons.addWidget(reload_button)

        delete_button = QPushButton("Delete Selected")
        delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(delete_button)

        buttons.addStretch()

        play_log_layout.addLayout(buttons)

        self.game_tabs.addTab(play_log_page, "Play Log")



    # ---------------------------------
    # TAB 2: PLAY DETAIL
    # ---------------------------------

        self.play_detail_page = QWidget()
        detail_layout = QVBoxLayout(self.play_detail_page)
        detail_layout.setContentsMargins(15, 15, 15, 15)
        detail_layout.setSpacing(12)

        # Page heading
        detail_title = QLabel("Play Detail")
        detail_title.setStyleSheet(
            "font-size: 24px; font-weight: bold;"
        )

        detail_description = QLabel(
            "Detailed scouting breakdown of the selected play."
        )
        detail_description.setStyleSheet("color: gray;")

        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(detail_description)

        # Selected play information
        self.play_detail_values = {}

        def create_detail_section(title, fields, target_layout):
            section = QFrame()
            section.setFrameShape(QFrame.Shape.StyledPanel)
            section.setStyleSheet("""
                QFrame {
                    border: 1px solid #444;
                    border-radius: 6px;
                    background-color: palette(base);
                }
            """)

            section_layout = QVBoxLayout(section)

            section_title = QLabel(title)
            section_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; "
                "border: none; background: transparent;"
            )

            section_layout.addWidget(section_title)

            grid = QGridLayout()
            grid.setHorizontalSpacing(20)
            grid.setVerticalSpacing(12)

            for index, (field_name, field_key, placeholder) in enumerate(fields):
                row = index // 2
                column = (index % 2) * 2

                field_label = QLabel(field_name)
                field_label.setStyleSheet(
                    "font-weight: bold; border: none;"
                )

                value_label = QLabel(placeholder)
                value_label.setWordWrap(True)
                value_label.setStyleSheet(
                    "border: none; padding: 3px;"
                )

                if field_key:
                    self.play_detail_values[field_key] = value_label

                grid.addWidget(field_label, row, column)
                grid.addWidget(value_label, row, column + 1)

            section_layout.addLayout(grid)
            target_layout.addWidget(section)

        # Situation
        create_detail_section(
            "PLAY SITUATION",
            [
                ("Series", "series", "—"),
                ("Play Number", "play_number", "—"),
                ("Quarter", "quarter", "—"),
                ("Game Time", "game_time", "—"),
                ("Down", "down", "—"),
                ("Distance", "distance", "—"),
                ("Hash", "hash", "—"),
                ("Yardline", "yardline", "—"),
            ],
            detail_layout
        )

        # Offense
        create_detail_section(
            "OFFENSIVE INFORMATION",
            [
                ("Formation", None, "Not configured yet"),
                ("Personnel", None, "Not configured yet"),
                ("Offensive Concept", None, "Not configured yet"),
                ("Motion / Shift", None, "Not configured yet"),
            ],
            detail_layout
        )

        # Defense
        create_detail_section(
            "DEFENSIVE INFORMATION",
            [
                ("Defensive Front", None, "Not configured yet"),
                ("Safety Alignment", None, "Not configured yet"),
                ("Corner Alignment", None, "Not configured yet"),
                ("Coverage", None, "Not configured yet"),
            ],
            detail_layout
        )

        # Play result
        create_detail_section(
            "PLAY RESULT",
            [
                ("Run / Pass / No Play", "rpn", "—"),
                ("Yards Gained", "yards_gained", "—"),
                ("Result", "result", "—"),
                ("Film Verified", "film_verified", "—"),
            ],
            detail_layout
        )

        # Scouting observations
        observations_frame = QFrame()
        observations_frame.setFrameShape(QFrame.Shape.StyledPanel)
        observations_frame.setStyleSheet("""
            QFrame {
                border: 1px solid #444;
                border-radius: 6px;
                background-color: palette(base);
            }
        """)

        observations_layout = QVBoxLayout(observations_frame)

        observations_title = QLabel("SCOUTING OBSERVATIONS")
        observations_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; border: none;"
        )

        observations_placeholder = QLabel(
            "Scouting notes, defensive reactions, adjustments, "
            "and film references will appear here."
        )
        observations_placeholder.setWordWrap(True)
        observations_placeholder.setMinimumHeight(55)

        observations_layout.addWidget(observations_title)
        observations_layout.addWidget(observations_placeholder)

        detail_layout.addWidget(observations_frame)

        # Custom fields
        custom_frame = QFrame()
        custom_frame.setFrameShape(QFrame.Shape.StyledPanel)
        custom_frame.setStyleSheet("""
            QFrame {
                border: 1px dashed #777;
                border-radius: 6px;
                background-color: palette(base);
            }
        """)

        custom_layout = QVBoxLayout(custom_frame)

        custom_title = QLabel("CUSTOM FIELDS")
        custom_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; border: none;"
        )

        custom_description = QLabel(
            "Organization-created scouting fields will be displayed here."
        )
        custom_description.setWordWrap(True)

        custom_layout.addWidget(custom_title)
        custom_layout.addWidget(custom_description)

        detail_layout.addWidget(custom_frame)
        detail_layout.addStretch()

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(self.play_detail_page)

        self.game_tabs.addTab(detail_scroll, "Play Detail")

    # ---------------------------------
    # TAB 3: GAME ANALYTICS
    # ---------------------------------

       # TAB 3: GAME ANALYTICS

        analytics_page = QWidget()

        analytics_scroll = QScrollArea()
        analytics_scroll.setWidgetResizable(True)

        analytics_content = QWidget()
        analytics_layout = QVBoxLayout(analytics_content)

        analytics_scroll.setWidget(analytics_content)

        analytics_page_layout = QVBoxLayout(analytics_page)
        analytics_page_layout.addWidget(analytics_scroll)

# Page heading
        analytics_title = QLabel("Game Analytics")
        analytics_title.setStyleSheet(
            "font-size: 22px; font-weight: bold;"
        )

        analytics_description = QLabel(
        "Review game performance, run/pass tendencies, "
        "and situational information for the selected game."
            )
        analytics_description.setWordWrap(True)

        analytics_layout.addWidget(analytics_title)
        analytics_layout.addWidget(analytics_description)

# GAME OVERVIEW
        overview_title = QLabel("Game Overview")
        overview_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; margin-top: 12px;"
        )
        analytics_layout.addWidget(overview_title)

        overview_grid = QGridLayout()
        overview_grid.setSpacing(12)

        self.analytics_value_labels = {}

        metrics = [
                ("total", "Total Plays", "0"),
                ("runs", "Run Plays", "0"),
                ("passes", "Pass Plays", "0"),
                ("run_pct", "Run Percentage", "N/A"),
                ("pass_pct", "Pass Percentage", "N/A"),
                ("avg_yards", "Average Yards", "N/A"),

    ]

        for index, (key, label_text, default_value) in enumerate(metrics):

            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setStyleSheet("""
                QFrame {
            background-color: #252525;
            border: 1px solid #444444;
            border-radius: 8px;
        }
            """     )

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 12, 15, 12)

            metric_label = QLabel(label_text)
            metric_label.setStyleSheet(
                "font-size: 12px; color: #bbbbbb; border: none;"
            )

            value_label = QLabel(default_value)
            value_label.setStyleSheet(
                "font-size: 24px; font-weight: bold; "
                "color: white; border: none;"
            )

            card_layout.addWidget(metric_label)
            card_layout.addWidget(value_label)

            row = index // 2
            column = index % 2

            overview_grid.addWidget(card, row, column)

            self.analytics_value_labels[key] = value_label

        analytics_layout.addLayout(overview_grid)

        # ANALYSIS TOOLS
        tools_title = QLabel("Analysis Tools")
        tools_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; margin-top: 15px;"
        )
        analytics_layout.addWidget(tools_title)

        tools_description = QLabel(
            "Open detailed breakdowns of the selected game's statistics "
            "and situational tendencies."
        )
        tools_description.setWordWrap(True)
        analytics_layout.addWidget(tools_description)

        stats_button = QPushButton("View Statistics")
        stats_button.clicked.connect(self.open_statistics)

        situational_button = QPushButton("Situational Analysis")
        situational_button.clicked.connect(
            self.open_situational_analysis
        )

        analytics_layout.addWidget(stats_button)
        analytics_layout.addWidget(situational_button)

# DOWN AND DISTANCE PREVIEW
        tendency_title = QLabel("Down & Distance Tendencies")
        tendency_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; margin-top: 15px;"
            )
        analytics_layout.addWidget(tendency_title)

        tendency_description = QLabel(
            "Run/pass tendencies grouped by down and distance."
            )
        analytics_layout.addWidget(tendency_description)

        self.analytics_situation_table = QTableWidget()
        self.analytics_situation_table.setColumnCount(7)

        self.analytics_situation_table.setHorizontalHeaderLabels([
            "Down",
            "Distance",
    "Plays",
    "Runs",
    "Passes",
    "Run %",
    "Pass %",
        ])

        self.analytics_situation_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self.analytics_situation_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
            )

        self.analytics_situation_table.setMaximumHeight(280)
        self.analytics_situation_table.setAlternatingRowColors(True)

        analytics_layout.addWidget(self.analytics_situation_table)

        analytics_layout.addStretch()

        self.game_tabs.addTab(analytics_page, "Game Analytics")

# Refresh the overview when the selected game changes.
        self.game_selector.currentTextChanged.connect(
        self.update_game_analytics
        )
        self.game_selector.currentTextChanged.connect(
        self.update_down_distance_preview
            )

        self.update_game_analytics()
        self.update_down_distance_preview()


    # ---------------------------------
    # TAB 4: GAME REPORTS
    # ---------------------------------

        reports_page = QWidget()
        reports_layout = QVBoxLayout(reports_page)

        # PAGE HEADING
        reports_title = QLabel("Game Reports")
        reports_title.setStyleSheet(
            "font-size: 22px; font-weight: bold;"
        )

        reports_description = QLabel(
            "Generate and review scouting reports using "
            "the recorded data from the selected game."
        )
        reports_description.setWordWrap(True)

        reports_layout.addWidget(reports_title)
        reports_layout.addWidget(reports_description)

        # REPORT SCOPE
        scope_title = QLabel("Report Scope")
        scope_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; margin-top: 15px;"
        )

        scope_description = QLabel(
            "Reports will only use plays recorded for the "
            "currently selected game."
        )
        scope_description.setWordWrap(True)

        reports_layout.addWidget(scope_title)
        reports_layout.addWidget(scope_description)

        # REPORT TYPE
        report_type_title = QLabel("Select Report Type")
        report_type_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; margin-top: 15px;"
        )

        self.report_type_selector = QComboBox()

        self.report_type_selector.addItems([
            "Game Summary",
            "Offensive Report",
            "Defensive Report",
            "Situational Report",
            "Player Report",
            "Custom Report",
        ])

        reports_layout.addWidget(report_type_title)
        reports_layout.addWidget(self.report_type_selector)

        # GENERATE REPORT
        generate_report_button = QPushButton("Generate Report")
        generate_report_button.clicked.connect(self.open_report)

        reports_layout.addWidget(generate_report_button)

        reports_layout.addStretch()

        self.game_tabs.addTab(reports_page, "Game Reports")

    # Status information
        self.status_label = QLabel("Connecting to database...")
        layout.addWidget(self.status_label)

        return page


    def build_analysis_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 20, 20, 20)
        page_layout.setSpacing(12)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(15)

        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        # PAGE HEADING
        title = QLabel("Season Analysis")
        title.setStyleSheet("font-size: 26px; font-weight: bold;")
        layout.addWidget(title)

        description = QLabel(
            "Analyze team performance, tendencies, and production "
            "across multiple games and seasons."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: gray;")
        layout.addWidget(description)

        # SEASON SELECTION
        season_layout = QHBoxLayout()

        season_label = QLabel("Select Season:")
        self.season_selector = QComboBox()
        self.season_selector.setMinimumWidth(200)

        self.season_selector.addItem("All Seasons", None)

        season_layout.addWidget(season_label)
        season_layout.addWidget(self.season_selector)
        season_layout.addStretch()

        layout.addLayout(season_layout)

        # SEASON OVERVIEW
        overview_title = QLabel("Season Overview")
        overview_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 10px;"
        )
        layout.addWidget(overview_title)

        overview_grid = QGridLayout()
        overview_grid.setSpacing(12)

        self.season_analysis_value_labels = {}

        metrics = [
            ("games", "Games Scouted", "0"),
            ("plays", "Total Plays", "0"),
            ("runs", "Run Plays", "0"),
            ("passes", "Pass Plays", "0"),
            ("run_pct", "Run Percentage", "N/A"),
            ("avg_yards", "Average Yards", "N/A"),
        ]

        for index, (key, label_text, default_value) in enumerate(metrics):

            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setStyleSheet("""
                QFrame {
                background-color: #252525;
                border: 1px solid #444444;
                border-radius: 8px;
                }
            """)

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 12, 15, 12)

            metric_label = QLabel(label_text)
            metric_label.setStyleSheet(
                "font-size: 12px; color: #bbbbbb; border: none;"
            )

            value_label = QLabel(default_value)
            value_label.setStyleSheet(
                "font-size: 24px; font-weight: bold; "
                "color: white; border: none;"
            )

            card_layout.addWidget(metric_label)
            card_layout.addWidget(value_label)

            row = index // 2
            column = index % 2

            overview_grid.addWidget(card, row, column)

            self.season_analysis_value_labels[key] = value_label

        layout.addLayout(overview_grid)

        # TEAM TENDENCIES
        tendencies_title = QLabel("Team Tendencies")
        tendencies_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 15px;"
        )
        layout.addWidget(tendencies_title)

        tendencies_description = QLabel(
            "Review offensive tendencies across the selected season."
        )
        tendencies_description.setStyleSheet("color: gray;")
        layout.addWidget(tendencies_description)

        self.season_tendencies_table = QTableWidget()
        self.season_tendencies_table.setColumnCount(7)

        self.season_tendencies_table.setHorizontalHeaderLabels([
            "Situation",
            "Plays",
            "Runs",
            "Passes",
            "Run %",
            "Pass %",
            "Average Yards",
        ])

        self.season_tendencies_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self.season_tendencies_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )

        self.season_tendencies_table.setAlternatingRowColors(True)
        self.season_tendencies_table.horizontalHeader().setStretchLastSection(
            True
        )
        self.season_tendencies_table.setMinimumHeight(220)

        layout.addWidget(self.season_tendencies_table)

        # GAME COMPARISON
        comparison_title = QLabel("Game Comparison")
        comparison_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 15px;"
        )
        layout.addWidget(comparison_title)

        comparison_description = QLabel(
            "Compare recorded offensive production from game to game."
        )
        comparison_description.setStyleSheet("color: gray;")
        layout.addWidget(comparison_description)

        self.season_game_comparison_table = QTableWidget()
        self.season_game_comparison_table.setColumnCount(7)

        self.season_game_comparison_table.setHorizontalHeaderLabels([
            "Game",
            "Opponent",
            "Date",
            "Plays",
            "Runs",
            "Passes",
            "Average Yards",
        ])

        self.season_game_comparison_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self.season_game_comparison_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )

        self.season_game_comparison_table.setAlternatingRowColors(True)
        self.season_game_comparison_table.horizontalHeader().setStretchLastSection(
            True
        )
        self.season_game_comparison_table.setMinimumHeight(220)

        layout.addWidget(self.season_game_comparison_table)

        # PLAYER ANALYSIS
        player_title = QLabel("Player Analysis")
        player_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 15px;"
        )
        layout.addWidget(player_title)

        player_frame = QFrame()
        player_frame.setFrameShape(QFrame.Shape.StyledPanel)
        player_frame.setStyleSheet("""
            QFrame {
            border: 1px dashed #777;
            border-radius: 8px;
            background-color: palette(base);
        }
        """)

        player_layout = QVBoxLayout(player_frame)

        player_description = QLabel(
            "Individual player statistics, performance comparisons, "
            "and player-specific tendencies will be available "
            "when player tracking is implemented."
        )
        player_description.setWordWrap(True)
        player_description.setStyleSheet(
            "color: gray; padding: 10px;"
        )

        player_layout.addWidget(player_description)
        layout.addWidget(player_frame)

        layout.addStretch()

        self.season_selector.currentIndexChanged.connect(
        self.update_season_analysis
            )

        self.refresh_season_selector()

        return page


    def build_reports_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(20, 20, 20, 20)
        page_layout.setSpacing(15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(15)

        scroll.setWidget(content)
        page_layout.addWidget(scroll)

    # PAGE HEADER
        title = QLabel("Reports")
        title.setStyleSheet(
            "font-size: 26px; font-weight: bold;"
        )
        layout.addWidget(title)

        description = QLabel(
            "Generate and review scouting reports across individual "
            "games and seasons."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: gray;")
        layout.addWidget(description)

    # GAME REPORT SECTION
        game_title = QLabel("Game Reports")
        game_title.setStyleSheet(
            "font-size: 20px; font-weight: bold; margin-top: 10px;"
        )
        layout.addWidget(game_title)

        game_description = QLabel(
            "Generate reports using the plays recorded for an individual game."
        )
        game_description.setWordWrap(True)
        game_description.setStyleSheet("color: gray;")
        layout.addWidget(game_description)

        game_frame = QFrame()
        game_frame.setFrameShape(QFrame.Shape.StyledPanel)
        game_frame.setStyleSheet("""
            QFrame {
                border: 1px solid #555555;
                border-radius: 8px;
                background-color: palette(base);
            }
        """)

        game_layout = QVBoxLayout(game_frame)
        game_layout.setContentsMargins(15, 15, 15, 15)
        game_layout.setSpacing(10)

        game_label = QLabel("Select Game:")
        game_layout.addWidget(game_label)

        self.central_report_game_selector = QComboBox()
        self.central_report_game_selector.setMinimumHeight(32)
        game_layout.addWidget(self.central_report_game_selector)

        report_label = QLabel("Report Type:")
        game_layout.addWidget(report_label)

        self.central_report_type_selector = QComboBox()
        self.central_report_type_selector.setMinimumHeight(32)

        self.central_report_type_selector.addItems([
         "Game Summary",
            "Offensive Report",
            "Defensive Report",
            "Situational Report",
        ])

        game_layout.addWidget(self.central_report_type_selector)

        generate_game_button = QPushButton("Generate Game Report")
        generate_game_button.setMinimumHeight(38)
        generate_game_button.clicked.connect(
            self.open_central_game_report
        )
        game_layout.addWidget(generate_game_button)

        layout.addWidget(game_frame)

    # SEASON REPORT SECTION
        season_title = QLabel("Season Reports")
        season_title.setStyleSheet(
        "font-size: 20px; font-weight: bold; margin-top: 15px;"
        )
        layout.addWidget(season_title)

        season_frame = QFrame()
        season_frame.setFrameShape(QFrame.Shape.StyledPanel)
        season_frame.setStyleSheet("""
        QFrame {
            border: 1px dashed #777777;
            border-radius: 8px;
            background-color: palette(base);
        }
        """)


        season_layout = QVBoxLayout(season_frame)
        season_layout.setContentsMargins(15, 15, 15, 15)
        season_layout.setSpacing(10)

        season_description = QLabel(
                "Generate reports across all games in a selected season."
                )
        season_description.setWordWrap(True)
        season_description.setStyleSheet("color: gray;")
        season_layout.addWidget(season_description)

        season_label = QLabel("Select Season:")
        season_layout.addWidget(season_label)

        self.central_report_season_selector = QComboBox()
        self.central_report_season_selector.setMinimumHeight(32)
        season_layout.addWidget(self.central_report_season_selector)

        season_report_label = QLabel("Report Type:")
        season_layout.addWidget(season_report_label)

        self.central_season_report_type_selector = QComboBox()
        self.central_season_report_type_selector.setMinimumHeight(32)

        self.central_season_report_type_selector.addItems([
            "Season Summary",
            "Season Tendencies",
            ])

        season_layout.addWidget(self.central_season_report_type_selector)

        generate_season_button = QPushButton("Generate Season Report")
        generate_season_button.setMinimumHeight(38)
        generate_season_button.clicked.connect(
            self.open_central_season_report
            )
        season_layout.addWidget(generate_season_button)

        layout.addWidget(season_frame)



        layout.addStretch()

        self.refresh_central_report_games()
        self.refresh_central_report_seasons()

        return page





    def build_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(18)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")

        description = QLabel(
            "Manage your organization, scouting data, "
            "and application preferences."
        )
        description.setStyleSheet("font-size: 14px; color: gray;")

        layout.addWidget(title)
        layout.addWidget(description)

    # Team Management
        team_management_title = QLabel("Team Management")
        team_management_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 15px;"
        )

        team_management_description = QLabel(
            "Create, edit, and manage the teams belonging "
            "to your organization."
        )
        team_management_description.setStyleSheet(
            "font-size: 14px; color: gray;"
        )

        team_management_button = QPushButton("Manage Teams")
        team_management_button.setFixedWidth(180)
        team_management_button.clicked.connect(
            self.open_team_management
        )

        layout.addWidget(team_management_title)
        layout.addWidget(team_management_description)
        layout.addWidget(team_management_button)
            # Roster Management
        roster_management_title = QLabel("Roster Management")
        roster_management_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; margin-top: 15px;"
        )

        roster_management_description = QLabel(
            "Create and manage team rosters by season."
        )
        roster_management_description.setStyleSheet(
            "font-size: 14px; color: gray;"
        )

        roster_management_button = QPushButton("Manage Rosters")
        roster_management_button.setFixedWidth(180)
        roster_management_button.clicked.connect(
            self.open_roster_management
        )

        layout.addWidget(roster_management_title)
        layout.addWidget(roster_management_description)
        layout.addWidget(roster_management_button)
        self.player_management_button = QPushButton("Manage Players")

        self.player_management_button.clicked.connect(
        self.open_player_management
            )

        layout.addWidget(self.player_management_button)
        layout.addStretch()

        return page




    def open_team_management(self):
        dialog = TeamManagementDialog(
            self.organization_id,
            get_connection,
            self
        )

        dialog.exec()


    def open_roster_management(self):
        dialog = RosterManagementDialog(
            self.organization_id,
            get_connection,
            self
        )

        dialog.exec()


    def open_player_management(self):
        dialog = PlayerManagementDialog(
            self.organization_id,
            get_connection,
            self
        )
        dialog.exec()


    def refresh_games(self):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                """
                    SELECT id, name
                    FROM games
                    WHERE organization_id = %s
                    ORDER BY name
                    """,
                    (self.organization_id,),
                )
                games = cur.fetchall()

    # Preserve the currently selected game by ID.
        current_game_id = self.game_selector.currentData()

        self.game_selector.blockSignals(True)
        self.game_selector.clear()

        for game_id, game_name in games:
            self.game_selector.addItem(game_name, game_id)

    # Restore the previous selection if it still exists.
        if current_game_id is not None:
            index = self.game_selector.findData(current_game_id)

            if index >= 0:
                self.game_selector.setCurrentIndex(index)
            elif games:
                self.game_selector.setCurrentIndex(0)

        elif games:
            self.game_selector.setCurrentIndex(0)

        self.game_selector.blockSignals(False)


    def logout(self):
        answer = QMessageBox.question(
            self,
            "Log Out",
            "Log out of the current account?",
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        clear_session()
        self.close()

        self.login_window = LoginDialog()

        if self.login_window.exec() == QDialog.DialogCode.Accepted:
            save_session(self.login_window.user)

            self.new_window = FootballApp(self.login_window.user)
            self.new_window.show()



    def update_game_analytics(self, *_):
        game_id = self.get_selected_game_id()

        if not game_id:


            defaults = {
            "total": "0",
            "runs": "0",
            "passes": "0",
            "run_pct": "N/A",
            "pass_pct": "N/A",
            "avg_yards": "N/A",
            }

            for key, value in defaults.items():
                self.analytics_value_labels[key].setText(value)

            return

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    SELECT
                        COUNT(*),

                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),

                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        ),

                        AVG(yards_gained) FILTER (
                            WHERE yards_gained IS NOT NULL
                              AND UPPER(TRIM(COALESCE(rpn, '')))
                                  IN ('R', 'P')
                        )

                    FROM plays
                    WHERE game_id = %s
                      AND organization_id = %s
                    """,
                        (game_id, self.organization_id),
                    )

                    total, runs, passes, avg_yards = cur.fetchone()

            run_pass_total = runs + passes

            if run_pass_total > 0:
                run_pct = f"{runs / run_pass_total * 100:.1f}%"
                pass_pct = f"{passes / run_pass_total * 100:.1f}%"
            else:
                run_pct = "N/A"
                pass_pct = "N/A"

            average_yards = (
                f"{float(avg_yards):.1f}"
                if avg_yards is not None
                else "N/A"
            )

            values = {
                "total": str(total),
                "runs": str(runs),
                "passes": str(passes),
                "run_pct": run_pct,
                "pass_pct": pass_pct,
                "avg_yards": average_yards,
            }

            for key, value in values.items():
                self.analytics_value_labels[key].setText(value)

        except Exception as error:
            print(f"Game Analytics Error: {error}")

            for label in self.analytics_value_labels.values():
                label.setText("Error")



    def refresh_central_report_games(self):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                """
                SELECT id, name, opponent, game_date
                FROM games
                WHERE organization_id = %s
                ORDER BY game_date DESC NULLS LAST, name
                """,
                    (self.organization_id,),
                )

                games = cur.fetchall()

        selector = self.central_report_game_selector
        current_data = selector.currentData()

        selector.blockSignals(True)
        selector.clear()

        for game_id, game_name, opponent, game_date in games:
            label = game_name

            if opponent:
                label += f" — vs. {opponent}"

            if game_date:
                label += f" ({game_date.strftime('%Y-%m-%d')})"

            selector.addItem(
                label,
                (game_id, game_name)
            )

        if current_data is not None:
            index = selector.findData(current_data)
            if index >= 0:
                selector.setCurrentIndex(index)

        selector.blockSignals(False)




    def open_central_game_report(self):
        selected_game = self.central_report_game_selector.currentData()

        if selected_game is None:
            QMessageBox.warning(
                self,
                "Select a Game",
                "There are no games available. Create a game first."
            )
            return

        game_id, game_name = selected_game

        report_type = self.central_report_type_selector.currentText()

        dialog = ReportsDialog(
            game_id,
            game_name,
            self.organization_id,
            report_type,
            self
        )

        dialog.exec()





    def update_season_tendencies(self):
        selected_season = self.season_selector.currentData()

        season_filter = ""
        params = [self.organization_id]

        if selected_season == "unassigned":
            season_filter = "AND g.season IS NULL"
        elif selected_season != "all":
            season_filter = "AND g.season = %s"
            params.append(selected_season)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                f"""
                WITH selected_plays AS (
                    SELECT
                        p.down,
                        p.quarter,
                        p.yardline,
                        p.rpn,
                        p.yards_gained
                    FROM games g
                    JOIN plays p
                      ON p.game_id = g.id
                     AND p.organization_id = g.organization_id
                    WHERE g.organization_id = %s
                      {season_filter}
                      AND UPPER(TRIM(COALESCE(p.rpn, '')))
                          IN ('R', 'P')
                ),

                positioned_plays AS (
                    SELECT *,
                        CASE
                            WHEN yardline = 50
                                THEN 'Midfield'
                            WHEN yardline < 0 AND ABS(yardline) <= 20
                                THEN 'Own 1-20'
                            WHEN yardline < 0
                                THEN 'Own 21-49'
                            WHEN yardline > 0 AND yardline <= 20
                                THEN 'Opponent 1-20'
                            WHEN yardline > 20
                                THEN 'Opponent 21-49'
                        END AS field_position
                    FROM selected_plays
                ),

                tendency_rows AS (

                    SELECT
                        1 AS sort_group,
                        down AS sort_order,
                        CASE down
                            WHEN 1 THEN '1st Down'
                            WHEN 2 THEN '2nd Down'
                            WHEN 3 THEN '3rd Down'
                            WHEN 4 THEN '4th Down'
                            ELSE down::TEXT || 'th Down'
                        END AS situation,
                        COUNT(*) AS plays,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(rpn)) = 'R'
                        ) AS runs,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(rpn)) = 'P'
                        ) AS passes,
                        AVG(yards_gained) AS avg_yards
                    FROM selected_plays
                    WHERE down IS NOT NULL
                    GROUP BY down

                    UNION ALL

                    SELECT
                        2 AS sort_group,
                        quarter AS sort_order,
                        'Quarter ' || quarter AS situation,
                        COUNT(*) AS plays,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(rpn)) = 'R'
                        ) AS runs,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(rpn)) = 'P'
                        ) AS passes,
                        AVG(yards_gained) AS avg_yards
                    FROM selected_plays
                    WHERE quarter IS NOT NULL
                    GROUP BY quarter

                    UNION ALL

                    SELECT
                        3 AS sort_group,
                        CASE field_position
                            WHEN 'Own 1-20' THEN 1
                            WHEN 'Own 21-49' THEN 2
                            WHEN 'Midfield' THEN 3
                            WHEN 'Opponent 21-49' THEN 4
                            WHEN 'Opponent 1-20' THEN 5
                        END AS sort_order,
                        field_position AS situation,
                        COUNT(*) AS plays,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(rpn)) = 'R'
                        ) AS runs,
                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(rpn)) = 'P'
                        ) AS passes,
                        AVG(yards_gained) AS avg_yards
                    FROM positioned_plays
                    WHERE field_position IS NOT NULL
                    GROUP BY field_position
                )

                SELECT
                    situation,
                    plays,
                    runs,
                    passes,
                    avg_yards
                FROM tendency_rows
                ORDER BY sort_group, sort_order
                """,
                    tuple(params),
                )

                results = cur.fetchall()

        table = self.season_tendencies_table
        table.setRowCount(len(results))

        for row, record in enumerate(results):
            situation, plays, runs, passes, avg_yards = record

            run_pct = runs / plays * 100 if plays else 0
            pass_pct = passes / plays * 100 if plays else 0

            values = [
                situation,
                str(plays),
                str(runs),
                str(passes),
                f"{run_pct:.1f}%",
                f"{pass_pct:.1f}%",
                f"{avg_yards:.1f}" if avg_yards is not None else "N/A",
            ]

            for column, value in enumerate(values):
                table.setItem(
                    row,
                    column,
                    QTableWidgetItem(value)
                )


    def update_season_game_comparison(self):
        selected_season = self.season_selector.currentData()

        season_filter = ""
        params = [self.organization_id]

        if selected_season == "unassigned":
            season_filter = "AND g.season IS NULL"
        elif selected_season != "all":
            season_filter = "AND g.season = %s"
            params.append(selected_season)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                SELECT
                    g.name,
                    g.opponent,
                    g.game_date,

                    COUNT(p.id) AS total_plays,

                    COUNT(p.id) FILTER (
                        WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'R'
                    ) AS runs,

                    COUNT(p.id) FILTER (
                        WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'P'
                    ) AS passes,

                    AVG(p.yards_gained) FILTER (
                        WHERE UPPER(TRIM(COALESCE(p.rpn, '')))
                            IN ('R', 'P')
                          AND p.yards_gained IS NOT NULL
                    ) AS avg_yards

                FROM games g

                LEFT JOIN plays p
                    ON p.game_id = g.id
                   AND p.organization_id = g.organization_id

                WHERE g.organization_id = %s
                    {season_filter}

                GROUP BY
                    g.id,
                    g.name,
                    g.opponent,
                    g.game_date

                ORDER BY
                    g.game_date NULLS LAST,
                    g.name
                """,
                    tuple(params),
                )

                results = cur.fetchall()

        table = self.season_game_comparison_table
        table.setRowCount(len(results))

        for row, record in enumerate(results):
            game, opponent, game_date, plays, runs, passes, avg_yards = record

            date_text = (
                game_date.strftime("%Y-%m-%d")
                if game_date is not None
                else "N/A"
            )

            values = [
                game or "N/A",
                opponent or "N/A",
                date_text,
                str(plays),
                str(runs),
                str(passes),
                f"{avg_yards:.1f}" if avg_yards is not None else "N/A",
            ]

            for column, value in enumerate(values):
                table.setItem(
                    row,
                    column,
                    QTableWidgetItem(value)
             )




    def refresh_season_selector(self):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                """
                SELECT DISTINCT season
                FROM games
                WHERE organization_id = %s
                  AND season IS NOT NULL
                ORDER BY season DESC
                """,
                    (self.organization_id,),
                )
                seasons = cur.fetchall()

                cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM games
                    WHERE organization_id = %s
                      AND season IS NULL
                )
                """,
                (self.organization_id,),
                )
                has_unassigned = cur.fetchone()[0]

        self.season_selector.blockSignals(True)
        self.season_selector.clear()

        self.season_selector.addItem("All Seasons", "all")

        for (season,) in seasons:
            self.season_selector.addItem(str(season), season)

        if has_unassigned:
            self.season_selector.addItem(
                "Unassigned Season",
                "unassigned"
            )

        self.season_selector.blockSignals(False)

        self.update_season_analysis()



    def refresh_central_report_seasons(self):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                """
                SELECT DISTINCT season
                FROM games
                WHERE organization_id = %s
                  AND season IS NOT NULL
                ORDER BY season DESC
                """,
                    (self.organization_id,),
                )
                seasons = cur.fetchall()

                cur.execute(
                """
                    SELECT EXISTS (
                    SELECT 1
                    FROM games
                    WHERE organization_id = %s
                      AND season IS NULL
                    )
                    """,
                    (self.organization_id,),
                )
                has_unassigned = cur.fetchone()[0]

        selector = self.central_report_season_selector

        selector.blockSignals(True)
        selector.clear()

        selector.addItem("All Seasons", "all")

        for (season,) in seasons:
            selector.addItem(str(season), season)

        if has_unassigned:
            selector.addItem("Unassigned Season", "unassigned")

        selector.blockSignals(False)




    def open_central_season_report(self):
        selected_season = (
            self.central_report_season_selector.currentData()
        )

        if selected_season is None:
            QMessageBox.warning(
                self,
                "Select a Season",
                "No season selection is available."
            )
            return

        report_type = (
            self.central_season_report_type_selector.currentText()
        )

        dialog = SeasonReportsDialog(
            selected_season,
            self.organization_id,
            report_type,
            self
        )

        dialog.exec()




    def update_season_analysis(self):
        selected_season = self.season_selector.currentData()

        season_filter = ""
        params = [self.organization_id]

        if selected_season == "unassigned":
            season_filter = "AND g.season IS NULL"

        elif selected_season != "all":
            season_filter = "AND g.season = %s"
            params.append(selected_season)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                    COUNT(DISTINCT g.id),
                    COUNT(p.id),

                    COUNT(p.id) FILTER (
                        WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'R'
                    ),

                    COUNT(p.id) FILTER (
                        WHERE UPPER(TRIM(COALESCE(p.rpn, ''))) = 'P'
                    ),

                    AVG(p.yards_gained) FILTER (
                        WHERE UPPER(TRIM(COALESCE(p.rpn, '')))
                        IN ('R', 'P')
                          AND p.yards_gained IS NOT NULL
                    )

                FROM games g

                LEFT JOIN plays p
                    ON p.game_id = g.id
                   AND p.organization_id = g.organization_id

                WHERE g.organization_id = %s
                {season_filter}
                """,
                tuple(params),
            )

                result = cur.fetchone()

        total_games, total_plays, runs, passes, avg_yards = result

        total_games = total_games or 0
        total_plays = total_plays or 0
        runs = runs or 0
        passes = passes or 0

        classified_plays = runs + passes

        if classified_plays > 0:
            run_percentage = runs / classified_plays * 100
            run_percentage_text = f"{run_percentage:.1f}%"
        else:
            run_percentage_text = "N/A"

        if avg_yards is not None:
            avg_yards_text = f"{avg_yards:.1f}"
        else:
            avg_yards_text = "N/A"

        self.season_analysis_value_labels["games"].setText(
            str(total_games)
        )

        self.season_analysis_value_labels["plays"].setText(
            str(total_plays)
        )

        self.season_analysis_value_labels["runs"].setText(
            str(runs)
        )

        self.season_analysis_value_labels["passes"].setText(
            str(passes)
        )

        self.season_analysis_value_labels["run_pct"].setText(
            run_percentage_text
        )

        self.season_analysis_value_labels["avg_yards"].setText(
            avg_yards_text
        )

        self.update_season_tendencies()
        self.update_season_game_comparison()






    def load_game(self):
        game = self.game_selector.currentText().strip()

        if not game:
            QMessageBox.warning(
                self, "Select a Game", "Select a game first."
            )
            return

        game_id = self.get_selected_game_id()

        if game_id is None:
            QMessageBox.warning(
                self,
                "Game Not Found",
                "The selected game could not be found.",
            )
            return

        self._autosave_timer.stop()
        self._pending_autosave_rows.clear()
        self._autosave_suspended = True

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    SELECT
                        series_number,
                        play_number,
                        quarter,
                        game_time,
                        down,
                        distance,
                        hash,
                        yardline,
                        rpn,
                        yards_gained,
                        result_reason,
                        id
                        FROM plays
                    WHERE game_id = %s
                      AND organization_id = %s
                    ORDER BY play_number, id
                    """,
                        (game_id, self.organization_id),
                    )

                    records = cur.fetchall()

            self.table.setRowCount(0)

            for record in records:
                row = self.table.rowCount()
                self.table.insertRow(row)

                for column, value in enumerate(record[:11]):
                    self.set_cell_value(row, column, value)

                self.set_cell_value(row, 11, "No")
                self.set_cell_value(row, 12, str(record[11]))

            self.update_status()

            self.status_label.setText(
                f"Loaded {len(records)} plays for {game}."
            )

        except Exception as error:
            QMessageBox.critical(
                self, "Load Error", str(error)
            )

        finally:
            self._autosave_suspended = False


    def delete_game(self):
        game_id = self.get_selected_game_id()

        if not game_id:
            QMessageBox.warning(
                self,
                "No Game Selected",
                "Select a game before deleting it."
            )
            return

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                # Retrieve game name and number of associated plays
                    cur.execute(
                    """
                    SELECT
                        g.name,
                        COUNT(p.id)
                    FROM games AS g
                    LEFT JOIN plays AS p
                        ON p.game_id = g.id
                       AND p.organization_id = g.organization_id
                    WHERE g.id = %s
                      AND g.organization_id = %s
                    GROUP BY g.id, g.name
                    """,
                        (game_id, self.organization_id)
                )

                    result = cur.fetchone()

            if result is None:
                QMessageBox.warning(
                    self,
                    "Game Not Found",
                    "The selected game could not be found."
                )
                self.refresh_games()
                return

            game_name, play_count = result

        # Require explicit confirmation
            answer = QMessageBox.warning(
                self,
                "Confirm Game Deletion",
            (
                f'Are you sure you want to delete "{game_name}"?\n\n'
                f"This will permanently delete {play_count} "
                f"associated play(s).\n\n"
                "This action cannot be undone."
            ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if answer != QMessageBox.StandardButton.Yes:
                return

        # Delete the game. Associated plays are deleted by ON DELETE CASCADE.
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    DELETE FROM games
                    WHERE id = %s
                      AND organization_id = %s
                    RETURNING id
                    """,
                        (game_id, self.organization_id)
                    )

                    deleted_game = cur.fetchone()

            if deleted_game is None:
                QMessageBox.warning(
                    self,
                    "Deletion Failed",
                    "The game could not be deleted."
                )
                return

            self.refresh_games()

        # Clear the play table after deletion
            self.table.setRowCount(0)

            QMessageBox.information(
                self,
                "Game Deleted",
                (
                f'"{game_name}" and its {play_count} '
                "associated play(s) were deleted."
                )
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Could Not Delete Game",
                f"An error occurred while deleting the game:\n{error}"
            )




    def update_down_distance_preview(self, *_):
        game_id = self.get_selected_game_id()

        self.analytics_situation_table.setRowCount(0)

        if not game_id:
            return

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    WITH grouped_plays AS (
                        SELECT
                            down,

                            CASE
                                WHEN distance BETWEEN 1 AND 3
                                    THEN 'Short (1-3)'
                                WHEN distance BETWEEN 4 AND 6
                                    THEN 'Medium (4-6)'
                                WHEN distance >= 7
                                    THEN 'Long (7+)'
                            END AS distance_group,

                            CASE
                                WHEN distance BETWEEN 1 AND 3 THEN 1
                                WHEN distance BETWEEN 4 AND 6 THEN 2
                                WHEN distance >= 7 THEN 3
                            END AS distance_order,

                            rpn

                        FROM plays

                        WHERE game_id = %s
                          AND organization_id = %s
                          AND down IS NOT NULL
                          AND distance IS NOT NULL
                          AND distance >= 1
                    )

                    SELECT
                        down,
                        distance_group,
                        COUNT(*),

                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'R'
                        ),

                        COUNT(*) FILTER (
                            WHERE UPPER(TRIM(COALESCE(rpn, ''))) = 'P'
                        )

                    FROM grouped_plays

                    GROUP BY down, distance_group, distance_order

                    ORDER BY down, distance_order
                    """,
                    (game_id, self.organization_id),
                )

                    rows = cur.fetchall()

            self.analytics_situation_table.setRowCount(len(rows))

            for row_index, row_data in enumerate(rows):
                down, distance_group, total, runs, passes = row_data

                run_pass_total = runs + passes

                if run_pass_total:
                    run_pct = f"{runs / run_pass_total * 100:.1f}%"
                    pass_pct = f"{passes / run_pass_total * 100:.1f}%"
                else:
                    run_pct = "N/A"
                    pass_pct = "N/A"

                values = [
                    f"{down} Down",
                    distance_group,
                    str(total),
                    str(runs),
                    str(passes),
                    run_pct,
                    pass_pct,
                ]

                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)

                    self.analytics_situation_table.setItem(
                        row_index,
                        column,
                        item
                    )

            self.analytics_situation_table.resizeColumnsToContents()

        except Exception as error:
            print(f"Down & Distance Analytics Error: {error}")









    def create_game(self):
        dialog = GameSetupDialog(self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        game_data = dialog.get_game_data()

        if not game_data["name"]:
            QMessageBox.warning(
                self,
                "Missing Game Name",
                "Enter a game name before saving."
            )
            return

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    INSERT INTO games (
                        organization_id,
                        name,
                        opponent,
                        season,
                        game_date,
                        location,
                        scouting_focus,
                        general_notes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (organization_id, name)
                    DO NOTHING
                    RETURNING id
                    """,
                        (
                        self.organization_id,
                        game_data["name"],
                        game_data["opponent"],
                        game_data["season"],
                        game_data["game_date"],
                        game_data["location"],
                        game_data["scouting_focus"],
                        game_data["general_notes"]
                        )
                    )

                    created_game = cur.fetchone()

                    if created_game is None:
                        QMessageBox.warning(
                            self,
                            "Game Already Exists",
                            "A game with that name already exists."
                     )
                        return

        # Refresh application data after successful creation.
            self.refresh_games()
            self.game_selector.setCurrentText(game_data["name"])

            self.refresh_central_report_games()
            self.refresh_season_selector()
            self.refresh_central_report_seasons()
            self.update_dashboard()

            QMessageBox.information(
                self,
                "Game Created",
                f'{game_data["name"]} has been created successfully.'
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Could Not Create Game",
                f"An error occurred:\n{error}"
            )




    def get_selected_game_id(self):
        game_id = self.game_selector.currentData()

        if game_id is None:
            return None

        return int(game_id)





    def update_dashboard(self):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:

                # Count games belonging to this organization
                    cur.execute("""
                    SELECT COUNT(*)
                    FROM games
                    WHERE organization_id = %s;
                """, (self.organization_id,))

                    game_count = cur.fetchone()[0]

                # Count plays belonging to this organization's games
                    cur.execute("""
                    SELECT COUNT(*)
                    FROM plays p
                    JOIN games g ON p.game_id = g.id
                    WHERE g.organization_id = %s;
                """, (self.organization_id,))

                    play_count = cur.fetchone()[0]

                # Retrieve the five most recently created games
                    cur.execute("""
                    SELECT name, opponent, game_date
                    FROM games
                    WHERE organization_id = %s
                    ORDER BY created_at DESC
                    LIMIT 5;
                    """, (self.organization_id,))

                    recent_games = cur.fetchall()

        # Update dashboard cards
            self.dashboard_game_count.setText(str(game_count))
            self.dashboard_play_count.setText(str(play_count))

        # Reports are not currently stored in a database table
            self.dashboard_report_count.setText("Not tracked")

        # Update recent activity
            if recent_games:
                activity_text = ""

                for name, opponent, game_date in recent_games:
                    opponent_text = opponent or "Opponent not specified"
                    date_text = (
                        game_date.strftime("%b %d, %Y")
                        if game_date
                        else "Date not specified"
                    )

                    activity_text += (
                        f"{name} vs {opponent_text} — {date_text}\n"
                    )

                self.dashboard_activity.setText(activity_text)

            else:
                self.dashboard_activity.setText(
                    "No games have been created yet."
                )

        except Exception as error:
            self.dashboard_game_count.setText("—")
            self.dashboard_play_count.setText("—")
            self.dashboard_report_count.setText("—")
            self.dashboard_activity.setText(
                f"Could not load dashboard information: {error}"
            )

            print(f"Dashboard update failed: {error}")




    def update_play_detail(self):
        selected_rows = self.table.selectionModel().selectedRows()

        if not selected_rows:
            for value_label in self.play_detail_values.values():
                value_label.setText("—")
            return

        row = selected_rows[0].row()

        column_mapping = {
            "series": 0,
            "play_number": 1,
            "quarter": 2,
        "game_time": 3,
        "down": 4,
        "distance": 5,
        "hash": 6,
        "yardline": 7,
        "rpn": 8,
        "yards_gained": 9,
        "result": 10,
        "film_verified": 11,
        }

        for field_key, column in column_mapping.items():
            cell_widget = self.table.cellWidget(row, column)

            if isinstance(cell_widget, QComboBox):
                value = cell_widget.currentText().strip()

            else:
                item = self.table.item(row, column)

                if item is not None:
                    value = item.text().strip()
                else:
                    value = ""

            if not value:
                value = "Not recorded"

            self.play_detail_values[field_key].setText(value)




    def edit_game_setup(self):
        game_id = self.get_selected_game_id()

        if not game_id:
            QMessageBox.warning(
                self,
                "No Game Selected",
                "Select a game before editing its setup."
            )
            return

        try:
        # Retrieve the selected game's existing information
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    SELECT
                        name,
                        opponent,
                        season,
                        game_date,
                        location,
                        scouting_focus,
                        general_notes
                    FROM games
                    WHERE id = %s
                      AND organization_id = %s
                    """,
                        (game_id, self.organization_id)
                    )

                    record = cur.fetchone()

            if record is None:
                QMessageBox.warning(
                    self,
                    "Game Not Found",
                    "The selected game could not be found."
                )
                self.refresh_games()
                return

            game_data = {
                "name": record[0],
                "opponent": record[1],
                "season": record[2],
                "game_date": record[3],
                "location": record[4],
                "scouting_focus": record[5],
                "general_notes": record[6]
            }

        # Open the setup dialog with the existing information
            dialog = GameSetupDialog(self, game_data)

            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            updated_data = dialog.get_game_data()

            if not updated_data["name"]:
                QMessageBox.warning(
                    self,
                    "Missing Game Name",
                    "The game name cannot be blank."
                )
                return

        # Save changes
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                    """
                    UPDATE games
                    SET
                        name = %s,
                        opponent = %s,
                        season = %s,
                        game_date = %s,
                        location = %s,
                        scouting_focus = %s,
                        general_notes = %s
                    WHERE id = %s
                      AND organization_id = %s
                    """,
                        (
                        updated_data["name"],
                        updated_data["opponent"],
                        updated_data["season"],
                        updated_data["game_date"],
                        updated_data["location"],
                        updated_data["scouting_focus"],
                        updated_data["general_notes"],
                        game_id,
                        self.organization_id
                        )
                    )

                # Keep the legacy game_name field consistent
                    cur.execute(
                    """
                        UPDATE plays
                        SET game_name = %s
                        WHERE game_id = %s
                      AND organization_id = %s
                    """,
                    (
                            updated_data["name"],
                            game_id,
                            self.organization_id
                    )
                )

        # Refresh application data
            self.refresh_games()
            self.game_selector.setCurrentText(updated_data["name"])

            self.refresh_central_report_games()
            self.refresh_season_selector()
            self.refresh_central_report_seasons()
            self.update_dashboard()

            QMessageBox.information(
                self,
                "Game Updated",
                f'{updated_data["name"]} has been updated successfully.'
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Could Not Update Game",
                f"An error occurred while updating the game:\n{error}"
            )




    def closeEvent(self, event):
    # Flush pending autosaves before taking the final backup.
        if hasattr(self, "_autosave_timer"):
            self._autosave_timer.stop()

        if hasattr(self, "autosave_pending_rows"):
            self.autosave_pending_rows()

        success, message = create_backup()

        if not success:
            QMessageBox.warning(
                self,
                "Backup Warning",
                message,
            )

        event.accept()








    def open_report(self):
        game_id = self.get_selected_game_id()
        game_name = self.game_selector.currentText().strip()

        if game_id is None:
            QMessageBox.warning(
                self,
                "Select a Game",
                "Select a game before generating a report.",
            )
            return

        report_type = self.report_type_selector.currentText()

        dialog = ReportsDialog(
            game_id,
            game_name,
            self.organization_id,
            report_type,
            self
        )
        dialog.exec()


    def open_situational_analysis(self):
        game_id = self.get_selected_game_id()
        game_name = self.game_selector.currentText().strip()

        if not game_id:
            QMessageBox.warning(
                self,
                "Select a Game",
                "Select a saved game before opening situational analysis.",
            )
            return

        dialog = SituationalAnalysisDialog(
            game_id,
            game_name,
            self.organization_id,
            self
        )
        dialog.exec()


    def add_play(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

        defaults = {
            0: "1",       # Series
            1: str(row + 1),  # Visible play number
            2: "1",       # Quarter
            3: "",   # Game time
            4: "",        # Down
            5: "",        # Distance
            6: "",        # Hash
            7: "",     # Yardline unknown until confirmed
            8: "",        # Run / Pass / No play
            9: "",        # Yards gained
            10: "",       # Result
            11: "",     # Film verified
            12: "",       # Database ID: blank means new record
        }

        for column, value in defaults.items():
            self.set_cell_value(row, column, value)

        self.table.setCurrentCell(row, 4)
        self.table.editItem(self.table.item(row, 4))
        self.update_status()

    def open_statistics(self):
        game = self.game_selector.currentText().strip()

        if not game:
            QMessageBox.warning(
                self,
                "Select a Game",
                "Select or enter a game name first.",
         )
            return

        dialog = StatisticsDialog(game, self.organization_id, self)
        dialog.exec()

    def save_changes(self):
        print("DEBUG: Save Changes button triggered.", flush=True)

        game = self.game_selector.currentText().strip()
        print(f"DEBUG: Selected game = {game!r}", flush=True)

        if not game:
            QMessageBox.warning(
                self, "Game Required", "Select a game first."
            )
            return

        game_id = self.get_selected_game_id()

        if game_id is None:
            QMessageBox.warning(
                self,
                "Game Required",
                "The selected game could not be found. Refresh the game list.",
            )
            return

        saved_count = 0

        def optional_int(value, field_name, row_number):
            value = value.strip()

            if value == "":
                return None

            try:
                return int(value)
            except ValueError:
                raise ValueError(
                    f"Row {row_number}: {field_name} must be "
                    "a whole number or left blank."
                )

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:

                    for row in range(self.table.rowCount()):
                        row_number = row + 1

                        values = [
                            self.cell_text(row, col).strip()
                            for col in range(11)
                        ]

                    # Sequence defaults.
                        series = optional_int(
                            values[0], "Series number", row_number
                        )
                        play_number = optional_int(
                            values[1], "Play number", row_number
                        )

                        if series is None:
                            series = 1

                        if play_number is None:
                            play_number = row_number

                        if series < 1 or play_number < 1:
                            raise ValueError(
                                f"Row {row_number}: series and play "
                                "numbers must be positive."
                            )

                    # Optional numeric fields.
                        quarter = optional_int(
                            values[2], "Quarter", row_number
                        )
                        down = optional_int(
                            values[4], "Down", row_number
                        )
                        distance = optional_int(
                            values[5], "Distance", row_number
                        )
                        yards_gained = optional_int(
                            values[9], "Yards gained", row_number
                        )

                        if quarter is not None and quarter not in (1, 2, 3, 4, 5):
                            raise ValueError(
                                f"Row {row_number}: quarter must be 1–5."
                            )

                        if down is not None and down not in (1, 2, 3, 4):
                            raise ValueError(
                                f"Row {row_number}: down must be 1–4."
                            )

                        if distance is not None and distance < 0:
                            raise ValueError(
                                f"Row {row_number}: distance cannot be negative."
                            )

                    # Yardline.
                        yardline_text = values[7].strip().upper()

                        if yardline_text in ("", "N/A", "NA"):
                            yardline = None
                        else:
                            yardline = optional_int(
                                yardline_text, "Yardline", row_number
                            )

                            if yardline is not None and (
                                not -49 <= yardline <= 50
                                or yardline == 0
                            ):
                                raise ValueError(
                                    f"Row {row_number}: yardline must be "
                                    f"-49 to 50, excluding 0, or N/A."
                                )

                    # Hash.
                        hash_value = values[6].strip().upper()

                        if hash_value in ("", "N/A", "NA"):
                            hash_value = None
                        elif hash_value not in (
                            "L", "M", "R", "LH", "RH",
                            "LM", "RM", "LEFT", "RIGHT", "MIDDLE"
                        ):
                            raise ValueError(
                                f"Row {row_number}: invalid hash."
                            )

                    # Run / Pass / No Play.
                        rpn = values[8].strip().upper()

                        if rpn in ("", "N/A", "NA"):
                            rpn = None
                        elif rpn in ("R", "RUN"):
                            rpn = "R"
                        elif rpn in ("P", "PASS"):
                            rpn = "P"
                        elif rpn in ("N", "NO PLAY", "NO-PLAY", "NOPLAY"):
                            rpn = "N"
                        else:
                            raise ValueError(
                                f"Row {row_number}: R/P/N must be R, P, "
                                f"N, or left blank."
                            )

                        game_time = values[3] or None
                        result = values[10] or None

                    # Reflect assigned sequence numbers in the UI.
                        self.set_cell_value(row, 0, str(series))
                        self.set_cell_value(row, 1, str(play_number))

                    # Database ID is stored in hidden column 12.
                        db_id_text = self.cell_text(row, 12).strip()

                        fields = (
                            game,
                            series,
                            play_number,
                            quarter,
                            game_time,
                            down,
                            distance,
                            hash_value,
                            rpn,
                            yards_gained,
                            result,
                            yardline,
                        )

                        if db_id_text:
                            try:
                                db_id = int(db_id_text)
                            except ValueError:
                                raise ValueError(
                                    f"Row {row_number}: invalid database ID. "
                                    "Reload the game and try again."
                                )

                            cur.execute(
                                """
                                UPDATE plays
                                SET game_name = %s,
                                    series_number = %s,
                                play_number = %s,
                                quarter = %s,
                                game_time = %s,
                                down = %s,
                                distance = %s,
                                hash = %s,
                                rpn = %s,
                                yards_gained = %s,
                                result_reason = %s,
                                yardline = %s,
                                game_id = %s
                            WHERE id = %s
                              AND organization_id = %s
                            """,
                                fields + (
                                    game_id,
                                    db_id,
                                    self.organization_id,
                             ),
                            )

                            if cur.rowcount != 1:
                                raise ValueError(
                                f"Row {row_number}: database record "
                                "was not found. Reload the game."
                            )

                        else:
                            cur.execute(
                            """
                            INSERT INTO plays (
                                game_name,
                                series_number,
                                play_number,
                                quarter,
                                game_time,
                                down,
                                distance,
                                hash,
                                rpn,
                                yards_gained,
                                result_reason,
                                yardline,
                                organization_id,
                                game_id
                            )
                            VALUES (
                                %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s
                            )
                            RETURNING id
                            """,
                                fields + (
                                    self.organization_id,
                                    game_id,
                                ),
                            )

                            new_id = cur.fetchone()[0]
                            self.set_cell_value(row, 12, str(new_id))

                        saved_count += 1

            self.refresh_games()

            self.status_label.setText(
                f"Saved successfully. Processed {saved_count} plays."
         )

            QMessageBox.information(
                self,
                "Save Complete",
                f"Saved {saved_count} play records.",
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Save Error",
                f"No changes from this save were committed.\n\n{error}",
            )

    def schedule_row_autosave(self, row, column=None):
        if self._autosave_suspended:
            return

    # Film Verified and Database ID are not autosaved.
        if column in (11, 12):
            return

        game_name = self.game_selector.currentText().strip()

        if not game_name:
            self.status_label.setText("Select a game before editing plays.")
            return

        game_id = self.get_selected_game_id()

        if game_id is None:
            self.status_label.setText("Autosave unavailable: game not found.")
            return

    # Remember which game this row belongs to.
        self._pending_autosave_rows[row] = (game_id, game_name)

    # Restart the timer after each edit.
        self._autosave_timer.start()


    def autosave_pending_rows(self):
        pending = dict(self._pending_autosave_rows)
        failed_rows = set()

        for row, game_info in pending.items():
            game_id, game_name = game_info

            if row < 0 or row >= self.table.rowCount():
                failed_rows.add(row)
                continue

            if not self.autosave_row(row, game_id, game_name):
                failed_rows.add(row)
            else:
                self._pending_autosave_rows.pop(row, None)

        return len(failed_rows) == 0


    def autosave_row(self, row, game_id, game_name):
        self._autosave_suspended = True

        try:
            values = [
                self.cell_text(row, col).strip()
                for col in range(11)
            ]

            def optional_int(value, field_name):
                if value == "":
                    return None

                try:
                    return int(value)
                except ValueError:
                    raise ValueError(
                        f"{field_name} must be a whole number or blank."
                    )

            series = optional_int(values[0], "Series number")
            play_number = optional_int(values[1], "Play number")

            if series is None:
                series = 1

            if play_number is None:
                play_number = row + 1

            if series < 1 or play_number < 1:
                raise ValueError("Series and play numbers must be positive.")

            quarter = optional_int(values[2], "Quarter")
            down = optional_int(values[4], "Down")
            distance = optional_int(values[5], "Distance")
            yards_gained = optional_int(values[9], "Yards gained")

            if quarter is not None and quarter not in (1, 2, 3, 4, 5):
                raise ValueError("Quarter must be between 1 and 5.")

            if down is not None and down not in (1, 2, 3, 4):
                raise ValueError("Down must be between 1 and 4.")

            if distance is not None and distance < 0:
                raise ValueError("Distance cannot be negative.")

            yardline_text = values[7].upper()

            if yardline_text in ("", "N/A", "NA"):
                yardline = None
            else:
                yardline = optional_int(yardline_text, "Yardline")

                if yardline is not None and (
                    not -49 <= yardline <= 50 or yardline == 0
                ):
                    raise ValueError(
                        "Yardline must be -49 to 50, excluding 0, or N/A."
                    )

            hash_value = values[6].upper()

            if hash_value in ("", "N/A", "NA"):
                hash_value = None
            elif hash_value not in (
                "L", "M", "R", "LH", "RH",
                "LM", "RM", "LEFT", "RIGHT", "MIDDLE"
            ):
                raise ValueError("Invalid hash value.")

            rpn = values[8].upper()

            if rpn in ("", "N/A", "NA"):
                rpn = None
            elif rpn in ("R", "RUN"):
                rpn = "R"
            elif rpn in ("P", "PASS"):
                rpn = "P"
            elif rpn in ("N", "NO PLAY", "NO-PLAY", "NOPLAY"):
                rpn = "N"
            else:
                raise ValueError("R/P/N must be R, P, N, or blank.")

            game_time = values[3] or None
            result = values[10] or None

            fields = (
                game_name,
                series,
                play_number,
                quarter,
                game_time,
                down,
                distance,
                hash_value,
                rpn,
                yards_gained,
                result,
                yardline,
            )

        # Update the visible sequence numbers without triggering autosave.
            self.set_cell_value(row, 0, str(series))
            self.set_cell_value(row, 1, str(play_number))

            db_id_text = self.cell_text(row, 12).strip()

            with get_connection() as conn:
                with conn.cursor() as cur:

                    if db_id_text:
                        db_id = int(db_id_text)

                        cur.execute(
                        """
                            UPDATE plays
                            SET
                            game_name = %s,
                            series_number = %s,
                            play_number = %s,
                            quarter = %s,
                            game_time = %s,
                            down = %s,
                            distance = %s,
                            hash = %s,
                            rpn = %s,
                            yards_gained = %s,
                            result_reason = %s,
                            yardline = %s,
                            game_id = %s
                        WHERE id = %s
                          AND organization_id = %s
                          AND game_id = %s
                        """,
                            fields + (
                                game_id,
                                db_id,
                                self.organization_id,
                                game_id,
                            ),
                        )

                        if cur.rowcount != 1:
                            raise ValueError(
                            "Play record was not found. Reload the game."
                            )

                    else:
                        cur.execute(
                        """
                        INSERT INTO plays (
                            game_name,
                            series_number,
                            play_number,
                            quarter,
                            game_time,
                            down,
                            distance,
                            hash,
                            rpn,
                            yards_gained,
                            result_reason,
                            yardline,
                            organization_id,
                            game_id
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING id
                        """,
                            fields + (
                                self.organization_id,
                                game_id,
                            ),
                        )

                        new_id = cur.fetchone()[0]
                        self.set_cell_value(row, 12, str(new_id))

            self.status_label.setText(
                f"Autosaved Play {play_number} — {game_name}"
            )
            return True

        except Exception as error:
            self.status_label.setText(
                f"Autosave failed for row {row + 1}: {error}"
            )
            print(
                f"DEBUG: Autosave failed for row {row + 1}: {error}",
                flush=True,
            )
            return False

        finally:
            self._autosave_suspended = False



    def set_cell_value(self, row, column, value):
        # Dropdowns for common football charting fields.
        options = {
            2: ["", "1", "2", "3", "4", "5"],  # Quarter
            4: ["", "1", "2", "3", "4"],       # Down
            6: ["", "L", "M", "R", "N/A"],     # Hash
            8: ["", "R", "P", "N"],            # Run / Pass / No play
            11: ["", "No", "Yes"],             # Film verified
        }

        if column in options:
            combo = QComboBox()
            combo.addItems(options[column])

            # Hash can use a custom value if needed.
            if column == 6:
                combo.setEditable(True)

            if column == 8:
                combo.setToolTip(
                    "R = Run, P = Pass, N = No play"
                )

            text = (
                "N/A"
                if column == 7 and value is None
                else "" if value is None
                else str(value)
            )

            # Preserve existing values that aren't in the suggestions.
            if text and combo.findText(text) == -1:
                combo.addItem(text)

            combo.setCurrentText(text)
            self.table.setCellWidget(row, column, combo)

# Detect changes made through dropdowns
            if column != 11:
                combo.currentTextChanged.connect(
                    lambda value, r=row, c=column:
                        self.schedule_row_autosave(r, c)
                    )

        else:
            text = (
                "N/A"
                if column == 7 and value is None
                else "" if value is None
                else str(value)
            )
            previous_state = self.table.blockSignals(True)

            try:
                self.table.setItem(
                    row, column, QTableWidgetItem(text)
                    )
            finally:
                self.table.blockSignals(previous_state)

    def cell_text(self, row, column):
        widget = self.table.cellWidget(row, column)

        if isinstance(widget, QComboBox):
            return widget.currentText().strip()

        item = self.table.item(row, column)
        return item.text().strip() if item else ""

    def delete_selected(self):
        rows = sorted(
            {
                index.row()
                for index in self.table.selectionModel().selectedRows()
            },
            reverse=True,
        )

        if not rows:
            QMessageBox.information(
                self, "Select a Play", "Select a row to delete."
            )
            return

        answer = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Delete the selected play records permanently?",
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

    # Stop the timer and save pending edits before changing row positions.
        self._autosave_timer.stop()

        if not self.autosave_pending_rows():
            QMessageBox.warning(
                self,
                "Deletion Cancelled",
                (
                    "One or more pending play edits could not be saved.\n\n"
                    "Correct the affected entries and try deleting again."
                ),
            )
            return

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    for row in rows:
                        db_id = self.cell_text(row, 12)

                        if db_id:
                            cur.execute(
                            """
                            DELETE FROM plays
                            WHERE id = %s
                              AND organization_id = %s
                            """,
                                (int(db_id), self.organization_id),
                            )

            for row in rows:
                self.table.removeRow(row)

            self.update_status()
            self.status_label.setText(
                f"Deleted {len(rows)} selected rows."
            )

        except Exception as error:
            QMessageBox.critical(
                self, "Delete Error", str(error)
            )



    def update_status(self):
        self.status_label.setText(
            f"Ready | {self.table.rowCount()} plays"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)

    saved_user = load_session()

    if saved_user is not None:
        current_user = saved_user

    else:
        login_dialog = LoginDialog()

        if login_dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)

        current_user = login_dialog.user
        save_session(current_user)

    window = FootballApp(current_user)

    # Create a recovery point before the user starts working.
    success, message = create_backup()

    if not success:
        QMessageBox.warning(
            window,
            "Backup Warning",
            message,
        )

    window.show()

    sys.exit(app.exec())