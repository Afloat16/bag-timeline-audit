import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from bag_timeline_audit.core import audit, records, nearest_offsets
from bag_timeline_audit.cli import main


class TimelineTests(unittest.TestCase):
    def test_regression_is_not_hidden_by_sorting(self):
        report = audit([{'topic': '/x', 'record_ns': x} for x in [20, 10, 10, 50]], gap_ns=25)
        self.assertEqual(report['finding_counts'], {'timestamp_regression': 1, 'duplicate_timestamp': 1, 'large_gap': 1})

    def test_subsecond_precision(self):
        report = audit([{'topic': '/x', 'record_ns': x} for x in [10**18, 10**18 + 1]])
        self.assertEqual(report['topics']['/x']['record_ns']['span_ns'], 1)

    def test_clock_pairing_requires_explicit_assertion(self):
        rows = [{'topic': '/a', 'record_ns': 10}, {'topic': '/b', 'record_ns': 12}]
        with self.assertRaises(ValueError):
            audit(rows, pair=['/a', '/b'])
        self.assertEqual(audit(rows, pair=['/a', '/b'], same_clock=True)['pairing']['max_absolute_offset_ns'], 2)

    def test_tie_is_deterministic(self):
        self.assertEqual(nearest_offsets([5], [10, 0]), [-5])

    def test_record_limit_never_returns_partial_success(self):
        with self.assertRaises(ValueError):
            audit([{'topic': '/a', 'record_ns': 1}] * 2, max_records=1)

    def test_empty_and_invalid(self):
        self.assertEqual(audit([])['error_count'], 1)
        for value in [True, -1, 1.5]:
            with self.assertRaises(ValueError):
                audit([{'topic': '/a', 'record_ns': value}])

    def test_sqlite_readonly_and_stored_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bag.db3'
            connection = sqlite3.connect(path)
            connection.executescript('CREATE TABLE topics(id INTEGER PRIMARY KEY,name TEXT);'
                                     'CREATE TABLE messages(id INTEGER PRIMARY KEY,topic_id INTEGER,timestamp INTEGER,data BLOB);'
                                     "INSERT INTO topics VALUES(1,'/x');"
                                     "INSERT INTO messages VALUES(1,1,20,X'00');"
                                     "INSERT INTO messages VALUES(2,1,10,X'00');")
            connection.close()
            before = path.read_bytes()
            report = audit(records(path))
            self.assertEqual(report['finding_counts']['timestamp_regression'], 1)
            self.assertEqual(before, path.read_bytes())

    def test_mcap_native_order(self):
        from mcap.writer import Writer, CompressionType
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bag.mcap'
            with path.open('wb') as stream:
                writer = Writer(stream, compression=CompressionType.NONE)
                writer.start()
                channel = writer.register_channel('/x', 'json', 0)
                writer.add_message(channel, 20, b'{}', 19)
                writer.add_message(channel, 10, b'{}', 9)
                writer.finish()
            report = audit(records(path))
            self.assertEqual(report['records'], 2)
            self.assertEqual(report['finding_counts']['timestamp_regression'], 2)

    def test_jsonl_and_cli_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.jsonl'
            path.write_text('{"topic":"/x","record_ns":1}\n', encoding='utf-8')
            output = Path(tmp) / 'report.json'
            self.assertEqual(main([str(path), '--output', str(output)]), 0)
            self.assertEqual(json.loads(output.read_text())['records'], 1)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path), '--output', str(output)]), 2)
            self.assertEqual(list(records(path))[0]['record_ns'], 1)

    def test_malformed_mcap_is_an_input_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.mcap'
            path.write_bytes(b'not an mcap')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path)]),2)

    def test_findings_limit_preserves_error_count(self):
        rows = [{'topic': '/x', 'record_ns': 1}] * 205
        report = audit(rows, pair=['/x', '/missing'], same_clock=True)
        self.assertTrue(report['findings_truncated'])
        self.assertEqual(report['error_count'], 1)

    def test_stdout_json_is_safe_for_non_utf8_console(self):
        from bag_timeline_audit.common import emit
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            emit({'topic':'/机器人'})
        self.assertTrue(stream.getvalue().isascii())
        self.assertEqual(json.loads(stream.getvalue())['topic'],'/机器人')
