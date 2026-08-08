"""Exception hierarchy for aerolab.

The package rule is that a solver never returns a plausible-looking wrong
number. Any condition that invalidates a result raises one of these, or is
reported through an explicit status flag on the result object. Silence is
never an option.

Every exception derives from :class:`AerolabError`, so a caller that wants to
catch "anything aerolab considers a failure" can catch that one class.
"""

from __future__ import annotations


class AerolabError(Exception):
    """Base class for every error raised by aerolab."""


class GeometryError(AerolabError):
    """The geometry is malformed or physically impossible.

    Raised for self-intersecting surfaces, non-monotonic coordinate ordering
    that cannot be repaired, negative thickness, or a chord of zero length.
    """


class ConvergenceError(AerolabError):
    """An iterative solver failed to reach its tolerance.

    Attributes
    ----------
    iterations : int
        Number of iterations actually performed before giving up.
    residual : float
        Final residual, in the norm documented by the solver that raised.
    tolerance : float
        Residual the solver was required to reach.
    """

    def __init__(
        self,
        message: str,
        *,
        iterations: int,
        residual: float,
        tolerance: float,
    ) -> None:
        super().__init__(
            f"{message} (stopped after {iterations} iterations, "
            f"residual {residual:.3e} > tolerance {tolerance:.3e})"
        )
        self.iterations = iterations
        self.residual = residual
        self.tolerance = tolerance


class SingularSystemError(AerolabError):
    """The linear system assembled by a panel method is singular or near-singular.

    Usually caused by duplicate panel endpoints, a zero-length panel, or a
    trailing edge whose two panels are collinear.
    """


class ValidityRangeError(AerolabError):
    """Inputs are outside the range in which the model is defensible.

    Raised rather than silently extrapolating — for example a compressibility
    correction asked for a local Mach number well above the transonic
    threshold, or a boundary-layer correlation asked for a shape factor
    outside the range its data was fitted over.
    """
