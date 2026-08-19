# Jieli W-Car camera client

This is a dependency-free macOS/Python client reconstructed from the Android
APK in `com.spd.stream.dv.wcar_271.apk_Decompiler.com`.

## What was decoded

The camera command protocol uses TCP port `3333`. Every command is:

```text
"CTP:"
uint16_le topic_length
topic bytes
uint32_le JSON_length
compact JSON bytes
```

Live input is selected by `net_type` in the camera's device description:

- `net_type=0`: TCP from camera port `2229`
- `net_type=1`: UDP delivered to the client on port `2224` (front) or `2225` (rear)

The Android APK's `6666`/`1234` ports are only loopback RTP outputs produced by
`libjl_player.so`; they are not camera-facing ports.

## Camera-Wi-Fi handoff

First connect the Mac to the camera's `W-Car...` Wi-Fi network. Internet access
is not required. In Terminal, run:

```bash
cd /Users/starkguo/Documents/chengstark.github.io/tools/jieli_camera
python3 jieli_camera.py info 2>&1 | tee ~/Desktop/jieli_camera_info.log
python3 jieli_camera.py capture --format h264 --seconds 20 --output ~/Desktop/jieli_capture.h264 --play 2>&1 | tee ~/Desktop/jieli_camera_capture.log
```

The capture command reads `dev_desc.txt`, selects TCP or UDP, performs the
`APP_ACCESS` handshake, starts heartbeats, sends `OPEN_RT_STREAM`, reconstructs
the Jieli frame stream, writes Annex-B H.264 (or MJPEG when the camera reports
`rts_type=0`), and sends `CLOSE_RT_STREAM` when finished.

If no frames arrive, force the other transport:

```bash
python3 jieli_camera.py capture --format h264 --transport tcp --seconds 20 --output ~/Desktop/jieli_tcp.h264
python3 jieli_camera.py capture --format h264 --transport udp --seconds 20 --output ~/Desktop/jieli_udp.h264
```

To convert a successful capture to MP4:

```bash
ffmpeg -framerate 30 -i ~/Desktop/jieli_capture.h264 -c copy ~/Desktop/jieli_capture.mp4
```

Keep the complete Terminal output if capture fails. It includes the device
description, CTP replies, selected transport, and any rejected frame header.
The `tee` commands above preserve those logs on the Desktop while the Mac is
offline from the internet.
