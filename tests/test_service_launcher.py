"""真实 Bash 启动器参数检查；不访问摄像头、systemd 或 engine。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash'), '需要 Linux/Bash')
class ServiceLauncherTests(unittest.TestCase):
    def run_launcher(self, extra):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            binary = work / 'fake-runtime'
            binary.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            binary.chmod(0o755)
            engine = work / 'not-a-model.plan'
            engine.touch()
            env = {k: v for k, v in os.environ.items() if not k.startswith('EDGE_VISION_')}
            env.update(STATE_DIRECTORY=str(work / 'state'), EDGE_VISION_BINARY=str(binary),
                       EDGE_VISION_ENGINE=str(engine))
            env.update(extra)
            result = subprocess.run(['bash', str(ROOT / 'scripts/run_edge_vision_service.sh')],
                                    env=env, capture_output=True, text=True, timeout=10)
            args = json.loads(result.stdout.splitlines()[-1]) if result.returncode == 0 else []
            return result, args

    def test_legacy_no_candidate_flags_or_video(self):
        result, args = self.run_launcher({'EDGE_VISION_EVENT_ROI': '0.2 0.35 0.8 0.95'})
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ('--event-line-confirm-seconds', '--event-roi-exit-margin', '--event-clip-encoder',
                       '--event-clip-capacity', '--event-clip-share-overlap', '--output-video', '--frames'):
            self.assertNotIn(option, args)
        self.assertIn('--continuous', args)
        self.assertEqual(args[args.index('--warmup-frames') + 1], '30')
        self.assertEqual(args[args.index('--score-threshold') + 1], '0.3')

    def test_profile_complete_and_event_only(self):
        profile = {}
        for line in (ROOT / 'deploy/systemd/event-evidence.env.example').read_text().splitlines():
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                profile[key] = value.strip('"')
        result, args = self.run_launcher({**profile, 'EDGE_VISION_EVENT_ROI': '0.2 0.35 0.8 0.95'})
        self.assertEqual(result.returncode, 0, result.stderr)
        for option, value in {'--match-threshold': '0.8', '--event-line-confirm-seconds': '0.2',
                              '--event-roi-exit-margin': '0.02', '--event-roi-exit-seconds': '0.5',
                              '--event-clip-encoder': 'x264', '--event-clip-capacity': '8',
                              '--event-clip-bitrate-kbps': '10000', '--event-clip-max-shared-seconds': '6',
                              '--event-clip-max-shared-events': '32'}.items():
            self.assertEqual(args.count(option), 1)
            self.assertEqual(args[args.index(option) + 1], value)
        self.assertIn('--event-clip-share-overlap', args)
        for option in ('--event-jsonl', '--event-snapshot-dir', '--event-clip-dir'):
            self.assertIn(option, args)
        self.assertNotIn('--output-video', args)
        self.assertNotIn('--frames', args)

    def test_literal_not_shell_evaluated(self):
        literal = '$(touch should-not-exist) ; --frames 1'
        result, args = self.run_launcher({'EDGE_VISION_MATCH_THRESHOLD': literal})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args[args.index('--match-threshold') + 1], literal)
        self.assertNotIn('--frames', args)

    def test_invalid_boolean_rejected(self):
        result, _ = self.run_launcher({'EDGE_VISION_EVENT_ROI': '0 0 1 1',
                                       'EDGE_VISION_EVENT_CLIP_SHARE_OVERLAP': 'yes'})
        self.assertNotEqual(result.returncode, 0)

    def test_absent_rules_do_not_enable_evidence(self):
        result, args = self.run_launcher({'EDGE_VISION_EVENT_CLIP_ENCODER': 'x264'})
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('--event-clip-dir', args)
        self.assertNotIn('--event-clip-encoder', args)


if __name__ == '__main__':
    unittest.main()
