"""The committed frontend fixtures must equal what pruner.fixtures generates."""

import json

from pruner.fixtures import FIXTURES_DIR, build_fixtures


def test_committed_fixtures_are_up_to_date():
    for name, expected in build_fixtures().items():
        path = FIXTURES_DIR / name
        assert path.exists(), f"{name} missing; run: cd backend && uv run python -m pruner.fixtures"
        assert json.loads(path.read_text()) == expected, (
            f"{name} is stale; run: cd backend && uv run python -m pruner.fixtures"
        )
