# Integration Guide: pdf-image-extractor

This guide shows how to integrate the `pdf-image-extractor` package into any Python project.

## Installation

### Option 1: Install from local package (recommended for this project)

```bash
# From your project root
pip install packages/pdf-image-extractor/

# Or add to requirements.txt
echo "pdf-image-extractor==1.0.0" >> requirements.txt
pip install -r requirements.txt
```

### Option 2: Install as editable package (for development)

```bash
pip install -e packages/pdf-image-extractor/
```

### Option 3: Copy to your project

If you want to vendor the package:

```bash
cp -r packages/pdf-image-extractor/pdf_image_extractor your_project/
```

## Basic Usage

### Extract images from any PDF

```python
from pdf_image_extractor import extract_images

# Simple extraction
result = extract_images("document.pdf", "./output_images")

print(f"Extracted {result.kept} images from {result.total_found} found")
for img in result.images:
    print(f"  - {img.filename} ({img.width}x{img.height})")
```

### With custom configuration

```python
from pdf_image_extractor import extract_images

# Extract only large images (suitable for presentations)
result = extract_images(
    "document.pdf",
    "./output",
    config={
        "min_width": 400,
        "min_height": 300,
        "min_page_ratio_width": 0.2,
        "min_page_ratio_height": 0.2,
    }
)
```

### Using the class-based API

```python
from pdf_image_extractor import ImageExtractor, ImageFilterConfig

# Create extractor with custom config
config = ImageFilterConfig(
    min_width=200,
    min_height=200,
    margin_top=0.1,  # Skip top 10% of page
    margin_bottom=0.1,
)

extractor = ImageExtractor(config)
result = extractor.extract("document.pdf", "./output")

# Access detailed results
print(f"Pages processed: {result.pages_processed}")
print(f"Images kept: {result.kept}")
print(f"Images filtered: {result.filtered}")

# Convert to dict for JSON serialization
result_dict = result.to_dict()
```

### With vision model filtering (optional)

Requires OpenAI API key:

```python
from pdf_image_extractor import extract_images
import os

result = extract_images(
    "document.pdf",
    "./output",
    config={
        "use_vision_model": True,
        "vision_api_key": os.getenv("OPENAI_API_KEY"),
        "vision_model": "gpt-4-vision-preview",
        "vision_threshold": 0.7,
    }
)
```

## Integration Example: Django Project

Here's how we integrated it in `apps/parser/services.py`:

```python
from pdf_image_extractor import extract_images
from pathlib import Path

def extract_chapter_content(pdf_path: Path, chapter_id: str) -> dict:
    """Extract text and images from a chapter PDF."""
    from django.conf import settings
    
    # Setup output directory
    images_dir = Path(settings.STORAGE_ROOT) / "images" / chapter_id
    
    # Extract images with smart filtering
    result = extract_images(
        pdf_path,
        images_dir,
        config={
            "min_width": 200,
            "min_height": 150,
            "min_page_ratio_width": 0.1,
            "min_page_ratio_height": 0.1,
            "margin_top": 0.05,
            "margin_bottom": 0.05,
        }
    )
    
    return {
        "images": [img.filename for img in result.images],
        "total_images": result.total_found,
        "filtered_count": result.filtered,
        "passed_count": result.kept,
    }
```

## Configuration Reference

### ImageFilterConfig Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_width` | int | 150 | Minimum width in pixels |
| `min_height` | int | 150 | Minimum height in pixels |
| `min_file_size` | int | 1024 | Minimum file size in bytes |
| `min_page_ratio_width` | float | 0.05 | Min width as % of page width (0.0-1.0) |
| `min_page_ratio_height` | float | 0.05 | Min height as % of page height (0.0-1.0) |
| `max_page_ratio_width` | float | 0.95 | Max width as % of page width (0.0-1.0) |
| `max_page_ratio_height` | float | 0.95 | Max height as % of page height (0.0-1.0) |
| `margin_top` | float | 0.05 | Skip top margin (0.0-1.0) |
| `margin_bottom` | float | 0.05 | Skip bottom margin (0.0-1.0) |
| `margin_left` | float | 0.05 | Skip left margin (0.0-1.0) |
| `margin_right` | float | 0.05 | Skip right margin (0.0-1.0) |
| `use_vision_model` | bool | False | Enable vision model filtering |
| `vision_api_key` | str | "" | OpenAI API key (if using vision model) |
| `vision_model` | str | "gpt-4-vision-preview" | Vision model name |
| `vision_threshold` | float | 0.7 | Confidence threshold (0.0-1.0) |

### Result Object

```python
ExtractionResult:
    - images: List[ExtractedImage]
    - pages_processed: int
    - total_found: int
    - kept: int
    - filtered: int
    - to_dict() -> dict

ExtractedImage:
    - filename: str
    - path: str
    - page: int
    - width: int
    - height: int
    - size: int
    - format: str
    - page_ratio_w: float
    - page_ratio_h: float
```

## CLI Usage

```bash
# Basic extraction
pdf-image-extract document.pdf ./output

# With custom filters
pdf-image-extract document.pdf ./output \
    --min-width 200 \
    --min-height 150 \
    --min-ratio 0.1 \
    --margin-top 0.05 \
    --margin-bottom 0.05

# Output as JSON
pdf-image-extract document.pdf ./output --json
```

## Testing Your Integration

```python
from pdf_image_extractor import extract_images
from pathlib import Path

# Test with a sample PDF
test_pdf = Path("path/to/test.pdf")
output_dir = Path("./test_output")

result = extract_images(test_pdf, output_dir)

print(f"Test Results:")
print(f"  Pages: {result.pages_processed}")
print(f"  Found: {result.total_found}")
print(f"  Kept: {result.kept}")
print(f"  Filtered: {result.filtered}")

# Verify output files
for img in result.images:
    img_path = Path(img.path)
    assert img_path.exists(), f"Missing: {img_path}"
    assert img_path.stat().st_size > 0, f"Empty: {img_path}"

print("✓ All tests passed")
```

## Common Use Cases

### 1. Extract images for presentations
```python
# Large, high-quality images only
result = extract_images(pdf, output, config={
    "min_width": 800,
    "min_height": 600,
    "min_page_ratio_width": 0.3,
    "min_page_ratio_height": 0.3,
})
```

### 2. Extract all content images
```python
# Relaxed filtering, keep most images
result = extract_images(pdf, output, config={
    "min_width": 100,
    "min_height": 100,
    "min_page_ratio_width": 0.02,
    "min_page_ratio_height": 0.02,
})
```

### 3. Extract images from specific page regions
```python
# Skip headers/footers, focus on content area
result = extract_images(pdf, output, config={
    "margin_top": 0.1,    # Skip top 10%
    "margin_bottom": 0.1, # Skip bottom 10%
    "margin_left": 0.05,
    "margin_right": 0.05,
})
```

### 4. Batch processing multiple PDFs
```python
from pathlib import Path
from pdf_image_extractor import extract_images

pdf_dir = Path("./pdfs")
output_base = Path("./outputs")

for pdf_file in pdf_dir.glob("*.pdf"):
    output_dir = output_base / pdf_file.stem
    result = extract_images(pdf_file, output_dir)
    print(f"{pdf_file.name}: {result.kept}/{result.total_found} images")
```

## Troubleshooting

### No images extracted
- Check if PDF actually contains images
- Try relaxing filters: `min_width=50, min_height=50`
- Check if images are in margins (increase margin values)

### Too many small images
- Increase `min_width` and `min_height`
- Increase `min_page_ratio_width` and `min_page_ratio_height`
- Enable vision model filtering

### Vision model not working
- Verify OpenAI API key is set
- Check API quota/limits
- Try different model: `gpt-4o-mini` (faster, cheaper)

## Support

For issues or questions:
1. Check the README.md in `packages/pdf-image-extractor/`
2. Review test cases in `packages/pdf-image-extractor/test_integration.py`
3. See implementation in `pdf_image_extractor/extractor.py`
