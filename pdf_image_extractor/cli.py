"""Command-line interface for PDF Image Extractor."""

import argparse
import json
import os

from dotenv import load_dotenv
import sys
from pathlib import Path

from .extractor import extract_images
from .config import ImageFilterConfig
from .page_renderer import extract_diagram_regions, extract_vector_diagrams


def main():
    # Load environment variables from .env file
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        description="Extract images from PDF files with smart filtering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pdf-image-extract document.pdf ./images
  pdf-image-extract document.pdf ./images --min-width 200 --min-height 200
  pdf-image-extract document.pdf ./images --format png
  pdf-image-extract document.pdf ./images --json
        """,
    )
    
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("output", help="Output directory for images")
    
    # Filter options
    parser.add_argument("--min-width", type=int, default=150, help="Minimum width in pixels (default: 150)")
    parser.add_argument("--min-height", type=int, default=150, help="Minimum height in pixels (default: 150)")
    parser.add_argument("--min-size", type=int, default=3072, help="Minimum file size in bytes (default: 3072)")
    parser.add_argument("--min-ratio", type=float, default=0.08, help="Minimum page ratio (default: 0.08)")
    parser.add_argument("--max-ratio", type=float, default=0.95, help="Maximum page ratio (default: 0.95)")
    
    # Vision model options
    parser.add_argument("--vision", action="store_true", help="Enable vision model filtering")
    parser.add_argument("--vision-provider", choices=["openai", "dashscope"], default="openai",
                        help="Vision API provider (default: openai)")
    parser.add_argument("--vision-api-key", type=str, default="",
                        help="API key for vision model (or set OPENAI_API_KEY / DASHSCOPE_API_KEY env var)")
    parser.add_argument("--vision-model", type=str, default="",
                        help="Vision model name (auto-selected per provider if omitted)")
    
    # Output options
    parser.add_argument("--format", choices=["original", "png", "jpeg"], default="original", help="Output format (default: original)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    
    args = parser.parse_args()
    
    # Validate input
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    
    # Resolve vision API key from args or environment
    vision_api_key = args.vision_api_key
    if args.vision and not vision_api_key:
        if args.vision_provider == "dashscope":
            vision_api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        else:
            vision_api_key = os.environ.get("OPENAI_API_KEY", "")

    # Build config
    config = {
        "min_width": args.min_width,
        "min_height": args.min_height,
        "min_file_size": args.min_size,
        "min_page_ratio_width": args.min_ratio,
        "min_page_ratio_height": args.min_ratio,
        "max_page_ratio_width": args.max_ratio,
        "max_page_ratio_height": args.max_ratio,
        "output_format": args.format,
        "use_vision_model": args.vision,
        "vision_provider": args.vision_provider,
        "vision_api_key": vision_api_key,
    }

    # Only override vision_model if user explicitly provided it
    if args.vision_model:
        config["vision_model"] = args.vision_model
    
    # Extract
    result = extract_images(pdf_path, Path(args.output), config)
    
    # Output
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif not args.quiet:
        print(f"Extracted {result.kept}/{result.total_found} images from {result.pages_processed} pages")
        for img in result.images:
            print(f"  Page {img.page:3}: {img.filename:35} {img.width}x{img.height} ({img.size//1024}KB)")


if __name__ == "__main__":
    main()


def diagrams_main():
    """Entry point for the pdf-image-extract-diagrams command."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Extract vector diagram regions from a PDF as PNG images.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fully automatic — detect and extract all diagrams in the PDF
  pdf-image-extract-diagrams chapter01.pdf ./diagrams

  # Auto-detect diagram bboxes on specific pages
  pdf-image-extract-diagrams chapter01.pdf ./diagrams --pages 16,17,22

  # Provide explicit bounding boxes (x0,y0,x1,y1 in PDF points)
  pdf-image-extract-diagrams chapter01.pdf ./diagrams \\
      --region "16:133,297,391,428:shannon_model" \\
      --region "17:122,438,403,491:schramm_model" \\
      --region "22:111,78,414,184:lasswell_matrix"
        """,
    )

    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("output", help="Output directory for diagram images")
    parser.add_argument(
        "--pages",
        type=str,
        default="",
        help="Comma-separated page numbers for auto-detection (e.g. 16,17,22)",
    )
    parser.add_argument(
        "--region",
        action="append",
        dest="regions",
        metavar="PAGE:X0,Y0,X1,Y1:NAME",
        help=(
            "Explicit region spec: PAGE:X0,Y0,X1,Y1:NAME  "
            "(NAME is optional). Can be repeated."
        ),
    )
    parser.add_argument(
        "--dpi", type=int, default=200, help="Render resolution in DPI (default: 200)"
    )
    parser.add_argument(
        "--min-drawings",
        type=int,
        default=5,
        help="Min drawings per cluster for auto-detection (default: 5)",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=50.0,
        help="Clustering gap threshold in points (default: 50)",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    # Build the regions dict from CLI inputs
    region_specs: dict = {}

    # --pages  →  auto-detect bbox on each listed page
    if args.pages:
        for part in args.pages.split(","):
            part = part.strip()
            if part:
                page_num = int(part)
                region_specs[page_num] = {"name": f"diagram"}

    # --region PAGE:X0,Y0,X1,Y1:NAME  →  explicit bbox
    for raw in args.regions or []:
        parts = raw.split(":")
        if len(parts) < 2:
            print(f"Error: invalid --region format '{raw}'", file=sys.stderr)
            sys.exit(1)
        page_num = int(parts[0])
        coords = tuple(float(v) for v in parts[1].split(","))
        if len(coords) != 4:
            print(
                f"Error: bbox must be four numbers x0,y0,x1,y1 — got '{parts[1]}'",
                file=sys.stderr,
            )
            sys.exit(1)
        name = parts[2] if len(parts) >= 3 else f"diagram"
        region_specs[page_num] = {"bbox": coords, "name": name}

    # Fully automatic mode: no --pages or --region given
    if not region_specs:
        results = extract_vector_diagrams(
            pdf_path=pdf_path,
            output_dir=Path(args.output),
            dpi=args.dpi,
            min_drawings=args.min_drawings,
            gap=args.gap,
        )
    else:
        results = extract_diagram_regions(
            pdf_path=pdf_path,
            regions=region_specs,
            output_dir=Path(args.output),
            dpi=args.dpi,
        )

    if args.json:
        # Convert tuples to lists for JSON serialization
        serializable = []
        for r in results:
            sr = dict(r)
            if "bbox" in sr and isinstance(sr["bbox"], tuple):
                sr["bbox"] = list(sr["bbox"])
            serializable.append(sr)
        print(json.dumps(serializable, indent=2))
    else:
        if not results:
            print("No diagrams detected.")
        else:
            print(f"Extracted {len(results)} diagram(s):")
            for r in results:
                drawings_info = ""
                if "drawings" in r:
                    drawings_info = f"  ({r['drawings']} drawings)"
                print(
                    f"  Page {r['page']:3}: {Path(r['path']).name:45} "
                    f"{r['width']}x{r['height']}px  ({r['size'] // 1024} KB)"
                    f"{drawings_info}"
                )
