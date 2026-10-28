"""Evidence-based prospect categories for a packaging business.

A category is only *suggested* when the page text contains enough supporting keywords, and the
matching keywords + text snippets are stored so you can see (and override) why. Nothing is guessed
from a company name alone."""
from __future__ import annotations

import re
from typing import Dict, List, Optional

DEFAULT_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "E-commerce Store": ["add to cart", "shop now", "free shipping", "online store", "checkout", "shopify", "woocommerce", "bigcommerce", "ecommerce", "e-commerce", "shopping cart"],
    "Manufacturer": ["manufacturer", "manufacturing", "we manufacture", "factory", "oem", "production facility", "fabrication", "made in usa", "contract manufacturing"],
    "Food & Beverage": ["restaurant", "bakery", "beverage", "snack", "coffee roaster", "brewery", "food products", "organic food", "catering", "gourmet", "sauces", "frozen food", "food manufacturer", "bottling"],
    "Cosmetics & Beauty": ["skincare", "skin care", "cosmetics", "beauty", "makeup", "serum", "lotion", "fragrance", "haircare", "hair care"],
    "Pharmaceutical": ["pharmaceutical", "pharma", "nutraceutical", "supplements", "gmp", "medical device", "drug delivery", "otc products", "vitamins"],
    "Warehouse & Logistics": ["warehouse", "warehousing", "logistics", "freight", "3pl", "supply chain", "distribution center", "trucking", "cross-dock"],
    "Retail": ["retail", "storefront", "our stores", "store locations", "boutique", "visit our store", "retailer"],
    "Subscription Box": ["subscription box", "monthly box", "curated box", "subscribe and save", "box subscription"],
    "Shipping & Fulfillment": ["fulfillment", "order fulfillment", "pick and pack", "shipping services", "dropship", "drop ship", "ecommerce fulfillment", "kitting"],
    "Packaging Distributor": ["packaging supplies", "packaging distributor", "corrugated", "shipping boxes", "stretch film", "poly bags", "packaging materials", "packaging solutions", "custom packaging", "packaging products"],
    "Wholesale": ["wholesale", "bulk orders", "wholesale pricing", "wholesale distributor", "b2b", "distributor", "bulk pricing"],
}


def _merge(extra: Optional[Dict[str, List[str]]]) -> Dict[str, List[str]]:
    merged = {k: list(v) for k, v in DEFAULT_CATEGORY_KEYWORDS.items()}
    for cat, words in (extra or {}).items():
        if not cat or not isinstance(words, list):
            continue
        merged.setdefault(cat, [])
        merged[cat].extend(w.strip().lower() for w in words if isinstance(w, str) and w.strip())
    return merged


def _snippet(text: str, idx: int, length: int, radius: int = 60) -> str:
    start, end = max(0, idx - radius), min(len(text), idx + length + radius)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def classify(text: str, extra_keywords: Optional[Dict[str, List[str]]] = None, min_distinct: int = 2) -> Optional[dict]:
    """Return ``{"category", "confidence", "keywords", "snippets"}`` or None when evidence is too thin.

    Rule: at least ``min_distinct`` different keywords, or one keyword repeated 3+ times."""
    if not text or len(text) < 40:
        return None
    lowered = text.lower()
    best: Optional[dict] = None
    best_score = 0.0
    for category, words in _merge(extra_keywords).items():
        hits: Dict[str, int] = {}
        first_idx: Dict[str, int] = {}
        for w in dict.fromkeys(words):
            if not w:
                continue
            pattern = r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])"
            matches = list(re.finditer(pattern, lowered))
            if matches:
                hits[w] = len(matches)
                first_idx[w] = matches[0].start()
        if not hits:
            continue
        distinct = len(hits)
        total = sum(hits.values())
        if distinct < min_distinct and total < 3:
            continue
        score = distinct * 2 + min(total, 10) * 0.25
        if score > best_score:
            best_score = score
            best = {
                "category": category,
                "confidence": "high" if distinct >= 4 else "medium" if distinct >= 2 else "low",
                "keywords": sorted(hits, key=lambda k: -hits[k]),
                "snippets": [_snippet(text, first_idx[k], len(k)) for k in sorted(hits, key=lambda k: first_idx[k])[:3]],
            }
    return best


def find_keyword_matches(text: str, terms: List[str], mode: str = "any") -> List[str]:
    """Which of the user's prospect-search terms appear in ``text``. mode='all' requires every term;
    returns [] when the requirement is not met."""
    lowered = (text or "").lower()
    matched = [t for t in terms if t and t.lower() in lowered]
    if mode == "all" and len(matched) != len([t for t in terms if t]):
        return []
    return matched
