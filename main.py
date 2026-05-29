import argparse
import sys
from datetime import date, timedelta

import providers.sleeper as sleeper
import providers.yahoo as yahoo


def _parse_dates(dates_str):
    """Parse comma-separated dates and/or YYYY-MM-DD:YYYY-MM-DD ranges."""
    result = []
    for token in dates_str.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            start_s, end_s = token.split(":", 1)
            start = date.fromisoformat(start_s.strip())
            end = date.fromisoformat(end_s.strip())
            d = start
            while d <= end:
                result.append(d.isoformat())
                d += timedelta(days=1)
        else:
            result.append(date.fromisoformat(token).isoformat())
    return result


def cmd_report(args):
    try:
        if args.provider == "sleeper":
            manual_overrides = sleeper.load_manual_keeper_overrides(args.keepers)
            data = sleeper.fetch_keeper_data(args.league_id)
            rows = sleeper.build_report(data, manual_overrides, cost_model=args.cost_model)
            sleeper.write_csv(rows, args.output)

        elif args.provider == "yahoo":
            manual_overrides = yahoo.load_manual_keeper_overrides(args.keepers)
            data = yahoo.fetch_keeper_data(args.league_id, season=args.season)
            rows = yahoo.build_report(data, manual_overrides)
            yahoo.write_csv(rows, args.output)

        else:
            rows = []
            data = {}

        if args.sheets and rows:
            from sheets import export_to_sheets
            title = args.sheets_title or f"{data['season'] + 1} Keeper Report - {data['league_name']}"
            export_to_sheets(rows, title=title)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dashboard(args):
    import os
    from providers.yahoo_history import fetch_all_seasons, save_history, load_history
    from dashboard import build_dashboard

    cache = args.cache or f"{args.slug}_history.json"
    output = args.output or f"docs/{args.slug}/index.html"

    if args.refresh or not os.path.exists(cache):
        print(f"Fetching history for league {args.league_id}, season {args.season}...")
        seasons = fetch_all_seasons(args.league_id, current_season=args.season)
        save_history(seasons, cache)
    else:
        print(f"Loading cached history from {cache}...")
        seasons = load_history(cache)

    build_dashboard(seasons, output)
    print(f"Dashboard written to {output}")


def cmd_schedule(args):
    from schedule import run_scheduler

    try:
        dates = _parse_dates(args.dates)
    except ValueError as e:
        print(f"Error parsing dates: {e}", file=sys.stderr)
        sys.exit(1)
    emails = [e.strip() for e in args.emails.split(",") if e.strip()]
    names = [n.strip() for n in args.names.split(",") if n.strip()] if args.names else None

    if not dates:
        print("Error: --dates is required (comma-separated YYYY-MM-DD values)", file=sys.stderr)
        sys.exit(1)
    if not emails:
        print("Error: --emails is required (comma-separated email addresses)", file=sys.stderr)
        sys.exit(1)

    try:
        run_scheduler(
            spreadsheet_id=args.sheet_id,
            league_name=args.league,
            dates=dates,
            emails=emails,
            names=names,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Keeper League Tool — pull roster/draft history for keeper league draft prep"
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # -----------------------------------------------------------------------
    # report subcommand (keeper data export)
    # -----------------------------------------------------------------------
    rp = sub.add_parser("report", help="Pull keeper data and export CSV / Google Sheet")
    rp.add_argument(
        "provider",
        choices=["sleeper", "yahoo"],
        help="Fantasy platform",
    )
    rp.add_argument("league_id", help="Your league ID")
    rp.add_argument(
        "--output",
        default="keeper_report.csv",
        help="Output CSV file path (default: keeper_report.csv)",
    )
    rp.add_argument(
        "--keepers",
        default="keeper_overrides.csv",
        help="Optional CSV with manual keeper counts: columns Player, Keeper Count",
    )
    rp.add_argument(
        "--season",
        type=int,
        default=2025,
        help="Season year to pull data for (default: 2025)",
    )
    rp.add_argument(
        "--sheets",
        action="store_true",
        help="Export to a new Google Sheet in addition to CSV",
    )
    rp.add_argument(
        "--sheets-title",
        default=None,
        help="Title for the Google Sheet (default: '{year} Keeper Report - {league name}')",
    )
    rp.add_argument(
        "--cost-model",
        choices=["standard", "escalate"],
        default="standard",
        help="Keeper cost formula: standard = max(draft, FAAB) with $20 waiver floor; escalate = base + max(10%%, $2)",
    )
    rp.set_defaults(func=cmd_report)

    # -----------------------------------------------------------------------
    # schedule subcommand (draft date poll)
    # -----------------------------------------------------------------------
    # -----------------------------------------------------------------------
    # dashboard subcommand (league history)
    # -----------------------------------------------------------------------
    dp = sub.add_parser("dashboard", help="Generate a league history dashboard (static HTML)")
    dp.add_argument("league_id", help="Yahoo league ID (numeric)")
    dp.add_argument("slug", help="Short name for this league used in the URL and file paths (e.g. lobos)")
    dp.add_argument(
        "--season", type=int, default=2025,
        help="Most recent season to start the history chain from (default: 2025)",
    )
    dp.add_argument(
        "--output", default=None,
        help="Output HTML file path (default: docs/<slug>/index.html)",
    )
    dp.add_argument(
        "--cache", default=None,
        help="JSON cache file for raw season data (default: <slug>_history.json)",
    )
    dp.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch from Yahoo even if cache exists",
    )
    dp.set_defaults(func=cmd_dashboard)

    # -----------------------------------------------------------------------
    # schedule subcommand (draft date poll)
    # -----------------------------------------------------------------------
    sp = sub.add_parser("schedule", help="Send a draft date availability poll via email")
    sp.add_argument("--sheet-id", required=True, help="Google Sheet ID to store poll results")
    sp.add_argument("--league", required=True, help="League name (used in email subject and poll title)")
    sp.add_argument(
        "--dates",
        required=True,
        help="Dates to poll: comma-separated YYYY-MM-DD and/or YYYY-MM-DD:YYYY-MM-DD ranges (e.g. 2026-08-01:2026-08-31 or 2026-08-01,2026-08-08)",
    )
    sp.add_argument(
        "--emails",
        required=True,
        help="Comma-separated email addresses to send the poll to",
    )
    sp.add_argument(
        "--names",
        default=None,
        help="Comma-separated team/person names (used for the response tracker; optional)",
    )
    sp.set_defaults(func=cmd_schedule)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
