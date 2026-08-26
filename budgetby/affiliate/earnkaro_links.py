"""
EarnKaro affiliate link generator for Flipkart, Myntra, Ajio, and Nykaa.

How EarnKaro tracking works (reverse-engineered from real generated links):
  - EarnKaro's fktr.in/xxxxx short links simply redirect to the product URL
    with 3 appended parameters:
      1. affid=affgrowth                            (EarnKaro's master affiliate ID)
      2. affExtParam1=ENKR{YYYYMMDD}A{UNIQUE_ID}   (unique per-click tracking token)
      3. affExtParam2={YOUR_EARNKARO_USER_ID}       (your EarnKaro account ID = 5549565)

  - Confirmed real expanded link:
    https://www.flipkart.com/...?pid=XYZ
    &affid=affgrowth
    &affExtParam1=ENKR20260826A2145271280
    &affExtParam2=5549565

  - We replicate this exactly — a fresh unique ENKR token per call so every
    click is individually tracked by EarnKaro, same as their website/app does.
"""
import logging
import random
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from budgetby import config

logger = logging.getLogger("budgetby.affiliate.earnkaro")

EARNKARO_AFF_ID = "affgrowth"

# Params to strip before re-applying ours (avoids double-param duplication)
_STRIP_PARAMS = {"affid", "affExtParam1", "affExtParam2", "affTrackingKey",
                 "utm_source", "utm_medium", "utm_campaign"}


def _generate_enkr_token() -> str:
    """
    Generate a unique EarnKaro per-click tracking token.
    Format from real links: ENKR{YYYYMMDD}A{HHMMSS}{4-random-digits}
    Example: ENKR20260826A2145271280
    """
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M%S")
    rand_suffix = str(random.randint(1000, 9999))
    return f"ENKR{date_str}A{time_str}{rand_suffix}"


def _strip_existing_affiliate_params(url: str) -> str:
    """Remove any pre-existing affiliate/tracking params before adding ours."""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        for p in _STRIP_PARAMS:
            qs.pop(p, None)
        clean_query = urlencode({k: v[0] for k, v in qs.items()})
        return urlunparse(parsed._replace(query=clean_query))
    except Exception:
        return url


def build_earnkaro_url_sync(url: str) -> str:
    """
    Convert a raw product URL (Flipkart / Myntra / Ajio / Nykaa) into a
    fully-tracked EarnKaro affiliate URL by appending the 3 required params.

    Exactly replicates what EarnKaro's fktr.in redirect does — every call
    generates a unique ENKR token so each click is individually tracked.
    """
    if not url:
        return ""

    user_id = config.EARNKARO_API_KEY  # "5549565"
    token = _generate_enkr_token()

    try:
        clean_url = _strip_existing_affiliate_params(url)
        sep = "&" if "?" in clean_url else "?"
        affiliate_url = (
            f"{clean_url}{sep}"
            f"affid={EARNKARO_AFF_ID}"
            f"&affExtParam1={token}"
            f"&affExtParam2={user_id}"
        )
        logger.debug(f"EarnKaro URL built [{token}]: {affiliate_url[:80]}...")
        return affiliate_url
    except Exception as e:
        logger.warning(f"EarnKaro URL build failed for {url[:60]}: {e}")
        return url


async def build_earnkaro_url(url: str) -> str:
    """Async wrapper — same as sync, no I/O needed."""
    return build_earnkaro_url_sync(url)
