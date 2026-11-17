"""Chrome Web Push (ntfy.sh) and Local Desktop System Notification dispatcher."""

import os
import platform
import subprocess
from typing import List, Optional, Dict, Any
from urllib.request import Request, urlopen

from src.models import WatchAnalysis


def build_daily_recap_message(
    analyses: List[WatchAnalysis],
    dashboard_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a structured daily recap & price alert summary for Chrome notifications."""
    valid = [a for a in analyses if a.best_offer and a.best_offer.price is not None]
    valid.sort(key=lambda a: a.bf_score, reverse=True)

    target_hits = [a for a in valid if a.best_offer.price <= a.watch.target_price]  # type: ignore
    price_drops = [a for a in valid if a.price_drop_vs_previous > 0.5]

    if target_hits:
        best = target_hits[0]
        title = f"🔥 OBJECTIF ATTEINT : {best.watch.name} à {best.best_offer.price:.2f} € !"
        priority = "high"
        tags = "watch,fire,tada"
    elif price_drops:
        best = price_drops[0]
        title = f"📉 Baisse de prix (-{best.price_drop_vs_previous:.2f} €) : {best.watch.name}"
        priority = "high"
        tags = "watch,chart_with_downwards_trend"
    elif valid:
        best = valid[0]
        title = f"⌚ Récap Black Friday : Meilleur deal {best.watch.reference} à {best.best_offer.price:.2f} €"
        priority = "default"
        tags = "watch,shopping_cart"
    else:
        title = "⌚ Récap Black Friday Montres : Aucun prix relevé"
        priority = "low"
        tags = "watch"

    lines = []
    for a in valid:
        offer = a.best_offer
        assert offer is not None and offer.price is not None
        diff_target = offer.price - a.watch.target_price
        target_str = (
            f"✅ {abs(diff_target):.0f}€ sous ta cible"
            if diff_target <= 0
            else f"cible {a.watch.target_price:.0f}€ (+{diff_target:.0f}€)"
        )
        drop_str = f" [📉 -{a.price_drop_vs_previous:.2f}€]" if a.price_drop_vs_previous > 0 else ""
        lines.append(
            f"• {a.watch.reference} : {offer.price:.2f} € chez {offer.merchant} "
            f"(-{a.discount_vs_msrp_pct:.0f}% vs neuf, {target_str}, Score BF {a.bf_score}/100){drop_str}"
        )

    body = "\n".join(lines) if lines else "Vérifie tes URLs dans watches.yaml."
    click_url = dashboard_url or (valid[0].best_offer.url if valid and valid[0].best_offer else "")

    return {
        "title": title,
        "body": body,
        "priority": priority,
        "tags": tags,
        "click_url": click_url,
        "has_alert": bool(target_hits or price_drops),
    }


def send_ntfy_chrome_push(
    ntfy_server: str,
    ntfy_topic: str,
    summary: Dict[str, Any],
    timeout: int = 10,
) -> bool:
    """
    Send Web Push notification via ntfy.sh.
    When subscribed in Google Chrome at https://ntfy.sh/app, Chrome Service Workers
    display a native OS/Chrome notification even if the tab is closed.
    """
    if not ntfy_topic or not ntfy_topic.strip():
        return False

    url = f"{ntfy_server.rstrip('/')}/{ntfy_topic.strip()}"
    headers = {
        "Title": summary["title"].encode("utf-8").decode("latin-1", errors="ignore"),
        "Priority": summary.get("priority", "default"),
        "Tags": summary.get("tags", "watch"),
    }
    if summary.get("click_url"):
        headers["Click"] = summary["click_url"]

    try:
        req = Request(url, data=summary["body"].encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            return status in (200, 201, 202)
    except Exception:
        return False


def send_local_desktop_notification(summary: Dict[str, Any]) -> bool:
    """Trigger a local OS desktop notification if run on the user's computer."""
    title = summary["title"]
    body = summary["body"]
    system = platform.system().lower()

    try:
        if system == "linux":
            if shutil_which("notify-send"):
                subprocess.run(["notify-send", title, body], check=False, timeout=5)
                return True
        elif system == "darwin":
            script = f'display notification "{body[:200].replace(chr(34), "")}" with title "{title.replace(chr(34), "")}"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=5)
            return True
    except Exception:
        pass
    return False


def shutil_which(cmd: str) -> Optional[str]:
    for path in os.environ.get("PATH", "").split(os.pathsep):
        full = os.path.join(path, cmd)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            return full
    return None
