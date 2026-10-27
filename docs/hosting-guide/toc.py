import sys, json, re
import pymupdf as fitz
toc = json.loads(sys.argv[2])
doc = fitz.open(sys.argv[1])
out = {}
for t in toc:
    for i, page in enumerate(doc):
        if i < 2: continue
        lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
        if lines[:3] and t in lines[:3]:
            out[t] = i + 1; break
print(json.dumps(out, indent=0))
missing = [t for t in toc if t not in out]
print("MISSING", missing, file=sys.stderr)
print("PAGES", doc.page_count, file=sys.stderr)
