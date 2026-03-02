"""
main.py - Full scrape + Notion sync + weekly email digest.

Modes:
  python main.py            -> scrape, sync, send email if changes exist
  python main.py --no-email -> scrape and sync only (no email)
  python main.py --setup    -> create/verify the Notion database, then exit

Incremental design: bills are upserted to Notion one-by-one as they
finish scraping.  If the job is killed at minute 43, everything scraped
so far is already in Notion.  The next run picks up from the existing
records (fetch_existing_bills) and only overwrites what has changed.
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def run(send_email=True):
    from src.scraper import LegInfoScraper
    from src.notion_sync import NotionSync
    from src.email_client import send_weekly_digest

    # ----------------------------------------------------------------
    # 1. Set up Notion DB and load already-synced bills
    # ----------------------------------------------------------------
    logger.info("Connecting to Notion ...")
    notion = NotionSync()
    notion.get_or_create_database()

    logger.info("Loading existing bills from Notion ...")
    existing = notion.fetch_existing_bills()
    logger.info(f"Found {len(existing)} bills already in Notion.")

    # ----------------------------------------------------------------
    # 2. Scrape + upsert incrementally
    #    Each bill is written to Notion as soon as its detail pages are
    #    fetched, so a crash never discards more than ~1 bill's work.
    # ----------------------------------------------------------------
    logger.info("Starting leginfo scrape ...")
    scraper = LegInfoScraper()
    changes = []

    # get_all_public_safety_bills_incremental yields (bill_id, bill_data)
    # one at a time as each bill finishes being scraped.
    total = 0
    for bid, bill in scraper.get_all_public_safety_bills_incremental():
        total += 1
        try:
            change = notion.upsert_bill(bill, existing)
            # Update existing cache so subsequent duplicates are treated as updates
            if bid not in existing:
                existing[bid] = {
                    "page_id": None,   # not needed after initial create
                    "status": bill.get("status", ""),
                    "movement": bill.get("recent_movement", ""),
                    "prev_status": "",
                    "prev_movement": "",
                }
            if change:
                changes.append((bill, change))
                logger.info(f"[{total}] {bid}: {change}")
        except Exception as exc:
            logger.error(f"[{total}] Failed to upsert {bid}: {exc}")

    if not total:
        logger.warning("No bills found - aborting.")
        sys.exit(1)

    logger.info(f"Scrape+sync complete. {total} bills processed, {len(changes)} changes.")

    # ----------------------------------------------------------------
    # 3. Send email
    # ----------------------------------------------------------------
    if send_email:
        if changes:
            logger.info("Sending weekly digest ...")
            send_weekly_digest(changes)
        else:
            logger.info("No changes - skipping email.")
    else:
        logger.info("Email skipped (--no-email flag).")

    return len(changes)


def setup_only():
    from src.notion_sync import NotionSync
    logger.info("Setting up Notion database ...")
    notion = NotionSync()
    db_id = notion.get_or_create_database()
    logger.info(f"Database ready: {db_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CA Legislation Tracker")
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Scrape and sync to Notion but skip sending the email.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create the Notion database only, then exit.",
    )
    args = parser.parse_args()

    if args.setup:
        setup_only()
    else:
        run(send_email=not args.no_email)
