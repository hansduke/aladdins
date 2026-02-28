"""
Uses Claude (claude-haiku-4-5) to generate a crisp 2-sentence summary
of each bill from a Governor's public-safety-advisor perspective.

Falls back to the raw legislative digest if the API call fails.
"""

import logging
import os

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = (
    "You are a senior policy advisor to the Governor of California, "
    "specializing in public safety — crime, firearms, CDCR, probation, "
    "parole, jails, and record clearance. "
    "Summarize legislation concisely for an executive audience."
)

USER_TEMPLATE = """Summarize the following California bill in exactly 2 sentences.
Sentence 1: What the bill does (the operative change to law).
Sentence 2: Why it matters for public safety policy — who is affected and what the likely impact is.
Be direct. No filler phrases like "This bill..." or "The legislation...".

Bill number: {bill_number}
Title: {title}
Legislative Counsel's Digest:
{digest}
"""


def summarize_bill(bill_number, title, digest):
    """
    Return a 2-sentence summary via Claude, or fall back to the digest.
    """
    if not ANTHROPIC_API_KEY:
        logger.debug("No ANTHROPIC_API_KEY — using raw digest.")
        return _truncate_digest(digest)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = USER_TEMPLATE.format(
            bill_number=bill_number,
            title=title,
            digest=digest[:3000],  # stay well within context
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = msg.content[0].text.strip()
        logger.debug(f"Summarized {bill_number}")
        return summary

    except Exception as exc:
        logger.warning(f"Anthropic summarization failed for {bill_number}: {exc}")
        return _truncate_digest(digest)


def _truncate_digest(digest):
    """Return the first 2 sentences of the raw digest as a fallback."""
    if not digest:
        return ""
    import re
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", digest.strip())
    return " ".join(sentences[:2])[:500]
