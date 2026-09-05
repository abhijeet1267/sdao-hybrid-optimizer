#!/usr/bin/env python3
"""Inspect References: dump every text line on page 7 with its bbox + char count."""
import pymupdf, re

doc = pymupdf.open('paper/main.pdf')
page = doc[6]
data = page.get_text('dict')

# Collect all text lines with bbox
out = []
for b in data['blocks']:
    if b['type'] != 0:
        continue
    for line in b['lines']:
        full = ''.join(s['text'] for s in line['spans'])
        bbox = line['bbox']
        # Only keep lines that contain a "[N]" reference marker or are continuation
        out.append({'text': full, 'x0': bbox[0], 'y0': bbox[1],
                    'x1': bbox[2], 'y1': bbox[3]})

# Filter to area y > 600 (the references area) and print everything
print('=== All lines below y=600 (References area) ===')
ref_area = [L for L in out if L['y0'] > 600]
ref_area.sort(key=lambda L: (round(L['y0'],1), L['x0']))
for L in ref_area:
    print(f"y={L['y0']:6.1f}  x0={L['x0']:6.1f}..{L['x1']:6.1f}  len={len(L['text']):3d} | {L['text']!r}")

# Now check: are there really two lines per reference, or is each reference one line
# that overflows the column?
print()
print('=== Column width = 3.4*inch = 244.8pt. Lines with x1-x0 > 244.8: ===')
for L in ref_area:
    if (L['x1']-L['x0']) > 244.5:
        print(f"  y={L['y0']:6.1f}  width={L['x1']-L['x0']:5.1f}  x0={L['x0']:6.1f} | {L['text'][:60]!r}")
