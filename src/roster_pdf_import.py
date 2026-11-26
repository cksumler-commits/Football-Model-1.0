
import re
import sys
from pathlib import Path

import pymupdf


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be extracted successfully."""


# ============================================================
# OUTPUT FIELDS
# ============================================================

OUTPUT_HEADERS = [
    "Jersey Number",
    "Name",
    "Position",
    "Height",
    "Weight",
    "Class",
    "Experience",
    "Hometown",
    "High School",
    "Previous School",
]


# ============================================================
# PROFILE A: TRADITIONAL TABLE LAYOUT
# ============================================================

COLUMN_BOUNDS = [
    ("Jersey Number", 40, 65),
    ("Name", 65, 130),
    ("Position", 130, 193),
    ("Height", 193, 238),
    ("Weight", 238, 284),
    ("Class", 284, 344),
    ("Experience", 344, 409),
    ("Hometown", 409, 476),
    ("High School", 476, 558),
    ("Previous School", 558, 612),
]


# ============================================================
# PROFILE B: PLAYER CARD LAYOUT
# ============================================================

CARD_NUMBER_X_MIN = 40
CARD_NUMBER_X_MAX = 60

CARD_NAME_X_MIN = 65
CARD_NAME_X_MAX = 220

CARD_METADATA_X_MIN = 220

CARD_HEADER_EXCLUSION_Y = 25

CARD_FIRST_ROW_PADDING = 28
CARD_LAST_ROW_PADDING = 30

CARD_LINE_Y_TOLERANCE = 4.0

HEIGHT_PATTERN = re.compile(r"^\d-\d{1,2}$")
WEIGHT_PATTERN = re.compile(r"^\d{2,3}$")

POSITION_PHRASES = (
    "quarterback",
    "running back",
    "wide receiver",
    "tight end",
    "offensive line",
    "offensive tackle",
    "offensive guard",
    "defensive line",
    "defensive tackle",
    "defensive end",
    "linebacker",
    "cornerback",
    "safety",
    "nickel",
    "edge",
    "kicker",
    "punter",
    "long snapper",
    "specialist",
    "center",
)

POSITION_ABBREVIATIONS = {
    "qb", "rb", "wr", "te", "ol", "dl",
    "lb", "cb", "db", "s", "ls",
}


# ============================================================
# SHARED HELPERS
# ============================================================

def get_player_anchors(words):
    """Find jersey numbers that mark the beginning of player records."""

    anchors = []

    for word in words:
        x0, y0, x1, y1, text, *_ = word

        if (
            CARD_NUMBER_X_MIN <= x0 <= CARD_NUMBER_X_MAX
            and re.fullmatch(r"\d{1,2}", text)
            and y0 < 740
        ):
            anchors.append({
                "number": text,
                "y": (y0 + y1) / 2,
            })

    return sorted(anchors, key=lambda item: item["y"])


def group_words_into_lines(words, tolerance=CARD_LINE_Y_TOLERANCE):
    """Group PDF words into approximate horizontal text lines."""

    sorted_words = sorted(
        words,
        key=lambda word: (
            (word[1] + word[3]) / 2,
            word[0]
        )
    )

    lines = []

    for word in sorted_words:
        center_y = (word[1] + word[3]) / 2
        matching_line = None

        for line in reversed(lines):
            if abs(center_y - line["center_y"]) <= tolerance:
                matching_line = line
                break

            if center_y - line["center_y"] > tolerance:
                break

        if matching_line is None:
            lines.append({
                "center_y": center_y,
                "words": [word],
            })
        else:
            matching_line["words"].append(word)

            centers = [
                (item[1] + item[3]) / 2
                for item in matching_line["words"]
            ]

            matching_line["center_y"] = sum(centers) / len(centers)

    for line in lines:
        line["words"].sort(key=lambda word: word[0])

    return sorted(lines, key=lambda line: line["center_y"])


def split_words_on_hyphens(words):
    """Split on standalone hyphens while preserving hyphens inside values."""

    segments = [[]]

    for word in sorted(words, key=lambda item: item[0]):
        text = word[4].strip()

        if text in ("-", "–", "—"):
            segments.append([])
            continue

        if text == "|":
            continue

        segments[-1].append(text)

    return [
        " ".join(segment).strip()
        for segment in segments
    ]


def looks_like_position(value):
    """Identify position names without matching abbreviations inside words."""

    normalized = value.casefold().strip()

    if any(phrase in normalized for phrase in POSITION_PHRASES):
        return True

    tokens = re.findall(r"[a-z]+", normalized)

    return any(
        token in POSITION_ABBREVIATIONS
        for token in tokens
    )


def split_line_at_pipe(words):
    """Divide a metadata line at its standalone pipe character."""

    sorted_words = sorted(words, key=lambda word: word[0])

    pipe_index = next(
        (
            index
            for index, word in enumerate(sorted_words)
            if word[4].strip() == "|"
        ),
        None
    )

    if pipe_index is None:
        return sorted_words, []

    return (
        sorted_words[:pipe_index],
        sorted_words[pipe_index + 1:]
    )


# ============================================================
# PROFILE DETECTION
# ============================================================

def detect_pdf_layout(document):
    """
    Detect a supported layout.

    Returns:
        "table"  - traditional table profile
        "card"   - player card profile
        "unknown" - no supported profile confidently identified

    Unknown is a valid detection result, not an extraction failure.
    """

    table_score = 0
    card_score = 0

    for page in document:
        words = page.get_text("words")
        anchors = get_player_anchors(words)

        if not anchors:
            continue

        if any(
            word[4].strip() == "|" and word[0] >= 300
            for word in words
        ):
            card_score += 2

        if any(
            word[0] >= 240
            and word[4].strip().lower() in (
                "quarterback", "safety", "linebacker",
                "cornerback", "wide", "defensive",
                "offensive", "tight", "running",
            )
            for word in words
        ):
            card_score += 1

        if any(
            130 <= word[0] < 193
            and looks_like_position(word[4])
            for word in words
        ):
            table_score += 1

    if card_score > 0 and card_score >= table_score:
        return "card"

    if table_score > 0:
        return "table"

    return "unknown"


# ============================================================
# PROFILE A: TRADITIONAL TABLE EXTRACTION
# ============================================================

def assign_words_to_columns(row_words):
    """Group the words in one player row by horizontal position."""

    fields = {}

    for field_name, left, right in COLUMN_BOUNDS:
        field_words = [
            word
            for word in row_words
            if left <= word[0] < right
        ]

        field_words.sort(
            key=lambda word: (
                round(word[1], 1),
                word[0]
            )
        )

        fields[field_name] = " ".join(
            word[4] for word in field_words
        ).strip()

    return fields


def extract_table_page_records(page):
    """Reconstruct player records from a traditional table-layout page."""

    words = page.get_text("words")
    anchors = get_player_anchors(words)

    if not anchors:
        return []

    records = []

    for index, anchor in enumerate(anchors):
        anchor_y = anchor["y"]

        if index == 0:
            top = max(0, anchor_y - 20)
        else:
            top = (
                anchors[index - 1]["y"] + anchor_y
            ) / 2

        if index == len(anchors) - 1:
            bottom = min(page.rect.height - 30, anchor_y + 20)
        else:
            bottom = (
                anchor_y + anchors[index + 1]["y"]
            ) / 2

        row_words = [
            word
            for word in words
            if (
                top <= (word[1] + word[3]) / 2 < bottom
                and word[1] >= CARD_HEADER_EXCLUSION_Y
                and word[1] < page.rect.height - 30
            )
        ]

        fields = assign_words_to_columns(row_words)
        fields["Jersey Number"] = anchor["number"]

        if fields["Name"]:
            records.append(fields)

    return records


# ============================================================
# PROFILE B: PLAYER CARD EXTRACTION
# ============================================================

def extract_card_name(row_words):
    """Extract the player name from the left side of a card."""

    name_words = [
        word
        for word in row_words
        if CARD_NAME_X_MIN <= word[0] < CARD_NAME_X_MAX
    ]

    name_words.sort(
        key=lambda word: (
            round(word[1], 1),
            word[0]
        )
    )

    return " ".join(
        word[4] for word in name_words
    ).strip()


def extract_class_height_weight(lines):
    """Extract class, height, and weight from card metadata."""

    result = {
        "Class": "",
        "Height": "",
        "Weight": "",
    }

    for line in lines:
        left_words, _ = split_line_at_pipe(line["words"])

        left_words = [
            word for word in left_words
            if word[0] >= CARD_METADATA_X_MIN - 20
        ]

        if not left_words:
            continue

        tokens = [
            word[4].strip()
            for word in sorted(left_words, key=lambda word: word[0])
        ]

        height_index = next(
            (
                index
                for index, token in enumerate(tokens)
                if HEIGHT_PATTERN.fullmatch(token)
            ),
            None
        )

        if height_index is not None:
            height_value = tokens[height_index]
            class_tokens = tokens[:height_index]
            weight_tokens = tokens[height_index + 1:]

        else:
            split_height_index = None

            for index in range(len(tokens) - 1):
                first = tokens[index]
                second = tokens[index + 1]

                if (
                    re.fullmatch(r"[4-7]", first)
                    and re.fullmatch(r"\d{1,2}", second)
                ):
                    split_height_index = index
                    break

            if split_height_index is None:
                continue

            height_value = (
                f"{tokens[split_height_index]}-"
                f"{tokens[split_height_index + 1]}"
            )

            class_tokens = tokens[:split_height_index]
            weight_tokens = tokens[split_height_index + 2:]

        weight = next(
            (
                re.sub(r"[^\d]", "", token)
                for token in weight_tokens
                if WEIGHT_PATTERN.fullmatch(
                    re.sub(r"[^\d]", "", token)
                )
            ),
            ""
        )

        if not weight or not class_tokens:
            continue

        result["Class"] = " ".join(class_tokens).strip()
        result["Height"] = height_value
        result["Weight"] = weight

        return result

    return result


def parse_position_segments(segments):
    """Convert position metadata segments into roster fields."""

    fields = {
        "Position": "",
        "Hometown": "",
        "High School": "",
        "Previous School": "",
    }

    cleaned_segments = [
        segment.strip()
        for segment in segments
        if segment and segment.strip()
    ]

    position_index = next(
        (
            index
            for index, segment in enumerate(cleaned_segments)
            if looks_like_position(segment)
        ),
        None
    )

    if position_index is None:
        return fields

    cleaned_segments = cleaned_segments[position_index:]

    fields["Position"] = cleaned_segments[0]

    if len(cleaned_segments) > 1:
        fields["Hometown"] = cleaned_segments[1]

    if len(cleaned_segments) > 2:
        fields["High School"] = cleaned_segments[2]

    if len(cleaned_segments) > 3:
        fields["Previous School"] = " - ".join(cleaned_segments[3:])

    return fields


def extract_position_metadata(lines):
    """Extract position, hometown, high school, and previous school."""

    candidate_segments = []

    for line in lines:
        left_words, right_words = split_line_at_pipe(line["words"])

        if right_words:
            candidate_segments.extend(
                split_words_on_hyphens(right_words)
            )
            continue

        metadata_words = [
            word
            for word in line["words"]
            if word[0] >= CARD_METADATA_X_MIN - 20
        ]

        if not metadata_words:
            continue

        segments = split_words_on_hyphens(metadata_words)

        if any(looks_like_position(segment) for segment in segments):
            candidate_segments.extend(segments)

    return parse_position_segments(candidate_segments)


def extract_card_metadata(row_words):
    """Extract all available metadata from a player card."""

    metadata_words = [
        word
        for word in row_words
        if word[0] >= CARD_METADATA_X_MIN - 20
    ]

    lines = group_words_into_lines(metadata_words)

    fields = {
        "Class": "",
        "Height": "",
        "Weight": "",
        "Experience": "",
        "Position": "",
        "Hometown": "",
        "High School": "",
        "Previous School": "",
    }

    fields.update(extract_class_height_weight(lines))
    fields.update(extract_position_metadata(lines))

    return fields


def extract_card_page_records(page):
    """Reconstruct player records from a card-layout PDF page."""

    words = page.get_text("words")
    anchors = get_player_anchors(words)

    if not anchors:
        return []

    records = []

    for index, anchor in enumerate(anchors):
        anchor_y = anchor["y"]

        if index == 0:
            top = max(0, anchor_y - CARD_FIRST_ROW_PADDING)
        else:
            top = (
                anchors[index - 1]["y"] + anchor_y
            ) / 2

        if index == len(anchors) - 1:
            bottom = min(
                page.rect.height - 25,
                anchor_y + CARD_LAST_ROW_PADDING
            )
        else:
            bottom = (
                anchor_y + anchors[index + 1]["y"]
            ) / 2

        row_words = [
            word
            for word in words
            if (
                top <= (word[1] + word[3]) / 2 < bottom
                and word[1] < page.rect.height - 25
            )
        ]

        name = extract_card_name(row_words)

        if not name:
            continue

        fields = {
            "Jersey Number": anchor["number"],
            "Name": name,
        }

        fields.update(extract_card_metadata(row_words))
        records.append(fields)

    return records


# ============================================================
# RECORD OUTPUT
# ============================================================

def records_to_tsv(records):
    """Convert reconstructed records into the existing TSV format."""

    output_lines = ["\t".join(OUTPUT_HEADERS)]

    for record in records:
        output_lines.append(
            "\t".join(
                str(record.get(header, "") or "")
                for header in OUTPUT_HEADERS
            )
        )

    return "\n".join(output_lines)


# ============================================================
# GENERAL PDF ANALYSIS
# ============================================================

def analyze_pdf(pdf_path: str | Path):
    """
    Analyze a PDF without requiring a supported roster layout.

    Returns:
        file_name
        page_count
        layout
        has_selectable_text
        total_words
        records
        pages

    Unknown layouts still return extracted page text and diagnostics.
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise PDFExtractionError(f"PDF file not found: {pdf_path}")

    if not pdf_path.is_file():
        raise PDFExtractionError(
            f"The selected path is not a file: {pdf_path}"
        )

    if pdf_path.suffix.lower() != ".pdf":
        raise PDFExtractionError("The selected file is not a PDF.")

    try:
        with pymupdf.open(pdf_path) as document:

            if document.is_encrypted:
                raise PDFExtractionError(
                    "This PDF is password-protected."
                )

            if len(document) == 0:
                raise PDFExtractionError(
                    "This PDF does not contain any pages."
                )

            layout = detect_pdf_layout(document)

            page_results = []
            total_words = 0
            total_text_characters = 0

            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text", sort=True)
                words = page.get_text("words", sort=True)

                total_words += len(words)
                total_text_characters += len(text.strip())

                page_results.append({
                    "page_number": page_number,
                    "width": round(page.rect.width, 1),
                    "height": round(page.rect.height, 1),
                    "word_count": len(words),
                    "text": text,
                })

            has_selectable_text = total_words > 0

            records = []

            if layout == "table":
                for page in document:
                    records.extend(extract_table_page_records(page))

            elif layout == "card":
                for page in document:
                    records.extend(extract_card_page_records(page))

            return {
                "file_name": pdf_path.name,
                "page_count": len(document),
                "layout": layout,
                "has_selectable_text": has_selectable_text,
                "total_words": total_words,
                "total_text_characters": total_text_characters,
                "records": records,
                "pages": page_results,
            }

    except PDFExtractionError:
        raise

    except Exception as error:
        raise PDFExtractionError(
            f"Could not analyze PDF: {error}"
        ) from error


# ============================================================
# MAIN PDF EXTRACTION
# ============================================================

def extract_pdf_text(pdf_path: str | Path) -> str:
    """
    Extract roster records using a supported layout.

    This function remains the entry point for actual roster imports.
    Unknown layouts are analyzed by analyze_pdf(), not guessed here.
    """

    result = analyze_pdf(pdf_path)

    if result["layout"] == "unknown":
        if result["has_selectable_text"]:
            raise PDFExtractionError(
                "The PDF contains selectable text, but its roster "
                "layout is not supported yet. Use the PDF Tester "
                "to inspect the extracted text."
            )

        raise PDFExtractionError(
            "The PDF does not appear to contain selectable text. "
            "It may be scanned or image-based and require OCR."
        )

    if not result["records"]:
        raise PDFExtractionError(
            "A supported layout was detected, but no player records "
            "could be reconstructed."
        )

    return records_to_tsv(result["records"])


# ============================================================
# PDF LAYOUT INSPECTION
# ============================================================

def inspect_pdf_layout(
    pdf_path: str | Path,
    page_number: int = 1,
    word_limit: int = 100
) -> None:
    """Print word coordinates for diagnosing a PDF layout."""

    pdf_path = Path(pdf_path)

    if not pdf_path.exists() or not pdf_path.is_file():
        raise PDFExtractionError(
            f"PDF file not found: {pdf_path}"
        )

    try:
        with pymupdf.open(pdf_path) as document:

            if document.is_encrypted:
                raise PDFExtractionError(
                    "This PDF is password-protected."
                )

            if page_number < 1 or page_number > len(document):
                raise PDFExtractionError(
                    f"Page number must be between 1 and {len(document)}."
                )

            page = document[page_number - 1]

            print(f"\nLAYOUT INSPECTION: PAGE {page_number}")
            print(f"Page dimensions: {page.rect}")
            print("=" * 80)

            words = page.get_text("words", sort=True)

            for word in words[:word_limit]:
                x0, y0, x1, y1, text, *_ = word

                print(
                    f"x={x0:7.1f}-{x1:7.1f}  "
                    f"y={y0:7.1f}-{y1:7.1f}  "
                    f"text={text}"
                )

            print("=" * 80)
            print(
                f"Displayed {min(len(words), word_limit)} "
                f"of {len(words)} words."
            )

    except PDFExtractionError:
        raise

    except Exception as error:
        raise PDFExtractionError(
            f"Could not inspect PDF layout: {error}"
        ) from error


# ============================================================
# COMMAND LINE
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            '  Extract roster: python roster_pdf_import.py "path/to/roster.pdf"\n'
            '  Inspect layout: python roster_pdf_import.py "path/to/roster.pdf" --inspect'
        )
        sys.exit(1)

    try:
        if len(sys.argv) >= 3 and sys.argv[2] == "--inspect":
            inspect_pdf_layout(sys.argv[1])

        else:
            result = extract_pdf_text(sys.argv[1])

            print("\nPDF ROSTER RECONSTRUCTION SUCCESSFUL")
            print("=" * 100)
            print(result)

            print("\n" + "=" * 100)
            print(
                f"PLAYER RECORDS RECONSTRUCTED: "
                f"{max(0, len(result.splitlines()) - 1)}"
            )

    except PDFExtractionError as error:
        print(f"\nPDF EXTRACTION FAILED: {error}")
        sys.exit(1)
