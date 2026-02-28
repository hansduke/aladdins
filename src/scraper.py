"""
Scraper for https://leginfo.legislature.ca.gov/

Searches for CA public safety bills by keyword, then fetches status,
legislative digest (summary), history, and committee analyses for each.
"""

import re
import time
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .config import BASE_LEGINFO_URL, SESSION_YEAR, CATEGORY_KEYWORDS, DEAD_STATUSES

logger = logging.getLogger(__name__)

SEARCH_URL = f"{BASE_LEGINFO_URL}/faces/billSearchClient.xhtml"


class LegInfoScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, url, **kwargs):
        for attempt in range(4):
            try:
                resp = self.session.get(url, timeout=30, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as exc:
                if attempt == 3:
                    raise
                wait = 2 ** attempt
                logger.warning(f"GET {url} failed ({exc}), retrying in {wait}s")
                time.sleep(wait)

    def _post(self, url, data, **kwargs):
        for attempt in range(4):
            try:
                resp = self.session.post(url, data=data, timeout=30, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as exc:
                if attempt == 3:
                    raise
                wait = 2 ** attempt
                logger.warning(f"POST {url} failed ({exc}), retrying in {wait}s")
                time.sleep(wait)

    def _extract_form_data(self, soup):
        """Return (form_data_dict, action_url) from the first form on the page."""
        form = soup.find("form")
        if not form:
            return {}, SEARCH_URL
        data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                data[name] = inp.get("value", "")
        for sel in form.find_all("select"):
            name = sel.get("name")
            if name:
                chosen = sel.find("option", selected=True)
                data[name] = chosen["value"] if chosen else ""
        action = form.get("action") or SEARCH_URL
        if not action.startswith("http"):
            action = urljoin(BASE_LEGINFO_URL, action)
        return data, action

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_bills(self, keyword, session_year=SESSION_YEAR):
        """Return list of basic bill dicts matching *keyword*."""
        resp = self._get(SEARCH_URL)
        soup = BeautifulSoup(resp.text, "lxml")
        form_data, action = self._extract_form_data(soup)

        # Inject our values into whatever fields the form exposes
        for key in list(form_data.keys()):
            kl = key.lower()
            if "keyword" in kl:
                form_data[key] = keyword
            elif "session" in kl:
                form_data[key] = session_year
            elif "house" in kl:
                form_data[key] = "Both"

        # Click the search/submit button
        submit = soup.find("input", {"type": "submit"}) or soup.find(
            "button", {"type": "submit"}
        )
        if submit and submit.get("name"):
            form_data[submit["name"]] = submit.get("value", "Search")

        time.sleep(1)  # be polite
        resp = self._post(action, form_data)
        bills = self._parse_search_results(resp.text)
        logger.info(f"  keyword '{keyword}' → {len(bills)} bills")
        return bills

    def _parse_search_results(self, html):
        soup = BeautifulSoup(html, "lxml")
        bills = []
        seen = set()

        for link in soup.find_all("a", href=re.compile(r"bill_id=")):
            href = link.get("href", "")
            m = re.search(r"bill_id=([^&\"'\s]+)", href)
            if not m:
                continue
            bill_id = m.group(1).strip()
            if bill_id in seen:
                continue
            seen.add(bill_id)

            row = link.find_parent("tr")
            cells = row.find_all("td") if row else []

            bills.append({
                "bill_id": bill_id,
                "bill_number": link.text.strip(),
                "author": cells[1].text.strip() if len(cells) > 1 else "",
                "title": cells[2].text.strip() if len(cells) > 2 else "",
                "status": cells[3].text.strip() if len(cells) > 3 else "",
            })

        return bills

    # ------------------------------------------------------------------
    # Per-bill detail pages
    # ------------------------------------------------------------------

    def get_bill_details(self, bill_id):
        """Fetch status, text/digest, history, and analysis for one bill."""
        details = {"bill_id": bill_id}
        base = BASE_LEGINFO_URL

        pages = {
            "status": f"{base}/faces/billStatusClient.xhtml?bill_id={bill_id}",
            "text": f"{base}/faces/billTextClient.xhtml?bill_id={bill_id}",
            "history": f"{base}/faces/billHistoryClient.xhtml?bill_id={bill_id}",
            "analysis": f"{base}/faces/billAnalysisClient.xhtml?bill_id={bill_id}",
        }

        for page_type, url in pages.items():
            try:
                resp = self._get(url)
                parser = getattr(self, f"_parse_{page_type}_page")
                # Pass bill metadata to text parser so Claude can write a better summary
                if page_type == "text":
                    parsed = parser(
                        resp.text,
                        bill_number=details.get("bill_number", ""),
                        title=details.get("title", ""),
                    )
                else:
                    parsed = parser(resp.text)
                details.update(parsed)
                details[f"{page_type}_url"] = url
                time.sleep(0.75)
            except Exception as exc:
                logger.warning(f"Could not fetch {page_type} page for {bill_id}: {exc}")

        return details

    def _parse_status_page(self, html):
        soup = BeautifulSoup(html, "lxml")
        data = {}
        text = soup.get_text(separator=" ", strip=True)

        for label, key in [
            ("Author:", "author"),
            ("Subject:", "subject"),
            ("Status:", "status"),
            ("Location:", "location"),
        ]:
            m = re.search(rf"{re.escape(label)}\s*(.+?)(?:\s{{2,}}|\Z)", text, re.I)
            if m:
                data[key] = m.group(1).strip()[:300]

        return data

    def _parse_text_page(self, html, bill_number="", title=""):
        from .summarizer import summarize_bill

        soup = BeautifulSoup(html, "lxml")
        data = {}
        text = soup.get_text(separator="\n", strip=True)

        # Extract Legislative Counsel's Digest
        digest_m = re.search(
            r"LEGISLATIVE COUNSEL'S DIGEST\s*\n(.*?)(?:The people of the State|AN ACT|SECTION 1\.|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if digest_m:
            digest = re.sub(r"\s+", " ", digest_m.group(1)).strip()
            # Use Claude to produce a policy-focused 2-sentence summary
            data["summary"] = summarize_bill(bill_number, title, digest)
            data["raw_digest"] = digest[:1000]

        # Link to current enrolled/chaptered/amended text (PDF or HTML)
        version_links = soup.find_all("a", href=re.compile(r"\.(pdf|html?)$", re.I))
        if version_links:
            data["latest_text_link"] = urljoin(BASE_LEGINFO_URL, version_links[-1]["href"])

        return data

    def _parse_history_page(self, html):
        soup = BeautifulSoup(html, "lxml")
        data = {}
        entries = []

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            date_text = cells[0].text.strip()
            action_text = cells[1].text.strip()
            if date_text and re.match(r"\d{1,2}/\d{1,2}/\d{4}", date_text):
                entries.append({"date": date_text, "action": action_text})

        if entries:
            latest = entries[-1]
            data["recent_movement"] = f"{latest['date']}: {latest['action']}"
            data["history_entries"] = entries

        return data

    def _parse_analysis_page(self, html):
        soup = BeautifulSoup(html, "lxml")
        data = {}
        links = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "analysis" in href.lower() or "billAnalysis" in href:
                full = urljoin(BASE_LEGINFO_URL, href)
                links.append({"text": a.text.strip(), "url": full})

        if links:
            data["latest_analysis_url"] = links[-1]["url"]

        return data

    # ------------------------------------------------------------------
    # Active-bill filter
    # ------------------------------------------------------------------

    def is_bill_active(self, bill_data):
        """
        Return True if the bill is still live this year.
        Excludes bills whose most recent action was a terminal outcome in 2025.
        """
        movement = bill_data.get("recent_movement", "")
        status_text = (
            bill_data.get("status", "") + " " + movement
        ).lower()

        for dead in DEAD_STATUSES:
            if dead in status_text:
                # If the terminal action happened in 2026, keep it
                if "2026" in movement:
                    return True
                return False

        return True

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def get_all_public_safety_bills(self):
        """
        Search every category/keyword and return a deduplicated dict of
        { bill_id: bill_data_with_categories }.
        """
        all_bills = {}

        for category, keywords in CATEGORY_KEYWORDS.items():
            logger.info(f"Searching category: {category}")
            for keyword in keywords:
                try:
                    results = self.search_bills(keyword)
                except Exception as exc:
                    logger.error(f"Search failed for '{keyword}': {exc}")
                    time.sleep(3)
                    continue

                for bill in results:
                    bid = bill["bill_id"]
                    if bid not in all_bills:
                        all_bills[bid] = bill
                        all_bills[bid]["categories"] = [category]
                    elif category not in all_bills[bid]["categories"]:
                        all_bills[bid]["categories"].append(category)

        logger.info(f"Found {len(all_bills)} unique bills before detail fetch")

        # Fetch full details for each bill
        detailed = {}
        for bid, bill in all_bills.items():
            try:
                details = self.get_bill_details(bid)
                bill.update(details)
                if self.is_bill_active(bill):
                    detailed[bid] = bill
                else:
                    logger.debug(f"Filtered inactive bill: {bid}")
            except Exception as exc:
                logger.error(f"Detail fetch failed for {bid}: {exc}")
                time.sleep(2)

        logger.info(f"{len(detailed)} active public-safety bills after filtering")
        return detailed
