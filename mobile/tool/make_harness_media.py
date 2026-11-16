"""Generate 40 s test tones (WAV) and solid-colour covers (PNG) for the device harness."""
import math
import struct
import sys
import wave
import zlib
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
RATE = 22050


def tone(path: Path, freq: float, seconds: int = 40) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = bytearray()
        for i in range(RATE * seconds):
            # short beep every second so position changes are audible
            on = (i % RATE) < RATE * 0.6
            v = int(9000 * math.sin(2 * math.pi * freq * i / RATE)) if on else 0
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def png(path: Path, rgb: tuple[int, int, int], size: int = 256) -> None:
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


for name, freq, colour in [("tone-a", 440, (220, 40, 40)), ("tone-b", 554, (40, 180, 60)), ("tone-c", 659, (40, 80, 220))]:
    tone(out / f"{name}.wav", freq)
    png(out / f"{name}.png", colour)
print("ok", sorted(p.name for p in out.iterdir()))
