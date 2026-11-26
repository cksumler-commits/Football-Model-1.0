
from dataclasses import field, fields

from PySide6.QtGui import QGuiApplication
import re
from html.parser import HTMLParser


def read_clipboard_content():
    """
    Retrieve clipboard content in both HTML and plain-text formats.

    Returns:
        dict: Clipboard content and available formats.
    """

    app = QGuiApplication.instance()

    if app is None:
        raise RuntimeError(
            "A Qt application must be running before "
            "reading clipboard content."
        )

    clipboard = app.clipboard()
    mime_data = clipboard.mimeData()

    html_content = None
    text_content = None

    if mime_data.hasHtml():
        html = mime_data.html()

        if html and html.strip():
            html_content = html

    if mime_data.hasText():
        text = mime_data.text()

        if text and text.strip():
            text_content = text

    if html_content is None and text_content is None:
        raise ValueError(
            "The clipboard does not contain readable text."
        )

    return {
        "html": html_content,
        "text": text_content,
        "available_formats": mime_data.formats(),
    }




class ClipboardHTMLParser(HTMLParser):
    """
    Extract readable text, links, and images from clipboard HTML.
    Uses Python's built-in HTML parser.
    """

    BLOCK_ELEMENTS = {
        "address", "article", "aside", "blockquote",
        "div", "dl", "dt", "dd", "fieldset",
        "figcaption", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "li", "main", "nav", "ol",
        "p", "section", "ul"
    }

    def __init__(self):
        super().__init__()

        self.text_parts = []
        self.links = []
        self.images = []

        self.skip_depth = 0
        self.link_stack = []
        self.table_rows = []
        self.current_row = None
        self.current_cell = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
            return

        if self.skip_depth:
            return

        if tag == "tr":
            self.current_row = []

        elif tag in {"td", "th"}:
            self.current_cell = []

        if tag in self.BLOCK_ELEMENTS:
            self.text_parts.append("\n")

        elif tag in {"td", "th"}:
            self.text_parts.append("\t")

        elif tag == "br":
            self.text_parts.append("\n")

        elif tag == "span":
            self.text_parts.append(" ")

        if tag == "a":
            link = {
                "url": attributes.get("href"),
                "text": ""
            }

            self.link_stack.append(link)

        elif tag == "img":
            image_url = (
                attributes.get("src")
                or attributes.get("data-src")
            )

            self.images.append({
                "url": image_url,
                "alt": attributes.get("alt"),
                "srcset": attributes.get("srcset")
            })

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            if self.skip_depth:
                self.skip_depth -= 1
            return

        if self.skip_depth:
            return

        if tag == "a" and self.link_stack:
            link = self.link_stack.pop()

            if link["url"]:
                self.links.append(link)

        if tag in {"td", "th"}:
            if self.current_row is not None:
                cell_text = "".join(self.current_cell or [])
                cell_text = re.sub(
                    r"\s+",
                    " ",
                    cell_text
                    ).strip()

                self.current_row.append(cell_text)

            self.current_cell = None

        elif tag == "tr":
            if self.current_row is not None:
                if any(self.current_row):
                    self.table_rows.append(self.current_row)

            self.current_row = None

        if tag in self.BLOCK_ELEMENTS:
            self.text_parts.append("\n")

        elif tag in {"td", "th"}:
            self.text_parts.append("\t")
        elif tag == "span":
            self.text_parts.append(" ")

    def handle_data(self, data):
        if self.skip_depth:
            return

        if not data:
            return

        self.text_parts.append(data)

        if self.current_cell is not None:
            self.current_cell.append(data)

        for link in self.link_stack:
            link["text"] += data

    def get_results(self):
        raw_text = "".join(self.text_parts)

        lines = []

        for line in raw_text.splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()

            if line:
                lines.append(line)

        return {
            "text": "\n".join(lines),
            "links": self.links,
            "images": self.images,
            "table_rows": self.table_rows
        }


def extract_html_content(html_content):
    """
    Extract readable information and metadata from HTML.
    """

    if not html_content:
        return {
            "text": "",
            "links": [],
            "images": [],
            "table_rows": []
        }

    parser = ClipboardHTMLParser()
    parser.feed(html_content)
    parser.close()

    return parser.get_results()


def extract_text_content(text_content):
    """
    Normalize plain-text clipboard content without
    discarding its original information.
    """

    if not text_content:
        return ""

    text_content = text_content.replace("\r\n", "\n")
    text_content = text_content.replace("\r", "\n")

    return text_content.strip()


def extract_clipboard_content(clipboard_data):
    """
    Process both HTML and plain-text clipboard content.

    HTML and plain text are retained separately because
    they may contain different information.
    """

    html_results = extract_html_content(
        clipboard_data.get("html")
    )

    plain_text = extract_text_content(
        clipboard_data.get("text")
    )

    return {
        "html_text": html_results["text"],
        "plain_text": plain_text,
        "links": html_results["links"],
        "images": html_results["images"],
        "html_rows": html_results["table_rows"],
        "available_formats": clipboard_data.get(
            "available_formats", []
        )
    }

def segment_player_blocks(extracted_data):
    """
    Separate copied roster content into individual player blocks.

    Uses common player-profile completion markers when available.
    If no markers exist, preserves the content as one block
    rather than guessing where players begin and end.
    """

    html_text = extracted_data.get("html_text", "")
    plain_text = extracted_data.get("plain_text", "")

    # Prefer HTML-derived text when available.
    if html_text and html_text.strip():
        source_text = html_text
        source = "html"
    elif plain_text and plain_text.strip():
        source_text = plain_text
        source = "plain_text"
    else:
        return []

    # Common profile completion markers found on roster sites.
    completion_pattern = re.compile(
        r"Full Bio(?:\s+for\s+[^\n]+)?",
        re.IGNORECASE
    )

    segments = completion_pattern.split(source_text)

    # Remove common website navigation/action text.
    action_patterns = [
        r"^Expand for more info about .*$",
        r"^Hide/Show Additional Information For .*$",
        r"^Full Bio(?: for .*)?$",
        r"^View Profile$",
    ]

    blocks = []

    for segment in segments:
        lines = segment.splitlines()
        cleaned_lines = []

        for line in lines:
            line = line.strip()

            if not line:
                continue

            is_action = any(
                re.match(pattern, line, re.IGNORECASE)
                for pattern in action_patterns
            )

            if is_action:
                continue

            cleaned_lines.append(line)

        cleaned_text = "\n".join(cleaned_lines).strip()

        if not cleaned_text:
            continue

        blocks.append({
            "index": len(blocks) + 1,
            "text": cleaned_text,
            "source": source
        })

    return blocks


def detect_table_header(rows):
    """
    Identify whether a table contains a recognizable header row.

    Returns:
        {
            "header_index": int or None,
            "headers": list or None,
            "has_header": bool
        }
    """

    header_aliases = {
        "name",
        "player",
        "full name",
        "position",
        "pos",
        "pos.",
        "height",
        "ht",
        "ht.",
        "weight",
        "wt",
        "wt.",
        "year",
        "class",
        "academic year",
        "hometown",
        "home town",
        "high school",
        "school",
        "previous school",
        "jersey",
        "jersey number",
        "number",
        "#",
    }

    for index, row in enumerate(rows):
        normalized_cells = [
            re.sub(r"[^\w#]", "", cell.lower())
            for cell in row
        ]

        recognized_headers = sum(
            1
            for cell in normalized_cells
            if cell in {
                re.sub(r"[^\w#]", "", alias.lower())
                for alias in header_aliases
            }
        )

        # Require multiple recognizable header labels.
        if recognized_headers >= 2:
            return {
                "header_index": index,
                "headers": row,
                "has_header": True,
            }

    return {
        "header_index": None,
        "headers": None,
        "has_header": False,
    }


def map_table_headers(headers):
    """
    Convert website column headers into standardized field names.

    Unknown headers are preserved as custom fields.
    """
    if not headers:
        return {}

    aliases = {
        "jersey_number": [
            "#",
            "number",
            "no",
            "no.",
            "jersey",
            "jersey number",
            "uniform number",
        ],

        "full_name": [
            "name",
            "player",
            "full name",
            "player name",
        ],

        "position": [
            "pos",
            "pos.",
            "position",
        ],

        "height": [
            "height",
            "ht",
            "ht.",
        ],

        "weight": [
            "weight",
            "wt",
            "wt.",
        ],

        "classification": [
            "year",
            "yr",
            "yr.",
            "class",
            "academic year",
            "classification",
            "cl",
            "cl.",


        ],

        "hometown": [
            "hometown",
            "home town",
            "home",
            "city",
        ],

        "high_school": [
            "high school",
            "hs",
            "prep school",
        ],

        "previous_school": [
            "previous school",
            "last school",
            "college",
            "transfer school",
        ],

        "major": [
            "major",
            "academic major",
        ],
    }

    # Normalize aliases for easier comparisons.
    normalized_aliases = {}

    for field_name, field_aliases in aliases.items():
        for alias in field_aliases:
            normalized_alias = re.sub(
                r"[^\w]",
                "",
                alias.lower()
            )

            normalized_aliases[normalized_alias] = field_name

    column_mapping = {}

    for index, header in enumerate(headers):

        normalized_header = re.sub(
            r"[^\w]",
            "",
            header.lower()
        )

        field_name = normalized_aliases.get(
            normalized_header
        )

        if field_name:
            column_mapping[index] = field_name

        else:
            # Preserve headers we don't recognize.
            column_mapping[index] = {
                "custom_field": header.strip()
            }

    return column_mapping



def parse_table_records(rows, header_result, column_mapping):
    """
    Convert a table with detected headers into standardized player records.

    Recognized columns map to standard fields.
    Unknown columns are preserved as custom fields.

    Compound headers such as "Hometown / High School" map
    the first cell component to the first field and everything
    after the first slash to the second field.
    """

    if not rows or not header_result.get("has_header"):
        return []

    header_row_index = header_result["header_index"]
    headers = header_result["headers"]

    records = []

    standard_fields = {
        "jersey_number",
        "full_name",
        "position",
        "height",
        "weight",
        "classification",
        "major",
        "hometown",
        "high_school",
        "previous_school",
    }

    # Recognized names used in compound headers.
    header_field_aliases = {
        "hometown": "hometown",
        "home town": "hometown",
        "high school": "high_school",
        "highschool": "high_school",
        "hs": "high_school",
        "previous school": "previous_school",
        "previous college": "previous_school",
        "prev school": "previous_school",
        "college": "previous_school",
        "university": "previous_school",
    }

    def normalize_header_part(value):
        value = str(value).strip().lower()
        value = re.sub(r"[^a-z0-9\s]", "", value)
        value = re.sub(r"\s+", " ", value)
        return value


    def assign_field(record, field_name, value, header, source_row_index):
        if value is None or value == "":
            return

        if record[field_name] is None:
            record[field_name] = value

        elif record[field_name] == value:
            # The same information appeared in another source column.
            # Do not treat identical values as conflicting duplicates.
            return

        else:
            record["duplicate_columns"].append({
                "field": field_name,
                "header": header,
                "value": value,
                "source_row_index": source_row_index,
            })


    for source_row_index, row in enumerate(
        rows[header_row_index + 1:],
        start=header_row_index + 1,
    ):

        # Skip completely empty rows.
        if not any(
            str(cell).strip()
            for cell in row
            if cell is not None
        ):
            continue

        record = {
            field: None
            for field in standard_fields
        }

        record["custom_fields"] = {}
        record["duplicate_columns"] = []
        record["raw_row"] = row
        record["source_row_index"] = source_row_index

        # Determine whether the data contains two columns
        # missing from the header: jersey number and name.
        column_offset = 0

        if len(row) == len(headers) + 2:

            first_cell = str(row[0]).strip()
            second_cell = str(row[1]).strip()

            if (
                re.fullmatch(r"\d{1,2}", first_cell)
                and second_cell
                and not re.fullmatch(r"\d{1,2}", second_cell)
            ):
                column_offset = 2

                record["jersey_number"] = first_cell
                record["full_name"] = second_cell

        # Process source columns using the header mapping.
        for index, value in enumerate(row):

            value = value.strip() if isinstance(value, str) else value

            if value == "":
                value = None

            mapped_index = index - column_offset

            if mapped_index < 0:
                continue

            if mapped_index not in column_mapping:
                continue

            mapping = column_mapping[mapped_index]

            source_header = (
                headers[mapped_index]
                if mapped_index < len(headers)
                else str(mapped_index)
            )

            # Check whether an unmapped/custom column actually
            # has a recognized compound header.
            if isinstance(mapping, dict):

                header_parts = [
                    part.strip()
                    for part in str(source_header).split("/")
                ]

                normalized_parts = [
                    normalize_header_part(part)
                    for part in header_parts
                ]

                # Only interpret headers containing exactly two
                # recognized standard-field names.
                if len(normalized_parts) == 2:

                    first_field = header_field_aliases.get(
                        normalized_parts[0]
                    )

                    second_field = header_field_aliases.get(
                        normalized_parts[1]
                    )

                    if (
                        first_field in standard_fields
                        and second_field in standard_fields
                        and first_field != second_field
                    ):

                        # Split the cell ONLY at the first slash.
                        # Any additional slash remains part of
                        # the second field's value.
                        if value is not None and "/" in str(value):

                            first_value, second_value = str(value).split(
                                "/", 1
                            )

                            first_value = first_value.strip() or None
                            second_value = second_value.strip() or None

                            assign_field(
                                record,
                                first_field,
                                first_value,
                                source_header,
                                source_row_index,
                            )

                            assign_field(
                                record,
                                second_field,
                                second_value,
                                source_header,
                                source_row_index,
                            )

                            continue

                # Preserve unrecognized or malformed columns.
                # This also preserves values that cannot safely
                # be separated because they contain no slash.
                custom_field_name = mapping["custom_field"]

                record["custom_fields"][custom_field_name] = value

                continue

            field_name = mapping

            if field_name not in standard_fields:
                continue

            assign_field(
                record,
                field_name,
                value,
                source_header,
                source_row_index,
            )

        records.append(record)

    return records




def parse_headerless_table_records(rows):
    """
    Parse roster tables that do not contain recognizable headers.

    Each cell is evaluated independently using recognizable patterns.
    Column order is not assumed to be fixed.

    Unknown values are preserved as custom fields for review.
    """

    if not rows:
        return []

    standard_fields = {
        "jersey_number",
        "full_name",
        "position",
        "height",
        "weight",
        "classification",
        "hometown",
        "high_school",
        "previous_school",
        "major",
    }

    # Recognized football positions.
    position_values = {
        "QB", "RB", "FB", "HB",
        "WR", "TE",
        "C", "G", "OG", "OT", "OL",
        "DL", "DE", "DT", "NT",
        "EDGE",
        "LB", "MLB", "ILB", "OLB",
        "DB", "CB", "S", "FS", "SS",
        "NICKEL", "NB",
        "K", "PK", "P", "LS", "KR", "PR",
    }

    full_position_names = {
        "QUARTERBACK",
        "RUNNING BACK",
        "FULLBACK",
        "HALFBACK",
        "WIDE RECEIVER",
        "TIGHT END",
        "CENTER",
        "GUARD",
        "OFFENSIVE GUARD",
        "TACKLE",
        "OFFENSIVE TACKLE",
        "OFFENSIVE LINE",
        "DEFENSIVE LINE",
        "DEFENSIVE LINEMAN",
        "DEFENSIVE END",
        "DEFENSIVE TACKLE",
        "NOSE TACKLE",
        "LINEBACKER",
        "MIDDLE LINEBACKER",
        "INSIDE LINEBACKER",
        "OUTSIDE LINEBACKER",
        "DEFENSIVE BACK",
        "CORNERBACK",
        "SAFETY",
        "FREE SAFETY",
        "STRONG SAFETY",
        "NICKEL",
        "KICKER",
        "PLACEKICKER",
        "PUNTER",
        "LONG SNAPPER",
        "KICK RETURNER",
        "PUNT RETURNER",
    }

    classification_pattern = re.compile(
    r"^(?:"
    r"FR|FRESHMAN|"
    r"R[- ]?FR|REDSHIRT\s+FRESHMAN|"
    r"SO|SOPH|SOPHOMORE|"
    r"R[- ]?SO|REDSHIRT\s+SOPHOMORE|"
    r"JR|JUNIOR|"
    r"R[- ]?JR|REDSHIRT\s+JUNIOR|"
    r"SR|SENIOR|"
    r"R[- ]?SR|REDSHIRT\s+SENIOR|"
    r"GR|GRAD|GRADUATE|"
    r"1ST|2ND|3RD|4TH|5TH|6TH|"
    r"FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|"
    r"\d+(?:ST|ND|RD|TH)[- ]YEAR\s+"
    r"(?:FRESHMAN|SOPHOMORE|JUNIOR|SENIOR|GRADUATE)|"
    r"\d+(?:ST|ND|RD|TH)\s+YEAR\s+"
    r"(?:FRESHMAN|SOPHOMORE|JUNIOR|SENIOR|GRADUATE)"
    r")\.?$",
    re.IGNORECASE,
)


    height_pattern = re.compile(
        r"^(?:"
        r"\d{1,2}-\d{1,2}|"
        r"\d{1,2}'\s*\d{1,2}(?:''|\"|')?|"
        r"\d{1,2}\s*ft\s*\d{1,2}\s*(?:in)?"
        r")$",
        re.IGNORECASE,
)

    weight_pattern = re.compile(
        r"^\d{2,3}\s*(?:lbs?|pounds)?$",
        re.IGNORECASE,
    )

    jersey_pattern = re.compile(
        r"^\d{1,2}$"
    )

    def clean_cell(value):
        if value is None:
            return ""

        return str(value).strip()

    def normalize_position(value):
        value = clean_cell(value).upper()

        value = re.sub(
            r"[^A-Z/]",
            "",
            value,
        )

        if value in position_values:
            return True

        # Support combinations such as WR/DB or RB/FB.
        if "/" in value:
            parts = value.split("/")

            if all(
                part in position_values
                for part in parts
            ):
                return True

        return False

    def is_position(value):
        cleaned = clean_cell(value).upper().strip()

        if cleaned in full_position_names:
            return True

        return normalize_position(cleaned)

    def is_classification(value):
        return bool(
            classification_pattern.fullmatch(
                clean_cell(value)
            )
        )

    def is_height(value):
        return bool(
            height_pattern.fullmatch(
                clean_cell(value)
            )
        )

    def is_weight(value):
        return bool(
            weight_pattern.fullmatch(
                clean_cell(value)
            )
        )

    def is_jersey(value):
        return bool(
            jersey_pattern.fullmatch(
                clean_cell(value)
            )
        )

    def is_name_like(value):
        value = clean_cell(value)

        if not value:
            return False

        if is_position(value):
            return False

        if is_classification(value):
            return False

        if is_height(value):
            return False

        if is_weight(value):
            return False

        if is_jersey(value):
            return False

        # Names generally contain at least two words.
        if len(value.split()) < 2:
            return False

        # Names should primarily contain alphabetic characters.
        if not re.search(r"[A-Za-z]", value):
            return False

        return True

    records = []

    for row in rows:

        # Skip entirely empty rows.
        if not any(
            clean_cell(cell)
            for cell in row
        ):
            continue

        values = [
            clean_cell(cell)
            for cell in row
        ]

        record = {
            field: None
            for field in standard_fields
        }

        record["custom_fields"] = {}
        record["duplicate_columns"] = []
        record["raw_row"] = row

        used_indexes = set()

        # --------------------------------------------------
        # Identify jersey number.
        # --------------------------------------------------

        for index, value in enumerate(values):

            if is_jersey(value):

                record["jersey_number"] = value
                used_indexes.add(index)
                break

        # --------------------------------------------------
        # Identify player name.
        # --------------------------------------------------

        name_candidates = []

        for index, value in enumerate(values):

            if index in used_indexes:
                continue

            if is_name_like(value):

                name_candidates.append(
                    (index, value)
                )

        if name_candidates:

            # Prefer the earliest name-like cell.
            name_index, name_value = (
                name_candidates[0]
            )

            record["full_name"] = name_value
            used_indexes.add(name_index)

        # --------------------------------------------------
        # Identify classification.
        # --------------------------------------------------

        for index, value in enumerate(values):

            if index in used_indexes:
                continue

            if is_classification(value):

                record["classification"] = value
                used_indexes.add(index)
                break

        # --------------------------------------------------
        # Identify position.
        # --------------------------------------------------

        for index, value in enumerate(values):

            if index in used_indexes:
                continue

            if is_position(value):

                record["position"] = value
                used_indexes.add(index)
                break

        # --------------------------------------------------
        # Identify height.
        # --------------------------------------------------

        for index, value in enumerate(values):

            if index in used_indexes:
                continue

            if is_height(value):

                record["height"] = value
                used_indexes.add(index)
                break

        # --------------------------------------------------
        # Identify weight.
        # --------------------------------------------------

        for index, value in enumerate(values):

            if index in used_indexes:
                continue

            if is_weight(value):

                # Extract numeric portion.
                weight_match = re.search(
                    r"\d{2,3}",
                    value,
                )

                if weight_match:

                    record["weight"] = (
                        weight_match.group(0)
                    )

                used_indexes.add(index)
                break

        # --------------------------------------------------
        # Preserve remaining values.
        # --------------------------------------------------

        remaining_values = []

        for index, value in enumerate(values):

            if index in used_indexes:
                continue

            if not value:
                continue

            remaining_values.append(value)

        # The first remaining value is a possible
        # hometown/location.
        # Identify location-like values among the remaining cells.
# Combined hometown/high-school values may contain commas
# and slashes, such as:
# "Houston, Texas / Westfield"

        location_candidates = []

        other_candidates = []

        for value in remaining_values:

            if "," in value or "/" in value:

                location_candidates.append(value)

            else:

                other_candidates.append(value)

# Preserve the first location-like value as hometown.
        if location_candidates:

            record["hometown"] = (
                location_candidates.pop(0)
            )

# If another location-like value remains,
# preserve it as an additional custom field.
        for index, value in enumerate(
            location_candidates,
            start=1,
        ):

            record["custom_fields"][
                f"Additional Location {index}"
            ] = value


# Preserve any additional unidentified values.
        for index, value in enumerate(
            other_candidates,
            start=1,
        ):

            record["custom_fields"][
                f"Unmapped Field {index}"
            ] = value
        records.append(record)

    return records



def infer_headerless_column_mapping(
    rows,
    observations=None,
    hypotheses=None
):
    """
    Infer column meanings using semantic patterns, structural
    observations, hypotheses, contextual evidence, and global
    field assignment.

    Does not modify the input rows.

    Required roster fields:
        - jersey_number
        - full_name
        - position

    Optional roster fields:
        - height
        - weight
        - classification
        - transfer_status
        - experience
        - hometown
        - high_school
        - previous_school
        - social_links

    Returns mapping, confidence, scores, reasons, structural
    information, ambiguous columns, custom columns, and
    required-field validation.
    """

    # ---------------------------------------------------------
    # 0. Initialize observations and hypotheses
    # ---------------------------------------------------------

    if observations is None:
        observations = observe_table(rows)

    if hypotheses is None:
        hypotheses = generate_column_hypotheses(
            observations
        )

    fields = [
        "jersey_number",
        "full_name",
        "position",
        "height",
        "weight",
        "classification",
        "transfer_status",
        "experience",
        "hometown",
        "high_school",
        "previous_school",
        "social_links",
    ]

    required_fields = [
        "jersey_number",
        "full_name",
        "position",
    ]

    if not rows:
        return {
            "mapping": {},
            "confidence": {},
            "scores": {},
            "reasons": {},
            "unmapped_columns": [],
            "ambiguous_columns": {},
            "custom_columns": {},
            "column_structure": {},
            "required_field_status": {
                field: {
                    "status": "missing",
                    "column": None,
                }
                for field in required_fields
            },
            "import_readiness": "incomplete",
        }

    # ---------------------------------------------------------
    # 1. Define semantic recognition patterns
    # ---------------------------------------------------------

    jersey_pattern = re.compile(
        r"^\d{1,2}$"
    )

    height_pattern = re.compile(
        r"^\s*\d{1,2}\s*[-'′]\s*\d{1,2}"
        r"\s*(?:[\"″]|''|in)?\s*$"
    )

    weight_pattern = re.compile(
        r"^\s*\d{2,3}\s*"
        r"(?:lbs?|pounds)?\s*$",
        re.IGNORECASE
    )

    classification_pattern = re.compile(
        r"^\s*(?:"
        r"freshman|frosh|fr\.?|"
        r"sophomore|soph\.?|so\.?|"
        r"junior|jr\.?|"
        r"senior|sr\.?|"
        r"graduate|grad\.?|gr\.?|"
        r"fifth\s+year|5th\s+year|"
        r"redshirt\s+(?:freshman|sophomore|junior|senior)|"
        r"r[-\s]?(?:fr|so|jr|sr)\.?|"
        r"(?:rs|r)\s?(?:fr|so|jr|sr)\.?|"
        r"\d+(?:st|nd|rd|th)(?:\s+year)?"
        r")\s*$",
        re.IGNORECASE
    )

    transfer_pattern = re.compile(
        r"^\s*(?:"
        r"tr|transfer|transferred|"
        r"transfer\s+student"
        r")\s*$",
        re.IGNORECASE
    )

    experience_pattern = re.compile(
        r"^\s*(?:"
        r"rs|redshirt|"
        r"\d+\s*l|"
        r"\d+\s*letter|"
        r"walk[\s-]?on|"
        r"scholarship"
        r")\s*$",
        re.IGNORECASE
    )

    # ---------------------------------------------------------
    # 2. Recognize football positions
    # ---------------------------------------------------------

    position_values = {
        "QB", "RB", "FB", "WR", "TE",
        "OL", "OT", "OG", "C", "G",
        "DL", "DE", "DT", "NT", "EDGE",
        "LB", "ILB", "OLB", "MLB",
        "CB", "DB", "S", "FS", "SS",
        "K", "PK", "P", "LS", "KR", "PR",
        "NICKEL",
    }

    full_positions = {
        "quarterback",
        "running back",
        "fullback",
        "wide receiver",
        "tight end",
        "offensive line",
        "offensive lineman",
        "offensive tackle",
        "offensive guard",
        "center",
        "defensive line",
        "defensive lineman",
        "defensive end",
        "defensive tackle",
        "nose tackle",
        "edge",
        "edge rusher",
        "linebacker",
        "inside linebacker",
        "outside linebacker",
        "middle linebacker",
        "cornerback",
        "defensive back",
        "safety",
        "free safety",
        "strong safety",
        "kicker",
        "place kicker",
        "punter",
        "long snapper",
        "nickel",
    }

    # ---------------------------------------------------------
    # 3. Geographic recognition
    # ---------------------------------------------------------

    state_abbreviations = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT",
        "DE", "FL", "GA", "HI", "ID", "IL", "IN",
        "IA", "KS", "KY", "LA", "ME", "MD", "MA",
        "MI", "MN", "MS", "MO", "MT", "NE", "NV",
        "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
        "OK", "OR", "PA", "RI", "SC", "SD", "TN",
        "TX", "UT", "VT", "VA", "WA", "WV", "WI",
        "WY", "DC",
    }

    state_name_aliases = {
        "alabama", "alaska", "arizona", "arkansas",
        "california", "colorado", "connecticut", "delaware",
        "florida", "georgia", "hawaii", "idaho", "illinois",
        "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan",
        "minnesota", "mississippi", "missouri", "montana",
        "nebraska", "nevada", "new hampshire", "new jersey",
        "new mexico", "new york", "north carolina",
        "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina",
        "south dakota", "tennessee", "texas", "utah",
        "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming",
    }

    state_abbreviation_aliases = {
        "ala", "alaska", "ariz", "ark", "calif",
        "colo", "conn", "del", "fla", "ga",
        "id", "ill", "ind", "kan", "kans",
        "ken", "ky", "la", "mass", "mich",
        "minn", "miss", "mo", "mont", "neb",
        "nev", "okla", "ore", "penna", "penn",
        "tenn", "tex", "utah", "va", "wash",
        "wis", "wisc", "wyo",
    }

    state_pattern = re.compile(
        r"\b(?:"
        + "|".join(state_abbreviations)
        + r")\b",
        re.IGNORECASE
    )

    # ---------------------------------------------------------
    # 4. School and social information
    # ---------------------------------------------------------

    high_school_markers = [
        "high school",
        " hs",
        "h.s.",
        "secondary school",
        "prep school",
        "preparatory",
    ]

    school_markers = [
        "university",
        "college",
        "institute",
        "academy",
        "school",
    ]

    social_markers = [
        "instagram",
        "twitter",
        "facebook",
        "linkedin",
        "opendorse",
        "opens in a new window",
        "social media",
        "http://",
        "https://",
        "www.",
    ]

    # ---------------------------------------------------------
    # 5. Normalize and recognize values
    # ---------------------------------------------------------

    def normalize_value(value):

        if value is None:
            return ""

        return re.sub(
            r"\s+",
            " ",
            str(value).strip()
        )

    def is_position(value):

        normalized = value.strip().lower()

        return (
            normalized in full_positions
            or normalized.upper() in position_values
        )

    def is_height(value):
        return bool(height_pattern.fullmatch(value))

    def is_weight(value):
        return bool(weight_pattern.fullmatch(value))

    def is_classification(value):
        return bool(classification_pattern.fullmatch(value))

    def is_transfer_status(value):
        return bool(transfer_pattern.fullmatch(value))

    def is_experience(value):
        return bool(experience_pattern.fullmatch(value))

    def is_social_link(value):

        lower_value = value.lower()

        return any(
            marker in lower_value
            for marker in social_markers
        )

    def is_hometown(value):
        normalized = normalize_value(value).lower()

        if "," not in normalized:
            return False

        # Look at the location portion after the final comma.
        location_suffix = normalized.rsplit(",", 1)[-1].strip()
        location_suffix = location_suffix.rstrip(".")

        if location_suffix in state_name_aliases:
            return True

        if location_suffix in state_abbreviation_aliases:
            return True

        if location_suffix.upper() in state_abbreviations:
            return True

        return False


    def is_school(value):
        lower_value = normalize_value(value).lower()

        if any(
            marker in lower_value
            for marker in school_markers
        ):
            return True

        # Recognize common institution names that don't contain
        # words such as university, college, or school.
        institution_aliases = {
            "ole miss",
            "notre dame",
            "penn state",
            "georgia tech",
            "virginia tech",
            "wake forest",
            "boston college",
            "rice",
            "duke",
            "stanford",
            "syracuse",
            "tulane",
            "vanderbilt",
            "byu",
            "smu",
            "tcu",
            "ucla",
            "usc",
            "lsu",
            "unc",
            "ucf",
            "unlv",
        }

        return lower_value in institution_aliases

    def is_high_school(value):

            lower_value = value.lower()

            return any(
                marker in lower_value
                for marker in high_school_markers
            )


    def is_name_candidate(value):

        value = normalize_value(value)

        if not value:
            return False

        # These structures strongly suggest that the value is
        # something other than an individual player's name.
        if any(separator in value for separator in (
            ",", "/", "|", ";"
        )):
            return False

        if any((
            is_position(value),
            is_height(value),
            is_weight(value),
            is_classification(value),
            is_transfer_status(value),
            is_experience(value),
            is_hometown(value),
            is_social_link(value),
            is_high_school(value),
            is_school(value),
            bool(jersey_pattern.fullmatch(value)),
        )):
            return False

        words = value.split()

        if len(words) < 2 or len(words) > 6:
            return False

        # Player names should contain alphabetic characters.
        if not re.search(r"[A-Za-z]", value):
            return False

        return True
    # ---------------------------------------------------------
    # 6. Extract column profiles
    # ---------------------------------------------------------

    column_count = max(
        (len(row) for row in rows),
        default=0
    )

    row_count = len(rows)

    column_values = {}

    for column_index in range(column_count):

        values = []

        for row in rows:

            if column_index >= len(row):
                continue

            value = normalize_value(
                row[column_index]
            )

            if value:
                values.append(value)

        column_values[column_index] = values

    # ---------------------------------------------------------
    # 7. Extract structural column information
    # ---------------------------------------------------------

    column_structure = {}

    observed_columns = observations.get(
        "columns",
        {}
    )

    if not isinstance(observed_columns, dict):
        observed_columns = {}

    for column_index in range(column_count):

        column_info = observed_columns.get(
            column_index,
            observed_columns.get(
                str(column_index),
                {}
            )
        )

        if not isinstance(column_info, dict):
            column_info = {}

        present_cells = column_info.get(
            "present_cells",
            sum(
                column_index < len(row)
                for row in rows
            )
        )

        absent_cells = column_info.get(
            "absent_cells",
            row_count - present_cells
        )

        empty_cells = column_info.get(
            "empty_cells",
            0
        )

        nonempty_cells = column_info.get(
            "nonempty_cells",
            len(column_values[column_index])
        )

        column_structure[column_index] = {
            "present_cells": present_cells,
            "absent_cells": absent_cells,
            "empty_cells": empty_cells,
            "nonempty_cells": nonempty_cells,

            "record_coverage": round(
                present_cells / row_count,
                3
            ) if row_count else 0.0,

            "population_rate": round(
                nonempty_cells / present_cells,
                3
            ) if present_cells else 0.0,
        }

    # ---------------------------------------------------------
    # 8. Calculate semantic field scores
    # ---------------------------------------------------------

    scores = {}

    for column_index, values in column_values.items():

        total = len(values)

        field_scores = {
            field: 0.0
            for field in fields
        }

        if total == 0:
            scores[column_index] = field_scores
            continue

        # Direct semantic recognition

        field_scores["position"] = (
            sum(is_position(value) for value in values)
            / total
        )

        field_scores["height"] = (
            sum(is_height(value) for value in values)
            / total
        )

        field_scores["classification"] = (
            sum(is_classification(value) for value in values)
            / total
        )

        field_scores["transfer_status"] = (
            sum(is_transfer_status(value) for value in values)
            / total
        )

        field_scores["experience"] = (
            sum(is_experience(value) for value in values)
            / total
        )

        field_scores["hometown"] = (
            sum(is_hometown(value) for value in values)
            / total
        )

        field_scores["high_school"] = (
            sum(is_high_school(value) for value in values)
            / total
        )

        field_scores["social_links"] = (
            sum(is_social_link(value) for value in values)
            / total
        )

        # -----------------------------------------------------
        # Jersey number recognition
        # -----------------------------------------------------

        jersey_matches = sum(
            bool(jersey_pattern.fullmatch(value))
            for value in values
        )

        jersey_score = jersey_matches / total

        if column_index <= 1:
            jersey_score *= 1.15

        field_scores["jersey_number"] = min(
            jersey_score,
            1.0
        )

        # -----------------------------------------------------
        # Player name recognition
        # -----------------------------------------------------

        name_matches = sum(
            is_name_candidate(value)
            for value in values
        )

        name_score = name_matches / total

        if column_index == 0:
            name_score *= 1.20
        elif column_index == 1:
            name_score *= 1.10
        elif column_index >= 4:
            name_score *= 0.80

        field_scores["full_name"] = min(
            name_score,
            1.0
        )

        # -----------------------------------------------------
        # Weight recognition
        # -----------------------------------------------------

        numeric_weights = []

        for value in values:

            match = re.fullmatch(
                r"\s*(\d{2,3})\s*(?:lbs?|pounds)?\s*",
                value,
                re.IGNORECASE
            )

            if match:
                numeric_weights.append(
                    int(match.group(1))
                )

        # A two-digit jersey number should not automatically
        # become a weight. Use plausible weight ranges.

        if numeric_weights:

            plausible_weights = sum(
                130 <= value <= 450
                for value in numeric_weights
            )

            field_scores["weight"] = (
                plausible_weights / total
            )

        # -----------------------------------------------------
        # School context
        # -----------------------------------------------------

        school_matches = sum(
            is_school(value)
            for value in values
        )

        school_score = school_matches / total

        field_scores["previous_school"] = (
            school_score
        )

        field_scores["high_school"] = max(
            field_scores["high_school"],
            school_score * 0.35
        )

        # -----------------------------------------------------
        # Column-position context
        # -----------------------------------------------------

        if column_index == 0:

            field_scores["jersey_number"] = min(
                field_scores["jersey_number"] * 1.15,
                1.0
            )

        if column_index <= 2:

            field_scores["full_name"] = min(
                field_scores["full_name"] * 1.10,
                1.0
            )

        # -----------------------------------------------------
        # Hypothesis evidence
        # -----------------------------------------------------

        column_hypotheses = hypotheses.get(
            column_index,
            []
        )

        hypothesis_field_support = {
            field: 0.0
            for field in fields
        }

        for hypothesis in column_hypotheses:

            possible_fields = hypothesis.get(
                "possible_fields",
                []
            )

            support = hypothesis.get(
                "support",
                0.0
            )

            if not isinstance(support, (int, float)):
                continue

            relevant_fields = [
                field
                for field in possible_fields
                if field in hypothesis_field_support
            ]

            if not relevant_fields:
                continue

            # Generic hypotheses distribute their evidence
            # across all plausible fields.

            shared_support = (
                float(support) / len(relevant_fields)
            )

            for field in relevant_fields:

                hypothesis_field_support[field] = max(
                    hypothesis_field_support[field],
                    shared_support
                )

        # Hypotheses supplement direct recognition.
        # They do not override it.

        for field, support in hypothesis_field_support.items():

            field_scores[field] = min(
                1.0,
                field_scores[field] + (support * 0.25)
            )

        scores[column_index] = field_scores

    # ---------------------------------------------------------
    # 9. Contextual school-field resolution
    # ---------------------------------------------------------

    hometown_columns = [
        column_index
        for column_index, field_scores in scores.items()
        if field_scores["hometown"] >= 0.60
    ]

    for column_index, values in column_values.items():

        if not values:
            continue

        explicit_high_school = (
            sum(
                is_high_school(value)
                for value in values
            ) / len(values)
        )

        explicit_school = (
            sum(
                is_school(value)
                for value in values
            ) / len(values)
        )

        if explicit_high_school >= 0.50:

            scores[column_index]["high_school"] = max(
                scores[column_index]["high_school"],
                explicit_high_school
            )

        if (
            hometown_columns
            and column_index > min(hometown_columns)
            and explicit_school >= 0.30
        ):

            scores[column_index]["high_school"] = max(
                scores[column_index]["high_school"],
                explicit_school * 0.75
            )

            scores[column_index]["previous_school"] = max(
                scores[column_index]["previous_school"],
                explicit_school * 0.75
            )

    # ---------------------------------------------------------
    # 10. Build candidates for global assignment
    # ---------------------------------------------------------

    minimum_score = 0.55
    minimum_score_difference = 0.15

    field_priority = {
        field: index
        for index, field in enumerate(fields)
    }

    column_candidates = {}

    for column_index, field_scores in scores.items():

        candidates_for_column = [
            (field, score)
            for field, score in field_scores.items()
            if score >= minimum_score
        ]

        candidates_for_column.sort(
            key=lambda candidate: (
                -candidate[1],
                field_priority[candidate[0]],
            )
        )

        column_candidates[column_index] = (
            candidates_for_column
        )

    # ---------------------------------------------------------
    # 11. Global field assignment
    # ---------------------------------------------------------

    # Evaluate combinations across the entire roster.
    # A field can only be assigned to one column.
    #
    # The bitmask represents which fields have already
    # been assigned. With 12 supported fields, the maximum
    # number of states is 4096.

    states = {
        0: (0.0, ())
    }

    for column_index in range(column_count):

        candidates_for_column = column_candidates.get(
            column_index,
            []
        )

        next_states = {}

        for used_mask, (total_score, assignments) in states.items():

            # Leaving a column unassigned is always allowed.
            options = [
                (None, 0.0, used_mask)
            ]

            # Consider each available field.
            for field, score in candidates_for_column:

                field_bit = (
                    1 << field_priority[field]
                )

                if used_mask & field_bit:
                    continue

                options.append((
                    field,
                    score,
                    used_mask | field_bit
                ))

            for field, score, new_mask in options:

                new_score = total_score + score

                new_assignments = (
                    assignments + (field,)
                )

                existing = next_states.get(new_mask)

                if existing is None:

                    next_states[new_mask] = (
                        new_score,
                        new_assignments
                    )

                    continue

                existing_score, existing_assignments = existing

                if new_score > existing_score + 0.000001:

                    next_states[new_mask] = (
                        new_score,
                        new_assignments
                    )

                elif abs(
                    new_score - existing_score
                ) <= 0.000001:

                    new_priority = tuple(
                        field_priority[item]
                        if item is not None else 99
                        for item in new_assignments
                    )

                    existing_priority = tuple(
                        field_priority[item]
                        if item is not None else 99
                        for item in existing_assignments
                    )

                    if new_priority < existing_priority:

                        next_states[new_mask] = (
                            new_score,
                            new_assignments
                        )

        states = next_states

    # Select the strongest overall combination.

    best_score, best_assignments = max(
        states.values(),
        key=lambda result: (
            result[0],
            tuple(
                -(
                    field_priority[item]
                    if item is not None else 99
                )
                for item in result[1]
            )
        )
    )

    # ---------------------------------------------------------
    # 12. Record assignments and unresolved columns
    # ---------------------------------------------------------

    mapping = {}
    confidence = {}
    reasons = {}

    ambiguous_columns = {}
    custom_columns = {}

    for column_index, selected_field in enumerate(
        best_assignments
    ):

        candidates_for_column = column_candidates.get(
            column_index,
            []
        )

        if selected_field is not None:

            selected_score = scores[column_index][
                selected_field
            ]

            mapping[column_index] = selected_field

            confidence[column_index] = round(
                selected_score,
                3
            )

            reasons[column_index] = [
                (
                    f"Globally selected '{selected_field}' "
                    f"with a score of {selected_score:.3f}."
                )
            ]

            # Preserve competing interpretations.
            alternatives = [
                {
                    "field": field,
                    "score": round(score, 3),
                }
                for field, score in candidates_for_column
                if (
                    field != selected_field
                    and selected_score - score
                    < minimum_score_difference
                )
            ]

            if alternatives:

                ambiguous_columns[column_index] = {
                    "selected_field": selected_field,
                    "selected_score": round(
                        selected_score,
                        3
                    ),
                    "alternatives": alternatives,
                    "values": column_values[column_index],
                    "reason": (
                        "The global assignment selected a field, "
                        "but competing interpretations have "
                        "similar scores."
                    ),
                }

        else:

            if candidates_for_column:

                ambiguous_columns[column_index] = {
                    "candidates": [
                        {
                            "field": field,
                            "score": round(score, 3),
                        }
                        for field, score in candidates_for_column
                    ],
                    "values": column_values[column_index],
                    "reason": (
                        "This column had plausible field matches, "
                        "but no field could be assigned without "
                        "conflicting with a stronger global match."
                    ),
                }

                reasons[column_index] = [
                    "Requires manual review because of competing assignments."
                ]

            else:

                custom_columns[column_index] = {
                    "suggested_name": (
                        f"custom_column_{column_index + 1}"
                    ),
                    "values": column_values[column_index],
                    "reason": (
                        "No supported core field reached "
                        "the minimum confidence threshold."
                    ),
                }

                reasons[column_index] = [
                    "Preserved as potential custom data."
                ]

    # ---------------------------------------------------------
    # 13. Identify unmapped columns
    # ---------------------------------------------------------

    unmapped_columns = [
        column_index
        for column_index in range(column_count)
        if column_index not in mapping
    ]

    # ---------------------------------------------------------
    # 14. Validate required roster fields
    # ---------------------------------------------------------

    required_field_status = {}

    for field in required_fields:

        assigned_column = next(
            (
                column_index
                for column_index, mapped_field in mapping.items()
                if mapped_field == field
            ),
            None
        )

        if assigned_column is not None:

            is_ambiguous = (
                assigned_column in ambiguous_columns
            )

            required_field_status[field] = {
                "status": (
                    "needs_review"
                    if is_ambiguous
                    else "assigned"
                ),
                "column": assigned_column,
            }

            continue

        # Check whether this required field is a candidate
        # in any unresolved column.

        possible_columns = []

        for column_index, ambiguity in ambiguous_columns.items():

            candidates = ambiguity.get(
                "candidates",
                []
            )

            alternatives = ambiguity.get(
                "alternatives",
                []
            )

            candidate_fields = {
                candidate.get("field")
                for candidate in candidates + alternatives
            }

            if (
                field in candidate_fields
                or ambiguity.get("selected_field") == field
            ):

                possible_columns.append(column_index)

        if possible_columns:

            required_field_status[field] = {
                "status": "needs_review",
                "column": possible_columns[0],
                "possible_columns": possible_columns,
            }

        else:

            required_field_status[field] = {
                "status": "missing",
                "column": None,
            }

    # ---------------------------------------------------------
    # 15. Determine import readiness
    # ---------------------------------------------------------

    required_statuses = [
        item["status"]
        for item in required_field_status.values()
    ]

    if all(
        status == "assigned"
        for status in required_statuses
    ):

        import_readiness = "ready"

    elif any(
        status == "needs_review"
        for status in required_statuses
    ):

        import_readiness = "needs_review"

    else:

        import_readiness = "incomplete"

    # ---------------------------------------------------------
    # 16. Return complete mapping analysis
    # ---------------------------------------------------------

    return {
        "mapping": mapping,
        "confidence": confidence,
        "scores": scores,
        "reasons": reasons,
        "unmapped_columns": unmapped_columns,
        "ambiguous_columns": ambiguous_columns,
        "custom_columns": custom_columns,
        "column_structure": column_structure,
        "required_field_status": required_field_status,
        "import_readiness": import_readiness,
    }



def observe_table(rows):
    """
    Examine a table without assigning semantic meaning to its columns.

    Returns:
        {
            "table": {...},
            "columns": {...},
            "cells": [...]
        }

    This function does not modify rows or perform field mapping.
    """

    import re
    from collections import Counter

    if not rows:
        return {
            "table": {
                "row_count": 0,
                "column_count": 0,
                "row_widths": {},
                "consistent_width": True,
            },
            "columns": {},
            "cells": [],
        }

    # --------------------------------------------------
    # 1. Preserve and normalize the structural input
    # --------------------------------------------------

    raw_rows = [
        list(row) if row is not None else []
        for row in rows
    ]

    row_widths = Counter(len(row) for row in raw_rows)

    record_item_counts = [
        len(row)
        for row in raw_rows
    ]

    maximum_width = max(
        record_item_counts,
        default=0
    )

    maximum_width_record_indices = [
        index
        for index, count in enumerate(record_item_counts)
        if count == maximum_width
    ]

    # --------------------------------------------------
    # 2. Cell-level observation
    # --------------------------------------------------

    def observe_cell(value):

        raw_value = "" if value is None else str(value)
        normalized = raw_value.strip()

        # Basic content characteristics
        is_empty = normalized == ""
        contains_letters = bool(re.search(r"[A-Za-z]", normalized))
        contains_digits = bool(re.search(r"\d", normalized))

        # Identify numeric characteristics without
        # assuming that numbers represent any particular field.
        numeric_tokens = re.findall(
            r"(?<![A-Za-z])\d+(?:\.\d+)?",
            normalized
        )

        # Identify potentially meaningful separators.
        separators = [
            separator
            for separator in ["/", ",", "-", "|", ";", ":"]
            if separator in normalized
        ]

        # Identify possible subdivisions.
        segments = [
            segment.strip()
            for segment in re.split(r"[/|;]", normalized)
            if segment.strip()
        ]

        # Basic structural classification.
        if is_empty:
            value_type = "empty"

        elif normalized.isdigit():
            value_type = "integer"

        elif re.fullmatch(r"\d+\.\d+", normalized):
            value_type = "decimal"

        elif contains_letters and contains_digits:
            value_type = "alphanumeric"

        elif contains_letters:
            value_type = "text"

        else:
            value_type = "other"

        # Character-level observations.
        character_types = []

        if contains_letters:
            character_types.append("letters")

        if contains_digits:
            character_types.append("digits")

        if any(char.isspace() for char in normalized):
            character_types.append("whitespace")

        if separators:
            character_types.append("separators")

        return {
            "raw": raw_value,
            "normalized": normalized,
            "is_empty": is_empty,
            "value_type": value_type,
            "character_types": character_types,
            "length": len(normalized),
            "word_count": len(normalized.split()),
            "contains_letters": contains_letters,
            "contains_digits": contains_digits,
            "numeric_tokens": numeric_tokens,
            "separators": separators,
            "segments": segments,
            "segment_count": len(segments),
        }

    # --------------------------------------------------
    # 3. Observe every cell
    # --------------------------------------------------

    cell_observations = []

    for row_index, row in enumerate(raw_rows):

        observed_row = []

        for column_index, value in enumerate(row):

            observation = observe_cell(value)

            observation["row_index"] = row_index
            observation["column_index"] = column_index

            observed_row.append(observation)

        cell_observations.append(observed_row)

    # --------------------------------------------------
    # 4. Observe each column
    # --------------------------------------------------

    column_observations = {}

    for column_index in range(maximum_width):

        column_cells = [
            row[column_index]
            for row in cell_observations
            if column_index < len(row)
        ]

        values = [
            cell["normalized"]
            for cell in column_cells
            if not cell["is_empty"]
        ]

        value_counts = Counter(values)
        type_counts = Counter(
            cell["value_type"]
            for cell in column_cells
        )

        separator_counts = Counter()

        for cell in column_cells:
            separator_counts.update(cell["separators"])

        lengths = [
            cell["length"]
            for cell in column_cells
            if not cell["is_empty"]
        ]

        word_counts = [
            cell["word_count"]
            for cell in column_cells
            if not cell["is_empty"]
        ]

        numeric_token_counts = [
            len(cell["numeric_tokens"])
            for cell in column_cells
            if not cell["is_empty"]
        ]

        nonempty_count = len(values)
        total_count = len(column_cells)

        absent_count = len(raw_rows) - total_count

        unique_count = len(value_counts)

        unique_ratio = (
            unique_count / nonempty_count
            if nonempty_count
            else 0
        )

        column_observations[column_index] = {
            "column_index": column_index,

            "total_cells": total_count,
            "present_cells": total_count,
                "absent_cells": absent_count,
                "nonempty_cells": nonempty_count,
            "empty_cells": total_count - nonempty_count,

            "unique_values": unique_count,
            "unique_ratio": round(unique_ratio, 4),

            "value_type_counts": dict(type_counts),

            "separator_counts": dict(separator_counts),

            "length_statistics": {
                "minimum": min(lengths) if lengths else 0,
                "maximum": max(lengths) if lengths else 0,
                "average": (
                    round(sum(lengths) / len(lengths), 2)
                    if lengths
                    else 0
                ),
            },

            "word_count_statistics": {
                "minimum": min(word_counts) if word_counts else 0,
                "maximum": max(word_counts) if word_counts else 0,
                "average": (
                    round(sum(word_counts) / len(word_counts), 2)
                    if word_counts
                    else 0
                ),
            },

            "numeric_token_statistics": {
                "minimum": (
                    min(numeric_token_counts)
                    if numeric_token_counts
                    else 0
                ),
                "maximum": (
                    max(numeric_token_counts)
                    if numeric_token_counts
                    else 0
                ),
                "average": (
                    round(
                        sum(numeric_token_counts)
                        / len(numeric_token_counts),
                        2
                    )
                    if numeric_token_counts
                    else 0
                ),
            },

            "most_common_values": [
                {
                    "value": value,
                    "count": count,
                }
                for value, count in value_counts.most_common(10)
            ],

            "sample_values": values[:10],
        }

    # --------------------------------------------------
    # 5. Table-level observations
    # --------------------------------------------------

    total_cells = sum(len(row) for row in raw_rows)


    table_observations = {
    "row_count": len(raw_rows),

    "column_count": maximum_width,

    "maximum_record_width": maximum_width,

    "record_item_counts": record_item_counts,

    "maximum_width_record_indices": (
        maximum_width_record_indices
    ),

    "row_widths": dict(row_widths),

    "consistent_width": len(row_widths) <= 1,

        "minimum_row_width": min(row_widths.keys()),
        "maximum_row_width": maximum_width,

        "total_cells": total_cells,

        "total_empty_cells": sum(
            cell["is_empty"]
            for row in cell_observations
            for cell in row
        ),

        "total_nonempty_cells": sum(
            not cell["is_empty"]
            for row in cell_observations
            for cell in row
        ),
    }

    # --------------------------------------------------
    # 6. Return observations
    # --------------------------------------------------

    return {
        "table": table_observations,
        "columns": column_observations,
        "cells": cell_observations,
        "raw_rows": raw_rows,
    }


def generate_column_hypotheses(observations):
    """
    Generate possible interpretations for observed columns.

    This function proposes interpretations but does not
    select a final field mapping.

    Returns:
        {
            column_index: [
                {
                    "hypothesis": str,
                    "possible_fields": list,
                    "strength": str,
                    "support": float,
                    "evidence": list,
                    "examples": list
                }
            ]
        }
    """

    import re
    from collections import Counter

    columns = observations.get("columns", {})
    cells = observations.get("cells", [])

    hypotheses = {}

    # --------------------------------------------------
    # Helper: evidence strength
    # --------------------------------------------------

    def determine_strength(support):

        if support >= 0.85:
            return "strong"

        if support >= 0.60:
            return "moderate"

        return "weak"

    # --------------------------------------------------
    # Helper: add a hypothesis
    # --------------------------------------------------

    def add_hypothesis(
        results,
        hypothesis,
        possible_fields,
        support,
        evidence,
        examples,
    ):

        if support <= 0:
            return

        results.append({
            "hypothesis": hypothesis,
            "possible_fields": possible_fields,
            "strength": determine_strength(support),
            "support": round(support, 3),
            "evidence": evidence,
            "examples": examples[:5],
        })

    # --------------------------------------------------
    # Helper: geographic patterns
    # --------------------------------------------------

    state_pattern = re.compile(
        r",\s*[A-Z]{2,3}\.?(?:\s|$)",
        re.IGNORECASE
    )

    # --------------------------------------------------
    # Helper: classification patterns
    # --------------------------------------------------

    classification_pattern = re.compile(
        r"\b("
        r"freshman|freshmen|fr|"
        r"sophomore|soph|"
        r"junior|jr|"
        r"senior|sr|"
        r"graduate|grad|"
        r"redshirt|"
        r"first.year|second.year|third.year|fourth.year"
        r")\b",
        re.IGNORECASE
    )

    # --------------------------------------------------
    # Helper: school indicators
    # --------------------------------------------------

    school_pattern = re.compile(
        r"\b("
        r"high school|hs|academy|"
        r"university|college|"
        r"institute|prep|preparatory"
        r")\b",
        re.IGNORECASE
    )

    # --------------------------------------------------
    # Helper: social indicators
    # --------------------------------------------------

    social_pattern = re.compile(
        r"\b("
        r"instagram|twitter|facebook|"
        r"tiktok|youtube|x.com|opendorse"
        r")\b",
        re.IGNORECASE
    )

    # --------------------------------------------------
    # 1. Examine each column
    # --------------------------------------------------

    for column_index, column_info in columns.items():

        column_index = int(column_index)

        observed_values = []

        for row in cells:

            if column_index >= len(row):
                continue

            cell = row[column_index]

            if not cell["is_empty"]:
                observed_values.append(
                    cell["normalized"]
                )

        if not observed_values:
            hypotheses[column_index] = []
            continue

        total = len(observed_values)

        unique_count = len(set(observed_values))

        unique_ratio = unique_count / total

        results = []

        # --------------------------------------------------
        # 2. Numeric observations
        # --------------------------------------------------

        numeric_values = [
            value
            for value in observed_values
            if re.fullmatch(r"\d+", value)
        ]

        numeric_support = (
            len(numeric_values) / total
        )

        if numeric_support >= 0.60:

            numeric_numbers = [
                int(value)
                for value in numeric_values
            ]

            minimum = min(numeric_numbers)
            maximum = max(numeric_numbers)

            add_hypothesis(
                results,
                "numeric_values",
                [],
                numeric_support,
                [
                    "Most values contain only digits",
                    f"Observed numeric range: {minimum} to {maximum}",
                ],
                numeric_values,
            )

            # Possible identifier
            if (
                numeric_support >= 0.85
                and minimum >= 0
                and maximum <= 99
            ):

                add_hypothesis(
                    results,
                    "numeric_identifier",
                    ["jersey_number", "identifier"],
                    numeric_support,
                    [
                        "Values are numeric",
                        "All observed values fall between 0 and 99",
                    ],
                    numeric_values,
                )

            # Possible weight
            if (
                numeric_support >= 0.85
                and minimum >= 100
                and maximum <= 500
            ):

                add_hypothesis(
                    results,
                    "numeric_measurement",
                    ["weight", "other_measurement"],
                    numeric_support,
                    [
                        "Values are numeric",
                        "Values fall within a possible body-weight range",
                    ],
                    numeric_values,
                )

        # --------------------------------------------------
        # 3. Two-part numeric measurements
        # --------------------------------------------------

        pair_pattern = re.compile(
            r"^\s*\d{1,2}\s*[-'′]\s*\d{1,2}"
            r"\s*(?:[\"″]|''|in)?\s*$"
        )

        pair_values = [
            value
            for value in observed_values
            if pair_pattern.fullmatch(value)
        ]

        pair_support = len(pair_values) / total

        if pair_support >= 0.60:

            add_hypothesis(
                results,
                "two_part_measurement",
                ["height", "other_measurement"],
                pair_support,
                [
                    "Values contain two numeric components",
                    "Components use a consistent separator",
                ],
                pair_values,
            )

        # --------------------------------------------------
        # 4. Text characteristics
        # --------------------------------------------------

        text_values = [
            value
            for value in observed_values
            if re.search(r"[A-Za-z]", value)
        ]

        text_support = len(text_values) / total

        if text_support >= 0.60:

            add_hypothesis(
                results,
                "text_values",
                [],
                text_support,
                [
                    "Most values contain alphabetic characters",
                ],
                text_values,
            )

        # --------------------------------------------------
        # 5. Repeated categorical values
        # --------------------------------------------------

        repeated_values = [
            value
            for value, count in Counter(
                observed_values
            ).items()
            if count > 1
        ]

        repeated_support = (
            sum(
                count
                for count in Counter(
                    observed_values
                ).values()
                if count > 1
            )
            / total
        )

        if (
            repeated_support >= 0.60
            and unique_ratio <= 0.70
        ):

            add_hypothesis(
                results,
                "categorical_values",
                ["position", "classification", "category"],
                repeated_support,
                [
                    "Values repeat across multiple rows",
                    "Column contains a relatively limited set of values",
                ],
                repeated_values,
            )

        # --------------------------------------------------
        # 6. Potential name-like values
        # --------------------------------------------------

        name_candidates = [
            value
            for value in text_values
            if (
                2 <= len(value.split()) <= 5
                and not re.search(
                    r"\d",
                    value
                )
                and not re.search(
                    r"[/|]",
                    value
                )
            )
        ]

        name_support = (
            len(name_candidates) / total
        )

        if (
            name_support >= 0.60
            and unique_ratio >= 0.70
        ):

            add_hypothesis(
                results,
                "unique_person_or_entity_names",
                ["full_name", "institution", "other_entity"],
                name_support,
                [
                    "Most values contain multiple words",
                    "Most values are unique within the column",
                    "Values contain alphabetic text",
                ],
                name_candidates,
            )

        # --------------------------------------------------
        # 7. Potential location values
        # --------------------------------------------------

        location_candidates = [
            value
            for value in observed_values
            if state_pattern.search(value)
        ]

        location_support = (
            len(location_candidates) / total
        )

        if location_support >= 0.50:

            add_hypothesis(
                results,
                "geographic_values",
                ["hometown", "location", "other_geography"],
                location_support,
                [
                    "Values contain comma-separated text",
                    "Values contain patterns resembling geographic abbreviations",
                ],
                location_candidates,
            )

        # --------------------------------------------------
        # 8. Potential classification values
        # --------------------------------------------------

        classification_candidates = [
            value
            for value in observed_values
            if classification_pattern.search(value)
        ]

        classification_support = (
            len(classification_candidates) / total
        )

        if classification_support >= 0.50:

            add_hypothesis(
                results,
                "academic_or_experience_classification",
                ["classification", "experience", "other_status"],
                classification_support,
                [
                    "Values contain terms commonly associated with academic years or experience",
                ],
                classification_candidates,
            )

        # --------------------------------------------------
        # 9. Potential school/institution values
        # --------------------------------------------------

        school_candidates = [
            value
            for value in observed_values
            if school_pattern.search(value)
        ]

        school_support = (
            len(school_candidates) / total
        )

        if school_support >= 0.50:

            add_hypothesis(
                results,
                "institution_like_values",
                ["high_school", "previous_school", "institution"],
                school_support,
                [
                    "Values contain institution-related terminology",
                ],
                school_candidates,
            )

        # --------------------------------------------------
        # 10. Compound values
        # --------------------------------------------------

        compound_candidates = [
            value
            for value in observed_values
            if "/" in value or "|" in value or ";" in value
        ]

        compound_support = (
            len(compound_candidates) / total
        )

        if compound_support >= 0.30:

            add_hypothesis(
                results,
                "potential_compound_values",
                ["multiple_fields", "combined_field"],
                compound_support,
                [
                    "Values contain structural separators",
                    "Separators may divide multiple pieces of information",
                ],
                compound_candidates,
            )

        # --------------------------------------------------
        # 11. Potential social links or identifiers
        # --------------------------------------------------

        social_candidates = [
            value
            for value in observed_values
            if social_pattern.search(value)
        ]

        social_support = (
            len(social_candidates) / total
        )

        if social_support >= 0.30:

            add_hypothesis(
                results,
                "social_media_or_external_links",
                ["social_links", "external_links"],
                social_support,
                [
                    "Values contain social media or external platform names",
                ],
                social_candidates,
            )

        # --------------------------------------------------
        # 12. Store hypotheses
        # --------------------------------------------------

        hypotheses[column_index] = results

    return hypotheses




def recognize_core_values(text):
    """
    Recognize potential essential roster fields from arbitrary text.

    This function does not assign values to players.
    It identifies candidates, records evidence, and preserves
    their original positions for later interpretation.
    """

    import re

    if not text:
        return []

    candidates = []

    # --------------------------------------------------
    # Recognition patterns
    # --------------------------------------------------

    patterns = {
        "height": [
            # 6-2, 6'2, 6' 2", 6′2″, 6 ft 2 in
            r"\b\d\s*[-′']\s*\d{1,2}\s*(?:[″\"']|in)?\b",
            r"\b\d\s*ft\.?\s*\d{1,2}\s*(?:in\.?)?\b",
        ],

        "weight": [
            # 198 lbs, 198 lb, 198 pounds
            r"\b\d{2,3}\s*(?:lbs?\.?|pounds?)\b",
        ],

        "classification": [
            r"\b(?:"
            r"freshman|freshmen|frosh|"
            r"sophomore|sophomores|"
            r"junior|juniors|"
            r"senior|seniors|"
            r"graduate|grad|"
            r"redshirt|"
            r"r[-\s]?(?:fr|so|jr|sr)\.?|"
            r"(?:rs|r)\s?(?:fr|so|jr|sr)\.?|"
            r"\d+(?:st|nd|rd|th)"
            r"(?:[- ]year)?"
            r")\b",
        ],
    }

    # --------------------------------------------------
    # Known position terminology
    # --------------------------------------------------

    positions = {
        # Football
        "QB", "RB", "FB", "HB",
        "WR", "TE",
        "OL", "OT", "OG", "OC", "G", "T", "C",
        "DL", "DE", "DT", "NT",
        "LB", "MLB", "ILB", "OLB",
        "DB", "CB", "S", "FS", "SS",
        "K", "P", "LS",
        "EDGE",


    }

    position_names = {
        "quarterback",
        "running back",
        "wide receiver",
        "tight end",
        "offensive lineman",
        "defensive lineman",
        "defensive end",
        "defensive tackle",
        "linebacker",
        "cornerback",
        "safety",
        "kicker",
        "punter",
        "guard",
        "forward",
        "center",
        "pitcher",
        "catcher",
        "infielder",
        "outfielder",
        "goalkeeper",
        "midfielder",
        "defender",
        "striker",
        "setter",
        "libero",
        "middle blocker",
        "outside hitter",
    }

            # ----------------------------------------------
        # Combined / multi-position designations
        # ----------------------------------------------

    position_tokens = positions | {
            name.upper() for name in position_names
        }

    position_parts = [
            part.strip()
            for part in re.split(
                r"\s*[/|;,&+\-]\s*",
                stripped,
            )
            if part.strip()
        ]

    if (
            len(position_parts) > 1
            and all(
                part.upper() in position_tokens
                for part in position_parts
            )
        ):
            add_candidate(
                field="position",
                value=stripped,
                line_index=line_index,
                start=line.find(stripped),
                end=line.find(stripped) + len(stripped),
                confidence="high",
                evidence="Recognized combined position designation",
            )

    # --------------------------------------------------
    # Candidate helper
    # --------------------------------------------------

    def add_candidate(
        field,
        value,
        line_index,
        start,
        end,
        confidence,
        evidence,
    ):
        candidates.append({
            "field": field,
            "value": value.strip(),
            "line_index": line_index,
            "start": start,
            "end": end,
            "confidence": confidence,
            "evidence": evidence,
        })

    # --------------------------------------------------
    # Process text line by line
    # --------------------------------------------------

    lines = text.splitlines()

    for line_index, line in enumerate(lines):

        stripped = line.strip()

        if not stripped:
            continue

        # ----------------------------------------------
        # Height
        # ----------------------------------------------

        for pattern in patterns["height"]:

            for match in re.finditer(
                pattern,
                line,
                re.IGNORECASE,
            ):
                add_candidate(
                    field="height",
                    value=match.group(),
                    line_index=line_index,
                    start=match.start(),
                    end=match.end(),
                    confidence="high",
                    evidence="Recognized height measurement format",
                )

        # ----------------------------------------------
        # Weight
        # ----------------------------------------------

        for pattern in patterns["weight"]:

            for match in re.finditer(
                pattern,
                line,
                re.IGNORECASE,
            ):
                add_candidate(
                    field="weight",
                    value=match.group(),
                    line_index=line_index,
                    start=match.start(),
                    end=match.end(),
                    confidence="high",
                    evidence="Recognized weight unit",
                )

        # ----------------------------------------------
        # Classification
        # ----------------------------------------------

        for pattern in patterns["classification"]:

            for match in re.finditer(
                pattern,
                line,
                re.IGNORECASE,
            ):
                add_candidate(
                    field="classification",
                    value=match.group(),
                    line_index=line_index,
                    start=match.start(),
                    end=match.end(),
                    confidence="probable",
                    evidence="Recognized academic classification terminology",
                )

        # ----------------------------------------------
        # Position abbreviations
        # ----------------------------------------------

        for match in re.finditer(
            r"\b[A-Za-z]{1,4}\b",
            line,
        ):

            value = match.group().upper()

            if value in positions:

                add_candidate(
                    field="position",
                    value=match.group(),
                    line_index=line_index,
                    start=match.start(),
                    end=match.end(),
                    confidence="probable",
                    evidence="Matches recognized position abbreviation",
                )

        # ----------------------------------------------
        # Position names
        # ----------------------------------------------

        for position in position_names:

            for match in re.finditer(
                re.escape(position),
                line,
                re.IGNORECASE,
            ):

                add_candidate(
                    field="position",
                    value=match.group(),
                    line_index=line_index,
                    start=match.start(),
                    end=match.end(),
                    confidence="high",
                    evidence="Matches recognized position terminology",
                )

        # ----------------------------------------------
        # Potential jersey numbers
        # ----------------------------------------------

        # Numbers explicitly associated with a player
        # identifier, such as (0), #12, or No. 12.

        explicit_number_patterns = [
            r"#\s*(\d{1,2})\b",
            r"\(\s*(\d{1,2})\s*\)",
            r"\bNo\.?\s*(\d{1,2})\b",
        ]

        for pattern in explicit_number_patterns:

            for match in re.finditer(
                pattern,
                line,
                re.IGNORECASE,
            ):

                value = match.group(1)

                add_candidate(
                    field="jersey_number",
                    value=value,
                    line_index=line_index,
                    start=match.start(),
                    end=match.end(),
                    confidence="high",
                    evidence="Explicit jersey number formatting",
                )

        # Standalone numeric values are weaker candidates.
        # We do not assume that every number is a jersey.

        if re.fullmatch(r"\d{1,2}", stripped):

            add_candidate(
                field="jersey_number",
                value=stripped,
                line_index=line_index,
                start=line.find(stripped),
                end=line.find(stripped) + len(stripped),
                confidence="possible",
                evidence="Standalone numeric value",
            )

    return candidates






def parse_inferred_headerless_records(rows, analysis):
    """
    Build player records using whole-table column inference.

    Compound cells are decomposed before assignment. Structural
    column relationships help distinguish high schools from
    previous schools when semantic evidence is incomplete.
    """
    mapping = analysis.get("mapping", {})
    ambiguous_columns = analysis.get("ambiguous_columns", {})
    custom_columns = analysis.get("custom_columns", {})

    standard_fields = {
        "jersey_number",
        "full_name",
        "position",
        "height",
        "weight",
        "classification",
        "major",
        "hometown",
        "high_school",
        "previous_school",
        "transfer_status",
        "experience",
        "social_links",
    }

    # Find the inferred high-school column. This becomes a
    # structural reference for later school-like columns.
    high_school_columns = [
        index
        for index, field in mapping.items()
        if field == "high_school"
    ]

    high_school_column = (
        min(high_school_columns)
        if high_school_columns
        else None
    )

    def split_compound_value(value):
        return [
            part.strip()
            for part in re.split(r"[/|;]", str(value))
            if part.strip()
        ]

    def assign_if_empty(record, field, value):
        if field not in standard_fields or not value:
            return False

        existing = record.get(field)

        if existing is None:
            record[field] = value
            return True

        return (
            str(existing).strip().lower()
            == str(value).strip().lower()
        )

    records = []

        # Known position abbreviations and full position names.
    position_tokens = {
        "QB", "RB", "FB", "HB",
        "WR", "TE",
        "OL", "OT", "OG", "OC", "G", "T", "C",
        "DL", "DE", "DT", "NT",
        "LB", "MLB", "ILB", "OLB",
        "DB", "CB", "S", "FS", "SS",
        "K", "P", "LS", "EDGE",
        "PG", "SG", "SF", "PF",
        "SP", "RP", "IF", "OF",
        "2B", "3B", "1B", "LF", "CF", "RF", "DH",
        "GK", "OH", "OPP", "MB", "L",
        "SPRINTER", "DISTANCE", "HURDLES",
        "JUMPER", "THROWER",
        "ATH",
        "QUARTERBACK", "RUNNING BACK",
        "WIDE RECEIVER", "TIGHT END",
        "OFFENSIVE LINEMAN", "DEFENSIVE LINEMAN",
        "DEFENSIVE END", "DEFENSIVE TACKLE",
        "LINEBACKER", "CORNERBACK", "SAFETY",
        "KICKER", "PUNTER",
    }

    def is_position_designation(value):
        parts = [
            part.strip()
            for part in re.split(
                r"\s*[/|;,&+\-]\s*",
                str(value).strip(),
            )
            if part.strip()
        ]

        return (
            len(parts) > 1
            and all(
                part.upper() in position_tokens
                for part in parts
            )
        )

    for row_index, row in enumerate(rows):
        values = [
            str(value).strip() if value is not None else ""
            for value in row
        ]

        if not any(values):
            continue

        record = {
            field: None for field in standard_fields
        }

        record["custom_fields"] = {}
        record["duplicate_columns"] = []
        record["review_warnings"] = []
        record["compound_interpretations"] = []
        record["raw_row"] = row
        record["source_row_index"] = row_index

        for column_index, value in enumerate(values):
            if not value:
                continue

            selected_field = mapping.get(column_index)

            # Position combinations must be protected before
            # compound-cell interpretation.
            if (
                selected_field == "position"
                or is_position_designation(value)
                ):
                if record["position"] is None:
                        record["position"] = value
                else:
                        record["duplicate_columns"].append({
                            "field": "position",
                            "column": column_index,
                            "value": value,
                        })

                if column_index in ambiguous_columns:
                    record["review_warnings"].append({
                            "column": column_index,
                            "selected_field": "position",
                            "details": ambiguous_columns[column_index],
                        })

                continue

            # Handle other compound cells.
            components = split_compound_value(value)

            if len(components) > 1:
                hometown_component = None
                school_components = []
                unresolved_components = []

                for component in components:
                    component_type = _classify_compound_component(
                        component
                    )

                    if component_type == "hometown":
                        if hometown_component is None:
                            hometown_component = component
                        else:
                            unresolved_components.append(component)


                    elif component_type in {
                                "high_school",
                                "previous_school",
                            }:
                            school_components.append(
                                (component, component_type)
                                    )

# Respect an explicit user-selected school destination.
                    elif selected_field in {
                            "high_school",
                                "previous_school",
                            }:
                            school_components.append(
                                (component, selected_field)
                            )

                    elif _looks_like_school_name(component):
                            school_components.append(
                                    (component, None)
                                )


                    else:
                        unresolved_components.append(component)

                if hometown_component:
                    assign_if_empty(
                        record,
                        "hometown",
                        hometown_component,
                    )

                for component, component_type in school_components:
                    target_field = component_type

                    # If the component has no explicit school
                    # classification, use the column's role.
                    if target_field is None:
                        if selected_field in {
                            "high_school",
                            "previous_school",
                        }:
                            target_field = selected_field

                        elif (
                            high_school_column is not None
                            and column_index > high_school_column
                        ):
                            target_field = "previous_school"

                        else:
                            target_field = "high_school"

                    assigned = assign_if_empty(
                        record,
                        target_field,
                        component,
                    )

                    if not assigned:
                        unresolved_components.append(component)

                record["compound_interpretations"].append({
                    "column": column_index,
                    "original_value": value,
                    "hometown": hometown_component,
                    "school_components": [
                        {
                            "value": component,
                            "assigned_field": (
                                component_type
                                or (
                                    selected_field
                                    if selected_field in {
                                        "high_school",
                                        "previous_school",
                                    }
                                    else (
                                        "previous_school"
                                        if high_school_column is not None
                                        and column_index > high_school_column
                                        else "high_school"
                                    )
                                )
                            ),
                        }
                        for component, component_type in school_components
                    ],
                    "unresolved_components": unresolved_components,
                })

                if unresolved_components:
                    record["custom_fields"][
                        f"Unresolved Column {column_index + 1}"
                    ] = " / ".join(unresolved_components)

                    record["review_warnings"].append({
                        "type": "compound_cell",
                        "column": column_index,
                        "original_value": value,
                        "unresolved_components": unresolved_components,
                    })

                if column_index in ambiguous_columns:
                    record["review_warnings"].append({
                        "column": column_index,
                        "selected_field": selected_field,
                        "details": ambiguous_columns[column_index],
                    })

                continue

            if selected_field:
                if selected_field in standard_fields:
                    if record[selected_field] is None:
                        record[selected_field] = value
                    else:
                        record["duplicate_columns"].append({
                            "field": selected_field,
                            "column": column_index,
                            "value": value,
                        })
                else:
                    record["custom_fields"][selected_field] = value

                if column_index in ambiguous_columns:
                    record["review_warnings"].append({
                        "column": column_index,
                        "selected_field": selected_field,
                        "details": ambiguous_columns[column_index],
                    })

                continue

            if column_index in ambiguous_columns:
                custom_name = f"Unresolved Column {column_index + 1}"

                record["custom_fields"][custom_name] = value
                record["review_warnings"].append({
                    "column": column_index,
                    "details": ambiguous_columns[column_index],
                })

            elif column_index in custom_columns:
                custom_name = custom_columns[column_index].get(
                    "suggested_name",
                    f"Custom Column {column_index + 1}",
                )

                record["custom_fields"][custom_name] = value

            else:
                record["custom_fields"][
                    f"Unmapped Column {column_index + 1}"
                ] = value

        if any(record[field] for field in (
            "jersey_number",
            "full_name",
            "position",
        )):
            records.append(record)

    return records





def _classify_compound_component(value):
    """Identify strong clues about an individual compound-cell component."""
    value = str(value).strip()

    if not value:
        return None

    lower = value.lower()

    state_abbreviations = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT",
        "DE", "FL", "GA", "HI", "ID", "IL", "IN",
        "IA", "KS", "KY", "LA", "ME", "MD", "MA",
        "MI", "MN", "MS", "MO", "MT", "NE", "NV",
        "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
        "OK", "OR", "PA", "RI", "SC", "SD", "TN",
        "TX", "UT", "VT", "VA", "WA", "WV", "WI",
        "WY", "DC",
    }

    state_names = {
        "alabama", "alaska", "arizona", "arkansas",
        "california", "colorado", "connecticut", "delaware",
        "florida", "georgia", "hawaii", "idaho", "illinois",
        "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan",
        "minnesota", "mississippi", "missouri", "montana",
        "nebraska", "nevada", "new hampshire", "new jersey",
        "new mexico", "new york", "north carolina",
        "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina",
        "south dakota", "tennessee", "texas", "utah",
        "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming",
    }

    normalized_state_names = {
        re.sub(r"[^a-z]", "", name)
        for name in state_names
    }

    state_aliases = {
        "ALA": "AL", "ARIZ": "AZ", "ARK": "AR",
        "CALIF": "CA", "COLO": "CO", "CONN": "CT",
        "DEL": "DE", "FLA": "FL", "ILL": "IL",
        "IND": "IN", "KAN": "KS", "MASS": "MA",
        "MICH": "MI", "MINN": "MN", "MISS": "MS",
        "MONT": "MT", "NEB": "NE", "NEV": "NV",
        "OKLA": "OK", "ORE": "OR", "TENN": "TN",
        "TEX": "TX", "WASH": "WA", "WVA": "WV",
        "WIS": "WI", "WYO": "WY",
    }

    def is_state(value):
        normalized = re.sub(r"[^A-Za-z]", "", value).upper()
        normalized_name = re.sub(r"[^a-z]", "", value.lower())

        return (
            normalized in state_abbreviations
            or normalized in state_aliases
            or normalized_name in normalized_state_names
        )

    # Recognize locations with comma-separated state suffixes.
    if "," in value:
        suffix = value.rsplit(",", 1)[-1].strip()

        if is_state(suffix):
            return "hometown"

    # Recognize locations with state abbreviations or names
    # separated by spaces, including Washington D.C.
    location_match = re.fullmatch(
        r"(.+?)\s+([A-Za-z. ]+)",
        value,
    )

    if location_match:
        possible_state = location_match.group(2).strip()

        if is_state(possible_state):
            return "hometown"

    # Recognize common standalone geographic abbreviations.
    normalized_location = re.sub(
        r"[^a-z]",
        "",
        lower,
    )

    known_locations = {
        "washingtondc",
        "districtofcolumbia",
    }

    if normalized_location in known_locations:
        return "hometown"

    # Explicit high-school indicators.
    high_school_markers = (
        "high school",
        "secondary school",
        "prep school",
        "preparatory",
    )

    if any(marker in lower for marker in high_school_markers):
        return "high_school"

    if re.search(r"\bschool\b", lower):
        return "high_school"

    return None






def _looks_like_school_name(value):
    """
    Identify a plausible school name by its structure.

    This is a candidate check, not proof that a value
    represents an educational institution.
    """
    value = str(value).strip()

    if not value:
        return False

    # Reject geographic values.
    if _classify_compound_component(value) == "hometown":
        return False

    if "," in value:
        return False

    # Reject URLs and social-media content.
    if re.search(
        r"https?://|www\.|instagram|twitter|facebook|"
        r"opens in a new window",
        value,
        re.IGNORECASE,
    ):
        return False

    # Reject values containing digits.
    if re.search(r"\d", value):
        return False

    # Reject academic classifications.
    classification_pattern = re.compile(
        r"^(?:"
        r"R[-\s]?(?:FR|SO|JR|SR)\.?|"
        r"(?:RS|R)\s?(?:FR|SO|JR|SR)\.?|"
        r"FR|FRESHMAN|FROSH|"
        r"SO|SOPH|SOPHOMORE|"
        r"JR|JUNIOR|"
        r"SR|SENIOR|"
        r"GRAD|GRADUATE|"
        r"FIFTH\s+YEAR|5TH\s+YEAR|"
        r"POST[-\s]?BACC(?:ALAUREATE)?"
        r")$",
        re.IGNORECASE,
    )

    if classification_pattern.fullmatch(value):
        return False

    # Only accept explicit high-school-style indicators here.
    # Do not infer college status from generic institution names.
    school_markers = (
        "academy",
        "preparatory",
        "prep",
        "high school",
        "secondary school",
    )

    if not any(marker in value.lower() for marker in school_markers):
        return False

    # Allow ordinary school-name punctuation.
    if not re.fullmatch(
        r"[^\W\d_][\w .&'’\-()]*",
        value,
        re.UNICODE,
    ):
        return False

    words = value.split()

    return 1 <= len(words) <= 8




def interpret_compound_roster_cells(rows, records, analysis):
    """
    Interpret likely school columns using progressive row context
    and corroborating evidence across columns.

    Original values remain in raw_row.
    Uncertain interpretations remain in custom_fields and receive
    review warnings.
    """
    analysis = analysis or {}

    mapping = analysis.get("mapping", {})
    custom_columns = analysis.get("custom_columns", {})

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def split_components(value):
        return [
            part.strip()
            for part in re.split(r"[/|;]", str(value))
            if part.strip()
        ]

    def normalize_component(value):
        return re.sub(
            r"[^a-z0-9]",
            "",
            str(value).lower(),
        )
    position_tokens = {
        "QB", "RB", "FB", "HB", "WR", "TE",
        "OL", "OT", "OG", "OC", "G", "T", "C",
        "DL", "DE", "DT", "NT",
        "LB", "MLB", "ILB", "OLB",
        "DB", "CB", "S", "FS", "SS",
        "K", "P", "LS", "EDGE", "ATH",
    }

    def is_position_designation(value):
        parts = [
            part.strip().upper()
            for part in re.split(r"[/|;,&+]", str(value))
            if part.strip()
        ]

        return (
            len(parts) > 1
            and all(part in position_tokens for part in parts)
        )

    def remove_custom_value(record, column_index):
        custom_name = custom_columns.get(
            column_index, {}
        ).get(
            "suggested_name"
        )

        possible_names = [
            custom_name,
            f"Unresolved Column {column_index + 1}",
            f"Custom Column {column_index + 1}",
            f"Unmapped Column {column_index + 1}",
        ]

        for name in possible_names:
            if name:
                record["custom_fields"].pop(name, None)

    def assign_value(record, field, value):
            """
            Assign a value without duplicating school information.

            Allows an existing compound school value to be refined
            into one of its individual components.
         """
            value = str(value).strip()
            existing = record.get(field)

            if not value:
                return False

            school_fields = ("high_school", "previous_school")

        # Prevent the same school from occupying both fields.
            other_school_field = (
                "previous_school"
                if field == "high_school"
                else "high_school"
                if field == "previous_school"
                else None
            )

            if other_school_field:
                other_value = record.get(other_school_field)

                if other_value:
                    other_parts = split_components(other_value)

                    if any(
                        normalize_component(part)
                        == normalize_component(value)
                        for part in other_parts
                    ):
                        return False

            if existing is None:
                record[field] = value
                return True

            if normalize_component(existing) == normalize_component(value):
                return True

        # If the existing value contains multiple components,
        # allow it to be narrowed to one matching component.
            existing_parts = split_components(existing)

            if len(existing_parts) > 1:
                if any(
                    normalize_component(part)
                    == normalize_component(value)
                    for part in existing_parts
                ):
                    record[field] = value
                    return True

            return False

    # ---------------------------------------------------------
    # Identify school-like columns using the whole roster.
    # ---------------------------------------------------------

    column_count = max(
        (len(row) for row in rows),
        default=0,
    )

    school_columns = []

    for column_index in range(column_count):
        selected_field = mapping.get(column_index)

        if selected_field not in (
            None,
            "high_school",
            "previous_school",
        ):
            continue

        values = [
            str(row[column_index]).strip()
            for row in rows
            if column_index < len(row)
            and str(row[column_index]).strip()
        ]

        if not values:
            continue

        school_like_count = 0
        school_candidate_count = 0
        explicit_school_count = 0
        compound_count = 0

        for value in values:
            # Position combinations are not school evidence.
            if is_position_designation(value):
                continue

            parts = split_components(value)

            parts = [
                part for part in parts
                if not is_position_designation(part)
            ]

            if len(parts) > 1:
                compound_count += 1

            for part in parts:
                kind = _classify_compound_component(part)

        # Geographic components do not count against
        # the school-likeness of a mixed column.
                if kind == "hometown":
                    continue

                school_candidate_count += 1

                if kind in ("high_school", "previous_school"):
                    explicit_school_count += 1
                    school_like_count += 1

                elif _looks_like_school_name(part):
                    school_like_count += 1

        ratio = school_like_count / max(
            school_candidate_count,
            1,
        )
        # A column needs a consistent school-like pattern.
        # A compound cell or explicit marker can also establish
        # evidence when only one player has a value in that column.
        enough_evidence = (
            len(values) >= 2
            or compound_count > 0
            or explicit_school_count > 0
        )

        if ratio >= 0.60 and enough_evidence:
            school_columns.append(column_index)

            # ---------------------------------------------------------
    # Infer school-column roles using roster-wide coverage.
    # ---------------------------------------------------------

    inferred_school_roles = {}

    if len(school_columns) == 2 and rows:
        column_coverage = {}

        for column_index in school_columns:
            populated_count = sum(
                1
                for row in rows
                if column_index < len(row)
                and str(row[column_index]).strip()
            )

            column_coverage[column_index] = (
                populated_count / len(rows)
            )

        first_column, second_column = school_columns

        first_coverage = column_coverage[first_column]
        second_coverage = column_coverage[second_column]

        # Only infer roles when one column is complete and
        # the other is genuinely less consistently populated.
        if (
            first_coverage == 1.0
            and second_coverage < 1.0
            and second_coverage > 0
        ):
            inferred_school_roles[first_column] = "high_school"
            inferred_school_roles[second_column] = "previous_school"

        elif (
            second_coverage == 1.0
            and first_coverage < 1.0
            and first_coverage > 0
        ):
            inferred_school_roles[second_column] = "high_school"
            inferred_school_roles[first_column] = "previous_school"

    # ---------------------------------------------------------
    # Interpret each player's row.
    # ---------------------------------------------------------

    for record in records:
        row_index = record.get("source_row_index")
        raw_row = record.get("raw_row", [])

        if row_index is None:
            continue

        record.setdefault("compound_interpretations", [])
        record.setdefault("review_warnings", [])
        record.setdefault("custom_fields", {})

        # Find where the identified player name and hometown sit.
        name_column = next(
            (
                column
                for column, field in mapping.items()
                if field == "full_name"
            ),
            None,
        )

        hometown_column = next(
            (
                column
                for column, field in mapping.items()
                if field == "hometown"
            ),
            None,
        )

        # A school candidate should occur after the player's name.
        # When hometown is known, it should also occur after hometown.
        preceding_columns = [
            column
            for column in (name_column, hometown_column)
            if column is not None
        ]

        if not preceding_columns:
            continue

        minimum_school_column = max(preceding_columns)

        eligible_columns = [
            column
            for column in school_columns
            if column > minimum_school_column
            and column < len(raw_row)
            and str(raw_row[column]).strip()
        ]

        if not eligible_columns:
            continue

        # -----------------------------------------------------
        # First pass: compare school columns against each other.
        #
        # Example:
        # Column A: Duke / Harvard / Mater Dei
        # Column B: Duke / Harvard
        #
        # Shared values are previous schools.
        # The remaining value is a likely high school.
        # -----------------------------------------------------

        components_by_column = {
            column: split_components(raw_row[column])
            for column in eligible_columns
        }

        resolved_components = {
            column: set()
            for column in eligible_columns
        }

        for first_index, first_column in enumerate(eligible_columns):
            first_parts = components_by_column[first_column]

            for second_column in eligible_columns[first_index + 1:]:
                second_parts = components_by_column[second_column]

                first_lookup = {
                    normalize_component(part): part
                    for part in first_parts
                }

                second_lookup = {
                    normalize_component(part): part
                    for part in second_parts
                }

                shared_keys = (
                    set(first_lookup) & set(second_lookup)
                )

                if not shared_keys:
                    continue

                first_unique = (
                    set(first_lookup) - shared_keys
                )

                second_unique = (
                    set(second_lookup) - shared_keys
                )

                # Only use this relationship when one side has
                # additional school information.
                if not first_unique and not second_unique:
                    continue

                shared_values = [
                    first_lookup[key]
                    for key in shared_keys
                ]

                previous_value = " / ".join(shared_values)

                previous_assigned = assign_value(
                    record,
                    "previous_school",
                    previous_value,
                )

                if not previous_assigned:
                    continue

                for key in shared_keys:
                    resolved_components[first_column].add(key)
                    resolved_components[second_column].add(key)

                unique_values = []

                unique_values.extend(
                    first_lookup[key]
                    for key in first_unique
                )

                unique_values.extend(
                    second_lookup[key]
                    for key in second_unique
                )

                # One remaining component is a strong candidate
                # for the high school.
                if len(unique_values) == 1:
                    high_school_value = unique_values[0]

                    if assign_value(
                        record,
                        "high_school",
                        high_school_value,
                    ):
                        unique_key = normalize_component(
                            high_school_value
                        )

                        if unique_key in first_lookup:
                            resolved_components[first_column].add(
                                unique_key
                            )

                        if unique_key in second_lookup:
                            resolved_components[second_column].add(
                                unique_key
                            )

                        record["compound_interpretations"].append({
                            "columns": [
                                first_column,
                                second_column,
                            ],
                            "original_values": [
                                raw_row[first_column],
                                raw_row[second_column],
                            ],
                            "assignments": {
                                "previous_school": previous_value,
                                "high_school": high_school_value,
                            },
                            "confidence_basis": (
                                "corroborating_school_values_across_columns"
                            ),
                        })

                        remove_custom_value(
                            record,
                            first_column,
                        )
                        remove_custom_value(
                            record,
                            second_column,
                        )

        # -----------------------------------------------------
        # Second pass: interpret remaining components.
        # -----------------------------------------------------

        for column_index in eligible_columns:
            original_value = str(
                raw_row[column_index]
            ).strip()

            parts = components_by_column[column_index]

            unresolved = []

            assignments = {}

            for part in parts:
                key = normalize_component(part)

                if key in resolved_components[column_index]:
                    continue

                kind = _classify_compound_component(part)

                if kind in ("hometown", "high_school", "previous_school"):
                    if assign_value(record, kind, part):
                        assignments[kind] = part
                    else:
                        unresolved.append(part)

                elif column_index in inferred_school_roles:
                    inferred_field = inferred_school_roles[column_index]

                    if (
                        len(parts) == 1
                        and _looks_like_school_name(part)
                        and assign_value(record, inferred_field, part)
                    ):
                        assignments[inferred_field] = part

                        record["review_warnings"].append({
                            "type": "inferred_school_role",
                            "column": column_index,
                            "field": inferred_field,
                            "value": part,
                            "reason": (
                                "The school role was inferred from "
                                "column-wide population patterns."
                            ),
                        })
                    else:
                        unresolved.append(part)

                else:
                    unresolved.append(part)

            # A single unmarked school name in a consistently
            # school-like column is a reasonable high-school
            # candidate after the player's name and hometown.
            # Identify unmarked school-like components that remain
# after explicit hometown and school information is handled.
            unmarked_school_parts = [
                part
                for part in unresolved
                if _looks_like_school_name(part)
]

# If no high school has been identified, one unmarked
# school candidate is a possible high school.
            if (
                len(unmarked_school_parts) == 1
                and record.get("high_school") is None
            ):
                candidate = unmarked_school_parts[0]

                if assign_value(
                    record,
                    "high_school",
                    candidate,
                ):
                    assignments["high_school"] = candidate
                    unresolved.remove(candidate)

                    record["review_warnings"].append({
                            "type": "inferred_school",
                            "column": column_index,
                            "value": candidate,
                            "reason": (
                            "An unmarked school-like value was identified "
                "through its position and surrounding roster data."
            ),
        })

# If a high school has already been identified, additional
# unmarked school candidates in later school columns are
# interpreted as previous-school information.
            elif (
                unmarked_school_parts
                and record.get("high_school") is not None
                and len(unmarked_school_parts) == len(unresolved)
                ):
                candidate = " / ".join(unmarked_school_parts)

                if assign_value(
                    record,
                    "previous_school",
                    candidate,
         ):
                    assignments["previous_school"] = candidate

                    for part in unmarked_school_parts:
                        unresolved.remove(part)
            # Record the interpretation and preserve anything
            # that could not be confidently assigned.
            if assignments or len(parts) > 1:
                record["compound_interpretations"].append({
                    "column": column_index,
                    "original_value": original_value,
                    "components": parts,
                    "assignments": assignments,
                    "unresolved_components": unresolved,
                    "confidence_basis": (
                        "explicit_markers_and_progressive_row_context"
                    ),
                })

                        # Remove earlier warnings for this same cell.
            # The final interpretation below is authoritative.
            record["review_warnings"] = [
                warning
                for warning in record["review_warnings"]
                if not (
                    warning.get("type") == "compound_cell"
                    and warning.get("column") == column_index
                )
            ]

            assigned_components = {
                normalize_component(record.get(field))
                for field in (
                    "hometown",
                    "high_school",
                    "previous_school",
                )
                if record.get(field)
            }

            unresolved = [
                component
                for component in unresolved
                if normalize_component(component)
                not in assigned_components
            ]

            if unresolved:
                record["review_warnings"].append({
                    "type": "compound_cell",
                    "column": column_index,
                    "original_value": original_value,
                    "unresolved_components": unresolved,
                })
            else:
                remove_custom_value(
                    record,
                    column_index,
                )

    return records







def _normalize_roster_table_rows(rows):
    """Normalize extracted table rows and remove trailing empty cells."""
    normalized_rows = []

    for row in rows or []:
        if isinstance(row, (list, tuple)):
            normalized_row = [
                str(cell).strip() if cell is not None else ""
                for cell in row
            ]
        elif isinstance(row, str):
            normalized_row = [
                cell.strip() for cell in row.split("\t")
            ]
        else:
            continue

        # Remove empty cells at the end of a row without
        # disturbing empty cells between actual columns.
        while normalized_row and not normalized_row[-1]:
            normalized_row.pop()

        if any(normalized_row):
            normalized_rows.append(normalized_row)

    return normalized_rows



def _extract_plain_text_table_rows(plain_text):
    """
    Extract rows from tab-delimited clipboard text.

    Deliberately does not split ordinary text on spaces because that
    would destroy player names and multi-word values.
    """
    if not plain_text:
        return []

    rows = []

    for line in plain_text.splitlines():
        if "\t" not in line:
            continue

        row = [cell.strip() for cell in line.split("\t")]

        if any(row):
            rows.append(row)

    return rows



def parse_roster_clipboard(clipboard_data=None):
    """
    Main roster-import orchestration entry point.

    Pipeline:
        Clipboard extraction
        -> Table extraction
        -> Header detection
        -> Header mapping OR headerless inference
        -> Record construction
        -> Shared compound-cell interpretation
        -> Import-readiness information

    Pass clipboard_data to test with previously captured clipboard
    contents. If omitted, the current clipboard is read.
    """
    if clipboard_data is None:
        clipboard_data = read_clipboard_content()

    if not clipboard_data:
        return {
            "records": [],
            "source": None,
            "table_rows": [],
            "header_result": None,
            "column_mapping": {},
            "analysis": None,
            "blocks": [],
            "import_readiness": "not_ready",
            "required_field_status": {},
            "errors": ["No clipboard content was available."],
        }

    extracted = extract_clipboard_content(clipboard_data)

    # HTML tables take priority because they preserve actual columns.
    rows = _normalize_roster_table_rows(
        extracted.get("html_rows", [])
    )

    source = "html_table" if rows else None

    # Fall back to tab-delimited plain text.
    if not rows:
        rows = _extract_plain_text_table_rows(
            extracted.get("plain_text", "")
        )

        if rows:
            source = "plain_text_table"

    # Keep profile blocks available as a fallback source.
    blocks = segment_player_blocks(extracted)

    if not rows:
        return {
            "records": [],
            "source": "profile_blocks" if blocks else None,
            "table_rows": [],
            "header_result": None,
            "column_mapping": {},
            "analysis": None,
            "blocks": blocks,
            "import_readiness": "not_ready",
            "required_field_status": {},
            "errors": [
                "No tabular roster data was found. "
                "Profile blocks were extracted where available."
            ],
            "extracted": extracted,
        }

    header_result = detect_table_header(rows)

    analysis = None

    if header_result.get("has_header"):
        column_mapping = map_table_headers(
            header_result["headers"]
        )

        records = parse_table_records(
            rows,
            header_result,
            column_mapping,
        )

        pipeline_type = "headered"

    else:
        observations = observe_table(rows)

        hypotheses = generate_column_hypotheses(
            observations
        )

        analysis = infer_headerless_column_mapping(
            rows,
            observations=observations,
            hypotheses=hypotheses,
        )

        column_mapping = analysis.get("mapping", {})

        records = parse_inferred_headerless_records(
            rows,
            analysis,
        )

        pipeline_type = "headerless"

    # Shared compound-cell interpretation for both pipelines.
    records = interpret_compound_roster_cells(
        rows,
        records,
        analysis or {},
    )

    # Required fields are checked across the resulting roster.
    required_fields = (
        "jersey_number",
        "full_name",
        "position",
    )

    required_field_status = {
        field: any(record.get(field) for record in records)
        for field in required_fields
    }

    missing_required_fields = [
        field
        for field, present in required_field_status.items()
        if not present
    ]

    has_ambiguities = bool(
        analysis and analysis.get("ambiguous_columns")
    )

    has_custom_columns = any(
        record.get("custom_fields")
        for record in records
    )

    if not records or missing_required_fields:
        import_readiness = "not_ready"
    elif has_ambiguities or has_custom_columns:
        import_readiness = "needs_review"
    else:
        import_readiness = "ready"

    return {
        "records": records,
        "source": source,
        "pipeline_type": pipeline_type,
        "table_rows": rows,
        "header_result": header_result,
        "column_mapping": column_mapping,
        "analysis": analysis,
        "blocks": blocks,
        "import_readiness": import_readiness,
        "required_field_status": required_field_status,
        "missing_required_fields": missing_required_fields,
        "has_ambiguities": has_ambiguities,
        "has_custom_columns": has_custom_columns,
        "extracted": extracted,
        "errors": [],
    }


def extract_compound_components(
    rows,
    records,
    column_mapping,
    header_result=None,
    pipeline_type=None,
):
    """
    Extract individual components from compound roster cells.

    This function does not modify player records or assign values to
    standard/custom fields. It returns separate review candidates.

    Expected column_mapping format:
        {
            0: "full_name",
            1: "jersey_number",
            2: {"custom_field": "Hometown / High School"},
        }

    Columns absent from column_mapping are treated as ignored.
    """

    import copy
    import re

    components = []

    headers = []
    if isinstance(header_result, dict):
        headers = header_result.get("headers") or []

    # Common football position combinations should not be split.
    position_tokens = {
        "QB", "RB", "FB", "HB",
        "WR", "TE",
        "OL", "OT", "OG", "OC", "C", "G", "T",
        "DL", "DE", "DT", "NT", "NG",
        "LB", "ILB", "OLB", "MLB", "SAM", "MIKE", "WILL",
        "DB", "CB", "S", "FS", "SS", "NB",
        "K", "P", "LS",
    }

    def is_position_combination(parts):
        if len(parts) < 2:
            return False

        normalized = [
            re.sub(r"[^A-Za-z]", "", part).upper()
            for part in parts
        ]

        return all(
            token in position_tokens
            for token in normalized
        )


    def get_suggestion(value, source_mapping):
        """
        Return an advisory field suggestion based on the component itself.

        Source-column mappings are deliberately not used to force a
        classification onto individual components.
        """

        cleaned_value = str(value).strip()

        # Remove trailing punctuation so values such as "Lexington, Ky,"
        # and "Columbus, Ohio." can be classified more reliably.
        normalized_value = re.sub(
            r"[\s.,;:]+$",
            "",
            cleaned_value,
        ).strip()

        classification = _classify_compound_component(
            normalized_value
        )

        if classification in {
            "hometown",
            "high_school",
            "previous_school",
        }:
            reasons = {
                "hometown": "Recognized as a geographic location",
                "high_school": (
                    "Contains a recognized high-school indicator"
                ),
                "previous_school": (
                    "Contains a recognized college or university indicator"
                ),
            }

            return classification, reasons[classification]

        # Explicit high-school indicators.
        if re.search(
            r"\b(high school|secondary school|preparatory school|prep school)\b",
            normalized_value,
            flags=re.IGNORECASE,
        ) or re.search(
            r"\bHS\b",
            normalized_value,
            flags=re.IGNORECASE,
        ):
            return (
                "high_school",
                "Contains an explicit high-school indicator",
            )

        # Explicit college/university indicators.
        if re.search(
            r"\b(university|college)\b",
            normalized_value,
            flags=re.IGNORECASE,
        ):
            return (
                "previous_school",
                "Contains a college or university indicator",
            )

        # A generic school-like name is not enough to determine
        # whether it is a high school or a previous college.
        if _looks_like_school_name(normalized_value):
            return (
                None,
                "Looks like a school name, but its exact role is uncertain",
            )

        return (
            None,
            "No reliable automatic classification",
        )


    for record_index, record in enumerate(records):
        if not isinstance(record, dict):
            continue

        raw_row = record.get("raw_row")

        # Use the original source rows only as a fallback.
        source_row_index = record.get("source_row_index")

        if raw_row is None:
            if (
                isinstance(source_row_index, int)
                and 0 <= source_row_index < len(rows)
            ):
                raw_row = rows[source_row_index]
            elif record_index < len(rows):
                raw_row = rows[record_index]
                source_row_index = record_index
            else:
                continue

        if not isinstance(raw_row, (list, tuple)):
            continue

        if source_row_index is None:
            source_row_index = record_index

        # Headered imports can contain two leading source columns
        # (jersey number and player name) that are not part of headers.
        column_offset = 0

        if (
            pipeline_type == "headered"
            and headers
            and len(raw_row) == len(headers) + 2
        ):
            first_value = str(raw_row[0]).strip()
            second_value = str(raw_row[1]).strip()
            player_name = str(record.get("full_name") or "").strip()

            first_looks_like_jersey = bool(
                re.fullmatch(r"#?\d+[A-Za-z]?", first_value)
            )

            second_matches_player = (
                not player_name
                or second_value.casefold() == player_name.casefold()
            )

            if first_looks_like_jersey and second_matches_player:
                column_offset = 2

        for mapping_column_index, source_mapping in column_mapping.items():
            try:
                mapping_column_index = int(mapping_column_index)
            except (TypeError, ValueError):
                continue

            source_column_index = (
                mapping_column_index + column_offset
            )

            if not 0 <= source_column_index < len(raw_row):
                continue

            original_cell_value = raw_row[source_column_index]

            if original_cell_value is None:
                continue

            original_text = str(original_cell_value)

            if not original_text.strip():
                continue

            # Do not split URLs. Their slashes are part of the URL,
            # not separators between roster components.
            if re.search(
                r"(https?://|www\.)",
                original_text,
                flags=re.IGNORECASE,
            ):
                continue

            # Split on slash, pipe, or semicolon.
            # Empty pieces are discarded, but the original cell
            # remains preserved in every resulting component.
            parts = re.split(
                r"\s*/\s*|\s*\|\s*|\s*;\s*",
                original_text,
            )

            parts = [
                part.strip()
                for part in parts
                if part.strip()
            ]

            if len(parts) < 2:
                continue

            # Do not turn designations such as OL/TE or WR/DB
            # into separate review candidates.
            if is_position_combination(parts):
                continue

            if pipeline_type == "headered" and headers:
                if 0 <= mapping_column_index < len(headers):
                    source_column_name = str(
                        headers[mapping_column_index]
                    ).strip()
                else:
                    source_column_name = (
                        f"Column {mapping_column_index + 1}"
                    )
            else:
                source_column_name = (
                    f"Column {mapping_column_index + 1}"
                )

            for component_index, component_value in enumerate(parts):
                suggested_field, suggestion_reason = get_suggestion(
                    component_value,
                    source_mapping,
                )

                components.append({
                    "component_id": (
                        f"row_{source_row_index}"
                        f"_col_{source_column_index}"
                        f"_part_{component_index}"
                    ),
                    "record_index": record_index,
                    "player_name": record.get("full_name"),
                    "jersey_number": record.get("jersey_number"),

                    "source_row_index": source_row_index,
                    "source_column_index": source_column_index,
                    "mapping_column_index": mapping_column_index,
                    "source_column_name": source_column_name,

                    "original_cell_value": original_cell_value,
                    "component_index": component_index,
                    "component_value": component_value,

                    "source_mapping": copy.deepcopy(source_mapping),

                    "suggested_field": suggested_field,
                    "suggestion_reason": suggestion_reason,

                    # These remain empty until the user reviews
                    # and makes a decision.
                    "assigned_field": None,
                    "review_status": "pending",
                })

    return components


def split_headered_compound_cell(header, cell_value):
    """
    Split a compound source column using the meaning and order
    of its header.

    Example:
        Header: Hometown / Previous School
        Value:  Pine Bluff, AR / Arkansas State

    Returns:
        {
            "assignments": {
                "hometown": "Pine Bluff, AR",
                "previous_school": "Arkansas State"
            },
            "unresolved": [],
            "original_value": "Pine Bluff, AR / Arkansas State"
        }

    Does not guess when the header or component count is ambiguous.
    """

    import re

    if not header or cell_value is None:
        return None

    header_parts = [
        part.strip()
        for part in str(header).split("/")
    ]

    if len(header_parts) < 2:
        return None

    field_aliases = {
        "hometown": "hometown",
        "home town": "hometown",
        "city": "hometown",

        "high school": "high_school",
        "highschool": "high_school",
        "hs": "high_school",

        "previous school": "previous_school",
        "prev school": "previous_school",
        "previous college": "previous_school",
        "college": "previous_school",
        "university": "previous_school",
    }

    destination_fields = []

    for part in header_parts:
        normalized = re.sub(
            r"\s+",
            " ",
            part.lower().strip()
        )

        destination = field_aliases.get(normalized)

        if destination is None:
            return None

        if destination in destination_fields:
            return None

        destination_fields.append(destination)

    original_value = str(cell_value).strip()

    value_parts = [
        part.strip()
        for part in original_value.split("/")
    ]

    if len(value_parts) != len(destination_fields):
        return {
            "assignments": {},
            "unresolved": value_parts,
            "original_value": original_value,
            "reason": (
                "The number of cell components does not match "
                "the number of fields in the header."
            ),
        }

    assignments = {}
    unresolved = []

    for destination, value in zip(
        destination_fields,
        value_parts
    ):
        if value:
            assignments[destination] = value
        else:
            unresolved.append({
                "field": destination,
                "value": value,
            })

    return {
        "assignments": assignments,
        "unresolved": unresolved,
        "original_value": original_value,
        "reason": None,
    }