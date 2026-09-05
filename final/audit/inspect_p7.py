"""Inspect page 7 of the rendered PDF to understand the references overlap."""
import pymupdf

doc = pymupdf.open("paper/main.pdf")
p7 = doc[6]
print("Page 7 rect:", p7.rect)
print()

# Get text spans with bboxes
text_dict = p7.get_text("dict")
print("=== Page 7 text spans ===")
for block in text_dict["blocks"]:
    if "lines" not in block:
        continue
    for line in block["lines"]:
        for span in line["spans"]:
            x0, y0, x1, y1 = span["bbox"]
            text = span["text"][:90]
            print(f"x={x0:6.1f} y={y0:6.1f}  w={x1-x0:5.1f} h={y1-y0:5.1f}  | {text!r}")
