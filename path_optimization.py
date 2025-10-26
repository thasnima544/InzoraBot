"""
path_optimization.py
--------------------
A* path planning on a grid with:
- 8-direction movement
- obstacle support
- cost weighting by a risk heatmap
- optional diagonal penalty
- path smoothing (simple collinearity pruning)

No external dependencies (uses heapq).
"""

from __future__ import annotations
from typing import List, Tuple, Optional, Iterable
import heapq
import math


Grid = List[List[float]]  # 0 = free, 1 = obstacle (or high cost if >1)
Risk = List[List[float]]  # non-negative risk penalties


def _neighbors_8(r: int, c: int, rows: int, cols: int) -> Iterable[Tuple[int, int, float]]:
    """8-connected neighborhood with step cost (1 orthogonal, sqrt(2) diagonal)."""
    for dr, dc in (
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1),
    ):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            step = math.sqrt(2.0) if dr != 0 and dc != 0 else 1.0
            yield nr, nc, step


def _heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    """Octile distance heuristic suitable for 8-connected grids."""
    (r1, c1), (r2, c2) = a, b
    dx = abs(r1 - r2)
    dy = abs(c1 - c2)
    d_min = min(dx, dy)
    d_max = max(dx, dy)
    return (math.sqrt(2.0) * d_min) + (d_max - d_min)


def astar_path(
    occupancy: Grid,
    start: Tuple[int, int],
    goal: Tuple[int, int],
    risk: Optional[Risk] = None,
    risk_weight: float = 1.0,
    diagonal_penalty: float = 0.0,
) -> Tuple[List[Tuple[int, int]], float]:
    """
    Compute a path using A*.

    occupancy: grid of 0 (free) and 1 (blocked). You can also give fractional values
               as base costs (e.g., 0.0 = free, 5.0 = very hard terrain).
    start, goal: (row, col)
    risk: optional grid (same size) with non-negative risk per cell
    risk_weight: multiplies the risk contribution to cost
    diagonal_penalty: extra cost added to diagonal steps to discourage zig-zags

    Returns: (path, total_cost)
             path is a list of (row, col) from start to goal (inclusive).
             total_cost is the accumulated g-score of the goal.
    """
    rows = len(occupancy)
    cols = len(occupancy[0]) if rows else 0
    if rows == 0 or cols == 0:
        return [], float("inf")

    def blocked(r: int, c: int) -> bool:
        return occupancy[r][c] >= 1.0  # treat >=1 as obstacle

    # g = cost so far; f = g + h
    g = [[float("inf")] * cols for _ in range(rows)]
    came_from: List[List[Optional[Tuple[int, int]]]] = [[None] * cols for _ in range(rows)]

    sr, sc = start
    tr, tc = goal
    if blocked(sr, sc) or blocked(tr, tc):
        return [], float("inf")

    g[sr][sc] = 0.0
    h0 = _heuristic(start, goal)
    pq = [(h0, 0.0, start)]  # (f, g, (r,c))

    while pq:
        f_curr, g_curr, (r, c) = heapq.heappop(pq)
        if (r, c) == goal:
            break
        if g_curr > g[r][c]:
            continue

        for nr, nc, step_cost in _neighbors_8(r, c, rows, cols):
            if blocked(nr, nc):
                continue

            # base terrain cost (allow fractional occupancy)
            terrain = occupancy[nr][nc]
            base = step_cost + max(0.0, terrain)

            # risk penalty
            risk_pen = 0.0
            if risk is not None:
                risk_pen = risk_weight * max(0.0, risk[nr][nc])

            # diagonal discouragement (optional)
            diag_pen = diagonal_penalty if (nr != r and nc != c) else 0.0

            ng = g_curr + base + risk_pen + diag_pen
            if ng < g[nr][nc]:
                g[nr][nc] = ng
                came_from[nr][nc] = (r, c)
                f = ng + _heuristic((nr, nc), goal)
                heapq.heappush(pq, (f, ng, (nr, nc)))

    if g[tr][tc] == float("inf"):
        return [], float("inf")

    # reconstruct path
    path = []
    cur = goal
    while cur:
        path.append(cur)
        pr = came_from[cur[0]][cur[1]]
        cur = pr
    path.reverse()

    # optional smoothing by removing collinear points
    path = _prune_collinear(path)

    return path, g[tr][tc]


def _prune_collinear(path: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Remove intermediate points that are exactly collinear (keeps endpoints)."""
    if len(path) <= 2:
        return path[:]
    pruned = [path[0]]
    for i in range(1, len(path) - 1):
        r0, c0 = pruned[-1]
        r1, c1 = path[i]
        r2, c2 = path[i + 1]
        if (r1 - r0, c1 - c0) == (r2 - r1, c2 - c1):
            # same direction vector => collinear 8-connected
            continue
        pruned.append(path[i])
    pruned.append(path[-1])
    return pruned


# ---------------- Example usage ----------------
if __name__ == "__main__":
    # 10x10 grid with an obstacle wall and a gap
    occ = [[0.0 for _ in range(10)] for _ in range(10)]
    for rr in range(10):
        occ[rr][5] = 1.0  # wall
    occ[4][5] = 0.0      # opening in the wall
    occ[5][5] = 0.0

    # simple risk map with a risky band
    risk = [[0.0 for _ in range(10)] for _ in range(10)]
    for cc in range(3, 7):
        risk[6][cc] = 2.0  # higher risk area

    path, cost = astar_path(
        occupancy=occ,
        start=(0, 0),
        goal=(9, 9),
        risk=risk,
        risk_weight=0.5,
        diagonal_penalty=0.05,
    )
    print("Path:", path)
    print("Cost:", round(cost, 3))
