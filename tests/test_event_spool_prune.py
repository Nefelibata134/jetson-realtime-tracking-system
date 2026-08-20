import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prune_event_spool.py"
SPEC = importlib.util.spec_from_file_location("prune_event_spool", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class EventSpoolPruneTest(unittest.TestCase):
    def test_prunes_oldest_complete_sessions_and_keeps_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            spool = state / "spool"
            spool.mkdir()
            now = time.time()
            sessions = []
            for index in range(4):
                session = spool / f"session-{index}"
                session.mkdir()
                (session / "evidence.bin").write_bytes(b"x" * 10)
                timestamp = now - (4 - index) * 3600
                os.utime(session, (timestamp, timestamp))
                sessions.append(session)
            (state / "current").symlink_to(sessions[-1], target_is_directory=True)

            removed, retained_bytes = MODULE.prune_spool(
                spool,
                max_bytes=25,
                max_age_days=365,
                keep_latest=1,
                now=now,
            )

            self.assertEqual([path.name for path in removed], [
                "session-0",
                "session-1",
            ])
            self.assertFalse(sessions[0].exists())
            self.assertFalse(sessions[1].exists())
            self.assertTrue(sessions[2].exists())
            self.assertTrue(sessions[3].exists())
            self.assertEqual(retained_bytes, 20)


if __name__ == "__main__":
    unittest.main()
