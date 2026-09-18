"""Fixtures shared by the suite.

Two things need care in every test here. The application state is a module
level singleton (``model.EXPERIMENT``), so a test that configures a run would
leak into the next one unless it gets its own ``Experiment``; and the input
folder is resolved against the process's working directory, so a test that
writes a sample sheet has to be pointed at a temporary one or it will litter
the checkout.

Both are handled below, which is why no test needs to know about either.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from timon import paths                                 # noqa: E402
from timon.app import create_app                        # noqa: E402
from timon.app.config import PIPELINES, Config          # noqa: E402
from timon.app import model                             # noqa: E402
from timon.app.model import Container, Engine, downloads  # noqa: E402
from timon.app.model.experiment import Experiment       # noqa: E402


@pytest.fixture(scope="session")
def app():
    """One application for the whole suite, shared by every test that needs one.

    ``create_app`` registers the routes and the socket handlers by importing
    ``routes.py`` and ``events.py`` inside an app context, and a module is
    only imported once — so a second application built in the same process
    gets neither. Which is why this lives here rather than in the files that
    use it: two of them would leave one silently answering 404 to everything.
    """
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """Nothing in the suite may depend on, or leak into, the real environment.

    Two of these matter enough to be worth naming. timon finds databases by
    itself, so a developer who has installed them — or has KRAKEN_DB or
    TIMON_GENOMES_DB set in their shell — would otherwise see different
    results from CI, which is why TIMON_DB_DIR is an empty directory of the
    test's own; and XDG_STATE_HOME is where a launched run leaves the pointer that
    says it is going, so a test that starts one must not be able to reach the
    developer's own — or to leave anything of its own behind in it.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TIMON_DB_DIR", str(tmp_path / "databases"))
    # What is being fetched is module state, like the experiment is, so one
    # test's download would otherwise be the next one's "already going".
    monkeypatch.setattr(downloads, "DOWNLOADS", {})
    for name in (paths.GENOMES_DB_ENV, "TIMON_NEXTFLOW",
                 "TIMON_PROFILE", "KRAKEN_DB", "GTDBTK_DB", "INPUT_DIR",
                 "OUTPUT_DIR",
                 "TIMON_MAX_CPUS", "TIMON_MAX_MEMORY", "TIMON_MAX_TIME"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def installed_engines(monkeypatch):
    """Nextflow and a container engine, as a fact of the suite rather than of
    the machine it runs on.

    Neither is ever launched — a short python program stands in for nextflow
    and nothing here provisions a task — but whether a run *could* start is
    part of what a page is told, and it must not depend on whether the
    developer has nextflow installed or Docker running this morning. A test
    about the absence of either says so itself, by handing the presenter the
    engine it means (tests/test_presenters.py) or by patching what the model
    looks for (tests/test_nextflow.py).
    """
    monkeypatch.setattr(model, "engine", lambda: Engine(
        binary="nextflow", path="/usr/bin/nextflow",
        version="nextflow version 24.10.0"))
    monkeypatch.setattr(model, "container", lambda profile="": Container(
        profile=profile or "docker", binary="docker",
        path="/usr/bin/docker", version="Docker version 27.3.1",
        daemon=True))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A temporary launch directory, with both folders pointed inside it.

    Config.IMPORT_FOLDER and Config.OUTPUT_FOLDER are read when an Experiment
    resets, so setting them here is what keeps sample sheets, copied reads and
    anything a run writes out of the real checkout.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Config, "IMPORT_FOLDER", str(tmp_path / "imports"))
    monkeypatch.setattr(Config, "OUTPUT_FOLDER", str(tmp_path / "timon_results"))
    return tmp_path


@pytest.fixture
def experiment(workspace):
    """A run of timon's own, on a machine with no databases installed.

    That much is clean_environment's doing; the ones a test needs it installs
    with ``installed``.
    """
    return Experiment()


@pytest.fixture
def roshab():
    return PIPELINES["roshab-cli"]


@pytest.fixture
def magont():
    return PIPELINES["mag-ont"]


@pytest.fixture
def reads(workspace):
    """A factory for empty read files, for the checks that only want a path.

    Validation asks whether the path exists, never what is in it, so a real
    fastq would only make the tests slower to read.
    """
    def make(relative: str) -> Path:
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        return path
    return make


@pytest.fixture
def configured(reads):
    """A factory for a run that is ready to start, filled in as the form fills it.

    Every value goes in through the same ``Experiment`` methods a saved form
    posts to, so what comes back is refused for the same reasons a user's
    configuration would be — a test that gets a ready run out of this has one
    nextflow could really be launched on.

    mag-ont with bin QA skipped is the default because it reads no reference
    database at all (see "db_optional_when"), so a test that only needs a
    startable run needs nothing installed. Asking for another pipeline means
    installing what that one reads.
    """
    from timon.app.model import params as P, validation

    def configure(experiment, pipeline: str = "mag-ont", exp_id: str = "run_1",
                  params: dict | None = None, n_samples: int = 2) -> None:
        assert experiment.set_pipeline(pipeline)
        pipe = experiment.pipeline

        values = P.param_defaults(pipe)
        values.update({"skip_bin_qa": True} if pipeline == "mag-ont" else {})
        values.update(params or {})
        assert experiment.apply_configuration(exp_id, values) == []

        # Every column the pipeline insists on gets something that passes its
        # own check — only the file column is looked for on disk — and the
        # ones it treats as optional are left empty, as the form leaves them.
        required = set(validation.required_columns(pipe))
        rows = []
        for n in range(n_samples):
            sample_id = f"sample_{n + 1}"
            row = {column: ("x" if column in required else "")
                   for column in pipe["columns"]}
            row["sample_id"] = sample_id
            row["group"] = exp_id
            if "date" in required:
                row["date"] = f"2026-01-0{n + 1}"
            row[pipe["file_column"]] = str(reads(f"{exp_id}_reads/{sample_id}.fastq.gz"))
            rows.append(row)
        assert experiment.set_samples(rows) == []

    return configure


@pytest.fixture
def installed():
    """A factory that installs databases where timon looks for them.

    A directory under TIMON_DB_DIR for each: presence is all timon asks of
    one, so that is all a test has to make — except that a Kraken2 index is
    also looked into for its Bracken lengths, so it gets the pipeline's
    default one. Returns where they went.
    """
    def install(*keys: str) -> dict:
        keys = keys or tuple(paths.REFERENCE_DATA)
        where = {}
        for key in keys:
            path = paths.REFERENCE_DATA[key].locate()
            path.mkdir(parents=True, exist_ok=True)
            if key == "kraken_db":
                (path / "database300mers.kmer_distrib").touch()
            where[key] = path
        return where
    return install


@pytest.fixture
def db_dir(tmp_path):
    """A directory that exists, to stand in for a reference database.

    Validation asks whether the path is there, never what is inside it, so a
    real Kraken2 index would only make the suite impossible to run.
    """
    path = tmp_path / "reference_db"
    path.mkdir()
    return path
