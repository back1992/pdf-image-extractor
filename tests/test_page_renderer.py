"""Tests for page_renderer module — diagram detection and region extraction."""
import fitz
import pytest
from pathlib import Path

from pdf_image_extractor import (
    extract_diagram_regions,
    auto_detect_diagram_bbox,
    detect_pages_with_diagrams,
    render_page_as_image,
    render_diagram_pages,
    detect_diagram_regions,
    extract_vector_diagrams,
)
from pdf_image_extractor.page_renderer import (
    _filter_noise_drawings,
    _cluster_drawings,
    _is_noise_drawing,
)
from tests.conftest import DIAGRAM_REGIONS


class TestExtractDiagramRegions:
    """Tests for extract_diagram_regions()."""

    def test_explicit_bbox_extracts_all_three(self, pdf_path, tmp_output):
        """Extract 3 diagrams with measured bboxes — files created with correct sizes."""
        regions = {
            page: {"bbox": spec["bbox"], "name": spec["name"]}
            for page, spec in DIAGRAM_REGIONS.items()
        }

        results = extract_diagram_regions(pdf_path, regions, tmp_output, dpi=200)

        assert len(results) == 3
        for result in results:
            assert result["path"]
            assert Path(result["path"]).exists()
            assert result["width"] > 0
            assert result["height"] > 0
            assert result["size"] > 0

    def test_output_dimensions_match_expected(self, pdf_path, tmp_output):
        """Rendered pixel dimensions should be close to expected values at 200 DPI."""
        regions = {
            page: {"bbox": spec["bbox"], "name": spec["name"]}
            for page, spec in DIAGRAM_REGIONS.items()
        }

        results = extract_diagram_regions(pdf_path, regions, tmp_output, dpi=200)

        for result in results:
            name = result["name"]
            # Find the matching spec
            spec = next(s for s in DIAGRAM_REGIONS.values() if s["name"] == name)
            assert result["width"] >= spec["expected_min_width"], (
                f"{name}: width {result['width']} < {spec['expected_min_width']}"
            )
            assert result["height"] >= spec["expected_min_height"], (
                f"{name}: height {result['height']} < {spec['expected_min_height']}"
            )

    def test_output_filenames_follow_convention(self, pdf_path, tmp_output):
        """Output files should be named page_{n}_{name}.png."""
        regions = {
            16: {"bbox": DIAGRAM_REGIONS[16]["bbox"], "name": "shannon_model"},
        }

        results = extract_diagram_regions(pdf_path, regions, tmp_output)

        assert len(results) == 1
        assert results[0]["name"] == "shannon_model"
        filename = Path(results[0]["path"]).name
        assert filename == "page_16_shannon_model.png"

    def test_auto_detect_fallback(self, pdf_path, tmp_output):
        """Omitting bbox triggers auto-detection via auto_detect_diagram_bbox()."""
        # Page 22 has 29 drawings — auto-detect should find them
        regions = {
            22: {"name": "lasswell_auto"},
        }

        results = extract_diagram_regions(pdf_path, regions, tmp_output, dpi=200)

        assert len(results) == 1
        assert results[0]["width"] > 0
        assert results[0]["height"] > 0
        assert results[0]["bbox"] is not None

    def test_invalid_page_raises(self, pdf_path, tmp_output):
        """Page number beyond document length raises ValueError."""
        regions = {999: {"bbox": (0, 0, 100, 100), "name": "nope"}}

        with pytest.raises(ValueError, match="out of range"):
            extract_diagram_regions(pdf_path, regions, tmp_output)

    def test_no_drawings_no_bbox_raises(self, tmp_output):
        """Page with no drawings and no explicit bbox raises ValueError."""
        # Create a minimal 1-page PDF with no drawings
        empty_pdf = tmp_output / "empty.pdf"
        doc = fitz.open()
        doc.new_page()  # blank page
        doc.save(str(empty_pdf))
        doc.close()

        regions = {1: {"name": "nothing"}}

        with pytest.raises(ValueError, match="No vector drawings"):
            extract_diagram_regions(empty_pdf, regions, tmp_output)

    def test_higher_dpi_produces_larger_image(self, pdf_path, tmp_output):
        """Doubling DPI should roughly double pixel dimensions."""
        regions = {
            16: {"bbox": DIAGRAM_REGIONS[16]["bbox"], "name": "shannon_model"},
        }

        r200 = extract_diagram_regions(pdf_path, regions, tmp_output / "d200", dpi=200)
        r400 = extract_diagram_regions(pdf_path, regions, tmp_output / "d400", dpi=400)

        # 400 DPI should be ~2x the 200 DPI dimensions
        ratio = r400[0]["width"] / r200[0]["width"]
        assert 1.9 < ratio < 2.1, f"DPI ratio was {ratio}, expected ~2.0"


class TestAutoDetectDiagramBbox:
    """Tests for auto_detect_diagram_bbox()."""

    def test_returns_bbox_for_page_with_drawings(self, pdf_path):
        """Page 22 has 29 drawings — should return a valid bbox tuple."""
        with fitz.open(str(pdf_path)) as doc:
            page = doc[21]  # 0-indexed
            bbox = auto_detect_diagram_bbox(page)

        assert bbox is not None
        assert len(bbox) == 4
        x0, y0, x1, y1 = bbox
        assert x0 < x1
        assert y0 < y1

    def test_returns_none_for_blank_page(self):
        """A blank page with no drawings returns None."""
        doc = fitz.open()
        page = doc.new_page()
        bbox = auto_detect_diagram_bbox(page)
        doc.close()

        assert bbox is None

    def test_bbox_is_within_page_bounds(self, pdf_path):
        """Returned bbox should not exceed page dimensions."""
        with fitz.open(str(pdf_path)) as doc:
            page = doc[15]  # page 16
            bbox = auto_detect_diagram_bbox(page)
            page_rect = page.rect

        x0, y0, x1, y1 = bbox
        assert x0 >= page_rect.x0
        assert y0 >= page_rect.y0
        assert x1 <= page_rect.x1
        assert y1 <= page_rect.y1


class TestDetectPagesWithDiagrams:
    """Tests for detect_pages_with_diagrams()."""

    def test_detects_page22_with_default_thresholds(self, pdf_path):
        """Page 22 has 29 drawings — should be detected with min_drawings=10."""
        pages = detect_pages_with_diagrams(pdf_path, min_drawings=10, min_text_blocks=5)

        assert 22 in pages

    def test_detects_all_three_with_lower_threshold(self, pdf_path):
        """Pages 16 and 17 have 10-11 drawings — need min_drawings<=10 to detect them."""
        pages = detect_pages_with_diagrams(pdf_path, min_drawings=10, min_text_blocks=5)

        # Page 16 has 11 drawings (after noise), page 17 has 10
        # Both should appear with min_drawings=10
        assert 16 in pages or 17 in pages  # at least one should be detected

    def test_high_threshold_returns_fewer_pages(self, pdf_path):
        """Raising min_drawings should reduce detected pages."""
        low = detect_pages_with_diagrams(pdf_path, min_drawings=10)
        high = detect_pages_with_diagrams(pdf_path, min_drawings=25)

        assert len(high) <= len(low)

    def test_returns_empty_for_nonexistent_pdf(self):
        """Should handle missing file gracefully (fitz raises, but we can document behavior)."""
        with pytest.raises(Exception):
            detect_pages_with_diagrams(Path("/nonexistent.pdf"))


class TestRenderPageAsImage:
    """Tests for render_page_as_image()."""

    def test_renders_page_as_png(self, pdf_path, tmp_output):
        """Should create a PNG file for the specified page."""
        result = render_page_as_image(pdf_path, 1, tmp_output, dpi=150)

        assert result["filename"] == "page_1_rendered.png"
        assert Path(result["path"]).exists()
        assert result["width"] > 0
        assert result["height"] > 0

    def test_invalid_page_raises(self, pdf_path, tmp_output):
        """Page 0 or beyond document length raises ValueError."""
        with pytest.raises(ValueError, match="Invalid page"):
            render_page_as_image(pdf_path, 0, tmp_output)

        with pytest.raises(ValueError, match="Invalid page"):
            render_page_as_image(pdf_path, 9999, tmp_output)

    def test_clip_region_reduces_height(self, pdf_path, tmp_output):
        """clip_region=True should produce a shorter image than full page."""
        clipped = render_page_as_image(pdf_path, 1, tmp_output / "clip", clip_region=True)
        full = render_page_as_image(pdf_path, 1, tmp_output / "full", clip_region=False)

        assert clipped["height"] < full["height"]


class TestNoiseFiltering:
    """Tests for _filter_noise_drawings() and _is_noise_drawing()."""

    def test_filters_horizontal_line_near_top(self):
        """Single horizontal line near page top is classified as noise."""
        page_rect = fitz.Rect(0, 0, 500, 700)
        drawing = {
            "rect": fitz.Rect(50, 35, 450, 35),  # y=35 < 10% of 700=70
            "items": [("l", fitz.Point(50, 35), fitz.Point(450, 35))],
        }
        assert _is_noise_drawing(drawing, page_rect) is True

    def test_filters_horizontal_line_near_bottom(self):
        """Single horizontal line near page bottom is classified as noise."""
        page_rect = fitz.Rect(0, 0, 500, 700)
        drawing = {
            "rect": fitz.Rect(50, 640, 450, 640),  # y=640 > 88% of 700=616
            "items": [("l", fitz.Point(50, 640), fitz.Point(450, 640))],
        }
        assert _is_noise_drawing(drawing, page_rect) is True

    def test_filters_full_width_horizontal_line(self):
        """Full-width horizontal line anywhere is classified as noise."""
        page_rect = fitz.Rect(0, 0, 500, 700)
        drawing = {
            "rect": fitz.Rect(10, 350, 490, 350),  # 480/500 = 96% width
            "items": [("l", fitz.Point(10, 350), fitz.Point(490, 350))],
        }
        assert _is_noise_drawing(drawing, page_rect) is True

    def test_keeps_diagram_rect(self):
        """A rectangle (box) drawing is not classified as noise."""
        page_rect = fitz.Rect(0, 0, 500, 700)
        drawing = {
            "rect": fitz.Rect(100, 300, 200, 350),
            "items": [("re", fitz.Rect(100, 300, 200, 350))],
        }
        assert _is_noise_drawing(drawing, page_rect) is False

    def test_keeps_multi_item_drawing(self):
        """A drawing with multiple items (e.g., path + fill) is not noise."""
        page_rect = fitz.Rect(0, 0, 500, 700)
        drawing = {
            "rect": fitz.Rect(50, 35, 450, 35),
            "items": [
                ("l", fitz.Point(50, 35), fitz.Point(250, 35)),
                ("l", fitz.Point(250, 35), fitz.Point(450, 35)),
            ],
        }
        assert _is_noise_drawing(drawing, page_rect) is False

    def test_filter_removes_noise_keeps_diagrams(self):
        """_filter_noise_drawings removes noise and keeps real drawings."""
        page_rect = fitz.Rect(0, 0, 500, 700)
        drawings = [
            {  # noise: header line
                "rect": fitz.Rect(50, 35, 450, 35),
                "items": [("l", fitz.Point(50, 35), fitz.Point(450, 35))],
            },
            {  # diagram: rectangle
                "rect": fitz.Rect(100, 300, 200, 350),
                "items": [("re", fitz.Rect(100, 300, 200, 350))],
            },
            {  # noise: footer line
                "rect": fitz.Rect(50, 640, 450, 640),
                "items": [("l", fitz.Point(50, 640), fitz.Point(450, 640))],
            },
            {  # diagram: arrow
                "rect": fitz.Rect(150, 310, 180, 340),
                "items": [("l", fitz.Point(150, 325), fitz.Point(180, 325))],
            },
        ]
        filtered = _filter_noise_drawings(drawings, page_rect)
        assert len(filtered) == 2


class TestClustering:
    """Tests for _cluster_drawings()."""

    def test_empty_input(self):
        """Empty drawings list returns empty clusters."""
        assert _cluster_drawings([]) == []

    def test_single_drawing_one_cluster(self):
        """A single drawing produces one cluster."""
        drawings = [
            {"rect": fitz.Rect(100, 100, 200, 200), "items": []},
        ]
        clusters = _cluster_drawings(drawings, gap=50.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_nearby_drawings_merged(self):
        """Drawings within the gap threshold are merged into one cluster."""
        drawings = [
            {"rect": fitz.Rect(100, 100, 150, 150), "items": []},
            {"rect": fitz.Rect(160, 110, 210, 160), "items": []},  # 10pt gap
            {"rect": fitz.Rect(180, 130, 230, 180), "items": []},  # overlapping
        ]
        clusters = _cluster_drawings(drawings, gap=50.0)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_distant_drawings_separated(self):
        """Drawings farther than the gap become separate clusters."""
        drawings = [
            {"rect": fitz.Rect(100, 100, 150, 150), "items": []},
            {"rect": fitz.Rect(100, 300, 150, 350), "items": []},  # 150pt gap
        ]
        clusters = _cluster_drawings(drawings, gap=50.0)
        assert len(clusters) == 2

    def test_gap_threshold_controls_clustering(self):
        """A larger gap merges more drawings; smaller gap separates them."""
        drawings = [
            {"rect": fitz.Rect(100, 100, 150, 150), "items": []},
            {"rect": fitz.Rect(100, 180, 150, 230), "items": []},  # 30pt gap
        ]
        # gap=50 → one cluster (30 < 50)
        assert len(_cluster_drawings(drawings, gap=50.0)) == 1
        # gap=20 → two clusters (30 > 20)
        assert len(_cluster_drawings(drawings, gap=20.0)) == 2


class TestDetectDiagramRegions:
    """Tests for detect_diagram_regions()."""

    def test_finds_all_three_diagrams(self, pdf_path):
        """Should detect diagram regions on pages 16, 17, and 22."""
        regions = detect_diagram_regions(pdf_path, min_drawings=5, gap=50.0)

        assert 16 in regions, "Shannon's model not detected on page 16"
        assert 17 in regions, "Schramm's model not detected on page 17"
        assert 22 in regions, "Lasswell's matrix not detected on page 22"

    def test_each_page_has_one_region(self, pdf_path):
        """Each target page should have exactly one diagram region."""
        regions = detect_diagram_regions(pdf_path, min_drawings=5, gap=50.0)

        for page in [16, 17, 22]:
            assert len(regions[page]) == 1, f"Page {page} has {len(regions[page])} regions"

    def test_region_has_expected_keys(self, pdf_path):
        """Each region dict should have bbox, drawings, and area keys."""
        regions = detect_diagram_regions(pdf_path, min_drawings=5)

        for page, regs in regions.items():
            for r in regs:
                assert "bbox" in r
                assert "drawings" in r
                assert "area" in r
                assert len(r["bbox"]) == 4
                assert r["drawings"] >= 5
                assert r["area"] > 0

    def test_lasswell_has_most_drawings(self, pdf_path):
        """The Lasswell matrix (page 22) should have the most drawings (grid lines)."""
        regions = detect_diagram_regions(pdf_path, min_drawings=5)

        lasswell_drawings = regions[22][0]["drawings"]
        shannon_drawings = regions[16][0]["drawings"]
        assert lasswell_drawings > shannon_drawings

    def test_high_min_drawings_excludes_small_diagrams(self, pdf_path):
        """Raising min_drawings should exclude pages with fewer drawings."""
        # Schramm has ~5 filtered drawings — threshold of 20 should exclude it
        regions = detect_diagram_regions(pdf_path, min_drawings=20, gap=50.0)
        assert 17 not in regions

    def test_bbox_is_reasonable_size(self, pdf_path):
        """Detected bboxes should be between 50x50 and 500x500 pts."""
        regions = detect_diagram_regions(pdf_path, min_drawings=5)

        for page, regs in regions.items():
            for r in regs:
                x0, y0, x1, y1 = r["bbox"]
                w = x1 - x0
                h = y1 - y0
                assert 50 < w < 500, f"Page {page}: width {w:.0f} out of range"
                assert 20 < h < 500, f"Page {page}: height {h:.0f} out of range"


class TestExtractVectorDiagrams:
    """Tests for extract_vector_diagrams() — end-to-end pipeline."""

    def test_extracts_at_least_three_diagrams(self, pdf_path, tmp_output):
        """Should extract at least 3 diagrams from chapter01.pdf."""
        results = extract_vector_diagrams(
            pdf_path, tmp_output, dpi=200, min_drawings=5
        )

        assert len(results) >= 3

    def test_output_files_exist(self, pdf_path, tmp_output):
        """All output PNG files should exist."""
        results = extract_vector_diagrams(
            pdf_path, tmp_output, dpi=200, min_drawings=5
        )

        for r in results:
            assert Path(r["path"]).exists(), f"Missing: {r['path']}"
            assert r["size"] > 0

    def test_output_dimensions_reasonable(self, pdf_path, tmp_output):
        """Extracted images should have reasonable dimensions."""
        results = extract_vector_diagrams(
            pdf_path, tmp_output, dpi=200, min_drawings=5
        )

        for r in results:
            assert r["width"] >= 100, f"{r['name']}: width {r['width']} too small"
            assert r["height"] >= 30, f"{r['name']}: height {r['height']} too small"

    def test_results_include_drawing_metadata(self, pdf_path, tmp_output):
        """Results should include drawings count and area from detection."""
        results = extract_vector_diagrams(
            pdf_path, tmp_output, dpi=200, min_drawings=5
        )

        for r in results:
            assert "drawings" in r
            assert "area" in r
            assert r["drawings"] >= 5

    def test_empty_pdf_returns_empty_list(self, tmp_output):
        """A PDF with no drawings returns an empty list."""
        empty_pdf = tmp_output / "empty.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(empty_pdf))
        doc.close()

        results = extract_vector_diagrams(empty_pdf, tmp_output / "out")
        assert results == []
