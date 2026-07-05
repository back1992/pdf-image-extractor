# Target: Extract Vector Diagrams from Academic PDF

**Date:** 2026-07-02  
**Status:** Phase 1 complete ✅, Phase 2 pending  
**Scope:** Extend `pdf-image-extractor` to handle vector-based diagrams (flowcharts, matrices) that are drawn using PDF primitives, not embedded as raster images.

---

## Goal

Extract **3 specific vector diagrams** from `chapter01.pdf` as standalone, cropped PNG images:

1. **Shannon's Communication Model** (PDF page 16, book page 17)  
   - Linear flowchart: `[信源] → [传送者] → [信号] → [接收者] → [信宿]`
   - Includes noise source arrow pointing up to the signal line

2. **Schramm's Communication Model** (PDF page 17, book page 18)  
   - Simplified linear model: `[信源] → [编码] → [信号] → [译码] → [目的地]`

3. **Lasswell's 5W Model Matrix** (PDF page 22, book page 23)  
   - 5×4 matrix grid showing: Who/Says what/In which channel/To whom/With what effect
   - Four rows: English labels, Chinese translations, communication elements, research disciplines

All three diagrams are **vector graphics** (boxes, arrows, text) drawn using PDF path and text operators, not embedded raster images. **Important:** diagram labels use a custom embedded font, so text extraction returns garbled Unicode (see [Custom Font Encoding](#custom-font-encoding) below).

---

## Current Status

### What's implemented (Phase 1)

| Component | Location | Notes |
|---|---|---|
| `extract_diagram_regions()` | `page_renderer.py:213` | Renders named page regions by bbox, with auto-detect fallback |
| `auto_detect_diagram_bbox()` | `page_renderer.py:178` | Merges all drawing rects on a page into one bbox |
| `detect_pages_with_diagrams()` | `page_renderer.py:80` | Coarse heuristic based on drawing/text block counts |
| `render_diagram_pages()` | `page_renderer.py:141` | Convenience wrapper: detect + render |
| `render_page_as_image()` | `page_renderer.py:12` | Full-page or clipped render |
| CLI `pdf-image-extract-diagrams` | `cli.py:diagrams_main()` | `--pages`, `--region`, `--dpi`, `--json` |
| Public API exports | `__init__.py` | All 5 functions above are exported |

### What's not done

- **Auto-detection needs work.** `auto_detect_diagram_bbox()` merges ALL drawings on a page (including header/footer rules), producing oversized bboxes. No spatial clustering or noise filtering.
- **Default threshold mismatch.** `render_diagram_pages()` uses `min_drawings=15` but page 17 (Schramm) has only 10 drawings.

---

## Current Gap (Original)

The existing `extract_images()` function uses `page.get_images()` which only returns **embedded raster images** (JPEG, PNG bitmaps stored in the PDF). It will never find these diagrams because:

- They are constructed from PDF drawing primitives (paths, rectangles, text objects)
- `page.get_images()` returns an empty list for pages with only vector content
- The current filtering pipeline (size, ratio, margins, vision model) is irrelevant here

The library has `page_renderer.py` with `render_page_as_image()` and `detect_pages_with_diagrams()`, but:

- It renders **entire pages** (or clips top/bottom 10%), not diagram-specific regions
- Detection heuristics (`min_drawings=10`, `min_text_blocks=5`) are arbitrary and may not match these diagrams
- ~~There's no API to specify which pages or regions to extract~~ **(Resolved: `extract_diagram_regions()` now exists)**
- Rendered images include surrounding text, headers, footers

---

## Requirements

### Functional Requirements

1. **Region-based rendering:** Crop to the bounding box of the diagram, not the full page.
2. **Diagram detection:** Automatically identify diagram regions on pages 16, 17, and 22 of `chapter01.pdf`.
3. **Output format:** Save each diagram as a standalone PNG file with transparent or white background.
4. **Quality:** Render at 200+ DPI for readability of small text labels.
5. **API:** Provide a way to extract these 3 diagrams either by:
   - Specifying page numbers and letting the tool auto-detect regions
   - Manually specifying bounding boxes (for precision)

### Non-Functional Requirements

- **Performance:** Extraction should complete in <5 seconds for the 3 pages.
- **Accuracy:** Cropped regions should include all diagram elements with minimal surrounding whitespace.
- **Reusability:** The approach should generalize to similar vector diagrams in other academic PDFs.

---

## PDF Analysis Findings

### Page-level data

| Diagram | PDF Page | Book Page | Drawings | Drawing bbox (PDF pts) | Text blocks | Embedded images |
|---|---|---|---|---|---|---|
| Shannon's model | 16 | 17 | 11 | (62.4, 65.6, 392.8, 591.1)* | 29 | 1 |
| Schramm's model | 17 | 18 | 10 | (62.4, 65.6, 462.0, 579.1)* | 30 | 1 |
| Lasswell's matrix | 22 | 23 | 29 | (62.4, 65.6, 179.2, 65.6)* | 31 | 1 |

\* Auto-detected bbox from `auto_detect_diagram_bbox()` — **unreliable** because it merges ALL drawings on the page including header/footer decorative lines.

### Custom Font Encoding

**Critical discovery:** All three diagrams use a custom embedded font for their text labels. PyMuPDF's text extraction returns garbled Unicode characters (e.g., `ԍ⎼㑂ⴭԍण䃽ⴭⰚ⮰`) instead of readable Chinese text.

**Implications:**
- Text-based detection heuristics (looking for keywords like "信源", "编码") will not work
- OCR or vision model analysis is needed to verify label content
- The diagrams ARE vector-drawn (boxes, arrows, lines via `get_drawings()`), but the text within them is encoded with a non-standard CMap
- This is common in Chinese academic PDFs where publishers embed custom subset fonts

### Auto-detection problems

1. **Drawing bbox is too coarse.** The merged bbox spans nearly the full page for pages 16 and 17 because header/footer decorative lines are included as "drawings." Page 22's bbox collapses to a single line (y=65.6) because the matrix grid lines are drawn as many small line segments that merge into a thin strip.

2. **Every page has 1 embedded image.** The `detect_pages_with_diagrams()` check `large_images == 0` may filter out target pages if the embedded image exceeds 5% of page area.

3. **Drawing count thresholds are misaligned:**
   - Page 16 (Shannon): 11 drawings — passes `min_drawings=10` but fails `min_drawings=15`
   - Page 17 (Schramm): 10 drawings — passes `min_drawings=10` but fails `min_drawings=15`
   - Page 22 (Lasswell): 29 drawings — passes both thresholds

### Existing test fixtures

The `diagrams_test/` directory contains outputs from manual extraction attempts:

| File | Size | Dimensions | Assessment |
|---|---|---|---|
| `shannon_p16.png` | 12.0 KB | 718×290px | Likely correct crop (manual bbox) |
| `schramm_p17.png` | 4.5 KB | 782×101px | Suspiciously small — may be too tight |
| `lasswell_p22.png` | 31.5 KB | 845×296px | Likely correct crop (manual bbox) |
| `page_17_shannon_model.png` | 370 KB | 974×1516px | Full-page auto-detect render — too large |
| `page_18_schramm_model.png` | 453 KB | 1167×1483px | Full-page auto-detect render — too large |
| `page_23_lasswell_matrix.png` | 5.2 KB | 381×56px | Auto-detect caught only a single line — wrong |

---

## Success Criteria

After implementation, the following files should exist and meet quality standards:

```
output/diagrams/
├── page_16_shannon_model.png       # 718x364px, 14.7 KB, clean flowchart
├── page_17_schramm_model.png       # 782x148px, 9.6 KB, simple linear model
└── page_22_lasswell_matrix.png     # 844x296px, 31.5 KB, 5x4 matrix grid
```

**Visual inspection checklist:**
- [ ] All boxes and arrows are fully visible
- [ ] Text labels are legible (Chinese characters render correctly despite custom font — they render fine as pixels, just can't be extracted as text)
- [ ] No header/footer text from the page
- [ ] Minimal whitespace padding around the diagram
- [ ] Lines and shapes are crisp (not pixelized)

---

## Technical Approach

### Option A: Manual Bounding Boxes (Quick Win) — ✅ DONE

Hardcode the bounding boxes for the 3 diagrams based on PyMuPDF drawing rect analysis:

```python
diagram_regions = {
    16: {"bbox": (133.1, 297.1, 391.3, 427.9), "name": "shannon_model"},
    17: {"bbox": (121.6, 437.8, 402.8, 491.0), "name": "schramm_model"},
    22: {"bbox": (110.5, 78.0, 413.9, 184.1), "name": "lasswell_matrix"},
}
```

**Pros:** Fast, precise, guaranteed to work for these 3 diagrams.  
**Cons:** Not generalizable; requires manual measurement for each new PDF.

**Status:** ✅ Complete. Extraction script at `extract_chapter01_diagrams.py`, 17 unit tests passing.

### Option B: Auto-Detection via Drawing Density (Generalizable) — NOT DONE

Extend `detect_pages_with_diagrams()` to:
1. Filter out header/footer decorative lines (typically single horizontal lines near page edges)
2. Cluster remaining drawings spatially to isolate diagram regions
3. Filter out text-heavy regions (paragraphs) vs. diagram regions (sparse text + many shapes)
4. Handle pages where drawings include small line segments that form grids (Lasswell matrix)
5. Render only the diagram bounding box

**Pros:** Works for any PDF with similar vector diagrams.  
**Cons:** Complex; the custom font encoding prevents text-based heuristics; may require tuning; could fail on edge cases.

**Key challenge:** The current `auto_detect_diagram_bbox()` is too naive — it merges everything. A clustering approach (e.g., DBSCAN on drawing centroids, or connected-component analysis on drawing rects) would be needed.

### Option C: Hybrid (Recommended) — IN PROGRESS

1. **Short-term:** Use Option A to deliver the 3 target diagrams immediately. ✅ Function exists, needs bbox measurement.
2. **Long-term:** Implement Option B as a general feature, validated against these 3 diagrams as test cases.

---

## Implementation Plan (Hybrid Approach)

### Phase 1: Manual Extraction ✅ DONE

1. ~~Open `chapter01.pdf` in a PDF viewer or use PyMuPDF to inspect page coordinates~~
2. ~~Add a new function `extract_diagram_regions()` in `page_renderer.py`~~ (exists at line 213)
3. ~~Create a CLI command `pdf-image-extract-diagrams`~~ (exists in `cli.py`)
4. ✅ Measured accurate bounding boxes using PyMuPDF drawing rect analysis + custom-font text block detection, with header/footer noise filtering
5. ✅ Created `extract_chapter01_diagrams.py` — calls `extract_diagram_regions()` with measured bboxes
6. ✅ Verified output images: Shannon 718×364px (14.7 KB), Schramm 782×148px (9.6 KB), Lasswell 844×296px (31.5 KB)
7. ✅ Wrote 17 unit tests in `tests/test_page_renderer.py` — all passing

### Phase 2: Auto-Detection (Future Work)

1. Implement header/footer line filtering in `auto_detect_diagram_bbox()`:
   - Discard single horizontal lines within 10% of page top/bottom edges
2. Implement spatial clustering of drawing rects:
   - Group drawings by proximity (e.g., gap > 50pt = separate cluster)
   - Return multiple bbox candidates per page
3. Handle grid-like structures (many small line segments forming a matrix)
4. Replace hardcoded regions with auto-detected ones
5. Add test cases using the 3 diagrams as ground truth

---

## API Design

### Existing Function: `extract_diagram_regions()`

```python
from pathlib import Path
from pdf_image_extractor import extract_diagram_regions

regions = {
    16: {"bbox": (133.1, 297.1, 391.3, 427.9), "name": "shannon_model"},
    17: {"bbox": (121.6, 437.8, 402.8, 491.0), "name": "schramm_model"},
    22: {"bbox": (110.5, 78.0, 413.9, 184.1), "name": "lasswell_matrix"},
}

results = extract_diagram_regions(
    pdf_path="chapter01.pdf",
    regions=regions,
    output_dir="./diagrams",
    dpi=200
)

for r in results:
    print(f"{r['name']}: {r['path']} ({r['width']}x{r['height']})")
```

### CLI (already implemented)

```bash
# Manual bbox per region
pdf-image-extract-diagrams chapter01.pdf ./diagrams \
  --region 16:133.1,297.1,391.3,427.9:shannon_model \
  --region 17:121.6,437.8,402.8,491.0:schramm_model \
  --region 22:110.5,78.0,413.9,184.1:lasswell_matrix \
  --dpi 200

# Auto-detect bbox on specified pages
pdf-image-extract-diagrams chapter01.pdf ./diagrams --pages 16,17,22 --dpi 200
```

---

## Testing Strategy

### Immediate (for Phase 1) — ✅ DONE

Tests in `tests/test_page_renderer.py` (17 tests, all passing):

1. **Visual verification:** Compared output dimensions against existing test fixtures
2. **`test_explicit_bbox_extracts_all_three`** — Extract 3 diagrams with measured bboxes, verify files exist
3. **`test_output_dimensions_match_expected`** — Verify pixel dimensions ≥ expected minimums
4. **`test_output_filenames_follow_convention`** — Verify `page_{n}_{name}.png` naming
5. **`test_auto_detect_fallback`** — Omit bbox → falls back to `auto_detect_diagram_bbox()`
6. **`test_invalid_page_raises`** — Page 999 → raises `ValueError`
7. **`test_no_drawings_no_bbox_raises`** — Blank page + no bbox → raises `ValueError`
8. **`test_higher_dpi_produces_larger_image`** — 400 DPI ≈ 2× the 200 DPI dimensions
9. **`test_returns_bbox_for_page_with_drawings`** — Page 22 returns valid 4-tuple
10. **`test_returns_none_for_blank_page`** — Blank page → `None`
11. **`test_bbox_is_within_page_bounds`** — Bbox doesn't exceed page rect
12. **`test_detects_page22_with_default_thresholds`** — Page 22 detected with `min_drawings=10`
13. **`test_detects_all_three_with_lower_threshold`** — Pages 16/17 detected at appropriate threshold
14. **`test_high_threshold_returns_fewer_pages`** — Higher threshold → fewer results
15. **`test_renders_page_as_png`** — Creates valid PNG
16. **`test_invalid_page_raises`** — Page 0 or 9999 → `ValueError`
17. **`test_clip_region_reduces_height`** — Clipped image shorter than full page

### Future (for Phase 2)

4. **Unit test for `auto_detect_diagram_bbox()`:**
   - Mock a page with known drawing rects, verify merged bbox
   - Test header/footer filtering (drawings near page edges should be excluded)
5. **Integration test:** Run on `chapter01.pdf`, compare output hashes against golden images
6. **Regression test:** Save the 3 images as "golden" test fixtures

---

## Out of Scope

- OCR or text extraction from diagrams (labels use custom fonts; OCR would be a separate feature)
- Converting diagrams to structured data (e.g., Graphviz DOT notation)
- Handling raster images embedded within vector diagrams
- Supporting non-academic PDFs (e.g., marketing materials, infographics)
- Fixing custom font encoding for text extraction (rendering as pixels works fine)

---

## Next Steps

1. ~~**Immediate:** Measure accurate bounding boxes for the 3 diagrams (pages 16, 17, 22)~~ ✅
2. ~~**Validate:** Run extraction with measured bboxes, compare against existing fixtures~~ ✅
3. ~~**Test:** Write unit tests for `extract_diagram_regions()` using golden fixtures~~ ✅ (17 tests)
4. **Document:** Update README with diagram extraction examples
5. **Future:** Implement auto-detection with spatial clustering as Phase 2
6. **Future:** Add header/footer noise filtering to `auto_detect_diagram_bbox()`

---

## Appendix A: Diagram Descriptions

### 1. Shannon's Communication Model (Page 16)

**Structure:** Linear unidirectional flow with noise injection

```
[信源] --信息--> [传送者] --信号--> [  ] --信号--> [接收者] --信息--> [信宿]
                                  ↑
                              [噪声源]
                              (接收信号)
```

**Key elements:**
- 5 main boxes in horizontal sequence
- Noise source box below, arrow pointing up to signal line
- Labels: 信息 (information), 信号 (signal), 接收信号 (received signal)
- Drawing cluster at approximately y=307–418 in PDF coordinates

### 2. Schramm's Communication Model (Page 17)

**Structure:** Simplified linear model

```
[信源] → [编码] → [信号] → [译码] → [目的地]
```

**Key elements:**
- 5 boxes in horizontal sequence
- Single arrows connecting each box
- No noise source (simpler than Shannon)
- Located at approximately y=448–465 (narrow horizontal band)

### 3. Lasswell's 5W Model Matrix (Page 22)

**Structure:** 5×4 matrix grid

| Who (谁) | Says what (说什么) | In which channel (通过什么渠道) | To whom (给谁) | With what effect (取得什么效果) |
|----------|-------------------|--------------------------------|---------------|--------------------------------|
| 传播者 | 讯息 | 媒介 | 受众 | 效果 |
| 控制研究 | 内容分析 | 媒介分析 | 受众分析 | 效果分析 |

**Key elements:**
- 5 columns (one per W)
- 4 rows: English labels, Chinese translations, communication elements, research disciplines
- Grid lines separating cells — drawn as 29 individual line segments
- Located at approximately y=115–170

---

## Appendix B: Inconsistent Defaults

`detect_pages_with_diagrams()` defaults to `min_drawings=10`, but `render_diagram_pages()` overrides it to `min_drawings=15`. This means:

- `detect_pages_with_diagrams(pdf)` → returns pages 16, 22 (both have ≥10 drawings; page 17 has exactly 10, borderline)
- `render_diagram_pages(pdf)` → only detects page 22 (29 drawings ≥ 15; pages 16 and 17 fall below)

**Recommendation:** Align the defaults or document the intentional difference.

---

## References

- Current implementation: `pdf_image_extractor/page_renderer.py`
- PyMuPDF documentation: https://pymupdf.readthedocs.io/en/latest/
- Existing test fixtures: `diagrams_test/` (6 PNG files from manual extraction runs)
- Custom font issue: diagram text labels return garbled Unicode via `page.get_text()`
