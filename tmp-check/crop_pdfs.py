#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import argparse
from pypdf import PdfReader, PdfWriter

UNIT_TO_POINTS = {
    "in": 72.0,          # inch -> points
    "cm": 72.0 / 2.54,   # cm -> points
    "pt": 1.0,           # points
}

def crop_pdf(in_path: str, out_path: str, left_pt: float, right_pt: float, bottom_pt: float, top_pt: float):
    reader = PdfReader(in_path)
    writer = PdfWriter()

    for page in reader.pages:
        mb = page.mediabox
        x0, y0 = float(mb.left), float(mb.bottom)
        x1, y1 = float(mb.right), float(mb.top)

        nx0 = x0 + left_pt
        ny0 = y0 + bottom_pt
        nx1 = x1 - right_pt
        ny1 = y1 - top_pt

        if nx1 <= nx0 or ny1 <= ny0:
            raise ValueError(
                f"Crop too large for page in {in_path}: "
                f"new box invalid ({nx0:.2f},{ny0:.2f},{nx1:.2f},{ny1:.2f})"
            )

        # Set all boxes for best viewer compatibility
        page.mediabox.lower_left = (nx0, ny0)
        page.mediabox.upper_right = (nx1, ny1)

        if hasattr(page, "cropbox"):
            page.cropbox.lower_left = (nx0, ny0)
            page.cropbox.upper_right = (nx1, ny1)
        if hasattr(page, "trimbox"):
            page.trimbox.lower_left = (nx0, ny0)
            page.trimbox.upper_right = (nx1, ny1)
        if hasattr(page, "bleedbox"):
            page.bleedbox.lower_left = (nx0, ny0)
            page.bleedbox.upper_right = (nx1, ny1)
        if hasattr(page, "artbox"):
            page.artbox.lower_left = (nx0, ny0)
            page.artbox.upper_right = (nx1, ny1)

        writer.add_page(page)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

def main():
    ap = argparse.ArgumentParser(description="Batch crop PDFs by margins (left/right/bottom/top).")
    ap.add_argument("--unit", choices=["in", "cm", "pt"], default="in", help="Unit of margins (default: in)")
    ap.add_argument("--top", type=float, required=True)
    ap.add_argument("--bottom", type=float, required=True)
    ap.add_argument("--left", type=float, required=True)
    ap.add_argument("--right", type=float, required=True)
    ap.add_argument("--out_dir", default="", help="Output directory (default: same as input)")
    ap.add_argument("pdfs", nargs="+", help="PDF file paths")
    args = ap.parse_args()

    k = UNIT_TO_POINTS[args.unit]
    left_pt, right_pt, bottom_pt, top_pt = args.left * k, args.right * k, args.bottom * k, args.top * k

    for in_path in args.pdfs:
        in_path = os.path.expanduser(in_path)
        base = os.path.basename(in_path)
        name, ext = os.path.splitext(base)
        out_dir = os.path.expanduser(args.out_dir) if args.out_dir else os.path.dirname(in_path)
        out_path = os.path.join(out_dir, f"{name}_cropped{ext}")

        crop_pdf(in_path, out_path, left_pt, right_pt, bottom_pt, top_pt)
        print(f"[OK] {in_path} -> {out_path}")

if __name__ == "__main__":
    main()