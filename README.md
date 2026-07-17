# FBP Bills

Local/self-hosted reimbursement document generator for controlled, user-verified monthly documents:

- Internet invoice
- Driver salary receipt
- Book receipt
- Fuel logbook, fuel receipt PDFs, and merged fuel bill packet

The app is inspired by common form-to-PDF bill generators. Templates are local Jinja2 files and every generated version stores the source input JSON. Two inputs are intentionally fetched live from the internet on every generation rather than being cached indefinitely: book receipt metadata (OpenLibrary, a new title on every generate) and fuel prices (Goodreturns, fetched at least once per city/date and then reused for the rest of that month). No other bill type calls or scrapes a website.

## Compliance Boundary

This tool automates formatting, self-declarations, reimbursement summaries, and legitimate user-provided billing data. It does not verify third-party transactions and should not be used to misrepresent actual expenses. Fuel prices, book prices, provider details, and receipt numbers must come from user-provided or verified records; the automatic OpenLibrary/Goodreturns lookups are a starting point, not a substitute for verifying the final figures against an actual receipt. Generated versions keep the input snapshot and audit metadata in SQLite.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.main init-db
```

## Run The Web App

```bash
.venv/bin/python -m uvicorn app.web:app --reload
```

Open `http://127.0.0.1:8000`.

On a fresh installation, the app redirects to **Profile**. No generator,
document history, output file, or bundle route is available until every
required profile field has been saved. The new database contains no employee,
account, route, pump, driver, or book-store information.

Pages included:

- Dashboard
- Profile settings
- Generate Internet Bill
- Generate Driver Salary Receipt
- Generate Book Receipt
- Generate Fuel Bills
- Generated documents/version history
- Side-by-side structured forms and live previews
- Profile-backed readiness checks before generation

## CLI

```bash
.venv/bin/python -m app.main init-db
.venv/bin/python -m app.main generate --month 2026-06 --type internet
.venv/bin/python -m app.main generate --month 2026-06 --type all
.venv/bin/python -m app.main preview --month 2026-06 --type fuel
.venv/bin/python -m app.main export-bundle --month 2026-06
.venv/bin/python -m app.main visual-audit --month 2026-06
.venv/bin/python -m app.main prepare-share
```

Use `--input-json path/to/payload.json` with `generate` to supply explicit
data instead of the saved profile defaults.

## Sharing The Project Safely

Do not copy the working directory directly. A working installation contains
private data in:

- `data/fbp_bills.sqlite3`
- `output/`
- `assets/` when signatures, stamps, receipts, or account-specific images have been added
- `original-reference-docs/`
- `tmp/`

Create a sanitized source archive instead:

```bash
.venv/bin/python -m app.main prepare-share
```

The command writes `dist/fbp-bills-share.zip`. It excludes the database,
generated documents, uploaded/local assets, reference PDFs, temporary visual
audits, virtual environment, and existing archives. It includes empty
`data/`, `output/`, and `assets/` placeholders so the recipient starts with
first-time Profile setup.

An alternative output path can be supplied:

```bash
.venv/bin/python -m app.main prepare-share --output ~/Desktop/fbp-bills-share.zip
```

## Output

Generated files are written under:

```text
output/
  2026-06/
    Internet Invoice Jun 2026.pdf
    Driver Salary Jun 2026.pdf
    Book Invoice Jun 2026.pdf
    Fuel Logbook Jun 2026.xlsx
    Fuel Logbook Jun 2026.pdf
    Fuel Bills Jun 2026.pdf
    reimbursement_bundle_Jun_2026.zip
```

Fuel receipt PDFs are also stored in `output/YYYY-MM/fuel_receipts/` and merged after the logbook in the final fuel PDF.

## Profile Data

Edit defaults in the web UI at `/profile`. The profile stores employee name/code, address, optional contact details, vehicle number, default city pair, pump details, internet provider/account number, driver name/salary, book defaults, and driver stamp/signature placement.

Defaults are copied into each bill payload and can be overridden in structured forms. Generated versions keep the normalized JSON snapshot and a field audit summary in SQLite.

The profile is local installation data and is intentionally omitted from
sanitized share archives.

## Assets

Optional assets such as signatures or stamp images can be placed in `assets/` or uploaded from the Driver generator. Driver stamp/signature placement can be calibrated from Profile and overridden for a single run.

Recommended local asset layout:

```text
assets/
  logos/
    internet/
      airtel.png
    fuel/
      bharat-petroleum.png
      indian-oil.png
  fuel-receipts/
    receipt-01.jpg
  stamps/
  signatures/
```

Internet bills accept `provider_logo_path`, for example `assets/logos/internet/airtel.png`.

Fuel rows accept `vendor_logo_path`, for example `assets/logos/fuel/bharat-petroleum.png`.

## Fuel Data

Fuel rows are normally generated from the saved profile, working-day schedule, and fetched/stored fuel prices. If a month needs manual correction, open the Fuel generator, expand **Manual fuel rows**, and edit the structured row forms. CSV is still available internally for CLI/service usage. Required CSV columns:

```text
date,from_city,to_city,km_travelled,purpose,fuel_city,litres,petrol_price_per_litre,vendor,vendor_logo_path,pump_address,receipt_number,price_source,actual_receipt_image_path
```

The app never silently invents petrol prices. If `petrol_price_per_litre` is blank, it fetches the petrol price from Goodreturns for the row's `fuel_city`. The first lookup for a given city/date in a calendar month hits Goodreturns live and stores the fetched value and source URL in `fuel_price_sources`; every later generation that month for the same city/date reuses that stored row instead of re-fetching. A new month always triggers at least one fresh live fetch per city/date. If you enter a price manually, `price_source` is required, such as `manual: June 2026 Delhi price record` or a stored source URL.

Goodreturns city URLs are generated as `https://www.goodreturns.in/petrol-price-in-{city}.html`; `Delhi` is mapped to `new-delhi`. If a city page cannot be fetched or parsed at all, generation fails instead of guessing. Goodreturns only publishes a rolling ~10-day price history, so a travel date older than that window (common for early-month dates once you are generating mid-month) has no exact entry. In that case the app degrades gracefully: it uses the closest rate still published and flags the stored `price_source` as approximate (`exact rate for <date> unavailable ...; used closest published rate <date> (<n> day gap)`), never silently presenting it as an exact match. The approximation is capped at 45 days — beyond that (e.g. regenerating a months-old bill) it errors and you must supply a manual price. Replace an approximate rate with a manual price whenever you need the exact day's figure.

To include actual fuel receipt scans, place image files under `assets/fuel-receipts/` and set `actual_receipt_image_path` on each matching row, for example `assets/fuel-receipts/receipt-01.jpg`. When this field is present, the merged fuel PDF uses the user-provided actual receipt image page for that row instead of the local synthetic receipt template.

The app does not scrape or copy petrol-pump logos, revenue stamp images, or third-party visual assets from freeforonline.com or any other generator. If a logo, stamp, signature, or receipt image is needed, provide a verified file you are allowed to use and keep the source record.

## Visual QA

Render a contact sheet and bounding-box report for the generated monthly PDFs:

```bash
.venv/bin/python -m app.main visual-audit --month 2026-06
```

This writes `output/YYYY-MM/visual_audit/generated_pages.png` and `visual_report.json`. Use it after template changes to catch page-size, spacing, and layout drift against the local reference PDFs.

## Adding A Bill Type

Each bill type is defined in `app/registry.py` with:

- Pydantic model name
- Jinja2 template
- field metadata
- output filename pattern

Add a Pydantic model in `app/models.py`, calculations if needed, a template in `app/templates/bills/`, and a renderer branch in `app/services.py`.

## Tests

```bash
.venv/bin/python -m pytest
```

Coverage includes date/month formatting, filename generation, tax calculations, fuel totals, book lookup parsing, PDF generation smoke test, and SQLite version history creation.

## Reference Research

The public freeforonline.com pages were inspected only for high-level categories, form-oriented workflow, visible fields, and layout behavior. The app uses local templates and does not copy website assets, logos, proprietary code, or depend on that site at runtime.

## Limitations

- Templates are close v1 layouts, not pixel-perfect copies of the reference PDFs.
- Book metadata (title/author/publisher/description) is fetched fresh from OpenLibrary on every generate; price must still be user-provided or confirmed.
- Goodreturns' rolling ~10-day price history means fuel prices for older travel dates within the current month have no exact published entry. The app falls back to the nearest available rate and marks the stored `price_source` as approximate; enter that day's price manually if you need the exact figure.
- No authentication is implemented in v1, but the database has user/profile tables and the service layer is multi-user-ready.
- Copying a live working directory can expose its SQLite database and generated files. Use `prepare-share` for distribution.
- Exact output depends on provided local assets and profile defaults; use visual-audit after changing templates or calibration values.
