"""OpenAPI/FastAPI contract analyzer. LLM dependencies load on demand."""
from drift_agent.code_analyzer import analyze_codebase
from drift_agent.diff_engine import compute_drift
from drift_agent.spec_parser import parse_spec

__all__ = ['DriftAgent', 'PatchGenerator', 'analyze_codebase', 'compute_drift', 'parse_spec']

def __getattr__(name):
    if name == 'DriftAgent':
        from drift_agent.agent.core import DriftAgent
        return DriftAgent
    if name == 'PatchGenerator':
        from drift_agent.patch_generator import PatchGenerator
        return PatchGenerator
    raise AttributeError(name)
