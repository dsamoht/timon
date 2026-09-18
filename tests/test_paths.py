"""Where timon's own reference data is, and what shape it may take.

The genome database is the interesting one. The pipeline hands it to `coverm
genome --genome-fasta-directory`, so it is any set of FASTA files rather than
one particular reference, and the pipeline unpacks a tarball itself. Both of
those have to be true here too, or timon refuses runs the pipeline accepts.
"""

import pytest

from timon import paths


# ── where it is ──────────────────────────────────────────────────────────────

def test_the_genome_database_defaults_to_the_full_set_under_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("TIMON_DB_DIR", str(tmp_path))
    assert paths.genomes_db() == tmp_path / paths.GENOMES_DB_NAMES[0]


def test_the_genome_database_can_be_named_outright(monkeypatch, tmp_path):
    """Which is what lets a two-genome set stand in for the ~1 GB one."""
    monkeypatch.setenv(paths.GENOMES_DB_ENV, str(tmp_path / "small"))
    assert paths.genomes_db() == tmp_path / "small"


def test_a_named_genome_database_is_expanded_from_a_tilde(monkeypatch):
    monkeypatch.setenv(paths.GENOMES_DB_ENV, "~/genomes")
    assert "~" not in str(paths.genomes_db())


# ── what shape it may take ───────────────────────────────────────────────────

def test_a_genome_database_may_be_a_directory(monkeypatch, tmp_path):
    directory = tmp_path / "genomes"
    directory.mkdir()
    monkeypatch.setenv(paths.GENOMES_DB_ENV, str(directory))
    assert paths.missing_reference_data(["genomes_db"]) == []


def test_a_genome_database_may_be_a_tarball(monkeypatch, tmp_path):
    """The pipeline unpacks one, so refusing it here would refuse a valid run."""
    tarball = tmp_path / "genomes.tar.gz"
    tarball.write_text("")
    monkeypatch.setenv(paths.GENOMES_DB_ENV, str(tarball))
    assert paths.missing_reference_data(["genomes_db"]) == []


def test_a_genome_database_that_is_not_there_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.GENOMES_DB_ENV, str(tmp_path / "absent"))
    missing = paths.missing_reference_data(["genomes_db"])
    assert len(missing) == 1
    assert "genome database not found" in missing[0]


def test_the_report_names_the_path_that_was_looked_for(monkeypatch, tmp_path):
    """So the user can see which of the two ways of naming it took effect."""
    monkeypatch.setenv(paths.GENOMES_DB_ENV, str(tmp_path / "absent"))
    assert str(tmp_path / "absent") in paths.missing_reference_data(["genomes_db"])[0]


# ── every database, found the same way ───────────────────────────────────────

@pytest.mark.parametrize("key", sorted(paths.REFERENCE_DATA))
def test_a_database_is_found_where_timon_installs_it(key, monkeypatch, tmp_path):
    """Which is how every pipeline that reads it is pointed at the same one."""
    monkeypatch.setenv("TIMON_DB_DIR", str(tmp_path))
    reference = paths.REFERENCE_DATA[key]
    assert reference.locate() == tmp_path / reference.name
    assert reference.installed_here()


@pytest.mark.parametrize("key", sorted(paths.REFERENCE_DATA))
def test_a_database_named_outright_is_not_where_timon_would_install_it(key, monkeypatch, tmp_path):
    """So the install button knows a download there would go unseen."""
    reference = paths.REFERENCE_DATA[key]
    monkeypatch.setenv(reference.env, str(tmp_path / "elsewhere"))
    assert reference.locate() == tmp_path / "elsewhere"
    assert not reference.installed_here()


# ── a database published in more than one build ──────────────────────────────
#
# The Kraken2 index is offered capped at 8 GB and at 16 GB, and the user picks
# (config.DB_SOURCES). Both land under db_root(), so "where is it" has more
# than one answer to look through — and whichever of them the user installed
# has to be the one every pipeline is then pointed at.

def test_the_kraken_index_can_be_installed_under_either_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("TIMON_DB_DIR", str(tmp_path))
    reference = paths.REFERENCE_DATA["kraken_db"]
    for name in paths.KRAKEN_DB_NAMES:
        installed = tmp_path / name
        installed.mkdir()
        assert reference.present()
        assert reference.locate() == installed
        # And it is still somewhere a download would land, so the install
        # button is not left thinking it would go unseen.
        assert reference.installed_here()
        installed.rmdir()


def test_nothing_installed_points_at_what_a_download_would_create(monkeypatch, tmp_path):
    """So "not found" names a path rather than a list of ones it might be."""
    monkeypatch.setenv("TIMON_DB_DIR", str(tmp_path))
    reference = paths.REFERENCE_DATA["kraken_db"]
    assert not reference.present()
    assert reference.locate() == tmp_path / paths.KRAKEN_DB_NAMES[0]


def test_one_cap_installed_is_not_reported_missing_because_the_other_is_not(
        monkeypatch, tmp_path):
    """The whole point of the choice: installing the 8 GB build satisfies the
    run, and timon never goes looking for the 16 GB one it was not asked for."""
    monkeypatch.setenv("TIMON_DB_DIR", str(tmp_path))
    (tmp_path / paths.KRAKEN_DB_NAMES[1]).mkdir()
    assert paths.missing_reference_data(["kraken_db"]) == []


def test_naming_the_index_outright_still_wins_over_both(monkeypatch, tmp_path):
    """A site with a shared copy has neither of timon's names, and says so."""
    monkeypatch.setenv("TIMON_DB_DIR", str(tmp_path))
    (tmp_path / paths.KRAKEN_DB_NAMES[0]).mkdir()
    shared = tmp_path / "shared_index"
    shared.mkdir()
    monkeypatch.setenv(paths.KRAKEN_DB_ENV, str(shared))
    assert paths.REFERENCE_DATA["kraken_db"].locate() == shared
    assert not paths.REFERENCE_DATA["kraken_db"].installed_here()


def test_gtdbtk_data_has_to_be_a_directory(monkeypatch, tmp_path):
    """GTDB-Tk does not unpack a tarball it is handed."""
    tarball = tmp_path / "gtdbtk.tar.gz"
    tarball.write_text("")
    monkeypatch.setenv(paths.GTDBTK_DB_ENV, str(tarball))
    assert not paths.REFERENCE_DATA["gtdbtk_db"].present()


# ── what is inside it ────────────────────────────────────────────────────────

def test_the_bracken_lengths_are_the_distributions_the_index_holds(tmp_path):
    for name in ("database300mers.kmer_distrib", "database50mers.kmer_distrib",
                 "database1000mers.kmer_distrib", "hash.k2d", "database75mers.kmer_distrib.bak"):
        (tmp_path / name).touch()
    assert paths.bracken_lengths(tmp_path) == ["50", "300", "1000"]


def test_an_index_without_distributions_offers_no_length(tmp_path):
    (tmp_path / "hash.k2d").touch()
    assert paths.bracken_lengths(tmp_path) == []


def test_an_index_that_cannot_be_looked_into_offers_no_answer(tmp_path):
    """Not there, or a tarball only the pipeline unpacks — unknown, not empty."""
    assert paths.bracken_lengths(tmp_path / "absent") is None
    tarball = tmp_path / "k2.tar.gz"
    tarball.touch()
    assert paths.bracken_lengths(tarball) is None
