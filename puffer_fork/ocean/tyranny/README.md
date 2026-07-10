# Tyranny env (PufferLib 4.0 shim)

This is a thin C shim, not a simulator. PufferLib 4.0 compiles every env into
`_C.so` and steps it synchronously; it has no out-of-process env path. The shim
is a normal Ocean env whose `c_step` blocks on a TCP round-trip to a Python
`env_server` that owns the live Tyranny game.

```
  Windows game host                         Linux / WSL2 (CUDA)
  ┌───────────────────────────┐            ┌──────────────────────────┐
  │ Tyranny.exe + BepInEx mod │            │ PuffeRL 4.0 trainer      │
  │        ▲  (bridge :5555)   │            │  _C.so  ← ocean/tyranny  │
  │        │                   │            │        │ c_step()        │
  │  crpg_rle.core.env_server  │◄──TCP──────┤  socket │ (this shim)     │
  │        (:7000)             │   :7000    │        ▼                  │
  └───────────────────────────┘            └──────────────────────────┘
```

## Why a shim (and its cost)

The 4.0 CUDA/OpenMP throughput comes from stepping millions of in-process C
envs. Tyranny is a fixed-rate rendered game (~10–60 Hz), so no framework speeds
it up; a blocking-socket `c_step` starves the pipeline. This is accepted: the
fork gives us the PuffeRL trainer, and the game — not the framework — is the rate
limiter. See the project plan for the full rationale.

## Build (Linux / WSL2 with CUDA)

`OBS_SIZE` in `binding.c` must match the env_server's flattened observation
(pixels·3 + state + 1 + factions). The default assumes 84×84×3 pixels. Then:

```bash
# on the Linux/WSL2 trainer host
./build.sh tyranny --float --cpu     # or without --cpu for the CUDA build
```

## Run

```bash
# on the Windows game host
python -m crpg_rle.puffer.run_env_server --port 7000 --start-mode act1_save --save "<name>.savegame"

# on the Linux side, point the shim at the game host's IP:7000 and train
```

The env_server writes `obs_layout.json` describing how to slice the flat obs
back into {pixels, state, mode, goal} for the policy.
