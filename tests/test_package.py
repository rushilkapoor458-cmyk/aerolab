"""Smoke tests for the package skeleton.

These test the plumbing, not the physics: that the package imports, that the
subpackages exist, that the CLI is wired up, and that the exception hierarchy
behaves. Physics tests live beside the solver modules they exercise and are
checked against analytical results or published data, never against a
previously recorded output of this package.
"""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

import aerolab
from aerolab.exceptions import AerolabError, ConvergenceError

SUBPACKAGES = [
    "aerolab.geometry",
    "aerolab.inviscid",
    "aerolab.viscous",
    "aerolab.compressible",
    "aerolab.tunnel",
    "aerolab.validation",
]


def test_version_is_a_nonempty_string() -> None:
    assert isinstance(aerolab.__version__, str)
    assert aerolab.__version__


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    """Every architectural subpackage exists and is importable."""
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} has no module docstring"


def test_scientific_stack_available() -> None:
    """NumPy and SciPy are importable and new enough for the API used here."""
    import numpy as np
    import scipy

    assert int(np.__version__.split(".")[0]) >= 2
    major, minor = (int(p) for p in scipy.__version__.split(".")[:2])
    assert (major, minor) >= (1, 14)


def test_import_works_from_an_unrelated_directory(tmp_path) -> None:
    """`import aerolab` must not depend on the current working directory.

    Runs a fresh interpreter in an empty temporary directory, which is the
    only honest way to prove the editable install is on the path rather than
    the repository root merely happening to be the CWD.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import aerolab; print(aerolab.__version__)"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == aerolab.__version__


def test_cli_reports_version() -> None:
    """The installed `aerolab` console script runs and reports its version."""
    result = subprocess.run(
        ["aerolab", "version"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert aerolab.__version__ in result.stdout


class TestExceptions:
    """The no-silent-failure contract starts with a usable exception type."""

    def test_convergence_error_is_an_aerolab_error(self) -> None:
        err = ConvergenceError(
            "panel solver stalled", iterations=50, residual=1e-3, tolerance=1e-8
        )
        assert isinstance(err, AerolabError)

    def test_convergence_error_carries_diagnostics(self) -> None:
        """A failed solve must say how hard it tried and how close it got."""
        err = ConvergenceError(
            "panel solver stalled", iterations=50, residual=1e-3, tolerance=1e-8
        )
        assert err.iterations == 50
        assert err.residual == pytest.approx(1e-3)
        assert err.tolerance == pytest.approx(1e-8)
        # The numbers must be in the message too - a traceback in a log file
        # is often all you get.
        assert "50" in str(err)
        assert "1.000e-03" in str(err)
