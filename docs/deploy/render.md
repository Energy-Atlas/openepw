# Deploying OpenEPW on Render

One Docker web service serves the chat UI and the API from the same address. People sign
in with personal accounts: a Cornell email address and a password chosen from an emailed
link ([ADR 0005](../decisions/0005-accounts.md)); scripts can use a bearer token. Data (Stage 1 catalog, chat sessions, weather jobs, downloads)
lives on a Render persistent disk. Files: [`Dockerfile`](../../Dockerfile),
[`docker/entrypoint.sh`](../../docker/entrypoint.sh), [`render.yaml`](../../render.yaml),
[`src/openepw/deploy.py`](../../src/openepw/deploy.py) (catalog install) and
[`src/openepw/api/accounts.py`](../../src/openepw/api/accounts.py) (accounts).

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

## 2. Set up account email (Resend)

Account links are sent through [Resend](https://resend.com). Resend's shared test sender
(`onboarding@resend.dev`) delivers only to the email address of your own Resend account,
which is enough to try staging yourself. To send to other people, Resend needs a domain
you control and have verified; `cornell.edu` cannot be the sender.

1. In Resend, add a sending domain you control, preferably a subdomain such as
   `mail.example.org`, and add the DNS records it lists at your DNS provider. Wait until
   Resend shows it as verified.
2. Create an API key with sending access only.
3. Choose the sender, for example `OpenEPW <accounts@mail.example.org>`.

Staging and production can share the domain; give each its own API key so one can be
revoked alone.

## 3. Create the services

1. Push `feature/render-deploy` and `deploy/staging` to GitHub.
2. In Render: **New → Blueprint**, pick the repository. Render reads `render.yaml`, which
   defines two Docker web services on the Standard plan, each with its own disk at
   `/var/data` and health check `/health`:

   | Service | Branch | Disk | Deploys |
   |---|---|---|---|
   | `openepw` (production) | `feature/render-deploy` | 10 GB | manual |
   | `openepw-staging` (internal testing) | `deploy/staging` | 5 GB | on every push |

   New features go `feature/...` → `deploy/staging` (tested on staging) → `main` and
   `feature/render-deploy` (deployed to production by hand).
3. Fill in the secrets it asks for, separately for each service. Give staging its own
   Resend key and, where possible, its own provider keys or spending limits, so testing
   does not use up production's. Paste bare values, without quotes:

   | Variable | Value |
   |---|---|
   | `OPENEPW_RESEND_API_KEY` | the Resend key from step 2 |
   | `OPENEPW_MAIL_FROM` | the sender from step 2 |
   | `OPENEPW_BEARER_TOKEN` | optional: a long random token for scripts calling `/v1` |
   | `OPENEPW_NLR_API_KEY`, `OPENEPW_NLR_EMAIL` | NSRDB downloads |
   | `OPENEPW_CDS_KEY` | Copernicus CDS downloads |
   | `OPENAI_API_KEY` | the chat model (without it the offline parser still reads coordinates, years and products) |
   | `OPENEPW_CATALOG_URL`, `OPENEPW_CATALOG_SHA256` | the pinned package link and checksum from step 1 |

   `OPENEPW_ALLOWED_EMAIL_DOMAINS` is set to `cornell.edu` in the Blueprint. Emailed
   links use the service's own `onrender.com` address (Render's `RENDER_EXTERNAL_URL`);
   set `OPENEPW_PUBLIC_URL` once a custom domain is added.

4. **Apply**. The first build takes a few minutes. The log should show
   `Catalog installed from the data package`, then `Uvicorn running on http://0.0.0.0:10000`.
5. Open the `onrender.com` address. Visitors see the globe alone; click anywhere, choose
   **Create an account** and enter your `@cornell.edu` address. The emailed link opens a page to choose a password (at least 12
   characters) and signs you in; the browser stays signed in for 30 days. The button
   above Start over signs out; **Forgot password** emails a new link.

## Running it

- **Deploys are manual** (auto-deploy is off). Each deploy restarts the service; running
  weather jobs resume afterwards, but a Copernicus request waiting in its queue is sent
  again and loses its place.
- **One instance only.** A service with a disk cannot scale out, which suits the app:
  sessions are in SQLite and jobs run inside the process.
- **Accounts.** Anyone with a working `@cornell.edu` inbox can create one. From the
  Render shell, `openepw accounts list` shows them and `openepw accounts disable EMAIL`
  locks one out and ends its sessions (`enable` undoes it). Ten failed sign-ins per
  address or client in 10 minutes are refused; at most three account emails per address
  and 100 overall are sent per hour (counting only emails Resend accepted).
- **Scripts** call `/v1` with `Authorization: Bearer <OPENEPW_BEARER_TOKEN>`.
- **The catalog installs only when none is active.** To move to a new package version,
  update the two variables, delete `/var/data/openepw/catalog` from the Render shell and
  restart, or run `openepw catalog import --from-package` there.
- **Custom domain:** add it under the service's Settings; Render provides the certificate.
- Everyone who can sign in uses your NLR, Copernicus and OpenAI accounts. The model has
  a local spending stop (`model-usage.json` on the disk, $8 by default).

## Troubleshooting

| Symptom | Cause |
|---|---|
| The service stops at start with "Remote mode requires …" | neither `OPENEPW_RESEND_API_KEY` with `OPENEPW_MAIL_FROM` nor `OPENEPW_BEARER_TOKEN` is set |
| "The email service is not answering" on sign-up | Resend refused the message; the service log shows why (`accounts: not sent to … HTTP 4xx …`). Common reasons: the test sender `onboarding@resend.dev` only delivers to your Resend account's own address; the sender's domain is not verified yet; the sender or key was pasted with quotes |
| "A link is on its way" but no email arrives | the log shows `sent to …, id …` (then check spam and Resend's Emails page), `hourly email limit reached` (three per address per hour; wait), or nothing for an unknown address on **Forgot password** |

To test the mail settings directly, open the service's **Shell** in Render and run
`openepw --data-root /var/data/openepw accounts test-mail you@cornell.edu`. It prints
Resend's message id, or Resend's reason for refusing, with the sender and link settings
in use (never the key).
| The map legend is empty and products show "checked when planning" | no catalog: the package URL is unset or unreachable, or a checksum differs (see the start log) |
| Every message says "could not read" | the OpenAI key is missing or wrong, and the offline parser found nothing in the message |
| The login page keeps coming back | the browser blocks cookies for the site |

## Rehearse locally

```bash
docker build -t openepw:render-test .
docker run -p 18080:10000 -e OPENEPW_RESEND_API_KEY=… -e OPENEPW_MAIL_FROM=… \
  -e OPENEPW_PUBLIC_URL=http://localhost:18080 \
  -e OPENEPW_CATALOG_URL=file:///pkg/datasets/weather-availability-catalog/datapackage.json \
  -e OPENEPW_CATALOG_SHA256=… -v openepw-data:/var/data -v "$PWD/../open-data:/pkg:ro" openepw:render-test
```

`docker --env-file` keeps quotes around values, so give it a file without quotes.

Without Resend, run the server directly with `OPENEPW_ACCOUNTS_DEV_MAIL=1` on
`127.0.0.1`: account links are printed to the console instead of emailed. It refuses to
start when listening beyond the local machine.
