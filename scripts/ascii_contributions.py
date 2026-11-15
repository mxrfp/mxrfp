import html
import json
import os
import urllib.request
from datetime import date
from pathlib import Path

USERNAME = os.environ.get("GITHUB_USERNAME", "mxrfp")
API_URL = f"https://github-contributions-api.jogruber.de/v4/{USERNAME}?y=last"

CHARS = [".", ":", "+", "#", "@"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

THEMES = {
    "dark": {
        "bg": "#0a0a0a",
        "border": "#2e2e2e",
        "title": "#ffffff",
        "muted": "#737373",
        "levels": ["#333333", "#666666", "#999999", "#cccccc", "#ffffff"],
    },
    "light": {
        "bg": "#ffffff",
        "border": "#d4d4d4",
        "title": "#111111",
        "muted": "#737373",
        "levels": ["#d4d4d4", "#a3a3a3", "#737373", "#404040", "#000000"],
    },
}


def fetch_contributions() -> tuple[int, list[dict]]:
    req = urllib.request.Request(
        API_URL,
        headers={"User-Agent": "ascii-contributions-generator"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    entries = sorted(data.get("contributions", []), key=lambda x: x["date"])
    total = data.get("total", {}).get("lastYear")
    if total is None:
        total = sum(e.get("count", 0) for e in entries)
    return total, entries


def build_weeks(entries: list[dict]) -> list[list]:
    weeks = []
    current_week = [None] * 7
    for entry in entries:
        d = date.fromisoformat(entry["date"])
        row = (d.weekday() + 1) % 7  # Sun=0 .. Sat=6
        if row == 0 and any(cell is not None for cell in current_week):
            weeks.append(current_week)
            current_week = [None] * 7
        level = max(0, min(4, int(entry.get("level", 0))))
        count = int(entry.get("count", 0))
        current_week[row] = (d, level, count)
    if any(cell is not None for cell in current_week):
        weeks.append(current_week)
    return weeks[-53:]


def render_svg(total: int, weeks: list[list], theme_name: str) -> str:
    t = THEMES[theme_name]
    width, height = 820, 194
    grid_x, col_step = 60, 14
    grid_y, row_step = 76, 16
    font = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1" />',
        f'  <text x="24" y="32" fill="{t["title"]}" font-family="{font}" font-size="14" font-weight="600">{html.escape(f"{total} contributions in the last year")}</text>',
        f'  <text x="674" y="32" text-anchor="end" fill="{t["muted"]}" font-family="{font}" font-size="11">less</text>',
    ]

    for i, ch in enumerate(CHARS):
        lx = 692 + i * 16
        lines.append(
            f'  <text x="{lx}" y="32" text-anchor="middle" fill="{t["levels"][i]}" font-family="{font}" font-size="13" font-weight="700">{html.escape(ch)}</text>'
        )
    lines.append(
        f'  <text x="796" y="32" text-anchor="end" fill="{t["muted"]}" font-family="{font}" font-size="11">more</text>'
    )

    last_month = None
    last_label_col = -4
    for col_idx, week in enumerate(weeks):
        first_day = next((cell[0] for cell in week if cell is not None), None)
        if first_day is None:
            continue
        m = first_day.month
        if m != last_month and (col_idx - last_label_col) >= 3:
            mx = grid_x + col_idx * col_step
            lines.append(
                f'  <text x="{mx}" y="56" text-anchor="middle" fill="{t["muted"]}" font-family="{font}" font-size="11">{MONTHS[m - 1]}</text>'
            )
            last_label_col = col_idx
        last_month = m

    for row_idx, label in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        ly = grid_y + row_idx * row_step
        lines.append(
            f'  <text x="24" y="{ly}" fill="{t["muted"]}" font-family="{font}" font-size="11">{label}</text>'
        )

    for col_idx, week in enumerate(weeks):
        cx = grid_x + col_idx * col_step
        for row_idx, cell in enumerate(week):
            if cell is None:
                continue
            d, level, count = cell
            cy = grid_y + row_idx * row_step
            ch = html.escape(CHARS[level])
            color = t["levels"][level]
            weight = "700" if level >= 3 else "400"
            lines.append(
                f'  <text x="{cx}" y="{cy}" text-anchor="middle" fill="{color}" font-family="{font}" font-size="13" font-weight="{weight}">{ch}<title>{count} contributions on {d.isoformat()}</title></text>'
            )

    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    total, entries = fetch_contributions()
    weeks = build_weeks(entries)
    out_dir = Path("dist")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("dark", "light"):
        svg = render_svg(total, weeks, name)
        (out_dir / f"contributions-ascii-{name}.svg").write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
