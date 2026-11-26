
import sys
from pathlib import Path
from collections import Counter

from pdf_document_engine import analyze_pdf_document


def print_separator():
    print("=" * 90)


def get_bbox(word):
    bbox = word.get("bbox", (0, 0, 0, 0))
    return tuple(float(value) for value in bbox)


def group_words_into_visual_lines(words, tolerance=3.0):
    """
    Group words by their vertical position rather than relying
    on the PDF's internal text-reading order.
    """
    sorted_words = sorted(
        words,
        key=lambda word: (
            (get_bbox(word)[1] + get_bbox(word)[3]) / 2,
            get_bbox(word)[0],
        ),
    )

    lines = []

    for word in sorted_words:
        x0, y0, x1, y1 = get_bbox(word)
        center_y = (y0 + y1) / 2

        matching_line = None

        for line in lines:
            if abs(center_y - line["center_y"]) <= tolerance:
                matching_line = line
                break

        if matching_line is None:
            matching_line = {
                "center_y": center_y,
                "words": [],
            }
            lines.append(matching_line)

        matching_line["words"].append(word)

        # Update the representative vertical position.
        centers = [
            (get_bbox(item)[1] + get_bbox(item)[3]) / 2
            for item in matching_line["words"]
        ]
        matching_line["center_y"] = sum(centers) / len(centers)

    for line in lines:
        line["words"].sort(key=lambda word: get_bbox(word)[0])

    return sorted(lines, key=lambda line: line["center_y"])


def inspect_page(page):
    print_separator()
    print(f"PAGE {page['page_number']}")
    print_separator()

    print(f"Words: {page['word_count']}")
    print(f"Text blocks: {len(page['blocks'])}")
    print(f"Images: {page['image_count']}")
    print(f"Drawings: {page['drawing_count']}")

    print("\n--- VISUAL TEXT LINES (TOP TO BOTTOM, LEFT TO RIGHT) ---")

    visual_lines = group_words_into_visual_lines(page["words"])

    for index, line in enumerate(visual_lines, start=1):
        words = line["words"]

        text = " ".join(word["text"] for word in words)

        x_values = [get_bbox(word)[0] for word in words]
        y_values = [get_bbox(word)[1] for word in words]
        right_values = [get_bbox(word)[2] for word in words]
        bottom_values = [get_bbox(word)[3] for word in words]

        bbox = (
            min(x_values),
            min(y_values),
            max(right_values),
            max(bottom_values),
        )

        print(f"\nLine {index} | Y center: {line['center_y']:.2f}")
        print(f"  Bounding box: {bbox}")
        print(f"  Text: {text}")

        for word in words:
            print(
                f"    {word['text']!r:<25} "
                f"x={get_bbox(word)[0]:7.2f} "
                f"y={get_bbox(word)[1]:7.2f} "
                f"block={word.get('block_number')} "
                f"line={word.get('line_number')}"
            )

    print("\n--- TEXT BLOCK SUMMARY ---")

    for block in page["blocks"]:
        print(
            f"\nBlock {block['sequence_number']} | "
            f"BBox: {block['bbox']}"
        )
        print(f"  {block['text'][:500]!r}")

    print("\n--- DRAWING SUMMARY ---")

    drawings = page.get("drawings", [])

    drawing_types = Counter(
        drawing.get("type", "unknown")
        for drawing in drawings
    )

    primitive_types = Counter(
        item[0]
        for drawing in drawings
        for item in drawing.get("items", [])
        if isinstance(item, (list, tuple))
        and item
        and isinstance(item[0], str)
    )

    print(f"Drawing categories: {dict(drawing_types)}")
    print(f"Drawing primitives: {dict(primitive_types)}")

    print("\nFirst 20 drawing bounding boxes:")

    for drawing in drawings[:20]:
        print(
            f"  Drawing {drawing.get('drawing_index')}: "
            f"{drawing.get('bbox')} | "
            f"Type: {drawing.get('type')}"
        )


def inspect_pdf(pdf_path, selected_page=None):
    result = analyze_pdf_document(pdf_path)

    print_separator()
    print("PDF VISUAL STRUCTURE DIAGNOSTIC")
    print_separator()

    print(f"File: {result['file_name']}")
    print(f"Pages: {result['page_count']}")
    print(f"Total words: {result['total_words']}")
    print(f"Total drawings: {result['total_drawings']}")

    pages = result["pages"]

    if selected_page is not None:
        if selected_page < 1 or selected_page > len(pages):
            raise ValueError(
                f"Page {selected_page} does not exist. "
                f"This PDF has {len(pages)} pages."
            )

        pages = [pages[selected_page - 1]]

    for page in pages:
        inspect_page(page)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            'Usage: python src/pdf_structure_test.py "path/to/file.pdf" [page_number]'
        )
        sys.exit(1)

    try:
        pdf_path = Path(sys.argv[1])

        selected_page = None

        if len(sys.argv) >= 3:
            selected_page = int(sys.argv[2])

        inspect_pdf(pdf_path, selected_page)

    except Exception as error:
        print(f"\nTEST FAILED: {error}")
        sys.exit(1)
