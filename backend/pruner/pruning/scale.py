"""The judges score on a 1 to 10 scale (tenths allowed, e.g. 7.3). Stored scores are 0..1, but
every threshold in the config is written on the 1 to 10 scale and compared with to_ten()."""

SCALE_MAX = 10.0


def to_unit(score: float) -> float:
    """10-scale score (tenths) -> 0..1, clamped."""
    return round(min(max(round(score, 1), 0.0), SCALE_MAX) / SCALE_MAX, 4)


def to_ten(unit: float) -> float:
    """0..1 stored score -> the 1 to 10 scale the thresholds use."""
    return round(unit * SCALE_MAX, 4)
