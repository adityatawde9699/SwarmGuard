"""Stable M4 API surface."""
from .engine import (
    CommunicationProtocol, ExperimentOrchestrator, FailureInjector,
    DiscreteEventScheduler,
    GroundTruthEvaluator, IndependentGroundTruthEvaluator, MonitoringLayer,
    Provenance, SimulationEngine, SimulationLayer,
    run_m4_scenario,
)
from .models import TaskContext
from .policy import GroupPolicyGate

__all__ = [
    "CommunicationProtocol", "ExperimentOrchestrator", "FailureInjector",
    "GroundTruthEvaluator", "IndependentGroundTruthEvaluator", "MonitoringLayer",
    "Provenance", "SimulationEngine", "SimulationLayer", "DiscreteEventScheduler",
    "TaskContext",
    "GroupPolicyGate",
    "run_m4_scenario",
]
