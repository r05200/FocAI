from pruner.core.models import Node
from pruner.pruning.checks import check_train_py, reject

BASE = """
def build_model(vocab_size, block_size):
    return 1

def build_optimizer(model, lr=1e-3):
    return 2
"""


def test_small_valid_edit_passes():
    assert check_train_py(BASE.replace("1e-3", "3e-4"), BASE) == []


def test_syntax_error_is_rejected():
    [v] = check_train_py("def build_model(:\n", BASE)
    assert "does not compile" in v


def test_signature_change_and_removal_are_rejected():
    changed = BASE.replace("block_size", "context")
    assert any("build_model signature changed" in v for v in check_train_py(changed, BASE))
    removed = "def build_model(vocab_size, block_size):\n    return 1\n"
    assert "build_optimizer was removed" in check_train_py(removed, BASE)


def test_other_files_and_large_diffs_are_rejected():
    assert any("prepare.py" in v for v in
               check_train_py(BASE, BASE, changed_files=["train.py", "prepare.py"]))
    big = BASE + "\n".join(f"x{i} = {i}" for i in range(100))
    assert any("diff changes" in v for v in check_train_py(big, BASE))


def test_reject_parks_the_node_with_the_reasons():
    n = reject(Node(run_id="r", type="hypothesis", description="x"), ["a", "b"])
    assert n.status == "parked" and n.decision.stage == "pre"
    assert n.decision.reason == "Rejected before scoring: a; b"
