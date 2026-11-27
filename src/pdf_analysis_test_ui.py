

import sys
from tkinter import dialog
import traceback
from pathlib import Path
from unittest import result
from PySide6.QtCore import QRectF, QTimer, Qt

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QDialog,
    QGraphicsScene,
    QGraphicsView,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)
from numpy import record
from numpy import record

from pdf_structure_analyzer import analyze_pdf_structure

from pdf_document_engine import extract_page_words

from PySide6.QtGui import (
    QColor,
    QPen,
    QBrush,
    QPixmap,
    QPainter,
)
import pymupdf
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF

import re

from roster_pdf_reconstruction import reconstruct_pdf_roster_cells


def classify_roster_layout(words, selection_bbox):
    """
    Classify the visual organization of a selected PDF region.

    This function is domain-specific to roster analysis.
    It does not assign semantic fields or create player records.

    Possible results:
        traditional_table
        multi_column_roster
        player_cards
        single_column_roster
        staff_or_non_player
        roster_like_unclassified
        unclassified

    The result includes evidence and confidence so later stages
    can decide which reconstruction strategy to use.
    """

    sx0, sy0, sx1, sy1 = map(float, selection_bbox)

    valid_words = []

    for word in words:
        bbox = word.get("bbox")

        if not bbox or len(bbox) != 4:
            continue

        try:
            x0, y0, x1, y1 = map(float, bbox)
        except (TypeError, ValueError):
            continue

        if x1 <= x0 or y1 <= y0:
            continue

        text = str(word.get("text", "")).strip()

        if not text:
            continue

        valid_words.append({
            "text": text,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "cx": (x0 + x1) / 2,
            "cy": (y0 + y1) / 2,
            "height": y1 - y0,
        })

    if not valid_words:
        return {
            "layout_type": "unclassified",
            "confidence": 0.0,
            "evidence": ["No usable words were found."],
            "metrics": {},
        }

    # --------------------------------------------------
    # 1. Establish typical text size and visual rows.
    # --------------------------------------------------

    heights = sorted(
        word["height"] for word in valid_words
    )

    median_height = heights[len(heights) // 2]

    row_tolerance = max(
        2.5,
        median_height * 0.65,
    )

    visual_rows = []

    for word in sorted(
        valid_words,
        key=lambda item: (item["cy"], item["x0"]),
    ):
        matching_row = None

        for row in reversed(visual_rows):
            row_center = sum(
                item["cy"] for item in row
            ) / len(row)

            if abs(word["cy"] - row_center) <= row_tolerance:
                matching_row = row
                break

            if word["cy"] - row_center > row_tolerance:
                break

        if matching_row is None:
            visual_rows.append([word])
        else:
            matching_row.append(word)

    for row in visual_rows:
        row.sort(key=lambda item: item["x0"])

    # --------------------------------------------------
    # 2. Detect likely jersey-number anchors.
    # --------------------------------------------------

    number_words = [
        word for word in valid_words
        if re.fullmatch(
            r"#?\d{1,2}",
            word["text"],
        )
    ]

    number_groups = []

    for word in sorted(
        number_words,
        key=lambda item: item["x0"],
    ):
        matching_group = None

        for group in number_groups:
            group_center = sum(
                item["x0"] for item in group
            ) / len(group)

            if abs(word["x0"] - group_center) <= max(
                8.0,
                median_height * 1.5,
            ):
                matching_group = group
                break

        if matching_group is None:
            number_groups.append([word])
        else:
            matching_group.append(word)

    # Remove groups with fewer than two anchors.
    repeated_number_groups = []

    for group in number_groups:
        group.sort(key=lambda item: item["cy"])

        unique_group = []

        for word in group:
            if (
                unique_group
                and abs(
                    word["cy"] - unique_group[-1]["cy"]
                ) <= max(3.0, median_height * 0.7)
            ):
                continue

            unique_group.append(word)

        if len(unique_group) >= 2:
            repeated_number_groups.append(unique_group)

    repeated_number_groups.sort(
        key=lambda group: min(item["x0"] for item in group)
    )

    # --------------------------------------------------
    # 3. Detect recognizable roster and staff headers.
    # --------------------------------------------------

    roster_headers = {
        "number", "no", "jersey", "player", "name",
        "position", "pos", "height", "ht",
        "weight", "wt", "class", "classification",
        "hometown", "high school", "experience",
        "major", "previous school",
    }

    staff_headers = {
        "coach", "coaches", "staff", "title",
        "position", "director", "assistant",
        "head coach", "coordinator",
    }

    header_words = []

    # Only inspect the upper portion of the selected region.
    region_height = max(1.0, sy1 - sy0)
    header_limit = sy0 + region_height * 0.30

    for word in valid_words:
        if word["cy"] > header_limit:
            continue

        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            word["text"].casefold(),
        ).strip()

        if normalized:
            header_words.append(normalized)

    roster_header_matches = sorted(
        set(header_words) & roster_headers
    )

    staff_header_matches = sorted(
        set(header_words) & staff_headers
    )

    # --------------------------------------------------
    # 4. Measure vertical spacing between player anchors.
    # --------------------------------------------------

    anchor_gaps = []

    for group in repeated_number_groups:
        for first, second in zip(group, group[1:]):
            gap = second["cy"] - first["cy"]

            if gap > 0:
                anchor_gaps.append(gap)

    anchor_gaps.sort()

    median_anchor_gap = (
        anchor_gaps[len(anchor_gaps) // 2]
        if anchor_gaps
        else 0.0
    )

    # Estimate how much text exists around each anchor.
    local_record_line_counts = []

    for group in repeated_number_groups:
        for index, anchor in enumerate(group):

            top = (
                sy0
                if index == 0
                else (group[index - 1]["cy"] + anchor["cy"]) / 2
            )

            bottom = (
                sy1
                if index == len(group) - 1
                else (anchor["cy"] + group[index + 1]["cy"]) / 2
            )

            local_words = [
                word for word in valid_words
                if top <= word["cy"] < bottom
            ]

            local_rows = set()

            for word in local_words:
                local_rows.add(
                    min(
                        range(len(visual_rows)),
                        key=lambda row_index: abs(
                            (
                                sum(
                                    item["cy"]
                                    for item in visual_rows[row_index]
                                ) / len(visual_rows[row_index])
                            ) - word["cy"]
                        ),
                    )
                )

            local_record_line_counts.append(
                len(local_rows)
            )

    local_record_line_counts.sort()

    median_record_lines = (
        local_record_line_counts[
            len(local_record_line_counts) // 2
        ]
        if local_record_line_counts
        else 0
    )

    # --------------------------------------------------
    # 5. Check whether anchor groups align across columns.
    # --------------------------------------------------

    aligned_anchor_pairs = 0
    possible_anchor_pairs = 0

    for first_index in range(len(repeated_number_groups)):
        for second_index in range(first_index + 1, len(repeated_number_groups)):

            first_group = repeated_number_groups[first_index]
            second_group = repeated_number_groups[second_index]

            for first in first_group:
                for second in second_group:
                    possible_anchor_pairs += 1

                    if abs(first["cy"] - second["cy"]) <= max(
                        5.0,
                        median_height,
                    ):
                        aligned_anchor_pairs += 1

    alignment_rate = (
        aligned_anchor_pairs / possible_anchor_pairs
        if possible_anchor_pairs
        else 0.0
    )

    # --------------------------------------------------
    # 6. Classify using combined structural evidence.
    # --------------------------------------------------

    evidence = []

    group_count = len(repeated_number_groups)
    anchor_count = sum(
        len(group) for group in repeated_number_groups
    )

    layout_type = "unclassified"
    confidence = 0.0

    has_repeated_anchors = anchor_count >= 3

    has_roster_headers = len(roster_header_matches) >= 2

    has_staff_evidence = bool(staff_header_matches)

    # A card layout generally has multiple text lines per
    # player and greater vertical spacing between anchors.
    card_spacing = (
        median_anchor_gap >= median_height * 2.8
    )

    card_density = median_record_lines >= 3

    if (
        group_count >= 2
        and has_repeated_anchors
        and card_spacing
        and card_density
    ):
        layout_type = "player_cards"
        confidence = 0.78

        evidence.append(
            "Multiple repeated jersey-number groups were found."
        )
        evidence.append(
            "Player regions contain several vertically separated text lines."
        )

    elif (
        group_count >= 2
        and has_repeated_anchors
    ):
        layout_type = "multi_column_roster"

        confidence = 0.72

        evidence.append(
            f"{group_count} horizontally separated repeated number groups were found."
        )

        evidence.append(
            f"{alignment_rate:.0%} of cross-column anchor pairs are vertically aligned."
        )

        if alignment_rate >= 0.25:
            confidence += 0.08
            evidence.append(
                "Repeated player anchors show cross-column alignment."
            )

        if has_roster_headers:
            confidence += 0.08
            evidence.append(
                "Recognizable roster headers were found."
            )

        confidence = min(confidence, 0.92)

    elif (
        group_count == 1
        and has_repeated_anchors
        and card_spacing
        and card_density
    ):
        layout_type = "player_cards"
        confidence = 0.78

        evidence.append(
            "One repeated player-number alignment was found."
        )
        evidence.append(
            "Player regions contain multiple text lines and larger vertical gaps."
        )

    elif (
        group_count == 1
        and has_repeated_anchors
        and has_roster_headers
    ):
        layout_type = "traditional_table"
        confidence = 0.90

        evidence.append(
            "One repeated jersey-number column was found."
        )
        evidence.append(
            "Multiple recognizable roster headers were found."
        )

    elif (
        group_count == 1
        and has_repeated_anchors
    ):
        layout_type = "single_column_roster"
        confidence = 0.72

        evidence.append(
            "A repeated jersey-number alignment was found."
        )

    elif has_staff_evidence and not has_repeated_anchors:
        layout_type = "staff_or_non_player"
        confidence = 0.78

        evidence.append(
            "Staff-related headings were found without repeated player-number anchors."
        )

    elif has_roster_headers:
        layout_type = "roster_like_unclassified"
        confidence = 0.55

        evidence.append(
            "Roster-related headers were found, but repeated player boundaries were not."
        )

    else:
        layout_type = "unclassified"
        confidence = 0.35

        evidence.append(
            "The selected region does not contain enough repeated roster structure."
        )

    if not number_words:
        evidence.append(
            "No possible jersey-number tokens were found."
        )
    else:
        evidence.append(
            f"{len(number_words)} possible jersey-number tokens were found."
        )

    if roster_header_matches:
        evidence.append(
            "Roster headers: " + ", ".join(roster_header_matches)
        )

    if staff_header_matches:
        evidence.append(
            "Staff-related terms: " + ", ".join(staff_header_matches)
        )

    return {
        "layout_type": layout_type,
        "confidence": round(confidence, 3),
        "evidence": evidence,
        "metrics": {
            "word_count": len(valid_words),
            "visual_row_count": len(visual_rows),
            "possible_number_count": len(number_words),
            "repeated_number_group_count": group_count,
            "repeated_number_anchor_count": anchor_count,
            "median_text_height": round(median_height, 2),
            "median_anchor_gap": round(median_anchor_gap, 2),
            "median_record_line_count": median_record_lines,
            "cross_column_alignment_rate": round(alignment_rate, 3),
            "roster_headers": roster_header_matches,
            "staff_headers": staff_header_matches,
        },
    }


def segment_roster_records(words, selection_bbox, layout_result):
    """
    Divide a selected roster region into candidate player records.

    Uses repeated jersey-number anchors to identify record positions.
    Multiple anchor groups are treated as separate horizontal columns.

    This function performs structural segmentation only.
    It does not decide which values are names, positions, or measurements.
    """

    sx0, sy0, sx1, sy1 = map(float, selection_bbox)

    valid_words = []

    for original_index, word in enumerate(words):
        bbox = word.get("bbox")

        if not bbox or len(bbox) != 4:
            continue

        try:
            x0, y0, x1, y1 = map(float, bbox)
        except (TypeError, ValueError):
            continue

        if x1 <= x0 or y1 <= y0:
            continue

        text = str(word.get("text", "")).strip()

        if not text:
            continue

        valid_words.append({
            "original_index": original_index,
            "source": word,
            "text": text,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "cx": (x0 + x1) / 2,
            "cy": (y0 + y1) / 2,
        })

    if not valid_words:
        return {
            "records": [],
            "unassigned_words": [],
            "diagnostics": "No usable words were available.",
        }

    heights = sorted(
        item["y1"] - item["y0"]
        for item in valid_words
    )

    median_height = heights[len(heights) // 2]

    # --------------------------------------------------
    # 1. Find possible jersey-number anchors.
    # --------------------------------------------------

    number_candidates = [
        item for item in valid_words
        if re.fullmatch(r"#?\d{1,2}", item["text"])
    ]

    if not number_candidates:
        return {
            "records": [],
            "unassigned_words": [
                item["source"] for item in valid_words
            ],
            "diagnostics": (
                "No possible jersey-number anchors were found."
            ),
        }

    # --------------------------------------------------
    # 2. Group anchors by horizontal alignment.
    # --------------------------------------------------

    x_tolerance = max(
        8.0,
        median_height * 1.5,
    )

    number_groups = []

    for anchor in sorted(
        number_candidates,
        key=lambda item: item["x0"],
    ):
        matching_group = None

        for group in number_groups:
            group_x = sum(
                item["x0"] for item in group
            ) / len(group)

            if abs(anchor["x0"] - group_x) <= x_tolerance:
                matching_group = group
                break

        if matching_group is None:
            number_groups.append([anchor])
        else:
            matching_group.append(anchor)

    # Keep only groups with repeated vertical evidence.
    repeated_groups = []

    for group in number_groups:
        group.sort(key=lambda item: item["cy"])

        unique_anchors = []

        for anchor in group:
            if (
                unique_anchors
                and abs(
                    anchor["cy"] - unique_anchors[-1]["cy"]
                ) <= max(3.0, median_height * 0.7)
            ):
                continue

            unique_anchors.append(anchor)

        if len(unique_anchors) >= 2:
            repeated_groups.append(unique_anchors)

    repeated_groups.sort(
        key=lambda group: sum(
            item["cx"] for item in group
        ) / len(group)
    )

    if not repeated_groups:
        return {
            "records": [],
            "unassigned_words": [
                item["source"] for item in valid_words
            ],
            "diagnostics": (
                "Number-like text was found, but no repeated "
                "jersey-number alignment could be established."
            ),
        }

    # --------------------------------------------------
    # 3. Establish horizontal boundaries.
    # --------------------------------------------------

    group_centers = [
        sum(item["cx"] for item in group) / len(group)
        for group in repeated_groups
    ]

    if len(group_centers) == 1:
        horizontal_bands = [
            (sx0, sx1)
        ]
    else:
        horizontal_bands = [sx0]

        for left_center, right_center in zip(
            group_centers,
            group_centers[1:],
        ):
            horizontal_bands.append(
                (left_center + right_center) / 2
            )

        horizontal_bands.append(sx1)

        horizontal_bands = [
            (horizontal_bands[index], horizontal_bands[index + 1])
            for index in range(len(horizontal_bands) - 1)
        ]

    # --------------------------------------------------
    # 4. Build a vertical record boundary for each anchor.
    # --------------------------------------------------

    records = []
    assigned_indexes = set()

    for group_index, group in enumerate(repeated_groups):

        column_left, column_right = horizontal_bands[group_index]

        group = sorted(
            group,
            key=lambda item: item["cy"],
        )

        for anchor_index, anchor in enumerate(group):

            if anchor_index == 0:
                record_top = sy0
            else:
                record_top = (
                    group[anchor_index - 1]["cy"]
                    + anchor["cy"]
                ) / 2

            if anchor_index == len(group) - 1:
                record_bottom = sy1
            else:
                record_bottom = (
                    anchor["cy"]
                    + group[anchor_index + 1]["cy"]
                ) / 2

            record_items = []

            for item in valid_words:
                if not (
                    column_left <= item["cx"] < column_right
                ):
                    continue

                if not (
                    record_top <= item["cy"] < record_bottom
                ):
                    continue

                record_items.append(item)

            record_items.sort(
                key=lambda item: (
                    item["cy"],
                    item["x0"],
                )
            )

            if not record_items:
                continue

            # ------------------------------------------
            # Reconstruct text lines.
            # ------------------------------------------

            line_groups = {}

            for item in record_items:
                source = item["source"]

                line_key = (
                    source.get("block_number"),
                    source.get("line_number"),
                )

                # If extraction identifiers are unavailable,
                # use a unique key so unrelated words aren't merged.
                if line_key == (None, None):
                    line_key = (
                        "word",
                        item["original_index"],
                    )

                line_groups.setdefault(
                    line_key,
                    [],
                ).append(item)

            reconstructed_lines = []

            for line_items in line_groups.values():
                line_items.sort(
                    key=lambda item: item["x0"]
                )

                reconstructed_lines.append({
                    "x": min(
                        item["x0"] for item in line_items
                    ),
                    "y": min(
                        item["y0"] for item in line_items
                    ),
                    "text": " ".join(
                        item["text"] for item in line_items
                    ),
                    "words": [
                        item["source"] for item in line_items
                    ],
                })

            reconstructed_lines.sort(
                key=lambda item: (
                    item["y"],
                    item["x"],
                )
            )

            entry_text = "\n".join(
                line["text"]
                for line in reconstructed_lines
            )

            # ------------------------------------------
            # Find a possible name on the anchor's line.
            # This is only a candidate, not a final assignment.
            # ------------------------------------------

            same_row_words = [
                item for item in record_items
                if (
                    item["x0"] > anchor["x1"]
                    and abs(item["cy"] - anchor["cy"])
                    <= max(4.0, median_height)
                    and not re.fullmatch(
                        r"[\d#./-]+",
                        item["text"],
                    )
                )
            ]

            same_row_words.sort(
                key=lambda item: item["x0"]
            )

            name_candidate = " ".join(
                item["text"] for item in same_row_words
            )

            record_indexes = {
                item["original_index"]
                for item in record_items
            }

            assigned_indexes.update(record_indexes)

            records.append({
                "record_id": (
                    f"column_{group_index + 1}_"
                    f"record_{anchor_index + 1}"
                ),
                "column_index": group_index + 1,
                "jersey_candidate": anchor["text"].lstrip("#"),
                "name_candidate": name_candidate,
                "entry_text": entry_text,
                "lines": reconstructed_lines,
                "word_count": len(record_items),
                "bbox": [
                    column_left,
                    record_top,
                    column_right,
                    record_bottom,
                ],
                "anchor_bbox": [
                    anchor["x0"],
                    anchor["y0"],
                    anchor["x1"],
                    anchor["y1"],
                ],
            })

    # --------------------------------------------------
    # 5. Preserve words outside candidate records.
    # --------------------------------------------------

    unassigned_words = [
        item["source"]
        for item in valid_words
        if item["original_index"] not in assigned_indexes
    ]

    layout_type = layout_result.get(
        "layout_type",
        "unclassified",
    )

    diagnostics = (
        f"Layout: {layout_type} | "
        f"Anchor groups: {len(repeated_groups)} | "
        f"Candidate records: {len(records)} | "
        f"Unassigned words: {len(unassigned_words)}"
    )

    return {
        "records": records,
        "unassigned_words": unassigned_words,
        "diagnostics": diagnostics,
    }




def analyze_pdf_roster_values(records):
    """
    Analyze candidate roster records and identify possible
    semantic meanings for their extracted text.

    This stage proposes field candidates but does not make
    final field assignments.

    Original text and source-line information are preserved.
    """

    import re

    position_values = {
        "QB", "RB", "FB", "HB", "WR", "TE",
        "C", "G", "OG", "OT", "OL",
        "DL", "DE", "DT", "NT", "EDGE",
        "LB", "MLB", "ILB", "OLB",
        "DB", "CB", "S", "FS", "SS",
        "NICKEL", "NB",
        "K", "PK", "P", "LS", "KR", "PR",
    }

    classification_pattern = re.compile(
        r"^(?:"
        r"FR|FRESHMAN|"
        r"R[- ]?FR|REDSHIRT FRESHMAN|"
        r"SO|SOPH|SOPHOMORE|"
        r"R[- ]?SO|REDSHIRT SOPHOMORE|"
        r"JR|JUNIOR|R[- ]?JR|REDSHIRT JUNIOR|"
        r"SR|SENIOR|R[- ]?SR|REDSHIRT SENIOR|"
        r"GR|GRAD|GRADUATE|"
        r"FIFTH YEAR|5TH YEAR"
        r")\.?$",
        re.IGNORECASE,
    )

    height_pattern = re.compile(
        r"^(?:"
        r"\d{1,2}\s*-\s*\d{1,2}|"
        r"\d{1,2}\s*'\s*\d{1,2}"
        r"(?:\s*(?:\"|''|″))?|"
        r"\d{1,2}\s*ft\.?\s*\d{1,2}"
        r"(?:\s*in\.?)?"
        r")$",
        re.IGNORECASE,
    )

    weight_pattern = re.compile(
        r"^(\d{2,3})\s*(?:lbs?|pounds)$",
        re.IGNORECASE,
    )

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

    school_markers = (
        "high school",
        "academy",
        "university",
        "college",
        "institute",
        "preparatory",
        "prep school",
    )

    def clean(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or "").strip(),
        )

    def classify_value(value):
        """
        Return possible semantic interpretations for one value.
        """

        value = clean(value)

        if not value:
            return []

        candidates = []

        def add(field, confidence, reason):
            candidates.append({
                "field": field,
                "confidence": confidence,
                "reason": reason,
            })

        # Jersey number: require a standalone 1-2 digit value
        # or an explicitly marked number.
        jersey_match = re.fullmatch(
            r"#?(\d{1,2})",
            value,
        )

        if jersey_match:
            add(
                "jersey_number",
                0.95,
                "Standalone one- or two-digit jersey candidate.",
            )

        # Position.
        if value.upper() in position_values:
            add(
                "position",
                0.98,
                "Exact match to a recognized football position.",
            )

        # Height.
        if height_pattern.fullmatch(value):
            add(
                "height",
                0.98,
                "Matches a recognized height format.",
            )

        # Weight.
        weight_match = weight_pattern.fullmatch(value)

        if weight_match:
            weight = int(weight_match.group(1))

            if 130 <= weight <= 450:
                add(
                    "weight",
                    0.98,
                    "Explicit weight unit and plausible football weight.",
                )

        # Unmarked three-digit weights remain candidates,
        # not confirmed assignments.
        elif re.fullmatch(r"\d{3}", value):
            numeric_value = int(value)

            if 130 <= numeric_value <= 450:
                add(
                    "weight",
                    0.65,
                    "Plausible weight range, but no unit is present.",
                )

        # Classification.
        if classification_pattern.fullmatch(value):
            add(
                "classification",
                0.98,
                "Matches a recognized academic classification.",
            )

        # Hometown.
        if "," in value:
            location_suffix = (
                value.rsplit(",", 1)[-1]
                .strip()
                .rstrip(".")
            )

            if (
                location_suffix.upper() in state_abbreviations
                or location_suffix.lower() in state_names
            ):
                add(
                    "hometown",
                    0.90,
                    "Comma-separated location ending in a recognized state.",
                )

        # School-related fields.
        lower_value = value.lower()

        if any(
            marker in lower_value
            for marker in school_markers
        ):
            add(
                "school",
                0.85,
                "Contains a recognizable school or institution marker.",
            )

        # Name candidate.
        words = value.split()

        if (
            2 <= len(words) <= 6
            and re.search(r"[A-Za-z]", value)
            and not re.search(r"\d", value)
            and not candidates
            and not any(
                separator in value
                for separator in ("/", "|", ";")
            )
        ):
            add(
                "full_name",
                0.65,
                "Multi-word alphabetic value; requires further verification.",
            )

        if not candidates:
            add(
                "unclassified",
                0.0,
                "No supported semantic pattern matched this value.",
            )

        return candidates

    analyzed_records = []

    for record in records:

        line_observations = []

        source_lines = record.get("lines", [])

        for line_index, line in enumerate(source_lines):

            text = clean(line.get("text", ""))

            if not text:
                continue

            # A line may contain a jersey number followed
            # by a player's name.
            jersey_and_name = re.match(
                r"^\s*#?(\d{1,2})\s+(.+?)\s*$",
                text,
            )

            values_to_analyze = []

            if jersey_and_name:
                values_to_analyze.append({
                    "text": jersey_and_name.group(1),
                    "source": "leading_number",
                })

                values_to_analyze.append({
                    "text": jersey_and_name.group(2),
                    "source": "remaining_line",
                })
            else:
                values_to_analyze.append({
                    "text": text,
                    "source": "complete_line",
                })

            for value_info in values_to_analyze:

                value = value_info["text"]

                line_observations.append({
                    "line_index": line_index,
                    "source": value_info["source"],
                    "original_text": value,
                    "candidates": classify_value(value),
                    "source_line": line,
                })

        analyzed_records.append({
            "record_id": record.get("record_id"),
            "column_index": record.get("column_index"),
            "jersey_candidate": record.get("jersey_candidate"),
            "name_candidate": record.get("name_candidate"),
            "entry_text": record.get("entry_text", ""),
            "observations": line_observations,
            "original_record": record,
        })

    # Summarize field evidence across the entire selection.
    field_summary = {}

    for analyzed_record in analyzed_records:
        for observation in analyzed_record["observations"]:
            for candidate in observation["candidates"]:

                field = candidate["field"]

                field_summary.setdefault(field, {
                    "candidate_count": 0,
                    "values": [],
                })

                field_summary[field]["candidate_count"] += 1

                field_summary[field]["values"].append({
                    "record_id": analyzed_record["record_id"],
                    "value": observation["original_text"],
                    "confidence": candidate["confidence"],
                })

    return {
        "records": analyzed_records,
        "field_summary": field_summary,
        "record_count": len(analyzed_records),
    }



def resolve_pdf_roster_fields(semantic_result):
    """
    Resolve semantic observations into candidate player fields.

    Each observation can be assigned to at most one field.
    Each field can be assigned at most once per player record.

    Unresolved and competing interpretations are preserved.
    """

    fields = [
        "jersey_number",
        "full_name",
        "position",
        "height",
        "weight",
        "classification",
        "hometown",
        "school",
    ]

    field_priority = {
        field: index
        for index, field in enumerate(fields)
    }

    minimum_confidence = 0.55
    ambiguity_difference = 0.15

    resolved_records = []

    for record in semantic_result.get("records", []):

        observations = record.get("observations", [])

        # Each state represents a combination of fields
        # that have already been assigned.
        #
        # State format:
        # used_mask: (total_score, assignments)

        states = {
            0: (0.0, ())
        }

        # --------------------------------------------------
        # 1. Evaluate each observation.
        # --------------------------------------------------

        for observation_index, observation in enumerate(observations):

            candidates = [
                candidate
                for candidate in observation.get("candidates", [])
                if (
                    candidate.get("field") in field_priority
                    and candidate.get("confidence", 0)
                    >= minimum_confidence
                )
            ]

            next_states = {}

            for used_mask, (total_score, assignments) in states.items():

                # Leaving an observation unresolved is allowed.
                options = [
                    (None, 0.0, used_mask)
                ]

                for candidate in candidates:

                    field = candidate["field"]
                    score = float(candidate["confidence"])

                    field_bit = (
                        1 << field_priority[field]
                    )

                    # A field cannot be assigned twice
                    # within the same player record.
                    if used_mask & field_bit:
                        continue

                    options.append((
                        field,
                        score,
                        used_mask | field_bit,
                    ))

                for field, score, new_mask in options:

                    new_score = total_score + score

                    new_assignments = (
                        assignments + (field,)
                    )

                    existing = next_states.get(new_mask)

                    if (
                        existing is None
                        or new_score > existing[0]
                    ):
                        next_states[new_mask] = (
                            new_score,
                            new_assignments,
                        )

                    elif abs(
                        new_score - existing[0]
                    ) <= 0.000001:

                        new_priority = tuple(
                            field_priority[item]
                            if item is not None else 99
                            for item in new_assignments
                        )

                        existing_priority = tuple(
                            field_priority[item]
                            if item is not None else 99
                            for item in existing[1]
                        )

                        if new_priority < existing_priority:
                            next_states[new_mask] = (
                                new_score,
                                new_assignments,
                            )

            states = next_states

        # --------------------------------------------------
        # 2. Select the strongest non-conflicting assignment.
        # --------------------------------------------------

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
                ),
            ),
        )

        # --------------------------------------------------
        # 3. Build the resolved field dictionary.
        # --------------------------------------------------

        resolved_fields = {}
        unresolved_observations = []
        assigned_observations = []

        for observation_index, observation in enumerate(observations):

            selected_field = best_assignments[observation_index]

            candidates = observation.get("candidates", [])

            if selected_field is None:

                unresolved_observations.append({
                    "text": observation.get("original_text", ""),
                    "line_index": observation.get("line_index"),
                    "source": observation.get("source"),
                    "candidates": candidates,
                    "reason": (
                        "No field was assigned without creating "
                        "a conflict, or no candidate met the "
                        "minimum confidence threshold."
                    ),
                })

                continue

            selected_candidate = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.get("field") == selected_field
                ),
                None,
            )

            if selected_candidate is None:
                continue

            selected_confidence = float(
                selected_candidate.get("confidence", 0)
            )

            # Preserve competing interpretations.
            alternatives = [
                {
                    "field": candidate["field"],
                    "confidence": candidate["confidence"],
                    "reason": candidate.get("reason", ""),
                }
                for candidate in candidates
                if (
                    candidate.get("field") != selected_field
                    and selected_confidence
                    - candidate.get("confidence", 0)
                    < ambiguity_difference
                )
            ]

            assignment = {
                "value": observation.get("original_text", ""),
                "confidence": selected_confidence,
                "status": (
                    "needs_review"
                    if alternatives
                    else "assigned"
                ),
                "source": observation.get("source"),
                "line_index": observation.get("line_index"),
                "reason": selected_candidate.get("reason", ""),
                "alternatives": alternatives,
                "source_line": observation.get("source_line"),
            }

            resolved_fields[selected_field] = assignment

            assigned_observations.append({
                "field": selected_field,
                "value": assignment["value"],
                "confidence": selected_confidence,
            })

        # --------------------------------------------------
        # 4. Determine record-level readiness.
        # --------------------------------------------------

        if not resolved_fields:
            record_status = "unresolved"

        elif any(
            assignment["status"] == "needs_review"
            for assignment in resolved_fields.values()
        ):
            record_status = "needs_review"

        else:
            record_status = "partially_resolved"

        resolved_records.append({
            "record_id": record.get("record_id"),
            "column_index": record.get("column_index"),
            "fields": resolved_fields,
            "assigned_observations": assigned_observations,
            "unresolved_observations": unresolved_observations,
            "status": record_status,
            "original_record": record.get("original_record"),
        })

    # --------------------------------------------------
    # 5. Summarize results across the roster.
    # --------------------------------------------------

    field_summary = {}

    for record in resolved_records:

        for field, assignment in record["fields"].items():

            field_summary.setdefault(field, {
                "assigned_count": 0,
                "review_count": 0,
                "values": [],
            })

            field_summary[field]["assigned_count"] += 1

            if assignment["status"] == "needs_review":
                field_summary[field]["review_count"] += 1

            field_summary[field]["values"].append({
                "record_id": record["record_id"],
                "value": assignment["value"],
                "confidence": assignment["confidence"],
                "status": assignment["status"],
            })

    return {
        "records": resolved_records,
        "field_summary": field_summary,
        "record_count": len(resolved_records),
        "resolved_count": sum(
            bool(record["fields"])
            for record in resolved_records
        ),
        "unresolved_count": sum(
            not record["fields"]
            for record in resolved_records
        ),
    }










def detect_player_entries(words, selection_bbox):
    """
    Identify candidate player entries using repeated number
    positions and vertical record boundaries.

    This is structural detection, not final player recognition.
    """

    sx0, sy0, sx1, sy1 = selection_bbox

    number_candidates = []

    # Step 1: Find possible jersey-number tokens.
    for word in words:
        text = word.get("text", "").strip()
        bbox = word.get("bbox")

        if not bbox or len(bbox) != 4:
            continue

        if not re.fullmatch(r"#?\d{1,2}", text):
            continue

        x0, y0, x1, y1 = map(float, bbox)

        number_candidates.append({
            "text": text.lstrip("#"),
            "x": x0,
            "y": (y0 + y1) / 2,
            "bbox": [x0, y0, x1, y1],
            "word": word,
        })

    if not number_candidates:
        return []

    # Step 2: Group number candidates by horizontal alignment.
    sorted_candidates = sorted(
        number_candidates,
        key=lambda item: item["x"],
    )

    x_groups = []

    for candidate in sorted_candidates:
        matching_group = None

        for group in x_groups:
            group_center = sum(
                item["x"] for item in group
            ) / len(group)

            if abs(candidate["x"] - group_center) <= 10:
                matching_group = group
                break

        if matching_group is None:
            x_groups.append([candidate])
        else:
            matching_group.append(candidate)

    # Prefer the leftmost repeated number column.
    repeated_groups = [
        group for group in x_groups
        if len(group) >= 2
    ]

    if repeated_groups:
        anchor_group = min(
            repeated_groups,
            key=lambda group: min(
                item["x"] for item in group
            ),
        )
    else:
        anchor_group = [
            min(
                number_candidates,
                key=lambda item: item["x"],
            )
        ]

    # Step 3: Sort anchors vertically and remove duplicates.
    anchors = sorted(
        anchor_group,
        key=lambda item: item["y"],
    )

    unique_anchors = []

    for anchor in anchors:
        if (
            unique_anchors
            and abs(
                anchor["y"] - unique_anchors[-1]["y"]
            ) <= 4
        ):
            continue

        unique_anchors.append(anchor)

    anchors = unique_anchors

    if not anchors:
        return []

    records = []

    # Step 4: Divide the selection into candidate record regions.
    for index, anchor in enumerate(anchors):

        if index == 0:
            top = sy0
        else:
            top = (
                anchors[index - 1]["y"] + anchor["y"]
            ) / 2

        if index == len(anchors) - 1:
            bottom = sy1
        else:
            bottom = (
                anchor["y"] + anchors[index + 1]["y"]
            ) / 2

        record_words = []

        for word in words:
            bbox = word.get("bbox")

            if not bbox or len(bbox) != 4:
                continue

            x0, y0, x1, y1 = map(float, bbox)
            center_y = (y0 + y1) / 2

            if top <= center_y < bottom:
                record_words.append(word)

        # Step 5: Reconstruct the text in the candidate record.
        line_groups = {}

        for word in record_words:
            key = (
                word.get("block_number"),
                word.get("line_number"),
            )

            line_groups.setdefault(key, []).append(word)

        reconstructed_lines = []

        for line_words in line_groups.values():
            line_words.sort(
                key=lambda item: item["bbox"][0]
            )

            reconstructed_lines.append({
                "y": min(
                    item["bbox"][1]
                    for item in line_words
                ),
                "x": min(
                    item["bbox"][0]
                    for item in line_words
                ),
                "text": " ".join(
                    item["text"]
                    for item in line_words
                ),
                "words": line_words,
            })

        reconstructed_lines.sort(
            key=lambda item: (
                item["y"],
                item["x"],
            )
        )

        entry_text = "\n".join(
            line["text"]
            for line in reconstructed_lines
        )

        # Step 6: Find the likely player name spatially.
        # Do not require matching PDF block or line identifiers.

        anchor_x = anchor["bbox"][0]
        anchor_y = anchor["y"]

        name_candidates = []

        for word in record_words:
            text = word.get("text", "").strip()
            bbox = word.get("bbox")

            if not text or not bbox or len(bbox) != 4:
                continue

            x0, y0, x1, y1 = map(float, bbox)
            word_center_y = (y0 + y1) / 2

            # Name text should be to the right of the number.
            if x0 <= anchor_x + 12:
                continue

            # Keep text reasonably close to the number vertically.
            if abs(word_center_y - anchor_y) > 30:
                continue

            # Ignore obvious numeric measurements.
            if re.fullmatch(r"[\d#./-]+", text):
                continue

            name_candidates.append({
                "text": text,
                "x": x0,
                "y": word_center_y,
                "bbox": [x0, y0, x1, y1],
            })

        # Sort spatially: top-to-bottom, then left-to-right.
        name_candidates.sort(
            key=lambda item: (
                round(item["y"], 1),
                item["x"],
            )
        )

        # Use the closest text row to the jersey number.
        name_candidate = ""

        if name_candidates:
            closest_y = min(
                name_candidates,
                key=lambda item: abs(
                    item["y"] - anchor_y
                ),
            )["y"]

            closest_row = [
                item for item in name_candidates
                if abs(item["y"] - closest_y) <= 3
            ]

            closest_row.sort(
                key=lambda item: item["x"]
            )

            name_candidate = " ".join(
                item["text"]
                for item in closest_row
            )

        records.append({
            "jersey_candidate": anchor["text"],
            "name_candidate": name_candidate,
            "entry_text": entry_text,
            "word_count": len(record_words),
            "bbox": [sx0, top, sx1, bottom],
        })

    return records



def infer_pdf_columns(words, selection_bbox):
    """
    Reconstruct a roster-like table from selected PDF words.

    Header-based detection is preferred. If recognizable headers
    are unavailable, repeated spatial patterns and value types
    provide conservative fallback mappings.

    All words that cannot be confidently assigned are preserved
    in the unassigned output.
    """

    sx0, sy0, sx1, sy1 = map(float, selection_bbox)

    HEADER_ALIASES = {
        "jersey_number": {
            "#", "no", "number", "jersey", "jersey number",
            "uniform number",
        },
        "full_name": {
            "name", "player", "full name", "player name",
        },
        "position": {
            "pos", "position",
        },
        "height": {
            "height", "ht",
        },
        "weight": {
            "weight", "wt",
        },
        "classification": {
            "class", "classification", "year", "academic year",
            "yr",
        },
        "experience": {
            "experience", "exp",
        },
        "hometown": {
            "hometown", "home town", "home",
        },
        "high_school": {
            "high school", "highschool", "hs", "prep school",
        },
        "previous_school": {
            "previous school", "prev school", "college",
            "previous college", "last school",
        },
        "major": {
            "major", "academic major",
        },
    }

    POSITION_VALUES = {
        "QB", "RB", "FB", "HB", "WR", "TE",
        "C", "G", "OG", "OT", "OL",
        "DL", "DE", "DT", "NT", "EDGE",
        "LB", "MLB", "ILB", "OLB",
        "DB", "CB", "S", "FS", "SS",
        "NICKEL", "NB", "K", "PK", "P", "LS",
        "KR", "PR",
    }

    CLASS_VALUES = {
        "FR", "FRESHMAN", "R-FR", "RFR",
        "SO", "SOPH", "SOPHOMORE", "R-SO", "RSO",
        "JR", "JUNIOR", "R-JR", "RJR",
        "SR", "SENIOR", "R-SR", "RSR",
        "GR", "GRAD", "GRADUATE",
    }

    def normalize(value):
        value = str(value or "").casefold().strip()
        value = re.sub(r"[^a-z0-9#]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    normalized_headers = {}

    for field_name, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            normalized_headers[normalize(alias)] = field_name

    valid_words = []

    for original_index, word in enumerate(words):
        bbox = word.get("bbox")

        if not bbox or len(bbox) != 4:
            continue

        try:
            x0, y0, x1, y1 = map(float, bbox)
        except (TypeError, ValueError):
            continue

        if x1 <= x0 or y1 <= y0:
            continue

        text = str(word.get("text", "")).strip()

        if not text:
            continue

        valid_words.append({
            "source": word,
            "source_index": original_index,
            "text": text,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "cx": (x0 + x1) / 2,
            "cy": (y0 + y1) / 2,
            "height": y1 - y0,
        })

    if not valid_words:
        return {
            "columns": [],
            "records": [],
            "unassigned_text": "",
            "unassigned_words": [],
            "diagnostics": "No usable words were found in the selected region.",
        }

    heights = sorted(item["height"] for item in valid_words)
    median_height = heights[len(heights) // 2]

    row_tolerance = max(2.5, median_height * 0.65)

    # --------------------------------------------------
    # 1. Group words into visual text rows.
    # --------------------------------------------------

    visual_rows = []

    for word in sorted(valid_words, key=lambda item: (item["cy"], item["x0"])):
        matching_row = None

        for row in reversed(visual_rows):
            row_center = sum(item["cy"] for item in row) / len(row)

            if abs(word["cy"] - row_center) <= row_tolerance:
                matching_row = row
                break

            if word["cy"] - row_center > row_tolerance:
                break

        if matching_row is None:
            visual_rows.append([word])
        else:
            matching_row.append(word)

    for row in visual_rows:
        row.sort(key=lambda item: item["x0"])

    # --------------------------------------------------
    # 2. Find recognizable headers.
    # --------------------------------------------------

    header_candidates = []

    for row_index, row in enumerate(visual_rows):
        matches = []

        # Try phrases containing one to four adjacent words.
        for start in range(len(row)):
            for length in range(1, min(4, len(row) - start) + 1):
                phrase_words = row[start:start + length]
                phrase = normalize(
                    " ".join(item["text"] for item in phrase_words)
                )

                field_name = normalized_headers.get(phrase)

                if field_name:
                    matches.append({
                        "field": field_name,
                        "label": " ".join(
                            item["text"] for item in phrase_words
                        ),
                        "left": min(item["x0"] for item in phrase_words),
                        "right": max(item["x1"] for item in phrase_words),
                        "center": sum(item["cx"] for item in phrase_words) / len(phrase_words),
                        "words": phrase_words,
                    })

        # Keep the longest match when phrases overlap.
        matches.sort(
            key=lambda item: (
                item["left"],
                -(item["right"] - item["left"]),
            )
        )

        selected_matches = []
        occupied = set()

        for match in matches:
            indexes = {
                id(item) for item in match["words"]
            }

            if indexes & occupied:
                continue

            selected_matches.append(match)
            occupied.update(indexes)

        unique_fields = {
            item["field"] for item in selected_matches
        }

        if len(unique_fields) >= 2:
            header_candidates.append({
                "row_index": row_index,
                "matches": selected_matches,
                "score": len(unique_fields),
                "y": sum(item["cy"] for item in row) / len(row),
            })

    header_result = None

    if header_candidates:
        header_result = max(
            header_candidates,
            key=lambda item: item["score"],
        )

    # --------------------------------------------------
    # 3. Create semantic columns from header positions.
    # --------------------------------------------------

    columns = []
    header_word_ids = set()

    if header_result:
        header_matches = sorted(
            header_result["matches"],
            key=lambda item: item["center"],
        )

        # A field may only be assigned once.
        unique_matches = []
        used_fields = set()

        for match in header_matches:
            if match["field"] in used_fields:
                continue

            unique_matches.append(match)
            used_fields.add(match["field"])

            for word in match["words"]:
                header_word_ids.add(id(word))

        for index, match in enumerate(unique_matches):
            left = (
                sx0
                if index == 0
                else (
                    unique_matches[index - 1]["center"]
                    + match["center"]
                ) / 2
            )

            right = (
                sx1
                if index == len(unique_matches) - 1
                else (
                    match["center"]
                    + unique_matches[index + 1]["center"]
                ) / 2
            )

            columns.append({
                "field": match["field"],
                "label": match["label"],
                "left": left,
                "right": right,
                "confidence": 0.98,
                "source": "header",
            })

        header_y = header_result["y"]

    else:
        header_y = None

    # --------------------------------------------------
    # 4. Headerless fallback: infer repeated spatial bands.
    # --------------------------------------------------

    if not columns:
        gap_observations = []

        for row_index, row in enumerate(visual_rows):
            for left_word, right_word in zip(row, row[1:]):
                gap = right_word["x0"] - left_word["x1"]

                if gap >= max(7.0, median_height * 1.4):
                    gap_observations.append({
                        "x": (left_word["x1"] + right_word["x0"]) / 2,
                        "row": row_index,
                        "gap": gap,
                    })

        gap_observations.sort(key=lambda item: item["x"])
        clusters = []

        cluster_tolerance = max(5.0, median_height * 1.5)

        for observation in gap_observations:
            matching_cluster = None

            for cluster in reversed(clusters):
                center = sum(item["x"] for item in cluster) / len(cluster)

                if abs(observation["x"] - center) <= cluster_tolerance:
                    matching_cluster = cluster
                    break

                if center < observation["x"] - cluster_tolerance:
                    break

            if matching_cluster is None:
                clusters.append([observation])
            else:
                matching_cluster.append(observation)

        minimum_support = max(
            2,
            int(len(visual_rows) * 0.12 + 0.999),
        )

        boundaries = []

        for cluster in clusters:
            support = len({item["row"] for item in cluster})

            if support < minimum_support:
                continue

            positions = sorted(item["x"] for item in cluster)
            boundaries.append(positions[len(positions) // 2])

        boundaries.sort()

        # Remove boundaries that are too close together.
        cleaned_boundaries = []

        for boundary in boundaries:
            if (
                not cleaned_boundaries
                or boundary - cleaned_boundaries[-1]
                > max(12.0, median_height * 2)
            ):
                cleaned_boundaries.append(boundary)

        edges = [sx0] + cleaned_boundaries + [sx1]

        fallback_columns = []

        for index in range(len(edges) - 1):
            left = edges[index]
            right = edges[index + 1]

            band_words = [
                item for item in valid_words
                if left <= item["cx"] < right
            ]

            if not band_words:
                continue

            values = [item["text"].strip() for item in band_words]
            normalized_values = [value.upper() for value in values]

            number_count = sum(
                bool(re.fullmatch(r"#?\d{1,2}", value))
                for value in values
            )

            position_count = sum(
                value in POSITION_VALUES
                for value in normalized_values
            )

            height_count = sum(
                bool(re.fullmatch(r"\d{1,2}-\d{1,2}", value))
                for value in values
            )

            weight_count = sum(
                bool(re.fullmatch(r"\d{2,3}", value))
                for value in values
            )

            class_count = sum(
                value in CLASS_VALUES
                for value in normalized_values
            )

            name_like_count = sum(
                len(value.split()) >= 2
                and bool(re.search(r"[A-Za-z]", value))
                for value in values
            )

            total = max(1, len(values))

            scores = {
                "jersey_number": number_count / total,
                "position": position_count / total,
                "height": height_count / total,
                "weight": weight_count / total,
                "classification": class_count / total,
                "full_name": name_like_count / total,
            }

            best_field = max(scores, key=scores.get)
            best_score = scores[best_field]

            # Conservative thresholds. Ambiguous bands stay unassigned.
            thresholds = {
                "jersey_number": 0.45,
                "position": 0.35,
                "height": 0.35,
                "weight": 0.45,
                "classification": 0.35,
                "full_name": 0.35,
            }

            candidate_scores = {
                field: score
                for field, score in scores.items()
                if score >= thresholds[field]
            }

            if candidate_scores:
                fallback_columns.append({
                    "left": left,
                    "right": right,
                    "candidate_scores": candidate_scores,
                })

        # --------------------------------------------------
        # Globally assign fields across all inferred columns.
        # A field can only be assigned once.
        # Leaving a column unassigned is always allowed.
        # --------------------------------------------------

        field_order = [
            "jersey_number",
            "full_name",
            "position",
            "height",
            "weight",
            "classification",
        ]

        field_priority = {
            field: index
            for index, field in enumerate(field_order)
        }

        states = {
            0: (0.0, ())
        }

        for band in fallback_columns:
            next_states = {}

            for used_mask, (total_score, assignments) in states.items():

                options = [
                    (None, 0.0, used_mask)
                ]

                for field, score in band["candidate_scores"].items():
                    field_bit = 1 << field_priority[field]

                    if used_mask & field_bit:
                        continue

                    options.append((
                        field,
                        score,
                        used_mask | field_bit,
                    ))

                for field, score, new_mask in options:
                    new_score = total_score + score
                    new_assignments = assignments + (field,)

                    existing = next_states.get(new_mask)

                    if (
                        existing is None
                        or new_score > existing[0]
                    ):
                        next_states[new_mask] = (
                            new_score,
                            new_assignments,
                        )

            states = next_states

        best_score, best_assignments = max(
            states.values(),
            key=lambda result: result[0],
        )

        for band, selected_field in zip(
            fallback_columns,
            best_assignments,
        ):
            if selected_field is None:
                continue

            selected_score = band["candidate_scores"][selected_field]

            columns.append({
                "field": selected_field,
                "label": selected_field.replace("_", " ").title(),
                "left": band["left"],
                "right": band["right"],
                "confidence": min(
                    0.85,
                    0.50 + selected_score * 0.35,
                ),
                "source": "pattern",
                "candidate_scores": band["candidate_scores"],
            })

        columns.sort(
            key=lambda item: item["left"]
        )

    # --------------------------------------------------
    # 5. Identify repeated jersey-number anchors.
    # --------------------------------------------------

    number_candidates = []

    for word in valid_words:
        if not re.fullmatch(r"#?\d{1,2}", word["text"]):
            continue

        if header_y is not None and word["cy"] <= header_y:
            continue

        number_candidates.append(word)

    x_groups = []

    for word in sorted(number_candidates, key=lambda item: item["x0"]):
        group = None

        for candidate_group in x_groups:
            center = sum(item["x0"] for item in candidate_group) / len(candidate_group)

            if abs(word["x0"] - center) <= max(8.0, median_height * 1.5):
                group = candidate_group
                break

        if group is None:
            x_groups.append([word])
        else:
            group.append(word)

    repeated_groups = [
        group for group in x_groups
        if len(group) >= 2
    ]

    anchors = []

    if repeated_groups:
        # Prefer the leftmost repeated numeric column.
        anchor_group = min(
            repeated_groups,
            key=lambda group: min(item["x0"] for item in group),
        )

        for word in sorted(anchor_group, key=lambda item: item["cy"]):
            if (
                anchors
                and abs(word["cy"] - anchors[-1]["cy"])
                <= max(3.0, median_height * 0.7)
            ):
                continue

            anchors.append(word)

    # --------------------------------------------------
    # 6. Build player records from anchor-to-anchor regions.
    # --------------------------------------------------

    records = []
    assigned_word_ids = set(header_word_ids)

    if anchors:
        for index, anchor in enumerate(anchors):
            top = (
                sy0
                if index == 0
                else (anchors[index - 1]["cy"] + anchor["cy"]) / 2
            )

            bottom = (
                sy1
                if index == len(anchors) - 1
                else (anchor["cy"] + anchors[index + 1]["cy"]) / 2
            )

            record_words = [
                word for word in valid_words
                if top <= word["cy"] < bottom
                and (header_y is None or word["cy"] > header_y)
            ]

            record = {
                column["field"]: ""
                for column in columns
            }

            record["_source_bbox"] = [sx0, top, sx1, bottom]

            for column in columns:
                cell_words = [
                    word for word in record_words
                    if column["left"] <= word["cx"] < column["right"]
                ]

                cell_words.sort(
                    key=lambda item: (item["cy"], item["x0"])
                )

                cell_lines = []
                current_line = []
                current_y = None

                for word in cell_words:
                    if (
                        current_y is None
                        or abs(word["cy"] - current_y) <= row_tolerance
                    ):
                        current_line.append(word)
                        current_y = (
                            word["cy"]
                            if current_y is None
                            else (current_y + word["cy"]) / 2
                        )
                    else:
                        cell_lines.append(" ".join(
                            item["text"] for item in current_line
                        ))
                        current_line = [word]
                        current_y = word["cy"]

                if current_line:
                    cell_lines.append(" ".join(
                        item["text"] for item in current_line
                    ))

                value = " ".join(
                    line.strip() for line in cell_lines if line.strip()
                ).strip()

                record[column["field"]] = value

                if column["confidence"] >= 0.60:
                    assigned_word_ids.update(
                        id(word) for word in cell_words
                    )

            # Ensure the detected jersey anchor is retained.
            if "jersey_number" in record and not record["jersey_number"]:
                record["jersey_number"] = anchor["text"].lstrip("#")
                assigned_word_ids.add(id(anchor))

            if any(
                str(record.get(column["field"], "")).strip()
                for column in columns
            ):
                records.append(record)

    # --------------------------------------------------
    # 7. Preserve everything that was not confidently assigned.
    # --------------------------------------------------

    unassigned_words = [
        word for word in valid_words
        if id(word) not in assigned_word_ids
    ]

    unassigned_words.sort(
        key=lambda item: (item["cy"], item["x0"])
    )

    unassigned_lines = []

    for word in unassigned_words:
        if (
            not unassigned_lines
            or abs(word["cy"] - unassigned_lines[-1]["cy"]) > row_tolerance
        ):
            unassigned_lines.append({
                "cy": word["cy"],
                "words": [word],
            })
        else:
            unassigned_lines[-1]["words"].append(word)

    unassigned_text = "\n".join(
        " ".join(
            item["text"]
            for item in sorted(line["words"], key=lambda item: item["x0"])
        )
        for line in unassigned_lines
    )

    confident_columns = [
        column for column in columns
        if column["confidence"] >= 0.60
    ]

    diagnostics = (
        f"{len(valid_words)} words | "
        f"{len(visual_rows)} visual rows | "
        f"{'Header-based' if header_result else 'Headerless fallback'} | "
        f"{len(confident_columns)} confident fields | "
        f"{len(records)} candidate records | "
        f"{len(unassigned_words)} unassigned words"
    )

    return {
        "columns": columns,
        "records": records,
        "unassigned_text": unassigned_text,
        "unassigned_words": unassigned_words,
        "diagnostics": diagnostics,
        "header_detected": header_result is not None,
    }



class CopyableTableWidget(QTableWidget):
    """Read-only table that supports copying selected cells with Ctrl+C."""

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_C
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            indexes = self.selectedIndexes()

            if indexes:
                indexes = sorted(
                    indexes,
                    key=lambda item: (item.row(), item.column()),
                )

                selected_rows = sorted({
                    item.row() for item in indexes
                })

                selected_columns = sorted({
                    item.column() for item in indexes
                })

                selected_cells = {
                    (item.row(), item.column())
                    for item in indexes
                }

                lines = []

                for row in selected_rows:
                    values = []

                    for column in selected_columns:
                        if (row, column) not in selected_cells:
                            values.append("")
                            continue

                        item = self.item(row, column)
                        values.append(item.text() if item else "")

                    lines.append("\t".join(values))

                QApplication.clipboard().setText(
                    "\n".join(lines)
                )

                event.accept()
                return

        super().keyPressEvent(event)





class PDFAnalysisWorker(QThread):
    """Runs PDF analysis without freezing the interface."""

    progress = Signal(int, int, str)
    result_ready = Signal(str, object)
    error_ready = Signal(str, str)

    def __init__(self, pdf_paths):
        super().__init__()
        self.pdf_paths = list(pdf_paths)

    def run(self):
        total = len(self.pdf_paths)

        for index, pdf_path in enumerate(self.pdf_paths, start=1):
            filename = Path(pdf_path).name

            self.progress.emit(index, total, filename)

            try:
                result = analyze_pdf_structure(pdf_path)
                self.result_ready.emit(pdf_path, result)

            except Exception:
                error_details = traceback.format_exc()
                self.error_ready.emit(pdf_path, error_details)



class SelectableGraphicsView(QGraphicsView):
    """Graphics view supporting optional rectangular selection."""

    region_selected = Signal(object)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)

        self.selection_mode = False
        self.selection_origin = None
        self.selection_rectangle = None

        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )

    def set_selection_mode(self, enabled):
        self.selection_mode = enabled

        if enabled:
            self.setDragMode(
                QGraphicsView.DragMode.NoDrag
            )
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(
                QGraphicsView.DragMode.ScrollHandDrag
            )
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if (
            self.selection_mode
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.selection_origin = self.mapToScene(
                event.position().toPoint()
            )

            if self.selection_rectangle:
                self.scene().removeItem(
                    self.selection_rectangle
                )
                self.selection_rectangle = None

            return

        super().mousePressEvent(event)


    def reset_selection(self):
        """Clear any active or previously drawn selection."""

        self.selection_origin = None
        self.selection_rectangle = None

    def mouseMoveEvent(self, event):
        if self.selection_mode and self.selection_origin:
            current_position = self.mapToScene(
                event.position().toPoint()
            )

            rectangle = QRectF(
                self.selection_origin,
                current_position,
            ).normalized()

            if self.selection_rectangle is None:
                self.selection_rectangle = self.scene().addRect(
                    rectangle,
                    QPen(QColor("#facc15"), 2),
                    QBrush(QColor(250, 204, 21, 35)),
                )
            else:
                self.selection_rectangle.setRect(rectangle)

            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self.selection_mode
            and event.button() == Qt.MouseButton.LeftButton
            and self.selection_origin is not None
        ):
            current_position = self.mapToScene(
                event.position().toPoint()
            )

            rectangle = QRectF(
                self.selection_origin,
                current_position,
            ).normalized()

            self.selection_origin = None

            if rectangle.width() > 3 and rectangle.height() > 3:
                self.region_selected.emit(rectangle)

            return

        super().mouseReleaseEvent(event)




class PDFVisualInspector(QDialog):
    """Display PDF pages, detected structures, and selected-region text."""

    RENDER_SCALE = 1.5

    OVERLAY_STYLES = {
        "tables": ("#16a34a", "Tables"),
        "containers": ("#2563eb", "Containers"),
        "separator_regions": ("#d97706", "Separator regions"),
        "text_regions": ("#9333ea", "Text regions"),
        "unassigned_text": ("#dc2626", "Unassigned text"),
    }

    def __init__(self, analysis_results, parent=None):
        super().__init__(parent)

        self.analysis_results = analysis_results
        self.current_path = None
        self.current_page_number = None

        # Original word-level extraction data for the current page.
        self.current_page_words = []

        # Structured information from the most recent selection.
        self.selected_region_data = None

        self.setWindowTitle("PDF Visual Inspector")
        self.resize(1250, 950)

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # --------------------------------------------------
        # DOCUMENT AND PAGE CONTROLS
        # --------------------------------------------------

        controls = QHBoxLayout()

        self.document_selector = QComboBox()

        for path, result in self.analysis_results.items():
            self.document_selector.addItem(
                result.get("file_name", Path(path).name),
                path,
            )

        self.page_selector = QSpinBox()
        self.page_selector.setMinimum(1)
        self.page_selector.setMaximum(1)

        controls.addWidget(QLabel("Document:"))
        controls.addWidget(self.document_selector, stretch=1)
        controls.addWidget(QLabel("Page:"))
        controls.addWidget(self.page_selector)

        # --------------------------------------------------
        # PDF VIEWER
        # --------------------------------------------------

        self.scene = QGraphicsScene(self)

        self.page_view = SelectableGraphicsView(self.scene)

        self.page_view.region_selected.connect(
            self.handle_region_selected
        )

        self.page_view.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        self.page_view.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )

        # --------------------------------------------------
        # REGION SELECTION
        # --------------------------------------------------

        self.select_region_button = QPushButton(
            "Select Region"
        )

        self.select_region_button.setCheckable(True)

        self.select_region_button.toggled.connect(
            self.page_view.set_selection_mode
        )

        controls.addWidget(self.select_region_button)

        layout.addLayout(controls)

        # --------------------------------------------------
        # DETECTION LEGEND
        # --------------------------------------------------

        self.legend_label = QLabel(
            "Green: Tables | Blue: Containers | "
            "Orange: Separator regions | "
            "Purple: Text regions | Red: Unassigned text"
        )

        layout.addWidget(self.legend_label)

        self.region_info_label = QLabel(
            "Select a region to reconstruct its roster fields."
        )

        layout.addWidget(self.region_info_label)

        # --------------------------------------------------
        # SIDE-BY-SIDE WORKSPACE
        # --------------------------------------------------

        from PySide6.QtWidgets import QSplitter, QHeaderView

        self.workspace_splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        # Left: PDF viewer.
        self.workspace_splitter.addWidget(self.page_view)

        # Right: reconstructed roster and unassigned content.
        self.results_panel = QWidget()
        results_layout = QVBoxLayout(self.results_panel)
        results_layout.setContentsMargins(6, 6, 6, 6)

        roster_heading = QLabel("Automatically Reconstructed Roster")
        results_layout.addWidget(roster_heading)

        self.column_info_label = QLabel(
            "Select a PDF region to detect roster fields."
        )

        self.column_info_label.setWordWrap(True)
        results_layout.addWidget(self.column_info_label)

        self.roster_table = CopyableTableWidget()
        self.roster_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.roster_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.roster_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self.roster_table.setWordWrap(True)
        self.roster_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.roster_table.horizontalHeader().setStretchLastSection(True)

        results_layout.addWidget(self.roster_table, stretch=3)

        unassigned_heading = QLabel(
            "Unassigned / Uncertain Content"
        )

        results_layout.addWidget(unassigned_heading)

        self.unassigned_output = QPlainTextEdit()
        self.unassigned_output.setReadOnly(True)
        self.unassigned_output.setPlaceholderText(
            "Content that could not be confidently assigned "
            "to a roster field will appear here."
        )

        results_layout.addWidget(
            self.unassigned_output,
            stretch=1,
        )

        self.workspace_splitter.addWidget(
            self.results_panel
        )

        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([600, 600])

        layout.addWidget(
            self.workspace_splitter,
            stretch=1,
        )

        # --------------------------------------------------
        # SIGNALS
        # --------------------------------------------------

        self.document_selector.currentIndexChanged.connect(
            self.load_document
        )

        self.page_selector.valueChanged.connect(
            self.load_page
        )

        # --------------------------------------------------
        # INITIAL DOCUMENT
        # --------------------------------------------------

        if self.document_selector.count():
            self.load_document(0)

    def showEvent(self, event):
        """Fit the PDF after the dialog becomes visible."""

        super().showEvent(event)

        QTimer.singleShot(
            0,
            self.fit_page_to_view,
        )

    # ======================================================
    # PAGE DISPLAY
    # ======================================================

    def fit_page_to_view(self):
        """Fit the current PDF page inside the available viewport."""

        scene_rect = self.scene.sceneRect()

        if scene_rect.isNull() or scene_rect.isEmpty():
            return

        self.page_view.fitInView(
            scene_rect,
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def load_document(self, index):
        if index < 0:
            return

        path = self.document_selector.itemData(index)

        if not path:
            return

        result = self.analysis_results.get(path)

        if not result:
            return

        self.current_path = path

        page_count = result.get("page_count", 0)

        self.page_selector.blockSignals(True)

        self.page_selector.setRange(
            1,
            max(1, page_count),
        )

        self.page_selector.setValue(1)

        self.page_selector.blockSignals(False)

        self.load_page(1)

    def load_page(self, page_number):
        if not self.current_path:
            return

        result = self.analysis_results.get(
            self.current_path
        )

        if not result:
            return

        pages = result.get("pages", [])

        if not 1 <= page_number <= len(pages):
            return

        try:
            with pymupdf.open(self.current_path) as document:

                pdf_page = document[page_number - 1]

                # ------------------------------------------
                # RENDER PDF PAGE
                # ------------------------------------------

                pixmap = pdf_page.get_pixmap(
                    matrix=pymupdf.Matrix(
                        self.RENDER_SCALE,
                        self.RENDER_SCALE,
                    ),
                    alpha=False,
                )

                image = QPixmap()
                image.loadFromData(pixmap.tobytes("png"))

                if image.isNull():
                    raise RuntimeError(
                        "Could not render the selected PDF page."
                    )

                # ------------------------------------------
                # EXTRACT ORIGINAL WORD DATA
                # ------------------------------------------

                self.current_page_words = extract_page_words(
                    pdf_page
                )

                self.current_page_number = page_number

                # ------------------------------------------
                # RESET PREVIOUS SELECTION
                # ------------------------------------------

                self.page_view.reset_selection()

                self.select_region_button.setChecked(False)

                self.selected_region_data = None

                self.region_info_label.setText(
                    "Select a region to extract its text."
                )

                self.roster_table.clear()
                self.roster_table.setRowCount(0)
                self.roster_table.setColumnCount(0)

                self.unassigned_output.clear()

                self.column_info_label.setText(
                    "Select a region to detect roster fields."
                )

                # ------------------------------------------
                # REBUILD SCENE
                # ------------------------------------------

                self.scene.clear()

                page_item = self.scene.addPixmap(image)

                # Convert rendered pixels back into PDF-point
                # coordinates so overlays match analyzer bboxes.

                page_item.setScale(
                    1.0 / self.RENDER_SCALE
                )

                self.draw_overlays(
                    pages[page_number - 1]
                )

                self.scene.setSceneRect(
                    page_item.sceneBoundingRect()
                )

                self.page_view.fitInView(
                    self.scene.sceneRect(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )

                self.legend_label.setText(
                    "Green: Tables | Blue: Containers | "
                    "Orange: Separator regions | "
                    "Purple: Text regions | Red: Unassigned text"
                )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Page Rendering Error",
                str(error),
            )

    # ======================================================
    # MANUAL REGION EXTRACTION
    # ======================================================

    def handle_region_selected(self, rectangle):
        """
        Extract a selected PDF region and reconstruct its roster data.

        Original extracted words remain available for later review,
        layout analysis, record segmentation, and semantic mapping.
        """

        selection_bbox = [
            rectangle.left(),
            rectangle.top(),
            rectangle.right(),
            rectangle.bottom(),
        ]

        sx0, sy0, sx1, sy1 = selection_bbox

        selected_words = []

    # --------------------------------------------------
    # 1. Extract words intersecting the selected region.
    # --------------------------------------------------

        for word in self.current_page_words:
            bbox = word.get("bbox")

            if not bbox or len(bbox) != 4:
                continue

            try:
                x0, y0, x1, y1 = map(float, bbox)
            except (TypeError, ValueError):
                continue

            intersects = not (
                x1 <= sx0
                or x0 >= sx1
                or y1 <= sy0
                or y0 >= sy1
            )

            if intersects:
                selected_words.append(word)

    # --------------------------------------------------
    # 2. Preserve and reconstruct the original text.
    # --------------------------------------------------

        line_groups = {}

        for word in selected_words:
            line_key = (
                word.get("block_number"),
                word.get("line_number"),
            )

            line_groups.setdefault(line_key, []).append(word)

        reconstructed_lines = []

        for line_key, line_words in line_groups.items():
            line_words.sort(
                key=lambda item: item.get("word_number", 0)
            )

            reconstructed_lines.append({
                "block_number": line_key[0],
                "line_number": line_key[1],
                "text": " ".join(
                    item["text"] for item in line_words
                ),
                "words": line_words,
                "y": min(
                    item["bbox"][1] for item in line_words
                ),
                "x": min(
                    item["bbox"][0] for item in line_words
                ),
            })

        reconstructed_lines.sort(
            key=lambda item: (item["y"], item["x"])
        )

        extracted_text = "\n".join(
            line["text"] for line in reconstructed_lines
        )

        self.selected_region_data = {
            "file_path": self.current_path,
            "page_number": self.current_page_number,
            "selection_bbox": selection_bbox,
            "word_count": len(selected_words),
            "line_count": len(reconstructed_lines),
            "text": extracted_text,
            "words": selected_words,
            "lines": reconstructed_lines,
     }

    # --------------------------------------------------
    # 3. Classify the selected region's layout.
    # --------------------------------------------------

        layout_result = classify_roster_layout(
            selected_words,
            selection_bbox,
        )

        self.selected_region_data["layout_analysis"] = (
            layout_result
        )

    # --------------------------------------------------
    # 4. Segment the region into candidate records.
    # --------------------------------------------------

        segmentation_result = segment_roster_records(
            selected_words,
            selection_bbox,
            layout_result,
        )

        self.selected_region_data["segmentation"] = (
            segmentation_result
        )

        player_entries = segmentation_result.get(
            "records",
            [],
        )

        self.selected_region_data["player_entries"] = (
            player_entries
        )

        # --------------------------------------------------
# SEMANTIC ANALYSIS OF CANDIDATE RECORDS
# --------------------------------------------------

        # --------------------------------------------------
# RECONSTRUCT SPATIAL PDF CELLS
# --------------------------------------------------

        cell_reconstruction = reconstruct_pdf_roster_cells(
            player_entries,
            layout_result,
        )

        self.selected_region_data["cell_reconstruction"] = (
            cell_reconstruction
)

        semantic_input_records = cell_reconstruction.get(
            "records",
            player_entries,
        )


# --------------------------------------------------
# ANALYZE RECONSTRUCTED CELL VALUES
# --------------------------------------------------

        semantic_result = analyze_pdf_roster_values(
            semantic_input_records
        )

        self.selected_region_data["semantic_analysis"] = (
            semantic_result
        )

# --------------------------------------------------
# RESOLVE CANDIDATE ROSTER FIELDS
# --------------------------------------------------

        field_resolution = resolve_pdf_roster_fields(
            semantic_result
            )

        self.selected_region_data["field_resolution"] = (
            field_resolution
                )

# --------------------------------------------------
# RESOLVE CANDIDATE ROSTER FIELDS
# --------------------------------------------------

        field_resolution = resolve_pdf_roster_fields(
            semantic_result
        )

        self.selected_region_data["field_resolution"] = (
            field_resolution
            )

    # --------------------------------------------------
    # 5. Populate the candidate player-entry table.
    # --------------------------------------------------

        # --------------------------------------------------
# DISPLAY RECONSTRUCTED PLAYER RECORDS
# --------------------------------------------------

        reconstructed_records = cell_reconstruction.get(
            "records",
                [],
                )

        self.roster_table.clear()
        self.roster_table.setRowCount(len(player_entries))
        self.roster_table.setColumnCount(5)

        self.roster_table.setHorizontalHeaderLabels([
        "Jersey Candidate",
    "Name Candidate",
    "Reconstructed Cells",
    "Original Entry Text",
    "Word Count",
])

        for row_index, record in enumerate(player_entries):

            reconstructed_record = (
                reconstructed_records[row_index]
                if row_index < len(reconstructed_records)
                else {}
            )

            cells = reconstructed_record.get("cells", [])

            cell_summary = "\n".join(
        (
            f"Column {cell['column_index'] + 1}: "
            f"{cell['text'].replace(chr(10), ' / ')}"
        )
            for cell in cells
                if cell.get("text")
            )

            values = [
                record.get("jersey_candidate", ""),
                record.get("name_candidate", ""),
                cell_summary,
                record.get("entry_text", ""),
                str(record.get("word_count", 0)),
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))

                item.setToolTip(
                    f"Record ID: {record.get('record_id', '')}\n"
                    f"Column: {record.get('column_index', '')}\n"
                    f"Record boundaries: {record.get('bbox', [])}"
                )

                self.roster_table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        self.roster_table.resizeRowsToContents()
        self.roster_table.resizeColumnsToContents()
    # --------------------------------------------------
    # 6. Preserve unresolved content.
    # --------------------------------------------------

        unassigned_words = segmentation_result.get(
            "unassigned_words",
            [],
        )

        unassigned_lines = {}

        for word in unassigned_words:
            line_key = (
                word.get("block_number"),
                word.get("line_number"),
            )

            unassigned_lines.setdefault(
                line_key,
                [],
            ).append(word)

        unresolved_text = []

        for line_words in unassigned_lines.values():
            line_words.sort(
                key=lambda item: item.get("word_number", 0)
            )

            unresolved_text.append(
             " ".join(
                    item.get("text", "")
                    for item in line_words
                )
            )

        self.unassigned_output.setPlainText(
            "\n".join(unresolved_text)
        )

    # --------------------------------------------------
    # 7. Update layout and segmentation diagnostics.
    # --------------------------------------------------

        layout_type = layout_result.get(
            "layout_type",
            "unclassified",
        )

        layout_confidence = layout_result.get(
            "confidence",
            0,
        )

        segmentation_diagnostics = segmentation_result.get(
            "diagnostics",
            "No segmentation diagnostics available.",
        )

        cell_diagnostics = cell_reconstruction.get(
    "diagnostics",
    {},
)

        layout_summary = (
            f"Layout: {layout_type.replace('_', ' ').title()} "
            f"({layout_confidence:.0%} confidence)\n"
    f"Candidate records: {len(player_entries)}\n"
    f"Inferred columns: "
    f"{cell_diagnostics.get('column_count', 0)}\n"
    f"{cell_diagnostics.get('reason', '')}\n"
    f"{segmentation_diagnostics}"
)
        self.column_info_label.setText(
            layout_summary
        )

        self.column_info_label.setToolTip(
            "\n".join(
                layout_result.get("evidence", [])
            )
        )

    # --------------------------------------------------
    # 8. Update selected-region information.
    # --------------------------------------------------

        self.region_info_label.setText(
            f"Page {self.current_page_number} | "
            f"{len(selected_words)} words extracted | "
            f"{len(reconstructed_lines)} source lines | "
            f"{len(player_entries)} candidate records | "
            f"Selected region: "
            f"X={sx0:.1f}, Y={sy0:.1f}, "
            f"Width={sx1 - sx0:.1f}, "
            f"Height={sy1 - sy0:.1f}"
        )

    # ======================================================
    # AUTOMATIC STRUCTURE OVERLAYS
    # ======================================================

    def draw_overlays(self, page_data):
        """Draw detected structures over the rendered PDF page."""

        for category, style in self.OVERLAY_STYLES.items():

            color_hex, _label = style

            items = page_data.get(category, [])

            for item in items:

                bbox = item.get("bbox")

                if not bbox or len(bbox) != 4:
                    continue

                try:
                    x0, y0, x1, y1 = map(float, bbox)

                except (TypeError, ValueError):
                    continue

                if x1 <= x0 or y1 <= y0:
                    continue

                color = QColor(color_hex)

                pen = QPen(color, 1.5)

                if category == "unassigned_text":
                    pen.setStyle(
                        Qt.PenStyle.DashLine
                    )

                brush = QBrush(
                    QColor(
                        color.red(),
                        color.green(),
                        color.blue(),
                        28,
                    )
                )

                rectangle = self.scene.addRect(
                    x0,
                    y0,
                    x1 - x0,
                    y1 - y0,
                    pen,
                    brush,
                )

                rectangle.setToolTip(
                    item.get("text", category)
                )





class PDFAnalysisTestWindow(QMainWindow):
    """Standalone interface for testing the universal PDF analyzer."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Universal PDF Analysis - Test Workspace")
        self.resize(1200, 800)

        self.worker = None
        self.analysis_summaries = []
        self.analysis_results = {}

        self.setup_ui()

    # ======================================================
    # USER INTERFACE
    # ======================================================

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        # --------------------------------------------------
        # HEADER
        # --------------------------------------------------

        title = QLabel("Universal PDF Analysis")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold;"
        )

        subtitle = QLabel(
            "Select multiple PDF documents and evaluate "
            "the structural analysis engine."
        )
        subtitle.setStyleSheet("color: #888888;")

        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        # --------------------------------------------------
        # FILE SELECTION
        # --------------------------------------------------

        file_header = QHBoxLayout()

        file_label = QLabel("Selected PDF Documents")
        file_label.setStyleSheet(
            "font-size: 15px; font-weight: bold;"
        )

        file_header.addWidget(file_label)
        file_header.addStretch()

        self.add_button = QPushButton("Add PDFs")
        self.add_button.clicked.connect(self.add_pdfs)

        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_selected)

        self.clear_button = QPushButton("Clear All")
        self.clear_button.clicked.connect(self.clear_files)

        file_header.addWidget(self.add_button)
        file_header.addWidget(self.remove_button)
        file_header.addWidget(self.clear_button)

        main_layout.addLayout(file_header)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.file_list.setMinimumHeight(140)

        main_layout.addWidget(self.file_list)

        self.file_count_label = QLabel("0 documents selected")
        self.file_count_label.setStyleSheet("color: #888888;")

        main_layout.addWidget(self.file_count_label)

        # --------------------------------------------------
        # ANALYSIS CONTROLS
        # --------------------------------------------------

        control_layout = QHBoxLayout()

        self.analyze_button = QPushButton("Analyze PDFs")
        self.analyze_button.setMinimumHeight(38)

        self.analyze_button.setStyleSheet(
            """
            QPushButton {
                background-color: #2463a6;
                color: white;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 5px;
            }

            QPushButton:disabled {
                background-color: #555555;
            }
            """
        )

        self.analyze_button.clicked.connect(self.start_analysis)

        self.status_label = QLabel("Ready")

        control_layout.addWidget(self.analyze_button)
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()
        self.inspect_button = QPushButton(
    "Open Visual Inspector"
)

        self.inspect_button.setEnabled(False)

        self.inspect_button.clicked.connect(
            self.open_visual_inspector
            )

        control_layout.addWidget(self.inspect_button)

        main_layout.addLayout(control_layout)

        # --------------------------------------------------
        # PROGRESS BAR
        # --------------------------------------------------

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        main_layout.addWidget(self.progress_bar)

        # --------------------------------------------------
        # RESULTS
        # --------------------------------------------------

        results_label = QLabel("Batch Analysis Results")
        results_label.setStyleSheet(
            "font-size: 15px; font-weight: bold;"
        )

        main_layout.addWidget(results_label)

        self.results_output = QPlainTextEdit()
        self.results_output.setReadOnly(True)

        self.results_output.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )

        self.results_output.setPlaceholderText(
            "Your consolidated PDF analysis report "
            "will appear here after processing."
        )

        self.results_output.setStyleSheet(
            """
            QPlainTextEdit {
                font-family: Consolas, monospace;
                font-size: 9pt;
            }
            """
        )

        main_layout.addWidget(self.results_output, stretch=1)

    # ======================================================
    # FILE MANAGEMENT
    # ======================================================

    def add_pdfs(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDF Documents",
            "",
            "PDF Documents (*.pdf)",
        )

        if not file_paths:
            return

        existing_paths = {
            self.file_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.file_list.count())
        }

        added_count = 0

        for file_path in file_paths:
            normalized_path = str(Path(file_path).resolve())

            if normalized_path in existing_paths:
                continue

            item = QListWidgetItem(Path(file_path).name)

            item.setToolTip(normalized_path)

            item.setData(
                Qt.ItemDataRole.UserRole,
                normalized_path,
            )

            self.file_list.addItem(item)

            existing_paths.add(normalized_path)
            added_count += 1

        self.update_file_count()

        if added_count:
            self.status_label.setText(
                f"Added {added_count} document(s)."
            )

    def remove_selected(self):
        selected_items = self.file_list.selectedItems()

        for item in selected_items:
            row = self.file_list.row(item)
            self.file_list.takeItem(row)

        self.update_file_count()

    def clear_files(self):
        self.file_list.clear()

        self.update_file_count()

        self.status_label.setText(
            "File selection cleared."
        )

    def update_file_count(self):
        count = self.file_list.count()

        self.file_count_label.setText(
            f"{count} document(s) selected"
        )

        self.analyze_button.setEnabled(count > 0)

    # ======================================================
    # ANALYSIS
    # ======================================================

    def start_analysis(self):
        if self.worker is not None and self.worker.isRunning():
            return

        pdf_paths = [
            self.file_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.file_list.count())
        ]

        if not pdf_paths:
            QMessageBox.information(
                self,
                "No PDFs Selected",
                "Please select at least one PDF document.",
            )
            return

        # Reset previous session data.
        self.results_output.clear()
        self.analysis_summaries.clear()
        self.analysis_results.clear()

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            "UNIVERSAL PDF ANALYSIS TEST SESSION"
        )

        self.results_output.appendPlainText(
            f"Documents selected: {len(pdf_paths)}"
        )

        self.results_output.appendPlainText(
            "=" * 110
        )

        # Configure progress.
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(pdf_paths))

        # Disable file controls during processing.
        self.set_controls_enabled(False)

        self.status_label.setText(
            "Starting analysis..."
        )

        # Create worker.
        self.worker = PDFAnalysisWorker(pdf_paths)

        self.worker.progress.connect(
            self.update_progress
        )

        self.worker.result_ready.connect(
            self.display_result
        )

        self.worker.error_ready.connect(
            self.display_error
        )

        self.worker.finished.connect(
            self.analysis_finished
        )

        self.worker.start()

    def update_progress(self, current, total, filename):
        self.progress_bar.setValue(current)

        self.status_label.setText(
            f"Analyzing {current}/{total}: {filename}"
        )

    # ======================================================
    # RESULT COLLECTION
    # ======================================================

    def display_result(self, pdf_path, result):
        """
        Collects document metrics without printing
        detailed diagnostics for every PDF.
        """
        self.analysis_results[pdf_path] = result
        filename = Path(pdf_path).name

        # Handle unexpected analyzer output.
        if not isinstance(result, dict):
            self.analysis_summaries.append({
                "filename": filename,
                "status": "ERROR",
                "error": (
                    f"Unexpected result type: "
                    f"{type(result).__name__}"
                ),
            })
            return

        pages = result.get("pages", [])

        summary = {
            "filename": filename,
            "status": "SUCCESS",

            "pages": result.get(
                "page_count",
                len(pages),
            ),

            "model": result.get(
                "document_model_version",
                "Unknown",
            ),

            "tables": 0,
            "containers": 0,
            "regions": 0,

            "lines": 0,
            "unassigned": 0,

            "cells": 0,
            "populated": 0,

            "high": 0,
            "medium": 0,
            "low": 0,
            "unknown": 0,

            "fallback": 0,
        }

        # --------------------------------------------------
        # COLLECT DOCUMENT METRICS
        # --------------------------------------------------

        for page in pages:
            summary["tables"] += page.get(
                "table_count", 0
            )

            summary["containers"] += page.get(
                "container_count", 0
            )

            summary["regions"] += page.get(
                "text_region_count", 0
            )

            summary["lines"] += page.get(
                "text_line_count", 0
            )

            summary["unassigned"] += len(
                page.get("unassigned_text", [])
            )

            # Collect assignment diagnostics.
            diagnostics = page.get(
                "diagnostics", {}
            )

            assignment = diagnostics.get(
                "assignment", {}
            )

            if isinstance(assignment, dict):
                summary["fallback"] += assignment.get(
                    "fallback_assigned_lines", 0
                )

            # Collect cell information.
            for table in page.get("tables", []):
                for row in table.get("rows", []):
                    for cell in row.get("cells", []):
                        summary["cells"] += 1

                        if cell.get("text", "").strip():
                            summary["populated"] += 1

                        confidence = cell.get(
                            "assignment_confidence"
                        )

                        if confidence in (
                            "high",
                            "medium",
                            "low",
                        ):
                            summary[confidence] += 1
                        else:
                            summary["unknown"] += 1

        # --------------------------------------------------
        # CALCULATE TEXT COVERAGE
        # --------------------------------------------------

        summary["coverage"] = (
            (
                summary["lines"]
                - summary["unassigned"]
            )
            / summary["lines"] * 100
            if summary["lines"] else 0
        )

        # --------------------------------------------------
        # IDENTIFY DOCUMENT STRUCTURE
        # --------------------------------------------------

        if summary["tables"] and summary["containers"]:
            summary["layout"] = "Mixed"

        elif summary["tables"]:
            summary["layout"] = "Table-based"

        elif summary["containers"]:
            summary["layout"] = "Container-based"

        elif summary["regions"]:
            summary["layout"] = "Text-based"

        else:
            summary["layout"] = "Empty/Graphical"

        # --------------------------------------------------
        # STORE SUMMARY
        # --------------------------------------------------

        self.analysis_summaries.append(summary)

    def display_error(self, pdf_path, error_details):
        """
        Records failed documents without stopping
        the remaining analysis batch.
        """

        filename = Path(pdf_path).name

        error_lines = error_details.strip().splitlines()

        short_error = (
            error_lines[-1]
            if error_lines
            else "Unknown error"
        )

        self.analysis_summaries.append({
            "filename": filename,
            "status": "ERROR",
            "error": short_error,
        })

    # ======================================================
    # FINAL BATCH REPORT
    # ======================================================

    def analysis_finished(self):
        self.set_controls_enabled(True)

        self.status_label.setText(
            "Analysis session finished."
        )

        summaries = self.analysis_summaries

        successful = [
            item for item in summaries
            if item.get("status") == "SUCCESS"
        ]

        failed = [
            item for item in summaries
            if item.get("status") == "ERROR"
        ]

        # --------------------------------------------------
        # SESSION TOTALS
        # --------------------------------------------------

        total_pages = sum(
            item["pages"] for item in successful
        )

        total_tables = sum(
            item["tables"] for item in successful
        )

        total_containers = sum(
            item["containers"] for item in successful
        )

        total_regions = sum(
            item["regions"] for item in successful
        )

        total_lines = sum(
            item["lines"] for item in successful
        )

        total_unassigned = sum(
            item["unassigned"] for item in successful
        )

        total_cells = sum(
            item["cells"] for item in successful
        )

        total_populated = sum(
            item["populated"] for item in successful
        )

        total_fallback = sum(
            item["fallback"] for item in successful
        )

        overall_coverage = (
            (
                total_lines - total_unassigned
            ) / total_lines * 100
            if total_lines else 0
        )

        # --------------------------------------------------
        # REPORT HEADER
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            "PDF ANALYSIS — BATCH SUMMARY"
        )

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            f"Documents processed: {len(summaries)} | "
            f"Successful: {len(successful)} | "
            f"Failed: {len(failed)}"
        )

        self.results_output.appendPlainText(
            f"Total pages: {total_pages}"
        )

        # --------------------------------------------------
        # STRUCTURE TOTALS
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "DETECTED STRUCTURES"
        )

        self.results_output.appendPlainText(
            f"Tables: {total_tables} | "
            f"Containers: {total_containers} | "
            f"Text regions: {total_regions}"
        )

        # --------------------------------------------------
        # TEXT PROCESSING TOTALS
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "TEXT PROCESSING"
        )

        self.results_output.appendPlainText(
            f"Extracted lines: {total_lines} | "
            f"Unassigned lines: {total_unassigned} | "
            f"Coverage: {overall_coverage:.1f}%"
        )

        # --------------------------------------------------
        # TABLE TOTALS
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "TABLE PROCESSING"
        )

        if total_cells:
            cell_rate = (
                total_populated / total_cells * 100
            )

            self.results_output.appendPlainText(
                f"Populated cells: "
                f"{total_populated}/{total_cells} "
                f"({cell_rate:.1f}%)"
            )

        else:
            self.results_output.appendPlainText(
                "Table population: N/A — "
                "no table cells detected."
            )

        self.results_output.appendPlainText(
            f"Fallback assignments: {total_fallback}"
        )

        # --------------------------------------------------
        # DOCUMENT COMPARISON
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "-" * 110
        )

        self.results_output.appendPlainText(
            "DOCUMENT COMPARISON"
        )

        self.results_output.appendPlainText(
            "-" * 110
        )

        header = (
            f"{'DOCUMENT':<34}"
            f"{'PAGES':>6}"
            f"{'LAYOUT':>17}"
            f"{'T/C/R':>12}"
            f"{'COVERAGE':>11}"
            f"{'CELLS':>13}"
            f"{'FALLBACK':>10}"
            f"{'REVIEW':>10}"
        )

        self.results_output.appendPlainText(header)

        self.results_output.appendPlainText(
            "-" * 110
        )

        for item in summaries:
            filename = item["filename"][:32]

            # Failed documents.
            if item.get("status") == "ERROR":
                self.results_output.appendPlainText(
                    f"{filename:<34}  ANALYSIS FAILED"
                )

                self.results_output.appendPlainText(
                    f"  Error: {item.get('error', 'Unknown error')}"
                )

                continue

            # Table population.
            cell_display = (
                f"{item['populated']}/{item['cells']}"
                if item["cells"]
                else "N/A"
            )

            # Review indicators.
            review = (
                f"U{item['unassigned']}"
                f"/L{item['low']}"
                f"/E{item['cells'] - item['populated']}"
            )

            # Structure counts.
            structure_counts = (
                f"{item['tables']}/"
                f"{item['containers']}/"
                f"{item['regions']}"
            )

            coverage_display = (
                f"{item['coverage']:.1f}%"
            )

            self.results_output.appendPlainText(
                f"{filename:<34}"
                f"{item['pages']:>6}"
                f"{item['layout']:>17}"
                f"{structure_counts:>12}"
                f"{coverage_display:>11}"
                f"{cell_display:>13}"
                f"{item['fallback']:>10}"
                f"{review:>10}"
            )

        # --------------------------------------------------
        # CONFIDENCE TOTALS
        # --------------------------------------------------

        if total_cells:
            total_high = sum(
                item["high"] for item in successful
            )

            total_medium = sum(
                item["medium"] for item in successful
            )

            total_low = sum(
                item["low"] for item in successful
            )

            total_unknown = sum(
                item["unknown"] for item in successful
            )

            self.results_output.appendPlainText("")

            self.results_output.appendPlainText(
                "CELL ASSIGNMENT CONFIDENCE"
            )

            self.results_output.appendPlainText(
                f"High: {total_high} | "
                f"Medium: {total_medium} | "
                f"Low: {total_low} | "
                f"Unknown: {total_unknown}"
            )

        # --------------------------------------------------
        # REVIEW KEY
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "REVIEW KEY:"
        )

        self.results_output.appendPlainText(
            "U = Unassigned text lines"
        )

        self.results_output.appendPlainText(
            "L = Low-confidence cell assignments"
        )

        self.results_output.appendPlainText(
            "E = Empty table cells"
        )

        self.results_output.appendPlainText(
            "T/C/R = Tables / Containers / Text regions"
        )

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "Text coverage measures lines not marked "
            "unassigned. It does not verify correct placement."
        )

        # --------------------------------------------------
        # COMPLETION
        # --------------------------------------------------

        self.results_output.appendPlainText("")

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.results_output.appendPlainText(
            "TEST SESSION FINISHED"
        )

        self.results_output.appendPlainText(
            "=" * 110
        )

        self.worker = None

    def open_visual_inspector(self):
        if not self.analysis_results:
            QMessageBox.information(
                self,
                "No Analysis Available",
                "Analyze at least one PDF before opening "
                "the visual inspector.",
            )
            return

        dialog = PDFVisualInspector(
            self.analysis_results,
            self,
    )

        dialog.exec()

    # ======================================================
    # WORKER STATE
    # ======================================================

    def set_controls_enabled(self, enabled):
        self.add_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)

        self.file_list.setEnabled(enabled)

        self.analyze_button.setEnabled(
            enabled and self.file_list.count() > 0
        )

        self.inspect_button.setEnabled(
            enabled and bool(self.analysis_results)
        )

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(
                self,
                "Analysis Running",
                "Wait for the current analysis to finish "
                "before closing this window.",
            )

            event.ignore()
            return

        event.accept()


def main():
    app = QApplication(sys.argv)

    window = PDFAnalysisTestWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
