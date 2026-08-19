#!/usr/bin/env python3
"""Minimal macOS client for the Jieli W-Car camera protocol.

This is based on the protocol implemented by the decompiled Android APK:

* CTP command/control over TCP 3333
* live video over TCP 2229 or UDP 2224 (front) / 2225 (rear)
* a 20-byte little-endian live-frame header

It intentionally uses only Python's standard library so it can run while the
Mac is connected directly to the camera's Wi-Fi network.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable


CAMERA_IP = "192.168.1.1"
CONTROL_PORT = 3333
HTTP_PORT = 8080
TCP_VIDEO_PORT = 2229
UDP_FRONT_PORT = 2224
UDP_REAR_PORT = 2225
APP_VERSION_CODE = "20701"

CTP_SIGNATURE = b"CTP:"
CTP_MAX_PAYLOAD = 5 * 1024 * 1024
FRAME_HEADER = struct.Struct("<BBHIIII")
FRAME_HEADER_SIZE = FRAME_HEADER.size
MAX_FRAME_SIZE = 16 * 1024 * 1024

FRAME_AUDIO = 1
FRAME_JPEG = 2
FRAME_H264 = 3


def log(message: str) -> None:
    print(time.strftime("[%H:%M:%S]"), message, flush=True)


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError(f"socket closed with {size - len(data)} bytes remaining")
        data.extend(chunk)
    return bytes(data)


def encode_ctp(topic: str, operation: str | None = None, params: dict[str, object] | None = None) -> bytes:
    """Reproduce AbstractDeviceSocket.packageCtpData() byte-for-byte."""
    topic_bytes = topic.encode("utf-8")
    if len(topic_bytes) > 0xFFFF:
        raise ValueError("CTP topic is too long")

    if operation:
        body: dict[str, object] = {"op": operation}
        if params is not None:
            # Android serializes every value as a JSON string.
            body["param"] = {str(k): str(v) for k, v in params.items()}
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    else:
        payload = b""

    return b"".join(
        (
            CTP_SIGNATURE,
            struct.pack("<H", len(topic_bytes)),
            topic_bytes,
            struct.pack("<I", len(payload)),
            payload,
        )
    )


@dataclass(frozen=True)
class CTPMessage:
    topic: str
    operation: str | None
    errno: int
    params: dict[str, str]
    raw: dict[str, object]


def read_ctp(sock: socket.socket) -> CTPMessage:
    signature = recv_exact(sock, 4)
    if signature != CTP_SIGNATURE:
        raise ValueError(f"bad CTP signature: {signature!r}")
    topic_len = struct.unpack("<H", recv_exact(sock, 2))[0]
    topic = recv_exact(sock, topic_len).decode("utf-8", errors="replace")
    payload_len = struct.unpack("<I", recv_exact(sock, 4))[0]
    if payload_len > CTP_MAX_PAYLOAD:
        raise ValueError(f"implausible CTP payload length: {payload_len}")
    if not payload_len:
        return CTPMessage(topic, None, 0, {}, {})
    payload = json.loads(recv_exact(sock, payload_len).decode("utf-8"))
    params = payload.get("param") or {}
    return CTPMessage(
        topic=topic,
        operation=payload.get("op"),
        errno=int(payload.get("errno", 0)),
        params={str(k): str(v) for k, v in params.items()},
        raw=payload,
    )


class ControlChannel:
    def __init__(self, host: str, port: int = CONTROL_PORT) -> None:
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.stop_event = threading.Event()
        self.send_lock = threading.Lock()
        self.messages: queue.Queue[CTPMessage] = queue.Queue()
        self.reader_thread: threading.Thread | None = None
        self.heartbeat_thread: threading.Thread | None = None

    def connect(self, timeout: float = 5.0) -> None:
        log(f"connecting control channel to {self.host}:{self.port}")
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(None)
        self.reader_thread = threading.Thread(target=self._reader, name="ctp-reader", daemon=True)
        self.reader_thread.start()

    def send(self, topic: str, operation: str = "PUT", params: dict[str, object] | None = None) -> None:
        if self.sock is None:
            raise RuntimeError("control channel is not connected")
        packet = encode_ctp(topic, operation, params)
        with self.send_lock:
            self.sock.sendall(packet)
        log(f"CTP -> {topic} {operation} {params or {}} ({len(packet)} bytes)")

    def wait_for(self, topic: str, timeout: float) -> CTPMessage | None:
        deadline = time.monotonic() + timeout
        deferred: list[CTPMessage] = []
        try:
            while time.monotonic() < deadline:
                try:
                    message = self.messages.get(timeout=max(0.05, deadline - time.monotonic()))
                except queue.Empty:
                    return None
                if message.topic == topic:
                    return message
                deferred.append(message)
        finally:
            for message in deferred:
                self.messages.put(message)
        return None

    def start_heartbeat(self, period: float = 5.0) -> None:
        def run() -> None:
            while not self.stop_event.wait(period):
                try:
                    self.send("CTP_KEEP_ALIVE")
                except OSError as exc:
                    log(f"heartbeat stopped: {exc}")
                    return

        self.heartbeat_thread = threading.Thread(target=run, name="ctp-heartbeat", daemon=True)
        self.heartbeat_thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
            self.sock = None

    def _reader(self) -> None:
        assert self.sock is not None
        try:
            while not self.stop_event.is_set():
                message = read_ctp(self.sock)
                log(
                    f"CTP <- {message.topic} op={message.operation!r} "
                    f"errno={message.errno} params={message.params}"
                )
                self.messages.put(message)
        except (EOFError, OSError, ValueError, json.JSONDecodeError) as exc:
            if not self.stop_event.is_set():
                log(f"control reader stopped: {exc}")


@dataclass(frozen=True)
class Frame:
    frame_type: int
    flags: int
    sequence: int
    timestamp: int
    payload: bytes


def parse_frame_header(data: bytes) -> tuple[int, int, int, int, int, int, int]:
    if len(data) != FRAME_HEADER_SIZE:
        raise ValueError(f"frame header must be {FRAME_HEADER_SIZE} bytes")
    return FRAME_HEADER.unpack(data)


class FrameSink:
    def __init__(self, output: Path, video_format: str = "h264", play: bool = False) -> None:
        self.output_path = output
        self.output: BinaryIO = output.open("wb")
        self.video_format = video_format
        self.expected_type = FRAME_H264 if video_format == "h264" else FRAME_JPEG
        self.frame_count = 0
        self.byte_count = 0
        self.first_frame = threading.Event()
        self.player: subprocess.Popen[bytes] | None = None
        if play:
            self.player = subprocess.Popen(
                [
                    "ffplay",
                    "-loglevel",
                    "warning",
                    "-fflags",
                    "nobuffer",
                    "-flags",
                    "low_delay",
                    "-framedrop",
                    "-f",
                    video_format,
                    "-i",
                    "-",
                ],
                stdin=subprocess.PIPE,
            )

    def write(self, frame: Frame) -> None:
        if frame.frame_type != self.expected_type:
            return
        self.output.write(frame.payload)
        self.output.flush()
        self.frame_count += 1
        self.byte_count += len(frame.payload)
        self.first_frame.set()
        if self.player is not None and self.player.stdin is not None:
            try:
                self.player.stdin.write(frame.payload)
                self.player.stdin.flush()
            except (BrokenPipeError, OSError):
                self.player = None
        if self.frame_count <= 5 or self.frame_count % 30 == 0:
            prefix = frame.payload[:8].hex(" ")
            log(
                f"{self.video_format.upper()} frame #{self.frame_count} seq={frame.sequence} "
                f"timestamp={frame.timestamp} bytes={len(frame.payload)} prefix={prefix}"
            )

    def close(self) -> None:
        self.output.close()
        if self.player is not None:
            if self.player.stdin is not None:
                self.player.stdin.close()
            try:
                self.player.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.player.terminate()


class TCPVideoReceiver:
    def __init__(self, host: str, port: int, on_frame: Callable[[Frame], None]) -> None:
        self.host = host
        self.port = port
        self.on_frame = on_frame
        self.sock: socket.socket | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.error: Exception | None = None

    def start(self) -> None:
        log(f"connecting TCP video receiver to {self.host}:{self.port}")
        self.sock = socket.create_connection((self.host, self.port), timeout=5.0)
        self.sock.settimeout(1.0)
        self.thread = threading.Thread(target=self._run, name="tcp-video", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.sock is not None:
            self.sock.close()

    def _run(self) -> None:
        assert self.sock is not None
        try:
            while not self.stop_event.is_set():
                try:
                    header = recv_exact(self.sock, FRAME_HEADER_SIZE)
                except socket.timeout:
                    continue
                frame_type, flags, _chunk_len, sequence, frame_size, _offset, timestamp = parse_frame_header(header)
                frame_type &= 0x7F
                if frame_type not in (FRAME_AUDIO, FRAME_JPEG, FRAME_H264):
                    raise ValueError(f"unknown TCP frame type {frame_type}; header={header.hex()}")
                if not 0 < frame_size <= MAX_FRAME_SIZE:
                    raise ValueError(f"implausible TCP frame size {frame_size}; header={header.hex()}")
                payload = recv_exact(self.sock, frame_size)
                self.on_frame(Frame(frame_type, flags, sequence, timestamp, payload))
        except (EOFError, OSError, ValueError) as exc:
            self.error = exc
            if not self.stop_event.is_set():
                log(f"TCP video receiver stopped: {exc}")


@dataclass
class _Assembly:
    frame_type: int
    flags: int
    frame_size: int
    timestamp: int
    chunks: dict[int, bytes]


class UDPVideoReceiver:
    def __init__(self, port: int, on_frame: Callable[[Frame], None]) -> None:
        self.port = port
        self.on_frame = on_frame
        self.sock: socket.socket | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.error: Exception | None = None
        self.assemblies: dict[int, _Assembly] = {}

    def start(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", self.port))
        self.sock.settimeout(1.0)
        log(f"listening for UDP video on 0.0.0.0:{self.port}")
        self.thread = threading.Thread(target=self._run, name="udp-video", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.sock is not None:
            self.sock.close()

    def _run(self) -> None:
        assert self.sock is not None
        try:
            while not self.stop_event.is_set():
                try:
                    packet, _source = self.sock.recvfrom(256 * 1024)
                except socket.timeout:
                    continue
                self._consume_datagram(packet)
        except (OSError, ValueError) as exc:
            self.error = exc
            if not self.stop_event.is_set():
                log(f"UDP video receiver stopped: {exc}")

    def _consume_datagram(self, packet: bytes) -> None:
        cursor = 0
        while len(packet) - cursor >= FRAME_HEADER_SIZE:
            raw_header = packet[cursor : cursor + FRAME_HEADER_SIZE]
            frame_type, flags, chunk_size, sequence, frame_size, offset, timestamp = parse_frame_header(raw_header)
            frame_type &= 0x7F
            cursor += FRAME_HEADER_SIZE
            if frame_type not in (FRAME_AUDIO, FRAME_JPEG, FRAME_H264):
                raise ValueError(f"unknown UDP frame type {frame_type}; header={raw_header.hex()}")
            if not 0 < frame_size <= MAX_FRAME_SIZE:
                raise ValueError(f"implausible UDP frame size {frame_size}; header={raw_header.hex()}")
            if chunk_size > len(packet) - cursor:
                raise ValueError(
                    f"UDP chunk says {chunk_size} bytes, only {len(packet) - cursor} remain; "
                    f"header={raw_header.hex()}"
                )
            if offset + chunk_size > frame_size:
                raise ValueError(
                    f"UDP chunk range {offset}:{offset + chunk_size} exceeds frame size {frame_size}"
                )
            chunk = packet[cursor : cursor + chunk_size]
            cursor += chunk_size
            assembly = self.assemblies.get(sequence)
            if assembly is None or assembly.frame_size != frame_size:
                assembly = _Assembly(frame_type, flags, frame_size, timestamp, {})
                self.assemblies[sequence] = assembly
            assembly.chunks.setdefault(offset, chunk)
            self._maybe_emit(sequence, assembly)

        # Keep at most the newest few incomplete frames.
        if len(self.assemblies) > 8:
            for sequence in list(self.assemblies)[:-8]:
                del self.assemblies[sequence]

    def _maybe_emit(self, sequence: int, assembly: _Assembly) -> None:
        expected = 0
        ordered: list[bytes] = []
        for offset in sorted(assembly.chunks):
            chunk = assembly.chunks[offset]
            if offset != expected:
                return
            ordered.append(chunk)
            expected += len(chunk)
        if expected != assembly.frame_size:
            return
        payload = b"".join(ordered)
        del self.assemblies[sequence]
        self.on_frame(
            Frame(assembly.frame_type, assembly.flags, sequence, assembly.timestamp, payload)
        )


def fetch_device_description(host: str, timeout: float = 3.0) -> dict[str, object] | None:
    url = f"http://{host}:{HTTP_PORT}/mnt/spiflash/res/dev_desc.txt"
    log(f"fetching {url}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            log(f"device description: {json.dumps(result, ensure_ascii=False, sort_keys=True)}")
            return result
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        log(f"device description unavailable: {exc}")
        return None


def resolve_transport(requested: str, description: dict[str, object] | None) -> str:
    if requested != "auto":
        return requested
    if description is not None:
        net_type = str(description.get("net_type", ""))
        if net_type == "0":
            return "tcp"
        if net_type == "1":
            return "udp"
    log("net_type is unknown; defaulting to UDP (use --transport tcp if needed)")
    return "udp"


def capture(args: argparse.Namespace) -> int:
    description = fetch_device_description(args.host)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    control = ControlChannel(args.host, args.control_port)
    receiver: TCPVideoReceiver | UDPVideoReceiver | None = None
    sink: FrameSink | None = None
    camera_number = 1 if args.camera == "rear" else 0
    open_topic = "OPEN_PULL_RT_STREAM" if camera_number else "OPEN_RT_STREAM"
    close_topic = "CLOSE_PULL_RT_STREAM" if camera_number else "CLOSE_RT_STREAM"

    try:
        control.connect()
        control.send("APP_ACCESS", params={"type": "0", "ver": args.app_version})
        access = control.wait_for("APP_ACCESS", timeout=args.access_timeout)
        if access is None:
            log("no APP_ACCESS reply yet; continuing because some firmware replies late")
        elif access.errno != 0:
            raise RuntimeError(f"camera rejected APP_ACCESS with errno={access.errno}")
        control.start_heartbeat()

        # The Android app downloads dev_desc.txt only after APP_ACCESS succeeds.
        # Retry here in case the HTTP resource was gated or not ready before it.
        if description is None:
            description = fetch_device_description(args.host)
        transport = resolve_transport(args.transport, description)
        if description is not None and args.format == "auto":
            wire_format = str(description.get("rts_type", "1"))
        else:
            wire_format = "1" if args.format in ("auto", "h264") else "0"
        video_format = "h264" if wire_format == "1" else "mjpeg"
        sink = FrameSink(output, video_format=video_format, play=args.play)

        if transport == "tcp":
            receiver = TCPVideoReceiver(args.host, args.tcp_video_port, sink.write)
        else:
            udp_port = args.udp_port or (UDP_REAR_PORT if camera_number else UDP_FRONT_PORT)
            receiver = UDPVideoReceiver(udp_port, sink.write)
        receiver.start()

        control.send(
            open_topic,
            params={
                "format": wire_format,
                "w": str(args.width),
                "h": str(args.height),
                "fps": str(args.fps),
            },
        )
        open_reply = control.wait_for(open_topic, timeout=3.0)
        if open_reply is not None and open_reply.errno != 0:
            raise RuntimeError(f"camera rejected {open_topic} with errno={open_reply.errno}")

        log(
            f"capturing {args.camera} {video_format.upper()} via {transport.upper()} "
            f"for {args.seconds:g}s "
            f"to {output}"
        )
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            if sink.first_frame.wait(timeout=min(1.0, max(0.0, deadline - time.monotonic()))):
                break
        if not sink.first_frame.is_set():
            raise RuntimeError(
                f"no {video_format.upper()} frames arrived via {transport.upper()}; "
                f"inspect this log and retry "
                f"with --transport {'tcp' if transport == 'udp' else 'udp'}"
            )
        while time.monotonic() < deadline:
            time.sleep(min(0.25, deadline - time.monotonic()))

        log(f"captured {sink.frame_count} {video_format.upper()} frames / {sink.byte_count} bytes")
        return 0
    finally:
        try:
            if control.sock is not None:
                control.send(close_topic, params={"status": "1"})
        except OSError:
            pass
        if receiver is not None:
            receiver.close()
        control.close()
        if sink is not None:
            sink.close()


def show_info(args: argparse.Namespace) -> int:
    description = fetch_device_description(args.host)
    for port, label in ((args.control_port, "control TCP"), (args.tcp_video_port, "video TCP")):
        try:
            with socket.create_connection((args.host, port), timeout=2.0):
                log(f"{label} {args.host}:{port} is reachable")
        except OSError as exc:
            log(f"{label} {args.host}:{port} is not reachable: {exc}")
    if description is None:
        return 1
    transport = resolve_transport("auto", description)
    log(f"camera reports live transport={transport}, format={description.get('rts_type', 'unknown')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=CAMERA_IP, help="camera IP (default: %(default)s)")
    parser.add_argument("--control-port", type=int, default=CONTROL_PORT)
    parser.add_argument("--tcp-video-port", type=int, default=TCP_VIDEO_PORT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser("info", help="read dev_desc.txt and probe TCP ports")
    info_parser.set_defaults(func=show_info)

    capture_parser = subparsers.add_parser("capture", help="start and capture the live H.264 stream")
    capture_parser.add_argument("--transport", choices=("auto", "tcp", "udp"), default="auto")
    capture_parser.add_argument("--camera", choices=("front", "rear"), default="front")
    capture_parser.add_argument("--format", choices=("auto", "h264", "jpeg"), default="auto")
    capture_parser.add_argument("--width", type=int, default=1280)
    capture_parser.add_argument("--height", type=int, default=720)
    capture_parser.add_argument("--fps", type=int, default=30)
    capture_parser.add_argument("--seconds", type=float, default=20.0)
    capture_parser.add_argument("--output", default="jieli_capture.h264")
    capture_parser.add_argument("--udp-port", type=int, help="override UDP listen port")
    capture_parser.add_argument("--app-version", default=APP_VERSION_CODE)
    capture_parser.add_argument("--access-timeout", type=float, default=3.0)
    capture_parser.add_argument("--play", action="store_true", help="also pipe H.264 into ffplay")
    capture_parser.set_defaults(func=capture)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        log("interrupted")
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
