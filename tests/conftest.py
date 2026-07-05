"""Shared test fixtures for pdf-image-extractor tests."""
import pytest
from pathlib import Path

# chapter01.pdf is at the package root
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CHAPTER01_PDF = PACKAGE_ROOT / "chapter01.pdf"


@pytest.fixture
def pdf_path():
    """Path to chapter01.pdf test fixture."""
    if not CHAPTER01_PDF.exists():
        pytest.skip(f"Test PDF not found: {CHAPTER01_PDF}")
    return CHAPTER01_PDF


@pytest.fixture
def tmp_output(tmp_path):
    """Temporary output directory for test renders."""
    out = tmp_path / "output"
    out.mkdir()
    return out


# Known diagram regions with measured bounding boxes (PDF points).
# These exclude header/footer decorative lines and include custom-font text labels.
DIAGRAM_REGIONS = {
    16: {
        "bbox": (133.1, 297.1, 391.3, 427.9),
        "name": "shannon_model",
        "expected_min_width": 700,
        "expected_min_height": 340,
    },
    17: {
        "bbox": (121.6, 437.8, 402.8, 491.0),
        "name": "schramm_model",
        "expected_min_width": 760,
        "expected_min_height": 130,
    },
    22: {
        "bbox": (110.5, 78.0, 413.9, 184.1),
        "name": "lasswell_matrix",
        "expected_min_width": 820,
        "expected_min_height": 280,
    },
}
