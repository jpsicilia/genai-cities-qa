"""Los planes de referencia (correctos) no deben ser tocados por las reparaciones."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from pipeline import executor  # noqa: E402
from tools.profiles import Profile  # noqa: E402


def _cases():
    import eval_holdout
    import eval_variants
    import eval_zurich
    import eval_zurich_dev
    out = [("dublin", c["id"], c["q"], c["ref"]) for c in eval_holdout.CASES]
    out += [("dublin", i, q, p) for i, q, p in eval_variants.CASES]
    out += [("zurich", c["id"], c["q"], c["ref"]) for c in eval_zurich.build_cases(Profile("zurich"))]
    out += [("zurich", c["id"], c["q"], c["ref"]) for c in eval_zurich_dev.build_cases(Profile("zurich"))]
    return out


@pytest.mark.parametrize("prof,cid,q,ref", _cases(), ids=lambda x: x if isinstance(x, str) and len(x) < 6 else "")
def test_reference_plan_untouched(prof, cid, q, ref):
    P = Profile(prof)
    notes = []
    calls = executor.repair_plan(ref["calls"], q, P, notes)
    assert not notes, f"{cid}: {notes}"
    assert len(calls) == len(ref["calls"])
