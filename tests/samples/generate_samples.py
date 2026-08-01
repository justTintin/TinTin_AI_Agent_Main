# -*- coding: utf-8 -*-
"""样本生成器：生成测试用视频 / 图片 / 音频样本（纯标准库，可重复执行，已存在则跳过）。

用法:
    python tests/samples/generate_samples.py [--force]

生成:
    samples/video/sample_gradient_2s.avi     320x240, 2s, 15fps，渐变+运动方块
    samples/image/sample_gradient_640x480.png  8-bit RGB 渐变图
    samples/audio/test_tone_1s.wav           16kHz 16bit 440Hz 正弦 1s
"""
import argparse
import math
import os
import struct
import wave
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------- AVI (uncompressed rawvideo, RGB24) ----------
def _write_avi(path, width, height, fps, n_frames):
    frame_size = width * height * 3

    def write_chunk(f, tag, data):
        f.write(tag)
        f.write(struct.pack("<I", len(data)))
        f.write(data)
        if len(data) % 2:
            f.write(b"\x00")

    def build_avih():
        b = bytearray(56)
        struct.pack_into("<I", b, 0, 1000000 // fps)
        struct.pack_into("<I", b, 12, 0x10)          # AVIF_HASINDEX
        struct.pack_into("<I", b, 16, n_frames)
        struct.pack_into("<I", b, 24, 1)
        struct.pack_into("<I", b, 28, frame_size)
        struct.pack_into("<I", b, 32, width)
        struct.pack_into("<I", b, 36, height)
        return bytes(b)

    def build_strh():
        b = bytearray(64)
        b[0:4] = b"vids"
        struct.pack_into("<I", b, 20, 1)             # scale
        struct.pack_into("<I", b, 24, fps)           # rate
        struct.pack_into("<I", b, 32, n_frames)      # length
        struct.pack_into("<I", b, 36, frame_size)
        struct.pack_into("<I", b, 40, 0xFFFFFFFF)    # quality
        struct.pack_into("<i", b, 48, 0)
        struct.pack_into("<i", b, 52, 0)
        struct.pack_into("<i", b, 56, width)
        struct.pack_into("<i", b, 60, height)
        return bytes(b)

    def build_strf():
        return struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24, 0, frame_size, 0, 0, 0, 0)

    with open(path, "wb") as f:
        f.write(b"RIFF"); f.write(struct.pack("<I", 0)); f.write(b"AVI ")
        hdrl = b"avih" + struct.pack("<I", 56) + build_avih()
        strl_list = b"strl" + (b"strh" + struct.pack("<I", 64) + build_strh()) \
                          + (b"strf" + struct.pack("<I", 40) + build_strf())
        hdrl += b"LIST" + struct.pack("<I", len(strl_list)) + strl_list
        write_chunk(f, b"LIST", b"hdrl" + hdrl)

        movi = bytearray()
        for i in range(n_frames):
            frame = bytearray()
            # 渐变底色：R 随 x、G 随 y、B 随时间；中央白色方块随时间右移
            box_x = int(width * 0.2 + (width * 0.5) * (i / max(1, n_frames - 1)))
            for y in range(height):
                for x in range(width):
                    r = (x * 255) // width
                    g = (y * 255) // height
                    b = (i * 255) // n_frames
                    if abs(x - box_x) < 10 and abs(y - height // 2) < 10:
                        r, g, b = 255, 255, 255
                    frame += bytes([b, g, r])
            movi += b"00dc" + struct.pack("<I", frame_size) + frame + (b"\x00" if frame_size % 2 else b"")
        write_chunk(f, b"LIST", b"movi" + bytes(movi))

        idx = bytearray()
        offset = 4
        for _ in range(n_frames):
            idx += struct.pack("<4sIII", b"00dc", 0x10, offset, frame_size)
            offset += 8 + frame_size + frame_size % 2
        write_chunk(f, b"idx1", bytes(idx))

        size = f.tell()
        f.seek(4)
        f.write(struct.pack("<I", size - 8))


# ---------- PNG (8-bit RGB) ----------
def _write_png(path, width, height):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        for x in range(width):
            raw += bytes([(x * 255) // width, (y * 255) // height, 128])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


# ---------- WAV (16-bit PCM mono) ----------
def _write_wav(path, seconds=1.0, freq=440.0, rate=16000):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(32767 * 0.5 * math.sin(2 * math.pi * freq * t / rate)))
            for t in range(int(rate * seconds))
        )
        w.writeframes(frames)


def main():
    ap = argparse.ArgumentParser(description="生成测试样本")
    ap.add_argument("--force", action="store_true", help="已存在时也重新生成")
    args = ap.parse_args()

    targets = [
        ("video", "sample_gradient_2s.avi", lambda p: _write_avi(p, 320, 240, 15, 30)),
        ("image", "sample_gradient_640x480.png", lambda p: _write_png(p, 640, 480)),
        ("audio", "test_tone_1s.wav", lambda p: _write_wav(p)),
    ]
    for sub, name, fn in targets:
        d = os.path.join(HERE, sub)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        if os.path.exists(p) and not args.force:
            print("skip (exists):", os.path.relpath(p, HERE))
            continue
        fn(p)
        print("generated:", os.path.relpath(p, HERE), os.path.getsize(p), "bytes")


if __name__ == "__main__":
    main()