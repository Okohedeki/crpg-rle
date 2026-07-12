"""CrossyChickenEnv — a self-contained Crossy Road / Frogger-style RL env.

A chicken starts at the bottom of an endlessly-scrolling grid and must cross
lanes of traffic. Rows above alternate between safe grass and hazardous roads
whose cars sweep left/right at varying speeds; the world extends upward forever
(rows are generated procedurally and deterministically per seed on demand).

Design goals (mirroring the project's contracts so nothing downstream changes):

* Action space ``MultiDiscrete([5])`` — 0 noop, 1 forward/up, 2 back/down,
  3 left, 4 right — so ``MultiInputActorCritic`` reads ``action_space.nvec``
  and builds a single 5-way head with no modification.
* Observation is the exact ``crpg_rle.core.spaces`` Dict:
  ``{"pixels": 84x84x3 uint8, "state": float32[state_size], "mode": Discrete,
  "goal": float32[1]}``. Pixels are a numpy block render of the local window
  with the chicken centered; state is a compact hand-features vector (chicken
  column, timing, and per-visible-lane road/velocity/nearest-car features).
* Reward follows the non-farmable, progress-toward-goal philosophy: +1 ONLY on
  reaching a NEW furthest row, a small -0.01 step cost, and -1 on death (car
  hit or standing still too long). Oscillating or backtracking earns nothing,
  so the progress channel cannot be farmed by jittering.

Cars are modelled as an infinite periodic pattern that shifts by the lane
velocity each step: column ``c`` on a road lane is occupied at time ``t`` iff
``((c - dir*speed*t - phase) mod period) < car_len``. This is exact, cheap, and
deterministic, and lets us report nearest-car distances for the state vector.
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np

from crpg_rle.core import spaces as S
from crpg_rle.core.modes import Mode

# Reward channel magnitudes.
PROGRESS_REWARD = 1.0
STEP_PENALTY = -0.01
DEATH_PENALTY = -1.0

# Action ids.
NOOP, UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3, 4

# Render palette (RGB).
_COL_GRASS = (60, 180, 75)
_COL_ROAD = (70, 70, 70)
_COL_CAR = (230, 50, 50)
_COL_CHICKEN = (255, 220, 40)
_COL_VOID = (15, 15, 15)

_MAX_SPEED = 2  # for normalizing the velocity feature


class CrossyChickenEnv(gym.Env):
    """Endless lane-crossing arcade env with the CRPG obs/action contract."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        width: int = 11,
        obs_size: int = 84,
        view_rows: int = 11,
        n_lanes_state: int = 5,
        max_steps: int = 500,
        stuck_limit: int = 50,
        safe_prob: float = 0.4,
    ):
        self.width = int(width)
        self.obs_size = int(obs_size)
        self.view_rows = int(view_rows)
        self.center = self.view_rows // 2
        self.n_lanes_state = int(n_lanes_state)
        self.max_steps = int(max_steps)
        self.stuck_limit = int(stuck_limit)
        self.safe_prob = float(safe_prob)

        # state = [col_norm, t_norm, since_progress_norm] + n_lanes*[road, vel, dL, dR]
        self.state_size = 3 + self.n_lanes_state * 4

        self.action_space = gym.spaces.MultiDiscrete([5])
        self.observation_space = S.build_observation_space(
            obs_height=self.obs_size,
            obs_width=self.obs_size,
            state_size=self.state_size,
            n_modes=Mode.count(),
            n_factions=1,
        )

        self._seed = 0
        self._lanes: dict[int, dict] = {}
        self.row = 0
        self.col = self.width // 2
        self.t = 0
        self.max_row = 0
        self.steps = 0
        self.since_progress = 0

    # ------------------------------------------------------------- lanes / cars
    def _gen_lane(self, row: int) -> dict:
        """Deterministically generate a lane for ``row`` from (seed, row).

        Derived per-row so the world is identical for a seed regardless of the
        order rows are first touched (rendering may peek ahead of the chicken).
        """
        if row <= 0:
            return {"kind": "grass"}
        rng = np.random.default_rng([self._seed & 0xFFFFFFFF, row & 0xFFFFFFFF])
        if rng.random() < self.safe_prob:
            return {"kind": "grass"}
        car_len = int(rng.integers(2, 4))   # 2 or 3
        gap = int(rng.integers(2, 5))       # 2..4 (guarantees a passable gap)
        period = car_len + gap
        return {
            "kind": "road",
            "dir": int(rng.choice([-1, 1])),
            "speed": int(rng.integers(1, _MAX_SPEED + 1)),  # 1..MAX_SPEED
            "car_len": car_len,
            "gap": gap,
            "period": period,
            "phase": int(rng.integers(0, period)),
        }

    def _lane(self, row: int) -> dict:
        lane = self._lanes.get(row)
        if lane is None:
            lane = self._gen_lane(row)
            self._lanes[row] = lane
        return lane

    def _occupied(self, lane: dict, col: int, t: int) -> bool:
        """Is grid cell ``col`` covered by a car on ``lane`` at time ``t``?"""
        if lane["kind"] != "road":
            return False
        shift = lane["dir"] * lane["speed"] * t + lane["phase"]
        return int((col - shift) % lane["period"]) < lane["car_len"]

    # --------------------------------------------------------------- gym API
    def reset(self, *, seed: int | None = None, options: dict | None = None):
        if seed is not None:
            self._seed = int(seed)
        self._lanes = {}
        self.row = 0
        self.col = self.width // 2
        self.t = 0
        self.max_row = 0
        self.steps = 0
        self.since_progress = 0
        return self._obs(), {"mode": int(Mode.OVERWORLD), "max_row": 0}

    def step(self, action):
        a = int(np.asarray(action).ravel()[0])

        if a == UP:
            self.row += 1
        elif a == DOWN:
            self.row = max(0, self.row - 1)
        elif a == LEFT:
            self.col = max(0, self.col - 1)
        elif a == RIGHT:
            self.col = min(self.width - 1, self.col + 1)
        # NOOP: no positional change (but cars still advance below)

        self.t += 1
        self.steps += 1

        progress = 0.0
        death = 0.0
        step_cost = STEP_PENALTY
        terminated = False
        truncated = False
        terminal_kind = None

        # Car collision on the chicken's (possibly new) cell.
        lane = self._lane(self.row)
        if self._occupied(lane, self.col, self.t):
            death = DEATH_PENALTY
            terminated = True
            terminal_kind = "car"
        else:
            # Forward-progress reward: only a NEW furthest row pays out.
            if self.row > self.max_row:
                self.max_row = self.row
                progress = PROGRESS_REWARD
                self.since_progress = 0
            else:
                self.since_progress += 1
                # Standing still / never advancing too long is fatal.
                if self.since_progress >= self.stuck_limit:
                    death = DEATH_PENALTY
                    terminated = True
                    terminal_kind = "stuck"

        if not terminated and self.steps >= self.max_steps:
            truncated = True

        reward = float(progress + step_cost + death)
        info = {
            "mode": int(Mode.OVERWORLD),
            "reward_channels": {"progress": progress, "death": death, "step": step_cost},
            "max_row": self.max_row,
            "row": self.row,
        }
        if terminal_kind is not None:
            info["terminal_kind"] = terminal_kind
            info["events"] = [{"kind": "death", "cause": terminal_kind, "row": self.row}]
        return self._obs(), reward, terminated, truncated, info

    # --------------------------------------------------------------- obs build
    def _obs(self) -> dict:
        return {
            "pixels": self._render_pixels(),
            "state": self._state_vector(),
            "mode": int(Mode.OVERWORLD),
            "goal": np.zeros(1, dtype=np.float32),
        }

    def _lane_occupancy(self, row: int) -> np.ndarray:
        lane = self._lane(row)
        occ = np.zeros(self.width, dtype=bool)
        if lane["kind"] == "road":
            for c in range(self.width):
                occ[c] = self._occupied(lane, c, self.t)
        return occ

    def _state_vector(self) -> np.ndarray:
        v = np.zeros(self.state_size, dtype=np.float32)
        v[0] = self.col / max(1, self.width - 1)
        v[1] = self.t / max(1, self.max_steps)
        v[2] = self.since_progress / max(1, self.stuck_limit)
        w = self.width
        for i in range(self.n_lanes_state):
            row = self.row + i  # current lane + lanes ahead
            lane = self._lane(row)
            base = 3 + i * 4
            if lane["kind"] == "road":
                occ = self._lane_occupancy(row)
                v[base + 0] = 1.0
                v[base + 1] = (lane["dir"] * lane["speed"]) / _MAX_SPEED
                # Nearest occupied cell to the left/right of the chicken column.
                dl = dr = float(w)
                for c in range(w):
                    if occ[c]:
                        d = c - self.col
                        if d <= 0:
                            dl = min(dl, float(-d))
                        if d >= 0:
                            dr = min(dr, float(d))
                v[base + 2] = dl / w
                v[base + 3] = dr / w
            else:
                v[base + 0] = 0.0
                v[base + 1] = 0.0
                v[base + 2] = 1.0
                v[base + 3] = 1.0
        return v

    def _render_pixels(self) -> np.ndarray:
        vh, vw = self.view_rows, self.width
        grid = np.zeros((vh, vw, 3), dtype=np.uint8)
        for vr in range(vh):
            world_row = self.row + (self.center - vr)  # forward (higher) = up
            if world_row < 0:
                grid[vr, :] = _COL_VOID
                continue
            lane = self._lane(world_row)
            if lane["kind"] == "road":
                occ = self._lane_occupancy(world_row)
                for c in range(vw):
                    grid[vr, c] = _COL_CAR if occ[c] else _COL_ROAD
            else:
                grid[vr, :] = _COL_GRASS
        # Chicken drawn at the fixed center row.
        grid[self.center, self.col] = _COL_CHICKEN

        # Nearest-neighbour upscale to (obs_size, obs_size) with no deps.
        n = self.obs_size
        ys = (np.arange(n) * vh // n).clip(0, vh - 1)
        xs = (np.arange(n) * vw // n).clip(0, vw - 1)
        return grid[ys][:, xs]
