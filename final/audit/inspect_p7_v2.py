#!/usr/bin/env python3
"""Inspect References section of page 7: extract all reference lines with bboxes."""
import pymupdf
import re
import sys

doc = pymupdf.open('paper/main.pdf')
page = doc[6]  # page 7
data = page.get_text('dict')

# Collect every text line on the page
all_lines = []
for b in data['blocks']:
    if b['type'] != 0:
        continue
    for line in b['lines']:
        full = ''.join(s['text'] for s in line['spans'])
        bbox = line['bbox']
        all_lines.append({'text': full, 'x0': bbox[0], 'y0': bbox[1],
                          'x1': bbox[2], 'y1': bbox[3]})

# Print only lines that look like references (start with [N])
print('=== Reference lines (sorted by y, then x) ===')
ref_lines = [L for L in all_lines if re.match(r'\s*\[\d+\]', L['text'])]
ref_lines.sort(key=lambda L: (L['y0'], L['x0']))
for L in ref_lines:
    print(f"y0={L['y0']:6.1f} x0={L['x0']:6.1f} x1={L['x1']:6.1f}  | {L['text'][:120]!r}")

# Distinct y values (rows)
print()
print('=== Distinct rows (y0 values), with x ranges ===')
rows = {}
for L in ref_lines:
    key = round(L['y0'], 1)
    rows.setdefault(key, []).append(L)
for y in sorted(rows):
    xs = [(L['x0'], L['x1']) for L in rows[y]]
    print(f"y={y:6.1f}  count={len(rows[y])}  x_ranges={xs}  text0={rows[y][0]['text'][:50]!r}")
