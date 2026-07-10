"""Run a CRPGEnv behind the flat-binary env_server for the PufferLib 4.0 shim.

Topology: this process runs on the Windows game host (it launches Tyranny and
owns the bridge socket). The PuffeRL 4.0 trainer runs on WSL2/Linux with the
ocean/tyranny shim compiled into _C.so; the shim connects here over TCP.

    python -m crpg_rle.puffer.run_env_server --port 7000 --save "<save>.savegame"

Then on the Linux side: ./build.sh tyranny --float --cpu && puffer train tyranny
(the shim reads host/port from its .ini; point it at this machine).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
from crpg_rle.adapters.tyranny.config import TyrannyConfig
from crpg_rle.core.env import CRPGEnv
from crpg_rle.core.env_server import EnvServer


def _read_build_spec(value: str | None) -> dict | None:
    if value is None:
        return None
    path = Path(value)
    raw = path.read_text(encoding="utf-8") if path.is_file() else value
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("build spec must decode to a JSON object")
    return parsed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--base-seed", type=int, default=0)
    ap.add_argument("--start-mode", choices=["creation", "act1_save"], default="act1_save")
    ap.add_argument("--save", default=None, help="savegame filename for act1_save start")
    ap.add_argument("--corpus", default=None, help="dialogue corpus path")
    ap.add_argument(
        "--build-spec",
        default=None,
        help="one-shot build JSON, either inline or a path to a JSON file",
    )
    ap.add_argument(
        "--working-save",
        default=None,
        help="run-specific save name; generated automatically when omitted",
    )
    ap.add_argument("--obs-width", type=int, default=84)
    ap.add_argument("--obs-height", type=int, default=84)
    ap.add_argument("--time-scale", type=float, default=1.0)
    ap.add_argument("--layout", default="obs_layout.json")
    args = ap.parse_args()

    cfg = TyrannyConfig(
        start_mode=args.start_mode,
        save_start=args.save,
        corpus_path=args.corpus,
        build_spec=_read_build_spec(args.build_spec),
        working_save=args.working_save,
        obs_width=args.obs_width,
        obs_height=args.obs_height,
        time_scale=args.time_scale,
    )
    env = CRPGEnv(TyrannyAdapter(cfg))
    server = EnvServer(env, host=args.host, port=args.port,
                       base_seed=args.base_seed, layout_path=args.layout)
    print(f"env_server on {args.host}:{args.port}; obs {args.obs_width}x{args.obs_height}, "
          f"start={args.start_mode}. Waiting for the puffer shim to connect...")
    try:
        server.serve_forever()
    finally:
        env.close()


if __name__ == "__main__":
    main()
