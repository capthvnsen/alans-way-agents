"""The test transport must time out even with a partial JSON frame."""
import os
from types import SimpleNamespace
import unittest

from router_test_support import recv_json


class JsonFrameTests(unittest.TestCase):
    def setUp(self):
        read, write = os.pipe()
        self.proc = SimpleNamespace(stdout=self.enterContext(os.fdopen(read, "rb")))
        self.writer = self.enterContext(os.fdopen(write, "wb", buffering=0))

    def test_partial_frame_has_a_deadline_and_can_finish_later(self):
        self.writer.write(b'{"text":"\xe2')
        with self.assertRaisesRegex(AssertionError, "no complete JSON frame"):
            recv_json(self.proc, timeout=0.01)
        self.assertIsNone(recv_json(self.proc, timeout=0.01, required=False))
        self.writer.write(b'\x82\xac"}\n')
        self.assertEqual(recv_json(self.proc), {"text": "€"})

    def test_coalesced_frames_do_not_wait_for_more_pipe_data(self):
        self.writer.write(b'{"id":1}\n{"id":2}\n')
        self.assertEqual(recv_json(self.proc), {"id": 1})
        self.assertEqual(recv_json(self.proc), {"id": 2})

    def test_eof_with_a_partial_frame_fails_promptly(self):
        self.writer.write(b'{')
        self.writer.close()
        with self.assertRaisesRegex(AssertionError, "stdout closed"):
            recv_json(self.proc)
