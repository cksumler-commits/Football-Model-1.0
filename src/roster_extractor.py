
import sys
import re
import json
import csv
import sqlite3
import requests

from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from bs4 import BeautifulSoup

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QFileDialog,
    QComboBox,
    QHeaderView,
    QProgressBar,
)


# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "Football Roster Extractor"
APP_VERSION = "1.0"

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "roster_extractor.db"

TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
}

PLAYER_FIELDS = [
    "name",
    "first_name",
    "last_name",
    "jersey_number",
    "position",
    "height",
    "weight",
    "class_year",
    "experience",
    "hometown",
    "high_school",
    "previous_school",
]

DISPLAY_FIELDS = [
    "name",
    "jersey_number",
    "position",
    "height",
    "weight",
    "class_year",
    "experience",
    "hometown",
    "high_school",
    "previous_school",
    "school",
    "season",
    "warnings",
    "source_url",
]

HEADER_ALIASES = {
    "name": {
        "name", "player", "playername",
        "athlete", "studentathlete", "fullname"
    },
    "jersey_number": {
        "number", "jerseynumber", "jersey",
        "no", "uniformnumber", "num"
    },
    "position": {
        "position", "pos"
    },
    "height": {
        "height", "ht"
    },
    "weight": {
        "weight", "wt"
    },
    "class_year": {
        "class", "year", "academicclass",
        "classyear", "eligibility", "academicyear"
    },
    "experience": {
        "experience", "eligibilityexperience",
        "seasonsplayed"
    },
    "hometown": {
        "hometown", "home", "hometownlocation",
        "citystate"
    },
    "high_school": {
        "highschool", "prep", "prepschool"
    },
    "previous_school": {
        "previousschool", "prevschool",
        "lastschool", "collegetransfer"
    },
}


# ============================================================
# GENERAL UTILITIES
# ============================================================

def clean_text(value):

    if value is None:
        return ""

    value = str(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_header(value):

    value = clean_text(value).lower()

    return re.sub(
        r"[^a-z0-9]",
        "",
        value
    )


def empty_player():

    return {
        field: ""
        for field in PLAYER_FIELDS
    }


def split_name(name):

    name = clean_text(name)

    parts = name.split()

    if len(parts) < 2:
        return name, ""

    return (
        " ".join(parts[:-1]),
        parts[-1]
    )


def normalize_position(position):

    position = clean_text(position).upper()

    aliases = {
        "QB": "QB",
        "QUARTERBACK": "QB",
        "RB": "RB",
        "HB": "RB",
        "TB": "RB",
        "RUNNING BACK": "RB",
        "FB": "FB",
        "FULLBACK": "FB",
        "WR": "WR",
        "WIDE RECEIVER": "WR",
        "TE": "TE",
        "TIGHT END": "TE",
        "OL": "OL",
        "OFFENSIVE LINE": "OL",
        "OT": "OT",
        "OG": "OG",
        "C": "C",
        "DL": "DL",
        "DEFENSIVE LINE": "DL",
        "DE": "DE",
        "DT": "DT",
        "NT": "NT",
        "LB": "LB",
        "LINEBACKER": "LB",
        "ILB": "ILB",
        "OLB": "OLB",
        "CB": "CB",
        "CORNERBACK": "CB",
        "S": "S",
        "SAFETY": "S",
        "FS": "FS",
        "SS": "SS",
        "DB": "DB",
        "DEFENSIVE BACK": "DB",
        "K": "K",
        "PK": "K",
        "P": "P",
        "LS": "LS",
        "ATH": "ATH",
        "ATHLETE": "ATH",
    }

    return aliases.get(position, position)


def infer_school(soup, url):

    if soup.title:
        title = clean_text(soup.title.get_text())

        title = re.sub(
            r"\s*[|–—-]\s*.*$",
            "",
            title
        )

        if title:
            return title

    hostname = urlparse(url).hostname or ""

    return hostname.replace("www.", "")


def infer_season(soup, url):

    text = ""

    if soup.title:
        text += soup.title.get_text(" ", strip=True)

    text += " " + url

    matches = re.findall(
        r"\b20\d{2}\b",
        text
    )

    return matches[0] if matches else ""


def complete_player(player):

    for field in PLAYER_FIELDS:
        player.setdefault(field, "")

    player["name"] = clean_text(player["name"])

    first, last = split_name(player["name"])

    player["first_name"] = first
    player["last_name"] = last

    player["jersey_number"] = clean_text(
        player["jersey_number"]
    ).lstrip("#")

    player["position"] = normalize_position(
        player["position"]
    )

    return player


# ============================================================
# WEBSITE RETRIEVAL
# ============================================================

class WebsiteRetriever:

    @staticmethod
    def retrieve(url, use_browser=True):

        url = url.strip()

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        errors = []

        # First attempt: ordinary HTTP request.
        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT
            )

            response.raise_for_status()

            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            if "html" not in content_type:
                raise RuntimeError(
                    "The website did not return HTML."
                )

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            return soup, response.url, "Requests"

        except Exception as error:
            errors.append(str(error))

        # Second attempt: optional JavaScript browser.
        if use_browser:

            try:

                from playwright.sync_api import sync_playwright

                with sync_playwright() as playwright:

                    browser = playwright.chromium.launch(
                        headless=True
                    )

                    page = browser.new_page(
                        user_agent=HEADERS["User-Agent"]
                    )

                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=45000
                    )

                    page.wait_for_timeout(2000)

                    html = page.content()
                    final_url = page.url

                    browser.close()

                soup = BeautifulSoup(
                    html,
                    "html.parser"
                )

                return soup, final_url, "Playwright"

            except ImportError:
                errors.append(
                    "Playwright is not installed."
                )

            except Exception as error:
                errors.append(
                    f"Browser retrieval failed: {error}"
                )

        raise RuntimeError(
            "Unable to retrieve website.\n\n"
            + "\n".join(errors)
        )

    @staticmethod
    def retrieve_browser(url):

        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:

            browser = playwright.chromium.launch(
                headless=True
            )

            page = browser.new_page()

            page.goto(
                url,
                wait_until="networkidle",
                timeout=60000
            )

            html = page.content()
            final_url = page.url

            browser.close()

        return (
            BeautifulSoup(html, "html.parser"),
            final_url,
            "Playwright"
        )


# ============================================================
# EXTRACTION STRATEGY 1: HTML TABLES
# ============================================================

class TableExtractor:

    @staticmethod
    def identify_columns(headers):

        mapping = {}

        for index, header in enumerate(headers):

            normalized = normalize_header(header)

            for field, aliases in HEADER_ALIASES.items():

                if normalized in aliases:
                    mapping[field] = index

        return mapping

    @staticmethod
    def extract(soup):

        candidates = []

        for table in soup.find_all("table"):

            rows = table.find_all("tr")

            for header_index, row in enumerate(rows[:8]):

                cells = row.find_all(["th", "td"])

                headers = [
                    clean_text(
                        cell.get_text(" ", strip=True)
                    )
                    for cell in cells
                ]

                mapping = TableExtractor.identify_columns(
                    headers
                )

                if (
                    "name" in mapping
                    and (
                        "position" in mapping
                        or "jersey_number" in mapping
                    )
                ):

                    score = len(mapping)

                    candidates.append((
                        score,
                        table,
                        header_index,
                        mapping
                    ))

                    break

        if not candidates:
            return []

        candidates.sort(
            key=lambda item: item[0],
            reverse=True
        )

        _, table, header_index, mapping = candidates[0]

        players = []

        rows = table.find_all("tr")

        for row in rows[header_index + 1:]:

            cells = row.find_all(["td", "th"])

            if not cells:
                continue

            values = [
                clean_text(
                    cell.get_text(" ", strip=True)
                )
                for cell in cells
            ]

            player = empty_player()

            for field, column in mapping.items():

                if column < len(values):
                    player[field] = values[column]

            # Prefer linked player name when available.
            name_index = mapping.get("name")

            if name_index is not None and name_index < len(cells):

                anchor = cells[name_index].find("a")

                if anchor:
                    player["name"] = clean_text(
                        anchor.get_text(" ", strip=True)
                    )

            player = complete_player(player)

            if player["name"]:
                players.append(player)

        return players


# ============================================================
# EXTRACTION STRATEGY 2: ROSTER CARDS
# ============================================================

class CardExtractor:

    CARD_SELECTORS = [
        ".sidearm-roster-player",
        ".roster-player",
        ".roster-item",
        ".player-card",
        ".roster-card",
        "[class*='roster-player']",
        "[class*='rosterPlayer']",
        "[class*='player-card']",
        "[class*='playerCard']",
    ]

    FIELD_KEYWORDS = {

        "jersey_number": [
            "jersey-number",
            "player-number",
            "uniform-number",
            "number",
        ],

        "position": [
            "position",
            "player-position",
        ],

        "height": [
            "height",
            "player-height",
        ],

        "weight": [
            "weight",
            "player-weight",
        ],

        "class_year": [
            "academic-year",
            "class-year",
            "player-class",
            "academic-class",
        ],

        "experience": [
            "experience",
        ],

        "hometown": [
            "hometown",
            "home-town",
        ],

        "high_school": [
            "highschool",
            "high-school",
        ],

        "previous_school": [
            "previous-school",
            "prev-school",
        ],
    }

    @staticmethod
    def find_name(card):

        selectors = [
            ".sidearm-roster-player-name",
            ".roster-player-name",
            ".player-name",
            "[class*='player-name']",
            "h3",
            "h2",
        ]

        for selector in selectors:

            element = card.select_one(selector)

            if element:

                name = clean_text(
                    element.get_text(" ", strip=True)
                )

                if name:
                    return name

        return ""

    @staticmethod
    def find_field(card, keywords):

        for element in card.find_all(True):

            classes = element.get("class", [])

            class_text = " ".join(classes).lower()

            for keyword in keywords:

                if keyword in class_text:

                    value = clean_text(
                        element.get_text(" ", strip=True)
                    )

                    if value:
                        return value

        # Try structured definition lists.
        for dt in card.find_all("dt"):

            label = normalize_header(
                dt.get_text(" ", strip=True)
            )

            following = dt.find_next_sibling("dd")

            if following:

                for keyword in keywords:

                    if normalize_header(keyword) in label:

                        return clean_text(
                            following.get_text(" ", strip=True)
                        )

        return ""

    @classmethod
    def extract(cls, soup):

        cards = []
        seen = set()

        for selector in cls.CARD_SELECTORS:

            for card in soup.select(selector):

                identity = id(card)

                if identity not in seen:

                    seen.add(identity)
                    cards.append(card)

        players = []

        for card in cards:

            player = empty_player()

            player["name"] = cls.find_name(card)

            if not player["name"]:
                continue

            for field, keywords in cls.FIELD_KEYWORDS.items():

                player[field] = cls.find_field(
                    card,
                    keywords
                )

            player = complete_player(player)

            players.append(player)

        # Avoid nested card duplicates.
        return players


# ============================================================
# EXTRACTION STRATEGY 3: STRUCTURED JSON-LD
# ============================================================

class StructuredDataExtractor:

    @staticmethod
    def extract(soup):

        players = []

        for script in soup.find_all(
            "script",
            type="application/ld+json"
        ):

            try:

                data = json.loads(
                    script.string or script.get_text()
                )

            except (json.JSONDecodeError, TypeError):
                continue

            objects = data if isinstance(data, list) else [data]

            for obj in objects:

                if not isinstance(obj, dict):
                    continue

                entries = obj.get(
                    "itemListElement",
                    []
                )

                if entries:

                    for entry in entries:

                        item = entry.get("item", entry)

                        if isinstance(item, dict):

                            name = item.get("name", "")

                            if name:
                                player = empty_player()
                                player["name"] = name
                                players.append(
                                    complete_player(player)
                                )

        return players


# ============================================================
# NORMALIZATION AND VALIDATION
# ============================================================

class PlayerValidator:

    @staticmethod
    def validate(players):

        seen = {}

        for player in players:

            warnings = []

            name = clean_text(
                player.get("name", "")
            )

            key = name.casefold()

            if not name:
                warnings.append("Missing player name")

            if key in seen:
                warnings.append(
                    "Possible duplicate player name"
                )

            seen[key] = True

            if not player.get("position"):
                warnings.append("Missing position")

            if not player.get("jersey_number"):
                warnings.append("Missing jersey number")

            if not player.get("class_year"):
                warnings.append("Missing class year")

            player["warnings"] = warnings

        return players


# ============================================================
# MAIN EXTRACTION ENGINE
# ============================================================

class RosterEngine:

    @staticmethod
    def extract(url, school="", season=""):

        soup, final_url, retrieval_method = (
            WebsiteRetriever.retrieve(url)
        )

        title = ""

        if soup.title:
            title = clean_text(
                soup.title.get_text()
            )

        detected_school = (
            clean_text(school)
            or infer_school(soup, final_url)
        )

        detected_season = (
            clean_text(season)
            or infer_season(soup, final_url)
        )

        # Each strategy is attempted in order.
        strategies = [
            ("HTML Table", TableExtractor.extract),
            ("Roster Cards", CardExtractor.extract),
            (
                "Structured JSON-LD",
                StructuredDataExtractor.extract
            ),
        ]

        players = []
        extraction_method = ""

        for method, extractor in strategies:

            try:
                players = extractor(soup)

            except Exception:
                players = []

            if players:
                extraction_method = method
                break

        if not players:

            try:

                soup, final_url, retrieval_method = (
                 WebsiteRetriever.retrieve_browser(url)
                )

                for method, extractor in strategies:

                    try:
                        players = extractor(soup)

                    except Exception:
                        players = []

                    if players:
                        extraction_method = method
                        break

            except Exception:
                players = []

        if not players:

         raise RuntimeError(
        "No recognizable roster structure was found. "
        "This website may require a custom extraction adapter."
        )

        for player in players:

            complete_player(player)

            player["school"] = detected_school
            player["season"] = detected_season
            player["source_url"] = final_url
            player["source_title"] = title
            player["retrieval_method"] = retrieval_method
            player["extraction_method"] = extraction_method

        players = PlayerValidator.validate(players)

        return players


# ============================================================
# LOCAL DATABASE
# ============================================================

class RosterDatabase:

    def __init__(self):

        self.connection = sqlite3.connect(
            DATABASE_PATH
        )

        self.connection.row_factory = sqlite3.Row

        self.create_tables()

    def create_tables(self):

        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rosters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                school TEXT NOT NULL,
                season TEXT,
                source_url TEXT,
                source_title TEXT,
                extraction_method TEXT,
                imported_at TEXT,
                player_count INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roster_id INTEGER NOT NULL,
                name TEXT,
                first_name TEXT,
                last_name TEXT,
                jersey_number TEXT,
                position TEXT,
                height TEXT,
                weight TEXT,
                class_year TEXT,
                experience TEXT,
                hometown TEXT,
                high_school TEXT,
                previous_school TEXT,
                school TEXT,
                season TEXT,
                source_url TEXT,
                source_title TEXT,
                extraction_method TEXT,
                warnings TEXT,
                FOREIGN KEY(roster_id)
                    REFERENCES rosters(id)
                    ON DELETE CASCADE
            )
        """)

        self.connection.commit()

    def save_roster(self, players):

        if not players:
            raise ValueError("No players to save.")

        first = players[0]

        cursor = self.connection.cursor()

        cursor.execute("""
            INSERT INTO rosters (
                school,
                season,
                source_url,
                source_title,
                extraction_method,
                imported_at,
                player_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            first.get("school", ""),
            first.get("season", ""),
            first.get("source_url", ""),
            first.get("source_title", ""),
            first.get("extraction_method", ""),
            datetime.now(timezone.utc).isoformat(),
            len(players),
        ))

        roster_id = cursor.lastrowid

        for player in players:

            cursor.execute("""
                INSERT INTO players (
                    roster_id,
                    name,
                    first_name,
                    last_name,
                    jersey_number,
                    position,
                    height,
                    weight,
                    class_year,
                    experience,
                    hometown,
                    high_school,
                    previous_school,
                    school,
                    season,
                    source_url,
                    source_title,
                    extraction_method,
                    warnings
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                roster_id,
                player.get("name", ""),
                player.get("first_name", ""),
                player.get("last_name", ""),
                player.get("jersey_number", ""),
                player.get("position", ""),
                player.get("height", ""),
                player.get("weight", ""),
                player.get("class_year", ""),
                player.get("experience", ""),
                player.get("hometown", ""),
                player.get("high_school", ""),
                player.get("previous_school", ""),
                player.get("school", ""),
                player.get("season", ""),
                player.get("source_url", ""),
                player.get("source_title", ""),
                player.get("extraction_method", ""),
                json.dumps(player.get("warnings", [])),
            ))

        self.connection.commit()

        return roster_id

    def get_rosters(self):

        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT *
            FROM rosters
            ORDER BY id DESC
        """)

        return cursor.fetchall()

    def get_players(self, roster_id):

        cursor = self.connection.cursor()

        cursor.execute("""
            SELECT *
            FROM players
            WHERE roster_id = ?
            ORDER BY id
        """, (roster_id,))

        return cursor.fetchall()

    def close(self):
        self.connection.close()


# ============================================================
# EXPORT ENGINE
# ============================================================

class RosterExporter:

    @staticmethod
    def export_json(players, path):

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                players,
                file,
                indent=4,
                ensure_ascii=False
            )

    @staticmethod
    def export_csv(players, path):

        fields = DISPLAY_FIELDS

        with open(
            path,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fields,
                extrasaction="ignore"
            )

            writer.writeheader()

            for player in players:

                row = dict(player)

                warnings = row.get("warnings", [])

                if isinstance(warnings, list):
                    row["warnings"] = "; ".join(warnings)

                writer.writerow(row)


# ============================================================
# BACKGROUND EXTRACTION WORKER
# ============================================================

class ExtractionWorker(QThread):

    progress = Signal(int, int, str)
    completed = Signal(list, list)
    failed = Signal(str)

    def __init__(self, tasks):

        super().__init__()

        self.tasks = tasks

    def run(self):

        all_players = []
        failures = []

        try:

            total = len(self.tasks)

            for index, task in enumerate(self.tasks, start=1):

                url = task["url"]

                self.progress.emit(
                    index,
                    total,
                    url
                )

                try:

                    players = RosterEngine.extract(
                        url,
                        task.get("school", ""),
                        task.get("season", "")
                    )

                    for player in players:
                        player["_batch_source"] = url

                    all_players.extend(players)

                except Exception as error:

                    failures.append({
                        "url": url,
                        "error": str(error)
                    })

            self.completed.emit(
                all_players,
                failures
            )

        except Exception as error:

            self.failed.emit(str(error))


# ============================================================
# MAIN APPLICATION
# ============================================================

class RosterExtractorWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            f"{APP_NAME} {APP_VERSION}"
        )

        self.resize(1450, 850)

        self.database = RosterDatabase()

        self.current_players = []
        self.worker = None

        self.tabs = QTabWidget()

        self.single_tab = QWidget()
        self.batch_tab = QWidget()
        self.library_tab = QWidget()

        self.tabs.addTab(
            self.single_tab,
            "Individual Extraction"
        )

        self.tabs.addTab(
            self.batch_tab,
            "Batch Extraction"
        )

        self.tabs.addTab(
            self.library_tab,
            "Roster Library"
        )

        self.build_single_tab()
        self.build_batch_tab()
        self.build_library_tab()

        self.results_table = QTableWidget()

        self.results_table.setColumnCount(
            len(DISPLAY_FIELDS)
        )

        self.results_table.setHorizontalHeaderLabels(
            DISPLAY_FIELDS
        )

        self.results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        self.results_table.setAlternatingRowColors(True)

        self.status_label = QLabel("Ready.")

        self.progress_bar = QProgressBar()

        self.progress_bar.setVisible(False)

        main = QWidget()
        layout = QVBoxLayout(main)

        layout.addWidget(
            QLabel("FOOTBALL ROSTER EXTRACTOR")
        )

        layout.addWidget(self.tabs)

        layout.addWidget(
            QLabel("Player Records — Editable Preview")
        )

        layout.addWidget(self.results_table)

        actions = QHBoxLayout()

        self.save_button = QPushButton(
            "Save to Local Library"
        )

        self.save_button.clicked.connect(
            self.save_results
        )

        self.json_button = QPushButton(
            "Export JSON"
        )

        self.json_button.clicked.connect(
            self.export_json
        )

        self.csv_button = QPushButton(
            "Export CSV"
        )

        self.csv_button.clicked.connect(
            self.export_csv
        )

        self.clear_button = QPushButton(
            "Clear Results"
        )

        self.clear_button.clicked.connect(
            self.clear_results
        )

        actions.addWidget(self.save_button)
        actions.addWidget(self.json_button)
        actions.addWidget(self.csv_button)
        actions.addWidget(self.clear_button)

        layout.addLayout(actions)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        self.setCentralWidget(main)

        self.set_actions_enabled(False)

        self.refresh_library()

    # --------------------------------------------------------
    # INDIVIDUAL EXTRACTION
    # --------------------------------------------------------

    def build_single_tab(self):

        layout = QVBoxLayout(self.single_tab)

        layout.addWidget(QLabel("Roster URL"))

        self.single_url = QLineEdit()

        self.single_url.setPlaceholderText(
            "Paste a college football roster URL..."
        )

        self.single_url.setText(
            "https://lsusports.net/sports/fb/roster?view=list"
        )

        layout.addWidget(self.single_url)

        layout.addWidget(QLabel("School / Team Name (optional)"))

        self.single_school = QLineEdit()

        self.single_school.setPlaceholderText(
            "Automatically detected if left blank"
        )

        layout.addWidget(self.single_school)

        layout.addWidget(QLabel("Season (optional)"))

        self.single_season = QLineEdit()

        self.single_season.setPlaceholderText(
            "Example: 2026"
        )

        layout.addWidget(self.single_season)

        self.single_button = QPushButton(
            "Extract Roster"
        )

        self.single_button.clicked.connect(
            self.start_single
        )

        layout.addWidget(self.single_button)

    # --------------------------------------------------------
    # BATCH EXTRACTION
    # --------------------------------------------------------

    def build_batch_tab(self):

        layout = QVBoxLayout(self.batch_tab)

        layout.addWidget(
            QLabel(
                "Enter one roster URL per line."
            )
        )

        self.batch_urls = QTextEdit()

        self.batch_urls.setPlaceholderText(
            "https://school1.edu/sports/football/roster\n"
            "https://school2.edu/sports/fb/roster\n"
            "https://school3.edu/football/roster"
        )

        layout.addWidget(self.batch_urls)

        self.batch_button = QPushButton(
            "Process All Rosters"
        )

        self.batch_button.clicked.connect(
            self.start_batch
        )

        layout.addWidget(self.batch_button)

    # --------------------------------------------------------
    # LIBRARY
    # --------------------------------------------------------

    def build_library_tab(self):

        layout = QVBoxLayout(self.library_tab)

        self.library_table = QTableWidget()

        self.library_table.setColumnCount(6)

        self.library_table.setHorizontalHeaderLabels([
            "ID",
            "School",
            "Season",
            "Players",
            "Imported",
            "Source",
        ])

        self.library_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        layout.addWidget(self.library_table)

        buttons = QHBoxLayout()

        refresh_button = QPushButton(
            "Refresh Library"
        )

        refresh_button.clicked.connect(
            self.refresh_library
        )

        load_button = QPushButton(
            "Load Selected Roster"
        )

        load_button.clicked.connect(
            self.load_selected_roster
        )

        buttons.addWidget(refresh_button)
        buttons.addWidget(load_button)

        layout.addLayout(buttons)

    # --------------------------------------------------------
    # WORKER MANAGEMENT
    # --------------------------------------------------------

    def start_single(self):

        url = self.single_url.text().strip()

        if not url:
            QMessageBox.warning(
                self,
                "Missing URL",
                "Enter a roster URL."
            )
            return

        task = {
            "url": url,
            "school": self.single_school.text().strip(),
            "season": self.single_season.text().strip(),
        }

        self.start_worker([task])

    def start_batch(self):

        urls = [
            line.strip()
            for line in self.batch_urls.toPlainText().splitlines()
            if line.strip()
        ]

        if not urls:
            QMessageBox.warning(
                self,
                "Missing URLs",
                "Enter at least one URL."
            )
            return

        tasks = [
            {
                "url": url,
                "school": "",
                "season": "",
            }
            for url in urls
        ]

        self.start_worker(tasks)

    def start_worker(self, tasks):

        if self.worker and self.worker.isRunning():
            return

        self.current_players = []

        self.results_table.setRowCount(0)

        self.progress_bar.setVisible(True)

        self.progress_bar.setRange(
            0,
            len(tasks)
        )

        self.progress_bar.setValue(0)

        self.status_label.setText(
            "Starting extraction..."
        )

        self.set_actions_enabled(False)

        self.single_button.setDisabled(True)
        self.batch_button.setDisabled(True)

        self.worker = ExtractionWorker(tasks)

        self.worker.progress.connect(
            self.on_progress
        )

        self.worker.completed.connect(
            self.on_completed
        )

        self.worker.failed.connect(
            self.on_failed
        )

        self.worker.start()

    def on_progress(self, current, total, url):

        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

        self.status_label.setText(
            f"Processing {current}/{total}: {url}"
        )

    def on_completed(self, players, failures):

        self.current_players = players

        self.display_players(players)

        self.progress_bar.setVisible(False)

        self.single_button.setDisabled(False)
        self.batch_button.setDisabled(False)

        self.set_actions_enabled(
            bool(players)
        )

        successful = len({
            player.get("source_url")
            for player in players
        })

        summary = (
            f"Completed: {successful} successful rosters, "
            f"{len(players)} players, "
            f"{len(failures)} failed URLs."
        )

        self.status_label.setText(summary)

        if failures:

            details = "\n\n".join(
                f"{item['url']}\n{item['error']}"
                for item in failures
            )

            QMessageBox.warning(
                self,
                "Extraction Finished with Errors",
                summary + "\n\n" + details
            )

        else:

            QMessageBox.information(
                self,
                "Extraction Complete",
                summary
            )

    def on_failed(self, error):

        self.progress_bar.setVisible(False)

        self.single_button.setDisabled(False)
        self.batch_button.setDisabled(False)

        self.set_actions_enabled(
            bool(self.current_players)
        )

        QMessageBox.critical(
            self,
            "Extraction Error",
            error
        )

    # --------------------------------------------------------
    # RESULT DISPLAY
    # --------------------------------------------------------

    def display_players(self, players):

        self.results_table.setSortingEnabled(False)

        self.results_table.setRowCount(
            len(players)
        )

        for row, player in enumerate(players):

            for column, field in enumerate(DISPLAY_FIELDS):

                value = player.get(field, "")

                if isinstance(value, list):
                    value = "; ".join(value)

                item = QTableWidgetItem(
                    str(value)
                )

                self.results_table.setItem(
                    row,
                    column,
                    item
                )

        self.results_table.setSortingEnabled(True)

    def read_results(self):

        records = []

        for row in range(self.results_table.rowCount()):

            player = {}

            for column, field in enumerate(DISPLAY_FIELDS):

                item = self.results_table.item(
                    row,
                    column
                )

                value = item.text() if item else ""

                if field == "warnings":

                    value = [
                        warning.strip()
                        for warning in value.split(";")
                        if warning.strip()
                    ]

                player[field] = value

            first, last = split_name(
                player.get("name", "")
            )

            player["first_name"] = first
            player["last_name"] = last

            records.append(player)

        return records

    # --------------------------------------------------------
    # SAVE RESULTS
    # --------------------------------------------------------

    def save_results(self):

        records = self.read_results()

        if not records:
            return

        groups = {}

        for player in records:

            source = player.get("source_url", "")

            if not source:
                QMessageBox.warning(
                    self,
                    "Missing Source",
                    "A player record is missing its source URL."
                )
                return

            groups.setdefault(source, []).append(player)

        saved = 0

        try:

            for players in groups.values():

                self.database.save_roster(players)
                saved += 1

            self.refresh_library()

            QMessageBox.information(
                self,
                "Saved",
                f"Saved {len(records)} players across "
                f"{saved} roster records."
            )

        except Exception as error:

            QMessageBox.critical(
                self,
                "Database Error",
                str(error)
            )

    # --------------------------------------------------------
    # EXPORTS
    # --------------------------------------------------------

    def export_json(self):

        records = self.read_results()

        if not records:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            "roster.json",
            "JSON Files (*.json)"
        )

        if path:

            try:

                RosterExporter.export_json(
                    records,
                    path
                )

                QMessageBox.information(
                    self,
                    "Export Complete",
                    "JSON export completed."
                )

            except Exception as error:

                QMessageBox.critical(
                    self,
                    "Export Error",
                    str(error)
                )

    def export_csv(self):

        records = self.read_results()

        if not records:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            "roster.csv",
            "CSV Files (*.csv)"
        )

        if path:

            try:

                RosterExporter.export_csv(
                    records,
                    path
                )

                QMessageBox.information(
                    self,
                    "Export Complete",
                    "CSV export completed."
                )

            except Exception as error:

                QMessageBox.critical(
                    self,
                    "Export Error",
                    str(error)
                )

    # --------------------------------------------------------
    # LIBRARY OPERATIONS
    # --------------------------------------------------------

    def refresh_library(self):

        rosters = self.database.get_rosters()

        self.library_table.setRowCount(
            len(rosters)
        )

        for row, roster in enumerate(rosters):

            values = [
                roster["id"],
                roster["school"],
                roster["season"],
                roster["player_count"],
                roster["imported_at"],
                roster["source_url"],
            ]

            for column, value in enumerate(values):

                self.library_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(str(value or ""))
                )

    def load_selected_roster(self):

        row = self.library_table.currentRow()

        if row < 0:
            return

        item = self.library_table.item(row, 0)

        roster_id = int(item.text())

        database_players = self.database.get_players(
            roster_id
        )

        players = []

        for record in database_players:

            player = dict(record)

            player.pop("id", None)
            player.pop("roster_id", None)

            try:

                player["warnings"] = json.loads(
                    player.get("warnings", "[]")
                )

            except json.JSONDecodeError:

                player["warnings"] = []

            players.append(player)

        self.current_players = players

        self.display_players(players)

        self.tabs.setCurrentIndex(0)

        self.status_label.setText(
            f"Loaded {len(players)} saved player records."
        )

        self.set_actions_enabled(
            bool(players)
        )

    # --------------------------------------------------------
    # GENERAL INTERFACE
    # --------------------------------------------------------

    def set_actions_enabled(self, enabled):

        self.save_button.setEnabled(enabled)
        self.json_button.setEnabled(enabled)
        self.csv_button.setEnabled(enabled)

    def clear_results(self):

        self.current_players = []

        self.results_table.setRowCount(0)

        self.status_label.setText(
            "Results cleared."
        )

        self.set_actions_enabled(False)

    def closeEvent(self, event):

        if self.worker and self.worker.isRunning():

            QMessageBox.warning(
                self,
                "Extraction Running",
                "Wait for extraction to finish before closing."
            )

            event.ignore()
            return

        self.database.close()

        event.accept()


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

def main():

    app = QApplication(sys.argv)

    window = RosterExtractorWindow()

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
