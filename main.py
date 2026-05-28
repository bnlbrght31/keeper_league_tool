import argparse
import sys

from providers.sleeper import fetch_keeper_data, build_report, write_csv, load_manual_keeper_overrides


def main():
    parser = argparse.ArgumentParser(
        description="Keeper League Tool — pull roster/draft history for keeper league draft prep"
    )
    parser.add_argument(
        "provider",
        choices=["sleeper"],
        help="Fantasy platform (sleeper; yahoo and espn coming soon)",
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
    args = parser.parse_args()

    if args.provider == "sleeper":
        try:
            manual_overrides = load_manual_keeper_overrides(args.keepers)
            data = fetch_keeper_data(args.league_id)
            rows = build_report(data, manual_overrides)
            write_csv(rows, args.output)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"{args.provider} not yet implemented.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
