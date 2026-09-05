#!/usr/bin/env python3
"""
Audit-only visual overlay for page 7 of paper/main.pdf.

Goals (per spec):
- Identify logical references [1]..[12] by detecting lines that begin with
  a bracketed numeric citation ("[1]", "[2]", ..., "[12]").
- Exclude all non-reference text: body paragraphs, "References" heading,
  section headings, conclusion, captions, etc. (We do NOT use y0 > 600
  as the gate; the bracket pattern alone is the gate.)
- Group continuation lines (no leading [N]) onto the preceding logical
  reference. A multi-line reference such as Stillger et al. [5] therefore
  yields 1 logical label and 1 or 2 physical boxes -- never two labels.
- Verify that the set of detected numbers is exactly {1..12} and is in
  ascending order with no duplicates.
- Place labels in the page's right margin (a clear, empty area on this
  page) so they never overlap their own reference box or another
  reference's box. Left/right column assignment is preserved (red/blue).
- Do NOT modify the paper, the PDF, or any artifact. We render once,
  overlay onto a copy in memory, and save a *new* PNG; the original
  page object is never written back to disk.
"""
import re
import sys
import pymupdf

REF_PATTERN = re.compile(r'^\s*\[(\d+)\]')

PAGE_INDEX = 6  # page 7 (0-indexed)
ZOOM = 2.0
LEFT_COL_X_MAX = 306.0  # x0 < 306 -> left column -> red
# Reference rows on this page are spaced as tightly as 11.4 pt in PDF
# coords (where a 2-line reference sits above a 1-line reference). To
# avoid label collisions we keep each label compact: fontsize 9 gives
# ~6 pt of visible glyph height, and we draw no opaque halo -- the
# margins are already white paper, so colored text is fully legible.
LABEL_FONTSIZE = 9
LABEL_TEXT_H = 9.0       # cap-height-ish footprint in PDF points
LABEL_BOX_W = 20.0       # generous width; we use it only for overlap math
LABEL_BOX_H = LABEL_TEXT_H  # 9 pt
# Labels go in the page's left or right margin, depending on column, so
# that the two labels at the same row never collide. Page is 612 pt wide.
# Left-column reference boxes start at x ~= 63 -> left margin fits at x ~= 6
# (we draw the white halo to the right of the label).
# Right-column reference boxes end at x ~= 545 -> right margin fits at
# x ~= 578 (just inside the 612 page edge).
LABEL_MARGIN_X_LEFT = 6.0
LABEL_MARGIN_X_RIGHT = 578.0

PDF_PATH = 'paper/main.pdf'
OUT_DIR = 'audit/pdf_pages'
BARE_PNG = f'{OUT_DIR}/page_7_full.png'
ANN_PNG = f'{OUT_DIR}/page_7_annotated.png'

def collect_lines(page):
    """Return [(block_idx, line_idx, text, bbox), ...] from get_text('dict')."""
    out = []
    data = page.get_text('dict')
    for bi, b in enumerate(data['blocks']):
        if b['type'] != 0:
            continue
        for li, line in enumerate(b['lines']):
            text = ''.join(s['text'] for s in line['spans'])
            out.append((bi, li, text, line['bbox']))
    return out


def group_into_logical_refs(lines):
    """
    Group physical lines into logical references.

    A logical reference starts on a line whose text matches REF_PATTERN.
    Subsequent lines are appended to that logical reference until the
    next [N] starts. Returns a list of dicts:
        { 'num': int, 'spans': [(text, bbox), ...] }
    in document order.
    """
    refs = []
    for bi, li, text, bbox in lines:
        m = REF_PATTERN.match(text)
        if m:
            refs.append({'num': int(m.group(1)), 'spans': [(text, bbox)]})
        elif refs:
            # continuation of the most recent reference
            refs[-1]['spans'].append((text, bbox))
        # else: stray pre-reference line; ignore (no active ref yet)
    return refs


def union_bbox(boxes):
    boxes = list(boxes)  # materialize so the caller can't accidentally exhaust
    if not boxes:
        raise ValueError('union_bbox called with no boxes')
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


def main():
    doc = pymupdf.open(PDF_PATH)
    page = doc[PAGE_INDEX]
    page_w, page_h = page.rect.x1, page.rect.y1

    lines = collect_lines(page)
    refs = group_into_logical_refs(lines)

    # --- Validation pass -------------------------------------------------
    # The paper uses a two-column layout, so the PDF's reading order
    # interleaves left-column and right-column references row-by-row
    # (e.g. [1], [7], [2], [8], ...). What matters is that every
    # reference in the paper's [1]..[12] range is detected exactly once.
    nums = [r['num'] for r in refs]
    expected_set = set(range(1, 13))
    if set(nums) != expected_set:
        missing = expected_set - set(nums)
        extra = set(nums) - expected_set
        print(f'ERROR: reference set {set(nums)} != {expected_set}; '
              f'missing={missing} extra={extra}', file=sys.stderr)
        sys.exit(1)
    if len(nums) != 12:
        print(f'ERROR: expected 12 logical refs, got {len(nums)}: {nums}',
              file=sys.stderr)
        sys.exit(1)
    if len(set(nums)) != len(nums):
        from collections import Counter
        dups = [n for n, c in Counter(nums).items() if c > 1]
        print(f'ERROR: duplicate reference numbers: {dups}', file=sys.stderr)
        sys.exit(1)
    # Sanity: only one logical ref per number, preserved from the paper.
    for n in nums:
        assert 1 <= n <= 12
    print(f'Detected {len(refs)} logical references, numbers {nums}')

    # --- Render bare page first -----------------------------------------
    mat = pymupdf.Matrix(ZOOM, ZOOM)
    pix_bare = page.get_pixmap(matrix=mat)
    pix_bare.save(BARE_PNG)
    print(f'Wrote {BARE_PNG} ({pix_bare.width}x{pix_bare.height})')

    # --- Draw overlays on the in-memory page (overlay=True, so original
    #     page is untouched on disk) -------------------------------------
    physical_boxes = 0
    label_centers = []  # (x_center, y_center, col) for overlap check
    for ref in refs:
        n = ref['num']
        is_left = ref['spans'][0][1][0] < LEFT_COL_X_MAX
        color = (1, 0, 0) if is_left else (0, 0, 1)

        # One physical box per PDF line belonging to this reference.
        for (text, bbox) in ref['spans']:
            x0, y0, x1, y1 = bbox
            page.draw_rect(
                pymupdf.Rect(x0, y0, x1, y1),
                color=color, width=0.6, overlay=True,
            )
            physical_boxes += 1

        # Label: in the page margin on the SAME SIDE as the column, so
        # the left-column label and the right-column label at the same
        # row do not collide. Anchor on the FIRST physical line's
        # vertical center, not the union -- otherwise a 2-line ref
        # above a 1-line ref can compress the gap to 11.4 pt.
        first_bbox = ref['spans'][0][1]
        cy = (first_bbox[1] + first_bbox[3]) / 2
        label = f'[{n}]'
        margin_x = LABEL_MARGIN_X_LEFT if is_left else LABEL_MARGIN_X_RIGHT
        # Vertically center the text on cy. The baseline for fontsize 9
        # sits ~3 pt above the visual center of the glyphs.
        text_baseline = cy + 3.0
        page.insert_text(
            (margin_x, text_baseline),
            label, fontsize=LABEL_FONTSIZE, color=color, overlay=True,
        )
        label_centers.append((margin_x + LABEL_BOX_W / 2, cy, 'L' if is_left else 'R'))

    # --- Render annotated page ------------------------------------------
    pix_ann = page.get_pixmap(matrix=mat)
    pix_ann.save(ANN_PNG)
    print(f'Wrote {ANN_PNG} ({pix_ann.width}x{pix_ann.height}) '
          f'with {len(refs)} logical refs / {physical_boxes} physical boxes')

    # --- Overlap sanity check (per-column) ------------------------------
    for col in ('L', 'R'):
        rows = sorted([(y, x) for (x, y, c) in label_centers if c == col])
        for (y1, _), (y2, _) in zip(rows, rows[1:]):
            if y2 - y1 < LABEL_BOX_H:
                print(f'WARN: column {col} labels nearly overlap at '
                      f'y={y1:.1f}, {y2:.1f} (gap {y2 - y1:.1f} < '
                      f'{LABEL_BOX_H})')

    # --- Spec-required report -------------------------------------------
    print('\n=== AUDIT REPORT ===')
    print(f'PDF path          : {PDF_PATH}')
    print(f'Logical refs      : {len(refs)}  (expected 12)')
    print(f'Physical boxes    : {physical_boxes}')
    print(f'Reference numbers : {nums}')
    print(f'Bare PNG          : {BARE_PNG}')
    print(f'Annotated PNG     : {ANN_PNG}')


if __name__ == '__main__':
    main()
