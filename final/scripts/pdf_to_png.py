"""Convert all PDF figures to PNG so reportlab Image can render them."""
from pathlib import Path
import pymupdf

FIG = Path("/Users/abhijeetmiskin/AppData/MyProject/final/figures")
for pdf in sorted(FIG.glob("*.pdf")):
    doc = pymupdf.open(str(pdf))
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    out = pdf.with_suffix(".png")
    pix.save(str(out))
    print(f"{pdf.name} -> {out.name} ({out.stat().st_size} bytes)")
    doc.close()