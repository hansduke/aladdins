"""
Creates and maintains the '2026 Leg' Notion database.

On each run it upserts bill records and returns a list of changes
(new bills, status changes, new movement) for use in the weekly email.

Key design: bills are upserted to Notion one-by-one as they are scraped
so that progress is saved incrementally and a crash does not lose data.
"""

import logging
from datetime import date
from notion_client import Client

from .config import (
    NOTION_API_KEY,
    NOTION_PAGE_ID,
    DATABASE_NAME,
    CATEGORY_PRIORITY,
)

logger = logging.getLogger(__name__)

# Map category name -> Notion color for the select pill
CATEGORY_COLORS = {
    "Crime/Guns": "red",
    "Corrections/CDCR": "orange",
    "Probation/Parole": "yellow",
    "Jails": "green",
    "Record Clearance": "blue",
}

STATUS_COLORS = {
    "Introduced": "gray",
    "In Committee": "yellow",
    "In Appropriations": "orange",
    "On Floor": "red",
    "Enrolled": "purple",
    "Chaptered": "blue",
    "Vetoed": "pink",
    "Dead": "default",
}


def _rt(text):
    """Build a Notion rich_text property value."""
    return [{"text": {"content": str(text)[:2000]}}]


def _normalize_status(raw):
    """Map raw leginfo status text to one of our select option names."""
    if not raw:
        return "Introduced"
    s = raw.lower()
    if "chaptered" in s:
        return "Chaptered"
    if "vetoed" in s or "pocket veto" in s:
        return "Vetoed"
    if "dead" in s or "failed" in s:
        return "Dead"
    if "enrolled" in s:
        return "Enrolled"
    if "floor" in s or "third reading" in s or "second reading" in s:
        return "On Floor"
    if "appropriation" in s:
        return "In Appropriations"
    if "committee" in s or "referred" in s or "hearing" in s:
        return "In Committee"
    return "Introduced"


class NotionSync:
    def __init__(self):
        # Pin to Notion API version 2022-06-28 so that the
        # /v1/databases/{id}/query endpoint is available and not deprecated.
        self.client = Client(auth=NOTION_API_KEY, notion_version="2022-06-28")
        self.db_id = None

    # ------------------------------------------------------------------
    # Database bootstrap
    # ------------------------------------------------------------------

    def get_or_create_database(self):
        """Find the existing '2026 Leg' database or create it fresh."""
        raw = NOTION_PAGE_ID.replace("-", "")
        page_id = f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
        print(f"Using Notion page ID: {page_id}", flush=True)

        try:
            results = self.client.search(query=DATABASE_NAME)
        except Exception as e:
            print(f"\nNotion API search failed: {e}", flush=True)
            print("Check that your integration is shared with the target page.", flush=True)
            raise

        for item in results.get("results", []):
            if item.get("object") != "database":
                continue
            title_parts = item.get("title", [])
            if title_parts and title_parts[0].get("plain_text") == DATABASE_NAME:
                self.db_id = item["id"]
                logger.info(f"Using existing Notion database: {self.db_id}")
                print(f"Found existing database: {self.db_id}", flush=True)
                return self.db_id

        print("Database not found - creating it now...", flush=True)
        return self._create_database(page_id)

    def _create_database(self, page_id):
        try:
            db = self.client.databases.create(
                parent={"type": "page_id", "page_id": page_id},
                title=[{"type": "text", "text": {"content": DATABASE_NAME}}],
                properties={
                    "Bill Number": {"title": {}},
                    "Bill Title": {"rich_text": {}},
                    "Author": {"rich_text": {}},
                    "Category": {
                        "select": {
                            "options": [
                                {"name": cat, "color": CATEGORY_COLORS[cat]}
                                for cat in CATEGORY_COLORS
                            ]
                        }
                    },
                    "Status": {
                        "select": {
                            "options": [
                                {"name": s, "color": c}
                                for s, c in STATUS_COLORS.items()
                            ]
                        }
                    },
                    "Summary": {"rich_text": {}},
                    "Recent Movement": {"rich_text": {}},
                    "Bill Text": {"url": {}},
                    "Committee Report": {"url": {}},
                    "Priority": {"number": {}},
                    "Last Updated": {"date": {}},
                    "Bill ID": {"rich_text": {}},
                    "Prev Status": {"rich_text": {}},
                    "Prev Movement": {"rich_text": {}},
                },
            )
        except Exception as e:
            print(f"\nNotion database creation failed: {e}", flush=True)
            print(
                "Most likely fix: open the Notion page, click Share, "
                "and invite your integration (Hans Synthesis Bot) as a connection.",
                flush=True,
            )
            raise

        self.db_id = db["id"]
        print(f"Created Notion database: {self.db_id}", flush=True)
        logger.info(f"Created Notion database: {self.db_id}")
        return self.db_id

    # ------------------------------------------------------------------
    # Read existing records
    # ------------------------------------------------------------------

    def fetch_existing_bills(self):
        """
        Return dict of { bill_id: { page_id, status, movement } } by
        paginating through the whole database using the REST API directly.
        Uses the 2022-06-28 API endpoint POST /v1/databases/{id}/query.
        """
        existing = {}
        cursor = None
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor

            resp = self.client.request(
                path=f"databases/{self.db_id}/query",
                method="POST",
                body=body,
            )

            for page in resp.get("results", []):
                props = page["properties"]
                bid_rt = props.get("Bill ID", {}).get("rich_text", [])
                if not bid_rt:
                    continue
                bid = bid_rt[0]["plain_text"]
                existing[bid] = {
                    "page_id": page["id"],
                    "status": self._get_select(props, "Status"),
                    "movement": self._get_rt(props, "Recent Movement"),
                    "prev_status": self._get_rt(props, "Prev Status"),
                    "prev_movement": self._get_rt(props, "Prev Movement"),
                }

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        return existing

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_rt(props, name):
        items = props.get(name, {}).get("rich_text", [])
        return items[0]["plain_text"] if items else ""

    @staticmethod
    def _get_select(props, name):
        sel = props.get(name, {}).get("select")
        return sel["name"] if sel else ""

    def _build_properties(self, bill):
        category = bill.get("categories", [""])[0]
        priority = CATEGORY_PRIORITY.get(category, 99)
        status_label = _normalize_status(bill.get("status", ""))
        today = date.today().isoformat()

        props = {
            "Bill Number": {"title": _rt(bill.get("bill_number", ""))},
            "Bill Title": {"rich_text": _rt(bill.get("title", ""))},
            "Author": {"rich_text": _rt(bill.get("author", ""))},
            "Summary": {"rich_text": _rt(bill.get("summary", ""))},
            "Recent Movement": {"rich_text": _rt(bill.get("recent_movement", ""))},
            "Priority": {"number": priority},
            "Last Updated": {"date": {"start": today}},
            "Bill ID": {"rich_text": _rt(bill["bill_id"])},
            "Status": {"select": {"name": status_label}},
        }

        if category:
            props["Category"] = {"select": {"name": category}}

        text_url = bill.get("text_url") or bill.get("latest_text_link")
        if text_url:
            props["Bill Text"] = {"url": text_url}

        analysis_url = bill.get("latest_analysis_url")
        if analysis_url:
            props["Committee Report"] = {"url": analysis_url}

        return props, status_label

    # ------------------------------------------------------------------
    # Upsert one bill - called immediately after each bill is scraped
    # ------------------------------------------------------------------

    def upsert_bill(self, bill, existing_bills):
        """
        Create or update a single bill page in Notion.
        Returns a change description string, or None if nothing changed.
        """
        bid = bill["bill_id"]
        props, status_label = self._build_properties(bill)
        new_movement = bill.get("recent_movement", "")
        change = None

        if bid in existing_bills:
            ex = existing_bills[bid]
            old_status = ex["status"]
            old_movement = ex["movement"]

            if old_status != status_label:
                change = f"Status changed: {old_status} -> {status_label}"
                props["Prev Status"] = {"rich_text": _rt(old_status)}
            elif old_movement != new_movement and new_movement:
                change = f"New movement: {new_movement}"
                props["Prev Movement"] = {"rich_text": _rt(old_movement)}

            self.client.pages.update(page_id=ex["page_id"], properties=props)
        else:
            self.client.pages.create(
                parent={"database_id": self.db_id},
                properties=props,
            )
            change = "New bill added"

        return change

    # ------------------------------------------------------------------
    # Bulk sync
    # ------------------------------------------------------------------

    def sync_bills(self, bills_dict):
        """
        Sync all bills into Notion.
        Returns list of (bill_data, change_str).
        """
        existing = self.fetch_existing_bills()
        changes = []
        synced = 0
        for bid, bill in bills_dict.items():
            try:
                change = self.upsert_bill(bill, existing)
                synced += 1
                if change:
                    changes.append((bill, change))
                    logger.info(f"[{synced}/{len(bills_dict)}] {bid}: {change}")
                else:
                    logger.debug(f"[{synced}/{len(bills_dict)}] {bid}: no change")
            except Exception as exc:
                logger.error(f"Failed to upsert {bid}: {exc}")

        logger.info(
            f"Synced {synced}/{len(bills_dict)} bills. "
            f"{len(changes)} changes detected."
        )
        return changes
