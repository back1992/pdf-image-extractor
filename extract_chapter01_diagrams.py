"""Extract the 3 vector diagrams from chapter01.pdf.

Target diagrams:
  1. Shannon's Communication Model (page 16) — linear flowchart with noise source
  2. Schramm's Communication Model (page 17) — simplified linear model
  3. Lasswell's 5W Model Matrix (page 22) — 5×4 matrix grid

These are vector graphics drawn with PDF primitives, not embedded raster images.
Bounding boxes were measured by inspecting drawing rects and custom-font text blocks,
excluding header/footer decorative lines.
"""
from pathlib import Path
from pdf_image_extractor import extract_diagram_regions


# Measured bounding boxes (PDF points) with 10pt padding,
# filtered to exclude header/footer noise lines.
DIAGRAM_REGIONS = {
    16: {
        "bbox": (133.1, 297.1, 391.3, 427.9),
        "name": "shannon_model",
    },
    17: {
        "bbox": (121.6, 437.8, 402.8, 491.0),
        "name": "schramm_model",
    },
    22: {
        "bbox": (110.5, 78.0, 413.9, 184.1),
        "name": "lasswell_matrix",
    },
}


def main():
    pdf_path = Path("chapter01.pdf")
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found.")
        raise SystemExit(1)

    output_dir = Path("output/diagrams")

    results = extract_diagram_regions(
        pdf_path=pdf_path,
        regions=DIAGRAM_REGIONS,
        output_dir=output_dir,
        dpi=200,
    )

    print(f"Extracted {len(results)} diagrams to {output_dir}/\n")
    for r in results:
        size_kb = r["size"] / 1024
        print(
            f"  {r['name']:20s}  page {r['page']:2d}  "
            f"{r['width']}x{r['height']}px  {size_kb:.1f} KB  {r['path']}"
        )


if __name__ == "__main__":
    main()
