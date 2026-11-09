"""Build and run step-by-step GUI tests with PyAutoGUI."""

from guiautomation.model import Automation, Step, StepType, ValidationError, load_automation
from guiautomation.runner import RunResult, StepResult, run_automation

__version__ = "0.1.0"

__all__ = [
    "Automation",
    "RunResult",
    "Step",
    "StepResult",
    "StepType",
    "ValidationError",
    "load_automation",
    "run_automation",
]
