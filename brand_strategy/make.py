"""To'liq yig'ish: HTML -> PDF -> mundarija sahifalarini topish -> qayta yig'ish.
Ishlatish: python3 make.py"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "out"
PDF = OUT / "BOBUR_30_kunlik_strategiya.pdf"


def run():
    subprocess.run(["python3", str(ROOT / "build.py")], check=True)
    subprocess.run(["node", str(ROOT / "render.js")], check=True)


def find_pages():
    html = (OUT / "strategy.html").read_text(encoding="utf-8")
    # har bir bo'lim: id -> sarlavha (h2) matni
    heads = {m.group(1): re.sub("<[^>]+>", "", m.group(2)).strip()
             for m in re.finditer(r'<section class="chapter" id="(\w+)">\s*<div class="chapter-head">.*?<h2>(.*?)</h2>', html, re.S)}
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(PDF)], capture_output=True, text=True).stdout).group(1))
    texts = [subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), str(PDF), "-"], capture_output=True, text=True).stdout
             for i in range(1, n + 1)]
    norm = lambda t: re.sub(r"\s+", " ", t)
    pages = {}
    for sid, title in heads.items():
        for i, t in enumerate(texts[2:], start=3):  # muqova va mundarijadan keyin
            if norm(title) in norm(t):
                pages[sid] = i - 1  # muqovada raqam yo'q
                break
    return pages


if __name__ == "__main__":
    pf = OUT / "toc_pages.json"
    pf.unlink(missing_ok=True)
    run()
    pages = find_pages()
    pf.write_text(json.dumps(pages))
    run()
    assert find_pages() == pages, "sahifalar siljidi"
    print("Mundarija:", pages)
