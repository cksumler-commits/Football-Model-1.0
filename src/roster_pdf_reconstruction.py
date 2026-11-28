
import re
from statistics import median

import pymupdf


HEADER_TERMS = {
    "no", "number", "jersey", "player", "name", "position", "pos",
    "height", "ht", "weight", "wt", "class", "year",
    "experience", "hometown", "home town", "high school",
    "highschool", "previous school", "school", "major",
}

POSITION_TERMS = {
    "QB", "RB", "FB", "HB", "WR", "TE", "C", "G", "OG", "OT",
    "OL", "DL", "DE", "DT", "NT", "EDGE", "LB", "MLB", "ILB",
    "OLB", "DB", "CB", "S", "FS", "SS", "NICKEL", "NB",
    "K", "PK", "P", "LS", "KR", "PR",
}

CLASS_TERMS = {
    "FR", "FRESHMAN", "R-FR", "RFR", "SO", "SOPH",
    "SOPHOMORE", "R-SO", "RSO", "JR", "JUNIOR", "R-JR",
    "RJR", "SR", "SENIOR", "R-SR", "RSR", "GR", "GRAD",
    "GRADUATE", "FIFTH", "FIFTH YEAR",
}


def _word_geometry(word):
    bbox = word.get("bbox")

    if not bbox or len(bbox) != 4:
        return None

    try:
        x0, y0, x1, y1 = map(float, bbox)
    except (TypeError, ValueError):
        return None

    text = str(word.get("text", "")).strip()

    if not text or x1 <= x0 or y1 <= y0:
        return None

    return {
        "text": text,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "cx": (x0 + x1) / 2,
        "cy": (y0 + y1) / 2,
        "height": y1 - y0,
        "source": word,
    }


def _extract_page_words(page):
    extracted = []

    for item in page.get_text("words", sort=False):
        if len(item) < 5:
            continue

        x0, y0, x1, y1, text = item[:5]

        extracted.append({
            "text": str(text),
            "bbox": [x0, y0, x1, y1],
            "block_number": item[5] if len(item) > 5 else None,
            "line_number": item[6] if len(item) > 6 else None,
            "word_number": item[7] if len(item) > 7 else None,
        })

    return extracted


def _group_visual_rows(words, tolerance):
    rows = []

    for word in sorted(words, key=lambda item: (item["cy"], item["x0"])):
        best_row = None
        best_distance = None

        for row in rows:
            center = median(item["cy"] for item in row)
            distance = abs(word["cy"] - center)

            if distance <= tolerance and (
                best_distance is None or distance < best_distance
            ):
                best_row = row
                best_distance = distance

        if best_row is None:
            rows.append([word])
        else:
            best_row.append(word)

    for row in rows:
        row.sort(key=lambda item: item["x0"])

    rows.sort(key=lambda row: median(item["cy"] for item in row))
    return rows


def _cluster_positions(candidates, tolerance, minimum_support):
    clusters = []

    for candidate in sorted(candidates, key=lambda item: item["x"]):
        best_cluster = None
        best_distance = None

        for cluster in clusters:
            center = median(item["x"] for item in cluster)
            distance = abs(candidate["x"] - center)

            if distance <= tolerance and (
                best_distance is None or distance < best_distance
            ):
                best_cluster = cluster
                best_distance = distance

        if best_cluster is None:
            clusters.append([candidate])
        else:
            best_cluster.append(candidate)

    accepted = []

    for cluster in clusters:
        row_ids = {item["row"] for item in cluster}

        if len(row_ids) >= minimum_support:
            accepted.append({
                "x": median(item["x"] for item in cluster),
                "row_support": len(row_ids),
                "observations": len(cluster),
            })

    return sorted(accepted, key=lambda item: item["x"])


def _is_header_text(text):
    normalized = re.sub(
        r"[^a-z0-9]+", " ", str(text).casefold()
    ).strip()

    if not normalized:
        return False

    if normalized in HEADER_TERMS:
        return True

    return any(
        term in normalized
        for term in (
            "high school",
            "previous school",
            "hometown",
            "home town",
            "classification",
        )
    )


def _row_text(row):
    return " ".join(word["text"] for word in row).strip()


def _detect_columns(rows, median_height):
    gap_threshold = max(5.0, median_height * 1.35)
    position_tolerance = max(5.0, median_height * 1.5)

    candidates = []

    for row_index, row in enumerate(rows):
        for left, right in zip(row, row[1:]):
            gap = right["x0"] - left["x1"]

            if gap >= gap_threshold:
                candidates.append({
                    "x": right["x0"],
                    "row": row_index,
                    "gap": gap,
                })

    minimum_support = max(2, round(len(rows) * 0.20))

    boundaries = _cluster_positions(
        candidates,
        position_tolerance,
        minimum_support,
    )

    return boundaries, gap_threshold, position_tolerance


def _split_row_into_cells(row, column_starts, position_tolerance):
    cells = []

    for word in row:
        target_column = 0

        for index, boundary in enumerate(column_starts):
            if word["x0"] >= boundary["x"] - position_tolerance:
                target_column = index + 1

        while len(cells) <= target_column:
            cells.append([])

        cells[target_column].append(word)

    result = []

    for index, cell_words in enumerate(cells):
        cell_words.sort(key=lambda item: item["x0"])

        if not cell_words:
            result.append({
                "column_index": index,
                "text": "",
                "words": [],
                "bbox": None,
            })
            continue

        result.append({
            "column_index": index,
            "text": " ".join(item["text"] for item in cell_words),
            "words": [item["source"] for item in cell_words],
            "bbox": [
                min(item["x0"] for item in cell_words),
                min(item["y0"] for item in cell_words),
                max(item["x1"] for item in cell_words),
                max(item["y1"] for item in cell_words),
            ],
        })

    return result


def _is_page_metadata(text):
    value = str(text or "").strip()
    lowered = value.casefold()

    if not value:
        return True

    if re.search(r"https?://|www\.", lowered):
        return True

    if re.search(
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
        r"|\b\d{1,2}:\d{2}\s*(am|pm)\b",
        lowered,
    ):
        return True

    if re.fullmatch(r"\d+\s*/\s*\d+", value):
        return True

    if any(term in lowered for term in (
        "official athletics website",
        "football roster",
        "previous",
        "next",
    )):
        return True

    return False


def _row_features(cells, row_text):
    """
    Score a row using multiple independent football-roster clues.

    Numeric jersey-like values are supporting evidence only.
    """

    cell_values = [
        str(cell.get("text", "")).strip()
        for cell in cells
        if str(cell.get("text", "")).strip()
    ]

    text = " ".join(cell_values) or row_text
    tokens = re.findall(r"[A-Za-z0-9#'\"-]+", text)
    upper_tokens = {token.upper().strip(".") for token in tokens}

    has_position = bool(upper_tokens & POSITION_TERMS)

    has_height = bool(
        re.search(
            r"\b\d{1,2}\s*[-′']\s*\d{1,2}\s*(?:[″\"])?\b",
            text,
        )
        or re.search(
            r"\b\d{1,2}\s*(?:ft|feet)\s*\d{1,2}\s*(?:in|inches)?\b",
            text,
            re.IGNORECASE,
        )
    )

    has_weight = bool(
        re.search(r"\b\d{2,3}\s*(?:lbs?|pounds)\b", text, re.I)
    )

    has_class = bool(upper_tokens & CLASS_TERMS)

    # Number is only a supporting clue, and only in the first cell.
    first_cell = cell_values[0] if cell_values else ""
    has_number = bool(
        re.fullmatch(r"#?\d{1,2}", first_cell.strip())
    )

    has_name_like_text = any(
        len(token) >= 2
        and token[0].isalpha()
        and token[1:].replace("-", "").isalpha()
        for token in tokens
    )

    score = (
        2 * has_position
        + 2 * has_height
        + 2 * has_weight
        + 2 * has_class
        + has_number
        + has_name_like_text
    )

    # A strong row requires multiple independent kinds of evidence.
    is_anchor = (
        (has_position and (has_height or has_weight or has_class))
        or (has_height and has_weight and has_class)
        or (
            has_number
            and has_position
            and (has_height or has_weight or has_class)
        )
    )

    return {
        "score": int(score),
        "has_position": has_position,
        "has_height": has_height,
        "has_weight": has_weight,
        "has_class": has_class,
        "has_number": has_number,
        "has_name_like_text": has_name_like_text,
        "is_anchor": bool(is_anchor),
    }


def _merge_record_rows(page_number, row_group, anchor_row_index):
    """
    Merge cells vertically while retaining every original fragment.

    The merged cell text is convenient for later field mapping.
    Its fragments and source words preserve the original evidence.
    """

    maximum_columns = max(
        (len(row["cells"]) for row in row_group),
        default=0,
    )

    merged_cells = []

    for column_index in range(maximum_columns):
        fragments = []

        for row in row_group:
            cells = row["cells"]

            if column_index >= len(cells):
                continue

            cell = cells[column_index]

            if not cell.get("text"):
                continue

            fragments.append({
                "row_index": row["row_index"],
                "text": cell["text"],
                "bbox": cell.get("bbox"),
                "words": cell.get("words", []),
            })

        if not fragments:
            continue

        source_words = [
            word
            for fragment in fragments
            for word in fragment["words"]
        ]

        boxes = [
            fragment["bbox"]
            for fragment in fragments
            if fragment.get("bbox")
        ]

        merged_bbox = None

        if boxes:
            merged_bbox = [
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ]

        merged_cells.append({
            "cell_id": (
                f"page_{page_number}_record_{anchor_row_index + 1}"
                f"_column_{column_index + 1}"
            ),
            "column_index": column_index,
            "text": " ".join(
                fragment["text"] for fragment in fragments
            ),
            "fragments": fragments,
            "source_words": source_words,
            "bbox": merged_bbox,
            "word_count": len(source_words),
            "contributing_rows": [
                fragment["row_index"] for fragment in fragments
            ],
        })

    all_words = [
        word
        for row in row_group
        for word in row["source_words"]
    ]

    boxes = [row["bbox"] for row in row_group]

    bbox = [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]

    original_text = "\n".join(
        row["text"] for row in row_group
    )

    return {
        "record_id": (
            f"page_{page_number}_record_{anchor_row_index + 1}"
        ),
        "page_number": page_number,
        "anchor_row_index": anchor_row_index,
        "row_indices": [
            row["row_index"] for row in row_group
        ],
        "text": original_text,
        "cells": merged_cells,
        "bbox": bbox,
        "word_count": len(all_words),
        "source_words": all_words,
        "confidence": "medium",
        "confidence_score": 0.0,
        "review_required": True,
        "record_features": {},
    }


def _reconstruct_page(page_number, source_words):
    geometries = [
        item for item in
        (_word_geometry(word) for word in source_words)
        if item is not None
    ]

    if not geometries:
        return {
            "page_number": page_number,
            "source_words": source_words,
            "visual_rows": [],
            "rows": [],
            "records": [],
            "columns": [],
            "unassigned_text": "",
            "unassigned_content": [],
            "diagnostics": {
                "word_count": 0,
                "row_count": 0,
                "record_count": 0,
                "column_count": 0,
                "reason": "No usable word geometry was extracted.",
            },
        }

    median_height = median(item["height"] for item in geometries)
    row_tolerance = max(2.0, median_height * 0.65)

    rows = _group_visual_rows(geometries, row_tolerance)

    column_starts, gap_threshold, position_tolerance = (
        _detect_columns(rows, median_height)
    )

    visual_rows = []
    metadata_rows = []
    eligible_rows = []

    for row_index, row in enumerate(rows):
        cells = _split_row_into_cells(
            row,
            column_starts,
            position_tolerance,
        )

        text = _row_text(row)

        bbox = [
            min(word["x0"] for word in row),
            min(word["y0"] for word in row),
            max(word["x1"] for word in row),
            max(word["y1"] for word in row),
        ]

        features = _row_features(cells, text)

        nonempty_cells = [
            cell for cell in cells if cell["text"]
        ]

        header_hits = sum(
            1 for cell in nonempty_cells
            if _is_header_text(cell["text"])
        )

        is_header = (
            header_hits >= 2
            or (
                len(nonempty_cells) == 1
                and _is_header_text(text)
            )
        )

        is_metadata = _is_page_metadata(text)

        row_result = {
            "row_index": row_index,
            "text": text,
            "cells": cells,
            "bbox": bbox,
            "word_count": len(row),
            "is_header_candidate": is_header,
            "is_metadata_candidate": is_metadata,
            "source_words": [word["source"] for word in row],
            "features": features,
        }

        visual_rows.append(row_result)

        if is_header or is_metadata:
            metadata_rows.append(row_result)
        else:
            eligible_rows.append(row_result)

    # --------------------------------------------------
    # Find strong record-start rows using combined evidence.
    # --------------------------------------------------

    anchors = [
        row for row in eligible_rows
        if row["features"]["is_anchor"]
    ]

    # Conservative fallback for unusual layouts where the usual
    # position/height/weight/class combination is absent.
    if not anchors:
        anchors = [
            row for row in eligible_rows
            if (
                row["features"]["score"] >= 5
                and len([
                    cell for cell in row["cells"]
                    if cell["text"]
                ]) >= 3
            )
        ]

    anchors.sort(key=lambda row: row["row_index"])

    record_groups = []

    if anchors:
        anchor_centers = [
            (row["bbox"][1] + row["bbox"][3]) / 2
            for row in anchors
        ]

        for anchor_index, anchor in enumerate(anchors):
            if anchor_index == 0:
                top = float("-inf")
            else:
                top = (
                    anchor_centers[anchor_index - 1]
                    + anchor_centers[anchor_index]
                ) / 2

            if anchor_index == len(anchors) - 1:
                bottom = float("inf")
            else:
                bottom = (
                    anchor_centers[anchor_index]
                    + anchor_centers[anchor_index + 1]
                ) / 2

            group = [
                row for row in eligible_rows
                if top < (
                    (row["bbox"][1] + row["bbox"][3]) / 2
                ) <= bottom
            ]

            if group:
                record_groups.append((anchor, group))

    else:
        # Do not pretend that arbitrary visual rows are players.
        # Keep the content visible for review instead.
        record_groups = []

    records = []

    for anchor, group in record_groups:
        record = _merge_record_rows(
            page_number,
            group,
            anchor["row_index"],
        )

        features = anchor["features"]
        score = features["score"]

        record["record_features"] = features
        record["confidence_score"] = min(1.0, score / 9.0)

        # Confidence remains deliberately cautious until semantic
        # column mapping validates the values.
        if score >= 7:
            record["confidence"] = "medium"
        else:
            record["confidence"] = "low"

        record["review_required"] = True
        records.append(record)

    assigned_row_indices = {
        row_index
        for record in records
        for row_index in record["row_indices"]
    }

    unassigned_rows = [
        row for row in visual_rows
        if (
            row["row_index"] not in assigned_row_indices
            or row["is_header_candidate"]
            or row["is_metadata_candidate"]
        )
    ]

    unassigned_content = [
        {
            "page_number": page_number,
            "row_index": row["row_index"],
            "text": row["text"],
            "bbox": row["bbox"],
            "reason": (
                "header"
                if row["is_header_candidate"]
                else "page metadata"
                if row["is_metadata_candidate"]
                else "unassigned or ambiguous row"
            ),
            "source_words": row["source_words"],
        }
        for row in unassigned_rows
    ]

    column_count = len(column_starts) + 1 if rows else 0

    return {
        "page_number": page_number,
        "source_words": source_words,
        "visual_rows": visual_rows,
        # Keep the previous key for compatibility with existing callers.
        "rows": visual_rows,
        "records": records,
        "columns": column_starts,
        "unassigned_text": "\n".join(
            item["text"] for item in unassigned_content
        ),
        "unassigned_content": unassigned_content,
        "diagnostics": {
            "word_count": len(geometries),
            "row_count": len(visual_rows),
            "record_count": len(records),
            "column_count": column_count,
            "anchor_count": len(anchors),
            "median_text_height": round(median_height, 2),
            "row_tolerance": round(row_tolerance, 2),
            "gap_threshold": round(gap_threshold, 2),
            "column_boundaries": column_starts,
            "reason": (
                "Visual rows were grouped around multi-signal "
                "record anchors. Cell fragments and source words "
                "were retained."
                if records
                else
                "No sufficiently supported player-record anchors "
                "were found. Source rows were preserved for review."
            ),
        },
    }


def analyze_roster_pdf(pdf_path):
    """Analyze every page and reconstruct grouped candidate records."""

    pages = []

    with pymupdf.open(pdf_path) as document:
        for page_index, page in enumerate(document):
            source_words = _extract_page_words(page)

            pages.append(
                _reconstruct_page(page_index + 1, source_words)
            )

    all_records = [
        record
        for page in pages
        for record in page["records"]
    ]

    all_unassigned = [
        item
        for page in pages
        for item in page["unassigned_content"]
    ]

    total_words = sum(
        page["diagnostics"]["word_count"] for page in pages
    )

    return {
        "pdf_path": str(pdf_path),
        "page_count": len(pages),
        "pages": pages,
        "records": all_records,
        "unassigned_content": all_unassigned,
        "diagnostics": {
            "total_words": total_words,
            "total_candidate_records": len(all_records),
            "pages_with_records": sum(
                bool(page["records"]) for page in pages
            ),
            "message": (
                "Automatic analysis completed. Records are grouped "
                "candidates and still require semantic review."
            ),
        },
    }


def recover_selected_region(source_words, selection_bbox, page_number):
    """Analyze a selected region without replacing full-page results."""

    x0, y0, x1, y1 = map(float, selection_bbox)

    selected = []

    for word in source_words:
        geometry = _word_geometry(word)

        if geometry is None:
            continue

        intersects = not (
            geometry["x1"] <= x0
            or geometry["x0"] >= x1
            or geometry["y1"] <= y0
            or geometry["y0"] >= y1
        )

        if intersects:
            selected.append(word)

    reconstructed = _reconstruct_page(page_number, selected)

    reconstructed["recovery_region"] = list(selection_bbox)
    reconstructed["is_recovery_result"] = True

    return reconstructed


def reconstruct_pdf_roster_cells(records, layout_result=None):
    """Backward-compatible wrapper for older callers."""

    reconstructed = []

    for record_index, record in enumerate(records):
        source_words = []

        for line in record.get("lines", []):
            source_words.extend(line.get("words", []))

        geometries = [
            item for item in
            (_word_geometry(word) for word in source_words)
            if item is not None
        ]

        if not geometries:
            reconstructed.append({
                **record,
                "cells": [],
            })
            continue

        median_height = median(item["height"] for item in geometries)
        rows = _group_visual_rows(
            geometries,
            max(2.0, median_height * 0.65),
        )

        boundaries, _gap_threshold, tolerance = _detect_columns(
            rows,
            median_height,
        )

        cells = []

        for row in rows:
            cells.extend(
                _split_row_into_cells(row, boundaries, tolerance)
            )

        reconstructed.append({
            **record,
            "cells": cells,
        })

    return {
        "records": reconstructed,
        "column_starts": [],
        "diagnostics": {
            "layout_type": (layout_result or {}).get(
                "layout_type", "unclassified"
            ),
            "record_count": len(reconstructed),
            "column_count": 0,
            "reason": (
                "Backward-compatible reconstruction. "
                "Use analyze_roster_pdf() for full-document analysis."
            ),
        },
    }
