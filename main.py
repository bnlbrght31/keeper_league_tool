import argparse
import sys

import providers.sleeper as sleeper
import providers.yahoo as yahoo


def main():
    parser = argparse.ArgumentParser(
        description="Keeper League Tool — pull roster/draft history for keeper league draft prep"
    )
    parser.add_argument(
        "provider",
        choices=["sleeper", "yahoo"],
        help="Fantasy platform (espn coming soon)",
    )
    parser.add_argument("league_id", help="Your league ID")
    parser.add_argument(
        "--output",
        default="keeper_report.csv",
        help="Output CSV file path (default: keeper_report.csv)",
    )
    parser.add_argument(
        "--keepers",
        default="keeper_overrides.csv",
        help="Optional CSV with manual keeper counts: columns Player, Keeper Count (default: keeper_overrides.csv)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=2025,
        help="Season year to pull data for (default: 2025)",
    )
    args = parser.parse_args()

    try:
        if args.provider == "sleeper":
            manual_overrides = sleeper.load_manual_keeper_overrides(args.keepers)
            data = sleeper.fetch_keeper_data(args.league_id)
            rows = sleeper.build_report(data, manual_overrides)
            sleeper.write_csv(rows, args.output)

        elif args.provider == "yahoo":
            manual_overrides = yahoo.load_manual_keeper_overrides(args.keepers)
            data = yahoo.fetch_keeper_data(args.league_id, season=args.season)
            rows = yahoo.build_report(data, manual_overrides)
            yahoo.write_csv(rows, args.output)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
