import sys
from pathlib import Path
from pdf_image_extractor import extract_images, extract_vector_diagrams


# Define what constitutes a "content image"
# Most diagrams and photos are larger than 200px. 
# Icons/Logos are usually smaller.
MIN_WIDTH = 200
MIN_HEIGHT = 200


def run_extraction(pdf_filename: str, output_path: str, min_w: int = 200, min_h: int = 200):
    pdf_file = Path(pdf_filename)
    
    if not pdf_file.exists():
        print(f"Error: The file '{pdf_filename}' was not found.")
        sys.exit(1)

    # --- Raster images (embedded JPEGs, PNGs, etc.) ---
    result = extract_images(str(pdf_file), output_dir=Path(output_path) / "raster")

    # Filter images to keep only those that meet the "content" criteria
    content_images = [
        img for img in result.images 
        if img.width >= min_w and img.height >= min_h
    ]

    print(f"Raster images: Processed {result.pages_processed} pages. "
          f"Found {len(content_images)} content images "
          f"(skipped {result.kept - len(content_images)} small assets).")

    if content_images:
        for img in content_images:
            print(f"  - Page {img.page}: {img.filename} ({img.width}x{img.height})")
    else:
        print("  No raster images matched the 'content' size criteria.")

    # --- Vector diagrams (flowcharts, matrices, etc.) ---
    print()
    vector_results = extract_vector_diagrams(
        pdf_file,
        output_dir=Path(output_path) / "vector",
        dpi=200,
    )

    print(f"Vector diagrams: Found {len(vector_results)} diagram(s).")

    if vector_results:
        for r in vector_results:
            size_kb = r["size"] / 1024
            print(f"  - Page {r['page']}: {r['name']} "
                  f"({r['width']}x{r['height']}, {size_kb:.1f} KB, "
                  f"{r['drawings']} drawings)")
    else:
        print("  No vector diagrams detected.")


if __name__ == "__main__":
    run_extraction("chapter04.pdf", output_path="./images", min_w=MIN_WIDTH, min_h=MIN_HEIGHT)
