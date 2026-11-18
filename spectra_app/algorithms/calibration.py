"""Hardware-in-the-loop baseline calibration for S.P.E.C.T.R.A."""

from __future__ import annotations

import numpy as np

from rad_daes.background.model import BackgroundModel


def build_background_model(
    samples,
    covariance_shrinkage: float = 0.10,
    covariance_floor: float = 1e-6,
    covariance_floor_fraction: float = 0.25,
) -> BackgroundModel:
    """Build a regularized six-channel model from clean baseline samples."""

    x = np.asarray(samples, dtype=float)

    if x.ndim != 2 or x.shape[1] != 6:
        raise ValueError("Expected samples with shape (n, 6)")

    if x.shape[0] < 30:
        raise ValueError("At least 30 baseline samples are required")

    if not np.all(np.isfinite(x)):
        raise ValueError("Baseline contains non-finite observations")

    if np.any(x < 0):
        raise ValueError("Channel observations cannot be negative")

    if not 0.0 <= covariance_shrinkage <= 1.0:
        raise ValueError("Shrinkage must be between 0 and 1")

    mean = np.mean(x, axis=0)
    empirical_covariance = np.cov(x, rowvar=False, ddof=1)

    diagonal = np.diag(np.diag(empirical_covariance))

    covariance = (
        (1.0 - covariance_shrinkage) * empirical_covariance
        + covariance_shrinkage * diagonal
    )

    channel_floors = np.maximum(
        covariance_floor,
        covariance_floor_fraction * mean,
    )

    current_diagonal = np.diag(covariance).copy()
    required_diagonal = np.maximum(current_diagonal, channel_floors)

    covariance += np.diag(required_diagonal - current_diagonal)
    covariance = 0.5 * (covariance + covariance.T)

    return BackgroundModel(
        mean=mean,
        covariance=covariance,
    )
