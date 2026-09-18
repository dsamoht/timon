"""The HTTP surface, over a real Flask test client.

Only what a route adds on top of the model is checked here: the shape of the
response the page is written against, and the status codes it branches on.
The rules themselves are tested where they live.
"""

import re

import pytest

from timon.app import model
from timon.app.model.experiment import Experiment


@pytest.fixture
def client(app, workspace, monkeypatch):
    """A page talking to an Experiment of this test's own.

    The routes read ``model.EXPERIMENT`` when they are called rather than
    holding a reference, so replacing the attribute is enough to keep one
    test's run out of the next.
    """
    experiment = Experiment()
    monkeypatch.setattr(model, "EXPERIMENT", experiment)
    with app.test_client() as client:
        client.experiment = experiment
        yield client


# ── the page ─────────────────────────────────────────────────────────────────

def test_the_page_renders(client):
    assert client.get("/").status_code == 200


def install_button(client) -> str:
    html = client.get("/").get_data(as_text=True)
    return re.search(r'<button[^>]*id="db-install-btn"[^>]*>', html, re.S).group(0)


def test_the_install_button_is_offered_on_a_fresh_install(client):
    assert "disabled" not in install_button(client)


def test_the_install_button_is_frozen_once_the_databases_are_there(client, installed):
    installed("kraken_db", "genomes_db")
    assert "disabled" in install_button(client)


# ── the rest of the surface it shares a shape with ───────────────────────────

def test_switching_pipelines_returns_the_new_form(client):
    data = client.post("/set_pipeline", data={"pipeline_select": "mag-ont"}).get_json()
    assert data["ok"] is True
    assert data["pipeline_id"] == "mag-ont"
    assert "long_reads" in data["columns"]
    assert "params_html" in data


def test_switching_pipelines_says_whether_the_new_one_can_be_tested(client):
    """The quick test button belongs to the pipeline, so it moves with it."""
    assert client.post("/set_pipeline",
                       data={"pipeline_select": "mag-ont"}).get_json()["can_test"] is False


def test_an_unknown_pipeline_is_refused(client):
    assert client.post("/set_pipeline", data={"pipeline_select": "nope"}).status_code == 400


def test_a_pipeline_that_is_not_offered_is_refused(client):
    assert client.post("/set_pipeline",
                       data={"pipeline_select": "isolate-wf"}).status_code == 400


def test_a_refused_save_comes_back_with_every_reason(client):
    response = client.post("/get_run_info_base", data={"exp-id": ""})
    assert response.status_code == 400
    body = response.get_json()
    assert body["errors"]
    assert body["error"] == body["errors"][0]


# ── reference databases ──────────────────────────────────────────────────────
#
# The page asks what is installed and what is being fetched; which databases
# are missing is the model's answer, and which can be fetched is config.py's.

def test_the_databases_are_listed_with_whether_the_run_can_start(client):
    body = client.get("/databases").get_json()

    assert body["ok"] is True
    assert body["installed"] is False
    kraken = next(db for db in body["bundle"] if db["key"] == "kraken_db")
    assert kraken["present"] is False
    assert kraken["can_install"] is True, "a Kraken2 index is published, so it is offered"
    assert body["busy"] is False
    assert body["can_start"] is False


def test_a_database_that_is_there_is_listed_as_installed(client, installed):
    installed("kraken_db")
    body = client.get("/databases").get_json()

    kraken = next(db for db in body["bundle"] if db["key"] == "kraken_db")
    assert kraken["present"] is True
    assert "kraken_db" not in body["missing"]


def test_an_install_with_nothing_left_to_do_is_not_a_refusal(client, installed):
    installed("kraken_db", "genomes_db")
    body = client.post("/databases/install").get_json()
    assert body["ok"] is True
    assert body["busy"] is False


def test_an_install_that_can_start_nothing_says_why(client):
    response = client.post("/databases/install", data={"db": "not_a_database"})

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]
    # The refusal still says what every database is, so the card that was
    # refused is not left showing something older than the answer.
    assert body["bundle"]
    assert body["busy"] is False


def test_the_build_the_page_picked_is_the_one_asked_for(client, monkeypatch):
    """The Kraken2 index is published capped at 8 GB and at 16 GB. Which one
    is the page's to hold — timon keeps no preference — so it has to survive
    the trip, on the way in and on the way back out."""
    from timon.app.model import downloads

    asked = {}
    monkeypatch.setattr(downloads, "install",
                        lambda dbs=None, choices=None: asked.update(choices or {}) or [])

    body = client.post("/databases/install",
                       data={"variant.kraken_db": "8GB"}).get_json()

    assert asked == {"kraken_db": "8GB"}
    kraken = next(db for db in body["bundle"] if db["key"] == "kraken_db")
    assert kraken["variant"] == "8GB"


def test_asking_what_is_there_carries_the_choice_too(client):
    """So the row's size follows the radio without anything being fetched."""
    body = client.get("/databases?variant.kraken_db=8GB").get_json()
    kraken = next(db for db in body["bundle"] if db["key"] == "kraken_db")

    assert kraken["variant"] == "8GB"
    assert kraken["size"] == "5.5 GB"


def test_stopping_a_download_nobody_started_is_not_an_error(client):
    body = client.post("/databases/cancel").get_json()

    assert body["ok"] is True
    assert body["stopped"] is False


def test_a_saved_configuration_comes_back_with_the_databases(client):
    """Skipping a step can take a database out of the run, so saving is when
    the line about a missing one can stop being true."""
    from timon.app.model import params as P
    client.post("/set_pipeline", data={"pipeline_select": "mag-ont"})
    form = {k: v for k, v in P.param_defaults(client.experiment.pipeline).items()
            if not isinstance(v, bool) and v is not None}
    body = client.post("/get_run_info_base",
                       data={"exp-id": "run_1", "skip_bin_qa": "on", **form}).get_json()
    assert body["databases"]["missing"] == []


# ── results ──────────────────────────────────────────────────────────────────
#
# The one part of the surface that serves file contents, so what is checked
# here is the wall around it as much as the shape of the answer.

@pytest.fixture
def outputs(client, workspace):
    """A finished run's worth of files in the output folder this page reads."""
    run = workspace / "timon_results" / "exp1"
    run.mkdir(parents=True)
    (run / "report.html").write_text("<h1>report</h1>")
    (run / "abundance.tsv").write_text("sample\tcount\na\t12\n")
    (run / "reads.bam").write_bytes(b"\x00\x01")
    return run


def test_the_output_folder_is_listed(client, outputs):
    body = client.get("/results/browse").get_json()
    assert body["ok"] is True
    assert [e["name"] for e in body["entries"]] == ["exp1"]


def test_a_listing_carries_what_the_page_prints(client, outputs):
    """Sizes, dates and glyphs are settled server-side, not in the page's JS."""
    entry = client.get("/results/browse?path=exp1").get_json()["entries"][0]
    assert entry["size_label"] and entry["when"] and entry["glyph"]


def test_the_folder_of_the_run_being_configured_is_marked(client, outputs):
    client.experiment.exp_id = "exp1"
    entry = client.get("/results/browse").get_json()["entries"][0]
    assert entry["current"] is True


def test_browsing_out_of_the_output_folder_is_refused(client, outputs):
    assert client.get("/results/browse?path=../..").status_code == 403


def test_a_folder_that_is_gone_is_a_404(client, outputs):
    assert client.get("/results/browse?path=exp1/nope").status_code == 404


def test_a_table_is_served_as_rows(client, outputs):
    body = client.get("/results/view?path=exp1/abundance.tsv").get_json()
    assert body["kind"] == "table"
    assert body["rows"][0] == ["sample", "count"]


def test_reading_out_of_the_output_folder_is_refused(client, outputs, tmp_path):
    (tmp_path / "secrets.txt").write_text("no")
    for path in ("../../secrets.txt", str(tmp_path / "secrets.txt")):
        assert client.get(f"/results/view?path={path}").status_code == 403


def test_a_file_is_served_as_itself(client, outputs):
    response = client.get("/results/raw/exp1/report.html")
    assert response.status_code == 200
    assert b"<h1>report</h1>" in response.data


def test_markup_is_served_under_a_sandbox_and_never_sniffed(client, outputs):
    """A pipeline's report must not be able to act as this page's script."""
    headers = client.get("/results/raw/exp1/report.html").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "allow-same-origin" not in headers["Content-Security-Policy"]
    assert headers["Content-Security-Policy"].startswith("sandbox")


def test_a_report_is_given_storage_before_its_own_scripts(client, outputs):
    """Sandboxed, a report's unguarded localStorage read throws and stops it."""
    body = client.get("/results/raw/exp1/report.html").data
    assert b"localStorage" in body
    assert body.index(b"localStorage") < body.index(b"<h1>report</h1>")


def test_a_downloaded_report_is_the_file_as_written(client, outputs):
    body = client.get("/results/raw/exp1/report.html?download=1").data
    assert b"localStorage" not in body


def test_a_file_can_be_asked_for_as_a_download(client, outputs):
    headers = client.get("/results/raw/exp1/reads.bam?download=1").headers
    assert "attachment" in headers["Content-Disposition"]


def test_raw_serving_cannot_leave_the_output_folder(client, outputs):
    """Climbing out of the URL is the same refusal as climbing out of a path."""
    for url in ("/results/raw/../../etc/hosts",
                "/results/raw/%2e%2e/%2e%2e/etc/hosts",
                "/results/raw/exp1/../../../etc/hosts"):
        response = client.get(url)
        assert response.status_code == 403
        assert b"localhost" not in response.data


# ── past runs ────────────────────────────────────────────────────────────────
#
# Two routes, and what they add over the model is the shape the runs view
# renders and the status codes it branches on.

@pytest.fixture
def recorded(client, workspace, installed):
    """A run this workspace remembers, configured the way the form would."""
    from timon.app.model import history
    from timon.app.model import params as P

    reads = workspace / "sample.fastq"
    reads.write_text("")
    experiment = client.experiment
    installed()
    values = P.param_defaults(experiment.pipeline)
    assert experiment.apply_configuration("past_run", values) == []
    row = {column: "x" for column in experiment.pipeline["columns"]}
    row.update({"sample_id": "s1", "date": "2026-01-01",
                experiment.pipeline["file_column"]: str(reads)})
    assert experiment.set_samples([row]) == []
    record = history.started(experiment.run_spec(), ["nextflow", "run", "x"])
    record = history.finished(record, history.FAILED, 1)
    experiment.reset()
    return record


def test_a_workspace_with_no_runs_lists_none(client):
    assert client.get("/runs").get_json() == {"ok": True, "runs": [],
                                              "elsewhere": []}


def test_a_recorded_run_is_listed_as_the_page_prints_it(client, recorded):
    row = client.get("/runs").get_json()["runs"][0]
    assert row["id"] == "past_run"
    assert row["status"]["label"] == "failed"
    # Worded and measured server-side, like every other listing timon serves.
    assert row["since"] and row["when"] and row["pipeline"] == "roshab-cli"
    assert row["n_samples"] == 1


def test_reopening_a_run_returns_the_form_and_the_rows(client, recorded):
    body = client.post("/runs/open", data={"exp_id": "past_run"}).get_json()
    assert body["ok"] is True
    assert body["id"] == "past_run"
    assert body["pinned"] is True
    assert body["params_html"] and body["columns"]
    assert len(body["samples"]) == 1
    assert body["databases"]["bundle"]
    assert client.experiment.exp_id == "past_run"


def test_a_pinned_run_refuses_a_switch_with_the_reason(client, recorded):
    client.post("/runs/open", data={"exp_id": "past_run"})
    response = client.post("/set_pipeline", data={"pipeline_select": "mag-ont"})
    assert response.status_code == 400
    assert response.get_json()["error"] == model.PINNED


def test_unpinning_a_run_says_it_is_no_longer_held(client, recorded):
    client.post("/runs/open", data={"exp_id": "past_run"})
    body = client.post("/runs/unpin").get_json()
    assert body["ok"] is True
    assert body["pinned"] is False
    assert body["id"] == "past_run"


def test_reopening_a_run_that_is_not_there_is_a_404(client):
    assert client.post("/runs/open", data={"exp_id": "never"}).status_code == 404


def test_a_saved_configuration_says_what_running_it_would_do(client, recorded, db_dir):
    """Typing an identifier that already names a run is how a restart starts."""
    from timon.app.model import params as P
    values = P.param_defaults(client.experiment.pipeline)
    values["kraken_db"] = str(db_dir)
    body = client.post("/get_run_info_base",
                       data={"exp-id": "past_run", "resume": "on", **values}).get_json()
    assert body["restart"]["previous"] is True
    assert body["restart"]["status"]["label"] == "failed"
