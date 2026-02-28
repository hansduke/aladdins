"""
Sends the weekly legislation digest via Gmail SMTP.

Requires a Gmail App Password (NOT your regular Gmail password).
Set via GMAIL_APP_PASSWORD environment variable / GitHub secret.
"""

import smtplib
import logging
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL, CATEGORY_PRIORITY, BASE_LEGINFO_URL

logger = logging.getLogger(__name__)

CATEGORY_ORDER = sorted(CATEGORY_PRIORITY, key=lambda c: CATEGORY_PRIORITY[c])


def _status_page_url(bill_id):
    return f"{BASE_LEGINFO_URL}/faces/billStatusClient.xhtml?bill_id={bill_id}"


def build_email_html(changes, week_start, week_end):
    """
    Build an HTML email body from the list of (bill_data, change_str) tuples.
    Groups changes by category in priority order.
    """
    # Bucket by category
    by_cat = {cat: [] for cat in CATEGORY_ORDER}
    for bill, change in changes:
        cat = bill.get("categories", [""])[0] or "Other"
        bucket = by_cat.get(cat, by_cat.get(CATEGORY_ORDER[-1]))
        bucket.append((bill, change))

    rows_html = ""
    for cat in CATEGORY_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue

        rows_html += f"""
        <tr>
          <td colspan="4" style="
            background:#1a1a2e;color:#fff;
            padding:10px 14px;font-size:13px;
            font-weight:bold;letter-spacing:.5px;
            text-transform:uppercase;">
            {cat}
          </td>
        </tr>"""

        for bill, change in sorted(items, key=lambda x: x[0].get("bill_number", "")):
            bill_num = bill.get("bill_number", "")
            title = bill.get("title", "")[:80]
            author = bill.get("author", "")
            bid = bill.get("bill_id", "")
            status_url = _status_page_url(bid)
            text_url = bill.get("text_url") or bill.get("latest_text_link") or ""
            analysis_url = bill.get("latest_analysis_url") or ""

            links = f'<a href="{status_url}" style="color:#2563eb;">Status</a>'
            if text_url:
                links += f' &nbsp;|&nbsp; <a href="{text_url}" style="color:#2563eb;">Latest Text</a>'
            if analysis_url:
                links += f' &nbsp;|&nbsp; <a href="{analysis_url}" style="color:#2563eb;">Committee Report</a>'

            rows_html += f"""
        <tr style="border-bottom:1px solid #e5e7eb;">
          <td style="padding:10px 14px;font-weight:600;white-space:nowrap;vertical-align:top;">
            {bill_num}
          </td>
          <td style="padding:10px 14px;vertical-align:top;">
            {title}<br>
            <span style="color:#6b7280;font-size:12px;">{author}</span>
          </td>
          <td style="padding:10px 14px;vertical-align:top;color:#dc2626;font-size:13px;">
            {change}
          </td>
          <td style="padding:10px 14px;vertical-align:top;font-size:12px;white-space:nowrap;">
            {links}
          </td>
        </tr>"""

    if not rows_html:
        rows_html = """
        <tr>
          <td colspan="4" style="padding:20px;text-align:center;color:#6b7280;">
            No changes detected this week.
          </td>
        </tr>"""

    total = len(changes)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:860px;margin:32px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1);">

    <!-- Header -->
    <div style="background:#1a1a2e;padding:24px 32px;">
      <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">
        CA Public Safety Legislation — Weekly Update
      </h1>
      <p style="margin:6px 0 0;color:#94a3b8;font-size:14px;">
        Changes from {week_start} through {week_end} &nbsp;·&nbsp; {total} bill update{'s' if total != 1 else ''}
      </p>
    </div>

    <!-- Table -->
    <div style="padding:0 0 24px;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f9fafb;border-bottom:2px solid #e5e7eb;">
            <th style="padding:10px 14px;text-align:left;color:#374151;font-weight:600;">Bill</th>
            <th style="padding:10px 14px;text-align:left;color:#374151;font-weight:600;">Title / Author</th>
            <th style="padding:10px 14px;text-align:left;color:#374151;font-weight:600;">Change</th>
            <th style="padding:10px 14px;text-align:left;color:#374151;font-weight:600;">Links</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="background:#f9fafb;padding:16px 32px;border-top:1px solid #e5e7eb;">
      <p style="margin:0;font-size:12px;color:#9ca3af;">
        Tracked via <a href="https://leginfo.legislature.ca.gov/" style="color:#6b7280;">leginfo.legislature.ca.gov</a>.
        Data updated every Wednesday at 6 AM PT.
      </p>
    </div>

  </div>
</body>
</html>"""

    return html


def build_email_text(changes, week_start, week_end):
    """Plain-text fallback for email clients that don't render HTML."""
    lines = [
        f"CA PUBLIC SAFETY LEGISLATION — WEEKLY UPDATE",
        f"Changes: {week_start} through {week_end}",
        f"Total updates: {len(changes)}",
        "=" * 60,
    ]

    by_cat = {cat: [] for cat in CATEGORY_ORDER}
    for bill, change in changes:
        cat = bill.get("categories", [""])[0] or "Other"
        by_cat.get(cat, by_cat[CATEGORY_ORDER[-1]]).append((bill, change))

    for cat in CATEGORY_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines += ["", f"--- {cat.upper()} ---"]
        for bill, change in items:
            lines += [
                f"{bill.get('bill_number','')} ({bill.get('author','')})",
                f"  {bill.get('title','')[:80]}",
                f"  CHANGE: {change}",
                f"  Status: {_status_page_url(bill.get('bill_id',''))}",
            ]
            if bill.get("text_url") or bill.get("latest_text_link"):
                lines.append(f"  Text: {bill.get('text_url') or bill.get('latest_text_link')}")
            if bill.get("latest_analysis_url"):
                lines.append(f"  Analysis: {bill['latest_analysis_url']}")

    if not changes:
        lines.append("\nNo changes detected this week.")

    return "\n".join(lines)


def send_weekly_digest(changes):
    """Send the weekly update email."""
    today = date.today()
    week_start = (today - timedelta(days=7)).strftime("%B %d, %Y")
    week_end = today.strftime("%B %d, %Y")

    subject = f"CA Legislation Weekly Update — {today.strftime('%b %d, %Y')} ({len(changes)} changes)"

    html_body = build_email_html(changes, week_start, week_end)
    text_body = build_email_text(changes, week_start, week_end)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

    logger.info(f"Weekly digest sent to {RECIPIENT_EMAIL} ({len(changes)} changes)")
