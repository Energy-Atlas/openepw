# Climate.OneBuilding

## MCP Stage 2 availability — 2026-09-24

The local catalog retains the 56 accepted metadata correspondences, three
approximate localities and two unresolved name/code conflicts. Accepted coordinates
are checksum-pinned to their source indexes; a changed index makes their authority
stale. An approximate locality is never an exact station location, and archive
coordinates or EPW content have not been verified by these annotations. Catalog
matching does not grant redistribution rights. See the
[accepted review](../validation/mcp-stage-1/onebuilding-manual-review.md).

## MCP Stage 3a batch behavior — 2026-09-25

An exact published HTTPS product path is a verified native fetch identity for
within-job reuse. Distinct requested occurrences still receive distinct normalized
EPW artifacts and retain the source coordinates. This path identity does not
establish availability at another location or redistribution permission. A compact
local export can group byte-identical outputs only when task, transform and lineage
semantics also match. The Stage 3a published-batch anchor uses synthetic source
bytes and does not re-download or redistribute a hosted archive.

## v0.1 implementation result — 2026-09-20

The adapter retrieved and parsed the published Ithaca TMYx into 8,760 rows. Selection uses an explicit relative ZIP product path, or a country catalog with a location name; no global nearest-station index is claimed. ZIP path, member count and uncompressed size checks apply. Native data stays in ignored local artifacts and is not committed or mirrored.

## Earlier source/access review

No public JSON API was established. Use the site's linked HTML/KML catalogs,
cache them, and follow published ZIP links. Do not synthesize filenames from city
strings. Initial guessed state/about paths returned 404; following the root's
links found the working country `index.html` and `about/default.html`.

The Ithaca TMYx 2011–2025 archive downloaded successfully (429,341 bytes); its EPW
contains 8,760 rows, 35 fields and the station location 42.483, -76.467, 335 m,
UTC−5. Preserve the period/product name, original checksum and source URL.
Archive members include DDY and other formats; retrieve EPW without executing
or extracting unsafe archive paths. Current TMYx solar data derive from ERA5;
these products are not entirely station observations.
[Catalog](https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/index.html), [source descriptions](https://climate.onebuilding.org/sources/default.html).

The first-party home/about/source pages reviewed advertise downloads and citation
but show an all-rights-reserved footer, without an explicit general redistribution
license. Do not assert CC BY solely because another service does. Permit local
source retrieval with source notices; do not check these EPWs into tests or offer
a public mirror pending an explicit grant. This uncertainty affects redistribution,
not the empirical fact that downloads work. Other hosted products may have their
own terms. [Home](https://climate.onebuilding.org/), [about](https://climate.onebuilding.org/about/default.html).

No published rate ceiling verified: default one concurrent request with cache
and backoff. Status: catalog/download validated; reuse terms unresolved.
