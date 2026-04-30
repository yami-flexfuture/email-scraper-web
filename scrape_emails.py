from __future__ import annotations

import argparse
import csv
import html
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

import gspread
import requests
from bs4 import BeautifulSoup
try:
    import dns.resolver
    import dns.exception
except ImportError:  # pragma: no cover
    dns = None

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)
COMMON_TLD_SUFFIXES = {
    "com",
    "org",
    "net",
    "edu",
    "gov",
    "mil",
    "int",
    "io",
    "co",
    "us",
    "uk",
    "ca",
    "au",
    "de",
    "fr",
    "it",
    "es",
    "nl",
    "in",
    "ai",
    "app",
    "biz",
    "info",
    "me",
    "dev",
    "tech",
    "club",
    "online",
    "site",
    "store",
    "agency",
    "media",
    "digital",
    "solutions",
}
TRAILING_DOMAIN_JUNK_HINTS = (
    "or",
    "and",
    "phone",
    "call",
    "contact",
    "email",
    "mobile",
    "whatsapp",
    "support",
    "sales",
    "team",
    "office",
    "info",
    "now",
    "today",
)

EMAIL_STRIP_CHARS = " \t\r\n<>()[]{}\"'.,;:!?"

HIGH_PRIORITY_PREFIXES = (
    "editor",
    "editorial",
    "business",
    "marketing",
    "partnerships",
    "partnership",
    "advertise",
    "advertising",
)
MEDIUM_PRIORITY_PREFIXES = ("contact", "hello", "info", "solutions")
LOW_PRIORITY_PREFIXES = ("admin", "support", "careers", "privacy", "abuse", "noreply", "no-reply")
PRIORITY_SCORE = {"high": 0, "medium": 1, "normal": 2, "low": 3}

CONTACT_PATH_HINTS = (
    "contact",
    "about",
    "team",
    "advertise",
    "write",
    "editor",
    "contribute",
    "guest",
    "partner",
    "advertis",
)

COMMON_CONTACT_PATHS = (
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/team",
    "/write-for-us",
    "/advertise",
    "/advertising",
    "/contribute",
    "/editorial",
    "/guest-post",
    "/partners",
)

MAX_DISCOVERED_INTERNAL_PAGES = 8
PLAYWRIGHT_WAIT_AFTER_LOAD_MS = 1200
PLAYWRIGHT_PAGE_TIMEOUT_MS = 15000
MAX_WORKERS = 5
MAX_RETRIES = 2
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 18
BACKOFF_SECONDS = 0.7
ENABLE_MX_CHECK = False
DNS_TIMEOUT = 3.0
EXPORT_INVALID_EMAILS = False
ENABLE_FILE_LOGGING = False
LOG_FILE_PATH = "scraper.log"
SAVE_DEBUG_HTML = False
DEBUG_HTML_DIR = "debug_html"
MAX_EMAILS_PER_DOMAIN = 3
OBFUSCATED_EMAIL_PATTERN = re.compile(
    r"\b([a-z0-9._%+\-]{1,64})\s*(?:@|\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\s+at\s+)\s*"
    r"([a-z0-9\-]+(?:\s*(?:\.|\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+dot\s+)\s*[a-z0-9\-]+)+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EmailRecord:
    domain: str
    input_url: str
    final_url: str
    page_found: str
    email: str
    email_type: str
    priority: str
    fetch_method: str
    has_contact_form: bool
    contact_form_url: str
    status: str
    error: str
    notes: str
    email_valid: bool
    validation_reason: str


class StructuredScraperLogger:
    def __init__(
        self,
        debug_enabled: bool,
        enable_file_logging: bool = False,
        log_file_path: str = LOG_FILE_PATH,
        save_debug_html: bool = False,
        debug_html_dir: str = DEBUG_HTML_DIR,
    ) -> None:
        self.debug_enabled = debug_enabled
        self.save_debug_html = save_debug_html
        self.debug_html_dir = debug_html_dir
        self.logger = logging.getLogger("outreach_scraper")
        self.logger.handlers.clear()
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(stream_handler)
        if enable_file_logging:
            file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(file_handler)

    def log(self, event: str, **fields: object) -> None:
        payload = {"event": event, **{k: v for k, v in fields.items() if v is not None and v != ""}}
        text = " ".join(f"{k}={payload[k]}" for k in payload)
        self.logger.info(text)

    def debug(self, event: str, **fields: object) -> None:
        if self.debug_enabled:
            self.log(event, **fields)

    def save_html(self, reason_code: str, page_url: str, html_content: str) -> None:
        if not self.save_debug_html or not html_content:
            return
        os.makedirs(self.debug_html_dir, exist_ok=True)
        safe_url = re.sub(r"[^a-zA-Z0-9]+", "_", page_url)[:120]
        filename = f"{reason_code}_{safe_url}.html"
        path = os.path.join(self.debug_html_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
        self.debug("debug_html_saved", reason_code=reason_code, page=page_url, path=path)


SCRAPER_LOGGER: StructuredScraperLogger | None = None


def normalize_website(raw_value: str) -> tuple[str, str] | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.netloc:
        return None
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    if scheme not in {"http", "https"}:
        return None
    normalized_input = f"{scheme}://{parsed.netloc}{parsed.path or ''}"
    if parsed.query:
        normalized_input = f"{normalized_input}?{parsed.query}"
    base_url = f"{scheme}://{parsed.netloc}"
    return normalized_input, base_url


class BaseScraper:
    """Engine contract for future Playwright upgrade."""

    def fetch(self, url: str) -> tuple[str, str]:
        raise NotImplementedError


class FetchError(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class PlaywrightFetcher:
    def __init__(self, timeout_ms: int = PLAYWRIGHT_PAGE_TIMEOUT_MS) -> None:
        self.timeout_ms = timeout_ms

    def fetch(self, url: str) -> tuple[str, str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Playwright is not installed. Install with: pip install playwright "
                "and run: playwright install chromium"
            ) from exc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(PLAYWRIGHT_WAIT_AFTER_LOAD_MS)
                return page.content(), page.url
            finally:
                browser.close()


class RequestsScraper(BaseScraper):
    def __init__(
        self,
        connect_timeout: int = CONNECT_TIMEOUT,
        read_timeout: int = READ_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        backoff_seconds: float = BACKOFF_SECONDS,
        proxy_url: str | None = None,
        proxy_list: list[str] | None = None,
        proxy_on_block_only: bool = False,
        debug: bool = False,
    ) -> None:
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.proxy_url = (proxy_url or "").strip() or None
        self.proxy_list = [p.strip() for p in (proxy_list or []) if p.strip()]
        self.proxy_on_block_only = proxy_on_block_only
        self.debug = debug
        self._proxy_index = 0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            }
        )

    def _next_proxy(self) -> str | None:
        if self.proxy_list:
            proxy = self.proxy_list[self._proxy_index % len(self.proxy_list)]
            self._proxy_index += 1
            return proxy
        return self.proxy_url

    @staticmethod
    def _proxy_dict(proxy: str | None) -> dict[str, str] | None:
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    @staticmethod
    def _is_blocked_response(response: requests.Response) -> bool:
        return response.status_code in (401, 403, 429)

    def _request(self, url: str, proxy: str | None) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=True,
                    proxies=self._proxy_dict(proxy),
                )
                if response.status_code >= 500:
                    if attempt < self.max_retries:
                        log_debug_event(
                            "retry_attempt",
                            page=url,
                            attempt=attempt + 1,
                            reason_code="http_5xx",
                            status_code=response.status_code,
                        )
                        time.sleep(self.backoff_seconds * (attempt + 1))
                        continue
                    raise FetchError("http_5xx", f"{response.status_code} Server Error: {url}")
                return response
            except requests.Timeout as exc:
                last_error = exc
                log_debug_event("timeout_event", page=url, attempt=attempt + 1, reason_code="timeout")
                if attempt < self.max_retries:
                    log_debug_event(
                        "retry_attempt",
                        page=url,
                        attempt=attempt + 1,
                        reason_code="timeout",
                    )
                    time.sleep(self.backoff_seconds * (attempt + 1))
                    continue
                raise FetchError("timeout", str(exc)) from exc
            except requests.exceptions.SSLError as exc:
                raise FetchError("ssl_error", str(exc)) from exc
            except requests.exceptions.ProxyError as exc:
                last_error = exc
                log_debug_event("proxy_failure", page=url, attempt=attempt + 1, reason_code="proxy_failed")
                if attempt < self.max_retries:
                    log_debug_event(
                        "retry_attempt",
                        page=url,
                        attempt=attempt + 1,
                        reason_code="proxy_failed",
                    )
                    time.sleep(self.backoff_seconds * (attempt + 1))
                    continue
                raise FetchError("proxy_error", str(exc)) from exc
            except requests.ConnectionError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    log_debug_event(
                        "retry_attempt",
                        page=url,
                        attempt=attempt + 1,
                        reason_code="connection_error",
                    )
                    time.sleep(self.backoff_seconds * (attempt + 1))
                    continue
                raise FetchError("connection_error", str(exc)) from exc
            except requests.RequestException as exc:
                last_error = exc
                break
        raise FetchError("failed", str(last_error or "request_failed"))

    def fetch(self, url: str) -> tuple[str, str]:
        try:
            direct_response = self._request(url, proxy=None)
        except FetchError as exc:
            if exc.status in {"timeout", "proxy_error", "connection_error", "http_5xx"}:
                direct_response = None
            else:
                raise
        except requests.RequestException:
            direct_response = None

        use_proxy_fallback = bool(self.proxy_url or self.proxy_list)

        if direct_response is None:
            if not use_proxy_fallback:
                raise FetchError("failed", "Direct request failed and no proxy configured.")
            proxy_response = self._request(url, proxy=self._next_proxy())
            response = proxy_response
        elif self.proxy_on_block_only and self._is_blocked_response(direct_response):
            if use_proxy_fallback:
                proxy_response = self._request(url, proxy=self._next_proxy())
                response = proxy_response
            else:
                response = direct_response
        elif not self.proxy_on_block_only and use_proxy_fallback:
            proxy_response = self._request(url, proxy=self._next_proxy())
            response = proxy_response
        else:
            response = direct_response

        if response.status_code == 403:
            raise FetchError("http_403", "403 Forbidden")
        if response.status_code == 404:
            raise FetchError("http_404", "404 Not Found")
        if response.status_code >= 500:
            raise FetchError("http_5xx", f"{response.status_code} Server Error")
        response.raise_for_status()
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            raise FetchError("empty", "Not an HTML page")
        return response.text, response.url


def read_websites(csv_path: str) -> list[str]:
    websites: list[str] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    if not rows:
        return websites

    first_row = [(cell or "").strip() for cell in rows[0]]
    if not first_row or not first_row[0]:
        return websites

    known_headers = {"website", "url", "domain", "site"}
    normalized_first = [cell.lower() for cell in first_row]
    has_header = any(cell in known_headers for cell in normalized_first)

    if has_header:
        header = first_row
        field_map = {name.lower(): idx for idx, name in enumerate(header)}
        candidate_idx = next(
            (field_map[name] for name in ("website", "url", "domain", "site") if name in field_map),
            0,
        )
        for row in rows[1:]:
            if row and len(row) > candidate_idx:
                websites.append((row[candidate_idx] or "").strip())
    else:
        for row in rows:
            if row:
                websites.append((row[0] or "").strip())
    return [w for w in websites if w]


def read_proxy_list(proxy_list_path: str) -> list[str]:
    proxies: list[str] = []
    with open(proxy_list_path, "r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            proxies.append(value)
    return proxies


def extract_domain(website_url: str) -> str:
    netloc = urlparse(website_url).netloc.lower()
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    if ":" in netloc:
        netloc = netloc.split(":", 1)[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.strip(".")


def normalize_email(raw_email: str) -> str:
    return (raw_email or "").strip().strip(EMAIL_STRIP_CHARS).lower()


def trim_attached_domain_suffix(email: str) -> str:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return normalized
    local_part, domain_part = normalized.split("@", 1)
    if not local_part or "." not in domain_part:
        return normalized

    labels = domain_part.split(".")
    last_label = labels[-1]
    if not last_label.isalpha() or len(last_label) < 4:
        return normalized

    max_tld_len = min(len(last_label) - 1, 24)
    for tld_len in range(max_tld_len, 1, -1):
        tld_candidate = last_label[:tld_len]
        trailing = last_label[tld_len:]
        if not trailing or len(trailing) < 2 or not trailing.isalpha():
            continue
        if tld_candidate not in COMMON_TLD_SUFFIXES:
            continue
        if not any(trailing.startswith(hint) for hint in TRAILING_DOMAIN_JUNK_HINTS):
            continue

        cleaned_domain = ".".join(labels[:-1] + [tld_candidate])
        cleaned_email = normalize_email(f"{local_part}@{cleaned_domain}")
        if EMAIL_PATTERN.fullmatch(cleaned_email) and not is_false_positive(cleaned_email):
            return cleaned_email
    return normalized


def clean_email_candidate(raw_candidate: str) -> str:
    normalized = normalize_email(raw_candidate)
    if not normalized:
        return ""
    return trim_attached_domain_suffix(normalized)


def is_false_positive(email: str) -> bool:
    lowered = email.lower()
    if "@" not in lowered:
        return True
    local_part, domain_part = lowered.split("@", 1)
    if not local_part or not domain_part:
        return True
    if not re.fullmatch(r"[a-z0-9._%+\-]+", local_part):
        return True
    if not re.fullmatch(r"[a-z0-9.\-]+\.[a-z]{2,}", domain_part):
        return True
    if ".." in lowered:
        return True
    junk_markers = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
    if any(marker in lowered for marker in junk_markers):
        return True
    return False


def extract_emails_from_text(text: str) -> set[str]:
    emails: set[str] = set()
    for match in EMAIL_PATTERN.finditer(text):
        email = clean_email_candidate(match.group(0))
        if not email or is_false_positive(email):
            continue
        emails.add(email)
    return emails


def normalize_visible_text(text: str) -> str:
    cleaned = (text or "").replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def decode_html_entities(text: str, debug: bool = False) -> str:
    decoded = html.unescape(text)
    if decoded != text:
        debug_log(debug, "html entity decoded")
    return decoded


def recover_obfuscated_emails(text: str, debug: bool = False) -> set[str]:
    emails: set[str] = set()
    decoded_text = decode_html_entities(text, debug=debug)
    for match in OBFUSCATED_EMAIL_PATTERN.finditer(decoded_text):
        raw_match = match.group(0).lower()
        obfuscation_signals = (
            "[at]",
            "(at)",
            "{at}",
            " at ",
            "[dot]",
            "(dot)",
            "{dot}",
            " dot ",
            " @ ",
            " . ",
        )
        if not any(signal in raw_match for signal in obfuscation_signals):
            continue
        local = match.group(1).strip()
        domain_raw = match.group(2)
        domain = re.sub(
            r"\s*(?:\.|\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+dot\s+)\s*",
            ".",
            domain_raw,
            flags=re.IGNORECASE,
        )
        recovered = clean_email_candidate(f"{local}@{domain}")
        if not recovered or is_false_positive(recovered):
            continue
        if EMAIL_PATTERN.fullmatch(recovered):
            emails.add(recovered)
            debug_log(debug, f"obfuscated email recovered: {recovered}")
    return emails


def extract_inline_script_emails(soup: BeautifulSoup, debug: bool = False) -> set[str]:
    emails: set[str] = set()
    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        script_text = script.get_text(" ", strip=True)
        if not script_text:
            continue
        decoded_script = decode_html_entities(script_text, debug=debug)
        direct = extract_emails_from_text(decoded_script)
        obfuscated = recover_obfuscated_emails(decoded_script, debug=debug)
        script_emails = direct | obfuscated
        if script_emails:
            for email in script_emails:
                debug_log(debug, f"inline script email recovered: {email}")
            emails.update(script_emails)
    return emails


def extract_layout_emails(soup: BeautifulSoup, debug: bool = False) -> set[str]:
    emails: set[str] = set()
    # Use spacing-preserving text extraction to avoid merged UI words
    # becoming part of email domains.
    full_text_space = decode_html_entities(soup.get_text(" ", strip=True), debug=debug)
    emails.update(extract_emails_from_text(full_text_space))
    emails.update(recover_obfuscated_emails(full_text_space, debug=debug))

    layout_nodes = []
    layout_nodes.extend(soup.find_all(["footer", "header", "nav", "aside"]))
    layout_nodes.extend(
        soup.select(
            "[id*='footer' i], [class*='footer' i], "
            "[id*='header' i], [class*='header' i], "
            "[id*='global' i], [class*='global' i], "
            "[id*='layout' i], [class*='layout' i]"
        )
    )
    seen_ids: set[int] = set()
    for node in layout_nodes:
        node_id = id(node)
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        block_space = decode_html_entities(node.get_text(" ", strip=True), debug=debug)
        emails.update(extract_emails_from_text(block_space))
        emails.update(recover_obfuscated_emails(block_space, debug=debug))
    return emails


def extract_emails_from_raw_html(html_content: str, debug: bool = False) -> set[str]:
    decoded_html = decode_html_entities(html_content or "", debug=debug)
    normalized_html = normalize_visible_text(decoded_html)
    emails = set()
    emails.update(extract_emails_from_text(decoded_html))
    emails.update(extract_emails_from_text(normalized_html))
    emails.update(recover_obfuscated_emails(decoded_html, debug=debug))
    emails.update(recover_obfuscated_emails(normalized_html, debug=debug))
    return emails


def decode_cloudflare_email(hex_string: str) -> str | None:
    try:
        data = bytes.fromhex(hex_string)
    except ValueError:
        return None
    if not data:
        return None
    key = data[0]
    decoded_chars = [chr(b ^ key) for b in data[1:]]
    return clean_email_candidate("".join(decoded_chars))


def extract_cloudflare_protected_emails(soup: BeautifulSoup, debug: bool = False) -> set[str]:
    emails: set[str] = set()
    for node in soup.select("[data-cfemail]"):
        encoded = (node.get("data-cfemail") or "").strip()
        if not encoded:
            continue
        decoded = decode_cloudflare_email(encoded)
        if not decoded or is_false_positive(decoded):
            continue
        if EMAIL_PATTERN.fullmatch(decoded):
            emails.add(decoded)
            debug_log(debug, f"Cloudflare protected email recovered: {decoded}")
    return emails


def path_contact_intent_score(url: str) -> int:
    path = urlparse(url).path.lower()
    if not path:
        return 0
    strong = ("contact", "contact-us", "get-in-touch", "reach-us", "inquiry")
    medium = ("support", "help", "write", "partner")
    if any(k in path for k in strong):
        return 3
    if any(k in path for k in medium):
        return 1
    return 0


def detect_contact_form_on_page(
    soup: BeautifulSoup,
    page_url: str,
    debug: bool = False,
) -> tuple[bool, int]:
    forms = soup.find_all("form")
    if not forms:
        return False, 0

    best_score = 0
    for form in forms:
        attrs_blob = " ".join(
            [
                form.get("id", ""),
                " ".join(form.get("class", [])) if isinstance(form.get("class"), list) else "",
                form.get("name", ""),
                form.get("action", ""),
                form.get_text(" ", strip=True),
            ]
        ).lower()

        negative_markers = (
            "search",
            "newsletter",
            "subscribe",
            "login",
            "signin",
            "sign-in",
            "register",
            "signup",
            "sign-up",
            "comment",
            "password",
            "captcha",
        )
        if any(marker in attrs_blob for marker in negative_markers):
            debug_log(debug, f"form ignored as non-contact on {page_url}: negative_marker")
            continue

        inputs = form.find_all("input")
        textareas = form.find_all("textarea")
        buttons = form.find_all(["button", "input"])

        field_blob_parts: list[str] = []
        has_password = False
        has_search_type = False
        for field in inputs + textareas:
            field_blob_parts.extend(
                [
                    str(field.get("name", "")),
                    str(field.get("id", "")),
                    str(field.get("placeholder", "")),
                    str(field.get("aria-label", "")),
                ]
            )
            field_type = str(field.get("type", "")).lower()
            if field_type == "password":
                has_password = True
            if field_type == "search":
                has_search_type = True

        if has_password or has_search_type:
            debug_log(debug, f"form ignored as non-contact on {page_url}: auth_or_search_field")
            continue

        field_blob = " ".join(field_blob_parts).lower()
        contact_field_hits = 0
        for marker in ("name", "email", "message", "subject", "phone", "company"):
            if marker in field_blob:
                contact_field_hits += 1

        has_textarea = len(textareas) > 0
        submit_text = " ".join(
            [
                (btn.get_text(" ", strip=True) if btn.name == "button" else str(btn.get("value", "")))
                for btn in buttons
            ]
        ).lower()
        has_submit_intent = any(k in submit_text for k in ("send", "submit", "contact", "message"))
        has_email_input = any(str(inp.get("type", "")).lower() == "email" for inp in inputs) or (
            "email" in field_blob
        )

        page_context = soup.get_text(" ", strip=True).lower()[:1200]
        has_contact_context = any(
            k in page_context for k in ("contact us", "get in touch", "reach us", "inquiry", "send us")
        )

        intent_score = path_contact_intent_score(page_url)
        form_score = 0
        form_score += min(contact_field_hits, 4)
        form_score += 2 if has_textarea else 0
        form_score += 1 if has_submit_intent else 0
        form_score += 1 if has_email_input else 0
        form_score += intent_score
        form_score += 1 if has_contact_context else 0

        is_contact_form = (
            (contact_field_hits >= 3 and (has_textarea or has_submit_intent))
            or (contact_field_hits >= 2 and has_textarea and (intent_score > 0 or has_contact_context))
            or (contact_field_hits >= 2 and has_email_input and intent_score >= 3)
        )

        if is_contact_form:
            best_score = max(best_score, form_score)
            debug_log(debug, f"contact form found on {page_url} (score={form_score})")
        else:
            debug_log(debug, f"form ignored as non-contact on {page_url}: weak_contact_signals")

    return best_score > 0, best_score


def extract_mailto_emails(soup: BeautifulSoup) -> set[str]:
    emails: set[str] = set()
    for anchor in soup.select("a[href^='mailto:']"):
        href = anchor.get("href", "")
        mailto_value = unquote(href.replace("mailto:", "", 1))
        maybe_email = clean_email_candidate(mailto_value.split("?")[0])
        if not maybe_email or is_false_positive(maybe_email):
            continue
        if EMAIL_PATTERN.fullmatch(maybe_email):
            emails.add(maybe_email)
    return emails


def classify_priority(email: str) -> str:
    local_part = email.split("@", 1)[0].lower()
    if local_part.startswith(HIGH_PRIORITY_PREFIXES):
        return "high"
    if local_part.startswith(MEDIUM_PRIORITY_PREFIXES):
        return "medium"
    if local_part.startswith(LOW_PRIORITY_PREFIXES):
        return "low"
    return "normal"


def classify_email_type(email: str) -> str:
    free_domains = {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "aol.com",
        "icloud.com",
        "protonmail.com",
        "pm.me",
        "zoho.com",
    }
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    return "free" if domain in free_domains else "corporate"


def is_valid_domain_format(domain: str) -> bool:
    domain = (domain or "").strip().lower()
    if not domain or "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    if ".." in domain:
        return False
    if not re.fullmatch(r"[a-z0-9.\-]+", domain):
        return False
    labels = domain.split(".")
    if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        return False
    if len(labels[-1]) < 2:
        return False
    return True


def validate_email_address(
    email: str,
    enable_mx_check: bool,
    dns_timeout: float,
    mx_cache: dict[str, tuple[bool, str]],
    debug: bool = False,
) -> tuple[bool, str]:
    normalized = normalize_email(email)
    if not normalized or not EMAIL_PATTERN.fullmatch(normalized):
        log_debug_event("validation_failure", email=email, reason_code="invalid_syntax")
        return False, "invalid_syntax"
    if is_false_positive(normalized):
        log_debug_event("validation_failure", email=email, reason_code="invalid_syntax")
        return False, "invalid_syntax"

    domain = normalized.split("@", 1)[1].lower()
    if not is_valid_domain_format(domain):
        log_debug_event("validation_failure", email=email, reason_code="invalid_domain")
        return False, "invalid_domain"

    if not enable_mx_check:
        log_debug_event("validation_skipped", email=email, reason_code="skipped_mx_check")
        return True, "skipped_mx_check"

    if domain in mx_cache:
        return mx_cache[domain]

    if dns is None:
        log_debug_event("validation_failure", email=email, reason_code="dns_error")
        result = (False, "dns_error")
        mx_cache[domain] = result
        return result

    resolver = dns.resolver.Resolver()
    resolver.timeout = dns_timeout
    resolver.lifetime = dns_timeout
    try:
        answers = resolver.resolve(domain, "MX")
        has_mx = len(list(answers)) > 0
        if has_mx:
            result = (True, "valid")
        else:
            log_debug_event("validation_failure", email=email, reason_code="no_mx")
            result = (False, "no_mx")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        log_debug_event("validation_failure", email=email, reason_code="no_mx")
        result = (False, "no_mx")
    except dns.exception.Timeout:
        log_debug_event("validation_failure", email=email, reason_code="dns_error")
        result = (False, "dns_error")
    except Exception:
        log_debug_event("validation_failure", email=email, reason_code="dns_error")
        result = (False, "dns_error")

    mx_cache[domain] = result
    return result


def apply_email_validation(
    records: list[EmailRecord],
    enable_mx_check: bool,
    dns_timeout: float,
    export_invalid_emails: bool,
    debug: bool = False,
) -> list[EmailRecord]:
    mx_cache: dict[str, tuple[bool, str]] = {}
    validated: list[EmailRecord] = []
    dropped_candidates = 0
    for rec in records:
        if not rec.email:
            validated_rec = EmailRecord(
                domain=rec.domain,
                input_url=rec.input_url,
                final_url=rec.final_url,
                page_found=rec.page_found,
                email=rec.email,
                email_type=rec.email_type,
                priority=rec.priority,
                fetch_method=rec.fetch_method,
                has_contact_form=rec.has_contact_form,
                contact_form_url=rec.contact_form_url,
                status=rec.status,
                error=rec.error,
                notes=rec.notes,
                email_valid=False,
                validation_reason="no_email_found",
            )
            validated.append(validated_rec)
            continue

        is_valid, reason = validate_email_address(
            rec.email,
            enable_mx_check=enable_mx_check,
            dns_timeout=dns_timeout,
            mx_cache=mx_cache,
            debug=debug,
        )
        validated_rec = EmailRecord(
            domain=rec.domain,
            input_url=rec.input_url,
            final_url=rec.final_url,
            page_found=rec.page_found,
            email=rec.email,
            email_type=rec.email_type,
            priority=rec.priority,
            fetch_method=rec.fetch_method,
            has_contact_form=rec.has_contact_form,
            contact_form_url=rec.contact_form_url,
            status=rec.status,
            error=rec.error,
            notes=rec.notes,
            email_valid=is_valid,
            validation_reason=reason if is_valid else reason,
        )
        if is_valid or export_invalid_emails:
            validated.append(validated_rec)
        else:
            dropped_candidates += 1
            log_debug_event(
                "candidate_dropped_after_validation",
                domain=rec.domain,
                email=rec.email,
                reason_code=reason,
            )
    log_debug_event(
        "validation_summary",
        input_candidates=len(records),
        kept=len(validated),
        dropped=dropped_candidates,
    )
    return validated


def rank_email(email: str) -> tuple[int, int, str]:
    priority = classify_priority(email)
    local_part = email.split("@", 1)[0]
    outreach_bonus_prefixes = ("business", "editor", "editorial", "partnership", "partnerships", "advertis")
    outreach_bonus_penalty = 0 if local_part.startswith(outreach_bonus_prefixes) else 1
    local_len_penalty = 0 if len(local_part) <= 20 else 1
    domain_part = email.split("@", 1)[1].lower() if "@" in email else ""
    noisy_suffix_penalty = 1 if domain_part.endswith(".email") else 0
    return (
        PRIORITY_SCORE[priority],
        noisy_suffix_penalty,
        outreach_bonus_penalty,
        local_len_penalty,
        email,
    )


def rank_record_for_domain_limit(rec: EmailRecord) -> tuple[int, int, int, int, str]:
    priority_rank, noisy_suffix_penalty, outreach_bonus_penalty, local_len_penalty, email_sort = rank_email(
        rec.email
    )
    corporate_preference_penalty = 0 if rec.email_type == "corporate" else 1
    return (
        priority_rank,
        corporate_preference_penalty,
        outreach_bonus_penalty,
        noisy_suffix_penalty,
        local_len_penalty,
        email_sort,
    )


def is_useful_contact_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(keyword in path for keyword in CONTACT_PATH_HINTS)


def should_use_playwright_fallback(
    url: str,
    html: str,
    page_text: str,
    found_emails: set[str],
) -> tuple[bool, str]:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    script_count = len(soup.find_all("script"))
    text_len = len(page_text.strip())
    body_text_len = len(body.get_text(" ", strip=True)) if body else 0
    app_shell_markers = (
        'id="app"',
        "id='app'",
        'id="root"',
        "id='root'",
        "__NEXT_DATA__",
        "data-reactroot",
        "ng-app",
    )
    has_app_shell = any(marker in html for marker in app_shell_markers)

    if text_len < 120:
        return True, "very_little_visible_text"
    if not body or body_text_len < 80:
        return True, "empty_or_near_empty_body"
    if script_count >= 12 and text_len < 250:
        return True, "many_scripts_low_text"
    if has_app_shell and text_len < 350:
        return True, "app_shell_markup_detected"
    if is_useful_contact_page(url) and not found_emails and text_len < 600:
        return True, "useful_page_without_content_or_emails"
    return False, "requests_content_looks_ok"


def debug_log(enabled: bool, message: str) -> None:
    if not enabled:
        return
    if SCRAPER_LOGGER is not None:
        SCRAPER_LOGGER.debug("debug", message=message)
    else:
        print(f"[debug] {message}")


def log_event(event: str, **fields: object) -> None:
    if SCRAPER_LOGGER is not None:
        SCRAPER_LOGGER.log(event, **fields)


def log_debug_event(event: str, **fields: object) -> None:
    if SCRAPER_LOGGER is not None:
        SCRAPER_LOGGER.debug(event, **fields)


def reason_code_for_status(status: str) -> str:
    mapping = {
        "http_403": "blocked_403",
        "ssl_error": "ssl_failed",
        "proxy_error": "proxy_failed",
        "browser_fallback_used": "browser_fallback_used",
    }
    return mapping.get(status, status)


def extract_page_emails(
    html_content: str,
    debug: bool = False,
) -> tuple[BeautifulSoup, str, set[str], set[str]]:
    soup = BeautifulSoup(html_content, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    decoded_page_text = decode_html_entities(page_text, debug=debug)
    normalized_page_text = normalize_visible_text(decoded_page_text)
    emails: set[str] = set()
    notes: set[str] = set()

    emails.update(extract_emails_from_text(decoded_page_text))
    emails.update(extract_emails_from_text(normalized_page_text))
    emails.update(extract_mailto_emails(soup))
    emails.update(extract_emails_from_raw_html(html_content, debug=debug))

    obfuscated = recover_obfuscated_emails(decoded_page_text, debug=debug) | recover_obfuscated_emails(
        normalized_page_text,
        debug=debug,
    )
    if obfuscated:
        emails.update(obfuscated)
        notes.add("obfuscated_email_recovered")

    inline_script_emails = extract_inline_script_emails(soup, debug=debug)
    if inline_script_emails:
        emails.update(inline_script_emails)
        notes.add("inline_script_email_recovered")

    layout_emails = extract_layout_emails(soup, debug=debug)
    if layout_emails:
        emails.update(layout_emails)

    cloudflare_emails = extract_cloudflare_protected_emails(soup, debug=debug)
    if cloudflare_emails:
        emails.update(cloudflare_emails)
        notes.add("cloudflare_email_recovered")
    return soup, decoded_page_text, emails, notes


def internal_candidate_links(base_url: str, soup: BeautifulSoup, max_links: int = 6) -> list[str]:
    base_domain = extract_domain(base_url)
    collected: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "javascript:", "tel:", "mailto:")):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if extract_domain(full_url) != base_domain:
            continue
        path_text = (parsed.path or "").lower()
        link_text = anchor.get_text(" ", strip=True).lower()
        composite = f"{path_text} {link_text}"
        if not any(hint in composite for hint in CONTACT_PATH_HINTS):
            continue
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized not in seen:
            seen.add(normalized)
            collected.append(normalized)
        if len(collected) >= max_links:
            break

    return collected


def common_contact_pages(base_url: str) -> list[str]:
    pages: list[str] = []
    seen: set[str] = set()
    for path in COMMON_CONTACT_PATHS:
        full = urljoin(base_url, path)
        parsed = urlparse(full)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized not in seen:
            seen.add(normalized)
            pages.append(normalized)
    return pages


def contact_form_url_score(url: str) -> tuple[int, int, int]:
    lowered = (url or "").lower()
    path = urlparse(lowered).path
    if any(k in path for k in ("/contact", "/contact-us", "/get-in-touch")):
        strong_path_penalty = 0
    else:
        strong_path_penalty = 1
    contact_intent_penalty = -path_contact_intent_score(lowered)
    path_len_penalty = len(path)
    return (strong_path_penalty, contact_intent_penalty, path_len_penalty)


def select_contact_form_records(records: list[EmailRecord]) -> list[EmailRecord]:
    by_domain: dict[str, list[EmailRecord]] = {}
    for rec in records:
        if rec.has_contact_form and rec.contact_form_url:
            by_domain.setdefault(rec.domain.lower(), []).append(rec)

    selected: list[EmailRecord] = []
    for _, domain_records in by_domain.items():
        best_record = min(
            domain_records,
            key=lambda r: (
                contact_form_url_score(r.contact_form_url),
                0 if r.status in {"ok", "browser_fallback_used", "empty"} else 1,
                r.input_url.lower(),
            ),
        )
        selected.append(
            EmailRecord(
                domain=best_record.domain,
                input_url=best_record.input_url,
                final_url=best_record.final_url,
                page_found=best_record.page_found,
                email="",
                email_type="",
                priority="",
                fetch_method=best_record.fetch_method,
                has_contact_form=True,
                contact_form_url=best_record.contact_form_url,
                status=best_record.status,
                error="",
                notes=best_record.notes,
                email_valid=False,
                validation_reason="",
            )
        )

    return sorted(selected, key=lambda r: (r.domain, r.input_url))


def scrape_site(
    base_url: str,
    input_url: str,
    scraper: BaseScraper,
    playwright_fetcher: PlaywrightFetcher | None = None,
    seed_urls: list[str] | None = None,
    debug: bool = False,
) -> list[EmailRecord]:
    domain = extract_domain(base_url)
    log_debug_event("domain_processing_started", domain=domain, input_url=input_url)
    pages_to_visit: list[str] = [base_url]
    queued: set[str] = {base_url}
    if seed_urls:
        for seed_url in seed_urls:
            if extract_domain(seed_url) != domain:
                continue
            if seed_url not in queued:
                queued.add(seed_url)
                pages_to_visit.append(seed_url)
    visited: set[str] = set()
    found: dict[str, EmailRecord] = {}
    best_contact_form_url = ""
    best_contact_form_score = -1

    while pages_to_visit:
        page_url = pages_to_visit.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)

        try:
            html, resolved_url = scraper.fetch(page_url)
            log_debug_event("page_fetched", domain=domain, page=page_url, fetch_method="html")
        except FetchError as exc:
            if page_url == base_url and not found:
                debug_log(debug, f"status assignment for {page_url}: {exc.status}")
                log_event(
                    "page_failed",
                    domain=domain,
                    page=page_url,
                    reason_code=reason_code_for_status(exc.status),
                )
                return [
                    EmailRecord(
                        domain=domain,
                        input_url=input_url,
                        final_url=page_url,
                        page_found=page_url,
                        email="",
                        email_type="",
                        priority="",
                        fetch_method="html",
                        has_contact_form=False,
                        contact_form_url="",
                        status=exc.status,
                        error=str(exc.message),
                        notes="",
                        email_valid=False,
                        validation_reason="",
                    )
                ]
            continue
        except Exception as exc:  # noqa: BLE001
            if page_url == base_url and not found:
                debug_log(debug, f"status assignment for {page_url}: failed")
                log_event("page_failed", domain=domain, page=page_url, reason_code="failed")
                return [
                    EmailRecord(
                        domain=domain,
                        input_url=input_url,
                        final_url=page_url,
                        page_found=page_url,
                        email="",
                        email_type="",
                        priority="",
                        fetch_method="html",
                        has_contact_form=False,
                        contact_form_url="",
                        status="failed",
                        error=str(exc),
                        notes="",
                        email_valid=False,
                        validation_reason="",
                    )
                ]
            continue

        soup, page_text, emails, notes = extract_page_emails(html, debug=debug)
        fetch_method = "html"
        effective_page_url = resolved_url or page_url
        log_debug_event(
            "page_candidate_emails",
            domain=domain,
            page=effective_page_url,
            fetch_method=fetch_method,
            candidates=len(emails),
        )

        if playwright_fetcher is not None:
            should_fallback, reason = should_use_playwright_fallback(
                url=page_url,
                html=html,
                page_text=page_text,
                found_emails=emails,
            )
            if should_fallback:
                debug_log(
                    debug,
                    f"Playwright fallback triggered for {page_url}: {reason}",
                )
                if SCRAPER_LOGGER is not None and reason in {
                    "very_little_visible_text",
                    "empty_or_near_empty_body",
                    "many_scripts_low_text",
                    "app_shell_markup_detected",
                    "useful_page_without_content_or_emails",
                }:
                    SCRAPER_LOGGER.save_html("js_required", page_url, html)
                try:
                    rendered_html, rendered_url = playwright_fetcher.fetch(page_url)
                    rendered_soup, rendered_text, rendered_emails, rendered_notes = extract_page_emails(
                        rendered_html,
                        debug=debug,
                    )
                    if rendered_text or rendered_emails:
                        soup = rendered_soup
                        emails = rendered_emails
                        notes.update(rendered_notes)
                        fetch_method = "browser"
                        effective_page_url = rendered_url or effective_page_url
                        debug_log(debug, f"browser fallback usage for {page_url}")
                        log_event(
                            "browser_fallback_used",
                            domain=domain,
                            page=page_url,
                            reason_code="browser_fallback_used",
                        )
                        notes.add("browser_fallback_used")
                        log_debug_event(
                            "page_candidate_emails",
                            domain=domain,
                            page=effective_page_url,
                            fetch_method=fetch_method,
                            candidates=len(emails),
                        )
                except Exception as exc:  # noqa: BLE001
                    debug_log(
                        debug,
                        f"Playwright fallback failed for {page_url}: {exc}",
                    )
                    if SCRAPER_LOGGER is not None:
                        SCRAPER_LOGGER.save_html("js_required", page_url, html)
            else:
                debug_log(
                    debug,
                    f"HTML-only fetch for {page_url}: {reason}",
                )
        else:
            debug_log(debug, f"HTML-only fetch for {page_url}: browser_fallback_disabled")

        for email in emails:
            if email not in found:
                found[email] = EmailRecord(
                    domain=domain,
                    input_url=input_url,
                    final_url=effective_page_url,
                    page_found=effective_page_url,
                    email=email,
                    email_type=classify_email_type(email),
                    priority=classify_priority(email=email),
                    fetch_method=fetch_method,
                    has_contact_form=False,
                    contact_form_url="",
                    status="browser_fallback_used" if fetch_method == "browser" else "ok",
                    error="",
                    notes=";".join(sorted(notes)),
                    email_valid=False,
                    validation_reason="",
                )
                log_debug_event("email_found", domain=domain, email=email, page=effective_page_url)

        has_contact_form, form_score = detect_contact_form_on_page(soup, page_url=page_url, debug=debug)
        if has_contact_form and form_score > best_contact_form_score:
            best_contact_form_score = form_score
            best_contact_form_url = page_url
            log_debug_event("contact_form_found", domain=domain, page=page_url, score=form_score)

        if page_url == base_url:
            for common_page in common_contact_pages(base_url):
                if common_page not in visited and common_page not in queued:
                    queued.add(common_page)
                    pages_to_visit.append(common_page)
                    log_debug_event("page_queued", domain=domain, page=common_page)
            discovered = internal_candidate_links(
                base_url,
                soup,
                max_links=MAX_DISCOVERED_INTERNAL_PAGES,
            )
            for discovered_page in discovered:
                if discovered_page not in visited and discovered_page not in queued:
                    queued.add(discovered_page)
                    pages_to_visit.append(discovered_page)
                    log_debug_event("page_queued", domain=domain, page=discovered_page)

    if not found:
        return [
            EmailRecord(
                domain=domain,
                input_url=input_url,
                final_url=base_url,
                page_found="",
                email="",
                email_type="",
                priority="",
                fetch_method="html",
                has_contact_form=bool(best_contact_form_url),
                contact_form_url=best_contact_form_url,
                status="empty",
                error="",
                notes="contact_form_only" if best_contact_form_url else "no_email_found",
                email_valid=False,
                validation_reason="",
            )
        ]
    if best_contact_form_url:
        debug_log(debug, f"selected best contact form for domain {domain}: {best_contact_form_url}")

    enriched_records = [
        EmailRecord(
            domain=r.domain,
            input_url=r.input_url,
            final_url=r.final_url,
            page_found=r.page_found,
            email=r.email,
            email_type=r.email_type,
            priority=r.priority,
            fetch_method=r.fetch_method,
            has_contact_form=bool(best_contact_form_url),
            contact_form_url=best_contact_form_url,
            status=r.status,
            error=r.error,
            notes=r.notes,
            email_valid=r.email_valid,
            validation_reason=r.validation_reason,
        )
        for r in found.values()
    ]
    ordered = sorted(enriched_records, key=lambda r: rank_email(r.email))
    log_debug_event("domain_processing_finished", domain=domain, rows=len(ordered))
    return ordered


def dedupe_records(records: Iterable[EmailRecord]) -> list[EmailRecord]:
    deduped: dict[tuple[str, str, str], EmailRecord] = {}
    for rec in records:
        normalized_email = normalize_email(rec.email)
        if normalized_email.endswith(".email"):
            base_email = normalized_email[: -len(".email")]
            if EMAIL_PATTERN.fullmatch(base_email):
                continue
        key = (rec.domain.lower(), rec.input_url.strip().lower(), normalized_email)
        if key not in deduped:
            deduped[key] = rec
    result = list(deduped.values())

    grouped: dict[str, list[EmailRecord]] = {}
    for record in result:
        grouped.setdefault(record.domain.lower(), []).append(record)

    final_records: list[EmailRecord] = []
    for _, domain_records in grouped.items():
        successful = [r for r in domain_records if r.email]
        failed = [r for r in domain_records if not r.email]
        final_records.extend(successful or failed[:1])

    return sorted(final_records, key=lambda r: (r.domain, r.input_url, r.email))


def keep_top_emails_per_domain(
    records: list[EmailRecord],
    max_emails_per_domain: int = MAX_EMAILS_PER_DOMAIN,
) -> list[EmailRecord]:
    by_domain: dict[str, list[EmailRecord]] = {}
    for rec in records:
        by_domain.setdefault(rec.domain.lower(), []).append(rec)

    selected: list[EmailRecord] = []
    for _, domain_records in by_domain.items():
        with_email = [r for r in domain_records if r.email]
        without_email = [r for r in domain_records if not r.email]
        if not with_email:
            selected.extend(without_email[:1])
            continue

        best_per_email: dict[str, EmailRecord] = {}
        for rec in with_email:
            email_key = normalize_email(rec.email)
            existing = best_per_email.get(email_key)
            if existing is None or rank_record_for_domain_limit(rec) < rank_record_for_domain_limit(existing):
                best_per_email[email_key] = rec

        ranked = sorted(best_per_email.values(), key=rank_record_for_domain_limit)
        selected.extend(ranked[:max_emails_per_domain])

    return sorted(selected, key=lambda r: (r.domain, r.input_url, r.email))


def write_results(output_csv: str, records: list[EmailRecord]) -> None:
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "domain",
                "input_url",
                "final_url",
                "page_found",
                "email",
                "email_type",
                "priority",
                "has_contact_form",
                "contact_form_url",
                "fetch_method",
                "status",
                "notes",
                "email_valid",
                "validation_reason",
            ],
        )
        writer.writeheader()
        for rec in records:
            writer.writerow(
                {
                    "domain": rec.domain,
                    "input_url": rec.input_url,
                    "final_url": rec.final_url,
                    "page_found": rec.page_found,
                    "email": rec.email,
                    "email_type": rec.email_type,
                    "priority": rec.priority,
                    "has_contact_form": str(rec.has_contact_form).lower(),
                    "contact_form_url": rec.contact_form_url,
                    "fetch_method": rec.fetch_method,
                    "status": rec.status,
                    "notes": rec.notes,
                    "email_valid": str(rec.email_valid).lower(),
                    "validation_reason": rec.validation_reason,
                }
            )


def write_contact_forms_results(output_csv: str, records: list[EmailRecord]) -> None:
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "domain",
                "input_url",
                "final_url",
                "has_contact_form",
                "contact_form_url",
                "status",
                "notes",
            ],
        )
        writer.writeheader()
        for rec in records:
            writer.writerow(
                {
                    "domain": rec.domain,
                    "input_url": rec.input_url,
                    "final_url": rec.final_url,
                    "has_contact_form": str(rec.has_contact_form).lower(),
                    "contact_form_url": rec.contact_form_url,
                    "status": rec.status,
                    "notes": rec.notes,
                }
            )


def push_to_google_sheets(
    records: list[EmailRecord],
    creds_file: str,
    sheet_id: str,
    worksheet_name: str,
) -> int:
    if not records:
        return 0

    client = gspread.service_account(filename=creds_file)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.worksheet(worksheet_name)

    expected_headers = [
        "domain",
        "input_url",
        "final_url",
        "page_found",
        "email",
        "email_type",
        "priority",
        "has_contact_form",
        "contact_form_url",
        "fetch_method",
        "status",
        "notes",
        "email_valid",
        "validation_reason",
        "run_at",
    ]

    existing_values = worksheet.get_all_values()
    if not existing_values:
        worksheet.append_row(expected_headers, value_input_option="RAW")
        existing_values = [expected_headers]

    headers = existing_values[0]
    header_map = {name: idx for idx, name in enumerate(headers)}
    for header in expected_headers:
        if header not in header_map:
            raise ValueError(
                f"Worksheet '{worksheet_name}' is missing required column: {header}"
            )

    existing_keys: set[tuple[str, str, str]] = set()
    for row in existing_values[1:]:
        website = (
            row[header_map["domain"]].strip().lower()
            if len(row) > header_map["domain"]
            else ""
        )
        email = (
            row[header_map["email"]].strip().lower()
            if len(row) > header_map["email"]
            else ""
        )
        input_url = (
            row[header_map["input_url"]].strip().lower()
            if len(row) > header_map["input_url"]
            else ""
        )
        if website and email:
            existing_keys.add((website, input_url, email))

    now_iso = datetime.now(timezone.utc).isoformat()
    rows_to_append: list[list[str]] = []

    for rec in records:
        website_key = rec.domain.strip().lower()
        email_key = rec.email.strip().lower()
        input_key = rec.input_url.strip().lower()
        dedupe_key = (website_key, input_key, email_key)
        if email_key and dedupe_key in existing_keys:
            continue
        if email_key:
            existing_keys.add(dedupe_key)
        rows_to_append.append(
            [
                rec.domain,
                rec.input_url,
                rec.final_url,
                rec.page_found,
                rec.email,
                rec.email_type,
                rec.priority,
                str(rec.has_contact_form).lower(),
                rec.contact_form_url,
                rec.fetch_method,
                rec.status,
                rec.notes,
                str(rec.email_valid).lower(),
                rec.validation_reason,
                now_iso,
            ]
        )

    if not rows_to_append:
        return 0

    worksheet.append_rows(rows_to_append, value_input_option="RAW")
    return len(rows_to_append)


def run(
    input_csv: str,
    output_csv: str,
    contact_forms_output_csv: str,
    timeout: int,
    max_workers: int,
    max_retries: int,
    connect_timeout: int,
    read_timeout: int,
    backoff_seconds: float,
    enable_mx_check: bool,
    dns_timeout: float,
    export_invalid_emails: bool,
    enable_file_logging: bool,
    log_file_path: str,
    save_debug_html: bool,
    debug_html_dir: str,
    proxy_url: str | None,
    proxy_list_file: str | None,
    proxy_on_block_only: bool,
    enable_playwright_fallback: bool,
    debug: bool,
    push_to_sheets_enabled: bool,
    google_sheet_id: str | None,
    google_worksheet: str,
    google_creds_file: str | None,
    max_emails_per_domain: int,
) -> None:
    global SCRAPER_LOGGER
    SCRAPER_LOGGER = StructuredScraperLogger(
        debug_enabled=debug,
        enable_file_logging=enable_file_logging,
        log_file_path=log_file_path,
        save_debug_html=save_debug_html,
        debug_html_dir=debug_html_dir,
    )
    proxy_list = read_proxy_list(proxy_list_file) if proxy_list_file else []
    if proxy_list_file and not proxy_list:
        raise ValueError("Proxy list file is empty.")

    websites = read_websites(input_csv)
    if not websites:
        raise ValueError("Input CSV has no websites to process.")

    all_records: list[EmailRecord] = []
    invalid_records: list[EmailRecord] = []
    domain_groups: dict[str, dict[str, object]] = {}
    for raw_site in websites:
        normalized = normalize_website(raw_site)
        if not normalized:
            invalid_records.append(
                EmailRecord(
                    domain=raw_site,
                    input_url=raw_site,
                    final_url="",
                    page_found="",
                    email="",
                    email_type="",
                    priority="",
                    fetch_method="html",
                    has_contact_form=False,
                    contact_form_url="",
                    status="invalid_website",
                    error="Could not parse website URL/domain.",
                    notes="",
                    email_valid=False,
                    validation_reason="",
                )
            )
            continue
        normalized_input_url, base_url = normalized
        domain = extract_domain(base_url)
        group = domain_groups.setdefault(
            domain,
            {
                "domain": domain,
                "base_url": base_url,
                "input_entries": [],
                "seed_urls": set(),
            },
        )
        # Prefer https base URL when mixed schemes are supplied.
        if str(group["base_url"]).startswith("http://") and base_url.startswith("https://"):
            group["base_url"] = base_url
        input_entries = group["input_entries"]
        if isinstance(input_entries, list):
            input_entries.append((raw_site, normalized_input_url))
        seed_urls = group["seed_urls"]
        if isinstance(seed_urls, set):
            seed_urls.add(normalized_input_url)
    log_event("run_started", domains=len(domain_groups), invalid_inputs=len(invalid_records))

    def process_domain(group: dict[str, object]) -> list[EmailRecord]:
        base_url = str(group["base_url"])
        input_entries = group.get("input_entries", [])
        seed_urls_set = group.get("seed_urls", set())
        if not isinstance(input_entries, list) or not input_entries:
            return []
        if not isinstance(seed_urls_set, set):
            seed_urls_set = set()
        representative_input = str(input_entries[0][0])
        seed_urls = sorted(str(url) for url in seed_urls_set)
        scraper = RequestsScraper(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            proxy_url=proxy_url,
            proxy_list=proxy_list,
            proxy_on_block_only=proxy_on_block_only,
            debug=debug,
        )
        playwright_fetcher = PlaywrightFetcher(timeout_ms=timeout * 1000) if enable_playwright_fallback else None
        domain_records = scrape_site(
            base_url=base_url,
            input_url=representative_input,
            scraper=scraper,
            playwright_fetcher=playwright_fetcher,
            seed_urls=seed_urls,
            debug=debug,
        )
        expanded_records: list[EmailRecord] = []
        for raw_input, _ in input_entries:
            for rec in domain_records:
                expanded_records.append(
                    EmailRecord(
                        domain=rec.domain,
                        input_url=str(raw_input),
                        final_url=rec.final_url,
                        page_found=rec.page_found,
                        email=rec.email,
                        email_type=rec.email_type,
                        priority=rec.priority,
                        fetch_method=rec.fetch_method,
                        has_contact_form=rec.has_contact_form,
                        contact_form_url=rec.contact_form_url,
                        status=rec.status,
                        error=rec.error,
                        notes=rec.notes,
                        email_valid=rec.email_valid,
                        validation_reason=rec.validation_reason,
                    )
                )
        return expanded_records

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_map = {
            executor.submit(process_domain, group): str(group_name)
            for group_name, group in domain_groups.items()
        }
        for future in as_completed(future_map):
            domain_name = future_map[future]
            try:
                all_records.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                debug_log(debug, f"status assignment for {domain_name}: failed")
                failed_group = domain_groups.get(domain_name, {})
                input_entries = failed_group.get("input_entries", [])
                if not isinstance(input_entries, list):
                    input_entries = []
                for raw_input, _ in input_entries:
                    all_records.append(
                        EmailRecord(
                            domain=str(domain_name),
                            input_url=str(raw_input),
                            final_url=str(failed_group.get("base_url", "")),
                            page_found="",
                            email="",
                            email_type="",
                            priority="",
                            fetch_method="html",
                            has_contact_form=False,
                            contact_form_url="",
                            status="failed",
                            error=str(exc),
                            notes="",
                            email_valid=False,
                            validation_reason="",
                        )
                    )
    all_records.extend(invalid_records)

    output_records = dedupe_records(all_records)
    output_records = apply_email_validation(
        output_records,
        enable_mx_check=enable_mx_check,
        dns_timeout=dns_timeout,
        export_invalid_emails=export_invalid_emails,
        debug=debug,
    )
    contact_form_records = select_contact_form_records(output_records)
    output_records = keep_top_emails_per_domain(
        output_records,
        max_emails_per_domain=max(1, max_emails_per_domain),
    )
    write_results(output_csv, output_records)
    write_contact_forms_results(contact_forms_output_csv, contact_form_records)
    if push_to_sheets_enabled:
        if not google_sheet_id:
            raise ValueError("--google-sheet-id is required when --push-to-sheets is enabled.")
        if not google_creds_file:
            raise ValueError(
                "--google-creds-file is required when --push-to-sheets is enabled."
            )
        appended_count = push_to_google_sheets(
            records=output_records,
            creds_file=google_creds_file,
            sheet_id=google_sheet_id,
            worksheet_name=google_worksheet,
        )
        print(
            f"Google Sheets sync complete. Appended {appended_count} new rows to '{google_worksheet}'."
        )
    log_event(
        "run_finished",
        output_rows=len(output_records),
        output_csv=output_csv,
        contact_form_rows=len(contact_form_records),
        contact_forms_output_csv=contact_forms_output_csv,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract emails from homepage + contact/about pages and export CSV."
    )
    parser.add_argument("--input", required=True, help="Input CSV path with website column.")
    parser.add_argument("--output", default="emails_output.csv", help="Output CSV path.")
    parser.add_argument(
        "--contact-forms-output",
        default="contact_forms_output.csv",
        help="Output CSV path for domains where contact forms were found.",
    )
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds.")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS, help="Max domains processed concurrently.")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES, help="Max retries for transient request failures.")
    parser.add_argument("--connect-timeout", type=int, default=CONNECT_TIMEOUT, help="Connect timeout in seconds.")
    parser.add_argument("--read-timeout", type=int, default=READ_TIMEOUT, help="Read timeout in seconds.")
    parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=BACKOFF_SECONDS,
        help="Base retry backoff seconds.",
    )
    parser.add_argument(
        "--enable-mx-check",
        action="store_true",
        default=ENABLE_MX_CHECK,
        help="Enable MX DNS checks for email domain validation.",
    )
    parser.add_argument(
        "--dns-timeout",
        type=float,
        default=DNS_TIMEOUT,
        help="DNS timeout in seconds for MX lookups.",
    )
    parser.add_argument(
        "--export-invalid-emails",
        action="store_true",
        default=EXPORT_INVALID_EMAILS,
        help="Include invalid emails in output with validation flags.",
    )
    parser.add_argument(
        "--enable-file-logging",
        action="store_true",
        default=ENABLE_FILE_LOGGING,
        help="Enable structured file logging.",
    )
    parser.add_argument(
        "--log-file-path",
        default=LOG_FILE_PATH,
        help="Path to structured log file.",
    )
    parser.add_argument(
        "--save-debug-html",
        action="store_true",
        default=SAVE_DEBUG_HTML,
        help="Save HTML snapshots for selected debug/failure cases.",
    )
    parser.add_argument(
        "--debug-html-dir",
        default=DEBUG_HTML_DIR,
        help="Directory for saved debug HTML files.",
    )
    parser.add_argument(
        "--proxy-url",
        default="",
        help="Single proxy URL, e.g. http://user:pass@host:port",
    )
    parser.add_argument(
        "--proxy-list-file",
        default="",
        help="Text file with one proxy URL per line.",
    )
    parser.add_argument(
        "--proxy-on-block-only",
        action="store_true",
        help="Use proxy only when direct request gets blocked (401/403/429) or fails.",
    )
    parser.add_argument(
        "--disable-browser-fallback",
        action="store_true",
        help="Disable browser-rendered fallback and use HTML-only mode.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print lightweight debug logs for fetch method decisions.",
    )
    parser.add_argument(
        "--push-to-sheets",
        action="store_true",
        help="Push results to Google Sheets after CSV export.",
    )
    parser.add_argument(
        "--google-sheet-id",
        default="",
        help="Google Sheets document ID.",
    )
    parser.add_argument(
        "--google-worksheet",
        default="emails",
        help="Worksheet tab name inside the Google Sheet.",
    )
    parser.add_argument(
        "--google-creds-file",
        default="",
        help="Path to Google service account credentials JSON file.",
    )
    parser.add_argument(
        "--max-emails-per-domain",
        type=int,
        default=MAX_EMAILS_PER_DOMAIN,
        help="Maximum number of emails to keep per domain in final output.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        run(
            input_csv=args.input,
            output_csv=args.output,
            contact_forms_output_csv=args.contact_forms_output,
            timeout=args.timeout,
            max_workers=args.max_workers,
            max_retries=args.max_retries,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            backoff_seconds=args.backoff_seconds,
            enable_mx_check=args.enable_mx_check,
            dns_timeout=args.dns_timeout,
            export_invalid_emails=args.export_invalid_emails,
            enable_file_logging=args.enable_file_logging,
            log_file_path=args.log_file_path,
            save_debug_html=args.save_debug_html,
            debug_html_dir=args.debug_html_dir,
            proxy_url=(args.proxy_url or "").strip() or None,
            proxy_list_file=(args.proxy_list_file or "").strip() or None,
            proxy_on_block_only=args.proxy_on_block_only,
            enable_playwright_fallback=not args.disable_browser_fallback,
            debug=args.debug,
            push_to_sheets_enabled=args.push_to_sheets,
            google_sheet_id=(args.google_sheet_id or "").strip() or None,
            google_worksheet=(args.google_worksheet or "").strip() or "emails",
            google_creds_file=(args.google_creds_file or "").strip() or None,
            max_emails_per_domain=max(1, args.max_emails_per_domain),
        )
        print(f"Done. Results written to {args.output}")
    except Exception as exc:  # noqa: BLE001
        print(f"Failed: {exc}")
        raise SystemExit(1)
