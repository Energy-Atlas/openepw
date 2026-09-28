# Deploying OpenEPW on Render

One Docker web service serves the chat UI and the API from the same address, behind a
single site password. Data (Stage 1 catalog, chat sessions, weather jobs, downloads)
lives on a Render persistent disk. Files: [`Dockerfile`](../../Dockerfile),
[`docker/entrypoint.sh`](../../docker/entrypoint.sh), [`render.yaml`](../../render.yaml),
[`src/openepw/deploy.py`](../../src/openepw/deploy.py) (catalog install) and
[`src/openepw/api/site_gate.py`](../../src/openepw/api/site_gate.py) (password gate).

Plan: **Standard** (2 GB). The service uses about 760 MB with the catalog loaded
(measured in the local container). Disk: 10 GB (about $2.50/month); today's data is
well under 1 GB and each EPW adds about 1.8 MB.

## 1. Pin the catalog package

The Stage 1 catalog is published as a CSV data package in the public
[Energy-Atlas/open-data](https://github.com/Energy-Atlas/open-data) repository
(`datasets/weather-availability-catalog/`). On first start the service downloads its
`datapackage.json`, checks it against a pinned SHA-256, downloads every file it lists,
checks each file's size and SHA-256, and builds the catalog from them. Pin a commit, not
a branch, so the package cannot change under the deployment:

```text
OPENEPW_CATALOG_URL=https://raw.githubusercontent.com/Energy-Atlas/open-data/<commit>/datasets/weather-availability-catalog/datapackage.json
OPENEPW_CATALOG_SHA256=<SHA-256 of that datapackage.json>
```

The checksum is printed by `openepw catalog export` and can be recomputed with
`sha256sum datapackage.json`. To publish a new catalog, export it from the machine with
the research catalog, add it to open-data as a new version, then update both values:

```bash
openepw --data-root .local/openepw catalog export --out ../open-data/datasets/weather-availability-catalog --package-version YYYY.MM.DD
```

## 2. Create the service

1. Push the deployment branch to GitHub.
2. In Render: **New → Blueprint**, pick the repository and branch. Render reads
   `render.yaml`: one Docker web service `openepw`, Standard plan, a 10 GB disk at
   `/var/data`, health check `/health`, auto-deploy off.
3. Fill in the secrets it asks for. Paste bare values, without quotes:

   | Variable | Value |
   |---|---|
   | `OPENEPW_SITE_PASSWORD` | the password everyone types once per browser |
   | `OPENEPW_NLR_API_KEY`, `OPENEPW_NLR_EMAIL` | NSRDB downloads |
   | `OPENEPW_CDS_KEY` | Copernicus CDS downloads |
   | `OPENAI_API_KEY` | the chat model (without it the offline parser still reads coordinates, years and products) |
   | `OPENEPW_CATALOG_URL`, `OPENEPW_CATALOG_SHA256` | the pinned package link and checksum from step 1 |

4. **Apply**. The first build takes a few minutes. The log should show
   `Catalog installed from the data package`, then `Uvicorn running on http://0.0.0.0:10000`.
5. Open the `onrender.com` address, enter the site password. The browser remembers it for
   30 days (a signed cookie); `/logout` forgets it.

## Running it

- **Deploys are manual** (auto-deploy is off). Each deploy restarts the service; running
  weather jobs resume afterwards, but a Copernicus request waiting in its queue is sent
  again and loses its place.
- **One instance only.** A service with a disk cannot scale out, which suits the app:
  sessions are in SQLite and jobs run inside the process.
- **Changing the password** (edit `OPENEPW_SITE_PASSWORD`, then deploy) signs every browser
  out. Ten wrong passwords from one address block that address for 10 minutes.
- **The catalog installs only when none is active.** To move to a new package version,
  update the two variables, delete `/var/data/openepw/catalog` from the Render shell and
  restart, or run `openepw catalog import --from-package` there.
- **Custom domain:** add it under the service's Settings; Render provides the certificate.
- Everyone who can sign in uses your NLR, Copernicus and OpenAI accounts. The model has
  a local spending stop (`model-usage.json` on the disk, $8 by default).

## Troubleshooting

| Symptom | Cause |
|---|---|
| The service stops at start with "Remote mode requires …" | `OPENEPW_SITE_PASSWORD` is not set |
| The map legend is empty and products show "checked when planning" | no catalog: the package URL is unset or unreachable, or a checksum differs (see the start log) |
| Every message says "could not read" | the OpenAI key is missing or wrong, and the offline parser found nothing in the message |
| The login page keeps coming back | the browser blocks cookies for the site |

## Rehearse locally

```bash
docker build -t openepw:render-test .
docker run -p 18080:10000 -e OPENEPW_SITE_PASSWORD=… \
  -e OPENEPW_CATALOG_URL=file:///pkg/datasets/weather-availability-catalog/datapackage.json \
  -e OPENEPW_CATALOG_SHA256=… -v openepw-data:/var/data -v "$PWD/../open-data:/pkg:ro" openepw:render-test
```

`docker --env-file` keeps quotes around values, so give it a file without quotes.
