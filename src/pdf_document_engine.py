
import sys
from pathlib import Path
from typing import Any
from collections import Counter

import pymupdf


class PDFDocumentError(Exception):
    """Raised when a PDF cannot be opened or analyzed."""


# ============================================================
# DOCUMENT CLASSIFICATION
# ============================================================

CONTENT_SELECTABLE_TEXT = "selectable_text"
CONTENT_MIXED = "mixed_text_and_images"
CONTENT_IMAGE_ONLY = "image_only_or_scanned"
CONTENT_IMAGE_CONTENT = "image_content"
CONTENT_GRAPHICS_ONLY = "non_text_graphics"
CONTENT_EMPTY = "no_extractable_content"

SIGNIFICANT_IMAGE_AREA_RATIO = 0.05
SCAN_IMAGE_AREA_RATIO = 0.50

DEFAULT_PROXIMITY_TOLERANCE = 2.0
MIN_LINE_TEXT_OVERLAP_RATIO = 0.01


def classify_page_content(
    word_count: int,
    image_count: int,
    image_area_ratio: float,
    drawing_count: int,
) -> str:
    """Classify available page content without interpreting its purpose."""

    has_text = word_count > 0
    has_images = image_count > 0
    has_graphics = drawing_count > 0

    significant_images = (
        has_images
        and image_area_ratio >= SIGNIFICANT_IMAGE_AREA_RATIO
    )

    if has_text and significant_images:
        return CONTENT_MIXED

    if has_text:
        return CONTENT_SELECTABLE_TEXT

    if has_images:
        if image_area_ratio >= SCAN_IMAGE_AREA_RATIO:
            return CONTENT_IMAGE_ONLY

        return CONTENT_IMAGE_CONTENT

    if has_graphics:
        return CONTENT_GRAPHICS_ONLY

    return CONTENT_EMPTY


# ============================================================
# TEXT EXTRACTION
# ============================================================

def extract_page_words(page) -> list[dict[str, Any]]:
    """Extract individual words while preserving their coordinates."""

    extracted = []

    for word in page.get_text("words", sort=True):
        (
            x0,
            y0,
            x1,
            y1,
            text,
            block_no,
            line_no,
            word_no,
        ) = word

        extracted.append({
            "text": text,
            "bbox": [
                round(x0, 2),
                round(y0, 2),
                round(x1, 2),
                round(y1, 2),
            ],
            "block_number": block_no,
            "line_number": line_no,
            "word_number": word_no,
        })

    return extracted


def extract_page_blocks(page) -> list[dict[str, Any]]:
    """Extract text blocks, lines, and spans with positioning details."""

    page_data = page.get_text("dict", sort=True)
    extracted_blocks = []

    for block_index, block in enumerate(
        page_data.get("blocks", [])
    ):

        if block.get("type") != 0:
            continue

        block_lines = []

        for line_index, line in enumerate(block.get("lines", [])):
            extracted_spans = []

            for span in line.get("spans", []):
                span_text = span.get("text", "")

                if not span_text:
                    continue

                extracted_spans.append({
                    "text": span_text,
                    "bbox": [
                        round(value, 2)
                        for value in span.get("bbox", [])
                    ],
                    "font": span.get("font", ""),
                    "font_size": round(
                        span.get("size", 0), 2
                    ),
                    "font_flags": span.get("flags", 0),
                    "color": span.get("color"),
                })

            if not extracted_spans:
                continue

            block_lines.append({
                "sequence_number": line_index,
                "bbox": [
                    round(value, 2)
                    for value in line.get("bbox", [])
                ],
                "text": "".join(
                    span["text"] for span in extracted_spans
                ),
                "spans": extracted_spans,
            })

        if not block_lines:
            continue

        extracted_blocks.append({
            "sequence_number": block_index,
            "bbox": [
                round(value, 2)
                for value in block.get("bbox", [])
            ],
            "text": "\n".join(
                line["text"] for line in block_lines
            ),
            "lines": block_lines,
        })

    return extracted_blocks


# ============================================================
# IMAGE INSPECTION
# ============================================================

def inspect_page_images(page) -> dict[str, Any]:
    """Identify images and estimate their page coverage."""

    try:
        images = page.get_image_info(xrefs=True)
    except Exception:
        images = []

    page_area = max(
        1.0,
        page.rect.width * page.rect.height
    )

    image_results = []
    estimated_image_area = 0.0

    for image in images:
        bbox = image.get("bbox")

        if not bbox or len(bbox) != 4:
            continue

        x0, y0, x1, y1 = bbox

        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        area = width * height

        estimated_image_area += area

        image_results.append({
            "bbox": [
                round(x0, 2),
                round(y0, 2),
                round(x1, 2),
                round(y1, 2),
            ],
            "width_pixels": image.get("width"),
            "height_pixels": image.get("height"),
            "xref": image.get("xref"),
            "x_resolution": image.get("xres"),
            "y_resolution": image.get("yres"),
        })

    # Estimate only. Overlapping images may be counted more than once.
    image_area_ratio = min(
        1.0,
        estimated_image_area / page_area
    )

    return {
        "image_count": len(image_results),
        "estimated_image_area_ratio": round(
            image_area_ratio, 4
        ),
        "images": image_results,
    }


# ============================================================
# GEOMETRY SERIALIZATION
# ============================================================

def serialize_drawing_value(value):
    """Convert PyMuPDF geometry objects into ordinary Python data."""

    if value is None:
        return None

    if all(
        hasattr(value, name)
        for name in ("ul", "ur", "ll", "lr")
    ):
        return {
            "type": "quad",
            "points": {
                "upper_left": serialize_drawing_value(value.ul),
                "upper_right": serialize_drawing_value(value.ur),
                "lower_left": serialize_drawing_value(value.ll),
                "lower_right": serialize_drawing_value(value.lr),
            },
        }

    if all(
        hasattr(value, name)
        for name in ("x0", "y0", "x1", "y1")
    ):
        return {
            "type": "rectangle",
            "coordinates": [
                round(float(value.x0), 2),
                round(float(value.y0), 2),
                round(float(value.x1), 2),
                round(float(value.y1), 2),
            ],
        }

    if hasattr(value, "x") and hasattr(value, "y"):
        return {
            "type": "point",
            "coordinates": [
                round(float(value.x), 2),
                round(float(value.y), 2),
            ],
        }

    if isinstance(value, (tuple, list)):
        return [
            serialize_drawing_value(item)
            for item in value
        ]

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def get_rectangle_coordinates(value):
    """Return rectangle coordinates from supported geometry formats."""

    if value is None:
        return None

    if all(
        hasattr(value, name)
        for name in ("x0", "y0", "x1", "y1")
    ):
        return [
            float(value.x0),
            float(value.y0),
            float(value.x1),
            float(value.y1),
        ]

    if isinstance(value, (tuple, list)) and len(value) == 4:
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return None

    if isinstance(value, dict):
        if value.get("type") == "rectangle":
            coordinates = value.get("coordinates")

            if (
                isinstance(coordinates, (tuple, list))
                and len(coordinates) == 4
            ):
                try:
                    return [
                        float(item) for item in coordinates
                    ]
                except (TypeError, ValueError):
                    return None

    return None


# ============================================================
# VECTOR DRAWING EXTRACTION
# ============================================================

def extract_page_drawings(page) -> list[dict[str, Any]]:
    """Extract vector drawing geometry without interpreting its purpose."""

    extracted = []

    for drawing_index, drawing in enumerate(page.get_drawings()):
        items = drawing.get("items", [])

        bbox_coordinates = get_rectangle_coordinates(
            drawing.get("rect")
        )

        dimensions = None

        if bbox_coordinates:
            x0, y0, x1, y1 = bbox_coordinates

            dimensions = {
                "width": round(max(0.0, x1 - x0), 2),
                "height": round(max(0.0, y1 - y0), 2),
                "area": round(
                    max(0.0, x1 - x0)
                    * max(0.0, y1 - y0),
                    2,
                ),
            }

        primitive_types = Counter(
            item[0]
            for item in items
            if isinstance(item, (tuple, list))
            and item
            and isinstance(item[0], str)
        )

        extracted.append({
            "drawing_index": drawing_index,
            "type": drawing.get("type"),

            "bbox": serialize_drawing_value(
                drawing.get("rect")
            ),

            "bbox_dimensions": dimensions,

            "color": serialize_drawing_value(
                drawing.get("color")
            ),

            "fill": serialize_drawing_value(
                drawing.get("fill")
            ),

            "width": drawing.get("width"),
            "close_path": drawing.get("closePath"),
            "even_odd": drawing.get("even_odd"),
            "stroke_opacity": drawing.get("stroke_opacity"),
            "fill_opacity": drawing.get("fill_opacity"),

            "line_cap": serialize_drawing_value(
                drawing.get("lineCap")
            ),

            "line_join": drawing.get("lineJoin"),
            "dashes": drawing.get("dashes"),
            "layer": drawing.get("layer"),
            "sequence_number": drawing.get("seqno"),
            "level": drawing.get("level"),

            "scissor": serialize_drawing_value(
                drawing.get("scissor")
            ),

            "item_count": len(items),
            "primitive_types": dict(primitive_types),

            "items": [
                serialize_drawing_value(item)
                for item in items
            ],
        })

    return extracted


def summarize_page_drawings(
    drawings: list[dict[str, Any]]
) -> dict[str, Any]:
    """Summarize drawing and primitive types."""

    drawing_types = Counter(
        drawing.get("type", "unknown")
        for drawing in drawings
    )

    primitive_types = Counter()

    for drawing in drawings:
        primitive_types.update(
            drawing.get("primitive_types", {})
        )

    return {
        "drawing_type_counts": dict(drawing_types),
        "primitive_type_counts": dict(primitive_types),
        "total_drawings": len(drawings),
    }


# ============================================================
# TEXT-TO-DRAWING GEOMETRY RELATIONSHIPS
# ============================================================

def calculate_rectangle_relationship(
    text_bbox: list[float],
    drawing_bbox: list[float],
    proximity_tolerance: float = DEFAULT_PROXIMITY_TOLERANCE,
) -> dict[str, Any] | None:
    """
    Compare two bounding boxes geometrically.

    Possible relationships:
    - drawing_contains_text
    - text_contains_drawing
    - overlap
    - nearby

    This function records geometry only. It does not interpret
    the purpose of either object.
    """

    if (
        not isinstance(text_bbox, (tuple, list))
        or not isinstance(drawing_bbox, (tuple, list))
        or len(text_bbox) != 4
        or len(drawing_bbox) != 4
    ):
        return None

    try:
        tx0, ty0, tx1, ty1 = map(float, text_bbox)
        dx0, dy0, dx1, dy1 = map(float, drawing_bbox)
    except (TypeError, ValueError):
        return None

    text_width = max(0.0, tx1 - tx0)
    text_height = max(0.0, ty1 - ty0)

    drawing_width = max(0.0, dx1 - dx0)
    drawing_height = max(0.0, dy1 - dy0)

    text_area = text_width * text_height
    drawing_area = drawing_width * drawing_height

    intersection_x = max(
        0.0,
        min(tx1, dx1) - max(tx0, dx0)
    )

    intersection_y = max(
        0.0,
        min(ty1, dy1) - max(ty0, dy0)
    )

    intersection_area = intersection_x * intersection_y

    overlap_ratio_text = (
        intersection_area / text_area
        if text_area > 0
        else 0.0
    )

    overlap_ratio_drawing = (
        intersection_area / drawing_area
        if drawing_area > 0
        else 0.0
    )

    drawing_contains_text = (
        dx0 <= tx0
        and dy0 <= ty0
        and dx1 >= tx1
        and dy1 >= ty1
    )

    text_contains_drawing = (
        tx0 <= dx0
        and ty0 <= dy0
        and tx1 >= dx1
        and ty1 >= dy1
    )

    if drawing_contains_text:
        relationship = "drawing_contains_text"

    elif text_contains_drawing:
        relationship = "text_contains_drawing"

    elif intersection_area > 0:
        relationship = "overlap"

    else:
        horizontal_gap = max(
            0.0,
            dx0 - tx1,
            tx0 - dx1,
        )

        vertical_gap = max(
            0.0,
            dy0 - ty1,
            ty0 - dy1,
        )

        distance = (
            horizontal_gap ** 2
            + vertical_gap ** 2
        ) ** 0.5

        if distance > proximity_tolerance:
            return None

        relationship = "nearby"

    return {
        "relationship": relationship,

        "intersection_area": round(
            intersection_area, 2
        ),

        "text_overlap_ratio": round(
            overlap_ratio_text, 4
        ),

        "drawing_overlap_ratio": round(
            overlap_ratio_drawing, 4
        ),
    }


def build_drawing_relationship_records(
    text_bbox: list[float],
    drawings: list[dict[str, Any]],
    proximity_tolerance: float,
    minimum_text_overlap_ratio: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Compare one text bounding box against all extracted drawings.

    Optional overlap filtering removes tiny intersections that
    are unlikely to represent meaningful spatial relationships.

    Containment and nearby relationships are retained.
    """

    relationships = []

    for drawing in drawings:
        drawing_bbox = get_rectangle_coordinates(
            drawing.get("bbox")
        )

        if not drawing_bbox:
            continue

        comparison = calculate_rectangle_relationship(
            text_bbox,
            drawing_bbox,
            proximity_tolerance,
        )

        if comparison is None:
            continue

        relationship_type = comparison["relationship"]

        # Filter only weak partial overlaps.
        # Keep containment and nearby relationships.
        if (
            relationship_type == "overlap"
            and comparison["text_overlap_ratio"]
            < minimum_text_overlap_ratio
        ):
            continue

        relationships.append({
            "drawing_index": drawing["drawing_index"],

            "drawing_bbox": drawing["bbox"],

            "drawing_type": drawing.get("type"),

            "drawing_fill": drawing.get("fill"),

            "drawing_color": drawing.get("color"),

            "drawing_dimensions": drawing.get(
                "bbox_dimensions"
            ),

            "drawing_primitive_types": drawing.get(
                "primitive_types"
            ),

            **comparison,
        })

    return relationships


def analyze_text_drawing_relationships(
    blocks: list[dict[str, Any]],
    drawings: list[dict[str, Any]],
    proximity_tolerance: float = DEFAULT_PROXIMITY_TOLERANCE,
) -> list[dict[str, Any]]:
    """
    Preserve the original block-level relationship analysis.

    This remains available for compatibility and broad document
    inspection. It intentionally does not apply the stricter
    line-level overlap filter.
    """

    relationships = []

    for block in blocks:
        text_bbox = block.get("bbox")

        if not text_bbox or len(text_bbox) != 4:
            continue

        block_relationships = (
            build_drawing_relationship_records(
                text_bbox=text_bbox,
                drawings=drawings,
                proximity_tolerance=proximity_tolerance,
                minimum_text_overlap_ratio=0.0,
            )
        )

        if block_relationships:
            relationships.append({
                "block_sequence_number": block[
                    "sequence_number"
                ],
                "block_text": block["text"],
                "block_bbox": text_bbox,
                "relationships": block_relationships,
            })

    return relationships


def analyze_text_line_drawing_relationships(
    blocks: list[dict[str, Any]],
    drawings: list[dict[str, Any]],
    proximity_tolerance: float = DEFAULT_PROXIMITY_TOLERANCE,
    minimum_text_overlap_ratio: float = MIN_LINE_TEXT_OVERLAP_RATIO,
) -> list[dict[str, Any]]:
    """
    Analyze drawing relationships for individual text lines.

    Unlike block-level analysis, each line has its own bounding box.
    This prevents an entire row of text from being treated as one
    enormous text region.

    Negligible partial overlaps are filtered. Containment and
    nearby relationships are preserved.
    """

    line_results = []

    for block in blocks:
        block_sequence_number = block.get("sequence_number")

        for line in block.get("lines", []):
            line_bbox = line.get("bbox")

            if not line_bbox or len(line_bbox) != 4:
                continue

            line_relationships = (
                build_drawing_relationship_records(
                    text_bbox=line_bbox,
                    drawings=drawings,
                    proximity_tolerance=proximity_tolerance,
                    minimum_text_overlap_ratio=(
                        minimum_text_overlap_ratio
                    ),
                )
            )

            line_results.append({
                "block_sequence_number": (
                    block_sequence_number
                ),

                "line_sequence_number": line.get(
                    "sequence_number"
                ),

                "line_text": line.get("text", ""),

                "line_bbox": line_bbox,

                "relationships": line_relationships,
            })

    return line_results


# ============================================================
# PAGE ANALYSIS
# ============================================================

def analyze_page(page, page_number: int) -> dict[str, Any]:
    """Extract content and diagnostics from one PDF page."""

    try:
        raw_text = page.get_text("text", sort=True)

        words = extract_page_words(page)

        blocks = extract_page_blocks(page)

        image_data = inspect_page_images(page)

        drawings = extract_page_drawings(page)

        drawing_summary = summarize_page_drawings(drawings)

        # Original broad block-level analysis.
        text_drawing_relationships = (
            analyze_text_drawing_relationships(
                blocks,
                drawings,
            )
        )

        # More precise line-level analysis.
        text_line_drawing_relationships = (
            analyze_text_line_drawing_relationships(
                blocks,
                drawings,
            )
        )

    except Exception as error:
        raise PDFDocumentError(
            f"Could not analyze page {page_number}: {error}"
        ) from error

    word_count = len(words)
    character_count = len(raw_text.strip())
    drawing_count = len(drawings)

    content_type = classify_page_content(
        word_count=word_count,
        image_count=image_data["image_count"],
        image_area_ratio=image_data[
            "estimated_image_area_ratio"
        ],
        drawing_count=drawing_count,
    )

    return {
        "page_number": page_number,

        "width": round(page.rect.width, 2),

        "height": round(page.rect.height, 2),

        "rotation": page.rotation,

        "content_type": content_type,

        "has_selectable_text": word_count > 0,

        "word_count": word_count,

        "character_count": character_count,

        "image_count": image_data["image_count"],

        "estimated_image_area_ratio": image_data[
            "estimated_image_area_ratio"
        ],

        "drawing_count": drawing_count,

        "text": raw_text,

        "words": words,

        "blocks": blocks,

        "images": image_data["images"],

        "drawings": drawings,

        "drawing_summary": drawing_summary,

        "text_drawing_relationships": (
            text_drawing_relationships
        ),

        "text_line_drawing_relationships": (
            text_line_drawing_relationships
        ),
    }


# ============================================================
# DOCUMENT CLASSIFICATION
# ============================================================

def classify_document_pages(
    pages: list[dict[str, Any]]
) -> str:
    """Determine the overall content type of a document."""

    if not pages:
        return CONTENT_EMPTY

    content_types = {
        page["content_type"]
        for page in pages
    }

    if CONTENT_MIXED in content_types:
        return CONTENT_MIXED

    has_text = any(
        page["has_selectable_text"]
        for page in pages
    )

    has_image_content = any(
        page["content_type"] in {
            CONTENT_IMAGE_ONLY,
            CONTENT_IMAGE_CONTENT,
        }
        for page in pages
    )

    has_graphics = any(
        page["drawing_count"] > 0
        for page in pages
    )

    if has_text and has_image_content:
        return CONTENT_MIXED

    if has_text:
        return CONTENT_SELECTABLE_TEXT

    if CONTENT_IMAGE_ONLY in content_types:
        return CONTENT_IMAGE_ONLY

    if CONTENT_IMAGE_CONTENT in content_types:
        return CONTENT_IMAGE_CONTENT

    if has_graphics:
        return CONTENT_GRAPHICS_ONLY

    return CONTENT_EMPTY


# ============================================================
# PUBLIC DOCUMENT ANALYSIS FUNCTION
# ============================================================

def analyze_pdf_document(
    pdf_path: str | Path
) -> dict[str, Any]:
    """
    Open and analyze a PDF without interpreting its subject matter.

    This is the reusable entry point for future PDF importers.

    It does not:
    - Identify players.
    - Identify football plays.
    - Assume a roster layout.
    - Assume a particular school or organization.
    - Perform OCR.
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise PDFDocumentError(
            f"PDF file not found: {pdf_path}"
        )

    if not pdf_path.is_file():
        raise PDFDocumentError(
            f"The selected path is not a file: {pdf_path}"
        )

    if pdf_path.suffix.lower() != ".pdf":
        raise PDFDocumentError(
            "The selected file is not a PDF."
        )

    try:
        with pymupdf.open(pdf_path) as document:

            if document.is_encrypted:
                raise PDFDocumentError(
                    "This PDF is password-protected."
                )

            if len(document) == 0:
                raise PDFDocumentError(
                    "This PDF does not contain any pages."
                )

            page_results = []

            for page_number, page in enumerate(
                document, start=1
            ):
                page_results.append(
                    analyze_page(page, page_number)
                )

            total_words = sum(
                page["word_count"]
                for page in page_results
            )

            total_characters = sum(
                page["character_count"]
                for page in page_results
            )

            total_images = sum(
                page["image_count"]
                for page in page_results
            )

            total_drawings = sum(
                page["drawing_count"]
                for page in page_results
            )

            return {
                "file_name": pdf_path.name,

                "file_path": str(pdf_path.resolve()),

                "page_count": len(document),

                "document_content_type": (
                    classify_document_pages(page_results)
                ),

                "has_selectable_text": total_words > 0,

                "total_words": total_words,

                "total_characters": total_characters,

                "total_images": total_images,

                "total_drawings": total_drawings,

                "metadata": document.metadata or {},

                "pages": page_results,
            }

    except PDFDocumentError:
        raise

    except Exception as error:
        raise PDFDocumentError(
            f"Could not analyze PDF: {error}"
        ) from error


# ============================================================
# SIMPLE COMMAND-LINE INSPECTION
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print(
            'Usage: python pdf_document_engine.py "path/to/file.pdf"'
        )
        raise SystemExit(1)

    try:
        result = analyze_pdf_document(sys.argv[1])

        print("\nPDF DOCUMENT ANALYSIS")
        print("=" * 70)

        print(f"File: {result['file_name']}")
        print(f"Pages: {result['page_count']}")

        print(
            f"Content type: "
            f"{result['document_content_type']}"
        )

        print(
            f"Selectable text: "
            f"{result['has_selectable_text']}"
        )

        print(f"Words: {result['total_words']}")
        print(f"Images: {result['total_images']}")
        print(f"Drawings: {result['total_drawings']}")

        print("\nPAGE BREAKDOWN")
        print("=" * 70)

        for page in result["pages"]:
            print(
                f"Page {page['page_number']}: "
                f"{page['content_type']} | "
                f"{page['word_count']} words | "
                f"{page['image_count']} images | "
                f"{page['drawing_count']} drawings"
            )

    except PDFDocumentError as error:
        print(f"\nPDF ANALYSIS FAILED: {error}")
        raise SystemExit(1)
