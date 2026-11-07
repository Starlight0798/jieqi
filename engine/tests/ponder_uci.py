#!/usr/bin/env python3
"""Exercise the real UCI process, including commands sent before its worker starts."""
import queue
import re
import subprocess
import sys
import threading
import time
import unittest

ENGINE = sys.argv.pop(1)
KNOWN = "r3k4/9/9/9/4P4/9/9/9/9/R3K4 w - 0 1"
TERMINAL = "4k4/3R1R3/9/9/4P4/9/9/9/9/4K4 b - 0 1"


class Engine:
    def __init__(self):
        self.proc = subprocess.Popen([ENGINE], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
        self.lines = queue.Queue()
        self.transcript = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.send("uci")
        self.options = self.until("uciok")
        self.send("isready")
        self.until("readyok")

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line.strip())

    def send(self, commands):
        self.proc.stdin.write(commands + "\n")
        self.proc.stdin.flush()

    def until(self, prefix, timeout=5):
        seen = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(.001, deadline - time.monotonic()))
            except queue.Empty:
                break
            self.transcript.append(line)
            seen.append(line)
            if line.startswith(prefix):
                return seen
        raise AssertionError(f"no {prefix!r}; recent output: {self.transcript[-12:]}")

    def quiet_bestmove(self, duration=.12):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(.001, deadline - time.monotonic()))
            except queue.Empty:
                return
            self.transcript.append(line)
            if line.startswith("bestmove "):
                raise AssertionError(f"premature output: {line}")

    def close(self):
        try:
            self.send("quit")
            self.proc.wait(timeout=3)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait()
        self.reader.join(timeout=1)
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        self.proc.stdout.close()


class PonderTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine()

    def tearDown(self):
        self.e.close()

    def test_option_and_prediction(self):
        self.assertIn("option name Ponder type check default false", self.e.options)
        self.e.send(f"position fen {KNOWN}\ngo depth 3 searchmoves a0a1")
        self.assertNotIn(" ponder ", self.e.until("bestmove ")[-1])
        self.e.send(f"setoption name Ponder value true\nposition fen {KNOWN}\ngo depth 3 searchmoves a0a1")
        self.assertRegex(self.e.until("bestmove ")[-1], r"^bestmove a0a1 ponder [a-i][0-9][a-i][0-9]$")
        self.e.send("position startpos\ngo depth 2")
        self.assertNotIn(" ponder ", self.e.until("bestmove ")[-1])

    def test_depth_limit_waits_and_isready_responds(self):
        self.e.send("position startpos\ngo ponder depth 2")
        self.e.until("info depth 2 ")
        self.e.quiet_bestmove()
        self.e.send("isready")
        self.assertFalse(any(s.startswith("bestmove ") for s in self.e.until("readyok")))
        self.e.send("ponderhit")
        self.e.until("bestmove ")
        self.e.send("ponderhit")  # idle hit is harmless
        self.e.quiet_bestmove(.03)

    def test_ponder_keyword_after_searchmoves(self):
        self.e.send(f"position fen {KNOWN}\ngo depth 1 searchmoves a0a1 ponder")
        self.e.quiet_bestmove()
        self.e.send("ponderhit")
        self.assertTrue(self.e.until("bestmove ")[-1].startswith("bestmove a0a1"))

    def test_node_limit_waits_for_stop(self):
        self.e.send("position startpos\ngo ponder nodes 100")
        self.e.quiet_bestmove()
        self.e.send("stop")
        self.e.until("bestmove ")

    def test_terminal_waits(self):
        self.e.send(f"position fen {TERMINAL}\ngo ponder depth 1")
        self.e.quiet_bestmove()
        self.e.send("ponderhit")
        self.assertEqual("bestmove (none)", self.e.until("bestmove ")[-1])

    def test_early_hit_and_stop(self):
        for threads in (1, 2):
            self.e.send(f"setoption name Threads value {threads}")
            for command in ("ponderhit", "stop"):
                for _ in range(8):
                    self.e.send(f"position startpos\ngo ponder depth 1\n{command}")
                    self.e.until("bestmove ")
        self.e.quiet_bestmove(.03)

    def test_miss_stop_then_new_search(self):
        self.e.send("position startpos\ngo ponder infinite")
        self.e.quiet_bestmove(.05)
        self.e.send("stop")
        self.e.until("bestmove ")
        self.e.send(f"position fen {KNOWN}\ngo depth 2 searchmoves a0a1")
        self.assertTrue(self.e.until("bestmove ")[-1].startswith("bestmove a0a1"))
        self.e.quiet_bestmove(.03)

    def test_hit_starts_wall_clock_and_reuses_search(self):
        for threads in (1, 2):
            self.e.send(f"setoption name Threads value {threads}\nposition startpos\ngo ponder movetime 220")
            self.e.quiet_bestmove(.32)
            before = [int(re.search(r" nodes (\d+)", s)[1]) for s in self.e.transcript
                      if s.startswith("info depth ") and " nodes " in s]
            self.assertTrue(before, "ponder must have done work")
            started = time.monotonic()
            self.e.send("ponderhit")
            lines = self.e.until("bestmove ")
            elapsed = time.monotonic() - started
            self.assertGreater(elapsed, .10, "ponder time must not consume move budget")
            self.assertLess(elapsed, 3)
            after = [int(re.search(r" nodes (\d+)", s)[1]) for s in lines
                     if s.startswith("info depth ") and " nodes " in s]
            if after:
                self.assertGreaterEqual(max(after), max(before), "hit must retain accumulated search")
            self.e.transcript.clear()

    def test_nodestime_and_native_clock_ponder(self):
        for option in ("setoption name NodesTime value 0", "setoption name NodesTime value 100"):
            self.e.send(option + "\nposition startpos\ngo ponder wtime 1000 btime 1000 movestogo 10")
            self.e.quiet_bestmove(.15)
            self.e.send("ponderhit")
            self.e.until("bestmove ")

    def test_quit_during_ponder(self):
        self.e.send("position startpos\ngo ponder infinite\nquit")
        self.assertEqual(0, self.e.proc.wait(timeout=3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
