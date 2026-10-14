import argparse
import sqlite3
import sys
from .common import emit, code
from .core import audit, records


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only ROS bag timestamp diagnostics.')
    parser.add_argument('input')
    parser.add_argument('--gap-ns', type=int, default=1_000_000_000)
    parser.add_argument('--max-records', type=int, default=1_000_000)
    parser.add_argument('--pair', nargs=2, metavar=('SOURCE_TOPIC', 'TARGET_TOPIC'))
    parser.add_argument('--pair-clock', choices=['record_ns', 'header_ns', 'publish_ns'], default='record_ns')
    parser.add_argument('--same-clock', action='store_true')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--output', help='New report file; existing files are never overwritten.')
    args = parser.parse_args(argv)
    try:
        report = audit(records(args.input, args.max_records), args.gap_ns, args.pair,
                       args.pair_clock, args.same_clock, args.max_records)
        emit(report, args.output)
        return code(report, args.strict)
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print(f'Input/report error: {exc}', file=sys.stderr)
        return 2
