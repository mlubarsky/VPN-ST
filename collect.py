"""Collect top-10 organic DuckDuckGo results per query and condition into dataset.csv.

Conditions per base query (e.g. MX-01):
  B0: English query, US settings          (kl=us-en)
  B1: English query, target-country settings (e.g. kl=mx-es, kl=jp-jp)
  T1: translated query, target-country settings (only when translated_query is filled in)

Usage: python3 collect.py            # collects every condition in queries.csv not yet in dataset.csv
       python3 collect.py MX-01 MX-02  # only these base queries
"""

import csv
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUERIES_CSV = HERE / "queries.csv"
DATASET_CSV = HERE / "dataset.csv"
RAW_DIR = HERE / "raw"

DOCKER_IMAGE = "openserp-local"
ENGINE = "duckduckgo"
TOP_N = 10
MAX_ATTEMPTS = 3
MIN_SANITY_HITS = 3  # results that must mention a sanity term, to catch junk SERPs
PAUSE_SECONDS = 8  # between searches, to stay under DuckDuckGo's bot detection

# DuckDuckGo kl value each (--region, --lang) pair must produce. DDG's Japan code is jp-jp.
EXPECTED_KL = {("US", "EN"): "us-en", ("MX", "ES"): "mx-es", ("JP", "JA"): "jp-jp"}

TRACKING_PARAMS = {"msockid", "gclid", "fbclid", "ref", "ref_src"}

COLUMNS = [
    "result_id", "query_id", "base_query_id", "method",
    "country", "region", "language", "category", "english_query", "query_text",
    "engine", "rank", "url", "normalized_url", "domain", "title", "snippet", "snippet_en",
    "retrieved_at",
    "relevance_criteria", "relevance_r1", "relevance_r2", "relevance_final", "notes",
]


def conditions(q):
    """Return (method, query_text, query_lang, region_flag, lang_flag) for each condition."""
    cc, tl = q["country_code"], q["target_lang"]
    conds = [
        ("B0", q["english_query"], "en", "US", "EN"),
        ("B1", q["english_query"], "en", cc, tl),
    ]
    if q["translated_query"].strip():
        conds.append(("T1", q["translated_query"], tl.lower(), cc, tl))
    return conds


def query_id_for(q, method):
    num = q["base_query_id"].split("-")[-1]
    return f"{q['country_code']}{method}-{num}"


def run_search(text, region, lang):
    """Run the openserp CLI in Docker. Returns (parsed JSON, kl actually sent to DDG)."""
    cmd = [
        "docker", "run", "--rm", "--init", "-e", "OPENSERP_APP_LOG_LEVEL=debug",
        DOCKER_IMAGE, "search", ENGINE, text,
        "--region", region, "--lang", lang, "--limit", str(TOP_N), "--format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "search failed")
    nav = re.findall(r"url=(https://duckduckgo\.com\S*?)\]\[Navigate\]", proc.stderr)
    kl = ""
    if nav:
        kl = urllib.parse.parse_qs(urllib.parse.urlsplit(nav[0]).query).get("kl", [""])[0]
    return json.loads(proc.stdout), kl


def organic(data):
    results = [r for r in data.get("results", []) if r.get("type") == "organic"]
    return sorted(results, key=lambda r: r["rank"])[:TOP_N]


def fold(text):
    """Lowercase and strip accents, so "Mérida" matches "merida"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def looks_valid(results, sanity_terms):
    """sanity_terms is "|"-separated; a result counts if it mentions any of them."""
    if len(results) < TOP_N:
        return False
    terms = [fold(t) for t in sanity_terms.split("|") if t.strip()]
    hits = 0
    for r in results:
        text = fold(r.get("title", "") + " " + urllib.parse.unquote(r.get("url", "")) + " " + r.get("snippet", ""))
        hits += any(t in text for t in terms)
    return hits >= MIN_SANITY_HITS


def normalize_url(url):
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    query = [
        (k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit((parts.scheme.lower(), host, path, urllib.parse.urlencode(query), ""))


def translate_to_en(text):
    """Back-translate via Google Translate (auto-detect source). Returns "" on failure."""
    if not text:
        return ""
    url = "https://clients5.google.com/translate_a/t?" + urllib.parse.urlencode(
        {"client": "dict-chrome-ex", "sl": "auto", "tl": "en", "q": text}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            translated, detected = json.load(resp)[0]
    except Exception as e:
        print(f"    translate failed: {e}", file=sys.stderr)
        return ""
    time.sleep(0.3)
    return text if detected == "en" else translated


def collect_condition(q, method, text, query_lang, region, lang):
    query_id = query_id_for(q, method)
    expected_kl = EXPECTED_KL[(region, lang)]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"  {query_id} attempt {attempt}: {text!r} region={region} lang={lang}", flush=True)
        try:
            data, kl = run_search(text, region, lang)
        except Exception as e:
            print(f"    error: {e}", flush=True)
            time.sleep(PAUSE_SECONDS * attempt)
            continue
        if kl != expected_kl:
            raise RuntimeError(f"{query_id}: DDG was sent kl={kl!r}, expected {expected_kl!r}")
        results = organic(data)
        time.sleep(PAUSE_SECONDS)
        # Pages in the target language often don't name their own country, so a translated
        # query can be checked against topic words from the translation instead.
        terms = q.get("t1_sanity_term") if method == "T1" and q.get("t1_sanity_term") else q["sanity_term"]
        if looks_valid(results, terms):
            break
        print(f"    rejected: {len(results)} organic results, failed sanity check", flush=True)
        time.sleep(PAUSE_SECONDS * attempt)
    else:
        raise RuntimeError(f"{query_id}: no valid results after {MAX_ATTEMPTS} attempts")

    RAW_DIR.mkdir(exist_ok=True)
    (RAW_DIR / f"{query_id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))

    rows = []
    for r in results:
        url = r["url"]
        rows.append({
            "result_id": f"{query_id}-R{r['rank']:02d}",
            "query_id": query_id,
            "base_query_id": q["base_query_id"],
            "method": method,
            "country": q["country"],
            "region": kl,
            "language": query_lang,
            "category": q["category"],
            "english_query": q["english_query"],
            "query_text": text,
            "engine": ENGINE,
            "rank": r["rank"],
            "url": url,
            "normalized_url": normalize_url(url),
            "domain": r.get("domain") or urllib.parse.urlsplit(url).netloc,
            "title": r.get("title", ""),
            "snippet": r.get("snippet", ""),
            "snippet_en": translate_to_en(r.get("snippet", "")),
            "retrieved_at": data.get("meta", {}).get("requested_at", ""),
            "relevance_criteria": q["relevance_criteria"],
            "relevance_r1": "", "relevance_r2": "", "relevance_final": "", "notes": "",
        })
    return rows


def main():
    with QUERIES_CSV.open(newline="", encoding="utf-8") as f:
        queries = list(csv.DictReader(f))
    if len(sys.argv) > 1:
        queries = [q for q in queries if q["base_query_id"] in sys.argv[1:]]

    done = set()
    if DATASET_CSV.exists():
        with DATASET_CSV.open(newline="", encoding="utf-8") as f:
            done = {row["query_id"] for row in csv.DictReader(f)}

    failed = []
    new_file = not DATASET_CSV.exists()
    with DATASET_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        for q in queries:
            pending = [c for c in conditions(q) if query_id_for(q, c[0]) not in done]
            if not pending:
                print(f"skip {q['base_query_id']} (already in dataset)")
                continue
            print(f"{q['base_query_id']}: {q['english_query']}", flush=True)
            for c in pending:
                try:
                    rows = collect_condition(q, *c)
                except RuntimeError as e:
                    print(f"  FAILED: {e}", flush=True)
                    failed.append(query_id_for(q, c[0]))
                    continue
                writer.writerows(rows)
                f.flush()

    if failed:
        print(f"\n{len(failed)} condition(s) failed, rerun to retry: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
