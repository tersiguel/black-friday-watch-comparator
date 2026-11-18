"""Keepa-style dual price history manager (Neuf & Occasion) and threshold alert analyzer."""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from src.models import WatchConfig, OfferResult, WatchAnalysis


def load_history(history_path: str) -> Dict[str, Any]:
    """Load price history JSON file or initialize an empty history structure."""
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "watches" in data:
                    return data
        except Exception:
            pass
    return {"updated_at": None, "watches": {}}


def save_history(history_path: str, history: Dict[str, Any]) -> None:
    """Persist price history JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(history_path)), exist_ok=True)
    history["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def _compute_series_stats(values: List[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if not values:
        return None, None, None
    low = round(min(values), 2)
    high = round(max(values), 2)
    avg = round(sum(values) / len(values), 2)
    return low, high, avg


def analyze_watch_and_update_history(
    watch: WatchConfig,
    offers: List[OfferResult],
    history: Dict[str, Any],
) -> WatchAnalysis:
    """Analyze user-configured Neuf & Occasion offers for a watch and update its dual Keepa history."""
    watch_hist = history.setdefault("watches", {}).setdefault(
        watch.id,
        {
            "name": watch.name,
            "reference": watch.reference,
            "target_price_new": watch.target_price_new,
            "target_price_used": watch.target_price_used,
            "reference_price": watch.reference_price,
            "entries": [],
        },
    )
    watch_hist["name"] = watch.name
    watch_hist["reference"] = watch.reference
    watch_hist["target_price_new"] = watch.target_price_new
    watch_hist["target_price_used"] = watch.target_price_used

    entries: List[Dict[str, Any]] = watch_hist.get("entries", [])

    past_new = [
        float(e["new_price"])
        for e in entries
        if isinstance(e.get("new_price"), (int, float))
    ]
    past_used = [
        float(e["used_price"])
        for e in entries
        if isinstance(e.get("used_price"), (int, float))
    ]

    previous_new_price = past_new[-1] if past_new else None
    previous_used_price = past_used[-1] if past_used else None

    valid_new = [
        o for o in offers if o.price is not None and o.in_stock and o.condition != "used"
    ]
    valid_used = [
        o for o in offers if o.price is not None and o.in_stock and o.condition == "used"
    ]
    valid_new.sort(key=lambda o: o.price)   # type: ignore
    valid_used.sort(key=lambda o: o.price)  # type: ignore

    best_new_offer = valid_new[0] if valid_new else None
    best_used_offer = valid_used[0] if valid_used else None

    best_new_price = best_new_offer.price if best_new_offer else None
    best_used_price = best_used_offer.price if best_used_offer else None

    all_new = past_new + ([best_new_price] if best_new_price is not None else [])
    all_used = past_used + ([best_used_price] if best_used_price is not None else [])

    low_new, high_new, avg_new = _compute_series_stats(all_new)
    low_used, high_used, avg_used = _compute_series_stats(all_used)

    drop_new = (
        round(previous_new_price - best_new_price, 2)
        if (best_new_price is not None and previous_new_price is not None)
        else 0.0
    )
    drop_used = (
        round(previous_used_price - best_used_price, 2)
        if (best_used_price is not None and previous_used_price is not None)
        else 0.0
    )

    alert_new = bool(
        best_new_price is not None
        and watch.target_price_new is not None
        and watch.target_price_new > 0
        and best_new_price <= watch.target_price_new
    )
    alert_used = bool(
        best_used_price is not None
        and watch.target_price_used is not None
        and watch.target_price_used > 0
        and best_used_price <= watch.target_price_used
    )

    if best_new_price is not None or best_used_price is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        entries.append(
            {
                "timestamp": now_iso,
                "new_price": best_new_price,
                "new_merchant": best_new_offer.merchant if best_new_offer else "",
                "new_url": best_new_offer.url if best_new_offer else "",
                "used_price": best_used_price,
                "used_merchant": best_used_offer.merchant if best_used_offer else "",
                "used_url": best_used_offer.url if best_used_offer else "",
            }
        )
        watch_hist["entries"] = entries[-365:]

    return WatchAnalysis(
        watch=watch,
        offers=offers,
        best_new_offer=best_new_offer,
        best_used_offer=best_used_offer,
        lowest_new_historical=low_new,
        highest_new_historical=high_new,
        avg_new_historical=avg_new,
        lowest_used_historical=low_used,
        highest_used_historical=high_used,
        avg_used_historical=avg_used,
        previous_new_price=previous_new_price,
        previous_used_price=previous_used_price,
        drop_new_vs_previous=drop_new,
        drop_used_vs_previous=drop_used,
        alert_new_triggered=alert_new,
        alert_used_triggered=alert_used,
    )
