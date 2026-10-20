"""Markdown summary of the top releases, shown privately on each GitHub Actions run page."""

SIGNAL_LABEL = {"buy": "🟢 Buy", "watch": "🟡 Watch", "moved": "🟠 Already moved", "": "—"}


def _pct(value):
    return "—" if value is None else f"{value * 100:+.0f}%"


def _cell(text):
    return str(text).replace("|", "\\|")


def markdown_summary(data, limit=25):
    items = data["releases"]
    counts = {s: sum(1 for i in items if i["signal"] == s) for s in ("buy", "watch", "moved")}
    lines = [
        f"## Vinyl Trend Tracker · {data['today']}",
        "",
        f"{len(items)} pressings tracked · **{counts['buy']} buy** · {counts['watch']} watch · "
        f"{counts['moved']} already moved. Download the `dashboard` artifact below for charts.",
        "",
    ]
    if not items:
        return "\n".join(lines + ["No data yet."]) + "\n"
    lines += [
        "| Release | Signal | Score | Lowest | For sale | Want/have | Wants 30d | Supply 30d | Price 30d | Trending song |",
        "|---|---|--:|--:|--:|--:|--:|--:|--:|---|",
    ]
    for i in items[:limit]:
        price = "—" if i["lowest_price"] is None else f"{i['lowest_price']:.2f} {i['currency']}"
        ratio = "—" if i["want_have"] is None else f"{i['want_have']:.2f}"
        c = i["change_30d"]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"[{_cell(i['artist'])} – {_cell(i['title'])}]({i['url']}) ({i.get('year') or '?'})",
                    SIGNAL_LABEL[i["signal"]],
                    f"{i['score']:.0f}",
                    price,
                    str(i["num_for_sale"] if i["num_for_sale"] is not None else "—"),
                    ratio,
                    _pct(c["want"]),
                    _pct(c["for_sale"]),
                    _pct(c["price"]),
                    _cell(i["songs"][0]) if i["songs"] else "watchlist",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
