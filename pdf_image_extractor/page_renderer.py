"""
Render entire pages or page regions as images when they contain complex diagrams.

Supports both manual bounding-box extraction and fully automatic diagram detection
with noise filtering and spatial clustering.
"""
import fitz
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_noise_drawing(drawing: dict, page_rect: fitz.Rect) -> bool:
    """Return True if a drawing is likely a header/footer decorative line.

    Noise patterns:
    - Single horizontal line (``l`` item with y0 ≈ y1) near the top or
      bottom 10 % of the page.
    - Single horizontal line spanning > 80 % of the page width (full-width
      rule), regardless of vertical position.
    """
    items = drawing["items"]
    if len(items) != 1 or items[0][0] != "l":
        return False

    rect = drawing["rect"]
    is_horizontal = abs(rect.height) < 2.0

    if not is_horizontal:
        return False

    near_top = rect.y0 < page_rect.height * 0.10
    near_bottom = rect.y0 > page_rect.height * 0.88
    full_width = rect.width > page_rect.width * 0.80

    return (near_top or near_bottom) or full_width


def _filter_noise_drawings(
    drawings: list, page_rect: fitz.Rect
) -> list:
    """Remove header/footer decorative lines from a list of drawings."""
    return [d for d in drawings if not _is_noise_drawing(d, page_rect)]


def _is_diagram_label(block: tuple, cluster_rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    """Return True if a text block is likely a label belonging to a diagram cluster.

    A text block is considered a diagram label if it:
    - Overlaps horizontally with the cluster (or is within it).
    - Is close to the cluster vertically (within 20 pt above, or inside).
    - Does **not** span > 70 % of the page width (body-text paragraphs do).
    - Is not near the page top (headers) or bottom (footers).
    """
    bx0, by0, bx1, by1 = block[0], block[1], block[2], block[3]
    block_rect = fitz.Rect(bx0, by0, bx1, by1)
    block_width = bx1 - bx0

    # Reject full-width body text (> 70 % of page width)
    if block_width > page_rect.width * 0.70:
        return False

    # Reject page headers and footers
    if by0 < page_rect.height * 0.10 or by0 > page_rect.height * 0.88:
        return False

    # Must overlap horizontally with the cluster
    if bx1 < cluster_rect.x0 or bx0 > cluster_rect.x1:
        return False

    # Must be within 20 pt above the cluster, or inside it
    above_limit = cluster_rect.y0 - 20.0
    below_limit = cluster_rect.y1 + 5.0
    if by1 < above_limit or by0 > below_limit:
        return False

    return True


def _expand_bbox_with_labels(
    bbox: fitz.Rect,
    text_blocks: list,
    page_rect: fitz.Rect,
    padding: float = 10.0,
) -> fitz.Rect:
    """Expand *bbox* to include nearby text blocks that look like diagram labels.

    This captures custom-font diagram labels that sit above or between
    drawing elements but are not part of ``page.get_drawings()``.
    """
    expanded = fitz.Rect(bbox)

    for block in text_blocks:
        if _is_diagram_label(block, expanded, page_rect):
            block_rect = fitz.Rect(block[0], block[1], block[2], block[3])
            expanded.include_rect(block_rect)

    # Re-apply padding and clamp
    expanded.x0 = max(page_rect.x0, expanded.x0 - padding)
    expanded.y0 = max(page_rect.y0, expanded.y0 - padding)
    expanded.x1 = min(page_rect.x1, expanded.x1 + padding)
    expanded.y1 = min(page_rect.y1, expanded.y1 + padding)

    return expanded


def _cluster_drawings(
    drawings: list, gap: float = 50.0
) -> List[List[dict]]:
    """Group drawings into spatial clusters separated by *gap* points.

    Algorithm:
    1. Sort drawing rects by (y0, x0).
    2. Sweep: expand the current cluster bbox with any rect that is within
       *gap* points of it.  When no remaining rect fits, start a new cluster.

    Returns a list of clusters, each cluster being a list of drawing dicts.
    """
    if not drawings:
        return []

    # Sort by vertical position first, then horizontal
    sorted_drawings = sorted(drawings, key=lambda d: (d["rect"].y0, d["rect"].x0))

    clusters: List[List[dict]] = []
    remaining = list(sorted_drawings)

    while remaining:
        # Start a new cluster with the first remaining drawing
        cluster = [remaining.pop(0)]
        cluster_rect = fitz.Rect(cluster[0]["rect"])

        # Keep expanding the cluster while we find nearby drawings
        changed = True
        while changed:
            changed = False
            still_remaining = []
            for d in remaining:
                dr = fitz.Rect(d["rect"])
                # Check if this drawing is within `gap` of the cluster bbox
                expanded = fitz.Rect(
                    cluster_rect.x0 - gap,
                    cluster_rect.y0 - gap,
                    cluster_rect.x1 + gap,
                    cluster_rect.y1 + gap,
                )
                if expanded.intersects(dr):
                    cluster.append(d)
                    cluster_rect.include_rect(dr)
                    changed = True
                else:
                    still_remaining.append(d)
            remaining = still_remaining

        clusters.append(cluster)

    return clusters


# ---------------------------------------------------------------------------
# Public API — page rendering
# ---------------------------------------------------------------------------

def render_page_as_image(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
    dpi: int = 200,
    clip_region: bool = True
) -> Dict:
    """
    Render an entire page (or content region) as a raster image.
    
    This is useful for pages with complex diagrams made of vector graphics
    that can't be extracted as embedded images.
    
    Args:
        pdf_path: Path to PDF file
        page_number: Page number (1-indexed)
        output_dir: Directory to save rendered image
        dpi: Resolution for rendering (default 200)
        clip_region: If True, only render content area (skip headers/footers)
    
    Returns:
        Dict with info about rendered image
    """
    with fitz.open(str(pdf_path)) as doc:
        if page_number < 1 or page_number > doc.page_count:
            raise ValueError(f"Invalid page number: {page_number}")

        page = doc[page_number - 1]  # Convert to 0-indexed
        page_rect = page.rect

        # Determine clip region
        if clip_region:
            # Skip top 10% and bottom 10% (headers/footers)
            clip = fitz.Rect(
                page_rect.x0,
                page_rect.y0 + page_rect.height * 0.10,
                page_rect.x1,
                page_rect.y1 - page_rect.height * 0.10
            )
        else:
            clip = page_rect

        # Calculate matrix for desired DPI
        # Base DPI is 72, so multiply by dpi/72
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        # Render page
        pix = page.get_pixmap(matrix=matrix, clip=clip)

        # Save as PNG
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"page_{page_number}_rendered.png"
        output_path = output_dir / filename
        pix.save(str(output_path))
    
    logger.info(f"Rendered page {page_number} as image: {filename}")
    
    return {
        "filename": filename,
        "page_number": page_number,
        "width": pix.width,
        "height": pix.height,
        "size": output_path.stat().st_size,
        "path": str(output_path)
    }


# ---------------------------------------------------------------------------
# Public API — diagram detection
# ---------------------------------------------------------------------------

def detect_pages_with_diagrams(
    pdf_path: Path,
    min_drawings: int = 10,
    min_text_blocks: int = 5
) -> List[int]:
    """
    Detect pages that likely contain complex diagrams.

    Uses noise-filtered drawing counts (header/footer rules are excluded).

    Criteria:
    - Many drawings/paths (vector graphics) after noise filtering
    - Some text (likely labels)
    - Few or no dominant embedded images (> 20 % of page area)
    
    Args:
        pdf_path: Path to PDF file
        min_drawings: Minimum number of drawings to consider
        min_text_blocks: Minimum number of text blocks
    
    Returns:
        List of page numbers (1-indexed) with potential diagrams
    """
    with fitz.open(str(pdf_path)) as doc:
        diagram_pages = []

        for page_num in range(doc.page_count):
            page = doc[page_num]
            page_rect = page.rect

            # Count drawings (noise-filtered)
            all_drawings = page.get_drawings()
            filtered_drawings = _filter_noise_drawings(all_drawings, page_rect)

            # Count text blocks
            text_blocks = page.get_text("blocks")

            # Count dominant embedded images (> 20% of page area)
            images = page.get_images(full=True)
            dominant_images = 0
            for img in images:
                rects = page.get_image_rects(img[0])
                if rects:
                    rect = rects[0]
                    area = rect.width * rect.height
                    page_area = page_rect.width * page_rect.height
                    if area / page_area > 0.20:
                        dominant_images += 1

            # Decision logic
            if (len(filtered_drawings) >= min_drawings and
                len(text_blocks) >= min_text_blocks and
                dominant_images == 0):

                diagram_pages.append(page_num + 1)  # Convert to 1-indexed
                logger.debug(
                    f"Page {page_num + 1}: {len(filtered_drawings)} drawings "
                    f"(filtered from {len(all_drawings)}), "
                    f"{len(text_blocks)} text blocks, {dominant_images} dominant images"
                )
    
    logger.info(f"Found {len(diagram_pages)} pages with potential diagrams")
    return diagram_pages


def render_diagram_pages(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 200,
    clip_region: bool = True,
    min_drawings: int = 10,
    min_text_blocks: int = 5
) -> List[Dict]:
    """
    Automatically detect and render pages with complex diagrams.
    
    Args:
        pdf_path: Path to PDF file
        output_dir: Directory to save rendered images
        dpi: Resolution for rendering
        clip_region: If True, only render content area
        min_drawings: Minimum number of vector drawings to consider as diagram
        min_text_blocks: Minimum number of text blocks (likely labels)
    
    Returns:
        List of rendered image info dicts
    """
    diagram_pages = detect_pages_with_diagrams(pdf_path, min_drawings, min_text_blocks)
    
    rendered = []
    for page_num in diagram_pages:
        try:
            result = render_page_as_image(
                pdf_path, page_num, output_dir, dpi, clip_region
            )
            rendered.append(result)
        except Exception as e:
            logger.error(f"Failed to render page {page_num}: {e}")
    
    return rendered


def auto_detect_diagram_bbox(
    page: fitz.Page,
    padding: float = 10.0,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Compute a tight bounding box around all vector drawings on a page.

    Header/footer decorative lines are filtered out before computing the
    merged bounding rectangle.

    Args:
        page: An open ``fitz.Page`` object.
        padding: Extra space (in PDF points) to add on each side.

    Returns:
        ``(x0, y0, x1, y1)`` in PDF points, or ``None`` if no drawings exist.
    """
    drawings = page.get_drawings()
    filtered = _filter_noise_drawings(drawings, page.rect)
    if not filtered:
        return None

    x0 = min(d["rect"].x0 for d in filtered)
    y0 = min(d["rect"].y0 for d in filtered)
    x1 = max(d["rect"].x1 for d in filtered)
    y1 = max(d["rect"].y1 for d in filtered)

    page_rect = page.rect
    x0 = max(page_rect.x0, x0 - padding)
    y0 = max(page_rect.y0, y0 - padding)
    x1 = min(page_rect.x1, x1 + padding)
    y1 = min(page_rect.y1, y1 + padding)

    return (x0, y0, x1, y1)


def detect_diagram_regions(
    pdf_path: Path,
    min_drawings: int = 5,
    min_region_area: float = 1000.0,
    gap: float = 50.0,
    padding: float = 10.0,
) -> Dict[int, List[Dict]]:
    """
    Detect diagram regions on every page of a PDF.

    For each page:
    1. Get all vector drawings via ``page.get_drawings()``.
    2. Filter out noise (header/footer decorative lines).
    3. Cluster remaining drawings by spatial proximity.
    4. Discard clusters with fewer than *min_drawings* drawings or
       smaller than *min_region_area* square points.

    Args:
        pdf_path: Path to the PDF file.
        min_drawings: Minimum drawings in a cluster to qualify as a diagram.
        min_region_area: Minimum bbox area (sq pts) to keep a cluster.
        gap: Clustering gap threshold in PDF points — drawings farther
             apart than this become separate clusters.
        padding: Padding (pts) added around each cluster bbox.

    Returns:
        Dict mapping 1-indexed page numbers to lists of region dicts::

            {
                16: [{"bbox": (x0, y0, x1, y1), "drawings": 9, "area": 33726.0}],
                22: [{"bbox": (x0, y0, x1, y1), "drawings": 27, "area": 32168.0}],
            }
    """
    result: Dict[int, List[Dict]] = {}

    with fitz.open(str(pdf_path)) as doc:
        for page_num in range(doc.page_count):
            page = doc[page_num]
            page_rect = page.rect

            all_drawings = page.get_drawings()
            filtered = _filter_noise_drawings(all_drawings, page_rect)

            if len(filtered) < min_drawings:
                continue

            clusters = _cluster_drawings(filtered, gap=gap)
            text_blocks = page.get_text("blocks")
            page_regions: List[Dict] = []

            for cluster in clusters:
                if len(cluster) < min_drawings:
                    continue

                # Compute cluster bbox
                cx0 = min(d["rect"].x0 for d in cluster)
                cy0 = min(d["rect"].y0 for d in cluster)
                cx1 = max(d["rect"].x1 for d in cluster)
                cy1 = max(d["rect"].y1 for d in cluster)

                # Expand to include nearby diagram labels (custom-font text)
                cluster_rect = fitz.Rect(cx0, cy0, cx1, cy1)
                expanded = _expand_bbox_with_labels(
                    cluster_rect, text_blocks, page_rect, padding=padding
                )

                area = expanded.width * expanded.height
                if area < min_region_area:
                    continue

                page_regions.append({
                    "bbox": (expanded.x0, expanded.y0, expanded.x1, expanded.y1),
                    "drawings": len(cluster),
                    "area": round(area, 1),
                })

            if page_regions:
                result[page_num + 1] = page_regions  # 1-indexed

    logger.info(
        f"Detected diagram regions on {len(result)} pages: "
        f"{', '.join(f'p{p}({len(r)})' for p, r in result.items())}"
    )
    return result


# ---------------------------------------------------------------------------
# Public API — region extraction
# ---------------------------------------------------------------------------

def extract_diagram_regions(
    pdf_path: Path,
    regions: Dict[int, Dict],
    output_dir: Path,
    dpi: int = 200,
) -> List[Dict]:
    """
    Render specific bounding-box regions of PDF pages as PNG images.

    Each region can supply an explicit ``bbox`` or omit it to trigger
    automatic bounding-box detection from the page's vector drawings.

    Args:
        pdf_path: Path to the PDF file.
        regions: Mapping of ``{page_number: {"name": str, "bbox": (x0,y0,x1,y1)}}``.
                 ``page_number`` is 1-indexed.  ``bbox`` is optional — when
                 absent the bbox is auto-detected from drawings on that page.
        output_dir: Directory where PNG files are written.
        dpi: Render resolution (default 200, minimum recommended 150).

    Returns:
        List of dicts with keys ``name``, ``page``, ``bbox``, ``path``,
        ``width``, ``height``, ``size``.

    Raises:
        ValueError: If a page number is out of range or no bbox can be found.

    Example::

        regions = {
            17: {"bbox": (50, 200, 550, 400), "name": "shannon_model"},
            18: {"bbox": (50, 150, 550, 250), "name": "schramm_model"},
            23: {"name": "lasswell_matrix"},  # auto-detect bbox
        }
        results = extract_diagram_regions("chapter01.pdf", regions, "./diagrams")
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    results: List[Dict] = []

    with fitz.open(str(pdf_path)) as doc:
        for page_num, spec in regions.items():
            if page_num < 1 or page_num > doc.page_count:
                raise ValueError(
                    f"Page {page_num} is out of range (document has {doc.page_count} pages)"
                )

            page = doc[page_num - 1]  # fitz uses 0-based indexing
            name = spec.get("name", f"page_{page_num}_diagram")

            if "bbox" in spec:
                bbox = spec["bbox"]
                clip = fitz.Rect(*bbox)
            else:
                detected = auto_detect_diagram_bbox(page)
                if detected is None:
                    raise ValueError(
                        f"No vector drawings found on page {page_num}; "
                        "provide an explicit 'bbox' in the region spec."
                    )
                clip = fitz.Rect(*detected)
                bbox = tuple(detected)

            pix = page.get_pixmap(matrix=matrix, clip=clip)

            filename = f"page_{page_num}_{name}.png"
            output_path = output_dir / filename
            pix.save(str(output_path))

            logger.info(
                f"Saved {filename} ({pix.width}x{pix.height}px, "
                f"bbox={bbox}, dpi={dpi})"
            )

            results.append(
                {
                    "name": name,
                    "page": page_num,
                    "bbox": bbox,
                    "path": str(output_path),
                    "width": pix.width,
                    "height": pix.height,
                    "size": output_path.stat().st_size,
                }
            )

    return results


# ---------------------------------------------------------------------------
# Public API — end-to-end extraction
# ---------------------------------------------------------------------------

def extract_vector_diagrams(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 200,
    min_drawings: int = 5,
    min_region_area: float = 1000.0,
    gap: float = 50.0,
) -> List[Dict]:
    """
    Automatically detect and extract all vector diagrams from a PDF.

    This is the fully automatic end-to-end pipeline:
    1. Scan every page for vector drawing clusters.
    2. Filter noise and small clusters.
    3. Render each detected region as a cropped PNG.

    Args:
        pdf_path: Path to the PDF file.
        output_dir: Directory where PNG files are written.
        dpi: Render resolution (default 200).
        min_drawings: Minimum drawings in a cluster to qualify as a diagram.
        min_region_area: Minimum bbox area (sq pts) to keep a cluster.
        gap: Clustering gap threshold in PDF points.

    Returns:
        List of dicts with keys ``name``, ``page``, ``bbox``, ``path``,
        ``width``, ``height``, ``size``, ``drawings``, ``area``.

    Example::

        results = extract_vector_diagrams("chapter01.pdf", "./diagrams")
        for r in results:
            print(f"Page {r['page']}: {r['name']} ({r['width']}x{r['height']})")
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)

    # Step 1: Detect regions
    all_regions = detect_diagram_regions(
        pdf_path,
        min_drawings=min_drawings,
        min_region_area=min_region_area,
        gap=gap,
    )

    if not all_regions:
        logger.info("No diagram regions detected.")
        return []

    # Step 2: Build region specs for extract_diagram_regions
    region_specs: Dict[int, Dict] = {}
    region_meta: Dict[int, Dict] = {}  # extra metadata per region

    for page_num, regions in all_regions.items():
        for i, region in enumerate(regions):
            suffix = f"_diagram_{i + 1}" if len(regions) > 1 else "_diagram"
            name = f"page_{page_num}{suffix}"

            # If multiple regions on same page, we need separate entries.
            # extract_diagram_regions uses page_num as key, so for multiple
            # regions on the same page we use synthetic keys and build specs
            # manually.
            key = page_num if i == 0 else (page_num, i)
            region_specs[key] = {"bbox": region["bbox"], "name": name}
            region_meta[key] = {
                "drawings": region["drawings"],
                "area": region["area"],
            }

    # Step 3: Render — handle multi-region pages
    output_dir.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    results: List[Dict] = []

    with fitz.open(str(pdf_path)) as doc:
        for key, spec in region_specs.items():
            page_num = key if isinstance(key, int) else key[0]
            page = doc[page_num - 1]
            bbox = spec["bbox"]
            name = spec["name"]
            clip = fitz.Rect(*bbox)

            pix = page.get_pixmap(matrix=matrix, clip=clip)

            filename = f"{name}.png"
            output_path = output_dir / filename
            pix.save(str(output_path))

            meta = region_meta[key]
            logger.info(
                f"Saved {filename} ({pix.width}x{pix.height}px, "
                f"{meta['drawings']} drawings, area={meta['area']})"
            )

            results.append({
                "name": name,
                "page": page_num,
                "bbox": bbox,
                "path": str(output_path),
                "width": pix.width,
                "height": pix.height,
                "size": output_path.stat().st_size,
                "drawings": meta["drawings"],
                "area": meta["area"],
            })

    return results


if __name__ == "__main__":
    # Test the renderer
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python page_renderer.py <pdf_path> <output_dir>")
        sys.exit(1)
    
    pdf_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    
    print(f"Detecting pages with diagrams in: {pdf_path}")
    diagram_pages = detect_pages_with_diagrams(pdf_path)
    print(f"Found {len(diagram_pages)} pages: {diagram_pages}")
    
    print(f"\nRendering to: {output_dir}")
    rendered = render_diagram_pages(pdf_path, output_dir)
    
    print(f"\nRendered {len(rendered)} pages:")
    for img in rendered:
        print(f"  - {img['filename']} ({img['width']}x{img['height']}, {img['size']/1024:.1f} KB)")
