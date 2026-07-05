"""Core PDF image extraction logic with smart filtering."""

import base64
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import fitz  # PyMuPDF
from dotenv import load_dotenv

from .config import ImageFilterConfig

logger = logging.getLogger(__name__)


@dataclass
class ExtractedImage:
    """Represents a single extracted image."""
    filename: str
    path: str
    page: int
    width: int
    height: int
    size: int
    format: str
    page_ratio_w: float = 0.0
    page_ratio_h: float = 0.0


@dataclass
class ExtractionResult:
    """Result of PDF image extraction."""
    images: list[ExtractedImage] = field(default_factory=list)
    total_found: int = 0
    kept: int = 0
    filtered: int = 0
    pages_processed: int = 0
    
    def to_dict(self) -> dict:
        return {
            "images": [
                {
                    "filename": img.filename,
                    "path": img.path,
                    "page": img.page,
                    "width": img.width,
                    "height": img.height,
                    "size": img.size,
                    "format": img.format,
                }
                for img in self.images
            ],
            "stats": {
                "total_found": self.total_found,
                "kept": self.kept,
                "filtered": self.filtered,
                "pages_processed": self.pages_processed,
            },
        }


class ImageExtractor:
    """Extract images from PDF files with configurable filtering.
    
    Usage:
        extractor = ImageExtractor()
        result = extractor.extract("document.pdf", output_dir="./images")
        for img in result.images:
            print(f"Page {img.page}: {img.filename} ({img.width}x{img.height})")
    """
    
    def __init__(self, config: Optional[ImageFilterConfig] = None):
        self.config = config or ImageFilterConfig()
    
    def extract(
        self,
        pdf_path: Union[str, Path],
        output_dir: Union[str, Path],
        config: Optional[dict] = None,
    ) -> ExtractionResult:
        """Extract images from a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            output_dir: Directory to save extracted images
            config: Optional dict to override default config settings
            
        Returns:
            ExtractionResult with extracted images and statistics
        """
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        # Apply config overrides if provided
        cfg = self.config.merge(config) if config else self.config
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Open PDF
        with fitz.open(str(pdf_path)) as doc:
            result = ExtractionResult(pages_processed=doc.page_count)
            content_area_cache: dict[int, dict] = {}

            for page_num in range(doc.page_count):
                page = doc[page_num]
                page_rect = page.rect

                # Pre-compute content area for this page (shared across all images)
                if cfg.use_smart_content_detection:
                    if page_num not in content_area_cache:
                        content_area_cache[page_num] = self._detect_content_area(page, page_rect)
                    page_content_area = content_area_cache[page_num]
                else:
                    page_content_area = None

                # Get all images on this page
                image_list = page.get_images(full=True)

                for img_index, img in enumerate(image_list):
                    result.total_found += 1
                    xref = img[0]

                    try:
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        img_width = base_image["width"]
                        img_height = base_image["height"]
                    except Exception as e:
                        logger.debug(f"Failed to extract image xref={xref}: {e}")
                        result.filtered += 1
                        continue

                    # Apply filters
                    if not self._passes_filters(
                        image_bytes, img_width, img_height, image_ext,
                        page, page_rect, xref, cfg, page_content_area
                    ):
                        result.filtered += 1
                        continue

                    # Image passed all filters - save it
                    if cfg.output_format == "original":
                        ext = image_ext
                    elif cfg.output_format == "png":
                        ext = "png"
                        image_bytes = self._convert_image(image_bytes, "PNG")
                    elif cfg.output_format == "jpeg":
                        ext = "jpg"
                        image_bytes = self._convert_image(image_bytes, "JPEG", quality=cfg.jpeg_quality)
                    else:
                        ext = image_ext

                    filename = f"page_{page_num + 1}_img_{img_index + 1}.{ext}"
                    image_path = output_dir / filename

                    with open(image_path, "wb") as img_file:
                        img_file.write(image_bytes)

                    # Calculate page ratios for metadata
                    rects = page.get_image_rects(xref)
                    page_ratio_w = 0.0
                    page_ratio_h = 0.0
                    if rects:
                        rect = rects[0]
                        page_ratio_w = rect.width / page_rect.width if page_rect.width > 0 else 0
                        page_ratio_h = rect.height / page_rect.height if page_rect.height > 0 else 0

                    extracted = ExtractedImage(
                        filename=filename,
                        path=str(image_path),
                        page=page_num + 1,
                        width=img_width,
                        height=img_height,
                        size=len(image_bytes),
                        format=ext,
                        page_ratio_w=page_ratio_w,
                        page_ratio_h=page_ratio_h,
                    )

                    result.images.append(extracted)
                    result.kept += 1
        
        logger.info(
            f"Extraction complete: {result.kept}/{result.total_found} images kept "
            f"from {result.pages_processed} pages"
        )
        
        return result
    

    def _detect_content_area(self, page: fitz.Page, page_rect: fitz.Rect) -> dict:
        """Detect the content area of a page based on text positions.
        
        Returns:
            dict with:
            - content_top: float (y ratio where content starts)
            - content_bottom: float (y ratio where content ends)
            - is_title_page: bool (whether this is a chapter title page)
        """
        # Get text blocks
        blocks = page.get_text("blocks")
        if not blocks:
            return {
                "content_top": 0.05,
                "content_bottom": 0.95,
                "is_title_page": False
            }
        
        # Sort by y position
        sorted_blocks = sorted(blocks, key=lambda b: b[1])
        
        # Filter substantial text, but also filter out running headers
        # Running headers often contain: page numbers + book title
        # Filter out blocks that are too short OR look like headers
        substantial_blocks = []
        for b in sorted_blocks:
            text = b[4].strip()
            
            # Skip very short text
            if len(text) <= 10:
                continue
            
            # Skip running headers (page number + book title patterns)
            # Common patterns: "22 传播学引论（第四版）", "Chapter 1", etc.
            y_ratio = b[1] / page_rect.height
            
            # If text is in top 10% and matches header patterns, skip it
            if y_ratio < 0.10:
                # Check if it looks like a running header
                # Contains number at start + short title-like text
                import re
                if re.match(r'^\d+\s+[\u4e00-\u9fa5]', text):  # Number + Chinese
                    continue
                if re.match(r'^\d+\s+Chapter', text, re.I):  # Number + Chapter
                    continue
                if re.match(r'^Chapter\s+\d+', text, re.I):  # Chapter + number
                    continue
                if re.match(r'^\d+$', text):  # Just a page number
                    continue
            
            substantial_blocks.append(b)
        
        if not substantial_blocks:
            return {
                "content_top": 0.05,
                "content_bottom": 0.95,
                "is_title_page": False
            }
        
        # Find first content text
        first_text_y = substantial_blocks[0][1]
        content_top = first_text_y / page_rect.height
        
        # Apply minimum threshold for non-title pages
        # Images can legitimately be at the very top of a page (2-3%)
        # Only filter images that are clearly in header/footer zones
        # This prevents filtering real content images at page edges
        min_content_top = 0.02  # Very lenient - allow images from 2% onwards
        if content_top < min_content_top:
            content_top = min_content_top
        
        # Find last content text
        last_text_y = substantial_blocks[-1][3]  # y1
        content_bottom = last_text_y / page_rect.height
        
        # Detect if this is a title page (content starts late)
        is_title_page = content_top > 0.15
        
        return {
            "content_top": content_top,
            "content_bottom": content_bottom,
            "is_title_page": is_title_page
        }

    def _passes_filters(
        self,
        image_bytes: bytes,
        width: int,
        height: int,
        ext: str,
        page: fitz.Page,
        page_rect: fitz.Rect,
        xref: int,
        cfg: ImageFilterConfig,
        content_area: Optional[dict] = None,
    ) -> bool:
        """Apply all configured filters to an image. Returns True if image passes."""
        
        # Filter 1: Minimum pixel dimensions
        if width < cfg.min_width or height < cfg.min_height:
            return False
        
        # Filter 2: Minimum file size
        if len(image_bytes) < cfg.min_file_size:
            return False
        
        # Get image position on page
        rects = page.get_image_rects(xref)
        if not rects:
            return False
        
        rect = rects[0]
        
        # Calculate ratios relative to page size
        w_ratio = rect.width / page_rect.width if page_rect.width > 0 else 0
        h_ratio = rect.height / page_rect.height if page_rect.height > 0 else 0
        x_ratio = rect.x0 / page_rect.width if page_rect.width > 0 else 0
        y_ratio = rect.y0 / page_rect.height if page_rect.height > 0 else 0
        
        # Filter 3: Too small relative to page
        if w_ratio < cfg.min_page_ratio_width or h_ratio < cfg.min_page_ratio_height:
            return False
        
        # Filter 4: Too large (likely full-page background)
        if w_ratio > cfg.max_page_ratio_width or h_ratio > cfg.max_page_ratio_height:
            return False
        
        # Filter 5: Smart content area detection (if enabled)
        y_bottom = (rect.y1 / page_rect.height) if page_rect.height > 0 else 0
        x_right = (rect.x1 / page_rect.width) if page_rect.width > 0 else 0
        
        if cfg.use_smart_content_detection:
            # Use pre-computed content area (cached per page)
            if content_area is None:
                content_area = self._detect_content_area(page, page_rect)
            
            # For title pages, use detected content area
            # For regular pages, only filter very specific header/footer zones
            if content_area["is_title_page"]:
                # Title page: use detected content area
                if y_ratio < content_area["content_top"]:
                    logger.debug(f"Image filtered: title page header (y={y_ratio:.2f} < content_top={content_area['content_top']:.2f})")
                    return False
                
                if y_bottom > content_area["content_bottom"]:
                    logger.debug(f"Image filtered: title page footer (y_bottom={y_bottom:.2f} > content_bottom={content_area['content_bottom']:.2f})")
                    return False
            else:
                # Regular page: only filter extreme header/footer zones
                # This allows images at top/bottom of pages (common in textbooks)
                # Images can legitimately extend slightly off page edges (bleed)
                header_zone = 0.01  # Top 1% only (very conservative)
                footer_zone = 0.99  # Bottom 1% only
                left_bleed = -0.05  # Allow 5% bleed off left edge
                right_bleed = 1.05  # Allow 5% bleed off right edge
                
                if y_ratio < header_zone:
                    logger.debug(f"Image filtered: header zone (y={y_ratio:.2f} < {header_zone})")
                    return False
                
                if y_bottom > footer_zone:
                    logger.debug(f"Image filtered: footer zone (y_bottom={y_bottom:.2f} > {footer_zone})")
                    return False
                
                # Allow images with slight bleed off page edges
                if x_ratio < left_bleed:
                    logger.debug(f"Image filtered: left bleed (x={x_ratio:.2f} < {left_bleed})")
                    return False
                
                if x_right > right_bleed:
                    logger.debug(f"Image filtered: right bleed (x_right={x_right:.2f} > {right_bleed})")
                    return False
        else:
            # Use static margin configuration
            if y_ratio < cfg.margin_top:
                return False
            if y_bottom > (1.0 - cfg.margin_bottom):
                return False
        
        # Filter 6: Side margins (only when smart detection is disabled)
        # When smart detection is enabled, side margins are checked in Filter 5
        # with more lenient values that allow for bleed
        if not cfg.use_smart_content_detection:
            if x_ratio < cfg.margin_left:
                return False
            if x_right > (1.0 - cfg.margin_right):
                return False
        
        # Filter 6: Vision model (optional)
        if cfg.use_vision_model and cfg.vision_api_key:
            if not self._check_with_vision(image_bytes, ext, cfg):
                return False
        
        return True
    
    def _check_with_vision(
        self,
        image_bytes: bytes,
        ext: str,
        cfg: ImageFilterConfig,
    ) -> bool:
        """Use a vision model to determine if image is meaningful content.
        
        Supports OpenAI and Dashscope (Qwen3-VL-Plus) providers.
        Both use the OpenAI-compatible SDK with different base_url/model.
        """
        try:
            from openai import OpenAI

            base_url, model = cfg.resolve_vision_settings()

            # Build client with optional custom base_url (for Dashscope)
            client_kwargs = {"api_key": cfg.vision_api_key}
            if base_url:
                client_kwargs["base_url"] = base_url

            client = OpenAI(**client_kwargs)

            # Convert image to base64
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            mime_map = {
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "png": "image/png",
                "bmp": "image/bmp",
                "gif": "image/gif",
                "tiff": "image/tiff",
            }
            media_type = mime_map.get(ext.lower(), f"image/{ext}")

            logger.debug(
                f"Calling vision model: provider={cfg.vision_provider} "
                f"model={model} base_url={base_url or 'default'}"
            )

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an image classifier. Determine if this image is "
                            "meaningful content (chart, diagram, photo, illustration) "
                            "or decorative/ornamental (icon, separator, background pattern, "
                            "border, small logo). Reply with only 'content' or 'decorative'."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{b64_image}",
                                },
                            },
                        ],
                    },
                ],
                max_tokens=10,
                temperature=0,
            )

            answer = response.choices[0].message.content.strip().lower()
            is_content = "content" in answer
            logger.debug(f"Vision model response: '{answer}' -> keep={is_content}")
            return is_content

        except ImportError:
            logger.error(
                "openai package not installed. "
                "Install with: pip install pdf-image-extractor[vision]"
            )
            return True
        except Exception as e:
            logger.warning(f"Vision model check failed (provider={cfg.vision_provider}): {e}")
            return True  # Keep image if vision check fails

    @staticmethod
    def _convert_image(image_bytes: bytes, target_format: str, quality: int = 95) -> bytes:
        """Convert image bytes to the target format using Pillow."""
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO()
        if target_format == "JPEG":
            # JPEG doesn't support alpha; convert RGBA to RGB
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=quality)
        else:
            img.save(buf, format=target_format)
        return buf.getvalue()


def extract_images(
    pdf_path: Union[str, Path],
    output_dir: Union[str, Path],
    config: Optional[dict] = None,
) -> ExtractionResult:
    """Convenience function to extract images from a PDF.
    
    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save extracted images
        config: Optional dict to override default filter settings
        
    Returns:
        ExtractionResult with extracted images and statistics
        
    Example:
        result = extract_images("document.pdf", "./images")
        print(f"Extracted {result.kept} images from {result.pages_processed} pages")
        for img in result.images:
            print(f"  {img.filename} ({img.width}x{img.height})")
    """
    # Load environment variables from .env file
    load_dotenv()
    
    extractor = ImageExtractor()
    return extractor.extract(pdf_path, output_dir, config)
