import os
import sys

def _require(name, hint=""):
    val = os.environ.get(name)
    if not val:
        print(f"\n❌  Missing required secret: {name}", flush=True)
        if hint:
            print(f"   {hint}", flush=True)
        print("   Go to: GitHub repo → Settings → Secrets and variables → Actions\n", flush=True)
        sys.exit(1)
    return val

NOTION_API_KEY    = _require("NOTION_API_KEY",    "Value: ntn_O18231483744Hl6Qv4mD7HPk3UrBFFKkrKUoLRTnMWz9Gv")
NOTION_PAGE_ID    = _require("NOTION_PAGE_ID",    "Value: 2fb06cab0956801b8269d2e17da45d70")
GMAIL_USER        = _require("GMAIL_USER",        "Value: Michael.w.redding@gmail.com")
GMAIL_APP_PASSWORD = _require("GMAIL_APP_PASSWORD", "Your Gmail App Password (16 chars)")
RECIPIENT_EMAIL   = os.environ.get("RECIPIENT_EMAIL", "Michael.redding@gov.ca.gov")

# ANTHROPIC_API_KEY is optional — falls back to raw digest if absent
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

DATABASE_NAME = "2026 Leg"
SESSION_YEAR = "20252026"
BASE_LEGINFO_URL = "https://leginfo.legislature.ca.gov"

# Lower number = higher priority in the Notion database
CATEGORY_PRIORITY = {
    "Crime/Guns": 1,
    "Corrections/CDCR": 2,
    "Probation/Parole": 3,
    "Jails": 4,
    "Record Clearance": 5,
}

# Keywords searched against leginfo for each category.
# Broad enough to capture relevant bills; filtering happens after.
CATEGORY_KEYWORDS = {
    "Crime/Guns": [
        "firearm",
        "ghost gun",
        "assault weapon",
        "concealed carry",
        "gun violence restraining",
        "red flag",
        "homicide",
        "murder",
        "manslaughter",
        "robbery",
        "carjacking",
        "retail theft",
        "fentanyl",
        "drug trafficking",
        "gang",
        "hate crime",
        "domestic violence",
        "sexual assault",
        "human trafficking",
        "ammunition",
    ],
    "Corrections/CDCR": [
        "CDCR",
        "Department of Corrections",
        "state prison",
        "incarceration",
        "sentence enhancement",
        "good conduct credit",
        "youth offender parole",
        "elderly parole",
        "rehabilitation",
        "reentry",
        "three strikes",
        "determinate sentencing",
    ],
    "Probation/Parole": [
        "probation",
        "parole",
        "post-release community supervision",
        "PRCS",
        "mandatory supervision",
        "flash incarceration",
        "supervised release",
        "realignment",
    ],
    "Jails": [
        "county jail",
        "pretrial detention",
        "bail",
        "local detention",
        "pretrial release",
        "arraignment",
        "booking",
    ],
    "Record Clearance": [
        "expungement",
        "seal conviction",
        "petition for dismissal",
        "conviction relief",
        "resentencing",
        "certificate of rehabilitation",
        "factual innocence",
        "record clearance",
        "sealing of records",
    ],
}

# Bill statuses that mean it's dead — filter these out unless action was in 2026
DEAD_STATUSES = ["dead", "failed deadline", "failed", "vetoed", "pocket veto", "chaptered"]
