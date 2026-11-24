# SPDX-License-Identifier: GPL-3.0-or-later
"""Undoing a MOVE/ROTATE/MIRROR copies the command's matrix to invert it.
ezdxf ships two Matrix44 classes: the compiled one (ezdxf.acc) accepts
another Matrix44 in its constructor, the pure-Python one (used when the C
extension is missing or disabled with EZDXF_DISABLE_C_EXT) does not and
raises ValueError. The undo must work with both."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ezdxf.math._matrix44 import Matrix44 as PureMatrix44  # noqa: E402

from core import actions  # noqa: E402
from core.commands import History  # noqa: E402
from core.document import Document  # noqa: E402


@pytest.mark.parametrize("matrix", [
    PureMatrix44.translate(3, 4, 0),
    PureMatrix44.z_rotate(1.2) @ PureMatrix44.translate(1, 2, 0),
])
def test_undo_restores_with_the_pure_python_matrix(matrix, monkeypatch):
    # as if the C extension were missing: ezdxf.math exports the Python class
    import ezdxf.math
    monkeypatch.setattr(ezdxf.math, "Matrix44", PureMatrix44)
    document = Document.new()
    line = document.doc.modelspace().add_line((0, 0), (2, 1))
    history = History(document)
    history.execute(actions.TransformCommand("MOVE", [line], matrix))
    assert tuple(line.dxf.start) != pytest.approx((0, 0, 0))
    history.undo()
    assert tuple(line.dxf.start) == pytest.approx((0, 0, 0))
    assert tuple(line.dxf.end) == pytest.approx((2, 1, 0))
