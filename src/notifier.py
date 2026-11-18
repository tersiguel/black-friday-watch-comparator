"""Chrome Web Push (ntfy.sh) and Local Desktop System Notification dispatcher for Neuf & Occasion thresholds."""

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
    """Build a clear French notification summary for Neuf & Occasion threshold alerts."""
    alerts: List[Dict[str, Any]] = []
    for a in analyses:
        if a.alert_new_triggered and a.best_new_offer and a.best_new_offer.price is not None:
            alerts.append(
                {
                    "label": "NEUF",
                    "watch": a.watch,
                    "offer": a.best_new_offer,
                    "threshold": a.watch.target_price_new,
                }
            )
        if a.alert_used_triggered and a.best_used_offer and a.best_used_offer.price is not None:
            alerts.append(
                {
                    "label": "OCCASION",
                    "watch": a.watch,
                    "offer": a.best_used_offer,
                    "threshold": a.watch.target_price_used,
                }
            )

    if alerts:
        first = alerts[0]
        title = (
            f"🔔 SEUIL {first['label']} ATTEINT : {first['watch'].reference} "
            f"à {first['offer'].price:.2f} € ({first['offer'].merchant})"
        )
        priority = "high"
        tags = "watch,bell,tada"
    else:
        title = "⌚ Suivi Prix Montres — Récapitulatif Neuf & Occasion"
        priority = "default"
        tags = "watch,chart_with_downwards_trend"

    lines: List[str] = []
    for a in analyses:
        parts = []
        if a.best_new_offer and a.best_new_offer.price is not None:
            flag = "🔔 " if a.alert_new_triggered else ""
            parts.append(f"{flag}Neuf {a.best_new_offer.price:.2f} € ({a.best_new_offer.merchant})")
        if a.best_used_offer and a.best_used_offer.price is not None:
            flag = "🔔 " if a.alert_used_triggered else ""
            parts.append(f"{flag}Occasion {a.best_used_offer.price:.2f} € ({a.best_used_offer.merchant})")
        if parts:
            lines.append(f"• {a.watch.brand} {a.watch.reference} : " + " | ".join(parts))

    body = "\n".join(lines) if lines else "Aucun prix relevé sur les pages suivies."
    click_url = dashboard_url or (alerts[0]["offer"].url if alerts else "")

    return {
        "title": title,
        "body": body,
        "priority": priority,
        "tags": tags,
        "click_url": click_url,
        "has_alert": bool(alerts),
        "alerts_count": len(alerts),
    }


def send_ntfy_chrome_push(
    ntfy_server: str,
    ntfy_topic: str,
    summary: Dict[str, Any],
    timeout: int = 10,
) -> bool:
    """Send Web Push notification via ntfy.sh."""
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
    """Trigger a local OS desktop notification if available."""
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
