"""
CLI entry point for mobilerun-autotest.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from mobilerun_autotest import TestRunner, __version__

console = Console()


def setup_logging(debug: bool = False):
    """Configure logging with rich output."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MobileRun AutoTest v3.0 - AI-powered mobile automation testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mobilerun-autotest --suite smoke
  mobilerun-autotest --suite full --device emulator-5554
  mobilerun-autotest --suite smoke --only test_login --only test_logout
  mobilerun-autotest --suite smoke --show-goals
  mobilerun-autotest --suite full --parallel 3 --rate-limit 2.0

For more information: https://github.com/droidrun/mobilerun
        """,
    )

    parser.add_argument(
        "--suite",
        choices=["smoke", "full", "all"],
        default="smoke",
        help="Test suite to run (default: smoke)",
    )

    parser.add_argument(
        "--device",
        "-d",
        metavar="SERIAL",
        help="Device serial (default: auto-detect)",
    )

    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="ID",
        help="Run only specific test case IDs (repeatable)",
    )

    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=Path("./cases"),
        metavar="PATH",
        help="Cases directory (default: ./cases)",
    )

    parser.add_argument(
        "--report-dir",
        type=Path,
        metavar="PATH",
        help="Report output directory (default: ./autotest-reports)",
    )

    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="MobileRun config file (default: auto-detect)",
    )

    parser.add_argument(
        "--show-goals",
        action="store_true",
        help="Print compiled goals without execution (debug)",
    )

    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop suite on first FAIL/ERROR",
    )

    parser.add_argument(
        "--rate-limit",
        type=float,
        metavar="RPS",
        help="Rate limit: max agent executions per second",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"mobilerun-autotest {__version__}",
    )

    args = parser.parse_args()

    setup_logging(debug=args.debug)

    # --show-goals: print compiled goals without execution
    if args.show_goals:
        runner = TestRunner(
            config_path=args.config,
            cases_dir=args.cases_dir,
        )
        runner.show_goals(args.suite)
        return 0

    # Check cases directory exists
    if not args.cases_dir.is_dir():
        console.print(f"[red]❌ Cases directory not found: {args.cases_dir}[/red]")
        console.print("\nExpected structure:")
        console.print("  cases/")
        console.print("    smoke/")
        console.print("      test1.yaml")
        console.print("      test2.yaml")
        console.print("    full/")
        console.print("      test3.yaml")
        return 2

    # Run tests
    try:
        runner = TestRunner(
            config_path=args.config,
            device_id=args.device,
            cases_dir=args.cases_dir,
            report_dir=args.report_dir,
            rate_limit=args.rate_limit,
            print_fn=console.print,
        )

        exit_code = asyncio.run(
            runner.run_suite(
                suite=args.suite,
                only=args.only or None,
                stop_on_error=args.stop_on_error,
            )
        )

        return exit_code

    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/red]")
        return 2
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        return 2
    except KeyboardInterrupt:
        console.print("\n[yellow]⏹️  Interrupted[/yellow]")
        return 130
    except Exception as e:
        console.print(f"[red]❌ Unexpected error: {e}[/red]")
        if args.debug:
            import traceback
            console.print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
