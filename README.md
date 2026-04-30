# Email Scraper Tool (HTML + Browser Fallback)

This tool:
- reads websites from a CSV
- visits each homepage
- discovers and visits likely contact/about pages
- extracts emails
- removes duplicates
- classifies email type (`editor`, `marketing`, `generic`)
- exports results to CSV

It uses fast HTML requests (`requests + BeautifulSoup`) first, then falls back to browser-rendered fetch (`Playwright`) only when a page looks incomplete or too empty.

## File placement

Place these files in the same project folder:
- `scrape_emails.py`
- `requirements.txt`
- your input file (for example: `input_websites.csv`)

## Input CSV format

Use one of these header names:
- `website`
- `url`
- `domain`
- `site`

Example:

```csv
website
example.com
https://example.org
news-site.net
```

## Setup

1. Create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Install Playwright browser (required for browser fallback):

```powershell
python -m playwright install chromium
```

## Run

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv
```

Run with separate contact forms export:

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --contact-forms-output contact_forms_output.csv
```

## Simple web UI

You can run a local web interface where a user uploads/pastes websites and downloads CSV results.

```powershell
streamlit run web_app.py
```

Web app output files:
- `emails_output.csv`
- `contact_forms_output.csv`

### Deploy to Streamlit Community Cloud (free)

1. Push this project to a GitHub repository.
2. Open [Streamlit Community Cloud](https://share.streamlit.io/).
3. Click **New app** and select your repository.
4. Set **Main file path** to:
   - `web_app.py`
5. Deploy.

Notes for free cloud:
- Keep **browser fallback disabled** in the UI (default ON for "disable browser fallback").
- For large CSV inputs, runtime and memory limits may apply on free tier.

Optional timeout:

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --timeout 20
```

Run with default browser fallback + debug logs:

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --debug
```

Optional: disable browser fallback (HTML-only):

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --disable-browser-fallback
```

Tune speed/stability for larger batches:

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --max-workers 5 --max-retries 2 --connect-timeout 8 --read-timeout 18 --backoff-seconds 0.7
```

Use a single proxy for all requests:

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --proxy-url "http://user:pass@host:port"
```

Use rotating proxies from file (one proxy per line):

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --proxy-list-file proxies.txt
```

Recommended: only use proxy when blocked (`401/403/429`) or direct request fails:

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --proxy-list-file proxies.txt --proxy-on-block-only
```

Push results to Google Sheets after CSV export:

```powershell
python scrape_emails.py --input input_websites.csv --output emails_output.csv --push-to-sheets --google-sheet-id "YOUR_SHEET_ID" --google-worksheet "emails" --google-creds-file "google-service-account.json"
```

## Output CSV columns

- `domain`: normalized website domain processed
- `email`: extracted email
- `priority`: `high`, `medium`, `normal`, or `low`
- `source_page`: page where the email was found
- `fetch_method`: `html` or `browser`
- `has_contact_form`: `true` or `false`
- `contact_form_url`: best contact form page URL for the domain
- `status`: `ok`, `no_email_found`, `fetch_error`, or `invalid_website`
- `error`: error details when status is not `ok`

## Browser fallback logic

Playwright is only used for suspicious pages, for example:
- very little visible text
- near-empty body
- many script tags with very low text
- app-shell markup (`id="app"`, `id="root"`, `__NEXT_DATA__`)
- useful contact page path with no extractable content/emails

## Google Sheets setup

1. Create a Google Cloud service account and download the JSON key.
2. Share your target Google Sheet with the service account email (Editor access).
3. Create worksheet tab (default `emails`) with these headers in row 1:
   - `domain,email,priority,source_page,fetch_method,status,error,run_at`
4. Run with `--push-to-sheets` and provide `--google-sheet-id` + `--google-creds-file`.
