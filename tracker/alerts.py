"""Optional Telegram alerts when a release turns into a "buy" signal."""

from datetime import date, timedelta

from . import storage
from .http import request_json

REALERT_AFTER_DAYS = 14


def format_alert(item):
    price = item["lowest_price"]
    price_text = f"{price:.2f} {item['currency']}" if price is not None else "no copies listed"
    lines = [
        f"🎵 {item['artist']} – {item['title']} ({item.get('year') or '?'})",
        f"Score {item['score']} · lowest {price_text} · {item['num_for_sale']} for sale",
        f"Wants {item['want']} / haves {item['have']}",
    ]
    if item.get("songs"):
        lines.append("Trending: " + ", ".join(item["songs"][:2]))
    lines.append(item["url"])
    return "\n".join(lines)


def pending_alerts(items, sent, today):
    cutoff = (date.fromisoformat(today) - timedelta(days=REALERT_AFTER_DAYS)).isoformat()
    return [i for i in items if i["signal"] == "buy" and sent.get(str(i["id"]), "") < cutoff]


def send_alerts(items, alerts_path, today, bot_token, chat_id, fetch=request_json, log=print):
    if not (bot_token and chat_id):
        return 0
    sent = storage.load_json(alerts_path, {})
    count = 0
    for item in pending_alerts(items, sent, today):
        try:
            fetch(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data={"chat_id": chat_id, "text": format_alert(item), "disable_web_page_preview": True},
            )
        except Exception as err:
            log(f"alerts: telegram failed for {item['id']}: {err}")
            continue
        sent[str(item["id"])] = today
        count += 1
    storage.save_json(alerts_path, sent)
    log(f"alerts: sent {count}")
    return count
