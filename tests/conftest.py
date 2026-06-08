"""Shared pytest fixtures."""
import os
import sys

# Make the repo root importable.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from ml_models.boolean_synth import BooleanSynthesizer
from ml_models.fault_detector import FaultDetector
from ml_models.gate_minimizer import GateMinimizer
from ml_models.question_solver import QuestionSolver


@pytest.fixture(scope="session")
def synth():
    return BooleanSynthesizer()


@pytest.fixture(scope="session")
def solver(synth):
    return QuestionSolver(
        fault_detector=FaultDetector(),
        gate_minimizer=GateMinimizer(),
        boolean_synth=synth,
    )


def gate_types(circuit):
    """Return non-IO gate types as a list."""
    return [g["type"] for g in circuit.get("gates", [])
            if g["type"] not in ("INPUT", "OUTPUT")]
