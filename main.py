"""
main.py — Full scrape + Notion sync + weekly email digest.

Modes:
  python main.py            → scrape, sync, send email if changes exist
  python main.py --no-email → scrape and sync only (no email)
  python main.py --setup    → create/verify the Notion database, then exit
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

    # 1. Scrape leginfo
    logger.info("Starting leginfo scrape …")
    scraper = LegInfoScraper()
    bills = scraper.get_all_public_safety_bills()

    if not bills:
        logger.warning("No bills found — aborting.")
        sys.exit(1)

    # 2. Sync to Notion
    logger.info("Syncing to Notion …")
    notion = NotionSync()
    notion.get_or_create_database()
    changes = notion.sync_bills(bills)

    logger.info(f"Sync complete. {len(changes)} changes this week.")

    # 3. Send email
    if send_email:
        if changes:
            logger.info("Sending weekly digest …")
            send_weekly_digest(changes)
        else:
            logger.info("No changes — skipping email.")
    else:
        logger.info("Email skipped (--no-email flag).")

    return len(changes)


def setup_only():
    from src.notion_sync import NotionSync

    logger.info("Setting up Notion database …")
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
