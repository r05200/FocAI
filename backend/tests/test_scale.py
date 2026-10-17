import pytest
from pydantic import ValidationError

from pruner.pruning.postscorer import PostScoreOutput
from pruner.pruning.prescorer import CandidateRating
from pruner.pruning.scale import to_unit


def test_ten_scale_maps_to_unit_interval_in_tenths():
    assert to_unit(10) == 1.0 and to_unit(1) == 0.1 and to_unit(0) == 0.0
    assert to_unit(7.3) == 0.73
    assert to_unit(7.34) == 0.73  # rounded to a tenth first
    assert to_unit(11) == 1.0 and to_unit(-2) == 0.0  # clamped


def test_judge_outputs_use_the_ten_scale():
    CandidateRating(node_id="n", reason="r", plausible=9.5, relevant=10,
                    novel=1)
    PostScoreOutput(reason="r", post_score=7.3)
    with pytest.raises(ValidationError):
        PostScoreOutput(reason="r", post_score=10.5)
