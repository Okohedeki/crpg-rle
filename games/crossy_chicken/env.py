"""CrossyChickenEnv — a self-contained Crossy Road / Frogger-style RL env.

A chicken starts at the bottom of an endlessly-scrolling grid and must cross
lanes of hazards. Rows above alternate between safe grass, hazardous **roads**
(cars sweep left/right; a car cell kills), and **rivers** (logs sweep left/right;
*water* kills — the chicken must be standing on a moving log). The world extends
upward forever (rows are generated procedurally and deterministically per seed).

Design goals (mirroring the project's contracts so nothing downstream changes):

* Action space ``MultiDiscrete([5])`` — 0 noop, 1 forward/up, 2 back/down,
  3 left, 4 right — so ``MultiInputActorCritic`` reads ``action_space.nvec``
  and builds a single 5-way head with no modification.
* Observation is the exact ``crpg_rle.core.spaces`` Dict:
  ``{"pixels": HxWx3 uint8, "state": float32[state_size], "mode": Discrete,
  "goal": float32[1]}``. Pixels are a numpy block render of the local window
  with the chicken centered; state is a compact hand-features vector (chicken
  column, timing, and per-visible-lane kind/velocity/nearest-danger features).
* Reward follows the non-farmable, progress-toward-goal philosophy: +1 ONLY on
  reaching a NEW furthest row, a small -0.01 step cost, and -1 on death (car
  hit, drowning, or standing still too long). Oscillating or backtracking earns
  nothing, so the progress channel cannot be farmed by jittering.

Hazards are modelled as an infinite periodic pattern that shifts by the lane
velocity each step: column ``c`` on a hazard lane is "occupied" at time ``t`` iff
``((c - dir*speed*t - phase) mod period) < obj_len``. On a **road** an occupied
cell is a *car* (lethal); on a **river** an occupied cell is a *log* (safe) and
everything else is water (lethal) — so ``danger`` inverts between the two. This
is exact, cheap, deterministic, and lets us report nearest-danger distances.

Difficulty presets (``difficulty=`` "easy"/"normal"/"hard") tune the mix of
grass/road/river and top speed; any explicit keyword overrides its preset value.
Rendering: ``render_mode="human"`` opens a pygame window and ``"rgb_array"``
returns an upscaled frame — both draw grass/road/car/water/log/chicken distinctly.
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
_COL_WATER = (40, 90, 200)
_COL_LOG = (120, 72, 40)
_COL_CHICKEN = (255, 220, 40)
_COL_VOID = (15, 15, 15)

_MAX_SPEED = 2  # normalizer for the velocity feature (speeds are capped here)

# Difficulty presets: fraction of lanes that are grass, fraction of the *hazard*
# lanes that are rivers (vs roads), and the top hazard speed. Explicit kwargs to
# the constructor override the matching preset field.
DIFFICULTY = {
    "easy":   {"safe_prob": 0.55, "river_frac": 0.15, "max_speed": 1},
    "normal": {"safe_prob": 0.40, "river_frac": 0.30, "max_speed": 2},
    "hard":   {"safe_prob": 0.25, "river_frac": 0.45, "max_speed": 2},
}

# Per-visible-lane state features (see _state_vector).
_LANE_FEATURES = 5


class CrossyChickenEnv(gym.Env):
    """Endless lane-crossing arcade env with the CRPG obs/action contract."""

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 8}

    def __init__(
        self,
        width: int = 11,
        obs_size: int = 84,
        view_rows: int = 11,
        n_lanes_state: int = 5,
        max_steps: int = 500,
        stuck_limit: int = 50,
        difficulty: str = "normal",
        safe_prob: float | None = None,
        river_frac: float | None = None,
        max_speed: int | None = None,
        render_mode: str | None = None,
        cell_px: int = 28,
    ):
        if difficulty not in DIFFICULTY:
            raise ValueError(f"difficulty must be one of {sorted(DIFFICULTY)}; got {difficulty!r}")
        preset = DIFFICULTY[difficulty]

        self.width = int(width)
        self.obs_size = int(obs_size)
        self.view_rows = int(view_rows)
        self.center = self.view_rows // 2
        self.n_lanes_state = int(n_lanes_state)
        self.max_steps = int(max_steps)
        self.stuck_limit = int(stuck_limit)
        self.difficulty = difficulty
        # Preset with per-field override.
        self.safe_prob = float(preset["safe_prob"] if safe_prob is None else safe_prob)
        self.river_frac = float(preset["river_frac"] if river_frac is None else river_frac)
        self.max_speed = int(min(_MAX_SPEED, preset["max_speed"] if max_speed is None else max_speed))

        if render_mode is not None and render_mode not in self.metadata["render_modes"]:
            raise ValueError(f"render_mode must be one of {self.metadata['render_modes']}")
        self.render_mode = render_mode
        self.cell_px = int(cell_px)
        self._window = None      # lazily created pygame surface
        self._clock = None

        # state = [col_norm, t_norm, since_progress_norm] + n_lanes*_LANE_FEATURES
        self.state_size = 3 + self.n_lanes_state * _LANE_FEATURES

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
        kind = "river" if rng.random() < self.river_frac else "road"
        obj_len = int(rng.integers(2, 4))   # car / log length: 2 or 3
        gap = int(rng.integers(2, 5))       # 2..4 (guarantees a passable gap)
        period = obj_len + gap
        return {
            "kind": kind,
            "dir": int(rng.choice([-1, 1])),
            "speed": int(rng.integers(1, self.max_speed + 1)),  # 1..max_speed
            "car_len": obj_len,             # occupied-run length (car or log)
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
        """Is grid cell ``col`` covered by the moving object (car/log) at ``t``?"""
        if lane["kind"] not in ("road", "river"):
            return False
        shift = lane["dir"] * lane["speed"] * t + lane["phase"]
        return int((col - shift) % lane["period"]) < lane["car_len"]

    def _danger(self, lane: dict, col: int, t: int) -> bool:
        """Would standing at ``col`` on ``lane`` at time ``t`` kill the chicken?

        Road: an occupied cell is a car (lethal). River: an *un*occupied cell is
        water (lethal) — the chicken survives only while on a log. Grass: safe.
        """
        kind = lane["kind"]
        if kind == "road":
            return self._occupied(lane, col, t)
        if kind == "river":
            return not self._occupied(lane, col, t)
        return False

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
        if self.render_mode == "human":
            self.render()
        return self._obs(), {"mode": int(Mode.OVERWORLD), "max_row": 0,
                             "difficulty": self.difficulty}

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
        # NOOP: no positional change (but hazards still advance below)

        self.t += 1
        self.steps += 1

        progress = 0.0
        death = 0.0
        step_cost = STEP_PENALTY
        terminated = False
        truncated = False
        terminal_kind = None

        # Death check on the chicken's (possibly new) cell: car on a road, water
        # on a river. Logs slide each step, so a chicken that stays put on a
        # river will drop into the water it drifts over — no farming a safe log.
        lane = self._lane(self.row)
        if self._danger(lane, self.col, self.t):
            death = DEATH_PENALTY
            terminated = True
            terminal_kind = "water" if lane["kind"] == "river" else "car"
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
        if self.render_mode == "human":
            self.render()
        return self._obs(), reward, terminated, truncated, info

    # --------------------------------------------------------------- obs build
    def _obs(self) -> dict:
        return {
            "pixels": self._render_pixels(),
            "state": self._state_vector(),
            "mode": int(Mode.OVERWORLD),
            "goal": np.zeros(1, dtype=np.float32),
        }

    def _state_vector(self) -> np.ndarray:
        v = np.zeros(self.state_size, dtype=np.float32)
        v[0] = self.col / max(1, self.width - 1)
        v[1] = self.t / max(1, self.max_steps)
        v[2] = self.since_progress / max(1, self.stuck_limit)
        w = self.width
        for i in range(self.n_lanes_state):
            row = self.row + i  # current lane + lanes ahead
            lane = self._lane(row)
            base = 3 + i * _LANE_FEATURES
            kind = lane["kind"]
            if kind == "grass":
                v[base + 0] = 0.0
                v[base + 1] = 0.0
                v[base + 2] = 1.0   # nearest danger left (far/safe)
                v[base + 3] = 1.0   # nearest danger right (far/safe)
                v[base + 4] = 1.0   # standing here is safe
                continue
            v[base + 0] = 0.5 if kind == "road" else 1.0
            v[base + 1] = (lane["dir"] * lane["speed"]) / _MAX_SPEED
            # Nearest *dangerous* cell to the left/right of the chicken column.
            dl = dr = float(w)
            for c in range(w):
                if self._danger(lane, c, self.t):
                    d = c - self.col
                    if d <= 0:
                        dl = min(dl, float(-d))
                    if d >= 0:
                        dr = min(dr, float(d))
            v[base + 2] = dl / w
            v[base + 3] = dr / w
            v[base + 4] = 0.0 if self._danger(lane, self.col, self.t) else 1.0
        return v

    # ------------------------------------------------------------- rendering
    def _cell_rgb(self, world_row: int, col: int) -> tuple:
        """RGB for the grid cell at (world_row, col), ignoring the chicken."""
        if world_row < 0:
            return _COL_VOID
        lane = self._lane(world_row)
        kind = lane["kind"]
        if kind == "grass":
            return _COL_GRASS
        occ = self._occupied(lane, col, self.t)
        if kind == "road":
            return _COL_CAR if occ else _COL_ROAD
        return _COL_LOG if occ else _COL_WATER   # river

    def _view_grid(self) -> np.ndarray:
        """(view_rows, width, 3) uint8 view centered on the chicken row."""
        vh, vw = self.view_rows, self.width
        grid = np.zeros((vh, vw, 3), dtype=np.uint8)
        for vr in range(vh):
            world_row = self.row + (self.center - vr)  # forward (higher) = up
            for c in range(vw):
                grid[vr, c] = self._cell_rgb(world_row, c)
        grid[self.center, self.col] = _COL_CHICKEN   # chicken at fixed center row
        return grid

    def _render_pixels(self) -> np.ndarray:
        """Nearest-neighbour upscale of the view grid to (obs_size, obs_size)."""
        grid = self._view_grid()
        vh, vw = self.view_rows, self.width
        n = self.obs_size
        ys = (np.arange(n) * vh // n).clip(0, vh - 1)
        xs = (np.arange(n) * vw // n).clip(0, vw - 1)
        return grid[ys][:, xs]

    def _frame(self) -> np.ndarray:
        """Chunky RGB frame (view_rows*cell_px, width*cell_px, 3) for watching."""
        grid = self._view_grid()
        return np.repeat(np.repeat(grid, self.cell_px, axis=0), self.cell_px, axis=1)

    def render(self):
        if self.render_mode == "rgb_array":
            return self._frame()
        if self.render_mode == "human":
            self._draw_human()
            return None
        return None

    def _draw_human(self) -> None:
        import pygame  # local import: only needed for the window
        frame = self._frame()
        h, w = frame.shape[0], frame.shape[1]
        if self._window is None:
            pygame.init()
            pygame.display.set_caption(f"Crossy Chicken — {self.difficulty}")
            self._window = pygame.display.set_mode((w, h))
            self._clock = pygame.time.Clock()
        # Drain the event queue so the OS keeps the window responsive.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.close()
                return
        # pygame surfaces are (w, h); numpy frame is (h, w) -> swap axes.
        surf = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
        self._window.blit(surf, (0, 0))
        pygame.display.flip()
        self._clock.tick(self.metadata["render_fps"])

    def close(self) -> None:
        if self._window is not None:
            import pygame
            pygame.display.quit()
            pygame.quit()
            self._window = None
            self._clock = None
