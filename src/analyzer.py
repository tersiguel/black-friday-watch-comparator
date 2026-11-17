"""Black Friday price history manager, fake promo detector, and BF Score calculator."""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

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


def detect_fake_promo(
    best_offer: OfferResult,
    watch: WatchConfig,
    lowest_historical: Optional[float],
) -> Tuple[bool, Optional[str]]:
    """
    Detect Black Friday fake promotions:
    1. Merchant crossed-out 'original_price' is artificially inflated above official MSRP (> +8%).
    2. Merchant claims a discount, yet current price is higher than the previously recorded low price.
    """
    if not best_offer or best_offer.price is None:
        return False, None

    # Check 1: Inflated crossed-out price vs official MSRP
    if best_offer.original_price and watch.reference_price > 0:
        if best_offer.original_price > watch.reference_price * 1.08:
            return (
                True,
                f"Prix barré gonflé ({best_offer.original_price:.0f} € affiché vs {watch.reference_price:.0f} € prix public officiel)",
            )

    # Check 2: Claimed promo while higher than historical low by > 5%
    if (
        best_offer.original_price
        and lowest_historical is not None
        and best_offer.price > lowest_historical * 1.05
    ):
        return (
            True,
            f"Fausse baisse : affiché en promo à {best_offer.price:.2f} € mais déjà vu à {lowest_historical:.2f} €",
        )

    return False, None


def compute_bf_score_and_verdict(
    best_price: Optional[float],
    watch: WatchConfig,
    lowest_historical: Optional[float],
    is_fake_promo: bool,
) -> Tuple[int, str, str]:
    """Compute a 0-100 Black Friday Deal Score and human-readable badge."""
    if best_price is None:
        return 0, "❌ Indisponible", "wait"

    score = 50.0

    # 1. Discount vs official MSRP (0 to +35 pts)
    if watch.reference_price > 0:
        discount_pct = ((watch.reference_price - best_price) / watch.reference_price) * 100.0
        score += max(-20.0, min(35.0, discount_pct * 1.1))

    # 2. Comparison vs user's target_price (-15 to +25 pts)
    if watch.target_price > 0:
        target_ratio = (watch.target_price - best_price) / watch.target_price
        if best_price <= watch.target_price:
            score += 18.0 + min(12.0, target_ratio * 60.0)
        else:
            score -= min(20.0, abs(target_ratio) * 50.0)

    # 3. Historical low bonus/penalty
    if lowest_historical is not None:
        if best_price <= lowest_historical + 0.01:
            score += 10.0  # All-time low!
        elif best_price > lowest_historical * 1.10:
            score -= 10.0

    # 4. Fake promo penalty
    if is_fake_promo:
        score -= 22.0

    final_score = int(round(max(5.0, min(100.0, score))))

    if is_fake_promo and best_price > watch.target_price:
        return final_score, "⚠️ Fausse Promo détectée", "fake_promo"
    if best_price <= watch.target_price * 0.93 or final_score >= 88:
        return final_score, "🔥 Deal Black Friday Exceptionnel", "exceptional"
    if best_price <= watch.target_price:
        return final_score, "✅ Sous le prix cible (À saisir)", "target_reached"
    if final_score >= 68:
        return final_score, "👍 Bonne promo (Proche de la cible)", "good"
    return final_score, "⏳ Attendre le vrai Black Friday", "wait"


def analyze_watch_and_update_history(
    watch: WatchConfig,
    direct_offers: List[OfferResult],
    discovered_offers: List[OfferResult],
    history: Dict[str, Any],
) -> WatchAnalysis:
    """Analyze all scraped and discovered offers for a watch and update its history."""
    watch_hist = history.setdefault("watches", {}).setdefault(
        watch.id,
        {
            "name": watch.name,
            "reference": watch.reference,
            "target_price": watch.target_price,
            "reference_price": watch.reference_price,
            "entries": [],
        },
    )

    entries: List[Dict[str, Any]] = watch_hist.get("entries", [])

    # Historical stats BEFORE adding current run
    past_best_prices = [
        e["best_price"] for e in entries if isinstance(e.get("best_price"), (int, float))
    ]
    previous_best_price = past_best_prices[-1] if past_best_prices else None
    lowest_historical_before = min(past_best_prices) if past_best_prices else None

    # Combine valid in-stock offers
    all_valid_offers = [
        o for o in (direct_offers + discovered_offers) if o.price is not None and o.in_stock
    ]
    all_valid_offers.sort(key=lambda o: o.price)  # type: ignore

    best_offer = all_valid_offers[0] if all_valid_offers else None
    best_price = best_offer.price if best_offer else None

    # Update historical low/high including current price
    all_prices = past_best_prices + ([best_price] if best_price is not None else [])
    lowest_historical = min(all_prices) if all_prices else None
    highest_historical = max(all_prices) if all_prices else None

    is_fake, fake_reason = (
        detect_fake_promo(best_offer, watch, lowest_historical_before)
        if best_offer
        else (False, None)
    )

    bf_score, bf_verdict, bf_level = compute_bf_score_and_verdict(
        best_price, watch, lowest_historical_before, is_fake
    )

    discount_vs_msrp_pct = 0.0
    if best_price is not None and watch.reference_price > 0:
        discount_vs_msrp_pct = round(
            ((watch.reference_price - best_price) / watch.reference_price) * 100.0, 1
        )

    discount_vs_target_diff = 0.0
    if best_price is not None:
        discount_vs_target_diff = round(best_price - watch.target_price, 2)

    price_drop_vs_previous = 0.0
    if best_price is not None and previous_best_price is not None:
        price_drop_vs_previous = round(previous_best_price - best_price, 2)

    # Record entry in history
    now_iso = datetime.now(timezone.utc).isoformat()
    merchant_prices = {
        o.merchant: o.price for o in direct_offers if o.price is not None
    }
    if best_price is not None:
        entries.append(
            {
                "timestamp": now_iso,
                "best_price": best_price,
                "best_merchant": best_offer.merchant if best_offer else "",
                "best_url": best_offer.url if best_offer else "",
                "merchant_prices": merchant_prices,
                "bf_score": bf_score,
            }
        )
        # Keep up to 180 snapshots per watch
        watch_hist["entries"] = entries[-180:]

    return WatchAnalysis(
        watch=watch,
        offers=direct_offers,
        discovered_offers=discovered_offers,
        best_offer=best_offer,
        lowest_historical_price=lowest_historical,
        highest_historical_price=highest_historical,
        previous_best_price=previous_best_price,
        discount_vs_msrp_pct=discount_vs_msrp_pct,
        discount_vs_target_diff=discount_vs_target_diff,
        price_drop_vs_previous=price_drop_vs_previous,
        is_fake_promo=is_fake,
        fake_promo_reason=fake_reason,
        bf_score=bf_score,
        bf_verdict=bf_verdict,
        bf_verdict_level=bf_level,
    )
