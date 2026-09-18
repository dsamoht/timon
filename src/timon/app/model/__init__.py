"""The model: everything timon knows and does, with no page attached.

Nothing under this package imports Flask, renders a template, or writes a
string for the eye. It answers questions about a run — which parameters it
uses, whether it can start, what nextflow would be launched with, what is in
a folder — and the view (``routes.py``, ``events.py``, ``presenters.py``,
``templates/``) is what turns those answers into a page. The dependency only
ever points that way, which is what lets any of this be exercised, and any of
it be changed, without the other half.
"""

from . import (downloads, history, live, nfstate, params, results,
               validation)
from .downloads import DownloadError
from .experiment import PINNED, EXPERIMENT, Experiment, selectable_pipelines
from .files import (ACCESS, PermissionRequired, listing, path_columns,
                    resolve, workspace_root)
from .history import RunUnavailable
from .live import Live, Tail
from .nextflow import (RUN, Container, Engine, Outcome, WorkflowError,
                       WorkflowRun, can_resume, container, engine, output_dir,
                       stop)
from .results import OutsideResults
from .samples import convert_realpaths_to_wildcards, detect_samples_files

__all__ = [
    "ACCESS", "EXPERIMENT", "Container", "DownloadError", "Engine",
    "Experiment", "Live", "Outcome", "OutsideResults", "PermissionRequired",
    "PINNED", "RUN", "RunUnavailable", "Tail", "WorkflowError",
    "WorkflowRun", "can_resume", "container", "convert_realpaths_to_wildcards",
    "detect_samples_files", "downloads", "engine",
    "history", "listing", "live", "nfstate", "output_dir", "params",
    "path_columns", "resolve", "results", "selectable_pipelines", "stop",
    "validation", "workspace_root",
]
