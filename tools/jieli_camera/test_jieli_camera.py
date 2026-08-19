import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from jieli_camera import (
    CTP_SIGNATURE,
    FRAME_H264,
    FRAME_HEADER,
    FrameSink,
    UDPVideoReceiver,
    encode_ctp,
    read_ctp,
)


class CTPTests(unittest.TestCase):
    def test_open_stream_packet_matches_apk_layout(self) -> None:
        packet = encode_ctp(
            "OPEN_RT_STREAM",
            "PUT",
            {"format": "1", "w": "1280", "h": "720", "fps": "30"},
        )
        payload = b'{"op":"PUT","param":{"format":"1","w":"1280","h":"720","fps":"30"}}'
        expected = (
            CTP_SIGNATURE
            + struct.pack("<H", len(b"OPEN_RT_STREAM"))
            + b"OPEN_RT_STREAM"
            + struct.pack("<I", len(payload))
            + payload
        )
        self.assertEqual(packet, expected)

    def test_access_packet_uses_abbreviated_version_key(self) -> None:
        packet = encode_ctp("APP_ACCESS", "PUT", {"type": "0", "ver": "20701"})
        self.assertIn(b'{"op":"PUT","param":{"type":"0","ver":"20701"}}', packet)

    def test_read_ctp_round_trip(self) -> None:
        left, right = socket.socketpair()
        try:
            packet = encode_ctp("APP_ACCESS", "NOTIFY", {"status": "1"})
            left.sendall(packet)
            message = read_ctp(right)
            self.assertEqual(message.topic, "APP_ACCESS")
            self.assertEqual(message.operation, "NOTIFY")
            self.assertEqual(message.params, {"status": "1"})
        finally:
            left.close()
            right.close()


class UDPReassemblyTests(unittest.TestCase):
    def test_reassembles_out_of_order_chunks(self) -> None:
        frames = []
        receiver = UDPVideoReceiver(0, frames.append)
        payload = b"\x00\x00\x00\x01\x67" + b"x" * 20
        second = payload[10:]
        first = payload[:10]
        packet2 = FRAME_HEADER.pack(FRAME_H264, 0, len(second), 7, len(payload), 10, 9000) + second
        packet1 = FRAME_HEADER.pack(FRAME_H264, 0, len(first), 7, len(payload), 0, 9000) + first
        receiver._consume_datagram(packet2)
        self.assertEqual(frames, [])
        receiver._consume_datagram(packet1)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].payload, payload)
        self.assertEqual(frames[0].sequence, 7)


if __name__ == "__main__":
    unittest.main()
