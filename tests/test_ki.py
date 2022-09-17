#!/usr/bin/env python3
"""Tests for ki command line interface (CLI)."""
import os
import gc
import sys
import json
import time
import random
import shutil
import tempfile
import itertools
from pathlib import Path
from dataclasses import dataclass

import git
import pytest
import bitstring
import checksumdir
from lark import Lark
from lark.exceptions import UnexpectedToken
from loguru import logger
from pytest_mock import MockerFixture
from click.testing import CliRunner

import anki.collection
from anki.collection import Collection, Note

from beartype import beartype
from beartype.typing import List, Union, Set, Iterator, Tuple

import ki
import ki.maybes as M
import ki.functional as F
from ki import (
    BRANCH_NAME,
    KI,
    MEDIA,
    HEAD_SUFFIX,
    REMOTE_SUFFIX,
    HASHES_FILE,
    MODELS_FILE,
    CONFIG_FILE,
    LAST_PUSH_FILE,
    GITIGNORE_FILE,
    BACKUPS_DIR,
    NotetypeDict,
    DeckNote,
    GitChangeType,
    Notetype,
    ColNote,
    Delta,
    Dir,
    File,
    EmptyDir,
    NotetypeMismatchError,
    UnhealthyNoteWarning,
    KiRepo,
    KiRev,
    get_note_warnings,
    cp_ki,
    get_note_payload,
    create_deck_dir,
    get_note_path,
    git_pull,
    get_colnote,
    backup,
    update_note,
    parse_notetype_dict,
    display_fields_health_warning,
    is_anki_note,
    parse_markdown_note,
    lock,
    unsubmodule_repo,
    write_repository,
    get_target,
    push_note,
    get_models_recursively,
    append_md5sum,
    copy_media_files,
    diff2,
    _clone,
    add_db_note,
    tidy_html_recursively,
)
from ki.types import (
    NoFile,
    NoPath,
    Leaves,
    PseudoFile,
    ExpectedEmptyDirectoryButGotNonEmptyDirectoryError,
    StrangeExtantPathError,
    MissingNotetypeError,
    MissingFieldOrdinalError,
    MissingNoteIdError,
    ExpectedNonexistentPathError,
    UnPushedPathWarning,
    DiffTargetFileNotFoundWarning,
    NotetypeKeyError,
    UnnamedNotetypeError,
    NoteFieldKeyError,
    PathCreationCollisionError,
    ExpectedDirectoryButGotFileError,
    GitHeadRefNotFoundError,
    MissingMediaDirectoryError,
    TargetExistsError,
    WrongFieldCountWarning,
    InconsistentFieldNamesWarning,
)
from ki.transformer import NoteTransformer


# pylint: disable=unnecessary-pass, too-many-lines, invalid-name
# pylint: disable=missing-function-docstring, too-many-instance-attributes
# pylint: disable=too-many-statements


@beartype
@dataclass(frozen=True)
class SampleCollection:
    """A test collection with all names and paths constructed."""

    col_file: File
    path: Path
    stem: str
    suffix: str
    repodir: str
    filename: str
    media_db_path: Path
    media_db_filename: str
    media_directory_path: Path
    media_directory_name: str


@beartype
@dataclass(frozen=True)
class DiffReposArgs:
    """Arguments for `diff2()`."""

    repo: git.Repo
    parser: Lark
    transformer: NoteTransformer


@beartype
def get_test_collection(stem: str) -> SampleCollection:
    collections_path = Path(__file__).parent / "data" / "collections"

    # Handle restricted valid path character set on Win32.
    if stem in ("multideck", "html") and sys.platform == "win32":
        stem = f"win32_{stem}"

    repodir = stem
    suffix = ".anki2"
    filename = stem + suffix
    path = (collections_path / filename).resolve()
    media_db_filename = stem + ".media.db2"
    media_db_path = collections_path / media_db_filename
    media_directory_name = stem + ".media"
    media_directory_path = collections_path / media_directory_name

    # Get col file.
    tempdir = Path(tempfile.mkdtemp())
    col_file = tempdir / filename
    shutil.copyfile(path, col_file)

    if media_db_path.exists():
        shutil.copyfile(media_db_path, tempdir / media_db_filename)
    if media_directory_path.exists():
        shutil.copytree(media_directory_path, tempdir / media_directory_name)

    return SampleCollection(
        F.chk(Path(col_file)),
        path,
        stem,
        suffix,
        repodir,
        filename,
        media_db_path,
        media_db_filename,
        media_directory_path,
        media_directory_name,
    )


TEST_DATA_PATH = "tests/data/"
COLLECTIONS_PATH = os.path.join(TEST_DATA_PATH, "collections/")


GITREPO_PATH = os.path.abspath(os.path.join(TEST_DATA_PATH, "repos/", "original/"))
MULTI_GITREPO_PATH = os.path.join(TEST_DATA_PATH, "repos/", "multideck/")
JAPANESE_GITREPO_PATH = os.path.join(TEST_DATA_PATH, "repos/", "japanese-core-2000/")

MULTI_NOTE_PATH = "aa/bb/cc/cc.md"

NOTES_PATH = os.path.abspath(os.path.join(TEST_DATA_PATH, "notes/"))
MEDIA_PATH = os.path.abspath(os.path.join(TEST_DATA_PATH, "media/"))
SUBMODULE_DIRNAME = "submodule"

MEDIA_FILENAME = "bullhorn-lg.png"
MEDIA_FILE_PATH = os.path.join(MEDIA_PATH, MEDIA_FILENAME)

NOTE_0 = "Default/a.md"
NOTE_1 = "Default/f.md"
NOTE_2 = "note123412341234.md"
NOTE_3 = "note 3.md"
NOTE_4 = "Default/c.md"
NOTE_5 = "alpha_guid.md"
NOTE_6 = "no_guid.md"
NOTE_7 = "Default/aa.md"
MEDIA_NOTE = "air.md"

NOTE_0_PATH = os.path.join(NOTES_PATH, NOTE_0)
NOTE_1_PATH = os.path.join(NOTES_PATH, NOTE_1)
NOTE_2_PATH = os.path.join(NOTES_PATH, NOTE_2)
NOTE_3_PATH = os.path.join(NOTES_PATH, NOTE_3)
NOTE_4_PATH = os.path.join(NOTES_PATH, NOTE_4)
NOTE_5_PATH = os.path.join(NOTES_PATH, NOTE_5)
NOTE_6_PATH = os.path.join(NOTES_PATH, NOTE_6)
MEDIA_NOTE_PATH = os.path.join(NOTES_PATH, MEDIA_NOTE)

NOTE_0_ID = 1645010162168
NOTE_4_ID = 1645027705329
MULTI_NOTE_ID = 1645985861853

# A models dictionary mapping model ids to notetype dictionaries.
# Note that the `flds` field has been removed.
MODELS_DICT = {
    "1645010146011": {
        "id": 1645010146011,
        "name": "Basic",
        "type": 0,
        "mod": 0,
        "usn": 0,
        "sortf": 0,
        "did": None,
        "tmpls": [
            {
                "name": "Card 1",
                "ord": 0,
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}",
                "bqfmt": "",
                "bafmt": "",
                "did": None,
                "bfont": "",
                "bsize": 0,
            }
        ],
        "req": [[0, "any", [0]]],
    }
}
NAMELESS_MODELS_DICT = {
    "1645010146011": {
        "id": 1645010146011,
    }
}
NT = {
    "id": 1645010146011,
    "name": "Basic",
    "type": 0,
    "mod": 0,
    "usn": 0,
    "sortf": 0,
    "did": None,
    "tmpls": [
        {
            "name": "Card 1",
            "ord": 0,
            "qfmt": "{{Front}}",
            "afmt": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}",
            "bqfmt": "",
            "bafmt": "",
            "did": None,
            "bfont": "",
            "bsize": 0,
        }
    ],
    "flds": [
        {
            "name": "Front",
            "ord": 0,
            "sticky": False,
            "rtl": False,
            "font": "Arial",
            "size": 20,
        },
        {
            "name": "Back",
            "ord": 1,
            "sticky": False,
            "rtl": False,
            "font": "Arial",
            "size": 20,
        },
    ],
    "req": [[0, "any", [0]]],
}

# HELPER FUNCTIONS


def invoke(*args, **kwargs):
    """Wrap click CliRunner invoke()."""
    return CliRunner().invoke(*args, **kwargs)


@beartype
def clone(
    runner: CliRunner,
    collection: File,
    directory: str = "",
    verbose: bool = False,
) -> str:
    """Make a test `ki clone` call."""
    res = runner.invoke(
        ki.ki,
        ["clone", str(collection), str(directory)] + (["-v"] if verbose else []),
        standalone_mode=False,
        catch_exceptions=False,
    )
    return res.output


@beartype
def pull(runner: CliRunner) -> str:
    """Make a test `ki pull` call."""
    res = runner.invoke(ki.ki, ["pull"], standalone_mode=False, catch_exceptions=False)
    return res.output


@beartype
def push(runner: CliRunner, verbose: bool = False) -> str:
    """Make a test `ki push` call."""
    res = runner.invoke(
        ki.ki,
        ["push"] + (["-v"] if verbose else []),
        standalone_mode=False,
        catch_exceptions=False,
    )
    return res.output


@beartype
def is_git_repo(path: str) -> bool:
    """Check if path is git repository."""
    if not os.path.isdir(path):
        return False
    try:
        _ = git.Repo(path).git_dir
        return True
    except git.InvalidGitRepositoryError:
        return False


@beartype
def randomly_swap_1_bit(path: File) -> None:
    """Randomly swap a bit in a file."""
    # Read in bytes.
    with open(path, "rb") as file:
        data: bytes = file.read()

    # Construct BitArray and swap bit.
    bits = bitstring.BitArray(bytes=data)
    i = random.randrange(len(bits))
    bits.invert(i)

    # Write out bytes.
    with open(path, "wb") as file:
        file.write(bits.bytes)


@beartype
def checksum_git_repository(path: str) -> str:
    """Compute a checksum of git repository without .git folder."""
    assert is_git_repo(path)
    tempdir = tempfile.mkdtemp()
    repodir = os.path.join(tempdir, "REPO")
    shutil.copytree(path, repodir)
    F.rmtree(F.chk(Path(os.path.join(repodir, ".git/"))))
    checksum = checksumdir.dirhash(repodir)
    F.rmtree(F.chk(Path(tempdir)))
    return checksum


@beartype
def get_notes(collection: File) -> List[ColNote]:
    """Get a list of notes from a path."""
    cwd: Dir = F.cwd()
    col = Collection(collection)
    F.chdir(cwd)

    notes: List[ColNote] = []
    for nid in set(col.find_notes("")):
        colnote: ColNote = get_colnote(col, nid)
        notes.append(colnote)

    return notes


@beartype
def get_repo_with_submodules(runner: CliRunner, col_file: File) -> git.Repo:
    """Return repo with committed submodule."""
    # Clone collection in cwd.
    ORIGINAL = get_test_collection("original")
    clone(runner, col_file)
    repo = git.Repo(ORIGINAL.repodir)
    cwd = F.cwd()
    os.chdir(ORIGINAL.repodir)

    # Create submodule out of GITREPO_PATH.
    submodule_name = SUBMODULE_DIRNAME
    shutil.copytree(GITREPO_PATH, submodule_name)
    git.Repo.init(submodule_name, initial_branch=BRANCH_NAME)
    sm = git.Repo(submodule_name)
    sm.git.add(all=True)
    _ = sm.index.commit("Initial commit.")

    # Add as a submodule.
    repo.git.submodule("add", Path(submodule_name).resolve())
    repo.git.add(all=True)
    _ = repo.index.commit("Add submodule.")

    # Go back to the original current working directory.
    os.chdir(cwd)

    return repo


# UTILS


def test_parse_markdown_note():
    """Does ki raise an error when it fails to parse nid?"""
    # Read grammar.
    # UNSAFE! Should we assume this always exists? A nice error message should
    # be printed on initialization if the grammar file is missing. No
    # computation should be done, and none of the click commands should work.
    grammar_path = Path(ki.__file__).resolve().parent / "grammar.lark"
    grammar = grammar_path.read_text(encoding="UTF-8")

    # Instantiate parser.
    parser = Lark(grammar, start="note", parser="lalr")
    transformer = NoteTransformer()

    with pytest.raises(UnexpectedToken):
        delta = Delta(GitChangeType.ADDED, F.chk(Path(NOTE_6_PATH)), Path("a/b"))
        parse_markdown_note(parser, transformer, delta)


def test_get_batches():
    """Does it get batches from a list of strings?"""
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = F.cwd()
        one = F.touch(root, "note1.md")
        two = F.touch(root, "note2.md")
        three = F.touch(root, "note3.md")
        four = F.touch(root, "note4.md")
        batches = list(F.get_batches([one, two, three, four], n=2))
        assert batches == [[one, two], [three, four]]


def test_is_anki_note():
    """Do the checks in ``is_anki_note()`` actually do anything?"""
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = F.cwd()
        mda = F.touch(root, "note.mda")
        amd = F.touch(root, "note.amd")
        mdtxt = F.touch(root, "note.mdtxt")
        nd = F.touch(root, "note.nd")

        assert is_anki_note(mda) is False
        assert is_anki_note(amd) is False
        assert is_anki_note(mdtxt) is False
        assert is_anki_note(nd) is False

        note_file: File = F.touch(root, "note.md")

        note_file.write_text("", encoding="UTF-8")
        assert is_anki_note(note_file) is False

        note_file.write_text("one line", encoding="UTF-8")
        assert is_anki_note(note_file) is False

        note_file.write_text("## Note\n# Note\n\n\n\n\n\n\n\n", encoding="UTF-8")
        assert is_anki_note(note_file) is False

        note_file.write_text("# Note\n```\nguid: 00a\n\n\n\n\n\n\n", encoding="UTF-8")
        assert is_anki_note(note_file) is True

        note_file.write_text("# Note\n```\nguid: 00\n\n\n\n\n\n\n\n", encoding="UTF-8")
        assert is_anki_note(note_file) is True


@beartype
def open_collection(col_file: File) -> Collection:
    cwd: Dir = F.cwd()
    col = Collection(col_file)
    F.chdir(cwd)
    return col


def test_update_note_raises_error_on_too_few_fields():
    """Do we raise an error when the field names don't match up?"""
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    field = "data"

    # Note that "Back" field is missing.
    decknote = DeckNote("title", "0", "Default", "Basic", [], {"Front": field})
    notetype: Notetype = parse_notetype_dict(note.note_type())
    warnings = update_note(note, decknote, notetype, notetype)
    warning: Warning = warnings.pop()
    assert isinstance(warning, Warning)
    assert isinstance(warning, WrongFieldCountWarning)
    assert "Wrong number of fields for model 'Basic'" in str(warning)


def test_update_note_raises_error_on_too_many_fields():
    """Do we raise an error when the field names don't match up?"""
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    field = "data"

    # Note that "Left" field is extra.
    fields = {"Front": field, "Back": field, "Left": field}
    decknote = DeckNote("title", "0", "Default", "Basic", [], fields)

    notetype: Notetype = parse_notetype_dict(note.note_type())
    warnings = update_note(note, decknote, notetype, notetype)
    warning: Warning = warnings.pop()
    assert isinstance(warning, Warning)
    assert isinstance(warning, WrongFieldCountWarning)
    assert "Wrong number of fields for model 'Basic'" in str(warning)


def test_update_note_raises_error_wrong_field_name():
    """Do we raise an error when the field names don't match up?"""
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    field = "data"

    # Field `Backus` has wrong name, should be `Back`.
    fields = {"Front": field, "Backus": field}
    decknote = DeckNote("title", "0", "Default", "Basic", [], fields)

    notetype: Notetype = parse_notetype_dict(note.note_type())
    warnings = update_note(note, decknote, notetype, notetype)
    warning: Warning = warnings.pop()
    assert isinstance(warning, Warning)
    assert isinstance(warning, InconsistentFieldNamesWarning)
    assert "Inconsistent field names" in str(warning)
    assert "Backus" in str(warning)
    assert "Back" in str(warning)


def test_update_note_sets_tags():
    """Do we update tags of anki note?"""
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    field = "data"

    fields = {"Front": field, "Back": field}
    decknote = DeckNote("", "0", "Default", "Basic", ["tag"], fields)

    assert note.tags == []
    notetype: Notetype = parse_notetype_dict(note.note_type())
    update_note(note, decknote, notetype, notetype)
    assert note.tags == ["tag"]


def test_update_note_sets_deck():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    field = "data"

    fields = {"Front": field, "Back": field}
    decknote = DeckNote("title", "0", "deck", "Basic", [], fields)

    # TODO: Remove implicit assumption that all cards are in the same deck, and
    # work with cards instead of notes.
    deck = col.decks.name(note.cards()[0].did)
    assert deck == "Default"
    notetype: Notetype = parse_notetype_dict(note.note_type())
    update_note(note, decknote, notetype, notetype)
    deck = col.decks.name(note.cards()[0].did)
    assert deck == "deck"


def test_update_note_sets_field_contents():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    field = "TITLE\ndata"
    fields = {"Front": field, "Back": field}
    decknote = DeckNote("title", "0", "Default", "Basic", [], fields)

    assert "TITLE" not in note.fields[0]

    notetype: Notetype = parse_notetype_dict(note.note_type())
    update_note(note, decknote, notetype, notetype)

    assert note.fields[0] == "TITLE<br>data"


def test_update_note_removes_field_contents():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    field = "y"
    fields = {"Front": field, "Back": field}
    decknote = DeckNote("title", "0", "Default", "Basic", [], fields)

    assert "a" in note.fields[0]
    notetype: Notetype = parse_notetype_dict(note.note_type())
    update_note(note, decknote, notetype, notetype)
    assert "a" not in note.fields[0]


def test_update_note_raises_error_on_nonexistent_notetype_name():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    field = "data"
    fields = {"Front": field, "Back": field}
    decknote = DeckNote("title", "0", "Nonexistent", "Default", [], fields)

    notetype: Notetype = parse_notetype_dict(note.note_type())

    with pytest.raises(NotetypeMismatchError):
        update_note(note, decknote, notetype, notetype)


def test_display_fields_health_warning_catches_missing_clozes():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    field = "data"
    fields = {"Text": field, "Back Extra": ""}
    decknote = DeckNote("title", "0", "Default", "Cloze", [], fields)

    clz: NotetypeDict = col.models.by_name("Cloze")
    cloze: Notetype = parse_notetype_dict(clz)
    notetype: Notetype = parse_notetype_dict(note.note_type())
    warnings = update_note(note, decknote, notetype, cloze)
    warning = warnings.pop()
    assert isinstance(warning, Exception)
    assert isinstance(warning, UnhealthyNoteWarning)

    msg = "Warning: Note '1645010162168' failed fields check with error code '3'"
    assert str(warning) == msg


def test_update_note_changes_notetype():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    field = "data"
    fields = {"Front": field, "Back": field}
    decknote = DeckNote(
        "title", "0", "Default", "Basic (and reversed card)", [], fields
    )

    rev: NotetypeDict = col.models.by_name("Basic (and reversed card)")
    reverse: Notetype = parse_notetype_dict(rev)
    notetype: Notetype = parse_notetype_dict(note.note_type())
    update_note(note, decknote, notetype, reverse)


def test_display_fields_health_warning_catches_empty_notes():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    note.fields = []
    health = display_fields_health_warning(note)
    assert health == 1


def test_slugify_handles_unicode():
    """Test that slugify handles unicode alphanumerics."""
    # Hiragana should be okay.
    text = "ゅ"
    result = F.slugify(text)
    assert result == text

    # Emojis as well.
    text = "😶"
    result = F.slugify(text)
    assert result == text


def test_slugify_handles_html_tags():
    text = '<img src="card11front.jpg" />'
    result = F.slugify(text)

    assert result == "img-srccard11frontjpg"


@beartype
def get_colnote_with_sortf_text(sortf_text: str) -> Tuple[Collection, ColNote]:
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    notetype: Notetype = parse_notetype_dict(note.note_type())
    deck = col.decks.name(note.cards()[0].did)
    return col, ColNote(
        n=note,
        new=False,
        deck=deck,
        title="",
        markdown=False,
        notetype=notetype,
        sortf_text=sortf_text,
    )


@beartype
def get_basic_colnote_with_fields(front: str, back: str) -> Tuple[Collection, ColNote]:
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    note["Front"] = front
    note["Back"] = back
    note.flush()

    notetype: Notetype = parse_notetype_dict(note.note_type())
    deck = col.decks.name(note.cards()[0].did)
    return col, ColNote(
        n=note,
        new=False,
        deck=deck,
        title="",
        markdown=False,
        notetype=notetype,
        sortf_text=note[notetype.sortf.name],
    )


def test_get_note_path_produces_nonempty_filenames():
    field_text = '<img src="card11front.jpg" />'
    col, colnote = get_colnote_with_sortf_text(field_text)

    runner = CliRunner()
    with runner.isolated_filesystem():
        deck_dir: Dir = F.force_mkdir(Path("a"))

        payload = get_note_payload(colnote, {})
        path: File = get_note_path(colnote, deck_dir)
        assert path.name == "img-srccard11frontjpg.md"

        # Check that it even works if the field is empty.
        col, empty_colnote = get_colnote_with_sortf_text("")
        payload = get_note_payload(empty_colnote, {})
        path: File = get_note_path(empty_colnote, deck_dir)
        assert ".md" in str(path)
        assert f"{os.sep}a{os.sep}" in str(path)

        col, empty = get_basic_colnote_with_fields("", "")
        payload = get_note_payload(empty, {})
        path: File = get_note_path(empty, deck_dir)


@beartype
def get_diff2_args() -> DiffReposArgs:
    """
    A test 'fixture' (not really a pytest fixture, but a setup function) to be
    called when we need to test `diff2()`.

    Basically a section of the code from `push()`, but without any error
    handling, since we expect things to work out nicely, and for the
    repositories operated upon during tests to be valid.

    Returns the values needed to pass as arguments to `diff2()`.

    This makes ephemeral repositories, so we should make any changes we expect
    to see the results of in `deltas: List[Delta]` *before* calling this
    function. For example, if we wanted to add a note, and then expected to see
    a `GitChangeType.ADDED`, then we should do that in `ORIGINAL.repodir`
    before calling this function.
    """
    cwd: Dir = F.cwd()
    kirepo: KiRepo = M.kirepo(cwd)
    lock(kirepo.col_file)
    md5sum: str = F.md5(kirepo.col_file)
    head: KiRev = M.head_ki(kirepo)
    head_kirepo: KiRepo = cp_ki(head, f"{HEAD_SUFFIX}-{md5sum}")
    remote_root: EmptyDir = F.mksubdir(F.mkdtemp(), REMOTE_SUFFIX / md5sum)
    msg = f"Fetch changes from collection '{kirepo.col_file}' with md5sum '{md5sum}'"
    remote_repo, _ = _clone(
        kirepo.col_file, remote_root, msg, silent=True, verbose=False
    )
    git_copy = F.copytree(F.gitd(remote_repo), F.chk(F.mkdtemp() / "GIT"))
    remote_root: Dir = F.root(remote_repo)
    remote_repo.close()
    remote_root: NoFile = F.rmtree(remote_root)
    remote_root: Dir = F.copytree(head_kirepo.root, remote_root)
    remote_repo: git.Repo = unsubmodule_repo(M.repo(remote_root))
    git_dir: Dir = F.gitd(remote_repo)
    remote_repo.close()
    git_dir: NoPath = F.rmtree(git_dir)
    F.copytree(git_copy, F.chk(git_dir))
    remote_repo: git.Repo = M.repo(remote_root)
    remote_repo.git.add(all=True)
    remote_repo.index.commit(f"Pull changes from repository at '{kirepo.root}'")
    grammar_path = Path(ki.__file__).resolve().parent / "grammar.lark"
    grammar = grammar_path.read_text(encoding="UTF-8")
    parser = Lark(grammar, start="note", parser="lalr")
    transformer = NoteTransformer()

    return DiffReposArgs(remote_repo, parser, transformer)


def test_diff2_shows_no_changes_when_no_changes_have_been_made(tmp_path: Path):
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):

        # Clone collection in cwd.
        clone(runner, ORIGINAL.col_file)
        os.chdir(ORIGINAL.repodir)

        args: DiffReposArgs = get_diff2_args()
        deltas: List[Delta] = diff2(
            args.repo,
            args.parser,
            args.transformer,
        )

        changed = [str(delta.path) for delta in deltas]
        assert changed == []


def test_diff2_yields_a_warning_when_a_file_cannot_be_found(tmp_path: Path):
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):

        # Clone collection in cwd.
        clone(runner, ORIGINAL.col_file)
        os.chdir(ORIGINAL.repodir)

        shutil.copyfile(NOTE_2_PATH, NOTE_2)
        repo = git.Repo(".")
        repo.git.add(all=True)
        repo.index.commit("CommitMessage")

        args: DiffReposArgs = get_diff2_args()

        os.remove(Path(args.repo.working_dir) / NOTE_2)

        deltas: List[Union[Delta, Warning]] = diff2(
            args.repo,
            args.parser,
            args.transformer,
        )
        del args
        gc.collect()
        warnings = [d for d in deltas if isinstance(d, DiffTargetFileNotFoundWarning)]
        assert len(warnings) == 1
        warning = warnings.pop()
        assert "note123412341234.md" in str(warning)


def test_unsubmodule_repo_removes_gitmodules(tmp_path: Path):
    """
    When you have a ki repo with submodules, does calling
    `unsubmodule_repo()`on it remove them? We test this by checking if the
    `.gitmodules` file exists.
    """
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        repo = get_repo_with_submodules(runner, ORIGINAL.col_file)
        gitmodules_path = Path(repo.working_dir) / ".gitmodules"
        assert gitmodules_path.exists()
        unsubmodule_repo(repo)
        assert not gitmodules_path.exists()


def test_diff2_handles_submodules():
    """
    Does 'diff2()' correctly generate deltas
    when adding submodules and when removing submodules?
    """
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem():
        repo = get_repo_with_submodules(runner, ORIGINAL.col_file)

        os.chdir(ORIGINAL.repodir)

        args: DiffReposArgs = get_diff2_args()
        deltas: List[Delta] = diff2(
            args.repo,
            args.parser,
            args.transformer,
        )
        del args
        gc.collect()

        assert len(deltas) == 1
        delta = deltas[0]
        assert isinstance(delta, Delta)
        assert delta.status == GitChangeType.ADDED
        assert str(Path("submodule") / "Default" / "a.md") in str(delta.path)

        # Push changes.
        push(runner)

        # Remove submodule.
        F.rmtree(F.chk(Path(SUBMODULE_DIRNAME)))
        repo.git.add(all=True)
        _ = repo.index.commit("Remove submodule.")

        args: DiffReposArgs = get_diff2_args()
        deltas: List[Delta] = diff2(
            args.repo,
            args.parser,
            args.transformer,
        )
        del args
        gc.collect()
        deltas = [d for d in deltas if isinstance(d, Delta)]

        # We expect the following delta (GitChangeType.RENAMED):
        #
        # DEBUG    | ki:diff2:389 - submodule/Default/a.md -> Default/a.md

        assert len(deltas) > 0
        for delta in deltas:
            assert delta.path.is_file()


def test_backup_is_no_op_when_backup_already_exists(mocker: MockerFixture):
    """
    Does the second subsequent backup call register as redundant (we assume a
    nice error message is displayed if so)?
    """
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem():
        clone(runner, ORIGINAL.col_file)
        os.chdir(ORIGINAL.repodir)
        kirepo: KiRepo = M.kirepo(F.cwd())

        mock = mocker.patch("ki.echo")

        returncode: int = backup(kirepo)
        assert returncode == 0

        returncode = backup(kirepo)
        assert returncode == 1


def test_git_pull():
    ORIGINAL = get_test_collection("original")
    EDITED = get_test_collection("edited")
    runner = CliRunner()
    with runner.isolated_filesystem():

        # Clone collection in cwd.
        clone(runner, ORIGINAL.col_file)

        # Edit collection.
        shutil.copyfile(EDITED.path, ORIGINAL.col_file)
        os.chdir(ORIGINAL.repodir)

        # Pull, poorly.
        with pytest.raises(RuntimeError):
            git_pull(
                "anki",
                "main",
                cwd=F.cwd(),
                unrelated=True,
                theirs=True,
                check=True,
                silent=False,
            )


def test_get_note_path():
    """Do we add ordinals to generated filenames if there are duplicates?"""
    runner = CliRunner()
    col, colnote = get_colnote_with_sortf_text("a")
    with runner.isolated_filesystem():
        deck_dir = F.cwd()
        dupe_path = deck_dir / "a.md"
        dupe_path.write_text("ay")
        payload = get_note_payload(colnote, {})
        note_path = get_note_path(colnote, deck_dir)
        assert str(note_path.name) == "a_1.md"


def test_tidy_html_recursively():
    """Does tidy wrapper print a nice error when tidy is missing?"""
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = F.cwd()
        file = root / "a.html"
        file.write_text("ay")
        old_path = os.environ["PATH"]
        try:
            os.environ["PATH"] = ""
            with pytest.raises(FileNotFoundError) as error:
                tidy_html_recursively(root, False)
            assert "'tidy'" in str(error.exconly())
        finally:
            os.environ["PATH"] = old_path


def test_create_deck_dir():
    deckname = "aa::bb::cc"
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = F.cwd()
        path = create_deck_dir(deckname, root)
        assert path.is_dir()
        assert os.path.isdir("aa/bb/cc")


def test_create_deck_dir_strips_leading_periods():
    deckname = ".aa::bb::.cc"
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = F.cwd()
        path = create_deck_dir(deckname, root)
        assert path.is_dir()
        assert os.path.isdir("aa/bb/cc")


def test_get_note_payload():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    colnote: ColNote = get_colnote(col, note.id)
    runner = CliRunner()
    with runner.isolated_filesystem():

        # Field-note content id for the note returned by our `col.get_note()`
        # call above. Perhaps this should not be hardcoded.
        fid = "1645010162168front"

        # We use the fid as the filename as well for convenience, but there is
        # no reason this must be the case.
        path = Path(fid)

        # Dump content to the file. This represents our tidied HTML source.
        heyoo = "HEYOOOOO"
        path.write_text(heyoo, encoding="UTF-8")

        result = get_note_payload(colnote, {fid: path})

        # Check that the dumped `front` field content is there.
        assert heyoo in result

        # The `back` field content.
        assert "\nb\n" in result


def test_write_repository_generates_deck_tree_correctly(tmp_path: Path):
    """Does generated FS tree match example collection?"""
    MULTIDECK: SampleCollection = get_test_collection("multideck")
    true_note_path = os.path.abspath(os.path.join(MULTI_GITREPO_PATH, MULTI_NOTE_PATH))
    cloned_note_path = os.path.join(MULTIDECK.repodir, MULTI_NOTE_PATH)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):

        targetdir = F.chk(Path(MULTIDECK.repodir))
        targetdir = F.mkdir(targetdir)
        kid = F.mkdir(F.chk(Path(MULTIDECK.repodir) / KI))
        media_dir = F.mkdir(F.chk(Path(MULTIDECK.repodir) / MEDIA))
        leaves: Leaves = F.fmkleaves(
            kid,
            files={CONFIG_FILE: CONFIG_FILE, LAST_PUSH_FILE: LAST_PUSH_FILE},
            dirs={BACKUPS_DIR: BACKUPS_DIR},
        )

        write_repository(
            MULTIDECK.col_file,
            targetdir,
            leaves,
            media_dir,
            silent=False,
            verbose=False,
        )

        # Check that deck directory is created and all subdirectories.
        assert os.path.isdir(os.path.join(MULTIDECK.repodir, "Default"))
        assert os.path.isdir(os.path.join(MULTIDECK.repodir, "aa/bb/cc"))
        assert os.path.isdir(os.path.join(MULTIDECK.repodir, "aa/dd"))

        # Compute hashes.
        cloned_md5 = F.md5(File(cloned_note_path))
        true_md5 = F.md5(File(true_note_path))

        assert cloned_md5 == true_md5


def test_write_repository_handles_html():
    """Does generated repo handle html okay?"""
    MULTIDECK: SampleCollection = get_test_collection("multideck")
    HTML: SampleCollection = get_test_collection("html")
    runner = CliRunner()
    with runner.isolated_filesystem():

        targetdir = F.mkdir(F.chk(Path(HTML.repodir)))
        kid = F.mkdir(F.chk(Path(HTML.repodir) / KI))
        media_dir = F.mkdir(F.chk(Path(MULTIDECK.repodir) / MEDIA))
        leaves: Leaves = F.fmkleaves(
            kid,
            files={CONFIG_FILE: CONFIG_FILE, LAST_PUSH_FILE: LAST_PUSH_FILE},
            dirs={BACKUPS_DIR: BACKUPS_DIR},
        )
        write_repository(
            HTML.col_file, targetdir, leaves, media_dir, silent=False, verbose=False
        )

        note_file = targetdir / "Default" / "あだ名.md"
        contents: str = note_file.read_text(encoding="UTF-8")

        assert '<div class="word-card">\n  <table class="kanji-match">' in contents


@beartype
def test_write_repository_propogates_errors_from_get_colnote(mocker: MockerFixture):
    """Do errors get forwarded nicdely?"""
    MULTIDECK: SampleCollection = get_test_collection("multideck")
    HTML: SampleCollection = get_test_collection("html")
    runner = CliRunner()
    with runner.isolated_filesystem():

        targetdir = F.mkdir(F.chk(Path(HTML.repodir)))
        kid = F.mkdir(F.chk(Path(HTML.repodir) / KI))
        media_dir = F.mkdir(F.chk(Path(MULTIDECK.repodir) / MEDIA))
        leaves: Leaves = F.fmkleaves(
            kid,
            files={CONFIG_FILE: CONFIG_FILE, LAST_PUSH_FILE: LAST_PUSH_FILE},
            dirs={BACKUPS_DIR: BACKUPS_DIR},
        )

        mocker.patch(
            "ki.get_colnote", side_effect=NoteFieldKeyError("'bad_field_key'", 0)
        )
        with pytest.raises(NoteFieldKeyError) as error:
            write_repository(
                HTML.col_file, targetdir, leaves, media_dir, silent=False, verbose=False
            )
        assert "'bad_field_key'" in str(error.exconly())


def test_maybe_kirepo_displays_nice_errors(tmp_path: Path):
    """Does a nice error get printed when kirepo metadata is missing?"""
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):

        # Case where `.ki/` directory doesn't exist.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        F.rmtree(targetdir / KI)
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "fatal: not a ki repository" in str(error.exconly())
        F.rmtree(targetdir)

        # Case where `.ki/` is a file instead of a directory.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        F.rmtree(targetdir / KI)
        (targetdir / KI).touch()
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "fatal: not a ki repository" in str(error.exconly())
        F.rmtree(targetdir)

        # Case where `.ki/backups` directory doesn't exist.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        F.rmtree(targetdir / KI / BACKUPS_DIR)
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "Directory not found" in str(error.exconly())
        assert "'.ki/backups'" in str(error.exconly())
        F.rmtree(targetdir)

        # Case where `.ki/backups` is a file instead of a directory.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        F.rmtree(targetdir / KI / BACKUPS_DIR)
        (targetdir / KI / BACKUPS_DIR).touch()
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "A directory was expected" in str(error.exconly())
        assert "'.ki/backups'" in str(error.exconly())
        gc.collect()
        F.rmtree(targetdir)

        # Case where `.ki/config` file doesn't exist.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        os.remove(targetdir / KI / CONFIG_FILE)
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "File not found" in str(error.exconly())
        assert "'.ki/config'" in str(error.exconly())
        F.rmtree(targetdir)

        # Case where `.ki/config` is a directory instead of a file.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        os.remove(targetdir / KI / CONFIG_FILE)
        os.mkdir(targetdir / KI / CONFIG_FILE)
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "A file was expected" in str(error.exconly())
        assert "'.ki/config'" in str(error.exconly())
        F.rmtree(targetdir)

        # Case where `.ki/hashes` file doesn't exist.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        os.remove(targetdir / KI / HASHES_FILE)
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "File not found" in str(error.exconly())
        assert "'.ki/hashes'" in str(error.exconly())
        F.rmtree(targetdir)

        # Case where `.ki/models` file doesn't exist.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        os.remove(targetdir / MODELS_FILE)
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "File not found" in str(error.exconly())
        assert f"'{MODELS_FILE}'" in str(error.exconly())
        F.rmtree(targetdir)

        # Case where collection file doesn't exist.
        clone(runner, ORIGINAL.col_file)
        targetdir: Dir = F.chk(Path(ORIGINAL.repodir))
        os.remove(ORIGINAL.col_file)
        with pytest.raises(Exception) as error:
            M.kirepo(targetdir)
        assert "File not found" in str(error.exconly())
        assert "'.anki2'" in str(error.exconly())
        assert "database" in str(error.exconly())
        assert ORIGINAL.filename in str(error.exconly())
        F.rmtree(targetdir)


def test_get_target(tmp_path: Path):
    """Do we print a nice error when the targetdir is nonempty?"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.mkdir("file")
        Path("file/subfile").touch()
        col_file: File = F.touch(F.cwd(), "file.anki2")
        with pytest.raises(TargetExistsError) as error:
            get_target(F.cwd(), col_file, "")
        assert "fatal: destination path" in str(error.exconly())
        assert "file" in str(error.exconly())


def test_maybe_emptydir(tmp_path: Path):
    """Do we print a nice error when the directory is unexpectedly nonempty?"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("file").touch()
        with pytest.raises(ExpectedEmptyDirectoryButGotNonEmptyDirectoryError) as error:
            M.emptydir(F.cwd())
        assert "but it is nonempty" in str(error.exconly())
        assert str(Path.cwd()) in str(error.exconly()).replace("\n", "")


def test_maybe_emptydir_handles_non_directories(tmp_path: Path):
    """Do we print a nice error when the path is not a directory?"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        file = Path("file")
        file.touch()
        with pytest.raises(ExpectedDirectoryButGotFileError) as error:
            M.emptydir(file)
        assert str(file) in str(error.exconly()).replace("\n", "")


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not have `os.mkfifo()`."
)
def test_maybe_xdir(tmp_path: Path):
    """Do we print a nice error when there is a non-file non-directory thing?"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.mkfifo("pipe")
        with pytest.raises(StrangeExtantPathError) as error:
            M.xdir(Path("pipe"))
        assert "pseudofile" in str(error.exconly())
        assert "pipe" in str(error.exconly())


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not have `os.mkfifo()`."
)
def test_maybe_xfile(tmp_path: Path):
    """Do we print a nice error when there is a non-file non-directory thing?"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.mkfifo("pipe")
        with pytest.raises(StrangeExtantPathError) as error:
            M.xfile(Path("pipe"))
        assert "pseudofile" in str(error.exconly())
        assert "pipe" in str(error.exconly())


def test_push_note():
    """Do we print a nice error when a notetype is missing?"""
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)

    field = "data"
    fields = {"Front": field, "Back": field}
    decknote = DeckNote("title", "0", "Default", "NonexistentModel", [], fields)
    new_nids: Iterator[int] = itertools.count(int(time.time_ns() / 1e6))
    with pytest.raises(MissingNotetypeError) as error:
        push_note(col, decknote, int(time.time_ns()), {}, new_nids)
    assert "NonexistentModel" in str(error.exconly())


def test_maybe_head():
    runner = CliRunner()
    with runner.isolated_filesystem():
        repo = git.Repo.init("repo")
        with pytest.raises(GitHeadRefNotFoundError) as error:
            M.head(repo)
        err_snippet = "ValueError raised while trying to get rev 'HEAD' from repo"
        assert err_snippet in str(error.exconly())


def test_maybe_head_ki():
    ORIGINAL: SampleCollection = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem():

        # Initialize the kirepo *without* committing.
        os.mkdir("original")
        targetdir = F.chk(Path("original"))
        silent = False
        kid: EmptyDir = F.mksubdir(targetdir, Path(KI))
        media_dir = F.mkdir(F.chk(targetdir / MEDIA))
        leaves: Leaves = F.fmkleaves(
            kid,
            files={CONFIG_FILE: CONFIG_FILE, LAST_PUSH_FILE: LAST_PUSH_FILE},
            dirs={BACKUPS_DIR: BACKUPS_DIR},
        )
        md5sum = F.md5(ORIGINAL.col_file)
        ignore_path = targetdir / GITIGNORE_FILE
        ignore_path.write_text(".ki/\n")
        write_repository(
            ORIGINAL.col_file, targetdir, leaves, media_dir, silent, verbose=False
        )
        repo = git.Repo.init(targetdir, initial_branch=BRANCH_NAME)
        append_md5sum(kid, ORIGINAL.col_file.name, md5sum, silent)

        # Since we didn't commit, there will be no HEAD.
        kirepo = M.kirepo(F.chk(Path(repo.working_dir)))
        with pytest.raises(GitHeadRefNotFoundError) as error:
            M.head_ki(kirepo)
        err_snippet = "ValueError raised while trying to get rev 'HEAD' from repo"
        assert err_snippet in str(error.exconly())


def test_push_note_handles_note_field_name_mismatches():
    """Do we return a nice warning when note fields are missing?"""
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)

    field = "data"
    fields = {"Front": field, "Backk": field}
    decknote = DeckNote("title", "0", "Default", "Basic", [], fields)
    new_nids: Iterator[int] = itertools.count(int(time.time_ns() / 1e6))
    warnings = push_note(col, decknote, int(time.time_ns()), {}, new_nids)
    assert len(warnings) == 1
    warning = warnings.pop()
    assert isinstance(warning, InconsistentFieldNamesWarning)
    assert "Backk" in str(warning)
    assert "Expected a field" in str(warning)


def test_parse_notetype_dict():
    nt = NT

    # This field ordinal doesn't exist.
    nt["sortf"] = 3
    with pytest.raises(MissingFieldOrdinalError) as error:
        parse_notetype_dict(nt)
    assert "3" in str(error.exconly())


def test_get_colnote_prints_nice_error_when_nid_doesnt_exist():
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    nid = 44444444444444444
    with pytest.raises(MissingNoteIdError) as error:
        get_colnote(col, nid)
    assert str(nid) in str(error.exconly())


@beartype
def test_get_colnote_propagates_errors_from_parse_notetype_dict(mocker: MockerFixture):
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())

    mocker.patch("ki.parse_notetype_dict", side_effect=UnnamedNotetypeError(NT))
    with pytest.raises(UnnamedNotetypeError) as error:
        get_colnote(col, note.id)
    assert "Failed to find 'name' field" in str(error.exconly())


@beartype
def test_get_colnote_propagates_errors_key_errors_from_sort_field(
    mocker: MockerFixture,
):
    mocker.patch("anki.notes.Note.__getitem__", side_effect=KeyError("bad_field_key"))
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = open_collection(ORIGINAL.col_file)
    note = col.get_note(set(col.find_notes("")).pop())
    with pytest.raises(NoteFieldKeyError) as error:
        get_colnote(col, note.id)
    assert "Expected field" in str(error.exconly())
    assert "'bad_field_key'" in str(error.exconly())


def test_nopath(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        file = Path("file")
        file.touch()
        with pytest.raises(FileExistsError):
            M.nopath(file)


def test_cp_ki(tmp_path: Path):
    """
    Do errors in `M.nopath()` call in `cp_ki()` get forwarded to
    the caller and printed nicely?

    In `cp_ki()`, we construct a `NoPath` for the `.ki`
    subdirectory, which doesn't exist yet at that point, because
    `cp_repo()` is just a git clone operation, and the `.ki`
    subdirectory is in the `.gitignore` file. It is possible but
    extraordinarily improbable that this path is created in between the
    `Repo.clone_from()` call and the `M.nopath()` call.

    In this test function, we simulate this possibility by the deleting the
    `.gitignore` file and committing the `.ki` subdirectory.
    """
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        clone(runner, ORIGINAL.col_file)
        os.chdir(ORIGINAL.repodir)
        os.remove(".gitignore")
        kirepo: KiRepo = M.kirepo(F.cwd())
        kirepo.repo.git.add(all=True)
        kirepo.repo.index.commit("Add ki directory.")
        head: KiRev = M.head_ki(kirepo)
        with pytest.raises(ExpectedNonexistentPathError) as error:
            cp_ki(head, suffix="suffix-md5")
        assert ".ki" in str(error.exconly())


def test_filter_note_path(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        directory = Path("directory")
        directory.mkdir()
        path = directory / "file"
        path.touch()
        patterns: List[str] = ["directory"]
        root: Dir = F.cwd()
        warning = get_note_warnings(
            path, root, ignore_files=set(), ignore_dirs=set(patterns)
        )
        assert isinstance(warning, Warning)
        assert isinstance(warning, UnPushedPathWarning)
        assert str(Path("directory") / "file") in str(warning)


def test_get_models_recursively(tmp_path: Path):
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        clone(runner, ORIGINAL.col_file)
        os.chdir(ORIGINAL.repodir)
        os.remove(MODELS_FILE)
        with open(Path(MODELS_FILE), "w", encoding="UTF-8") as models_f:
            json.dump(MODELS_DICT, models_f, ensure_ascii=False, indent=4)
        kirepo: KiRepo = M.kirepo(F.cwd())
        with pytest.raises(NotetypeKeyError) as error:
            get_models_recursively(kirepo, silent=True)
        assert "not found in notetype" in str(error.exconly())
        assert "flds" in str(error.exconly())
        assert "Basic" in str(error.exconly())


def test_get_models_recursively_prints_a_nice_error_when_models_dont_have_a_name(
    tmp_path: Path,
):
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        clone(runner, ORIGINAL.col_file)
        os.chdir(ORIGINAL.repodir)
        os.remove(MODELS_FILE)
        with open(Path(MODELS_FILE), "w", encoding="UTF-8") as models_f:
            json.dump(NAMELESS_MODELS_DICT, models_f, ensure_ascii=False, indent=4)
        kirepo: KiRepo = M.kirepo(F.cwd())
        with pytest.raises(UnnamedNotetypeError) as error:
            get_models_recursively(kirepo, silent=True)
        assert "Failed to find 'name' field" in str(error.exconly())
        assert "1645010146011" in str(error.exconly())


def test_cp_repo_handles_submodules(tmp_path: Path):
    ORIGINAL = get_test_collection("original")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        repo: git.Repo = get_repo_with_submodules(runner, ORIGINAL.col_file)

        os.chdir(repo.working_dir)

        # Edit a file within the submodule.
        file = Path(repo.working_dir) / SUBMODULE_DIRNAME / "Default" / "a.md"
        with open(file, "a", encoding="UTF-8") as note_f:
            note_f.write("\nz\n")

        subrepo = git.Repo(Path(repo.working_dir) / SUBMODULE_DIRNAME)
        subrepo.git.add(all=True)
        subrepo.index.commit(".")
        repo.git.add(all=True)
        repo.index.commit(".")

        kirepo: KiRepo = M.kirepo(F.cwd())
        head: KiRev = M.head_ki(kirepo)

        # Just want to check that this doesn't return an exception, so we
        # unwrap, but don't assert anything.
        kirepo = cp_ki(head, suffix="suffix-md5")


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not have `os.mkfifo()`."
)
def test_ftest_handles_strange_paths(tmp_path: Path):
    """Do we print a nice error when there is a non-file non-directory thing?"""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.mkfifo("pipe")
        pipe = F.chk(Path("pipe"))
        assert isinstance(pipe, PseudoFile)


def test_fparent_handles_fs_root():
    root: str = os.path.abspath(os.sep)
    parent = F.parent(F.chk(Path(root)))
    assert isinstance(parent, Dir)
    assert str(parent) == root


def test_fmkleaves_handles_collisions(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        root = F.chk(F.cwd())
        with pytest.raises(PathCreationCollisionError) as error:
            F.fmkleaves(root, files={"a": "a", "b": "a"})
        assert "'a'" in str(error.exconly())
        assert len(os.listdir(".")) == 0

        with pytest.raises(PathCreationCollisionError) as error:
            F.fmkleaves(root, files={"a": "a"}, dirs={"b": "a"})
        assert "'a'" in str(error.exconly())
        assert len(os.listdir(".")) == 0

        with pytest.raises(PathCreationCollisionError) as error:
            F.fmkleaves(root, dirs={"a": "a", "b": "a"})
        assert "'a'" in str(error.exconly())
        assert len(os.listdir(".")) == 0


def test_copy_media_files_returns_nice_errors():
    """Does `copy_media_files()` handle case where media directory doesn't exist?"""
    MEDIACOL: SampleCollection = get_test_collection("media")
    col: Collection = open_collection(MEDIACOL.col_file)
    runner = CliRunner()
    with runner.isolated_filesystem():

        # Remove the media directory.
        media_dir = F.chk(MEDIACOL.col_file.parent / MEDIACOL.media_directory_name)
        F.rmtree(media_dir)

        with pytest.raises(MissingMediaDirectoryError) as error:
            copy_media_files(col, F.mkdtemp(), silent=True)
        assert "media.media" in str(error.exconly())
        assert "bad Anki collection media directory" in str(error.exconly())


def test_copy_media_files_finds_notetype_media():
    """Does `copy_media_files()` get files like `collection.media/_vonNeumann.jpg`?"""
    MEDIACOL: SampleCollection = get_test_collection("media")
    col: Collection = open_collection(MEDIACOL.col_file)
    runner = CliRunner()
    with runner.isolated_filesystem():

        media = copy_media_files(col, F.mkdtemp(), silent=True)
        media_files: Set[File] = set()
        for media_set in media.values():
            media_files = media_files | media_set
        assert len(media_files) == 2
        media_files = sorted(list(media_files))
        von_neumann: File = media_files[1]
        assert "_vonNeumann" in str(von_neumann)


def test_shallow_walk_returns_extant_paths():
    """Shallow walk should only return paths that actually exist."""
    tmpdir = F.mkdtemp()
    (tmpdir / "file").touch()
    (tmpdir / "directory").mkdir()
    root, dirs, files = F.shallow_walk(tmpdir)
    assert os.path.isdir(root)
    for d in dirs:
        assert os.path.isdir(d)
    for file in files:
        assert os.path.isfile(file)


def test_get_test_collection_copies_media():
    """Do media files get copied into the temp directory?"""
    MEDIACOL: SampleCollection = get_test_collection("media")
    assert MEDIACOL.col_file.parent / (MEDIACOL.stem + ".media") / "1sec.mp3"


def test_cp_repo_preserves_git_symlink_file_modes(tmp_path: Path):
    """Especially on Windows, are copied symlinks still mode 120000?"""
    MEDIACOL: SampleCollection = get_test_collection("media")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):

        # Clone.
        clone(runner, MEDIACOL.col_file)

        # Check that filemode is initially 120000.
        repo = git.Repo(MEDIACOL.repodir)
        onesec_file = F.root(repo) / "Default" / MEDIA / "1sec.mp3"
        mode = M.filemode(onesec_file)
        assert mode == 120000

        # Check that `cp_repo()` keeps it as 120000.
        rev = M.head(repo)
        ephem = ki.cp_repo(rev, "filemode-test")
        onesec_file = F.root(ephem) / "Default" / MEDIA / "1sec.mp3"
        mode = M.filemode(onesec_file)
        assert mode == 120000


def test_write_deck_node_cards_does_not_fail_due_to_special_characters_in_paths_on_windows(
    tmp_path: Path,
):
    """If there are e.g. asterisks in a `guid`, do we still write the note file successfully?"""
    ORIGINAL: SampleCollection = get_test_collection("original")
    col = Collection(ORIGINAL.col_file)
    timestamp_ns: int = time.time_ns()
    new_nids: Iterator[int] = itertools.count(int(timestamp_ns / 1e6))

    nid = next(new_nids)
    mod = next(new_nids)
    mid = 1645010146011
    guid = r"QM6kTt.Nt*"
    decknote = DeckNote(
        title="title",
        guid=guid,
        deck="Default",
        model="Basic",
        tags=[],
        fields={"Front": "", "Back": "b"},
    )
    note: Note = add_db_note(
        col,
        nid,
        guid,
        mid,
        mod=int(timestamp_ns // 1e9),
        usn=-1,
        tags=decknote.tags,
        fields=list(decknote.fields.values()),
        sfld="",
        csum=0,
        flags=0,
        data="",
    )
    notetype: Notetype = parse_notetype_dict(note.note_type())

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        targetdir: Dir = F.mkdir(F.chk(Path("collection")))
        colnote = ColNote(
            n=note,
            new=True,
            deck="Default",
            title="None",
            markdown=False,
            notetype=notetype,
            sortf_text="",
        )
        payload: str = "payload"
        note_path: NoFile = get_note_path(colnote, targetdir)
        note_path: File = F.write(note_path, payload)


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows does not support colons in paths."
)
def test_diff2_handles_paths_containing_colons(tmp_path: Path):
    """Check that gitpython doesn't crash when a path contains a `:`."""
    # Create parser and transformer.
    grammar_path = Path(ki.__file__).resolve().parent / "grammar.lark"
    grammar = grammar_path.read_text(encoding="UTF-8")
    parser = Lark(grammar, start="note", parser="lalr")
    transformer = NoteTransformer()

    # Move to tmp directory.
    tgt = F.chk(tmp_path / "mwe")
    repodir = F.mkdir(tgt)
    repo = git.Repo.init(repodir, initial_branch=BRANCH_NAME)
    deck = F.mkdir(F.chk(repodir / "a:b"))
    file = F.chk(tgt / "a:b" / "file")
    file.write_text("a")
    repo.git.add(all=True)
    repo.index.commit("Initial commit.")
    file.write_text("b")
    repo.git.add(all=True)
    repo.index.commit("Edit file.")
    diff2(repo, parser, transformer)
