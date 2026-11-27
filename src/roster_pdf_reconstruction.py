import math
import re
from statistics import median


HEADER_TERMS = {
    "number", "no", "jersey", "player", "name",
    "position", "pos", "height", "ht",
    "weight", "wt", "class", "classification",
    "experience", "hometown", "home town",
    "high school", "highschool", "previous school",
    "major", "year",
}


def _get_word_geometry(word):
    """Return normalized word geometry, or None if unavailable."""

    bbox = word.get("bbox")

    if not bbox or len(bbox) != 4:
        return None

    try:
        x0, y0, x1, y1 = map(float, bbox)
    except (TypeError, ValueError):
        return None

    if x1 <= x0 or y1 <= y0:
        return None

    text = str(word.get("text", "")).strip()

    if not text:
        return None

    return {
        "source": word,
        "text": text,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "cx": (x0 + x1) / 2,
        "cy": (y0 + y1) / 2,
        "height": y1 - y0,
    }


def _get_record_words(record):
    """Collect each source word once from a segmented record."""

    collected = []
    seen = set()

    for line in record.get("lines", []):
        for word in line.get("words", []):
            geometry = _get_word_geometry(word)

            if geometry is None:
                continue

            # Word coordinates and extraction identifiers provide
            # a stable key without requiring object identity.
            key = (
                word.get("block_number"),
                word.get("line_number"),
                word.get("word_number"),
                tuple(round(value, 2) for value in geometry["source"]["bbox"]),
                geometry["text"],
            )

            if key in seen:
                continue

            seen.add(key)
            collected.append(geometry)

    return collected


def _group_visual_rows(words, row_tolerance):
    """
    Group words by vertical position rather than relying on PDF
    block/line identifiers, which can differ between columns.
    """

    rows = []

    for word in sorted(
        words,
        key=lambda item: (item["cy"], item["x0"]),
    ):
        best_row = None
        best_distance = None

        for row in rows:
            row_center = sum(
                item["cy"] for item in row
            ) / len(row)

            distance = abs(word["cy"] - row_center)

            if distance <= row_tolerance:
                if best_distance is None or distance < best_distance:
                    best_row = row
                    best_distance = distance

        if best_row is None:
            rows.append([word])
        else:
            best_row.append(word)

    for row in rows:
        row.sort(key=lambda item: item["x0"])

    rows.sort(
        key=lambda row: min(item["cy"] for item in row)
    )

    return rows


def _cluster_column_starts(gap_candidates, tolerance, record_count):
    """
    Cluster recurring starts of text that follows a wide horizontal gap.

    A candidate must recur across multiple player records. This helps
    distinguish actual column starts from ordinary spaces between words.
    """

    clusters = []

    for candidate in sorted(
        gap_candidates,
        key=lambda item: item["right_x"],
    ):
        matching_cluster = None
        best_distance = None

        for cluster in clusters:
            center = median(
                item["right_x"] for item in cluster
            )

            distance = abs(candidate["right_x"] - center)

            if distance <= tolerance:
                if best_distance is None or distance < best_distance:
                    matching_cluster = cluster
                    best_distance = distance

        if matching_cluster is None:
            clusters.append([candidate])
        else:
            matching_cluster.append(candidate)

    minimum_support = max(
        2,
        math.ceil(record_count * 0.25),
    )

    accepted = []

    for cluster in clusters:
        supporting_records = {
            item["record_index"]
            for item in cluster
        }

        if len(supporting_records) < minimum_support:
            continue

        accepted.append({
            "x": median(
                item["right_x"] for item in cluster
            ),
            "record_support": len(supporting_records),
            "gap_count": len(cluster),
            "median_gap_width": median(
                item["gap_width"] for item in cluster
            ),
        })

    accepted.sort(key=lambda item: item["x"])

    # Avoid treating two nearly identical clusters as separate columns.
    merged = []

    for cluster in accepted:
        if (
            merged
            and abs(cluster["x"] - merged[-1]["x"])
            <= tolerance
        ):
            previous = merged[-1]

            previous["x"] = median([
                previous["x"],
                cluster["x"],
            ])

            previous["record_support"] = max(
                previous["record_support"],
                cluster["record_support"],
            )

            previous["gap_count"] += cluster["gap_count"]

            previous["median_gap_width"] = median([
                previous["median_gap_width"],
                cluster["median_gap_width"],
            ])
        else:
            merged.append(cluster.copy())

    return merged


def _is_header_candidate(value):
    """Flag likely column headings without deleting their source text."""

    normalized = re.sub(
        r"[^a-z0-9]+",
        " ",
        str(value or "").casefold(),
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
            "classification",
            "hometown",
            "home town",
        )
    )


def reconstruct_pdf_roster_cells(records, layout_result=None):
    """
    Reconstruct spatially aligned cells from segmented PDF records.

    For table-like layouts, recurring wide gaps across multiple records
    are used to identify likely column starts.

    For card-like or uncertain layouts, the function preserves visual
    rows without forcing a table structure.

    No fixed PDF coordinates or school-specific assumptions are used.
    Original source words and bounding boxes are retained.
    """

    layout_result = layout_result or {}

    layout_type = layout_result.get(
        "layout_type",
        "unclassified",
    )

    table_like_layouts = {
        "traditional_table",
        "multi_column_roster",
        "single_column_roster",
    }

    use_column_inference = layout_type in table_like_layouts

    prepared_records = []
    all_heights = []

    # --------------------------------------------------
    # 1. Prepare words and visual rows for each record.
    # --------------------------------------------------

    for record_index, record in enumerate(records):
        words = _get_record_words(record)

        if not words:
            prepared_records.append({
                "record": record,
                "record_index": record_index,
                "words": [],
                "rows": [],
            })
            continue

        all_heights.extend(
            word["height"] for word in words
        )

        prepared_records.append({
            "record": record,
            "record_index": record_index,
            "words": words,
        })

    if not all_heights:
        return {
            "records": [],
            "column_starts": [],
            "diagnostics": {
                "layout_type": layout_type,
                "record_count": len(records),
                "column_count": 0,
                "reason": "No usable source-word geometry was found.",
            },
        }

    median_height = median(all_heights)

    row_tolerance = max(
        2.0,
        median_height * 0.65,
    )

    for prepared in prepared_records:
        prepared["rows"] = _group_visual_rows(
            prepared["words"],
            row_tolerance,
        )

    # --------------------------------------------------
    # 2. Find recurring horizontal column starts.
    # --------------------------------------------------

    gap_threshold = max(
        3.0,
        median_height * 1.20,
    )

    gap_candidates = []

    if use_column_inference:
        for prepared in prepared_records:
            record_index = prepared["record_index"]

            for row_index, row in enumerate(prepared["rows"]):
                for left_word, right_word in zip(row, row[1:]):
                    gap_width = (
                        right_word["x0"] - left_word["x1"]
                    )

                    if gap_width < gap_threshold:
                        continue

                    gap_candidates.append({
                        "record_index": record_index,
                        "row_index": row_index,
                        "right_x": right_word["x0"],
                        "gap_width": gap_width,
                    })

    column_tolerance = max(
        5.0,
        median_height * 1.25,
    )

    column_starts = _cluster_column_starts(
        gap_candidates,
        column_tolerance,
        len(records),
    )

    column_positions = [
        item["x"] for item in column_starts
    ]

    # --------------------------------------------------
    # 3. Split each visual row using the inferred starts.
    # --------------------------------------------------

    reconstructed_records = []

    for prepared in prepared_records:
        original_record = prepared["record"]

        cells_by_column = {}

        for row_index, row in enumerate(prepared["rows"]):
            current_column = 0
            current_words = []

            for word_index, word in enumerate(row):
                if word_index > 0 and column_positions:
                    previous_word = row[word_index - 1]

                    gap_width = (
                        word["x0"] - previous_word["x1"]
                    )

                    if gap_width >= gap_threshold:
                        matching_starts = [
                            (index + 1, start_x)
                            for index, start_x in enumerate(column_positions)
                            if abs(word["x0"] - start_x) <= column_tolerance
                        ]

                        if matching_starts:
                            current_column = min(
                                matching_starts,
                                key=lambda item: abs(
                                    word["x0"] - item[1]
                                ),
                            )[0]

                cells_by_column.setdefault(
                    current_column,
                    [],
                ).append({
                    "row_index": row_index,
                    "word": word,
                })

        # --------------------------------------------------
        # 4. Reconstruct cell text and preserve provenance.
        # --------------------------------------------------

        reconstructed_cells = []

        for column_index in sorted(cells_by_column):
            entries = cells_by_column[column_index]

            row_groups = {}

            for entry in entries:
                row_groups.setdefault(
                    entry["row_index"],
                    [],
                ).append(entry["word"])

            cell_lines = []

            for row_index in sorted(row_groups):
                line_words = sorted(
                    row_groups[row_index],
                    key=lambda item: item["x0"],
                )

                line_text = " ".join(
                    item["text"] for item in line_words
                ).strip()

                if not line_text:
                    continue

                cell_lines.append({
                    "row_index": row_index,
                    "text": line_text,
                    "words": [
                        item["source"] for item in line_words
                    ],
                })

            cell_text = "\n".join(
                line["text"] for line in cell_lines
            )

            source_words = [
                word
                for line in cell_lines
                for word in line["words"]
            ]

            geometries = [
                _get_word_geometry(word)
                for word in source_words
            ]

            geometries = [
                item for item in geometries
                if item is not None
            ]

            if geometries:
                cell_bbox = [
                    min(item["x0"] for item in geometries),
                    min(item["y0"] for item in geometries),
                    max(item["x1"] for item in geometries),
                    max(item["y1"] for item in geometries),
                ]
            else:
                cell_bbox = None

            reconstructed_cells.append({
                "cell_id": (
                    f"{original_record.get('record_id', 'record')}"
                    f"_column_{column_index + 1}"
                ),
                "column_index": column_index,
                "text": cell_text,
                "lines": cell_lines,
                "bbox": cell_bbox,
                "word_count": len(source_words),
                "is_header_candidate": _is_header_candidate(
                    cell_text
                ),
            })

        # --------------------------------------------------
        # 5. Build semantic input without discarding geometry.
        # --------------------------------------------------

        semantic_lines = []

        for cell in reconstructed_cells:
            for line in cell["lines"]:
                semantic_lines.append({
                    "text": line["text"],
                    "words": line["words"],
                    "cell_index": cell["column_index"],
                    "cell_id": cell["cell_id"],
                    "cell_bbox": cell["bbox"],
                    "is_header_candidate": (
                        cell["is_header_candidate"]
                    ),
                })

        reconstructed_records.append({
            **original_record,
            "cells": reconstructed_cells,
            "lines": semantic_lines,
        })

    # --------------------------------------------------
    # 6. Summarize the inferred structure.
    # --------------------------------------------------

    column_count = (
        len(column_positions) + 1
        if column_positions
        else 0
    )

    diagnostics = {
        "layout_type": layout_type,
        "record_count": len(reconstructed_records),
        "column_count": column_count,
        "column_start_positions": [
            round(value, 2)
            for value in column_positions
        ],
        "column_evidence": column_starts,
        "median_text_height": round(median_height, 2),
        "gap_threshold": round(gap_threshold, 2),
        "used_column_inference": use_column_inference,
        "reason": (
            "Recurring horizontal gaps were used to infer columns."
            if column_positions
            else
            "No recurring column boundaries met the evidence threshold; "
            "visual rows were preserved without forced column splitting."
        ),
    }

    return {
        "records": reconstructed_records,
        "column_starts": column_starts,
        "diagnostics": diagnostics,
    }