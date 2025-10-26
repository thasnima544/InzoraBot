"""
predictive_analysis.py
----------------------
Lightweight predictive analytics helpers for InzoraBot.

Features
- Exponential Moving Average (EMA) forecaster for quick time-series prediction
- Simple Kalman filter (1D) for noisy sensor smoothing
- ETA predictor based on recent robot speeds and remaining distance
- Risk heatmap updater with temporal decay

No heavy dependencies: only Python stdlib + typing + math.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Deque, Iterable, List, Tuple, Optional
from collections import deque
import math
import time


# ---------- 1) Exponential Moving Average Forecaster ----------

@dataclass
class EMAForecaster:
    """
    Fast, online exponential moving average forecaster.

    alpha: 0..1 smoothing factor (higher = reacts faster to new data)
    """
    alpha: float = 0.3
    _level: Optional[float] = None

    def update(self, value: float) -> float:
        """Feed a new observation and get the updated EMA."""
        if self._level is None:
            self._level = value
        else:
            self._level = self.alpha * value + (1 - self.alpha) * self._level
        return self._level

    def predict(self, steps: int = 1) -> float:
        """
        Predict `steps` ahead (for EMA it's the same value).
        """
        if self._level is None:
            raise ValueError("No data yet. Call update() first.")
        return self._level


# ---------- 2) Simple (1D) Kalman Filter for Sensor Smoothing ----------

@dataclass
class Kalman1D:
    """
    Minimal 1D Kalman filter for smoothing a single noisy signal.
    - x: current state estimate
    - p: current estimate covariance (uncertainty)
    - q: process noise (how much the true state moves)
    - r: measurement noise (sensor noise)

    Typical tuning: start with q small (e.g., 1e-3 to 1e-2) and set r to the
    observed measurement variance.
    """
    q: float = 1e-3
    r: float = 1e-2
    x: Optional[float] = None
    p: float = 1.0

    def update(self, z: float) -> float:
        """Update with measurement z and return filtered estimate."""
        if self.x is None:
            # initialize with first observation
            self.x = z
            self.p = 1.0

        # Predict
        self.p = self.p + self.q

        # Update
        k = self.p / (self.p + self.r)
        self.x = self.x + k * (z - self.x)
        self.p = (1 - k) * self.p
        return self.x


# ---------- 3) ETA (Arrival Time) Prediction ----------

@dataclass
class ETAPredictor:
    """
    Predict ETA based on the remaining distance (meters) and recent speed history (m/s).
    Maintains a rolling window of speed samples; uses a robust harmonic mean
    (less biased by occasional high speeds).
    """
    window: int = 30  # number of recent speed samples
    _speeds: Deque[float] = None

    def __post_init__(self):
        self._speeds = deque(maxlen=self.window)

    def update_speed(self, speed_mps: float) -> None:
        """Add a speed sample in meters/second."""
        self._speeds.append(max(0.0, float(speed_mps)))

    def estimate_eta_seconds(self, remaining_distance_m: float, min_speed: float = 0.05) -> float:
        """
        remaining_distance_m: meters left along planned path
        Returns ETA in seconds. If speed is too low/empty, clamps to min_speed.
        """
        if not self._speeds:
            v = min_speed
        else:
            # harmonic mean to reduce impact of spikes
            inv = [1.0 / max(min_speed, s) for s in self._speeds if s > 0]
            v = len(inv) / sum(inv) if inv else min_speed
            v = max(v, min_speed)
        return remaining_distance_m / v


# ---------- 4) Risk Heatmap with Temporal Decay ----------

@dataclass
class RiskHeatmap:
    """
    Maintains a risk grid (list of lists) that decays over time and can be
    reinforced by new observations (e.g., detections, hazards).
    """
    rows: int
    cols: int
    decay_per_sec: float = 0.01  # 1% per second
    _grid: List[List[float]] = None
    _last_ts: float = None

    def __post_init__(self):
        self._grid = [[0.0 for _ in range(self.cols)] for _ in range(self.rows)]
        self._last_ts = time.time()

    def _apply_decay(self):
        now = time.time()
        dt = max(0.0, now - self._last_ts)
        self._last_ts = now
        if dt <= 0:
            return
        decay_factor = max(0.0, 1.0 - self.decay_per_sec * dt)
        for r in range(self.rows):
            for c in range(self.cols):
                self._grid[r][c] *= decay_factor

    def reinforce(self, cells: Iterable[Tuple[int, int]], amount: float = 1.0) -> None:
        """
        Increase risk at given (row, col) cells.
        """
        self._apply_decay()
        for r, c in cells:
            if 0 <= r < self.rows and 0 <= c < self.cols:
                self._grid[r][c] += amount

    def get(self) -> List[List[float]]:
        """Return the current (decayed) risk grid."""
        self._apply_decay()
        return self._grid
