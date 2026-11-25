# VPN-ST
NLPers Group Project - VPN-ST (search and translate)

## Scripts

| Script | What it does |
|---|---|
| `collect.py` | Runs each query through DuckDuckGo (via OpenSERP in Docker) for each condition (B0, B1, T1) and appends the top 10 organic results to `dataset.csv`. |
| `complete_rows.py` | For results entered by hand (e.g. T2), fills in `normalized_url`, `domain` and `snippet_en` using the same rules as `collect.py`. |

Both scripts use only the Python standard library (Python 3.9 or newer); there is nothing to `pip install`.

## Setting up OpenSERP (Docker)

`collect.py` runs searches with [OpenSERP](https://github.com/karust/openserp) inside a Docker image named `openserp-local`. You need [Docker](https://docs.docker.com/get-docker/) installed and running, then build the image once:

**1. Download OpenSERP version 0.8.14.** Use this exact version; later versions have changed.

```sh
git clone --branch v0.8.14 --depth 1 https://github.com/karust/openserp.git
cd openserp
```

**2. Fix the Japan region code.** OpenSERP sends Japanese searches to DuckDuckGo as `kl=jp-ja`, which is not a DuckDuckGo region; Japan is `jp-jp`. In `duckduckgo/url.go`, change the line

```go
	"ja":    "jp-ja",
```

to

```go
	"ja":    "jp-jp",
```

or run this from the `openserp` folder:

```sh
perl -pi -e 's/"ja":(\s+)"jp-ja"/"ja":$1"jp-jp"/' duckduckgo/url.go
```

This is the only change. Without it, `collect.py` stops on every Japan search with `DDG was sent kl='jp-ja', expected 'jp-jp'`.

**3. Build the image.** The name must be exactly `openserp-local`, since that is what `collect.py` calls. This takes a few minutes the first time.

```sh
docker build -t openserp-local .
```

**4. Check it works.** This runs one search with Japan settings:

```sh
docker run --rm --init -e OPENSERP_APP_LOG_LEVEL=debug openserp-local \
  search duckduckgo "test" --region JP --lang JA --limit 3 --format json
```

You should get JSON results, and the log lines should include `kl=jp-jp`.

## Running the search

```sh
python3 collect.py                # every condition in queries.csv not yet in dataset.csv
python3 collect.py MX-01 JP-04    # only these queries
```

`collect.py` checks every search before saving it: the region DuckDuckGo actually received must match the condition (`us-en`, `mx-es` or `jp-jp`), and at least 3 of the 10 results must mention the query's location. Failed searches are retried up to 3 times. It pauses about 8 seconds between searches to avoid DuckDuckGo's bot detection, so a full run takes a while.

### T2 (LLM-translated queries)

`collect.py` does not run T2. `dataset.csv` already has 300 empty T2 rows (30 queries × ranks 1–10, `query_id` like `MXT2-01`) with the query, region and language filled in. For each row, search DuckDuckGo with the row's `query_text` and region setting (`mx-es` for Mexico, `jp-jp` for Japan) and fill in:

- `url`: the organic result at that rank (skip ads, so rank 1 is the first non-ad result)
- `title` and `snippet`: as shown on the results page, in the original language
- `retrieved_at`: when you searched, in UTC, e.g. `2026-11-26T18:05:00Z`

Then run:

```sh
python3 complete_rows.py
```

It fills in `normalized_url`, `domain` and `snippet_en` for every row with a `url`, and never overwrites values that are already filled in.
