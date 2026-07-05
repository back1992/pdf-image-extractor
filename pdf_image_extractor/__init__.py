"""PDF Image Extractor - Extract images from PDF files with smart filtering."""

from .extractor import ImageExtractor, extract_images, ExtractedImage, ExtractionResult
from .config import ImageFilterConfig
from .page_renderer import (
    render_page_as_image,
    detect_pages_with_diagrams,
    render_diagram_pages,
    extract_diagram_regions,
    auto_detect_diagram_bbox,
    detect_diagram_regions,
    extract_vector_diagrams,
)

__version__ = "1.1.0"
__all__ = [
    "ImageExtractor",
    "extract_images",
    "ExtractedImage",
    "ExtractionResult",
    "ImageFilterConfig",
    "render_page_as_image",
    "detect_pages_with_diagrams",
    "render_diagram_pages",
    "extract_diagram_regions",
    "auto_detect_diagram_bbox",
    "detect_diagram_regions",
    "extract_vector_diagrams",
]
