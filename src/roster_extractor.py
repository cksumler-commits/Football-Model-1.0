
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
        "QUARTERBACK": "QB",
        "QB": "QB",

        "RUNNING BACK": "RB",
        "HALFBACK": "RB",
        "TAILBACK": "RB",
        "RB": "RB",
        "HB": "RB",
        "TB": "RB",

        "FULLBACK": "FB",
        "FB": "FB",

        "WIDE RECEIVER": "WR",
        "WR": "WR",

        "TIGHT END": "TE",
        "TE": "TE",

        "OFFENSIVE LINE": "OL",
        "OL": "OL",
        "OFFENSIVE TACKLE": "OT",
        "OT": "OT",
        "OFFENSIVE GUARD": "OG",
        "OG": "OG",
        "CENTER": "C",
        "OC": "C",
        "C": "C",

        "DEFENSIVE LINE": "DL",
        "DL": "DL",
        "DEFENSIVE END": "DE",
        "DE": "DE",
        "DEFENSIVE TACKLE": "DT",
        "DT": "DT",
        "NOSE TACKLE": "NT",
        "NT": "NT",
        "NOSE GUARD": "NG",
        "NG": "NG",

        "LINEBACKER": "LB",
        "LB": "LB",
        "INSIDE LINEBACKER": "ILB",
        "ILB": "ILB",
        "MIDDLE LINEBACKER": "MLB",
        "MLB": "MLB",
        "OUTSIDE LINEBACKER": "OLB",
        "OLB": "OLB",

        "EDGE": "EDGE",
        "EDGE RUSHER": "EDGE",

        "CORNERBACK": "CB",
        "CB": "CB",

        "DEFENSIVE BACK": "DB",
        "DB": "DB",

        "SAFETY": "S",
        "S": "S",
        "FREE SAFETY": "FS",
        "FS": "FS",
        "STRONG SAFETY": "SS",
        "SS": "SS",

        "NICKEL": "NB",
        "NICKELBACK": "NB",
        "NB": "NB",

        "KICKER": "K",
        "K": "K",

        "PLACE KICKER": "PK",
        "PK": "PK",

        "PUNTER": "P",
        "P": "P",

        "LONG SNAPPER": "LS",
        "LS": "LS",

        "ATHLETE": "ATH",
        "ATH": "ATH",

        "RETURNER": "RET",
        "RET": "RET",
        "KICK RETURNER": "KR",
        "KR": "KR",
        "PUNT RETURNER": "PR",
        "PR": "PR",

        "ROVER": "ROVER",
        "BANDIT": "BANDIT",
        "JACK": "JACK",
    }

    # Keep unfamiliar position labels rather than discarding them.
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
                    break

        return mapping

    @staticmethod
    def extract_candidates(soup):
        candidates = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")

            for header_index, header_row in enumerate(rows[:12]):
                header_cells = header_row.find_all(
                    ["th", "td"],
                    recursive=False
                )

                headers = [
                    clean_text(cell.get_text(" ", strip=True))
                    for cell in header_cells
                ]

                mapping = TableExtractor.identify_columns(headers)

                if "name" not in mapping or len(mapping) < 2:
                    continue

                players = []

                for row_index, row in enumerate(
                    rows[header_index + 1:],
                    start=header_index + 1
                ):
                    cells = row.find_all(
                        ["td", "th"],
                        recursive=False
                    )

                    if not cells:
                        continue

                    values = [
                        clean_text(cell.get_text(" ", strip=True))
                        for cell in cells
                    ]

                    player = empty_player()

                    for field, column in mapping.items():
                        if column < len(values):
                            player[field] = values[column]

                    name_column = mapping["name"]

                    if name_column < len(cells):
                        anchor = cells[name_column].find("a")

                        if anchor:
                            linked_name = clean_text(
                                anchor.get_text(" ", strip=True)
                            )

                            if linked_name:
                                player["name"] = linked_name

                    # Preserve every source column, including columns
                    # the extractor does not recognize.
                    player["raw_fields"] = {
                        header: (
                            values[index]
                            if index < len(values)
                            else ""
                        )
                        for index, header in enumerate(headers)
                    }

                    player["custom_fields"] = {
                        header: values[index]
                        for index, header in enumerate(headers)
                        if (
                            index < len(values)
                            and header
                            and normalize_header(header)
                            not in {
                                alias
                                for aliases in HEADER_ALIASES.values()
                                for alias in aliases
                            }
                            and values[index]
                        )
                    }

                    player["source_headers"] = list(headers)
                    player["raw_source_row"] = list(values)
                    player["source_row_index"] = row_index

                    complete_player(player)

                    if player["name"]:
                        players.append(player)

                players = TableExtractor.remove_duplicates(players)

                if players:
                    candidates.append({
                        "method": "HTML Table",
                        "players": players,
                        "headers": headers,
                        "score": TableExtractor.score(players),
                    })

                # A table should only have one header row.
                break

        return candidates

    @staticmethod
    def remove_duplicates(players):
        unique = []
        seen = set()

        for player in players:
            name = clean_text(player.get("name", "")).casefold()
            number = clean_text(
                player.get("jersey_number", "")
            ).casefold()
            position = clean_text(
                player.get("position", "")
            ).casefold()

            # A name alone is not a safe identity.
            if not name:
                continue

            if number:
                key = (name, number)
            elif position:
                key = (
                    name,
                    position,
                    clean_text(player.get("height", "")),
                    clean_text(player.get("weight", "")),
                )
            else:
                # Preserve records when there is not enough information
                # to confidently identify them as the same player.
                unique.append(player)
                continue

            if key in seen:
                continue

            seen.add(key)
            unique.append(player)

        return unique

    @staticmethod
    def score(players):
        if not players:
            return 0

        populated = 0

        for player in players:
            populated += sum(
                bool(clean_text(player.get(field, "")))
                for field in PLAYER_FIELDS
            )

            populated += len(
                player.get("custom_fields", {})
            )

        average = populated / len(players)

        return len(players) * 100 + average * 10

    @staticmethod
    def extract(soup):
        candidates = TableExtractor.extract_candidates(soup)

        if not candidates:
            return []

        return max(
            candidates,
            key=lambda item: item["score"]
        )["players"]


    

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

    NAME_SELECTORS = [
        ".sidearm-roster-player-name",
        ".roster-player-name",
        ".player-name",
        "[class*='player-name']",
        "h3",
        "h2",
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
            "roster-class",
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

    @classmethod
    def find_name(cls, card):
        for selector in cls.NAME_SELECTORS:
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

        for dt in card.find_all("dt"):
            label = normalize_header(
                dt.get_text(" ", strip=True)
            )

            dd = dt.find_next_sibling("dd")

            if not dd:
                continue

            for keyword in keywords:
                if normalize_header(keyword) in label:
                    return clean_text(
                        dd.get_text(" ", strip=True)
                    )

        return ""

    @classmethod
    def extract(cls, soup):
        matched_cards = []
        seen_ids = set()

        for selector in cls.CARD_SELECTORS:
            for element in soup.select(selector):
                if id(element) in seen_ids:
                    continue

                seen_ids.add(id(element))
                matched_cards.append(element)

        # If a matching element contains another matching element,
        # prefer the inner element. This prevents a roster wrapper
        # and its player card from being counted as separate players.
        cards = []

        for element in matched_cards:
            has_matching_child = any(
                other is not element
                and other in element.descendants
                for other in matched_cards
            )

            if not has_matching_child:
                cards.append(element)

        players = []

        for card in cards:
            player = empty_player()

            player["name"] = cls.find_name(card)

            if not player["name"]:
                continue

            for field, keywords in cls.FIELD_KEYWORDS.items():
                player[field] = cls.find_field(card, keywords)

            card_text = clean_text(
                card.get_text(" ", strip=True)
            )

            player["raw_fields"] = {
                "Card Text": card_text
            }

            player["custom_fields"] = {}
            player["source_headers"] = ["Card Text"]
            player["raw_source_row"] = [card_text]

            complete_player(player)
            players.append(player)

        return TableExtractor.remove_duplicates(players)

    


# ============================================================
# EXTRACTION STRATEGY 3: STRUCTURED JSON-LD
# ============================================================

class StructuredDataExtractor:

    @staticmethod
    def extract(soup):
        players = []

        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return

            if not isinstance(value, dict):
                return

            item_type = value.get("@type", "")

            if isinstance(item_type, list):
                item_type = " ".join(str(item) for item in item_type)

            item_type = str(item_type).lower()

            name = clean_text(value.get("name", ""))

            is_player = any(
                marker in item_type
                for marker in (
                    "person",
                    "athlete",
                    "player",
                )
            )

            if name and is_player:
                player = empty_player()
                player["name"] = name

                field_aliases = {
                    "height": "height",
                    "weight": "weight",
                    "jobTitle": "position",
                    "honorificSuffix": "class_year",
                }

                for source_field, target_field in field_aliases.items():
                    if value.get(source_field):
                        player[target_field] = clean_text(
                            value[source_field]
                        )

                raw_fields = {}

                for key, item in value.items():
                    if not isinstance(item, (dict, list)):
                        raw_fields[str(key)] = clean_text(item)

                player["raw_fields"] = raw_fields
                player["custom_fields"] = {}
                player["source_headers"] = list(raw_fields.keys())
                player["raw_source_row"] = list(raw_fields.values())

                complete_player(player)
                players.append(player)

            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    walk(nested)

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

            walk(data)

        return TableExtractor.remove_duplicates(players)

    


class PatternExtractor:

    """
    General fallback extractor for roster pages that do not use
    recognizable HTML tables or standard player-card classes.

    Uses player-name links, surrounding record structure, explicit
    field labels, HTML attributes, and text patterns.
    """

    NAME_BLACKLIST = {
        "football roster",
        "view roster",
        "full roster",
        "coaching staff",
        "support staff",
        "team roster",
        "view profile",
        "full bio",
        "read more",
        "schedule",
        "statistics",
    }

    CLASS_PATTERNS = [
        r"\bredshirt\s+(?:freshman|sophomore|junior|senior)\b",
        r"\b(?:freshman|sophomore|junior|senior)\b",
        r"\b(?:fifth|sixth|seventh|eighth)\s+year\b",
        r"\bgraduate\s+student\b",
        r"\b(?:1st|2nd|3rd|4th|5th|6th|7th|8th)\s+year\b",
    ]

    # Longer position names and abbreviations come first.
    # Single-letter positions are handled separately to reduce
    # accidental matches in ordinary roster text.
    POSITION_PATTERNS = [
        ("OFFENSIVE LINE", "OL"),
        ("DEFENSIVE LINE", "DL"),
        ("WIDE RECEIVER", "WR"),
        ("RUNNING BACK", "RB"),
        ("TIGHT END", "TE"),
        ("QUARTERBACK", "QB"),
        ("LINEBACKER", "LB"),
        ("CORNERBACK", "CB"),
        ("DEFENSIVE BACK", "DB"),
        ("OFFENSIVE TACKLE", "OT"),
        ("OFFENSIVE GUARD", "OG"),
        ("DEFENSIVE END", "DE"),
        ("DEFENSIVE TACKLE", "DT"),
        ("LONG SNAPPER", "LS"),
        ("PLACE KICKER", "PK"),
        ("PUNTER", "P"),
        ("KICKER", "K"),
        ("FULLBACK", "FB"),
        ("SAFETY", "S"),
        ("EDGE", "EDGE"),
        ("NICKEL", "NB"),
        ("ROVER", "ROVER"),
        ("BANDIT", "BANDIT"),
        ("JACK", "JACK"),
        ("ATHLETE", "ATH"),
        ("QB", "QB"),
        ("RB", "RB"),
        ("HB", "RB"),
        ("TB", "RB"),
        ("FB", "FB"),
        ("WR", "WR"),
        ("TE", "TE"),
        ("OL", "OL"),
        ("OT", "OT"),
        ("OG", "OG"),
        ("OC", "C"),
        ("DL", "DL"),
        ("DE", "DE"),
        ("DT", "DT"),
        ("NT", "NT"),
        ("NG", "NG"),
        ("LB", "LB"),
        ("ILB", "ILB"),
        ("MLB", "MLB"),
        ("OLB", "OLB"),
        ("EDGE", "EDGE"),
        ("CB", "CB"),
        ("DB", "DB"),
        ("FS", "FS"),
        ("SS", "SS"),
        ("NB", "NB"),
        ("LS", "LS"),
        ("PK", "PK"),
        ("ATH", "ATH"),
        ("PR", "PR"),
        ("KR", "KR"),
        ("SAF", "S"),
    ]

    POSITION_LABEL_PATTERN = re.compile(
        r"\b(?:position|pos)\s*[:\-]\s*"
        r"([A-Za-z][A-Za-z /&-]{0,30})",
        re.IGNORECASE
    )

    JERSEY_LABEL_PATTERN = re.compile(
        r"\b(?:jersey|uniform|player)\s*"
        r"(?:number|no\.?|#)\s*[:#\-]?\s*(\d{1,2})\b",
        re.IGNORECASE
    )

    @staticmethod
    def is_likely_name(value):

        value = clean_text(value)

        if not value:
            return False

        if value.casefold() in PatternExtractor.NAME_BLACKLIST:
            return False

        if len(value) > 65:
            return False

        if re.search(r"\d", value):
            return False

        words = value.split()

        if len(words) < 2 or len(words) > 5:
            return False

        for word in words:
            if not re.fullmatch(
                r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'’\-]*",
                word
            ):
                return False

        return True

    @classmethod
    def is_name_anchor(cls, anchor):

        name = clean_text(
            anchor.get_text(" ", strip=True)
        )

        if not cls.is_likely_name(name):
            return False

        href = str(
            anchor.get("href", "")
        ).lower()

        classes = " ".join(
            anchor.get("class", [])
        ).lower()

        parent = anchor.parent
        inside_heading = False

        while parent is not None and getattr(parent, "name", None):

            if parent.name in ("h2", "h3", "h4"):
                inside_heading = True
                break

            if parent.name in ("body", "html"):
                break

            parent = parent.parent

        recognizable_link = any(
            marker in href
            for marker in (
                "roster",
                "player",
                "athlete",
                "bio",
            )
        )

        recognizable_class = (
            "player" in classes
            or "roster" in classes
        )

        return (
            recognizable_link
            or recognizable_class
            or inside_heading
        )

    @staticmethod
    def has_player_details(text):

        text = clean_text(text)

        height = re.search(
            r"\b[4-7]\s*['′’]\s*\d{1,2}\s*[\"″”]?",
            text
        )

        weight = re.search(
            r"\b\d{2,3}\s*(?:lbs?\.?|pounds?)\b",
            text,
            re.IGNORECASE
        )

        class_year = any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in PatternExtractor.CLASS_PATTERNS
        )

        position = PatternExtractor.find_position(text)

        jersey = PatternExtractor.JERSEY_LABEL_PATTERN.search(
            text
        )

        return bool(
            height
            or weight
            or class_year
            or position
            or jersey
        )

    @classmethod
    def find_record_container(cls, anchor):

        name = clean_text(
            anchor.get_text(" ", strip=True)
        )

        for parent in anchor.parents:

            if not getattr(parent, "name", None):
                continue

            if parent.name in (
                "body",
                "html",
                "main",
            ):
                break

            text = clean_text(
                parent.get_text(" ", strip=True)
            )

            if len(text) > 600:
                continue

            if len(text) <= len(name) + 3:
                continue

            if name.casefold() not in text.casefold():
                continue

            if not cls.has_player_details(text):
                continue

            name_links = [
                link
                for link in parent.find_all("a")
                if cls.is_name_anchor(link)
            ]

            if len(name_links) == 1:
                return parent

        return None

    @staticmethod
    def find_height(text):

        match = re.search(
            r"\b([4-7])\s*['′’]\s*(\d{1,2})\s*[\"″”]?",
            text
        )

        if not match:
            return ""

        return f"{match.group(1)}'{match.group(2)}\""

    @staticmethod
    def find_weight(text):

        match = re.search(
            r"\b(\d{2,3})\s*(?:lbs?\.?|pounds?)\b",
            text,
            re.IGNORECASE
        )

        if not match:
            return ""

        return f"{match.group(1)} lbs"

    @staticmethod
    def find_class_year(text):

        for pattern in PatternExtractor.CLASS_PATTERNS:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:
                return clean_text(match.group(0))

        return ""

    @classmethod
    def find_position(cls, text):

        text = clean_text(text)

        if not text:
            return ""

        # First look for an explicitly labeled position.
        labeled_match = cls.POSITION_LABEL_PATTERN.search(text)

        if labeled_match:

            labeled_value = clean_text(
                labeled_match.group(1)
            ).upper()

            labeled_value = re.split(
                r"[,;|]",
                labeled_value
            )[0].strip()

            if labeled_value:
                return labeled_value

        text_upper = text.upper()

        # Match multi-character position labels using word
        # boundaries so that "DE" does not match inside a word.
        for label, position in cls.POSITION_PATTERNS:

            if len(label) < 2:
                continue

            pattern = (
                r"(?<![A-Z])"
                + re.escape(label)
                + r"(?![A-Z])"
            )

            if re.search(pattern, text_upper):
                return position

        # Single-letter positions are only accepted when the
        # entire value is a single position or a clearly labeled
        # position. This avoids matching random letters in text.
        single_letter_positions = {
            "C": "C",
            "S": "S",
            "K": "K",
            "P": "P",
        }

        if text_upper in single_letter_positions:
            return single_letter_positions[text_upper]

        return ""

    @staticmethod
    def extract_number_from_value(value):

        value = clean_text(value)

        if not value:
            return ""

        patterns = [
            r"^\s*#\s*(\d{1,2})\s*$",
            r"^\s*(\d{1,2})\s*$",
            r"\b(?:jersey|uniform|player)\s*"
            r"(?:number|no\.?|#)\s*[:#\-]?\s*(\d{1,2})\b",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                value,
                re.IGNORECASE
            )

            if match:
                return match.group(1)

        return ""

    @classmethod
    def find_jersey_number(cls, record, name):

        # 1. Search the complete record text for an explicit label.
        record_text = clean_text(
            record.get_text(" ", strip=True)
        )

        labeled_match = cls.JERSEY_LABEL_PATTERN.search(
            record_text
        )

        if labeled_match:
            return labeled_match.group(1)

        # 2. Inspect HTML elements and their attributes.
        # This catches accessible labels and data attributes.
        for element in record.find_all(True):

            attributes = []

            for key, value in element.attrs.items():

                if isinstance(value, list):
                    value = " ".join(
                        str(item) for item in value
                    )

                attributes.append(
                    f"{key} {value}"
                )

            attribute_text = " ".join(attributes)

            if not re.search(
                r"jersey|uniform|player.?number|"
                r"roster.?number|(^|[\s_-])number([\s_-]|$)",
                attribute_text,
                re.IGNORECASE
            ):
                continue

            # Check the attributes themselves first.
            number = cls.extract_number_from_value(
                attribute_text
            )

            if number:
                return number

            # Then check the element's visible text.
            number = cls.extract_number_from_value(
                element.get_text(" ", strip=True)
            )

            if number:
                return number

        # 3. Check common explicit labels in definition lists.
        for label in record.find_all(
            ["dt", "th", "label", "span", "div"]
        ):

            label_text = clean_text(
                label.get_text(" ", strip=True)
            )

            if not re.fullmatch(
                r"(?:jersey|uniform|player)?\s*"
                r"(?:number|no\.?|#)",
                label_text,
                re.IGNORECASE
            ):
                continue

            value_element = (
                label.find_next_sibling()
                or label.find_next()
            )

            if value_element:
                number = cls.extract_number_from_value(
                    value_element.get_text(" ", strip=True)
                )

                if number:
                    return number

        # 4. Preserve the original nearby-number fallback.
        strings = [
            clean_text(value)
            for value in record.find_all(string=True)
        ]

        name_index = None

        for index, value in enumerate(strings):

            if name.casefold() in value.casefold():
                name_index = index
                break

        if name_index is not None:

            for value in reversed(
                strings[max(0, name_index - 4):name_index]
            ):

                match = re.fullmatch(
                    r"#?\s*(\d{1,2})",
                    value
                )

                if match:
                    return match.group(1)

        return ""

    @staticmethod
    def find_labeled_fields(record):

        player = empty_player()

        # Reuse the existing card-field reader.
        for field, keywords in CardExtractor.FIELD_KEYWORDS.items():

            try:

                value = CardExtractor.find_field(
                    record,
                    keywords
                )

                if value:
                    player[field] = value

            except Exception:
                continue

        # Read definition-list fields.
        for dt in record.find_all("dt"):

            label = clean_text(
                dt.get_text(" ", strip=True)
            )

            dd = dt.find_next_sibling("dd")

            if not dd:
                continue

            normalized = normalize_header(label)

            for field, aliases in HEADER_ALIASES.items():

                if normalized in aliases:
                    player[field] = clean_text(
                        dd.get_text(" ", strip=True)
                    )

        # Read explicitly labeled fields using common HTML
        # attributes such as data-label, aria-label and title.
        for element in record.find_all(True):

            label_parts = []

            for attribute in (
                "data-label",
                "aria-label",
                "title",
                "data-field",
                "data-stat",
            ):

                value = element.get(attribute)

                if value:
                    label_parts.append(
                        clean_text(value)
                    )

            label = " ".join(label_parts)

            if not label:
                continue

            normalized = normalize_header(label)

            for field, aliases in HEADER_ALIASES.items():

                if normalized in aliases:

                    value = clean_text(
                        element.get_text(" ", strip=True)
                    )

                    if value:
                        player[field] = value

        return player

    @classmethod
    def extract_player(cls, anchor, record):

        name = clean_text(
            anchor.get_text(" ", strip=True)
        )

        text = clean_text(
            record.get_text(" ", strip=True)
        )

        player = cls.find_labeled_fields(record)

        player["name"] = name

        if not player.get("jersey_number"):
            player["jersey_number"] = (
                cls.find_jersey_number(record, name)
            )

        if not player.get("height"):
            player["height"] = cls.find_height(text)

        if not player.get("weight"):
            player["weight"] = cls.find_weight(text)

        if not player.get("class_year"):
            player["class_year"] = cls.find_class_year(text)

        if not player.get("position"):
            player["position"] = cls.find_position(text)

        profile_url = clean_text(
            anchor.get("href", "")
        )

        # Preserve original information even when a field
        # cannot confidently be identified.
        player["raw_fields"] = {
            "Roster Details": text,
            "Profile URL": profile_url,
        }

        player["custom_fields"] = {
            "Roster Details": text,
        }

        player["source_headers"] = [
            "Roster Details",
            "Profile URL",
        ]

        player["raw_source_row"] = [
            text,
            profile_url,
        ]

        complete_player(player)

        return player

    @classmethod
    def extract(cls, soup):

        anchors = [
            anchor
            for anchor in soup.find_all("a", href=True)
            if cls.is_name_anchor(anchor)
        ]

        players = []
        seen = set()

        for anchor in anchors:

            name = clean_text(
                anchor.get_text(" ", strip=True)
            )

            record = cls.find_record_container(anchor)

            if record is None:
                continue

            player = cls.extract_player(
                anchor,
                record
            )

            if not player["name"]:
                continue

            identity = (
                player["name"].casefold(),
                player.get("jersey_number", ""),
                player.get("position", ""),
            )

            if identity in seen:
                continue

            seen.add(identity)
            players.append(player)

        return TableExtractor.remove_duplicates(players)






# ============================================================
# NORMALIZATION AND VALIDATION
# ============================================================

class PlayerValidator:

    @staticmethod
    def validate(players):
        seen = set()

        for player in players:
            complete_player(player)

            warnings = []

            name = clean_text(
                player.get("name", "")
            ).casefold()

            number = clean_text(
                player.get("jersey_number", "")
            ).casefold()

            position = clean_text(
                player.get("position", "")
            ).casefold()

            if not name:
                warnings.append("Missing player name")

            # Only flag a duplicate when there is identifying
            # information beyond the player's name.
            if name and (number or position):
                key = (
                    name,
                    number,
                    position,
                    clean_text(player.get("height", "")),
                    clean_text(player.get("weight", "")),
                )

                if key in seen:
                    warnings.append(
                        "Possible duplicate player record"
                    )

                seen.add(key)

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
    def build_url_variants(url):

        variants = [url]

        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        current_view = query.get("view", [""])[0].lower()

        # Many athletics websites support multiple roster views.
        # Try the table version as a fallback without requiring
        # a school-specific rule.
        if current_view != "table":

            query["view"] = ["table"]

            table_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True),
                parsed.fragment,
            ))

            if table_url not in variants:
                variants.append(table_url)

        return variants

    @staticmethod
    def score_candidate(candidate):

        players = candidate.get("players", [])

        if not players:
            return 0

        populated = 0

        for player in players:

            populated += sum(
                bool(clean_text(player.get(field, "")))
                for field in PLAYER_FIELDS
            )

            populated += len(
                player.get("custom_fields", {})
            )

        average = populated / len(players)

        method_bonus = {
            "HTML Table": 5,
            "Roster Cards": 3,
            "Structured JSON-LD": 0,
            "Pattern-Based Roster": 2,
        }.get(candidate.get("method"), 0)

        return (
            len(players) * 100
            + average * 10
            + method_bonus
        )

    @staticmethod
    def collect_candidates(soup):

        candidates = []

        strategies = [
            (
                "HTML Table",
                TableExtractor.extract_candidates,
            ),
            (
                "Roster Cards",
                CardExtractor.extract,
            ),
            (
                "Structured JSON-LD",
                StructuredDataExtractor.extract,
            ),
            (
                "Pattern-Based Roster",
                PatternExtractor.extract,
            ),
        ]

        for method, extractor in strategies:

            try:

                result = extractor(soup)

                # TableExtractor already returns candidate dictionaries.
                if method == "HTML Table":

                    candidates.extend(result)
                    continue

                if result:

                    candidates.append({
                        "method": method,
                        "players": result,
                    })

            except Exception:
                # One strategy failing must not prevent the
                # remaining strategies from being evaluated.
                continue

        for candidate in candidates:

            candidate["players"] = (
                TableExtractor.remove_duplicates(
                    candidate["players"]
                )
            )

            candidate["score"] = (
                RosterEngine.score_candidate(candidate)
            )

        return candidates

    @staticmethod
    def extract(url, school="", season=""):

        original_url = url.strip()

        if not original_url.startswith(
            ("http://", "https://")
        ):
            original_url = "https://" + original_url

        page_results = []
        errors = []

        # Retrieve all available URL variants.
        for candidate_url in RosterEngine.build_url_variants(
            original_url
        ):

            try:

                soup, final_url, retrieval_method = (
                    WebsiteRetriever.retrieve(
                        candidate_url,
                        use_browser=False
                    )
                )

                page_results.append({
                    "soup": soup,
                    "final_url": final_url,
                    "retrieval_method": retrieval_method,
                })

            except Exception as error:

                errors.append(
                    f"{candidate_url}: {error}"
                )

        best_candidate = None
        best_page = None

        # Evaluate every extraction strategy on every retrieved page.
        for page in page_results:

            candidates = RosterEngine.collect_candidates(
                page["soup"]
            )

            for candidate in candidates:

                if (
                    best_candidate is None
                    or candidate["score"] > best_candidate["score"]
                ):

                    best_candidate = candidate
                    best_page = page

        # Browser fallback if ordinary retrieval could not
        # identify any roster records.
        if best_candidate is None:

            for candidate_url in RosterEngine.build_url_variants(
                original_url
            ):

                try:

                    soup, final_url, retrieval_method = (
                        WebsiteRetriever.retrieve_browser(
                            candidate_url
                        )
                    )

                    page = {
                        "soup": soup,
                        "final_url": final_url,
                        "retrieval_method": retrieval_method,
                    }

                    candidates = RosterEngine.collect_candidates(
                        soup
                    )

                    if candidates:

                        candidate = max(
                            candidates,
                            key=lambda item: item["score"]
                        )

                        if (
                            best_candidate is None
                            or candidate["score"] > best_candidate["score"]
                        ):

                            best_candidate = candidate
                            best_page = page

                except Exception as error:

                    errors.append(
                        f"Browser fallback ({candidate_url}): {error}"
                    )

        if best_candidate is None:

            message = (
                "No recognizable roster structure was found. "
                "All available extraction strategies were attempted."
            )

            if errors:
                message += "\n\n" + "\n".join(errors)

            raise RuntimeError(message)

        soup = best_page["soup"]
        final_url = best_page["final_url"]

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

        players = TableExtractor.remove_duplicates(
            best_candidate["players"]
        )

        for player in players:

            complete_player(player)

            player["school"] = detected_school
            player["season"] = detected_season

            player["source_url"] = original_url
            player["retrieved_url"] = final_url

            player["source_title"] = title

            player["retrieval_method"] = (
                best_page["retrieval_method"]
            )

            player["extraction_method"] = (
                best_candidate["method"]
            )

            player.setdefault("raw_fields", {})
            player.setdefault("custom_fields", {})
            player.setdefault("source_headers", [])
            player.setdefault("raw_source_row", [])

        return PlayerValidator.validate(players)

    


# ============================================================
# LOCAL DATABASE
# ============================================================

class RosterDatabase:

    JSON_FIELDS = {
        "warnings",
        "raw_fields",
        "custom_fields",
        "source_headers",
        "raw_source_row",
    }

    def __init__(self):
        self.connection = sqlite3.connect(DATABASE_PATH)
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

        # Add new columns without deleting or rebuilding old records.
        existing_columns = {
            row["name"]
            for row in cursor.execute(
                "PRAGMA table_info(players)"
            ).fetchall()
        }

        new_columns = {
            "retrieved_url": "TEXT",
            "retrieval_method": "TEXT",
            "raw_fields": "TEXT",
            "custom_fields": "TEXT",
            "source_headers": "TEXT",
            "raw_source_row": "TEXT",
        }

        for column, column_type in new_columns.items():
            if column not in existing_columns:
                cursor.execute(
                    f"ALTER TABLE players "
                    f"ADD COLUMN {column} {column_type}"
                )

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
                    warnings,
                    retrieved_url,
                    retrieval_method,
                    raw_fields,
                    custom_fields,
                    source_headers,
                    raw_source_row
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
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
                json.dumps(player.get("warnings", []), ensure_ascii=False),
                player.get("retrieved_url", ""),
                player.get("retrieval_method", ""),
                json.dumps(player.get("raw_fields", {}), ensure_ascii=False),
                json.dumps(player.get("custom_fields", {}), ensure_ascii=False),
                json.dumps(player.get("source_headers", []), ensure_ascii=False),
                json.dumps(player.get("raw_source_row", []), ensure_ascii=False),
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
        fields = list(DISPLAY_FIELDS)

        custom_names = []
        raw_names = []

        for player in players:
            for name in (player.get("custom_fields") or {}):
                if name not in custom_names:
                    custom_names.append(name)

            for name in (player.get("raw_fields") or {}):
                if name not in raw_names:
                    raw_names.append(name)

        for name in custom_names:
            if name not in fields:
                fields.append(name)

        for name in raw_names:
            source_name = f"Source: {name}"

            if source_name not in fields:
                fields.append(source_name)

        for name in (
            "retrieved_url",
            "retrieval_method",
            "extraction_method",
        ):
            if name not in fields:
                fields.append(name)

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

                for name, value in (
                    player.get("custom_fields") or {}
                ).items():
                    row[name] = value

                for name, value in (
                    player.get("raw_fields") or {}
                ).items():
                    row[f"Source: {name}"] = value

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
        self.result_fields = list(DISPLAY_FIELDS)
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
        self.results_table.setColumnCount(len(DISPLAY_FIELDS))
        self.results_table.setHorizontalHeaderLabels(DISPLAY_FIELDS)

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

        self.save_button = QPushButton("Save to Local Library")
        self.save_button.clicked.connect(self.save_results)

        self.json_button = QPushButton("Export JSON")
        self.json_button.clicked.connect(self.export_json)

        self.csv_button = QPushButton("Export CSV")
        self.csv_button.clicked.connect(self.export_csv)

        self.clear_button = QPushButton("Clear Results")
        self.clear_button.clicked.connect(self.clear_results)

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

        layout.addWidget(
            QLabel("School / Team Name (optional)")
        )

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

        self.single_button = QPushButton("Extract Roster")
        self.single_button.clicked.connect(self.start_single)

        layout.addWidget(self.single_button)

    # --------------------------------------------------------
    # BATCH EXTRACTION
    # --------------------------------------------------------

    def build_batch_tab(self):
        layout = QVBoxLayout(self.batch_tab)

        layout.addWidget(
            QLabel("Enter one roster URL per line.")
        )

        self.batch_urls = QTextEdit()

        self.batch_urls.setPlaceholderText(
            "https://school1.edu/sports/football/roster\n"
            "https://school2.edu/sports/fb/roster\n"
            "https://school3.edu/football/roster"
        )

        layout.addWidget(self.batch_urls)

        self.batch_button = QPushButton("Process All Rosters")
        self.batch_button.clicked.connect(self.start_batch)

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

        refresh_button = QPushButton("Refresh Library")
        refresh_button.clicked.connect(self.refresh_library)

        load_button = QPushButton("Load Selected Roster")
        load_button.clicked.connect(self.load_selected_roster)

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
        self.result_fields = list(DISPLAY_FIELDS)

        self.results_table.clear()
        self.results_table.setRowCount(0)
        self.results_table.setColumnCount(len(DISPLAY_FIELDS))
        self.results_table.setHorizontalHeaderLabels(DISPLAY_FIELDS)

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(tasks))
        self.progress_bar.setValue(0)

        self.status_label.setText("Starting extraction...")

        self.set_actions_enabled(False)

        self.single_button.setDisabled(True)
        self.batch_button.setDisabled(True)

        self.worker = ExtractionWorker(tasks)

        self.worker.progress.connect(self.on_progress)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)

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

        self.set_actions_enabled(bool(players))

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

        fields = list(DISPLAY_FIELDS)
        custom_fields = []

        for player in players:
            for field_name in (
                player.get("custom_fields") or {}
            ):
                if field_name not in custom_fields:
                    custom_fields.append(field_name)

        self.result_fields = fields + custom_fields

        self.results_table.clear()
        self.results_table.setColumnCount(
            len(self.result_fields)
        )

        self.results_table.setHorizontalHeaderLabels(
            self.result_fields
        )

        self.results_table.setRowCount(len(players))

        for row, player in enumerate(players):
            for column, field in enumerate(self.result_fields):

                if field in DISPLAY_FIELDS:
                    value = player.get(field, "")
                else:
                    value = (
                        player.get("custom_fields") or {}
                    ).get(field, "")

                if isinstance(value, list):
                    value = "; ".join(
                        str(item) for item in value
                    )

                self.results_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(str(value or ""))
                )

        self.results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        self.results_table.setAlternatingRowColors(True)

        # Keep visual row order aligned with current_players.
        self.results_table.setSortingEnabled(False)

    def read_results(self):
        records = []

        fields = self.result_fields

        for row in range(self.results_table.rowCount()):

            if row < len(self.current_players):
                player = dict(self.current_players[row])
            else:
                player = {}

            custom_fields = dict(
                player.get("custom_fields") or {}
            )

            for column, field in enumerate(fields):
                item = self.results_table.item(row, column)

                value = item.text() if item else ""

                if field in DISPLAY_FIELDS:
                    if field == "warnings":
                        value = [
                            warning.strip()
                            for warning in value.split(";")
                            if warning.strip()
                        ]

                    player[field] = value
                else:
                    custom_fields[field] = value

            player["custom_fields"] = custom_fields

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
                RosterExporter.export_json(records, path)

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
                RosterExporter.export_csv(records, path)

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

        self.library_table.setRowCount(len(rosters))

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

        if not item:
            return

        roster_id = int(item.text())

        database_players = self.database.get_players(
            roster_id
        )

        players = []

        for record in database_players:
            player = dict(record)

            player.pop("id", None)
            player.pop("roster_id", None)

            for field in RosterDatabase.JSON_FIELDS:
                raw_value = player.get(field)

                try:
                    if raw_value:
                        player[field] = json.loads(raw_value)
                    elif field in ("raw_fields", "custom_fields"):
                        player[field] = {}
                    else:
                        player[field] = []

                except (json.JSONDecodeError, TypeError):
                    if field in ("raw_fields", "custom_fields"):
                        player[field] = {}
                    else:
                        player[field] = []

            players.append(player)

        self.current_players = players

        self.display_players(players)

        self.tabs.setCurrentIndex(0)

        self.status_label.setText(
            f"Loaded {len(players)} saved player records."
        )

        self.set_actions_enabled(bool(players))

    # --------------------------------------------------------
    # GENERAL INTERFACE
    # --------------------------------------------------------

    def set_actions_enabled(self, enabled):
        self.save_button.setEnabled(enabled)
        self.json_button.setEnabled(enabled)
        self.csv_button.setEnabled(enabled)

    def clear_results(self):
        self.current_players = []
        self.result_fields = list(DISPLAY_FIELDS)

        self.results_table.clear()
        self.results_table.setRowCount(0)
        self.results_table.setColumnCount(len(DISPLAY_FIELDS))
        self.results_table.setHorizontalHeaderLabels(DISPLAY_FIELDS)

        self.status_label.setText("Results cleared.")

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
