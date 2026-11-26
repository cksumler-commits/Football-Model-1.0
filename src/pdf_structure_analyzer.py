
"""
Universal PDF Structure Analyzer

Responsibilities:
- Reconstruct document structure using multiple sources of evidence.
- Detect ruled tables and filled-cell tables.
- Identify text regions outside detected tables.
- Assign text to reconstructed rows and columns.
- Preserve source coordinates and extraction evidence.
- Report uncertainty rather than silently guessing.

This module is domain-neutral. It does not know about football,
rosters, schools, or specific document types.
"""

import sys
from pathlib import Path
from collections import defaultdict
from statistics import median

from pdf_document_engine import analyze_pdf_document
import argparse


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

GEOMETRY_TOLERANCE = 1.5
MAX_LINE_THICKNESS = 2.0
MIN_LINE_LENGTH = 10.0
MIN_BOUNDARY_LENGTH = 100.0
MIN_TABLE_WIDTH = 40.0

# Filled rectangle detection
MIN_CELL_WIDTH = 8.0
MIN_CELL_HEIGHT = 8.0
MAX_CELL_PAGE_AREA_RATIO = 0.25

RECTANGLE_ROW_TOLERANCE = 3.0
RECTANGLE_COLUMN_TOLERANCE = 8.0
MIN_RECTANGLES_PER_ROW = 3
MIN_ROWS_PER_FILLED_TABLE = 2

# Text grouping
TEXT_REGION_GAP_MULTIPLIER = 2.5
TEXT_REGION_MIN_GAP = 8.0
# Repeated outlined-container detection
MIN_CONTAINER_WIDTH = 80.0
MIN_CONTAINER_HEIGHT = 18.0
MAX_CONTAINER_HEIGHT_RATIO = 0.25
MIN_CONTAINER_ASPECT_RATIO = 2.5
CONTAINER_ALIGNMENT_TOLERANCE = 5.0
MIN_REPEATED_CONTAINERS = 2
# Separator-delimited region detection
MIN_SEPARATOR_LENGTH = 100.0
MIN_REPEATED_SEPARATORS = 4
SEPARATOR_ALIGNMENT_TOLERANCE = 8.0
MIN_SEPARATOR_REGIONS = 3
SEPARATOR_CONTENT_PADDING = 2.0



# ------------------------------------------------------------
# BASIC GEOMETRY HELPERS
# ------------------------------------------------------------

def get_bbox_coordinates(item):
    """Extract coordinates from supported bounding-box formats."""

    bbox = item.get("bbox")

    if isinstance(bbox, dict):
        return bbox.get("coordinates")

    if isinstance(bbox, (list, tuple)):
        return bbox

    return None


def normalize_bbox(bbox):
    """Return a normalized [x0, y0, x1, y1] bounding box."""

    if isinstance(bbox, dict):
        bbox = bbox.get("coordinates")

    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None

    try:
        x0, y0, x1, y1 = map(float, bbox[:4])
    except (TypeError, ValueError):
        return None

    return [
        min(x0, x1),
        min(y0, y1),
        max(x0, x1),
        max(y0, y1),
    ]


def bbox_width(bbox):
    return max(0.0, bbox[2] - bbox[0])


def bbox_height(bbox):
    return max(0.0, bbox[3] - bbox[1])


def bbox_area(bbox):
    return bbox_width(bbox) * bbox_height(bbox)


def bbox_intersection_area(first, second):
    """Calculate the intersection area of two bounding boxes."""

    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])

    if x1 <= x0 or y1 <= y0:
        return 0.0

    return (x1 - x0) * (y1 - y0)


def bbox_overlap_ratio(first, second):
    """
    Intersection relative to the smaller bounding box.

    Useful when a small cell rectangle sits inside a larger
    background rectangle.
    """

    intersection = bbox_intersection_area(first, second)

    smaller_area = min(
        bbox_area(first),
        bbox_area(second),
    )

    if smaller_area <= 0:
        return 0.0

    return intersection / smaller_area


def cluster_values(values, tolerance):
    """Cluster nearby numeric values and return their averages."""

    if not values:
        return []

    ordered = sorted(float(value) for value in values)
    groups = []

    for value in ordered:
        if not groups or abs(value - median(groups[-1])) > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)

    return [
        sum(group) / len(group)
        for group in groups
    ]


def cluster_segments(segments, coordinate_index, tolerance):
    """
    Group segments whose selected coordinate is close.

    Horizontal segments are grouped by Y.
    Vertical segments are grouped by X.
    """

    ordered = sorted(
        segments,
        key=lambda segment: segment[coordinate_index],
    )

    groups = []

    for segment in ordered:
        coordinate = segment[coordinate_index]
        matching_group = None

        for group in groups:
            group_center = sum(
                item[coordinate_index] for item in group
            ) / len(group)

            if abs(coordinate - group_center) <= tolerance:
                matching_group = group
                break

        if matching_group is None:
            groups.append([segment])
        else:
            matching_group.append(segment)

    return groups


def merge_intervals(intervals, tolerance=2.0):
    """Merge overlapping or nearly touching intervals."""

    if not intervals:
        return []

    intervals = sorted(intervals)
    merged = [list(intervals[0])]

    for start, end in intervals[1:]:
        current = merged[-1]

        if start <= current[1] + tolerance:
            current[1] = max(current[1], end)
        else:
            merged.append([start, end])

    return [
        (start, end)
        for start, end in merged
    ]


# ------------------------------------------------------------
# TEXT EXTRACTION
# ------------------------------------------------------------

def extract_text_lines(page):
    """
    Flatten extracted text blocks into individual lines.

    Original source positions and coordinates are retained.
    """

    text_lines = []

    for block_index, block in enumerate(page.get("blocks", [])):
        for line_index, line in enumerate(block.get("lines", [])):
            text = line.get("text", "").strip()
            bbox = normalize_bbox(line.get("bbox"))

            if not text or not bbox:
                continue

            text_lines.append({
                "text": text,
                "bbox": bbox,
                "block_index": block_index,
                "line_index": line.get(
                    "sequence_number",
                    line_index,
                ),
                "center_x": (bbox[0] + bbox[2]) / 2,
                "center_y": (bbox[1] + bbox[3]) / 2,
                "width": bbox_width(bbox),
                "height": bbox_height(bbox),
            })

    return sorted(
        text_lines,
        key=lambda item: (
            item["center_y"],
            item["bbox"][0],
        ),
    )


# ------------------------------------------------------------
# DRAWING INSPECTION
# ------------------------------------------------------------

def get_drawing_dimensions(drawing, bbox):
    """Get drawing dimensions, using its bbox as a fallback."""

    dimensions = drawing.get("bbox_dimensions") or {}

    return (
        float(dimensions.get("width", bbox_width(bbox))),
        float(dimensions.get("height", bbox_height(bbox))),
    )


def extract_geometry_segments(page):
    """
    Extract thin horizontal and vertical drawings.

    Returns:
        horizontal_segments: (center_y, x0, x1)
        vertical_segments: (center_x, y0, y1)
    """

    horizontal_segments = []
    vertical_segments = []

    for drawing in page.get("drawings", []):
        bbox = get_bbox_coordinates(drawing)
        bbox = normalize_bbox(bbox)

        if not bbox:
            continue

        x0, y0, x1, y1 = bbox
        width, height = get_drawing_dimensions(drawing, bbox)

        if height <= MAX_LINE_THICKNESS and width >= MIN_LINE_LENGTH:
            horizontal_segments.append((
                (y0 + y1) / 2,
                x0,
                x1,
            ))

        elif width <= MAX_LINE_THICKNESS and height >= MIN_LINE_LENGTH:
            vertical_segments.append((
                (x0 + x1) / 2,
                y0,
                y1,
            ))

    return horizontal_segments, vertical_segments


def extract_rectangle_drawings(page):
    """
    Extract rectangle-like drawings.

    The drawing bbox is used as the primary geometry source.
    Drawing metadata is preserved for later diagnostics.
    """

    rectangles = []

    for drawing_index, drawing in enumerate(page.get("drawings", [])):
        bbox = normalize_bbox(
            get_bbox_coordinates(drawing)
        )

        if not bbox:
            continue

        width, height = get_drawing_dimensions(
            drawing,
            bbox,
        )

        rectangles.append({
            "drawing_index": drawing_index,
            "bbox": bbox,
            "width": width,
            "height": height,
            "area": width * height,
            "drawing_type": drawing.get("type"),
            "fill": drawing.get("fill"),
            "color": drawing.get("color"),
            "primitive_types": drawing.get("primitive_types", []),
        })

    return rectangles


def estimate_page_area(page, text_lines, rectangles):
    """
    Estimate page area from extracted content.

    This is used only to filter enormous background rectangles.
    It is not treated as authoritative page dimensions.
    """

    x_values = []
    y_values = []

    for line in text_lines:
        x_values.extend([line["bbox"][0], line["bbox"][2]])
        y_values.extend([line["bbox"][1], line["bbox"][3]])

    for rectangle in rectangles:
        x_values.extend([
            rectangle["bbox"][0],
            rectangle["bbox"][2],
        ])
        y_values.extend([
            rectangle["bbox"][1],
            rectangle["bbox"][3],
        ])

    if not x_values or not y_values:
        return 0.0

    return (
        (max(x_values) - min(x_values))
        * (max(y_values) - min(y_values))
    )


# ------------------------------------------------------------
# STRATEGY 1: RULED TABLE DETECTION
# ------------------------------------------------------------

def detect_horizontal_boundaries(horizontal_segments):
    """Group horizontal segments by Y and identify boundaries."""

    groups = cluster_segments(
        horizontal_segments,
        coordinate_index=0,
        tolerance=GEOMETRY_TOLERANCE,
    )

    boundaries = []

    for group in groups:
        center_y = sum(
            segment[0] for segment in group
        ) / len(group)

        intervals = [
            (segment[1], segment[2])
            for segment in group
        ]

        for x0, x1 in merge_intervals(intervals):
            length = x1 - x0

            if length < MIN_BOUNDARY_LENGTH:
                continue

            boundaries.append({
                "y": center_y,
                "x0": x0,
                "x1": x1,
                "length": length,
            })

    return sorted(
        boundaries,
        key=lambda item: (item["y"], item["x0"]),
    )


def vertical_segment_connects_boundaries(
    segment,
    top_y,
    bottom_y,
):
    """Check whether a vertical segment connects a row's boundaries."""

    _, segment_top, segment_bottom = segment

    exact_connection = (
        abs(segment_top - top_y) <= GEOMETRY_TOLERANCE
        and abs(segment_bottom - bottom_y) <= GEOMETRY_TOLERANCE
    )

    spans_entire_band = (
        segment_top <= top_y + GEOMETRY_TOLERANCE
        and segment_bottom >= bottom_y - GEOMETRY_TOLERANCE
    )

    return exact_connection or spans_entire_band


def find_internal_dividers(
    vertical_segments,
    top_y,
    bottom_y,
    left_x,
    right_x,
):
    """Find internal vertical dividers connecting row boundaries."""

    positions = []

    for segment in vertical_segments:
        center_x = segment[0]

        if not (
            left_x + GEOMETRY_TOLERANCE
            < center_x
            < right_x - GEOMETRY_TOLERANCE
        ):
            continue

        if vertical_segment_connects_boundaries(
            segment,
            top_y,
            bottom_y,
        ):
            positions.append(center_x)

    return cluster_values(
        positions,
        GEOMETRY_TOLERANCE,
    )


def detect_row_bands(boundaries, vertical_segments):
    """Identify row bands formed by horizontal and vertical rules."""

    y_groups = cluster_segments(
        [
            (item["y"], item["x0"], item["x1"])
            for item in boundaries
        ],
        coordinate_index=0,
        tolerance=GEOMETRY_TOLERANCE,
    )

    boundary_layers = []

    for group in y_groups:
        boundary_layers.append({
            "y": sum(item[0] for item in group) / len(group),
            "intervals": merge_intervals(
                [(item[1], item[2]) for item in group]
            ),
        })

    boundary_layers.sort(key=lambda item: item["y"])

    bands = []

    for index in range(len(boundary_layers) - 1):
        top_layer = boundary_layers[index]
        bottom_layer = boundary_layers[index + 1]

        top_y = top_layer["y"]
        bottom_y = bottom_layer["y"]

        if bottom_y <= top_y:
            continue

        for top_x0, top_x1 in top_layer["intervals"]:
            for bottom_x0, bottom_x1 in bottom_layer["intervals"]:
                left_x = max(top_x0, bottom_x0)
                right_x = min(top_x1, bottom_x1)

                if right_x - left_x < MIN_TABLE_WIDTH:
                    continue

                dividers = find_internal_dividers(
                    vertical_segments,
                    top_y,
                    bottom_y,
                    left_x,
                    right_x,
                )

                if not dividers:
                    continue

                bands.append({
                    "top_y": top_y,
                    "bottom_y": bottom_y,
                    "left_x": left_x,
                    "right_x": right_x,
                    "dividers": dividers,
                })

    return sorted(
        bands,
        key=lambda item: (
            item["top_y"],
            item["left_x"],
        ),
    )


def bands_belong_to_same_table(previous, current):
    """Check whether consecutive ruled row bands share geometry."""

    if abs(previous["bottom_y"] - current["top_y"]) > GEOMETRY_TOLERANCE:
        return False

    if abs(previous["left_x"] - current["left_x"]) > GEOMETRY_TOLERANCE:
        return False

    if abs(previous["right_x"] - current["right_x"]) > GEOMETRY_TOLERANCE:
        return False

    previous_dividers = previous["dividers"]
    current_dividers = current["dividers"]

    if len(previous_dividers) != len(current_dividers):
        return False

    return all(
        abs(first - second) <= GEOMETRY_TOLERANCE
        for first, second in zip(
            previous_dividers,
            current_dividers,
        )
    )


def detect_table_regions(row_bands):
    """Combine connected ruled row bands into table regions."""

    regions = []

    for band in row_bands:
        if not regions:
            regions.append([band])
            continue

        previous = regions[-1][-1]

        if bands_belong_to_same_table(previous, band):
            regions[-1].append(band)
        else:
            regions.append([band])

    tables = []

    for table_index, region_bands in enumerate(regions, start=1):
        first = region_bands[0]

        row_boundaries = [first["top_y"]]
        row_boundaries.extend(
            band["bottom_y"] for band in region_bands
        )

        column_boundaries = (
            [first["left_x"]]
            + first["dividers"]
            + [first["right_x"]]
        )

        tables.append({
            "table_index": table_index,
            "structure_type": "ruled_table",
            "bbox": [
                first["left_x"],
                row_boundaries[0],
                first["right_x"],
                row_boundaries[-1],
            ],
            "row_boundaries": row_boundaries,
            "column_boundaries": column_boundaries,
            "row_count": len(region_bands),
            "column_count": len(column_boundaries) - 1,
            "detection_evidence": {
                "connected_row_bands": len(region_bands),
                "internal_divider_count": len(first["dividers"]),
                "geometry_based": True,
                "strategy": "thin_line_geometry",
            },
        })

    return tables


# ------------------------------------------------------------
# STRATEGY 2: FILLED-CELL TABLE DETECTION
# ------------------------------------------------------------

def is_candidate_cell_rectangle(rectangle, page_area):
    """
    Decide whether a rectangle is worth considering as a cell.

    Large page backgrounds, tiny decorative strips, and
    extremely small shapes are excluded.
    """

    width = rectangle["width"]
    height = rectangle["height"]
    area = rectangle["area"]

    if width < MIN_CELL_WIDTH or height < MIN_CELL_HEIGHT:
        return False

    if page_area > 0:
        if area / page_area > MAX_CELL_PAGE_AREA_RATIO:
            return False

    return True


def rectangles_share_row(first, second):
    """Determine whether two rectangles likely belong to one row."""

    first_bbox = first["bbox"]
    second_bbox = second["bbox"]

    top_matches = (
        abs(first_bbox[1] - second_bbox[1])
        <= RECTANGLE_ROW_TOLERANCE
    )

    bottom_matches = (
        abs(first_bbox[3] - second_bbox[3])
        <= RECTANGLE_ROW_TOLERANCE
    )

    return top_matches and bottom_matches


def group_rectangles_into_rows(rectangles):
    """
    Group candidate rectangles by matching top and bottom edges.

    This supports filled-cell tables whose row heights vary.
    """

    ordered = sorted(
        rectangles,
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
        ),
    )

    rows = []

    for rectangle in ordered:
        matching_row = None

        for row in rows:
            if rectangles_share_row(
                rectangle,
                row["rectangles"][0],
            ):
                matching_row = row
                break

        if matching_row is None:
            rows.append({
                "rectangles": [rectangle],
            })
        else:
            matching_row["rectangles"].append(rectangle)

    # Remove groups that do not look like multi-column rows.
    rows = [
        row
        for row in rows
        if len(row["rectangles"]) >= MIN_RECTANGLES_PER_ROW
    ]

    for row in rows:
        row_rectangles = row["rectangles"]

        row["top_y"] = median(
            item["bbox"][1] for item in row_rectangles
        )

        row["bottom_y"] = median(
            item["bbox"][3] for item in row_rectangles
        )

        row["left_x"] = min(
            item["bbox"][0] for item in row_rectangles
        )

        row["right_x"] = max(
            item["bbox"][2] for item in row_rectangles
        )

        row["height"] = row["bottom_y"] - row["top_y"]

    return sorted(rows, key=lambda item: item["top_y"])


def rows_belong_to_same_filled_table(previous, current):
    """
    Determine whether two filled-cell rows likely belong
    to the same table.

    Rows can have different heights. Horizontal overlap and
    vertical continuity provide the grouping evidence.
    """

    vertical_gap = current["top_y"] - previous["bottom_y"]

    if vertical_gap < -RECTANGLE_ROW_TOLERANCE:
        return False

    typical_height = median([
        previous["height"],
        current["height"],
    ])

    allowed_gap = max(
        RECTANGLE_ROW_TOLERANCE * 2,
        typical_height * 1.5,
    )

    if vertical_gap > allowed_gap:
        return False

    overlap = max(
        0.0,
        min(previous["right_x"], current["right_x"])
        - max(previous["left_x"], current["left_x"]),
    )

    smaller_width = min(
        previous["right_x"] - previous["left_x"],
        current["right_x"] - current["left_x"],
    )

    if smaller_width <= 0:
        return False

    return overlap / smaller_width >= 0.70


def group_filled_rows_into_tables(rows):
    """Group vertically adjacent filled-cell rows into tables."""

    tables = []

    for row in rows:
        if not tables:
            tables.append([row])
            continue

        if rows_belong_to_same_filled_table(tables[-1][-1], row):
            tables[-1].append(row)
        else:
            tables.append([row])

    return [
        table
        for table in tables
        if len(table) >= MIN_ROWS_PER_FILLED_TABLE
    ]


def build_filled_table_columns(table_rows):
    """
    Infer column centers from repeated rectangle geometry.

    Column centers are used instead of requiring every text
    item to fall perfectly inside a rectangle. This is useful
    for documents with slightly offset text or partial cell
    background rectangles.
    """

    centers = []

    for row in table_rows:
        for rectangle in row["rectangles"]:
            bbox = rectangle["bbox"]
            centers.append((bbox[0] + bbox[2]) / 2)

    column_centers = cluster_values(
        centers,
        RECTANGLE_COLUMN_TOLERANCE,
    )

    return sorted(column_centers)


def detect_filled_cell_tables(page, text_lines):
    """
    Detect tables made from filled rectangular cells.

    This strategy does not require thin border lines.
    """

    rectangles = extract_rectangle_drawings(page)

    page_area = estimate_page_area(
        page,
        text_lines,
        rectangles,
    )

    candidates = [
        rectangle
        for rectangle in rectangles
        if is_candidate_cell_rectangle(
            rectangle,
            page_area,
        )
    ]

    # Remove rectangles that contain several smaller rectangles.
    # These are often background panels or outer table regions.
    filtered = []

    for rectangle in candidates:
        contained_count = 0

        for other in candidates:
            if other is rectangle:
                continue

            if bbox_area(other["bbox"]) >= bbox_area(rectangle["bbox"]):
                continue

            if bbox_overlap_ratio(
                rectangle["bbox"],
                other["bbox"],
            ) >= 0.95:
                contained_count += 1

        if contained_count < MIN_RECTANGLES_PER_ROW:
            filtered.append(rectangle)

    candidate_rows = group_rectangles_into_rows(filtered)

    table_groups = group_filled_rows_into_tables(
        candidate_rows
    )

    tables = []

    for table_index, row_groups in enumerate(table_groups, start=1):
        column_centers = build_filled_table_columns(
            row_groups
        )

        if len(column_centers) < 3:
            continue

        row_boundaries = [
            row_groups[0]["top_y"]
        ]

        row_boundaries.extend(
            row["bottom_y"]
            for row in row_groups
        )

        left_x = min(row["left_x"] for row in row_groups)
        right_x = max(row["right_x"] for row in row_groups)

        tables.append({
            "table_index": table_index,
            "structure_type": "filled_cell_table",
            "bbox": [
                left_x,
                row_boundaries[0],
                right_x,
                row_boundaries[-1],
            ],
            "row_boundaries": row_boundaries,
            "column_centers": column_centers,
            "row_count": len(row_groups),
            "column_count": len(column_centers),
            "filled_rows": row_groups,
            "detection_evidence": {
                "filled_rectangle_count": sum(
                    len(row["rectangles"])
                    for row in row_groups
                ),
                "repeated_row_count": len(row_groups),
                "column_center_count": len(column_centers),
                "geometry_based": True,
                "strategy": "filled_rectangle_geometry",
            },
        })

    return tables


# ------------------------------------------------------------
# STRATEGY 3: REPEATED OUTLINED-CONTAINER DETECTION
# ------------------------------------------------------------

def detect_repeated_outlined_containers(page, text_lines):
    """
    Detect repeated outlined rectangular containers.

    This is a domain-neutral layout strategy. It can identify
    repeated cards, panels, profile blocks, or other rectangular
    content containers without deciding what they represent.

    A candidate must:
    - Be a stroked rectangle.
    - Be sufficiently wide and tall.
    - Have a broad rectangular shape.
    - Contain multiple text lines.
    - Share approximately the same horizontal boundaries as
      at least one other candidate on the page.
    """

    if len(text_lines) < 2:
        return []

    text_x0 = min(line["bbox"][0] for line in text_lines)
    text_x1 = max(line["bbox"][2] for line in text_lines)
    text_y0 = min(line["bbox"][1] for line in text_lines)
    text_y1 = max(line["bbox"][3] for line in text_lines)

    text_width = text_x1 - text_x0
    text_height = text_y1 - text_y0

    if text_width <= 0 or text_height <= 0:
        return []

    rectangles = extract_rectangle_drawings(page)

    candidates = []

    for rectangle in rectangles:
        bbox = rectangle["bbox"]
        width = rectangle["width"]
        height = rectangle["height"]

        # Outlined containers are expected to use stroke-only
        # drawing operations. Filled cells are handled separately.
        if rectangle["drawing_type"] != "s":
            continue

        if width < max(
            MIN_CONTAINER_WIDTH,
            text_width * 0.50,
        ):
            continue

        if height < MIN_CONTAINER_HEIGHT:
            continue

        if height > text_height * MAX_CONTAINER_HEIGHT_RATIO:
            continue

        if width / height < MIN_CONTAINER_ASPECT_RATIO:
            continue

        # Require actual text inside the candidate container.
        contained_lines = [
            line
            for line in text_lines
            if (
                bbox[0] <= line["center_x"] <= bbox[2]
                and bbox[1] <= line["center_y"] <= bbox[3]
            )
        ]

        if len(contained_lines) < 2:
            continue

        candidates.append({
            **rectangle,
            "contained_lines": contained_lines,
        })

    # Group rectangles with approximately matching horizontal
    # boundaries. This prevents a single unrelated rectangle
    # from being treated as a repeated layout.
    groups = []

    for candidate in sorted(
        candidates,
        key=lambda item: (
            item["bbox"][0],
            item["bbox"][2],
            item["bbox"][1],
        ),
    ):
        bbox = candidate["bbox"]
        matching_group = None

        for group in groups:
            reference = group[0]["bbox"]

            left_matches = (
                abs(bbox[0] - reference[0])
                <= CONTAINER_ALIGNMENT_TOLERANCE
            )

            right_matches = (
                abs(bbox[2] - reference[2])
                <= CONTAINER_ALIGNMENT_TOLERANCE
            )

            if left_matches and right_matches:
                matching_group = group
                break

        if matching_group is None:
            groups.append([candidate])
        else:
            matching_group.append(candidate)

    containers = []

    for group in groups:
        if len(group) < MIN_REPEATED_CONTAINERS:
            continue

        group.sort(
            key=lambda item: item["bbox"][1]
        )

        for rectangle in group:
            bbox = rectangle["bbox"]

            contained_lines = sorted(
                rectangle["contained_lines"],
                key=lambda item: (
                    item["bbox"][1],
                    item["bbox"][0],
                ),
            )

            containers.append({
                "container_index": len(containers) + 1,
                "container_type": "outlined_rectangle",
                "bbox": bbox,
                "drawing_index": rectangle["drawing_index"],
                "line_count": len(contained_lines),
                "text": "\n".join(
                    line["text"]
                    for line in contained_lines
                ),
                "source_lines": [
                    {
                        "text": line["text"],
                        "bbox": line["bbox"],
                        "block_index": line["block_index"],
                        "line_index": line["line_index"],
                    }
                    for line in contained_lines
                ],
                "detection_evidence": {
                    "drawing_type": rectangle["drawing_type"],
                    "primitive_types": rectangle["primitive_types"],
                    "width": rectangle["width"],
                    "height": rectangle["height"],
                    "repeated_group_size": len(group),
                    "horizontal_alignment_tolerance":
                        CONTAINER_ALIGNMENT_TOLERANCE,
                    "geometry_based": True,
                },
            })

    return sorted(
        containers,
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
        ),
    )



# ------------------------------------------------------------
# TEXT-TO-TABLE ASSIGNMENT
# ------------------------------------------------------------

def find_containing_interval(value, boundaries):
    """Find the interval containing a coordinate."""

    for index in range(len(boundaries) - 1):
        lower = boundaries[index]
        upper = boundaries[index + 1]

        if lower <= value < upper:
            return index

    if boundaries and value == boundaries[-1]:
        return len(boundaries) - 2

    return None


def create_empty_cells(row_count, column_count):
    """Create a row/column cell structure."""

    return [
        [
            {
                "row_number": row_index + 1,
                "column_number": column_index + 1,
                "text": "",
                "line_count": 0,
                "source_lines": [],
                "assignment_confidence": None,
            }
            for column_index in range(column_count)
        ]
        for row_index in range(row_count)
    ]


def assign_text_to_ruled_table(table, text_lines):
    """Assign lines to ruled-table cells using geometric intervals."""

    cells = create_empty_cells(
        table["row_count"],
        table["column_count"],
    )

    for line in text_lines:
        center_x = line["center_x"]
        center_y = line["center_y"]

        row_index = find_containing_interval(
            center_y,
            table["row_boundaries"],
        )

        column_index = find_containing_interval(
            center_x,
            table["column_boundaries"],
        )

        if row_index is None or column_index is None:
            continue

        cells[row_index][column_index]["source_lines"].append(line)
        cells[row_index][column_index]["assignment_confidence"] = "high"

    finalize_table_cells(table, cells)


def find_nearest_column(center_x, column_centers):
    """Find the closest inferred column center."""

    if not column_centers:
        return None, None

    distances = [
        abs(center_x - column_center)
        for column_center in column_centers
    ]

    index = distances.index(min(distances))

    return index, distances[index]


def find_filled_row(center_y, row_groups):
    """Find the filled-cell row containing a text line."""

    for index, row in enumerate(row_groups):
        if row["top_y"] <= center_y <= row["bottom_y"]:
            return index, "high"

    # A line may sit slightly outside a cell's rectangle.
    # Only accept a nearby row when it is clearly the closest.
    distances = []

    for index, row in enumerate(row_groups):
        if center_y < row["top_y"]:
            distance = row["top_y"] - center_y
        elif center_y > row["bottom_y"]:
            distance = center_y - row["bottom_y"]
        else:
            distance = 0

        distances.append((distance, index))

    if not distances:
        return None, None

    distance, index = min(distances)

    if distance <= 4.0:
        return index, "medium"

    return None, None


def assign_text_to_filled_table(table, text_lines):
    """
    Assign text to filled-cell tables.

    Text is associated with the nearest inferred column center.
    A nearby but not perfectly contained assignment is marked
    medium confidence instead of being silently treated as exact.
    """

    cells = create_empty_cells(
        table["row_count"],
        table["column_count"],
    )

    column_centers = table["column_centers"]

    for line in text_lines:
        center_x = line["center_x"]
        center_y = line["center_y"]

        row_index, row_confidence = find_filled_row(
            center_y,
            table["filled_rows"],
        )

        if row_index is None:
            continue

        column_index, column_distance = find_nearest_column(
            center_x,
            column_centers,
        )

        if column_index is None:
            continue

        # Avoid assigning distant page text to a table column.
        if column_distance > 35.0:
            continue

        confidence = (
            "high"
            if row_confidence == "high" and column_distance <= 15.0
            else "medium"
        )

        cells[row_index][column_index]["source_lines"].append(line)
        cells[row_index][column_index]["assignment_confidence"] = confidence

    finalize_table_cells(table, cells)


def finalize_table_cells(table, cells):
    """Sort cell text and construct the final row representation."""

    for row in cells:
        for cell in row:
            cell["source_lines"].sort(
                key=lambda item: (
                    item["bbox"][1],
                    item["bbox"][0],
                )
            )

            cell["line_count"] = len(cell["source_lines"])

            cell["text"] = "\n".join(
                item["text"]
                for item in cell["source_lines"]
            )

            # Keep only the useful source evidence.
            cell["source_lines"] = [
                {
                    "text": item["text"],
                    "bbox": item["bbox"],
                    "block_index": item["block_index"],
                    "line_index": item["line_index"],
                }
                for item in cell["source_lines"]
            ]

    table["rows"] = [
        {
            "row_number": row_index + 1,
            "cells": row,
        }
        for row_index, row in enumerate(cells)
    ]



def get_assigned_source_keys(table):
    """
    Return the unique source-line identifiers already assigned
    to cells in a table.
    """

    assigned_keys = set()

    for row in table.get("rows", []):
        for cell in row["cells"]:
            for source in cell["source_lines"]:
                assigned_keys.add((
                    source["block_index"],
                    source["line_index"],
                ))

    return assigned_keys


def get_source_line_key(line):
    """Return a unique identifier for an extracted text line."""

    return (
        line["block_index"],
        line["line_index"],
    )


def calculate_bbox_overlap_ratio(first_bbox, second_bbox):
    """
    Calculate how much of the first bounding box overlaps
    the second bounding box.

    The result is measured relative to the area of first_bbox.
    """

    first_x0, first_y0, first_x1, first_y1 = first_bbox
    second_x0, second_y0, second_x1, second_y1 = second_bbox

    intersection_x0 = max(first_x0, second_x0)
    intersection_y0 = max(first_y0, second_y0)
    intersection_x1 = min(first_x1, second_x1)
    intersection_y1 = min(first_y1, second_y1)

    intersection_width = max(
        0.0,
        intersection_x1 - intersection_x0,
    )

    intersection_height = max(
        0.0,
        intersection_y1 - intersection_y0,
    )

    intersection_area = (
        intersection_width * intersection_height
    )

    first_area = (
        max(0.0, first_x1 - first_x0)
        * max(0.0, first_y1 - first_y0)
    )

    if first_area <= 0:
        return 0.0

    return intersection_area / first_area


def get_rectangle_column_index(rectangle, column_centers):
    """
    Identify which table column a row rectangle belongs to.

    Unlike the primary assignment strategy, this uses the
    rectangle's center rather than the text's center.
    """

    bbox = rectangle.get("bbox")

    if not bbox:
        return None

    rectangle_center_x = (
        bbox[0] + bbox[2]
    ) / 2

    column_index, _ = find_nearest_column(
        rectangle_center_x,
        column_centers,
    )

    return column_index


def add_fallback_assignment(
    cell,
    line,
    assignment_method,
    confidence,
):
    """
    Add a source line to a cell while preserving the strategy
    and confidence that produced the assignment.
    """

    cell["source_lines"].append({
        "text": line["text"],
        "bbox": line["bbox"],
        "block_index": line["block_index"],
        "line_index": line["line_index"],
        "assignment_method": assignment_method,
        "assignment_confidence": confidence,
    })

    refresh_assigned_cell(cell)


def refresh_assigned_cell(cell):
    """Rebuild a finalized cell after a fallback assignment."""

    cell["source_lines"].sort(
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
        )
    )

    cell["line_count"] = len(cell["source_lines"])

    cell["text"] = "\n".join(
        item["text"]
        for item in cell["source_lines"]
    )

    # If any line was assigned with medium confidence,
    # conservatively mark the entire cell medium confidence.
    confidences = {
        source.get("assignment_confidence")
        for source in cell["source_lines"]
    }

    if "medium" in confidences:
        cell["assignment_confidence"] = "medium"
    elif "high" in confidences:
        cell["assignment_confidence"] = "high"


def annotate_primary_assignments(table):
    """
    Add provenance information to lines assigned by the
    original nearest-column-center strategy.

    The original assignment function remains unchanged.
    """

    for row in table.get("rows", []):
        for cell in row["cells"]:
            for source in cell["source_lines"]:
                source.setdefault(
                    "assignment_method",
                    "primary_nearest_column_center",
                )

                source.setdefault(
                    "assignment_confidence",
                    cell["assignment_confidence"],
                )


def assign_text_by_bounding_box_overlap(
    table,
    unresolved_lines,
):
    """
    Fallback strategy 1:

    Assign unresolved lines when their bounding boxes overlap
    an actual filled-cell rectangle sufficiently.

    The rectangle's position determines the column. The text's
    position is not compared against the global column center.
    """

    assigned_keys = set()

    column_centers = table["column_centers"]
    filled_rows = table["filled_rows"]

    for line in unresolved_lines:
        row_index, _ = find_filled_row(
            line["center_y"],
            filled_rows,
        )

        if row_index is None:
            continue

        row_rectangles = filled_rows[row_index].get(
            "rectangles",
            [],
        )

        candidates = []

        for rectangle in row_rectangles:
            rectangle_bbox = rectangle.get("bbox")

            if not rectangle_bbox:
                continue

            overlap_ratio = calculate_bbox_overlap_ratio(
                line["bbox"],
                rectangle_bbox,
            )

            if overlap_ratio < 0.65:
                continue

            column_index = get_rectangle_column_index(
                rectangle,
                column_centers,
            )

            if column_index is None:
                continue

            candidates.append({
                "column_index": column_index,
                "overlap_ratio": overlap_ratio,
            })

        if not candidates:
            continue

        candidates.sort(
            key=lambda item: item["overlap_ratio"],
            reverse=True,
        )

        best_candidate = candidates[0]

        # If two different columns have nearly identical
        # overlap evidence, do not guess.
        if len(candidates) > 1:
            second_candidate = candidates[1]

            if (
                best_candidate["column_index"]
                != second_candidate["column_index"]
                and
                abs(
                    best_candidate["overlap_ratio"]
                    - second_candidate["overlap_ratio"]
                ) < 0.10
            ):
                continue

        confidence = (
            "high"
            if best_candidate["overlap_ratio"] >= 0.90
            else "medium"
        )

        cell = table["rows"][row_index]["cells"][
            best_candidate["column_index"]
        ]

        add_fallback_assignment(
            cell,
            line,
            assignment_method="bounding_box_overlap",
            confidence=confidence,
        )

        assigned_keys.add(get_source_line_key(line))

    return assigned_keys


def assign_text_by_geometric_proximity(
    table,
    unresolved_lines,
):
    """
    Fallback strategy 2:

    Assign a line only when its center is very close to an
    actual rectangle in the appropriate row.

    This is deliberately conservative. It does not use the
    original 35-point global column-center threshold.
    """

    assigned_keys = set()

    column_centers = table["column_centers"]
    filled_rows = table["filled_rows"]

    for line in unresolved_lines:
        row_index, _ = find_filled_row(
            line["center_y"],
            filled_rows,
        )

        if row_index is None:
            continue

        row_rectangles = filled_rows[row_index].get(
            "rectangles",
            [],
        )

        candidates = []

        for rectangle in row_rectangles:
            bbox = rectangle.get("bbox")

            if not bbox:
                continue

            x0, y0, x1, y1 = bbox

            # Horizontal distance from the text center
            # to the rectangle's horizontal boundaries.
            if line["center_x"] < x0:
                horizontal_gap = x0 - line["center_x"]
            elif line["center_x"] > x1:
                horizontal_gap = line["center_x"] - x1
            else:
                horizontal_gap = 0.0

            # Vertical distance from the text center
            # to the rectangle's vertical boundaries.
            if line["center_y"] < y0:
                vertical_gap = y0 - line["center_y"]
            elif line["center_y"] > y1:
                vertical_gap = line["center_y"] - y1
            else:
                vertical_gap = 0.0

            if horizontal_gap > 4.0:
                continue

            if vertical_gap > 4.0:
                continue

            column_index = get_rectangle_column_index(
                rectangle,
                column_centers,
            )

            if column_index is None:
                continue

            candidates.append({
                "column_index": column_index,
                "distance": horizontal_gap + vertical_gap,
            })

        if not candidates:
            continue

        candidates.sort(
            key=lambda item: item["distance"]
        )

        best_candidate = candidates[0]

        # Do not assign when two different columns have
        # equally strong proximity evidence.
        if len(candidates) > 1:
            second_candidate = candidates[1]

            if (
                best_candidate["column_index"]
                != second_candidate["column_index"]
                and
                abs(
                    best_candidate["distance"]
                    - second_candidate["distance"]
                ) < 0.5
            ):
                continue

        cell = table["rows"][row_index]["cells"][
            best_candidate["column_index"]
        ]

        add_fallback_assignment(
            cell,
            line,
            assignment_method="geometric_proximity",
            confidence="medium",
        )

        assigned_keys.add(get_source_line_key(line))

    return assigned_keys


def run_filled_table_assignment_pipeline(table, text_lines):
    """
    Run filled-cell table assignment in stages.

    1. Original nearest-column-center assignment.
    2. Bounding-box overlap fallback.
    3. Geometric proximity fallback.

    Anything still unresolved remains outside the table.
    """

    # Stage 1: Existing primary strategy.
    assign_text_to_filled_table(
        table,
        text_lines,
    )

    annotate_primary_assignments(table)

    assigned_keys = get_assigned_source_keys(table)

    unresolved_lines = [
        line
        for line in text_lines
        if get_source_line_key(line) not in assigned_keys
    ]

    # Stage 2: Actual rectangle overlap.
    assign_text_by_bounding_box_overlap(
        table,
        unresolved_lines,
    )

    assigned_keys = get_assigned_source_keys(table)

    unresolved_lines = [
        line
        for line in text_lines
        if get_source_line_key(line) not in assigned_keys
    ]

    # Stage 3: Conservative geometric proximity.
    assign_text_by_geometric_proximity(
        table,
        unresolved_lines,
    )






def table_contains_point(table, x, y, padding=0.0):
    """Check whether a point falls inside a table region."""

    x0, y0, x1, y1 = table["bbox"]

    return (
        x0 - padding <= x <= x1 + padding
        and y0 - padding <= y <= y1 + padding
    )


def tables_overlap(first, second):
    """Check whether two detected table regions substantially overlap."""

    intersection = bbox_intersection_area(
        first["bbox"],
        second["bbox"],
    )

    smaller_area = min(
        bbox_area(first["bbox"]),
        bbox_area(second["bbox"]),
    )

    if smaller_area <= 0:
        return False

    return intersection / smaller_area >= 0.80


def remove_duplicate_tables(tables):
    """Avoid returning the same table from two detection strategies."""

    accepted = []

    for table in sorted(
        tables,
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
        ),
    ):
        duplicate_index = None

        for index, existing in enumerate(accepted):
            if tables_overlap(table, existing):
                duplicate_index = index
                break

        if duplicate_index is None:
            accepted.append(table)
            continue

        existing = accepted[duplicate_index]

        # Prefer the filled-cell strategy when both strategies
        # identify substantially the same table.
        if table["structure_type"] == "filled_cell_table":
            accepted[duplicate_index] = table

    return accepted

# ------------------------------------------------------------
# STRATEGY 4: SEPARATOR-DELIMITED REGION DETECTION
# ------------------------------------------------------------

def separator_boundaries_belong_together(first, second):
    """
    Determine whether two horizontal boundaries likely belong
    to the same repeated separator pattern.

    Their vertical positions are expected to differ. Their
    horizontal coverage should remain approximately consistent.
    """

    return (
        abs(first["x0"] - second["x0"])
        <= SEPARATOR_ALIGNMENT_TOLERANCE
        and
        abs(first["x1"] - second["x1"])
        <= SEPARATOR_ALIGNMENT_TOLERANCE
    )


def group_separator_boundaries(boundaries):
    """
    Group horizontal boundaries by similar horizontal coverage.

    This separates a repeated separator pattern from unrelated
    horizontal lines elsewhere on the page.
    """

    groups = []

    for boundary in sorted(
        boundaries,
        key=lambda item: (
            item["x0"],
            item["x1"],
            item["y"],
        ),
    ):
        matching_group = None

        for group in groups:
            if separator_boundaries_belong_together(
                boundary,
                group[0],
            ):
                matching_group = group
                break

        if matching_group is None:
            groups.append([boundary])
        else:
            matching_group.append(boundary)

    return groups


def find_separator_content_bounds(
    page,
    separators,
    text_lines,
):
    """
    Find the vertical content limits for a separator pattern.

    Prefer a large enclosing rectangle when one exists. This
    helps exclude page footers that sit outside the main content
    area.

    If no enclosing rectangle can be identified, fall back to
    the extracted text extent.
    """

    separator_x0 = min(
        item["x0"] for item in separators
    )

    separator_x1 = max(
        item["x1"] for item in separators
    )

    separator_y0 = min(
        item["y"] for item in separators
    )

    separator_y1 = max(
        item["y"] for item in separators
    )

    rectangles = extract_rectangle_drawings(page)

    enclosing_rectangles = []

    for rectangle in rectangles:
        bbox = rectangle["bbox"]

        contains_separator_width = (
            bbox[0] <= separator_x0 + SEPARATOR_ALIGNMENT_TOLERANCE
            and
            bbox[2] >= separator_x1 - SEPARATOR_ALIGNMENT_TOLERANCE
        )

        contains_separator_height = (
            bbox[1] <= separator_y0
            and
            bbox[3] >= separator_y1
        )

        if contains_separator_width and contains_separator_height:
            enclosing_rectangles.append(rectangle)

    if enclosing_rectangles:
        # The largest enclosing rectangle is the most likely
        # page or content boundary.
        outer_rectangle = max(
            enclosing_rectangles,
            key=lambda item: item["area"],
        )

        return {
            "top": outer_rectangle["bbox"][1],
            "bottom": outer_rectangle["bbox"][3],
            "source": "enclosing_rectangle",
        }

    # Fallback: use text that falls horizontally within the
    # separator pattern. This cannot guarantee footer exclusion,
    # so the fallback is recorded in the evidence.
    relevant_lines = [
        line
        for line in text_lines
        if (
            separator_x0 - SEPARATOR_CONTENT_PADDING
            <= line["center_x"]
            <= separator_x1 + SEPARATOR_CONTENT_PADDING
        )
    ]

    if relevant_lines:
        return {
            "top": min(
                line["bbox"][1] for line in relevant_lines
            ),
            "bottom": max(
                line["bbox"][3] for line in relevant_lines
            ),
            "source": "text_extent_fallback",
        }

    return None


def boundary_overlaps_table(boundary, tables):
    """
    Check whether a separator candidate is already part of
    a detected table's horizontal geometry.

    This prevents a ruled table from being detected again as
    a separator-delimited layout.
    """

    for table in tables:
        bbox = table["bbox"]

        if not (
            bbox[1] - GEOMETRY_TOLERANCE
            <= boundary["y"]
            <= bbox[3] + GEOMETRY_TOLERANCE
        ):
            continue

        overlap = max(
            0.0,
            min(boundary["x1"], bbox[2])
            - max(boundary["x0"], bbox[0]),
        )

        boundary_width = boundary["x1"] - boundary["x0"]

        if boundary_width <= 0:
            continue

        if overlap / boundary_width >= 0.80:
            return True

    return False


def build_separator_regions(
    separators,
    text_lines,
    content_bounds,
):
    """
    Build text regions between repeated horizontal separators.

    Text is assigned using both its horizontal and vertical
    position. This prevents unrelated text elsewhere on the
    page from being pulled into a separator-delimited region.

    Multiple text baselines and wrapped lines can belong to
    the same region.
    """

    if not separators or not text_lines or not content_bounds:
        return []

    separator_ys = sorted(
        cluster_values(
            [item["y"] for item in separators],
            GEOMETRY_TOLERANCE,
        )
    )

    separator_x0 = min(
        item["x0"] for item in separators
    )

    separator_x1 = max(
        item["x1"] for item in separators
    )

    content_top = content_bounds["top"]
    content_bottom = content_bounds["bottom"]

    if content_bottom <= content_top:
        return []

    if separator_x1 <= separator_x0:
        return []

    # Ignore separator lines outside the content limits.
    separator_ys = [
        y
        for y in separator_ys
        if content_top <= y <= content_bottom
    ]

    if len(separator_ys) < MIN_REPEATED_SEPARATORS:
        return []

    # Each separator is a boundary between two regions.
    # Including content_top and content_bottom preserves
    # the first and last regions when their boundaries are
    # not both represented by separator lines.
    region_boundaries = (
        [content_top]
        + separator_ys
        + [content_bottom]
    )

    regions = []

    for index in range(len(region_boundaries) - 1):
        top_y = region_boundaries[index]
        bottom_y = region_boundaries[index + 1]

        if bottom_y <= top_y:
            continue

        # Assign text only when its center falls within both
        # the horizontal separator span and the vertical band.
        region_lines = [
            line
            for line in text_lines
            if (
                separator_x0 - SEPARATOR_CONTENT_PADDING
                <= line["center_x"]
                <= separator_x1 + SEPARATOR_CONTENT_PADDING
                and
                top_y - SEPARATOR_CONTENT_PADDING
                <= line["center_y"]
                < bottom_y - SEPARATOR_CONTENT_PADDING
            )
        ]

        if not region_lines:
            continue

        region_lines.sort(
            key=lambda item: (
                item["bbox"][1],
                item["bbox"][0],
            )
        )

        # Regions bounded by separators on both sides have
        # stronger geometric evidence than edge regions.
        has_top_separator = index > 0
        has_bottom_separator = (
            index < len(region_boundaries) - 2
        )

        confidence = (
            "high"
            if has_top_separator and has_bottom_separator
            else "medium"
        )

        regions.append({
            "region_index": len(regions) + 1,
            "region_type": "separator_delimited_region",
            "bbox": [
                min(line["bbox"][0] for line in region_lines),
                min(line["bbox"][1] for line in region_lines),
                max(line["bbox"][2] for line in region_lines),
                max(line["bbox"][3] for line in region_lines),
            ],
            "separator_bounds": [
                top_y,
                bottom_y,
            ],
            "line_count": len(region_lines),
            "text": "\n".join(
                line["text"] for line in region_lines
            ),
            "source_lines": [
                {
                    "text": line["text"],
                    "bbox": line["bbox"],
                    "block_index": line["block_index"],
                    "line_index": line["line_index"],
                }
                for line in region_lines
            ],
            "assignment_confidence": confidence,
            "interpretation_status": "unclassified",
            "detection_evidence": {
                "strategy": "repeated_horizontal_separators",
                "separator_count": len(separator_ys),
                "top_boundary_is_separator": has_top_separator,
                "bottom_boundary_is_separator": has_bottom_separator,
                "content_bounds_source": content_bounds["source"],
                "horizontal_bounds": [
                    separator_x0,
                    separator_x1,
                ],
                "geometry_based": True,
            },
        })

    return regions




def detect_separator_delimited_regions(
    page,
    text_lines,
    horizontal_boundaries,
    existing_tables=None,
):
    """
    Detect repeated regions separated by long horizontal rules.

    This strategy is independent of ruled-table, filled-cell,
    and outlined-container detection.

    It does not interpret the contents of a region. It only
    reconstructs the spatial grouping.
    """

    if len(text_lines) < 3:
        return []

    existing_tables = existing_tables or []

    candidate_boundaries = [
        boundary
        for boundary in horizontal_boundaries
        if (
            boundary["length"] >= MIN_SEPARATOR_LENGTH
            and not boundary_overlaps_table(
                boundary,
                existing_tables,
            )
        )
    ]

    if len(candidate_boundaries) < MIN_REPEATED_SEPARATORS:
        return []

    boundary_groups = group_separator_boundaries(
        candidate_boundaries
    )

    # Prefer the strongest repeated horizontal pattern.
    boundary_groups = sorted(
        boundary_groups,
        key=lambda group: (
            len(group),
            median(item["length"] for item in group),
        ),
        reverse=True,
    )

    for group in boundary_groups:
        if len(group) < MIN_REPEATED_SEPARATORS:
            continue

        # A separator pattern should have a consistent horizontal
        # span. Do not combine unrelated short and long rules.
        median_length = median(
            item["length"] for item in group
        )

        if median_length < MIN_SEPARATOR_LENGTH:
            continue

        content_bounds = find_separator_content_bounds(
            page,
            group,
            text_lines,
        )

        if not content_bounds:
            continue

        regions = build_separator_regions(
            group,
            text_lines,
            content_bounds,
        )

        if len(regions) < MIN_SEPARATOR_REGIONS:
            continue

        # Reject a pattern that only creates a handful of tiny
        # fragments while leaving most of the text outside it.
        assigned_keys = {
            (
                source["block_index"],
                source["line_index"],
            )
            for region in regions
            for source in region["source_lines"]
        }

        if len(assigned_keys) < 3:
            continue

        for index, region in enumerate(regions, start=1):
            region["region_index"] = index

        return regions

    return []


# ------------------------------------------------------------
# TEXT REGION RECONSTRUCTION
# ------------------------------------------------------------

def build_text_regions(unassigned_text):
    """
    Group unassigned lines into spatially nearby text regions.

    These are deliberately called text regions rather than
    player cards or records. Document-specific interpretation
    belongs in a separate layer.
    """

    if not unassigned_text:
        return []

    ordered = sorted(
        unassigned_text,
        key=lambda item: (
            item["bbox"][1],
            item["bbox"][0],
        ),
    )

    heights = [
        item["height"]
        for item in ordered
        if item["height"] > 0
    ]

    typical_height = median(heights) if heights else 8.0

    allowed_gap = max(
        TEXT_REGION_MIN_GAP,
        typical_height * TEXT_REGION_GAP_MULTIPLIER,
    )

    regions = []
    current_region = []

    for line in ordered:
        if not current_region:
            current_region.append(line)
            continue

        previous = current_region[-1]

        vertical_gap = (
            line["bbox"][1] - previous["bbox"][3]
        )

        if vertical_gap <= allowed_gap:
            current_region.append(line)
        else:
            regions.append(current_region)
            current_region = [line]

    if current_region:
        regions.append(current_region)

    result = []

    for index, region_lines in enumerate(regions, start=1):
        result.append({
            "region_index": index,
            "region_type": "unclassified_text_region",
            "bbox": [
                min(item["bbox"][0] for item in region_lines),
                min(item["bbox"][1] for item in region_lines),
                max(item["bbox"][2] for item in region_lines),
                max(item["bbox"][3] for item in region_lines),
            ],
            "line_count": len(region_lines),
            "text": "\n".join(
                item["text"] for item in region_lines
            ),
            "source_lines": [
                {
                    "text": item["text"],
                    "bbox": item["bbox"],
                    "block_index": item["block_index"],
                    "line_index": item["line_index"],
                }
                for item in region_lines
            ],
            "interpretation_status": "unclassified",
        })

    return result


# ------------------------------------------------------------
# DOCUMENT MODEL CONSTRUCTION
# ------------------------------------------------------------

def calculate_table_assignment_diagnostics(tables):
    """Summarize cell population, confidence, and assignment methods."""

    total_cells = 0
    populated_cells = 0
    medium_confidence_cells = 0

    assignment_methods = {}

    for table in tables:
        for row in table.get("rows", []):
            for cell in row["cells"]:
                total_cells += 1

                if cell["text"].strip():
                    populated_cells += 1

                if cell["assignment_confidence"] == "medium":
                    medium_confidence_cells += 1

                for source in cell["source_lines"]:
                    method = source.get(
                        "assignment_method",
                        "unknown",
                    )

                    assignment_methods[method] = (
                        assignment_methods.get(method, 0) + 1
                    )

    fallback_assigned_lines = sum(
        count
        for method, count in assignment_methods.items()
        if method != "primary_nearest_column_center"
    )

    return {
        "total_cells": total_cells,
        "populated_cells": populated_cells,
        "empty_cells": total_cells - populated_cells,
        "medium_confidence_cells": medium_confidence_cells,
        "assignment_methods": assignment_methods,
        "fallback_assigned_lines": fallback_assigned_lines,
    }


def analyze_page_structure(page):
    """
    Reconstruct the structural model for one PDF page.

    Independent strategies detect:
    - Ruled tables.
    - Filled-cell tables.
    - Repeated outlined containers.
    - Separator-delimited regions.

    Remaining text is preserved as unclassified text regions.
    """

    text_lines = extract_text_lines(page)

    horizontal, vertical = extract_geometry_segments(page)

    boundaries = detect_horizontal_boundaries(horizontal)

    row_bands = detect_row_bands(
        boundaries,
        vertical,
    )

    ruled_tables = detect_table_regions(row_bands)

    filled_tables = detect_filled_cell_tables(
        page,
        text_lines,
    )

    tables = remove_duplicate_tables(
        ruled_tables + filled_tables
    )

    containers = detect_repeated_outlined_containers(
        page,
        text_lines,
    )

    unassigned_text = list(text_lines)

    # --------------------------------------------------------
    # 1. Assign text to detected tables.
    # --------------------------------------------------------

    for table in tables:
        if table["structure_type"] == "ruled_table":
            assign_text_to_ruled_table(
                table,
                text_lines,
            )

        elif table["structure_type"] == "filled_cell_table":
            run_filled_table_assignment_pipeline(
                table,
                text_lines,
            )

        assigned_source_keys = set()

        for row in table.get("rows", []):
            for cell in row["cells"]:
                for source in cell["source_lines"]:
                    assigned_source_keys.add((
                        source["block_index"],
                        source["line_index"],
                    ))

        unassigned_text = [
            line
            for line in unassigned_text
            if (
                line["block_index"],
                line["line_index"],
            ) not in assigned_source_keys
        ]

    # --------------------------------------------------------
    # 2. Assign remaining text to repeated containers.
    # --------------------------------------------------------

    for container in containers:
        assigned_source_keys = {
            (
                source["block_index"],
                source["line_index"],
            )
            for source in container["source_lines"]
        }

        unassigned_text = [
            line
            for line in unassigned_text
            if (
                line["block_index"],
                line["line_index"],
            ) not in assigned_source_keys
        ]

    # --------------------------------------------------------
    # 3. Detect separator-delimited regions from remaining text.
    # --------------------------------------------------------

    separator_regions = detect_separator_delimited_regions(
        page,
        unassigned_text,
        boundaries,
        existing_tables=tables,
    )

    for region in separator_regions:
        assigned_source_keys = {
            (
                source["block_index"],
                source["line_index"],
            )
            for source in region["source_lines"]
        }

        unassigned_text = [
            line
            for line in unassigned_text
            if (
                line["block_index"],
                line["line_index"],
            ) not in assigned_source_keys
        ]

    # --------------------------------------------------------
    # 4. Preserve anything not assigned by a strategy.
    # --------------------------------------------------------

    text_regions = build_text_regions(unassigned_text)

    rectangles = extract_rectangle_drawings(page)

    assignment_diagnostics = calculate_table_assignment_diagnostics(
        tables
    )

    if tables and (
        containers
        or separator_regions
        or text_regions
    ):
        structure_type = "mixed"

    elif tables:
        structure_type = "table_based"

    elif containers and separator_regions:
        structure_type = "mixed"

    elif containers and text_regions:
        structure_type = "mixed"

    elif separator_regions and text_regions:
        structure_type = "mixed"

    elif containers:
        structure_type = "repeated_container_based"

    elif separator_regions:
        structure_type = "separator_delimited"

    elif text_regions:
        structure_type = "text_based"

    else:
        structure_type = "empty_or_graphical"

    return {
        "page_number": page.get("page_number"),
        "structure_type": structure_type,

        "tables": tables,
        "table_count": len(tables),

        "containers": containers,
        "container_count": len(containers),

        "separator_regions": separator_regions,
        "separator_region_count": len(separator_regions),

        "text_regions": text_regions,
        "text_region_count": len(text_regions),

        "text_line_count": len(text_lines),
        "unassigned_text": unassigned_text,

        "diagnostics": {
            "horizontal_segment_count": len(horizontal),
            "vertical_segment_count": len(vertical),
            "horizontal_boundary_count": len(boundaries),
            "ruled_row_band_count": len(row_bands),
            "rectangle_count": len(rectangles),
            "ruled_table_count": len(ruled_tables),
            "filled_cell_table_count": len(filled_tables),
            "detected_table_count": len(tables),
            "outlined_container_count": len(containers),
            "separator_region_count": len(separator_regions),
            "separator_assigned_line_count": sum(
                region["line_count"]
                for region in separator_regions
            ),
            "assignment": assignment_diagnostics,
        },
    }




def analyze_pdf_structure(pdf_path):
    """
    Analyze a PDF and construct a domain-neutral document model.

    The original extraction data is preserved separately from
    the structural interpretation.
    """

    document = analyze_pdf_document(pdf_path)

    analyzed_pages = []

    for page in document.get("pages", []):
        analyzed_pages.append(
            analyze_page_structure(page)
        )

    return {
        "file_path": str(pdf_path),
        "page_count": len(analyzed_pages),
        "pages": analyzed_pages,
        "document_model_version": 3,
        "analysis_scope": {
            "ruled_tables": True,
            "filled_cell_tables": True,
            "repeated_outlined_containers": True,
            "unclassified_text_regions": True,
            "separator_delimited_regions": True,
            "scanned_document_ocr": False,
            "semantic_record_interpretation": False,
        },
    }




# ------------------------------------------------------------
# COMMAND-LINE SUMMARY
# ------------------------------------------------------------

def print_compact_summary(result, selected_page=None):
    """Print a short summary without dumping extracted text."""

    pages = result["pages"]

    if selected_page is not None:
        pages = [
            page
            for page in pages
            if page["page_number"] == selected_page
        ]

        if not pages:
            print(f"Page {selected_page} was not found.")
            return

    print("=" * 110)
    print("UNIVERSAL PDF STRUCTURE ANALYSIS")
    print("=" * 110)

    print(f"File: {result['file_path']}")
    print(f"Pages in document: {result['page_count']}")
    print(f"Document model version: {result['document_model_version']}")

    total_tables = sum(page["table_count"] for page in pages)
    total_containers = sum(page["container_count"] for page in pages)
    total_regions = sum(page["text_region_count"] for page in pages)
    total_lines = sum(page["text_line_count"] for page in pages)
    total_unassigned = sum(
        len(page["unassigned_text"])
        for page in pages
    )
    total_separator_regions = sum(
        page["separator_region_count"]
        for page in pages
    )

    print("-" * 110)
    print(
        f"Pages reported: {len(pages)} | "
        f"Tables: {total_tables} | "
        f"Outlined containers: {total_containers} | "
        f"Text regions: {total_regions} | "
        f"Separator regions: {total_separator_regions} | "
        f"Text lines: {total_lines} | "
        f"Unassigned lines: {total_unassigned}"
    )
    print("-" * 110)

    print(
    f"{'PAGE':<7}"
    f"{'STRUCTURE':<27}"
    f"{'TABLES':>8}"
    f"{'CONTAINERS':>13}"
    f"{'SEPARATORS':>12}"
    f"{'REGIONS':>10}"
    f"{'LINES':>9}"
    f"{'UNASSIGNED':>13}"
)

    print("-" * 110)

    for page in pages:
        print(
    f"{str(page['page_number']):<7}"
    f"{page['structure_type']:<27}"
    f"{page['table_count']:>8}"
    f"{page['container_count']:>13}"
    f"{page['separator_region_count']:>12}"
    f"{page['text_region_count']:>10}"
    f"{page['text_line_count']:>9}"
    f"{len(page['unassigned_text']):>13}"
)
    print("-" * 110)

    print("\nDETECTION BREAKDOWN")

    for page in pages:
        diagnostics = page["diagnostics"]
        assignment = diagnostics["assignment"]

        table_details = []

        for table in page["tables"]:
            table_details.append(
                f"{table['structure_type']}: "
                f"{table['row_count']}x{table['column_count']}"
            )

        table_summary = (
            ", ".join(table_details)
            if table_details
            else "none"
        )

        print(
            f"Page {page['page_number']}: "
            f"ruled={diagnostics['ruled_table_count']}, "
            f"filled={diagnostics['filled_cell_table_count']}, "
            f"containers={diagnostics['outlined_container_count']}, "
            f"separator-regions={diagnostics['separator_region_count']}, "
f"separator-lines={diagnostics['separator_assigned_line_count']}, "
            f"cells={assignment['total_cells']}, "
            f"populated={assignment['populated_cells']}, "
            f"medium-confidence={assignment['medium_confidence_cells']}, "
            f"tables=[{table_summary}]"
        )


def print_page_details(page):
    """Print extracted structural details for one page."""

    print("\n" + "=" * 90)
    print(f"DETAILED PAGE REPORT: {page['page_number']}")
    print("=" * 90)

    print(f"Structure: {page['structure_type']}")
    print(f"Text lines: {page['text_line_count']}")
    print(f"Tables: {page['table_count']}")
    print(f"Outlined containers: {page['container_count']}")
    print(f"Text regions: {page['text_region_count']}")
    print(f"Separator regions: {page['separator_region_count']}")
    print(f"Unassigned lines: {len(page['unassigned_text'])}")

    for table in page["tables"]:
        print("\n" + "-" * 70)
        print(
            f"TABLE {table['table_index']} "
            f"({table['structure_type']})"
        )
        print("-" * 70)

        print(f"Rows: {table['row_count']}")
        print(f"Columns: {table['column_count']}")
        print(f"BBox: {table['bbox']}")
        print(f"Evidence: {table['detection_evidence']}")

        for row in table.get("rows", [])[:3]:
            print(f"\n  ROW {row['row_number']}")

            for cell in row["cells"]:
                value = cell["text"] or "[EMPTY]"

                print(
                    f"    Column {cell['column_number']}: "
                    f"{value}"
                )

    for container in page["containers"]:
        print("\n" + "-" * 70)
        print(
            f"CONTAINER {container['container_index']} "
            f"({container['container_type']})"
        )
        print("-" * 70)

        print(f"BBox: {container['bbox']}")
        print(f"Drawing index: {container['drawing_index']}")
        print(f"Lines: {container['line_count']}")
        print(f"Evidence: {container['detection_evidence']}")
        print("Text:")

        for source in container["source_lines"]:
            print(f"  {source['text']}")
    for region in page.get("separator_regions", []):
        print("\n" + "-" * 70)
        print(
            f"SEPARATOR REGION {region['region_index']}"
        )
        print("-" * 70)

        print(f"BBox: {region['bbox']}")
        print(f"Separator bounds: {region['separator_bounds']}")
        print(f"Lines: {region['line_count']}")
        print(f"Confidence: {region['assignment_confidence']}")
        print(f"Evidence: {region['detection_evidence']}")
        print("Text:")

        for source in region["source_lines"]:
            print(f"  {source['text']}")

    if page["text_regions"]:
        print("\nUNCLASSIFIED TEXT REGIONS")

        for region in page["text_regions"][:10]:
            print(
                f"\nRegion {region['region_index']} "
                f"({region['line_count']} lines)"
            )
            print(region["text"][:500])

    if page["unassigned_text"]:
        print("\nUNASSIGNED TEXT")

        for item in page["unassigned_text"][:15]:
            print(f"  {item['text']}")


def print_analysis_summary(
    result,
    selected_page=None,
    verbose=False,
):
    """Print compact output by default, with optional details."""

    print_compact_summary(
        result,
        selected_page=selected_page,
    )

    if not verbose:
        return

    pages = result["pages"]

    if selected_page is not None:
        pages = [
            page
            for page in pages
            if page["page_number"] == selected_page
        ]

    for page in pages:
        print_page_details(page)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze the structural layout of a PDF."
    )

    parser.add_argument(
        "pdf_path",
        help="Path to the PDF document.",
    )

    parser.add_argument(
        "--page",
        type=int,
        default=None,
        help="Only report the selected 1-based page number.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed structural information.",
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)

    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        return

    try:
        result = analyze_pdf_structure(pdf_path)

        print_analysis_summary(
            result,
            selected_page=args.page,
            verbose=args.verbose,
        )

    except Exception as error:
        print(f"PDF structure analysis failed: {error}")
        raise


if __name__ == "__main__":
    main()
