"""메인 HTML에서 모든 W2X 화면 ID와 endpoint 참조를 뽑아낸다."""

import re
import sys
from collections import Counter
from pathlib import Path

if len(sys.argv) < 2:
    print("usage: extract_w2x_paths.py <recon_dir>")
    sys.exit(1)

recon_dir = Path(sys.argv[1])
html = (recon_dir / "page_main.html").read_text(encoding="utf-8", errors="replace")

w2x_paths = re.findall(r"""w2xPath=([^"'&<>\s]+)""", html)
print("=== w2xPath= references ===")
for p, n in Counter(w2x_paths).most_common():
    print(f"  x{n:<3} {p}")

xmls = re.findall(r"/pgj/ui/[A-Za-z0-9_/]+\.xml", html)
print("\n=== /pgj/ui/**/*.xml references (incl. components) ===")
for p, n in Counter(xmls).most_common():
    print(f"  x{n:<3} {p}")

ons = re.findall(r"/pgj/[A-Za-z0-9_/]+\.on", html)
print("\n=== /pgj/**/*.on references ===")
for p, n in Counter(ons).most_common():
    print(f"  x{n:<3} {p}")
