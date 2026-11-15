import html
import json
import os
import re
import textwrap
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

USERNAME = os.environ.get("GITHUB_USERNAME", "mxrfp")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
FONT = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"

CHARS = [".", ":", "+", "#", "@"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

FALLBACK_DESCS = {
    "Dynamic-Type-System-in-C-": "C++ runtime for a dynamically-typed language with double dispatch and custom memory pools (std::pmr).",
    "donutSMP-craft-price-founder": "Python script that scrapes live auction prices and calculates crafting material costs for Donut SMP.",
}

LEVEL_MAP = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

THEMES = {
    "dark": {
        "bg": "#0a0a0a",
        "border": "#2e2e2e",
        "title": "#ffffff",
        "label": "#d4d4d4",
        "muted": "#737373",
        "dim": "#3a3a3a",
        "levels": ["#333333", "#666666", "#999999", "#cccccc", "#ffffff"],
    },
    "light": {
        "bg": "#ffffff",
        "border": "#d4d4d4",
        "title": "#111111",
        "label": "#404040",
        "muted": "#737373",
        "dim": "#d4d4d4",
        "levels": ["#d4d4d4", "#a3a3a3", "#737373", "#404040", "#000000"],
    },
}

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    pullRequests(first: 1) { totalCount }
    issues(first: 1) { totalCount }
    repositoriesContributedTo(
      first: 1
      contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
    ) { totalCount }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
      }
    }
    repositories(
      first: 100
      ownerAffiliations: OWNER
      isFork: false
      privacy: PUBLIC
      orderBy: { field: STARGAZERS, direction: DESC }
    ) {
      nodes {
        name
        description
        url
        stargazerCount
        forkCount
        primaryLanguage { name }
        languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
          edges {
            size
            node { name }
          }
        }
      }
    }
  }
}
"""


def fetch_github_graphql() -> dict:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required")
    payload = json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": USERNAME}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "ascii-profile-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]["user"]


def fetch_calendar(user_data: dict) -> list[tuple[date, int, int]]:
    api_url = f"https://github-contributions-api.jogruber.de/v4/{USERNAME}?y=all"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "ascii-profile-generator"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        entries = []
        for item in raw.get("contributions", []):
            d = date.fromisoformat(item["date"])
            level = max(0, min(4, int(item.get("level", 0))))
            count = int(item.get("count", 0))
            entries.append((d, level, count))
        if entries:
            entries.sort(key=lambda x: x[0])
            return entries
    except Exception:
        pass

    entries = []
    cal = user_data["contributionsCollection"]["contributionCalendar"]
    for week in cal["weeks"]:
        for day in week["contributionDays"]:
            d = date.fromisoformat(day["date"])
            level = LEVEL_MAP.get(day["contributionLevel"], 0)
            count = int(day["contributionCount"])
            entries.append((d, level, count))
    entries.sort(key=lambda x: x[0])
    return entries


def compute_streaks(entries: list[tuple[date, int, int]]) -> tuple[int, int, int]:
    total_all = sum(c for _, _, c in entries)
    longest = 0
    run = 0
    prev_d = None
    for d, _, count in entries:
        if count > 0:
            run = run + 1 if (prev_d is not None and (d - prev_d).days == 1) else 1
            if run > longest:
                longest = run
        else:
            run = 0
        prev_d = d

    today_utc = datetime.now(timezone.utc).date()
    idx = len(entries) - 1
    while idx >= 0 and entries[idx][0] > today_utc and entries[idx][2] == 0:
        idx -= 1

    if idx >= 0 and entries[idx][2] == 0:
        idx -= 1

    current = 0
    expected = None
    while idx >= 0:
        d, _, count = entries[idx]
        if count <= 0:
            break
        if expected is not None and d != expected:
            break
        current += 1
        expected = d - timedelta(days=1)
        idx -= 1

    return total_all, current, longest


def compute_languages(repos: list[dict]) -> list[tuple[str, float]]:
    totals: dict[str, int] = {}
    for repo in repos:
        for edge in repo.get("languages", {}).get("edges", []):
            name = edge["node"]["name"]
            totals[name] = totals.get(name, 0) + int(edge["size"])
    grand_total = sum(totals.values())
    if grand_total == 0:
        return []
    ordered = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:5]
    return [(name, (size / grand_total) * 100.0) for name, size in ordered]


def build_weeks(entries: list[tuple[date, int, int]]) -> tuple[int, list[list]]:
    if not entries:
        return 0, []
    cutoff = entries[-1][0] - timedelta(days=364)
    last_year_entries = [e for e in entries if e[0] >= cutoff]
    total_last_year = sum(c for _, _, c in last_year_entries)

    weeks = []
    current_week = [None] * 7
    for d, level, count in entries:
        row = (d.weekday() + 1) % 7
        if row == 0 and any(cell is not None for cell in current_week):
            weeks.append(current_week)
            current_week = [None] * 7
        current_week[row] = (d, level, count)
    if any(cell is not None for cell in current_week):
        weeks.append(current_week)
    return total_last_year, weeks[-53:]


def render_stats_svg(
    user_data: dict,
    repos: list[dict],
    langs: list[tuple[str, float]],
    streaks: tuple[int, int, int],
    theme_name: str,
) -> str:
    t = THEMES[theme_name]
    width, height = 820, 268

    total_stars = sum(int(r.get("stargazerCount", 0)) for r in repos)
    commits_1y = int(user_data["contributionsCollection"]["totalCommitContributions"])
    prs = int(user_data["pullRequests"]["totalCount"])
    issues = int(user_data["issues"]["totalCount"])
    contributed_to = int(user_data["repositoriesContributedTo"]["totalCount"])
    total_all, current_streak, longest_streak = streaks

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1" />',
        f'  <text x="24" y="30" fill="{t["title"]}" font-family="{FONT}" font-size="14" font-weight="700">{html.escape(f"{USERNAME} // stats")}</text>',
        f'  <text x="796" y="30" text-anchor="end" fill="{t["muted"]}" font-family="{FONT}" font-size="11">public profile</text>',
        f'  <line x1="0" y1="48" x2="{width}" y2="48" stroke="{t["border"]}" stroke-width="1" />',
        f'  <line x1="380" y1="48" x2="380" y2="198" stroke="{t["border"]}" stroke-width="1" />',
        f'  <line x1="0" y1="198" x2="{width}" y2="198" stroke="{t["border"]}" stroke-width="1" />',
        f'  <line x1="273" y1="198" x2="273" y2="{height}" stroke="{t["border"]}" stroke-width="1" />',
        f'  <line x1="547" y1="198" x2="547" y2="{height}" stroke="{t["border"]}" stroke-width="1" />',
    ]

    left_rows = [
        ("stars earned", total_stars),
        ("commits (1y)", commits_1y),
        ("pull requests", prs),
        ("issues", issues),
        ("contributed to", contributed_to),
    ]
    for i, (label, val) in enumerate(left_rows):
        y = 78 + i * 26
        lines.append(
            f'  <text x="24" y="{y}" fill="{t["label"]}" font-family="{FONT}" font-size="12">{html.escape(label)}</text>'
        )
        lines.append(
            f'  <text x="356" y="{y}" text-anchor="end" fill="{t["title"]}" font-family="{FONT}" font-size="12" font-weight="700">{val}</text>'
        )

    if not langs:
        lines.append(
            f'  <text x="404" y="78" fill="{t["muted"]}" font-family="{FONT}" font-size="12">no language data</text>'
        )
    else:
        bar_len = 18
        for i, (name, pct) in enumerate(langs):
            y = 78 + i * 26
            short_name = name if len(name) <= 11 else name[:10] + "."
            filled = max(0, min(bar_len, round((pct / 100.0) * bar_len)))
            empty = bar_len - filled
            lines.append(
                f'  <text x="404" y="{y}" fill="{t["title"]}" font-family="{FONT}" font-size="12">{html.escape(short_name)}</text>'
            )
            lines.append(
                f'  <text x="508" y="{y}" font-family="{FONT}" font-size="12">'
                f'<tspan fill="{t["muted"]}">[</tspan>'
                f'<tspan fill="{t["title"]}">{"#" * filled}</tspan>'
                f'<tspan fill="{t["dim"]}">{"." * empty}</tspan>'
                f'<tspan fill="{t["muted"]}">]</tspan>'
                f'</text>'
            )
            lines.append(
                f'  <text x="796" y="{y}" text-anchor="end" fill="{t["label"]}" font-family="{FONT}" font-size="12">{pct:.1f}%</text>'
            )

    bottom_cols = [
        (136, f"{total_all}", "total contributions"),
        (410, f"{current_streak}d", "current streak"),
        (684, f"{longest_streak}d", "longest streak"),
    ]
    for cx, big_val, sub_label in bottom_cols:
        lines.append(
            f'  <text x="{cx}" y="229" text-anchor="middle" fill="{t["title"]}" font-family="{FONT}" font-size="18" font-weight="700">{html.escape(big_val)}</text>'
        )
        lines.append(
            f'  <text x="{cx}" y="249" text-anchor="middle" fill="{t["muted"]}" font-family="{FONT}" font-size="11">{html.escape(sub_label)}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def render_project_svg(repo: dict, theme_name: str) -> str:
    t = THEMES[theme_name]
    width, height = 400, 148
    name = repo["name"]
    title_str = f"> {name}"
    if len(title_str) > 36:
        title_str = title_str[:33] + "..."

    raw_desc = (repo.get("description") or "").strip() or FALLBACK_DESCS.get(name, "No description provided.")
    wrapped = textwrap.wrap(raw_desc, width=45)
    desc_lines = wrapped[:2]
    if len(wrapped) > 2:
        desc_lines[1] = desc_lines[1][:41].rstrip() + "..."

    lang = (repo.get("primaryLanguage") or {}).get("name") or "text"
    stars = int(repo.get("stargazerCount", 0))
    forks = int(repo.get("forkCount", 0))

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1" />',
        f'  <text x="20" y="32" fill="{t["title"]}" font-family="{FONT}" font-size="13" font-weight="700">{html.escape(title_str)}</text>',
    ]
    for i, line in enumerate(desc_lines):
        y = 58 + i * 20
        lines.append(
            f'  <text x="20" y="{y}" fill="{t["label"]}" font-family="{FONT}" font-size="11.5">{html.escape(line)}</text>'
        )

    lines.extend([
        f'  <line x1="20" y1="108" x2="{width - 20}" y2="108" stroke="{t["border"]}" stroke-width="1" />',
        f'  <text x="20" y="130" fill="{t["title"]}" font-family="{FONT}" font-size="11.5">{html.escape(f"[{lang}]")}</text>',
        f'  <text x="{width - 20}" y="130" text-anchor="end" fill="{t["muted"]}" font-family="{FONT}" font-size="11.5">{html.escape(f"stars: {stars} | forks: {forks}")}</text>',
        "</svg>",
    ])
    return "\n".join(lines)


def render_contributions_svg(total: int, weeks: list[list], theme_name: str) -> str:
    t = THEMES[theme_name]
    width, height = 820, 194
    grid_x, col_step = 60, 14
    grid_y, row_step = 76, 16

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1" />',
        f'  <text x="24" y="32" fill="{t["title"]}" font-family="{FONT}" font-size="14" font-weight="600">{html.escape(f"{total} contributions in the last year")}</text>',
        f'  <text x="674" y="32" text-anchor="end" fill="{t["muted"]}" font-family="{FONT}" font-size="11">less</text>',
    ]

    for i, ch in enumerate(CHARS):
        lx = 692 + i * 16
        lines.append(
            f'  <text x="{lx}" y="32" text-anchor="middle" fill="{t["levels"][i]}" font-family="{FONT}" font-size="13" font-weight="700">{html.escape(ch)}</text>'
        )
    lines.append(
        f'  <text x="796" y="32" text-anchor="end" fill="{t["muted"]}" font-family="{FONT}" font-size="11">more</text>'
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
                f'  <text x="{mx}" y="56" text-anchor="middle" fill="{t["muted"]}" font-family="{FONT}" font-size="11">{MONTHS[m - 1]}</text>'
            )
            last_label_col = col_idx
        last_month = m

    for row_idx, label in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        ly = grid_y + row_idx * row_step
        lines.append(
            f'  <text x="24" y="{ly}" fill="{t["muted"]}" font-family="{FONT}" font-size="11">{label}</text>'
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
                f'  <text x="{cx}" y="{cy}" text-anchor="middle" fill="{color}" font-family="{FONT}" font-size="13" font-weight="{weight}">{ch}<title>{count} contributions on {d.isoformat()}</title></text>'
            )

    lines.append("</svg>")
    return "\n".join(lines)


def main() -> None:
    user_data = fetch_github_graphql()
    all_repos = user_data["repositories"]["nodes"]
    project_repos = [r for r in all_repos if r["name"].lower() != USERNAME.lower()]

    entries = fetch_calendar(user_data)
    streaks = compute_streaks(entries)
    langs = compute_languages(all_repos)
    total_last_year, weeks = build_weeks(entries)

    out_dir = Path("dist")
    out_dir.mkdir(parents=True, exist_ok=True)

    for theme_name in ("dark", "light"):
        (out_dir / f"stats-ascii-{theme_name}.svg").write_text(
            render_stats_svg(user_data, all_repos, langs, streaks, theme_name),
            encoding="utf-8",
        )
        (out_dir / f"contributions-ascii-{theme_name}.svg").write_text(
            render_contributions_svg(total_last_year, weeks, theme_name),
            encoding="utf-8",
        )
        for repo in project_repos:
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", repo["name"])
            (out_dir / f"repo-{safe_name}-{theme_name}.svg").write_text(
                render_project_svg(repo, theme_name),
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
