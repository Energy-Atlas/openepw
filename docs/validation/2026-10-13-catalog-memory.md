# Catalog memory and first-page time on the hosted server (2026-10-13)

What happened on Render staging after the 2026.10.13 catalog, what was measured and changed,
and what is still open. Measurements are local (Windows, the project `.venv`, the local
data root with the 2026.10.13 generation); Render's CPU is slower and its memory accounting
is Linux's. Reproduce with `scripts/measure_catalog_runtime.py` (`memory` and `http`).

## What happened on staging

1. With the new catalog (73,403 products, 106,991 sites, 99,438 entries) the 2 GB instance
   ran out of memory. The owner upgraded staging to 4 GB.
2. On the larger instance Render set `WEB_CONCURRENCY=2`. Uvicorn took that as the worker
   count, refused it for an app object and exited with status 3.
   - Fixed by `serve` passing `workers=1`, since the server is one process by design.
   - Merged to `main` and staging.
3. Staging still ran out of memory about 13 minutes after start, on 4 GB.
   - Fixed by the compact catalog index (below).
   - Staging then stayed up through a 30-minute watch.

## Measurements and changes

**Where the memory went:** the store loaded every record of the generation as a validated
pydantic object.

| Table | Rows | Memory as objects |
|---|---:|---:|
| products | 73,403 | 287 MB |
| sites | 106,991 | 182 MB |
| entries | 99,438 | 431 MB |

By provider:
- OneBuilding: 615 MB (products 284, sites 123, entries 208).
- NOAA: 241 MB, most of it the month counts in its entries.

Deduplicating strings and lists saved only about 20% (900 to 726 MB), because most of the
cost is per-object overhead.

**Changes, in order:**

1. **Compact index** (`fix/catalog-memory`).
   - An assessment reads only the nearest few dozen files and stations, so OneBuilding and
     NOAA records stay in SQLite.
   - Memory holds only their positions, ids, entry ids and map points
     (`availability/catalog_index.py`, `StoreCatalogIndex`).
   - Records are read by id through an 8,192-record cache. Other providers are held in full.
   - On the local catalog, 137 assessments, the map and the scope list are identical to the
     full catalog. `tests/unit/test_catalog_index.py` checks the same on a synthetic catalog.
2. **Prepared at install, gzip and ETag, warm-up** (`fix/catalog-precompute`).
   - The index state and the map are saved under `catalog/derived/<generation>/`: `index.json`
     (71 MB) and `map-<footprints>.json.gz` (1.7 MB).
   - The install step (`openepw.deploy`, `prepare_catalog`) writes them before the server
     starts, and the server warms them in its lifespan before serving.
   - `/v1/catalog/map` returns the stored gzip with an ETag and `Cache-Control: no-cache`.
   - A gzip layer compresses every larger response.
3. **Diagnostics and allocator.**
   - `/v1/diagnostics` (the staging Copy log) reports resident and peak memory on Linux.
   - The image sets `MALLOC_ARENA_MAX=2` against glibc per-thread arena growth. This is a
     precaution, not reproduced locally: there is no Docker or WSL on this machine.

**Memory (working set, MB):**

| Point | Records in memory | Compact index | Index read from `index.json` |
|---|---:|---:|---:|
| After the catalog loads | 1,060 | 313 | 384–412 |
| Plateau under the browsing soak (map, hover, product lists) | ~1,250 | ~490 | ~470–520 |

No step leaked: repeated map loads, hover lookups and product lists level off.

**First page (seconds):**

| Step | Before | After |
|---|---:|---:|
| First `/v1/catalog/map` after a start | 3.52 | 0.01 |
| Later map requests (JSON encoding of the cached map) | 0.34–0.48 | 0.01 |
| First map hover lookup | 0.45 | 0.04 |
| Map sent per page load (MB) | 6.31 | 1.71, or 304 on revalidation |
| Start to `/health` | 2.66 | 3.19 (includes the warm-up) |

Before the change, the first map request was made of: index build 2.82, map layers 0.10,
`jsonable_encoder` 0.35, response 0.07.

**Install step** (`python -m openepw.deploy install-catalog`, its own process before the
server):

| Case | Time | Peak memory |
|---|---:|---:|
| New pin, local package files | 7.9 s | about 1.5 GB (holds the whole package and the whole bundle while staging the generation) |
| Same pin | 0.01 s | — |
| Preparing derived files, first time | 4.9 s | — |
| Preparing derived files, already present | 1.3 s | — |

## Open (not decided)

- **The install peak of about 1.5 GB.** It happens only when the pin changes, and runs
  before the server.
  - Options: stage the generation from the package table by table, or stream CSV rows into
    SQLite without building a `CatalogBundle`.
  - `export_package`/`load_package` and `CatalogStore.stage` would need streaming variants.
- **`index.json` is 71 MB,** read in one `json.loads` at start. Options: a compact binary
  form (numpy arrays for positions, a string table), or a SQLite table for the index state.
- **Render's own numbers.** The Copy log memory figure on staging, over a long session and
  under several users, would confirm the plateau and whether `MALLOC_ARENA_MAX` matters.
- **The instance size.** Staging runs at 4 GB after the owner's upgrade; whether 2 GB is
  enough now is untested. Production (`feature/render-deploy`) is at 2 GB, has none of
  these changes, and still has the 2026.09.28 catalog.
- **Per-request caches:**
  - the record cache (8,192 records);
  - the map hover cache in the API (4,096 points);
  - the map payload.
  They are bounded; their sizes are not tuned.
