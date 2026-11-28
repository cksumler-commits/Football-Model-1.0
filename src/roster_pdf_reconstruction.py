
import re
from statistics import median

import pymupdf


HEADER_TERMS = {
    "no", "number", "jersey", "player", "name", "position", "pos",
    "height", "ht", "weight", "wt", "class", "year",
    "experience", "hometown", "home town", "high school",
    "highschool", "previous school", "school", "major",
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
    """Extract word-level text while retaining PDF coordinates."""

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
    """Group words by their vertical positions, not PDF line IDs."""

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
    """Cluster recurring x positions, counting support by distinct rows."""

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

    accepted.sort(key=lambda item: item["x"])
    return accepted


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
    """
    Detect recurring cell starts from large horizontal gaps.

    The positions are inferred independently for each document/page.
    No school-specific coordinates or fixed column layouts are used.
    """

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

    clusters = _cluster_positions(
        candidates,
        position_tolerance,
        minimum_support,
    )

    return clusters, gap_threshold, position_tolerance


def _split_row_into_cells(row, column_starts, gap_threshold,
                          position_tolerance):
    cells = []

    for word in row:
        target_column = 0

        for index, boundary in enumerate(column_starts):
            if (
                word["x0"] >= boundary["x"] - position_tolerance
            ):
                target_column = index + 1

        while len(cells) <= target_column:
            cells.append([])

        cells[target_column].append(word)

    result = []

    for index, cell_words in enumerate(cells):
        if not cell_words:
            result.append({
                "column_index": index,
                "text": "",
                "words": [],
                "bbox": None,
            })
            continue

        cell_words.sort(key=lambda item: item["x0"])

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
            "rows": [],
            "records": [],
            "columns": [],
            "unassigned_text": "",
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

    reconstructed_rows = []
    records = []
    unassigned_rows = []

    for row_index, row in enumerate(rows):
        cells = _split_row_into_cells(
            row,
            column_starts,
            gap_threshold,
            position_tolerance,
        )

        text = _row_text(row)
        nonempty_cells = [cell for cell in cells if cell["text"]]

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

        bbox = [
            min(word["x0"] for word in row),
            min(word["y0"] for word in row),
            max(word["x1"] for word in row),
            max(word["y1"] for word in row),
        ]

        row_result = {
            "row_index": row_index,
            "text": text,
            "cells": cells,
            "bbox": bbox,
            "word_count": len(row),
            "is_header_candidate": is_header,
            "source_words": [word["source"] for word in row],
        }

        reconstructed_rows.append(row_result)

        if is_header:
            unassigned_rows.append(text)
            continue

        # Preserve every non-header visual row as a candidate.
        # No jersey-number anchor is required.
        if text:
            records.append({
                "record_id": f"page_{page_number}_row_{row_index + 1}",
                "page_number": page_number,
                "row_index": row_index,
                "text": text,
                "cells": cells,
                "bbox": bbox,
                "word_count": len(row),
                "source_words": [word["source"] for word in row],
                "confidence": (
                    "medium" if len(nonempty_cells) >= 2 else "low"
                ),
                "review_required": len(nonempty_cells) < 2,
            })

    # A column count is based on observed recurring boundaries.
    column_count = len(column_starts) + 1 if rows else 0

    return {
        "page_number": page_number,
        "source_words": source_words,
        "rows": reconstructed_rows,
        "records": records,
        "columns": column_starts,
        "unassigned_text": "\n".join(unassigned_rows),
        "diagnostics": {
            "word_count": len(geometries),
            "row_count": len(rows),
            "record_count": len(records),
            "column_count": column_count,
            "median_text_height": round(median_height, 2),
            "row_tolerance": round(row_tolerance, 2),
            "gap_threshold": round(gap_threshold, 2),
            "column_boundaries": column_starts,
            "reason": (
                "Rows and recurring column starts were inferred "
                "from word geometry."
                if column_starts
                else
                "Rows were reconstructed, but recurring column "
                "boundaries were not sufficiently supported."
            ),
        },
    }


def analyze_roster_pdf(pdf_path):
    """
    Analyze every page in a PDF without requiring manual region selection.

    Returns page-level rows, candidate records, inferred columns,
    source words, and diagnostics. All extracted words remain traceable.
    """

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
        {
            "page_number": page["page_number"],
            "text": page["unassigned_text"],
        }
        for page in pages
        if page["unassigned_text"].strip()
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
                "Automatic full-document reconstruction completed. "
                "Candidate rows are not yet confirmed player records."
            ),
        },
    }


def recover_selected_region(source_words, selection_bbox, page_number):
    """
    Reconstruct a selected region as supplemental recovery data.

    This does not replace or erase the automatic page analysis.
    """

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


# Backward-compatible wrapper for the previous selected-record workflow.
def reconstruct_pdf_roster_cells(records, layout_result=None):
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

        boundaries, gap_threshold, tolerance = _detect_columns(
            rows,
            median_height,
        )

        cells = []

        for row in rows:
            row_cells = _split_row_into_cells(
                row, boundaries, gap_threshold, tolerance
            )
            cells.extend(row_cells)

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
