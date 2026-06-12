"""SWE-Bench-CL learning-curve pilot harness.

Does a lesson store under survival selection produce a learning curve
on real software-engineering task sequences? SWE-Bench-CL (arXiv
2507.00014) organizes SWE-Bench Verified instances into per-repository
continual-learning sequences; this package pins one or two of those
sequences, runs a model through them task by task under three arms
(memory_on, memory_off, random_matched), settles the lesson store from
the per-task test outcome, and records one run JSON per task in the
committed-results format the rest of ``bench/`` uses.

Plumbing first, science later: every piece here runs offline against
the stub executor and a fake endpoint, and the real Docker path is
guarded so it can never eat a laptop's disk. docs/benchmarks.md holds
the pre-committed pilot protocol.
"""

from .arms import ARMS, ArmSpec
from .dataset import DATASET_PIN, DatasetPin, TaskRecord, build_manifest, load_dataset
from .executor import DiskGuardError, DockerExecutor, EvalReport, StubExecutor
from .lessons import mint_lesson
from .model import ChatEndpoint, EndpointConfig, extract_patch, extract_reflection
from .runner import run_sequence

__all__ = [
    "ARMS",
    "DATASET_PIN",
    "ArmSpec",
    "ChatEndpoint",
    "DatasetPin",
    "DiskGuardError",
    "DockerExecutor",
    "EndpointConfig",
    "EvalReport",
    "StubExecutor",
    "TaskRecord",
    "build_manifest",
    "extract_patch",
    "extract_reflection",
    "load_dataset",
    "mint_lesson",
    "run_sequence",
]
