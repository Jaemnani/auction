"""캡처된 W2X(XML) 본문에서 endpoint 패턴과 화면 ID를 모두 추출."""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if len(sys.argv) < 2:
    print("usage: extract_endpoints.py <recon_dir>")
    sys.exit(1)

recon = Path(sys.argv[1])
bodies = recon / "bodies"

url_by_body = {}
with (recon / "responses.jsonl").open(encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        if d.get("body_file"):
            url_by_body[d["body_file"]] = d["url"]

ON_RE = re.compile(r"/pgj/[A-Za-z0-9_/]+\.on")
W2X_RE = re.compile(r"/pgj/ui/[A-Za-z0-9_/]+\.xml")
ACTION_RE = re.compile(r"action=[\"']([^\"']+\.on)[\"']")
SCN_RE = re.compile(r"\bPGJ[0-9A-Z]+\.xml")

per_file_ons = defaultdict(set)
per_file_w2x = defaultdict(set)
per_file_action = defaultdict(set)
per_file_scn = defaultdict(set)

for body_path in sorted(bodies.iterdir()):
    text = body_path.read_text(encoding="utf-8", errors="replace")
    src_url = url_by_body.get(body_path.name, "(unknown)")
    for m in ON_RE.findall(text):
        per_file_ons[(body_path.name, src_url)].add(m)
    for m in W2X_RE.findall(text):
        per_file_w2x[(body_path.name, src_url)].add(m)
    for m in ACTION_RE.findall(text):
        per_file_action[(body_path.name, src_url)].add(m)
    for m in SCN_RE.findall(text):
        per_file_scn[(body_path.name, src_url)].add(m)

print("=== .on endpoints found per body ===")
for (name, src), s in sorted(per_file_ons.items()):
    print(f"\n[{name}] {src}")
    for u in sorted(s):
        print(f"   {u}")

print("\n=== submission action= refs ===")
for (name, src), s in sorted(per_file_action.items()):
    print(f"\n[{name}] {src}")
    for u in sorted(s):
        print(f"   {u}")

print("\n=== W2X file refs ===")
for (name, src), s in sorted(per_file_w2x.items()):
    print(f"\n[{name}] {src}")
    for u in sorted(s):
        print(f"   {u}")

print("\n=== screen IDs (PGJxxxMyy.xml) ===")
all_screens = set()
for s in per_file_scn.values():
    all_screens.update(s)
for sid in sorted(all_screens):
    print(f"   {sid}")
