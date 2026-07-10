"""Record a human play session's state flow to build infrastructure scripts.

Launches the game and polls the bridge ~8x/sec, logging scene / mode / loading /
creation-stage / conversation / party transitions with timestamps. Input
injection stays OFF, so you play normally with mouse+keyboard while this watches.

Usage:  python tools/record_session.py [out.jsonl]
Stop with Ctrl+C when you've finished (e.g. saved at the Act 1 start).
"""
from __future__ import annotations

import json
import socket
import struct
import subprocess
import sys
import time

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Tyranny\Tyranny.exe"
_id = 0


def rpc(sock, op, **kw):
    global _id
    _id += 1
    p = json.dumps({"id": _id, "op": op, **kw}).encode()
    sock.sendall(struct.pack("<I", len(p)) + p)
    hdr = b""
    while len(hdr) < 4:
        c = sock.recv(4 - len(hdr))
        if not c:
            raise ConnectionError
        hdr += c
    (n,) = struct.unpack("<I", hdr)
    buf = b""
    while len(buf) < n:
        buf += sock.recv(n - len(buf))
    return json.loads(buf)


def snapshot(sock):
    s = rpc(sock, "observe")["state"]
    scene = rpc(sock, "diag_asm").get("scene")
    cre = s.get("creation", {})
    conv = s.get("conversation", {})
    return {
        "scene": scene,
        "area": s.get("area"),
        "loading": s.get("loading"),
        "in_combat": s.get("in_combat"),
        "in_creation": cre.get("active"),
        "creation_stage": cre.get("stage"),
        "creation_ready": cre.get("ready"),
        "conversation": conv.get("active"),
        "party": len(s.get("party") or []),
    }


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "tools/session_recording.jsonl"
    proc = subprocess.Popen(
        [GAME, "-screen-width", "1280", "-screen-height", "720", "-screen-fullscreen", "0"],
        cwd=GAME.rsplit("\\", 1)[0])
    print(f"game launched (pid {proc.pid}); connecting...")
    sock = None
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", 5555), timeout=2)
            break
        except OSError:
            time.sleep(2)
    if sock is None:
        proc.kill()
        print("FAIL: no bridge connection")
        return 1
    sock.settimeout(10)
    print("connected. RECORDING — play through New Game -> creation -> save. Ctrl+C to stop.")

    last = None
    t0 = time.time()
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        try:
            while True:
                snap = snapshot(sock)
                if snap != last:  # only log transitions
                    rec = {"t": round(time.time() - t0, 2), **snap}
                    f.write(json.dumps(rec) + "\n")
                    f.flush()
                    print(f"  {rec['t']:6.1f}s  scene={snap['scene']} area={snap['area']} "
                          f"load={snap['loading']} creation={snap['in_creation']}"
                          f"/stage={snap['creation_stage']} party={snap['party']}")
                    last = snap
                    n += 1
                time.sleep(0.12)
        except KeyboardInterrupt:
            print(f"\nstopped. {n} transitions logged to {out}")
        finally:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
