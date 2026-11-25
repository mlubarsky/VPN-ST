"""Fill the derived columns of manually entered search results in dataset.csv.

For every row with a url, fills whichever of these are blank:
  normalized_url  same rules as collect.py (lowercase host, no www., no tracking params,
                  no #fragment, no trailing slash); used to match pages across conditions
  domain          host of the url, lowercased, without "www." (as in the B0/B1/T1 rows)
  snippet_en      snippet translated to English with Google Translate (same as collect.py)

Never overwrites a value that is already filled in. Safe to rerun.

Usage: python3 complete_rows.py
"""

import csv
import urllib.parse
from pathlib import Path

from collect import normalize_url, translate_to_en

HERE = Path(__file__).resolve().parent
DATASET_CSV = HERE / "dataset.csv"


def main():
    with DATASET_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols, rows = reader.fieldnames, list(reader)

    filled = {"normalized_url": 0, "domain": 0, "snippet_en": 0}
    for r in rows:
        url = r["url"].strip()
        if not url:
            continue
        if not r["normalized_url"]:
            r["normalized_url"] = normalize_url(url)
            filled["normalized_url"] += 1
        if not r["domain"]:
            # Matches the existing rows: host, lowercased, without "www." (e.g. properstar.com).
            r["domain"] = urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")
            filled["domain"] += 1
        if not r["snippet_en"] and r["snippet"].strip():
            r["snippet_en"] = translate_to_en(r["snippet"])
            filled["snippet_en"] += bool(r["snippet_en"])

    with DATASET_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    blank = sum(not r["url"].strip() for r in rows)
    print(f"filled {filled}; {blank} rows still have no url")


if __name__ == "__main__":
    main()
