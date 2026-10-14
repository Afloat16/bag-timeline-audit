# bag-timeline-audit

Read-only ROS 2 SQLite and MCAP timestamp diagnostics: gaps, regressions, duplicates and cross-topic alignment.

**English** · [简体中文](README.zh-CN.md) · [Demand evidence](docs/EVIDENCE.md) · [License](LICENSE)

Independent, experimental utility maintained by **Afloat16**. Original implementation; no upstream endorsement is implied.

## Install

Python 3.10+.

```bash
git clone https://github.com/Afloat16/bag-timeline-audit.git
cd bag-timeline-audit
python -m venv .venv
# Activate the virtual environment for your OS, then:
python -m pip install -e '.[dev,mcap]'
```

The core package uses the Python standard library only. No GPU, ROS runtime, API key, hosted service or model weights are required for the core offline workflow. Native MCAP requires the optional mcap extra.

## First run

```bash
bag-timeline-audit examples/timestamps.jsonl --pair /left /right --same-clock
bag-timeline-audit recording_0.db3 --gap-ns 100000000 --output report.json
bag-timeline-audit recording_0.mcap --strict
```

## Inputs and checks

One native ROS 2 SQLite file (.db3, .sqlite3, .sqlite), one MCAP file, or JSONL. JSONL rows require `topic` and integer `record_ns`; optional `header_ns` and `publish_ns` remain separate clocks. SQLite reads stored order by message ID, without decoding CDR payloads. MCAP reads physical order and log/publication timestamps without decoding payloads.

Detects regressions, equal timestamps and configurable gaps in stored order. Reports span/rate estimates and positive-step medians. Directional nearest-sample pairing requires `--same-clock`; use `--pair-clock header_ns` only when that field is present and clocks are verified.

## Boundaries

A gap does not prove sensor/transport/recorder loss. Publication and receive clocks are not assumed identical. No replay, repair or rewriting. Bag directories, split-file ordering, compressed SQLite and ROS 1 .bag are not inferred. Native inputs should be trusted; readers are not a sandbox. Default record limit 1,000,000; exceeding `--max-records` fails instead of emitting partial success. JSONL lines are limited to 1 MiB.

## Output and development

Audit commands exit 0 for no error findings, 1 for errors (also warnings with --strict), and 2 for malformed input/report-write failure. --output creates a new JSON file exclusively; existing files are never overwritten. Detailed audit findings are capped at 200 while total severity counts remain accurate.

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m build
```

The configured CI matrix covers Ubuntu, Windows and macOS with Python 3.10/3.13; inspect Actions for actual results. Fixtures are synthetic. No private captures or upstream user attachments are redistributed.

Report problems with command/version, expected/actual result and a minimal synthetic reproduction. Keep source attribution and compatible licensing. MIT license, copyright Afloat16.


## Related projects

[Browse Afloat16's project guide](https://github.com/Afloat16/research-to-fix/blob/main/docs/PROJECTS.md) for robotics diagnostics, model interfaces, 3D geometry and engineering workflows.
