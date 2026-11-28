
import re
from statistics import median

from pdf_document_engine import analyze_pdf_document
from pdf_structure_analyzer import analyze_page_structure

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


def _normalize_reconstructed_records(records, median_height):
    """
    Organize reconstructed candidates into generic, record-relative
    fields. No football-specific field interpretation occurs here.

    Original source words and fragments are preserved.
    """

    record_rows = {}
    observations = []
    total_visual_rows = 0

    gap_threshold = max(5.0, median_height * 1.35)
    relative_tolerance = 0.035

    for record in records:
        record_id = record.get("record_id")
        source_words = record.get("source_words", [])
        record_bbox = record.get("bbox")

        if not record_bbox or len(record_bbox) != 4:
            record_rows[record_id] = []
            continue

        record_x0, _, record_x1, _ = map(float, record_bbox)
        record_width = max(1.0, record_x1 - record_x0)

        geometries = [
            geometry
            for geometry in (
                _word_geometry(word)
                for word in source_words
            )
            if geometry is not None
        ]

        rows = _group_visual_rows(
            geometries,
            max(2.0, median_height * 0.65),
        )

        record_rows[record_id] = rows
        total_visual_rows += len(rows)

        for row_index, row in enumerate(rows):
            row_key = f"{record_id}:{row_index}"

            for left, right in zip(row, row[1:]):
                gap = right["x0"] - left["x1"]

                if gap < gap_threshold:
                    continue

                relative_x = (
                    right["x0"] - record_x0
                ) / record_width

                if 0.02 < relative_x < 0.98:
                    observations.append({
                        "x": relative_x,
                        "record_id": record_id,
                        "row_key": row_key,
                        "gap": gap,
                    })

    # Cluster recurring relative gaps across candidates.
    clusters = []

    for observation in sorted(
        observations,
        key=lambda item: item["x"],
    ):
        matching = None

        for cluster in clusters:
            center = median(
                item["x"] for item in cluster
            )

            if abs(observation["x"] - center) <= relative_tolerance:
                matching = cluster
                break

        if matching is None:
            clusters.append([observation])
        else:
            matching.append(observation)

    boundaries = []
    minimum_record_support = 2 if len(records) > 1 else 1

    for cluster in clusters:
        record_support = len({
            item["record_id"] for item in cluster
        })

        row_support = len({
            item["row_key"] for item in cluster
        })

        if (
            record_support >= minimum_record_support
            or row_support >= 2
        ):
            boundaries.append({
                "x": median(item["x"] for item in cluster),
                "record_support": record_support,
                "row_support": row_support,
                "observations": len(cluster),
            })

    boundaries.sort(key=lambda item: item["x"])

    column_count = len(boundaries) + 1

    columns = [
        {
            "column_index": index,
            "label": f"Field {index + 1}",
            "x_start_relative": (
                boundaries[index - 1]["x"]
                if index > 0
                else 0.0
            ),
        }
        for index in range(column_count)
    ]

    normalized_records = {}

    for record in records:
        record_id = record.get("record_id")
        rows = record_rows.get(record_id, [])
        record_bbox = record.get("bbox")

        if not record_bbox:
            normalized_records[record_id] = []
            continue

        record_x0, _, record_x1, _ = map(float, record_bbox)
        record_width = max(1.0, record_x1 - record_x0)

        field_fragments = [
            [] for _ in range(column_count)
        ]

        for visual_row_index, row in enumerate(rows):
            cell_words = [
                [] for _ in range(column_count)
            ]

            for word in row:
                relative_x = (
                    word["x0"] - record_x0
                ) / record_width

                column_index = 0

                for boundary_index, boundary in enumerate(boundaries):
                    if relative_x >= boundary["x"] - relative_tolerance:
                        column_index = boundary_index + 1

                cell_words[column_index].append(word)

            for column_index, words in enumerate(cell_words):
                if not words:
                    continue

                words.sort(key=lambda item: item["x0"])

                bbox = [
                    min(item["x0"] for item in words),
                    min(item["y0"] for item in words),
                    max(item["x1"] for item in words),
                    max(item["y1"] for item in words),
                ]

                field_fragments[column_index].append({
                    "visual_row_index": visual_row_index,
                    "text": " ".join(
                        item["text"] for item in words
                    ),
                    "bbox": bbox,
                    "source_words": [
                        item["source"] for item in words
                    ],
                })

        normalized_fields = []

        for column_index, fragments in enumerate(field_fragments):
            source_words = [
                word
                for fragment in fragments
                for word in fragment["source_words"]
            ]

            boxes = [
                fragment["bbox"]
                for fragment in fragments
                if fragment.get("bbox")
            ]

            field_bbox = None

            if boxes:
                field_bbox = [
                    min(box[0] for box in boxes),
                    min(box[1] for box in boxes),
                    max(box[2] for box in boxes),
                    max(box[3] for box in boxes),
                ]

            normalized_fields.append({
                "field_index": column_index,
                "label": f"Field {column_index + 1}",
                "text": "\n".join(
                    fragment["text"]
                    for fragment in fragments
                ),
                "fragments": fragments,
                "source_words": source_words,
                "bbox": field_bbox,
                "word_count": len(source_words),
                "contributing_visual_rows": [
                    fragment["visual_row_index"]
                    for fragment in fragments
                ],
            })

        normalized_records[record_id] = normalized_fields

    return {
        "strategy": "record_relative_alignment",
        "column_count": column_count,
        "columns": columns,
        "records": normalized_records,
        "diagnostics": {
            "records_processed": len(records),
            "visual_rows_processed": total_visual_rows,
            "relative_column_boundaries": boundaries,
            "gap_threshold": round(gap_threshold, 2),
            "relative_position_tolerance": relative_tolerance,
        },
    }


def _bbox_union(boxes):
    """Return the bounding box enclosing all valid boxes."""

    valid = [
        box for box in boxes
        if isinstance(box, (list, tuple)) and len(box) == 4
    ]

    if not valid:
        return None

    return [
        min(float(box[0]) for box in valid),
        min(float(box[1]) for box in valid),
        max(float(box[2]) for box in valid),
        max(float(box[3]) for box in valid),
    ]


def _table_row_source_lines(row):
    """Collect source lines from every cell in a structural table row."""

    result = []

    for cell in row.get("cells", []):
        result.extend(cell.get("source_lines", []))

    return result


def _build_structural_regions(structure_page):
    """
    Convert domain-neutral structural detections into regions
    that the roster-specific reconstruction layer can process.

    A table row is kept separate from the rest of its table.
    """

    if not structure_page:
        return []

    regions = []

    def add_region(region_type, bbox, source_lines=None, evidence=None):
        source_lines = source_lines or []

        unique_lines = []
        seen = set()

        for line in source_lines:
            line_bbox = line.get("bbox")
            text = str(line.get("text", "")).strip()

            if not line_bbox or len(line_bbox) != 4:
                continue

            key = (
                tuple(round(float(value), 2) for value in line_bbox),
                text,
            )

            if key in seen:
                continue

            seen.add(key)
            unique_lines.append(line)

        line_boxes = [
            line["bbox"]
            for line in unique_lines
        ]

        if not bbox:
            bbox = _bbox_union(line_boxes)

        if not bbox:
            return

        regions.append({
            "region_id": f"region_{len(regions) + 1}",
            "region_type": region_type,
            "bbox": list(map(float, bbox)),
            "source_lines": unique_lines,
            "_line_boxes": line_boxes,
            "evidence": evidence or {},
        })

    # --------------------------------------------------
    # TABLES: create one structural region per table row.
    # --------------------------------------------------

    for table in structure_page.get("tables", []):
        table_bbox = table.get("bbox")
        rows = table.get("rows", [])
        row_boundaries = table.get("row_boundaries", [])

        if rows:
            for row_index, row in enumerate(rows):
                source_lines = _table_row_source_lines(row)

                row_bbox = row.get("bbox")

                if not row_bbox and (
                    table_bbox
                    and len(row_boundaries) > row_index + 1
                ):
                    row_bbox = [
                        table_bbox[0],
                        row_boundaries[row_index],
                        table_bbox[2],
                        row_boundaries[row_index + 1],
                    ]

                add_region(
                    "table_row",
                    row_bbox,
                    source_lines,
                    {
                        "table_index": table.get("table_index"),
                        "row_index": row_index,
                        "structure_type": table.get("structure_type"),
                    },
                )

        elif (
            table_bbox
            and len(row_boundaries) >= 2
        ):
            for row_index in range(len(row_boundaries) - 1):
                row_bbox = [
                    table_bbox[0],
                    row_boundaries[row_index],
                    table_bbox[2],
                    row_boundaries[row_index + 1],
                ]

                add_region(
                    "table_row",
                    row_bbox,
                    evidence={
                        "table_index": table.get("table_index"),
                        "row_index": row_index,
                    },
                )

        else:
            add_region(
                "table",
                table_bbox,
                evidence={
                    "table_index": table.get("table_index"),
                },
            )

    # --------------------------------------------------
    # REPEATED OUTLINED CONTAINERS.
    # --------------------------------------------------

    for container in structure_page.get("containers", []):
        add_region(
            "container",
            container.get("bbox"),
            container.get("source_lines", []),
            {
                "container_index": container.get("container_index"),
                "container_type": container.get("container_type"),
                "detection_evidence": container.get(
                    "detection_evidence", {}
                ),
            },
        )

    # --------------------------------------------------
    # SEPARATOR-DELIMITED REGIONS.
    # --------------------------------------------------

    for separator in structure_page.get("separator_regions", []):
        add_region(
            "separator_region",
            separator.get("bbox"),
            separator.get("source_lines", []),
            {
                "region_index": separator.get("region_index"),
                "assignment_confidence": separator.get(
                    "assignment_confidence"
                ),
                "detection_evidence": separator.get(
                    "detection_evidence", {}
                ),
            },
        )

    # --------------------------------------------------
    # REMAINING UNCLASSIFIED TEXT REGIONS.
    # --------------------------------------------------

    for text_region in structure_page.get("text_regions", []):
        add_region(
            "text_region",
            text_region.get("bbox"),
            text_region.get("source_lines", []),
            {
                "region_index": text_region.get("region_index"),
                "interpretation_status": "unclassified",
            },
        )

    regions.sort(
        key=lambda region: (
            region["bbox"][1],
            region["bbox"][0],
        )
    )

    return regions


def _point_inside_bbox(x, y, bbox, tolerance=1.5):
    """Check whether a point lies inside a bounding box."""

    return (
        bbox[0] - tolerance <= x <= bbox[2] + tolerance
        and bbox[1] - tolerance <= y <= bbox[3] + tolerance
    )


def _assign_words_to_structural_regions(geometries, structure_page):
    """
    Assign each word to at most one structural region.

    Source-line geometry is preferred over broad region geometry.
    Words that cannot be assigned are preserved in a page-remainder
    region rather than discarded.
    """

    regions = _build_structural_regions(structure_page)

    if not regions:
        if not geometries:
            return []

        return [{
            "region_id": "page_fallback",
            "region_type": "page_remainder",
            "bbox": _bbox_union([
                [
                    item["x0"],
                    item["y0"],
                    item["x1"],
                    item["y1"],
                ]
                for item in geometries
            ]),
            "evidence": {
                "reason": "No usable structural regions were detected.",
            },
            "geometries": list(geometries),
        }]

    for region in regions:
        region["geometries"] = []

    remainder = []

    for geometry in geometries:
        center_x = geometry["cx"]
        center_y = geometry["cy"]

        matches = []

        for region in regions:
            line_matches = [
                bbox
                for bbox in region["_line_boxes"]
                if _point_inside_bbox(
                    center_x,
                    center_y,
                    bbox,
                )
            ]

            if line_matches:
                best_box = min(
                    line_matches,
                    key=lambda box: (
                        max(0.0, box[2] - box[0])
                        * max(0.0, box[3] - box[1])
                    ),
                )

                area = (
                    max(0.0, best_box[2] - best_box[0])
                    * max(0.0, best_box[3] - best_box[1])
                )

                matches.append((area, region))
                continue

            # Only use a broad region bbox when it has no
            # source-line geometry to provide a better match.
            if (
                not region["_line_boxes"]
                and _point_inside_bbox(
                    center_x,
                    center_y,
                    region["bbox"],
                )
            ):
                bbox = region["bbox"]
                area = (
                    max(0.0, bbox[2] - bbox[0])
                    * max(0.0, bbox[3] - bbox[1])
                )

                matches.append((area, region))

        if matches:
            matches.sort(
                key=lambda item: (
                    item[0],
                    item[1]["bbox"][1],
                    item[1]["bbox"][0],
                )
            )

            matches[0][1]["geometries"].append(geometry)
        else:
            remainder.append(geometry)

    regions = [
        region
        for region in regions
        if region["geometries"]
    ]

    if remainder:
        regions.append({
            "region_id": "page_remainder",
            "region_type": "page_remainder",
            "bbox": _bbox_union([
                [
                    item["x0"],
                    item["y0"],
                    item["x1"],
                    item["y1"],
                ]
                for item in remainder
            ]),
            "evidence": {
                "reason": "Words not assigned to a detected structural region.",
            },
            "geometries": remainder,
        })

    return regions


def _lane_anchor_support(rows):
    """
    Count rows that independently resemble record anchors.

    This is used only to decide whether a horizontal whitespace
    gap separates two parallel content lanes.
    """

    support = 0

    for row in rows:
        features = _row_features([], _row_text(row))

        signal_count = sum([
            features["has_position"],
            features["has_height"],
            features["has_weight"],
            features["has_class"],
        ])

        if (
            features["is_anchor"]
            or (
                features["has_name_like_text"]
                and signal_count >= 2
            )
        ):
            support += 1

    return support


def _detect_parallel_lanes(geometries, median_height):
    """
    Detect independent left/right content lanes.

    A gap is accepted only when both sides independently contain
    record-like evidence. Ordinary gaps between fields should not
    qualify merely because they are wide.
    """

    if len(geometries) < 4:
        return None

    row_tolerance = max(2.0, median_height * 0.65)

    rows = _group_visual_rows(
        geometries,
        row_tolerance,
    )

    if not rows:
        return None

    region_bbox = _bbox_union([
        [
            item["x0"],
            item["y0"],
            item["x1"],
            item["y1"],
        ]
        for item in geometries
    ])

    if not region_bbox:
        return None

    region_width = max(
        1.0,
        region_bbox[2] - region_bbox[0],
    )

    gap_threshold = max(
        12.0,
        median_height * 2.0,
    )

    observations = []

    for row_index, row in enumerate(rows):
        for left, right in zip(row, row[1:]):
            gap = right["x0"] - left["x1"]

            if gap < gap_threshold:
                continue

            split_x = (left["x1"] + right["x0"]) / 2

            relative_x = (
                split_x - region_bbox[0]
            ) / region_width

            # A parallel-lane divider should not sit at an
            # extreme edge of the region.
            if not 0.20 <= relative_x <= 0.80:
                continue

            observations.append({
                "x": split_x,
                "row": row_index,
                "gap": gap,
            })

    if not observations:
        return None

    minimum_support = (
        1 if len(rows) == 1
        else max(2, int(len(rows) * 0.20))
    )

    candidates = _cluster_positions(
        observations,
        max(4.0, median_height * 0.8),
        minimum_support,
    )

    accepted = []

    for candidate in candidates:
        split_x = candidate["x"]

        left_words = [
            item for item in geometries
            if item["cx"] < split_x
        ]

        right_words = [
            item for item in geometries
            if item["cx"] >= split_x
        ]

        if len(left_words) < 3 or len(right_words) < 3:
            continue

        left_rows = _group_visual_rows(
            left_words,
            row_tolerance,
        )

        right_rows = _group_visual_rows(
            right_words,
            row_tolerance,
        )

        left_anchor_support = _lane_anchor_support(left_rows)
        right_anchor_support = _lane_anchor_support(right_rows)

        if left_anchor_support < 1 or right_anchor_support < 1:
            continue

        paired_rows = 0

        for row in rows:
            has_left = any(
                item["cx"] < split_x for item in row
            )
            has_right = any(
                item["cx"] >= split_x for item in row
            )

            if has_left and has_right:
                paired_rows += 1

        if paired_rows < 1:
            continue

        left_y0 = min(item["y0"] for item in left_words)
        left_y1 = max(item["y1"] for item in left_words)

        right_y0 = min(item["y0"] for item in right_words)
        right_y1 = max(item["y1"] for item in right_words)

        overlap = max(
            0.0,
            min(left_y1, right_y1) - max(left_y0, right_y0),
        )

        shorter_extent = max(
            1.0,
            min(left_y1 - left_y0, right_y1 - right_y0),
        )

        overlap_ratio = overlap / shorter_extent

        if overlap_ratio < 0.35:
            continue

        score = (
            candidate["row_support"] * 2
            + paired_rows
            + left_anchor_support
            + right_anchor_support
            + min(2.0, candidate["observations"] * 0.25)
        )

        accepted.append({
            "split_x": split_x,
            "score": score,
            "row_support": candidate["row_support"],
            "paired_rows": paired_rows,
            "left_anchor_support": left_anchor_support,
            "right_anchor_support": right_anchor_support,
            "overlap_ratio": round(overlap_ratio, 3),
        })

    if not accepted:
        return None

    accepted.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    best = accepted[0]
    split_x = best["split_x"]

    return {
        "lanes": [
            {
                "lane_index": 0,
                "x_min": region_bbox[0],
                "x_max": split_x,
            },
            {
                "lane_index": 1,
                "x_min": split_x,
                "x_max": region_bbox[2],
            },
        ],
        "evidence": best,
    }





def _reconstruct_page(page_number, source_words, structure_page=None):
    """
    Reconstruct candidate records using document structure first,
    spatial lanes second, and roster-like evidence third.

    No source word is silently discarded.
    """

    geometries = [
        item
        for item in (
            _word_geometry(word)
            for word in source_words
        )
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
            "normalization": {
                "strategy": "record_relative_alignment",
                "column_count": 0,
                "columns": [],
                "records": {},
                "diagnostics": {
                    "records_processed": 0,
                    "visual_rows_processed": 0,
                    "reason": "No usable word geometry was extracted.",
                },
            },
            "unassigned_text": "",
            "unassigned_content": [],
            "structure": structure_page or {},
            "diagnostics": {
                "word_count": 0,
                "row_count": 0,
                "record_count": 0,
                "column_count": 0,
                "structural_region_count": 0,
                "parallel_lane_count": 0,
                "reason": "No usable word geometry was extracted.",
            },
        }

    median_height = median(
        item["height"] for item in geometries
    )

    row_tolerance = max(
        2.0,
        median_height * 0.65,
    )

    # --------------------------------------------------
    # 1. BUILD PAGE-LEVEL VISUAL ROWS.
    #
    # These are retained for the inspector and diagnostics.
    # They are not used as the primary record boundaries.
    # --------------------------------------------------

    page_rows = _group_visual_rows(
        geometries,
        row_tolerance,
    )

    page_column_starts, gap_threshold, position_tolerance = (
        _detect_columns(
            page_rows,
            median_height,
        )
    )

    visual_rows = []
    source_to_global_row = {}

    for row_index, row in enumerate(page_rows):
        cells = _split_row_into_cells(
            row,
            page_column_starts,
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
            cell for cell in cells
            if cell["text"]
        ]

        header_hits = sum(
            1
            for cell in nonempty_cells
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

        source_row_words = [
            word["source"] for word in row
        ]

        for word in source_row_words:
            source_to_global_row[id(word)] = row_index

        visual_rows.append({
            "row_index": row_index,
            "text": text,
            "cells": cells,
            "bbox": bbox,
            "word_count": len(row),
            "is_header_candidate": is_header,
            "is_metadata_candidate": is_metadata,
            "source_words": source_row_words,
            "features": features,
        })

    # --------------------------------------------------
    # 2. ASSIGN WORDS TO STRUCTURAL REGIONS.
    # --------------------------------------------------

    structural_regions = _assign_words_to_structural_regions(
        geometries,
        structure_page,
    )

    records = []
    assigned_word_ids = set()

    candidate_number = 0
    parallel_lane_count = 0
    region_diagnostics = []

    base_segmentation_scores = {
        "table_row": 0.92,
        "table": 0.82,
        "container": 0.88,
        "separator_region": 0.84,
        "text_region": 0.62,
        "page_remainder": 0.42,
    }

    # --------------------------------------------------
    # 3. PROCESS EACH STRUCTURAL REGION INDEPENDENTLY.
    # --------------------------------------------------

    for region in structural_regions:
        region_geometries = region.get("geometries", [])

        if not region_geometries:
            continue

        region_type = region.get(
            "region_type",
            "page_remainder",
        )

        lane_result = _detect_parallel_lanes(
            region_geometries,
            median_height,
        )

        if lane_result:
            lane_specs = lane_result["lanes"]
            lane_evidence = lane_result["evidence"]
            parallel_lane_count += len(lane_specs)
        else:
            region_bbox = _bbox_union([
                [
                    item["x0"],
                    item["y0"],
                    item["x1"],
                    item["y1"],
                ]
                for item in region_geometries
            ])

            lane_specs = [{
                "lane_index": 0,
                "x_min": region_bbox[0],
                "x_max": region_bbox[2],
            }]

            lane_evidence = None

        region_record_count = 0

        # --------------------------------------------------
        # 4. PROCESS EACH LANE SEPARATELY.
        # --------------------------------------------------

        for lane in lane_specs:
            lane_geometries = [
                item
                for item in region_geometries
                if (
                    lane["x_min"] - 1.0
                    <= item["cx"]
                    < lane["x_max"] + 1.0
                )
            ]

            if not lane_geometries:
                continue

            lane_rows = _group_visual_rows(
                lane_geometries,
                row_tolerance,
            )

            lane_columns, lane_gap_threshold, lane_tolerance = (
                _detect_columns(
                    lane_rows,
                    median_height,
                )
            )

            candidate_rows = []

            for local_row_index, row in enumerate(lane_rows):
                cells = _split_row_into_cells(
                    row,
                    lane_columns,
                    lane_tolerance,
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
                    cell for cell in cells
                    if cell["text"]
                ]

                header_hits = sum(
                    1
                    for cell in nonempty_cells
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

                source_row_words = [
                    word["source"] for word in row
                ]

                global_row_indices = [
                    source_to_global_row[id(word)]
                    for word in source_row_words
                    if id(word) in source_to_global_row
                ]

                global_row_index = (
                    min(global_row_indices)
                    if global_row_indices
                    else -1
                )

                candidate_rows.append({
                    "row_index": global_row_index,
                    "region_row_index": local_row_index,
                    "text": text,
                    "cells": cells,
                    "bbox": bbox,
                    "word_count": len(row),
                    "is_header_candidate": is_header,
                    "is_metadata_candidate": is_metadata,
                    "source_words": source_row_words,
                    "features": features,
                })

            eligible_rows = [
                row
                for row in candidate_rows
                if (
                    not row["is_header_candidate"]
                    and not row["is_metadata_candidate"]
                )
            ]

            if not eligible_rows:
                continue

            # --------------------------------------------------
            # 5. FIND ANCHORS WITHIN THIS LANE ONLY.
            # --------------------------------------------------

            anchors = [
                row
                for row in eligible_rows
                if row["features"]["is_anchor"]
            ]

            used_fallback_anchors = False

            if not anchors:
                fallback_anchors = [
                    row
                    for row in eligible_rows
                    if (
                        row["features"]["score"] >= 5
                        and len([
                            cell for cell in row["cells"]
                            if cell["text"]
                        ]) >= 2
                    )
                ]

                if fallback_anchors:
                    anchors = fallback_anchors
                    used_fallback_anchors = True

            anchors.sort(
                key=lambda row: (
                    row["bbox"][1],
                    row["bbox"][0],
                )
            )

            if not anchors:
                continue

            # --------------------------------------------------
            # 6. BUILD RECORD GROUPS.
            #
            # A structural table row is already a record-sized
            # region unless it contains independently detected
            # parallel lanes.
            #
            # Other regions use vertical anchor bands, but only
            # within their own lane.
            # --------------------------------------------------

            record_groups = []

            if (
                region_type == "table_row"
                and len(anchors) == 1
            ):
                record_groups.append((
                    anchors[0],
                    eligible_rows,
                ))

            else:
                anchor_centers = [
                    (
                        row["bbox"][1]
                        + row["bbox"][3]
                    ) / 2
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
                        row
                        for row in eligible_rows
                        if (
                            top
                            < (
                                row["bbox"][1]
                                + row["bbox"][3]
                            ) / 2
                            <= bottom
                        )
                    ]

                    if group:
                        record_groups.append((anchor, group))

            # --------------------------------------------------
            # 7. CREATE CANDIDATE RECORDS.
            # --------------------------------------------------

            for anchor, group in record_groups:
                if not group:
                    continue

                record = _merge_record_rows(
                    page_number,
                    group,
                    anchor["row_index"],
                )

                candidate_number += 1
                region_record_count += 1

                record["record_id"] = (
                    f"page_{page_number}_"
                    f"candidate_{candidate_number}"
                )

                record["record_features"] = (
                    anchor["features"]
                )

                content_score = (
                    anchor["features"]["score"]
                )

                content_confidence_score = min(
                    1.0,
                    content_score / 10.0,
                )

                segmentation_score = (
                    base_segmentation_scores.get(
                        region_type,
                        0.50,
                    )
                )

                if lane_result:
                    segmentation_score = 0.78

                if len(anchors) > 1:
                    segmentation_score += 0.03

                if used_fallback_anchors:
                    segmentation_score -= 0.08

                segmentation_score = max(
                    0.0,
                    min(1.0, segmentation_score),
                )

                if segmentation_score >= 0.85:
                    segmentation_label = "high"
                elif segmentation_score >= 0.65:
                    segmentation_label = "medium"
                else:
                    segmentation_label = "low"

                record["confidence"] = segmentation_label

                # Keep the legacy field, but make it represent
                # segmentation evidence rather than content clues.
                record["confidence_score"] = round(
                    segmentation_score,
                    3,
                )

                record["content_confidence_score"] = round(
                    content_confidence_score,
                    3,
                )

                record["segmentation_confidence"] = (
                    segmentation_label
                )

                record["segmentation_score"] = round(
                    segmentation_score,
                    3,
                )

                record["segmentation_method"] = (
                    "structural_region_parallel_lane"
                    if lane_result
                    else f"structural_region_{region_type}"
                )

                record["structural_region_id"] = (
                    region["region_id"]
                )

                record["structural_region_type"] = (
                    region_type
                )

                record["structural_region_bbox"] = (
                    region.get("bbox")
                )

                record["lane_index"] = lane["lane_index"]

                record["lane_count"] = len(lane_specs)

                record["lane_bounds"] = [
                    lane["x_min"],
                    lane["x_max"],
                ]

                record["boundary_evidence"] = {
                    "region_type": region_type,
                    "region_evidence": region.get(
                        "evidence", {}
                    ),
                    "parallel_lane_evidence": lane_evidence,
                    "anchor_count_in_lane": len(anchors),
                    "used_fallback_anchor": used_fallback_anchors,
                    "group_row_count": len(group),
                }

                record["review_required"] = True

                records.append(record)

                for word in record.get("source_words", []):
                    assigned_word_ids.add(id(word))

        region_diagnostics.append({
            "region_id": region["region_id"],
            "region_type": region_type,
            "word_count": len(region_geometries),
            "candidate_record_count": region_record_count,
            "lane_split": bool(lane_result),
            "lane_evidence": lane_evidence,
        })

    # --------------------------------------------------
    # 8. GENERIC NORMALIZATION.
    #
    # This happens only after candidate boundaries exist.
    # --------------------------------------------------

    normalization = _normalize_reconstructed_records(
        records,
        median_height,
    )

    for record in records:
        record["normalized_fields"] = (
            normalization["records"].get(
                record["record_id"],
                [],
            )
        )

    # --------------------------------------------------
    # 9. PRESERVE EVERY WORD NOT ASSIGNED TO A CANDIDATE.
    # --------------------------------------------------

    unassigned_geometries = [
        geometry
        for geometry in geometries
        if id(geometry["source"]) not in assigned_word_ids
    ]

    unassigned_rows = _group_visual_rows(
        unassigned_geometries,
        row_tolerance,
    )

    unassigned_content = []

    for row in unassigned_rows:
        text = _row_text(row)

        source_row_words = [
            word["source"] for word in row
        ]

        global_indices = [
            source_to_global_row[id(word)]
            for word in source_row_words
            if id(word) in source_to_global_row
        ]

        global_row_index = (
            min(global_indices)
            if global_indices
            else -1
        )

        if _is_page_metadata(text):
            reason = "page metadata"
        elif _is_header_text(text):
            reason = "header or field label"
        else:
            reason = "no sufficiently supported record boundary"

        unassigned_content.append({
            "page_number": page_number,
            "row_index": global_row_index,
            "text": text,
            "bbox": [
                min(item["x0"] for item in row),
                min(item["y0"] for item in row),
                max(item["x1"] for item in row),
                max(item["y1"] for item in row),
            ],
            "reason": reason,
            "source_words": source_row_words,
        })

    # --------------------------------------------------
    # 10. FINAL PAGE RESULT.
    # --------------------------------------------------

    structure_type = (
        structure_page.get("structure_type")
        if structure_page
        else "unavailable"
    )

    return {
        "page_number": page_number,
        "source_words": source_words,
        "visual_rows": visual_rows,
        "rows": visual_rows,
        "records": records,
        "columns": page_column_starts,
        "normalization": normalization,
        "structure": structure_page or {},
        "structural_regions": region_diagnostics,
        "unassigned_text": "\n".join(
            item["text"]
            for item in unassigned_content
        ),
        "unassigned_content": unassigned_content,
        "diagnostics": {
            "word_count": len(geometries),
            "row_count": len(visual_rows),
            "record_count": len(records),
            "column_count": len(page_column_starts) + 1,
            "anchor_count": sum(
                1
                for record in records
                if record.get("record_features", {}).get(
                    "is_anchor"
                )
            ),
            "median_text_height": round(median_height, 2),
            "row_tolerance": round(row_tolerance, 2),
            "gap_threshold": round(gap_threshold, 2),
            "column_boundaries": page_column_starts,
            "structure_type": structure_type,
            "structural_region_count": len(structural_regions),
            "parallel_lane_count": parallel_lane_count,
            "assigned_word_count": len(assigned_word_ids),
            "unassigned_word_count": len(unassigned_geometries),
            "segmentation_strategy": (
                "structure_first_region_and_lane_segmentation"
            ),
            "reason": (
                "Candidate records were reconstructed inside "
                "structural regions and independently supported "
                "horizontal lanes. Generic normalization followed "
                "candidate reconstruction."
                if records
                else
                "No sufficiently supported record boundaries "
                "were found. All extracted words remain available "
                "in unassigned content."
            ),
        },
    }




def analyze_roster_pdf(pdf_path):
    """
    Analyze the complete PDF using the shared document engine,
    the domain-neutral structure analyzer, and roster-specific
    reconstruction.
    """

    document_result = analyze_pdf_document(pdf_path)

    pages = []
    structural_analysis_errors = []

    for document_page in document_result.get("pages", []):
        page_number = document_page["page_number"]
        source_words = document_page.get("words", [])

        structure_page = None

        try:
            structure_page = analyze_page_structure(
                document_page
            )
        except Exception as error:
            structural_analysis_errors.append({
                "page_number": page_number,
                "error": (
                    f"{type(error).__name__}: {error}"
                ),
            })

        page_result = _reconstruct_page(
            page_number,
            source_words,
            structure_page=structure_page,
        )

        if structure_page is None:
            page_result["diagnostics"]["structure_error"] = (
                structural_analysis_errors[-1]["error"]
            )

        pages.append(page_result)

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
        page["diagnostics"]["word_count"]
        for page in pages
    )

    assigned_words = sum(
        page["diagnostics"]["assigned_word_count"]
        for page in pages
    )

    unassigned_words = sum(
        page["diagnostics"]["unassigned_word_count"]
        for page in pages
    )

    return {
        "pdf_path": document_result["file_path"],
        "page_count": len(pages),
        "pages": pages,
        "records": all_records,
        "unassigned_content": all_unassigned,
        "diagnostics": {
            "total_words": total_words,
            "assigned_words": assigned_words,
            "unassigned_words": unassigned_words,
            "total_candidate_records": len(all_records),
            "pages_with_records": sum(
                bool(page["records"])
                for page in pages
            ),
            "structural_analysis_errors": (
                structural_analysis_errors
            ),
            "message": (
                "Automatic structural and roster reconstruction "
                "completed. Candidate boundaries have separate "
                "confidence evidence and still require review."
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
