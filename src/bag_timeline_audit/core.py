"""Inspect stored order; never sort before detecting clock regressions."""
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path
import sqlite3
import statistics
import struct
from .common import Findings, integer, loads, text


def records(path, max_records=1_000_000):
    path = Path(path)
    integer(max_records, 'max_records', 1)
    if path.suffix.lower() in {'.db3', '.sqlite3', '.sqlite'}:
        connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            connection.execute('PRAGMA query_only=ON')
            for i, (_, topic, stamp) in enumerate(connection.execute(
                    'SELECT m.id, t.name, m.timestamp FROM messages AS m '
                    'LEFT JOIN topics AS t ON m.topic_id=t.id ORDER BY m.id')):
                if i >= max_records:
                    raise ValueError('Record limit exceeded; no partial success report emitted.')
                yield {'topic': topic, 'record_ns': stamp}
        finally:
            connection.close()
    elif path.suffix.lower() == '.mcap':
        try:
            from mcap.reader import NonSeekingReader
            from mcap.exceptions import McapError
        except ImportError as exc:
            raise ValueError('Install bag-timeline-audit[mcap] to read MCAP.') from exc
        with path.open('rb') as stream:
            try:
                reader = NonSeekingReader(stream, validate_crcs=True, record_size_limit=64 * 1024 * 1024)
                for i, (_, channel, message) in enumerate(reader.iter_messages(log_time_order=False)):
                    if i >= max_records:
                        raise ValueError('Record limit exceeded; no partial success report emitted.')
                    yield {'topic': channel.topic, 'record_ns': message.log_time,
                           'publish_ns': message.publish_time}
            except (McapError, EOFError, struct.error) as exc:
                raise ValueError('Malformed or incomplete MCAP input.') from exc
    elif path.suffix.lower() == '.jsonl':
        with path.open('r', encoding='utf-8-sig') as stream:
            i = 0
            while line := stream.readline(1024 * 1024 + 1):
                if len(line) > 1024 * 1024:
                    raise ValueError('JSONL line exceeds 1 MiB.')
                if not line.strip():
                    continue
                if i >= max_records:
                    raise ValueError('Record limit exceeded; no partial success report emitted.')
                yield loads(line)
                i += 1
    else:
        raise ValueError('Use a single .db3, .sqlite3, .mcap, or .jsonl file; bag directories are not inferred.')


def nearest_offsets(source, target):
    target = sorted(target)
    offsets = []
    for stamp in source:
        index = bisect_left(target, stamp)
        candidates = target[max(0, index - 1):index + 1]
        chosen = min(candidates, key=lambda value: (abs(value - stamp), value))
        offsets.append(chosen - stamp)
    return offsets


def audit(rows, gap_ns=1_000_000_000, pair=None, pair_clock='record_ns',
          same_clock=False, max_records=1_000_000):
    integer(gap_ns, 'gap_ns', 1)
    integer(max_records, 'max_records', 1)
    if pair_clock not in {'record_ns', 'header_ns', 'publish_ns'}:
        raise ValueError('Unsupported pair clock.')
    findings = Findings()
    topics = defaultdict(lambda: defaultdict(list))
    count = 0
    for row in rows:
        if count >= max_records:
            raise ValueError('Record limit exceeded; no partial success report emitted.')
        if not isinstance(row, dict):
            raise ValueError('Each timestamp record must be an object.')
        topic = text(row.get('topic'), 'topic')
        integer(row.get('record_ns'), 'record_ns')
        count += 1
        for clock in ('record_ns', 'header_ns', 'publish_ns'):
            if row.get(clock) is not None:
                value = integer(row[clock], clock)
                prior = topics[topic][clock]
                if prior:
                    delta = value - prior[-1]
                    if delta < 0:
                        findings.add('timestamp_regression', 'warning',
                                     'Timestamp decreased in stored message order.', topic=topic, clock=clock,
                                     record=count, previous_ns=prior[-1], current_ns=value)
                    elif delta == 0:
                        findings.add('duplicate_timestamp', 'warning',
                                     'Equal timestamps can make playback ordering ambiguous.', topic=topic,
                                     clock=clock, record=count)
                    elif delta > gap_ns:
                        findings.add('large_gap', 'warning',
                                     'Gap exceeds the configured threshold; this does not prove message loss.',
                                     topic=topic, clock=clock, record=count, gap_ns=delta)
                prior.append(value)
    if not count:
        findings.add('empty_input', 'error', 'No messages were observed.')
    summaries = {}
    for topic, clocks in sorted(topics.items()):
        summaries[topic] = {}
        for clock, values in clocks.items():
            duration = max(values) - min(values)
            ordered_deltas = [b - a for a, b in zip(values, values[1:]) if b > a]
            summaries[topic][clock] = dict(count=len(values), min_ns=min(values), max_ns=max(values),
                                          span_ns=duration,
                                          span_rate_hz=(len(values) - 1) * 1e9 / duration if duration else None,
                                          median_positive_step_ns=statistics.median(ordered_deltas)
                                          if ordered_deltas else None)
    pairing = None
    if pair:
        if len(pair) != 2 or pair[0] == pair[1]:
            raise ValueError('Pair requires two different topic names.')
        if not same_clock:
            raise ValueError('Cross-topic pairing requires --same-clock; clock identity cannot be inferred.')
        a, b = pair
        av, bv = topics.get(a, {}).get(pair_clock, []), topics.get(b, {}).get(pair_clock, [])
        if not av or not bv:
            findings.add('missing_pair_topic', 'error', 'Pair topic or selected clock has no samples.')
        else:
            offsets = nearest_offsets(av, bv)
            pairing = dict(source=a, target=b, clock=pair_clock, matched=len(offsets),
                           median_signed_offset_ns=statistics.median(offsets),
                           max_absolute_offset_ns=max(map(abs, offsets)),
                           semantics='Directional nearest sample; many-to-one, not synchronization proof.')
    return dict(tool='bag-timeline-audit', schema_version=1, records=count, topics=summaries,
                pairing=pairing, **findings.report())
