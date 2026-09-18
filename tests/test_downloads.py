"""Fetching a reference database, without fetching a reference database.

Every source timon declares is gigabytes over the network, so the suite
declares its own and serves it from a ``file://`` URL: urllib treats one like
any other, Content-Length and all, which is what lets the progress counters,
the unpacking and the cleaning up be tested without a byte leaving the
machine.

What is worth testing here is not the transfer — that is urllib's — but the
promise around it: nothing appears under the reference data directory until it
is whole, nothing is ever overwritten, and a download that fails or is stopped
leaves the directory as it found it.
"""

import tarfile

import pytest

from timon import paths
from timon.app.model import downloads


@pytest.fixture(autouse=True)
def db_root(tmp_path, monkeypatch):
    """A reference data directory of this test's own, and an empty registry.

    ``downloads.DOWNLOADS`` is module state, like the experiment is, so one
    test's download would otherwise be another's "already going".
    """
    root = tmp_path / "reference"
    monkeypatch.setenv("TIMON_DB_DIR", str(root))
    monkeypatch.setattr(downloads, "DOWNLOADS", {})
    return root


@pytest.fixture
def declare(monkeypatch, tmp_path):
    """Declare a source the way config.DB_SOURCES does, and hand it back."""
    def make(url, *, db="kraken_db", archive=False, install_as="test_db"):
        entry = {"label": "Test index", "size": "1 kB",
                 "url": str(url), "archive": archive, "install_as": install_as,
                 "description": "for the suite"}
        monkeypatch.setitem(downloads.DB_SOURCES, db, entry)
        return downloads.source(db)
    return make


@pytest.fixture
def served(tmp_path):
    """A file to be fetched, as a URL."""
    def make(name: str, content: bytes = b"an index") -> str:
        path = tmp_path / "served" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.as_uri()
    return make


def run(db: str) -> downloads.Download:
    """Start one and wait for it — the tests are about what it left behind."""
    download = downloads.start(db)
    download.wait(30)
    return download


def tarball(tmp_path, members: dict[str, str]) -> str:
    """A .tar.gz holding the named files, as a URL."""
    path = tmp_path / "served" / "package.tar.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, text in members.items():
            member = tmp_path / "build" / name.replace("../", "up_")
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_text(text)
            tar.add(member, arcname=name)
    return path.as_uri()


# ── what is on offer ─────────────────────────────────────────────────────────

def test_a_database_with_nothing_published_for_it_offers_nothing(monkeypatch):
    """Which is a normal answer: the page says it is missing all the same."""
    monkeypatch.delitem(downloads.DB_SOURCES, "genomes_db")
    assert downloads.source("genomes_db") is None
    assert downloads.refusal("genomes_db")


def test_a_database_with_no_source_is_refused_before_anything_is_fetched(monkeypatch):
    monkeypatch.delitem(downloads.DB_SOURCES, "genomes_db")
    with pytest.raises(downloads.DownloadError):
        downloads.start("genomes_db")


def test_a_database_timon_does_not_know_about_is_refused():
    with pytest.raises(downloads.DownloadError):
        downloads.start("not_a_database")


# ── a database published in more than one build ──────────────────────────────
#
# The Kraken2 index is offered capped at 8 GB and at 16 GB. Everything below
# here reads the same declaration, normalised: a database published one way is
# its own single variant, so nothing past downloads.variants has two shapes to
# reason about.

BIG, SMALL = paths.KRAKEN_DB_NAMES


@pytest.fixture
def two_builds(monkeypatch, served):
    """A database declared in two builds, the second of them the default.

    Each lands under one of the names paths.py looks for, as the real
    declaration does — which is what makes "installing one is installing the
    database" true here rather than only asserted.
    """
    def make(db="kraken_db"):
        entry = {
            "label": "Test index", "archive": False,
            "description": "for the suite", "default": "small",
            "variants": [
                {"id": "big",   "label": "Test index (big)",   "size": "2 kB",
                 "url": served("big.k2d", b"a big index"),
                 "install_as": BIG,   "note": "the larger one"},
                {"id": "small", "label": "Test index (small)", "size": "1 kB",
                 "url": served("small.k2d", b"a small index"),
                 "install_as": SMALL, "note": "the smaller one"},
            ],
        }
        monkeypatch.setitem(downloads.DB_SOURCES, db, entry)
        return entry
    return make


def test_every_build_is_offered_with_the_default_first(two_builds):
    two_builds()
    built = downloads.variants("kraken_db")

    assert [src.variant for src in built] == ["small", "big"]
    # What each build changes is its own; what they share comes from the entry
    # around them, so it is written once.
    assert [src.install_as for src in built] == [SMALL, BIG]
    assert {src.description for src in built} == {"for the suite"}


def test_a_database_published_one_way_is_its_own_single_build(declare, served):
    declare(served("index.k2d"))
    built = downloads.variants("kraken_db")

    assert len(built) == 1
    # No id, which is what tells the page there is no choice to draw.
    assert built[0].variant == ""


def test_asking_for_no_build_in_particular_takes_the_declared_default(two_builds):
    two_builds()
    assert downloads.source("kraken_db").variant == "small"


def test_the_build_asked_for_is_the_one_fetched(two_builds, db_root):
    two_builds()
    download = downloads.start("kraken_db", "big")
    download.wait(30)

    assert download.state == downloads.DONE
    assert (db_root / BIG).read_bytes() == b"a big index"
    assert not (db_root / SMALL).exists()


def test_the_default_is_what_the_install_button_fetches(two_builds, db_root, monkeypatch):
    """A user who never opened the choice gets the build timon declares."""
    monkeypatch.setattr(downloads, "DATABASE_BUNDLE", ["kraken_db"])
    two_builds()
    for download in downloads.install():
        download.wait(30)

    assert (db_root / SMALL).exists()


def test_the_bundle_takes_the_build_it_is_handed(two_builds, db_root, monkeypatch):
    monkeypatch.setattr(downloads, "DATABASE_BUNDLE", ["kraken_db"])
    two_builds()
    for download in downloads.install(choices={"kraken_db": "big"}):
        download.wait(30)

    assert (db_root / BIG).exists()


def test_a_build_nobody_declared_is_refused_by_name(two_builds):
    """Rather than as "nothing is published for it", which is a different
    fault and would send the user looking in the wrong place."""
    two_builds()
    assert "no Kraken2 database build called 'huge'" in downloads.refusal("kraken_db", "huge")
    with pytest.raises(downloads.DownloadError, match="huge"):
        downloads.start("kraken_db", "huge")


def test_one_build_installed_stops_the_other_being_fetched(two_builds, db_root):
    """Either build is the database, and timon reads whichever is there — so a
    second is gigabytes for something no pipeline would ever be pointed at."""
    two_builds()
    downloads.start("kraken_db", "small").wait(30)

    assert "already installed" in downloads.refusal("kraken_db", "big")
    with pytest.raises(downloads.DownloadError):
        downloads.start("kraken_db", "big")


# ── what it leaves behind ────────────────────────────────────────────────────

def test_a_plain_file_lands_under_the_reference_data_directory(declare, served, db_root):
    declare(served("index.k2d"), install_as="k2_test")
    download = run("kraken_db")

    assert download.state == downloads.DONE
    assert (db_root / "k2_test").read_bytes() == b"an index"
    assert download.path == str(db_root / "k2_test")


def test_the_counters_say_how_much_of_it_has_arrived(declare, served):
    declare(served("index.k2d", b"x" * 4096))
    download = run("kraken_db")

    assert download.done == 4096
    assert download.total == 4096


def test_a_package_wrapped_in_one_folder_is_unwrapped(declare, tmp_path, db_root):
    """GTDB-Tk's is a release folder, and the database is what is inside it."""
    declare(tarball(tmp_path, {"release232/taxonomy.tsv": "a\tb"}),
            archive=True, install_as="gtdbtk_data")
    run("kraken_db")

    assert (db_root / "gtdbtk_data" / "taxonomy.tsv").is_file()
    assert not (db_root / "gtdbtk_data" / "release232").exists()


def test_a_package_of_loose_files_becomes_the_database_directory(declare, tmp_path, db_root):
    """A Kraken2 index is: hash.k2d and its siblings, with nothing around them."""
    declare(tarball(tmp_path, {"hash.k2d": "h", "ktaxonomy.tsv": "k"}),
            archive=True, install_as="k2_test")
    run("kraken_db")

    assert (db_root / "k2_test" / "hash.k2d").is_file()
    assert (db_root / "k2_test" / "ktaxonomy.tsv").is_file()


def test_nothing_is_left_beside_the_database_it_installed(declare, tmp_path, db_root):
    """The part file and the staging directory are both the download's own."""
    declare(tarball(tmp_path, {"hash.k2d": "h"}), archive=True, install_as="k2_test")
    run("kraken_db")

    assert [p.name for p in db_root.iterdir()] == ["k2_test"]


# ── when it does not work ────────────────────────────────────────────────────

def test_a_download_that_fails_leaves_the_directory_as_it_found_it(declare, tmp_path, db_root):
    declare((tmp_path / "served" / "absent.tar.gz").as_uri(),
            archive=True, install_as="k2_test")
    download = run("kraken_db")

    assert download.state == downloads.FAILED
    assert download.error
    assert not db_root.exists() or list(db_root.iterdir()) == []


def test_a_tarball_that_reaches_outside_itself_is_refused(declare, tmp_path, db_root):
    """A package from the network is not trusted to name where it unpacks."""
    declare(tarball(tmp_path, {"../escaped.tsv": "no"}),
            archive=True, install_as="k2_test")
    download = run("kraken_db")

    assert download.state == downloads.FAILED
    assert not (db_root.parent / "escaped.tsv").exists()


def test_a_stopped_download_installs_nothing(declare, served, db_root):
    """Cancelling is read between chunks, so it is answered before the file is."""
    source = declare(served("index.k2d", b"x" * 4096))
    download = downloads.Download(source)
    download.cancel()
    download.start()
    download.wait(30)

    assert download.state == downloads.CANCELLED
    assert not (db_root / "test_db").exists()
    assert not db_root.exists() or list(db_root.iterdir()) == []


def test_only_a_download_still_arriving_can_be_stopped(declare, served):
    """Unpacking is one call into tarfile — timon cannot interrupt it."""
    declare(served("index.k2d"))
    run("kraken_db")

    assert downloads.cancel("kraken_db") is False


# ── what it refuses ──────────────────────────────────────────────────────────

def test_a_database_already_installed_is_never_downloaded_over(declare, served, db_root):
    """The thing being replaced may be a hundred gigabytes fetched last month."""
    declare(served("index.k2d"), install_as="k2_test")
    run("kraken_db")
    (db_root / "k2_test").write_bytes(b"the one already there")

    with pytest.raises(downloads.DownloadError):
        downloads.start("kraken_db")
    assert (db_root / "k2_test").read_bytes() == b"the one already there"


def test_one_download_per_database_at_a_time(declare, served):
    declare(served("index.k2d"))
    going = downloads.Download(downloads.source("kraken_db"))
    downloads.DOWNLOADS["kraken_db"] = going          # left in its starting state

    assert downloads.busy() is True
    with pytest.raises(downloads.DownloadError):
        downloads.start("kraken_db")


def test_nothing_is_being_fetched_once_the_last_one_is_over(declare, served):
    """What tells the page it can stop asking."""
    declare(served("index.k2d"))
    run("kraken_db")

    assert downloads.busy() is False


def test_a_database_timon_is_told_to_look_for_elsewhere_is_not_fetched(declare, served, db_root,
                                                                       monkeypatch, tmp_path):
    """A download lands under the data directory; one that landed where timon
    is not looking would be gigabytes spent on a database still missing."""
    declare(served("index.k2d"), install_as=paths.KRAKEN_DB_NAMES[0])
    monkeypatch.setenv("KRAKEN_DB", str(tmp_path / "moved"))

    assert "KRAKEN_DB" in downloads.refusal("kraken_db")
    with pytest.raises(downloads.DownloadError):
        downloads.start("kraken_db")


def test_a_database_named_outright_and_there_is_already_installed(db_root, monkeypatch, db_dir):
    monkeypatch.setenv("KRAKEN_DB", str(db_dir))
    assert "already installed" in downloads.refusal("kraken_db")


# ── the bundle ───────────────────────────────────────────────────────────────

def test_the_bundle_is_missing_until_every_database_in_it_is_there(installed):
    assert set(downloads.bundle_missing()) == set(downloads.DATABASE_BUNDLE)
    installed(*downloads.DATABASE_BUNDLE)
    assert downloads.bundle_missing() == []


def test_installing_fetches_what_is_missing_and_passes_over_what_is_there(
        declare, served, installed, monkeypatch):
    """Pressing the button again after one download failed fetches that one."""
    monkeypatch.setattr(downloads, "DATABASE_BUNDLE", ["kraken_db", "gtdbtk_db"])
    declare(served("index.k2d"), install_as=paths.KRAKEN_DB_NAMES[0])
    installed("gtdbtk_db")

    started = downloads.install()
    for download in started:
        download.wait(30)

    assert [d.source.db for d in started] == ["kraken_db"]
    assert downloads.bundle_missing() == []


def test_installing_with_nothing_it_can_start_says_why(monkeypatch):
    monkeypatch.delitem(downloads.DB_SOURCES, "genomes_db")
    monkeypatch.setattr(downloads, "DATABASE_BUNDLE", ["genomes_db"])
    with pytest.raises(downloads.DownloadError, match="genome database"):
        downloads.install()


def test_installing_what_is_all_there_is_nothing_to_do(installed):
    installed(*downloads.DATABASE_BUNDLE)
    assert downloads.install() == []


def test_stopping_with_no_database_named_stops_every_one_arriving(declare, served):
    declare(served("index.k2d"))
    going = downloads.Download(downloads.source("kraken_db"))
    downloads.DOWNLOADS["kraken_db"] = going

    assert downloads.cancel() is True
    assert going._cancel.is_set()
