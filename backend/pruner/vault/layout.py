"""Where each vault item sits on the 3D mind map.

Positions are cached on the items (VaultItem.auto_position), saved with them, and only
recomputed here (a person's manual moves live in VaultItem.position and are never touched here):
- pca_positions(): a full layout. Embeddings are projected onto their top three principal
  components, so similar items end up close together. Deterministic for the same items.
- place_near(): a spot beside the most similar already-placed item, for a newly added item, so
  adding knowledge never shuffles the items that are already placed (or that the user moved).
"""

from __future__ import annotations

import hashlib

import numpy as np

SCALE = 120.0  # the largest coordinate a full layout produces
NEAR_DISTANCE = 18.0  # how far a new item is placed from its closest neighbor


def _jitter(seed: str, amount: float) -> np.ndarray:
    """A deterministic offset in [-amount, amount]^3 from a string (e.g. the item id)."""
    digest = hashlib.md5(seed.encode()).digest()
    return (np.frombuffer(digest[:3], dtype=np.uint8) / 127.5 - 1.0) * amount


def pca_positions(ids: list[str], embeddings: np.ndarray) -> dict[str, tuple[float, float, float]]:
    """id -> (x, y, z) for every item. A single item sits at the origin."""
    if len(ids) == 0:
        return {}
    centered = embeddings - embeddings.mean(axis=0)
    coords = np.zeros((len(ids), 3))
    if len(ids) > 1 and np.any(centered):
        u, s, _ = np.linalg.svd(centered, full_matrices=False)
        k = min(3, len(s))
        coords[:, :k] = u[:, :k] * s[:k]
        peak = np.abs(coords).max()
        if peak > 0:
            coords *= SCALE / peak
    return {i: tuple(float(v) for v in c + _jitter(i, 2.0))  # type: ignore[misc]
            for i, c in zip(ids, coords, strict=True)}


def place_near(item_id: str, embedding: list[float],
               placed: list[tuple[list[float], tuple[float, float, float]]],
               ) -> tuple[float, float, float]:
    """A position beside the placed item whose embedding is most similar to this one.
    `placed` is (embedding, (x, y, z)) pairs; with none, the origin."""
    if not placed:
        return (0.0, 0.0, 0.0)
    matrix = np.array([e for e, _ in placed], dtype=np.float32)
    vec = np.array(embedding, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(vec) or 1.0)
    sims = (matrix @ vec) / np.where(norms == 0, 1, norms)
    anchor = np.array(placed[int(np.argmax(sims))][1])
    direction = _jitter(item_id, 1.0)
    direction = direction / (np.linalg.norm(direction) or 1.0)
    return tuple(float(v) for v in anchor + direction * NEAR_DISTANCE)  # type: ignore[return-value]
