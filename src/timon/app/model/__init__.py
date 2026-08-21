"""The model: everything timon knows and does, with no page attached.

Nothing under this package imports Flask, renders a template, or writes a
string for the eye. It answers questions about a run — which parameters it
uses, whether it can start, what nextflow would be launched with, what is in
a folder — and the view (``routes.py``, ``events.py``, ``presenters.py``,
``templates/``) is what turns those answers into a page. The dependency only
ever points that way, which is what lets any of this be exercised, and any of
it be changed, without the other half.
"""

from . import params, validation
from .experiment import EXPERIMENT, Experiment
from .files import (ACCESS, PermissionRequired, listing, path_columns,
                    resolve, workspace_root)
from .nextflow import RUN, Engine, Outcome, WorkflowError, WorkflowRun, engine
from .samples import convert_realpaths_to_wildcards, detect_samples_files

__all__ = [
    "ACCESS", "EXPERIMENT", "Engine", "Experiment", "Outcome",
    "PermissionRequired", "RUN", "WorkflowError", "WorkflowRun",
    "convert_realpaths_to_wildcards", "detect_samples_files", "engine",
    "listing", "params", "path_columns", "resolve", "validation",
    "workspace_root",
]
