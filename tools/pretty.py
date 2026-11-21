#!/usr/bin/env python3
"""Make UNO Q output readable: timestamp, tag and colour each line, and keep a log file.

    <command> | tools/pretty.py --tag PY

Colours: errors red, warnings yellow, [stat] bold, [rec] magenta, [alert] red background,
[mcu]/[boot] green. A plain-text copy goes to logs/<tag>-<date>-<time>.log.
Set NO_COLOR=1 to disable colours.
"""
import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TAG_COLOUR = {"PY": "36", "MCU": "32", "APP": "34"}
RULES = [  # first match wins
    (re.compile(r"\[alert\]", re.I), "1;97;41"),
    (re.compile(r"VERDICT .*: PASS\b"), "1;32"),
    (re.compile(r"VERDICT .*: PARTIAL\b"), "1;33"),
    (re.compile(r"VERDICT .*: FAIL\b"), "1;31"),
    (re.compile(r"^\[test\]\s+→"), "36"),
    (re.compile(r"Traceback|\bError\b|\bERROR\b|Exception|\bfailed\b|\bFAILED\b|✗"), "31"),
    (re.compile(r"\bWARN(ING)?\b|\[warn\]|\bWarning\b"), "33"),
    (re.compile(r"\[rec\]"), "35"),
    (re.compile(r"^\[(stat|live|step)\]"), "1"),
    (re.compile(r"^\[(mcu|boot)\]|connected|\bOK\b"), "32"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="UNOQ")
    ap.add_argument("--no-log", action="store_true", help="do not write a log file")
    args = ap.parse_args()

    colour = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    paint = (lambda code, s: f"\x1b[{code}m{s}\x1b[0m") if colour else (lambda code, s: s)
    tag = paint(TAG_COLOUR.get(args.tag, "37"), f"{args.tag:<3}")

    log = None
    if not args.no_log:
        logdir = Path(__file__).resolve().parent.parent / "logs"
        logdir.mkdir(exist_ok=True)
        log = open(logdir / f"{args.tag.lower()}-{dt.datetime.now():%Y%m%d-%H%M%S}.log", "w")

    try:
        for raw in sys.stdin.buffer:
            text = raw.decode("utf-8", "replace").rstrip("\r\n")
            text = text.split("\r")[-1]  # keep the final state of progress-bar style lines
            plain = ANSI.sub("", text)
            stamp = dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if log:
                log.write(f"{stamp} {args.tag} {plain}\n")
                log.flush()
            body = text
            if colour and text == plain:  # only colour lines that are not coloured already
                for rx, code in RULES:
                    if rx.search(plain):
                        body = paint(code, text)
                        break
            print(f"{paint('2', stamp)} {tag} {body}", flush=True)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    finally:
        if log:
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
