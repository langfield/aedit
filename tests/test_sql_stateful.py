"""Tests for SQLite Lark grammar."""
from __future__ import annotations

import shutil
import random
import tempfile
import subprocess
from pathlib import Path

import prettyprinter as pp
from loguru import logger
from libfaketime import fake_time, reexec_if_needed

from beartype import beartype
from beartype.typing import Set, List, Callable, TypeVar

import hypothesis.strategies as st
from hypothesis import settings, Verbosity
from hypothesis.stateful import (
    rule,
    precondition,
    RuleBasedStateMachine,
)
from hypothesis.strategies import composite, SearchStrategy

# pylint: disable=unused-import
import anki.collection

# pylint: enable=unused-import
from anki.decks import DeckNameId
from anki.models import NotetypeDict, FieldDict, TemplateDict
from anki.collection import Collection, Note

import ki.functional as F
from ki.sqlite import SQLiteTransformer
from tests.test_parser import get_parser
from tests.test_ki import get_test_collection

T = TypeVar("T")

# pylint: disable=too-many-lines, missing-function-docstring

reexec_if_needed()

ROOT_DID = 0
DEFAULT_DID = 1

EMPTY = get_test_collection("empty")
Collection(EMPTY.col_file).close(downgrade=True)
logger.debug(F.md5(EMPTY.col_file))

pp.install_extras(exclude=["django", "ipython", "ipython_repr_pretty"])


@composite
@beartype
def fnames(draw: Callable[[SearchStrategy[T]], T]) -> str:
    """Field names."""
    fchars = st.characters(
        blacklist_characters=[":", "{", "}", '"'],
        blacklist_categories=["Cc", "Cs"],
    )

    # First chars for field names.
    chars = st.characters(
        blacklist_characters=["^", "/", "#", ":", "{", "}", '"'],
        blacklist_categories=["Zs", "Zl", "Zp", "Cc", "Cs"],
    )
    fnames = st.text(alphabet=fchars, min_size=0)
    c = draw(chars, "add nt: fname head")
    cs = draw(fnames, "add nt: fname tail")
    return c + cs


class AnkiCollection(RuleBasedStateMachine):
    """
    A state machine for testing `sqldiff` output parsing.

    Operation classes
    =================
    * notes
    * cards
    * decks
    * notetypes
    * tags
    * media

    Notes
    -----
    Add, edit, change notetype, move, delete

    Cards
    -----
    Move

    Decks
    -----
    Add, rename, move, delete

    Notetypes
    ---------
    Add, edit (see below), delete

    Notetype fields
    ---------------
    Add, delete, reposition, rename, set sort index

    Notetype templates
    ------------------
    Add, delete, reposition

    Tags
    ----
    Add, rename, reparent, delete

    Media
    -----
    Add, delete
    """

    # pylint: disable=no-self-use
    k = 0

    def __init__(self):
        super().__init__()
        logger.debug(f"Starting test {AnkiCollection.k}...")
        AnkiCollection.k += 1
        random.seed(0)
        self.freeze = True
        if self.freeze:
            self.freezer = fake_time("2022-05-01 00:00:00")
            self.freezer.start()
        self.tempd = Path(tempfile.mkdtemp())
        self.path = F.chk(self.tempd / "collection.anki2")
        self.path = F.copyfile(EMPTY.col_file, self.path)
        self.col = Collection(self.path)
        if not self.col.db:
            self.col.reopen()

        characters: SearchStrategy = st.characters(
            blacklist_characters=["\x1f"],
            blacklist_categories=["Cs"],
        )
        self.fields: SearchStrategy = st.text(alphabet=characters)

    @precondition(lambda self: len(list(self.col.decks.all_names_and_ids())) >= 1)
    @rule(data=st.data())
    def add_note(self, data: st.DataObject) -> None:
        """Add a new note with random fields."""
        nt: NotetypeDict = data.draw(st.sampled_from(self.col.models.all()), "nt")
        note: Note = self.col.new_note(nt)
        n: int = len(self.col.models.field_names(nt))
        fieldlists: SearchStrategy = st.lists(self.fields, min_size=n, max_size=n)
        note.fields = data.draw(fieldlists, "add note: fields")
        dids = list(map(lambda d: d.id, self.col.decks.all_names_and_ids()))
        did: int = data.draw(st.sampled_from(dids), "add note: did")
        self.col.add_note(note, did)

    @precondition(lambda self: self.col.note_count() >= 1)
    @rule(data=st.data())
    def edit_note(self, data: st.DataObject) -> None:
        """Edit a note's fields."""
        nids = list(self.col.find_notes(query=""))
        nid = data.draw(st.sampled_from(nids), "edit note: nid")
        note: Note = self.col.get_note(nid)
        n: int = len(self.col.models.field_names(note.note_type()))
        fieldlists: SearchStrategy = st.lists(self.fields, min_size=n, max_size=n)
        note.fields = data.draw(fieldlists, "edit note: fields")

    @precondition(lambda self: self.col.note_count() >= 1)
    @rule(data=st.data())
    def change_notetype(self, data: st.DataObject) -> None:
        """Change a note's notetype."""
        nids = list(self.col.find_notes(query=""))
        nid = data.draw(st.sampled_from(nids), "chg nt: nid")
        note: Note = self.col.get_note(nid)
        nt: NotetypeDict = data.draw(st.sampled_from(self.col.models.all()), "nt")
        old: NotetypeDict = note.note_type()
        items = map(lambda x: (x[0], None), self.col.models.field_map(nt).values())
        self.col.models.change(old, [nid], nt, fmap=dict(items), cmap=None)

    @precondition(lambda self: len(list(self.col.decks.all_names_and_ids())) >= 3)
    @precondition(lambda self: self.col.card_count() >= 1)
    def move_card(self, data: st.DataObject) -> None:
        """Move a card to a (possibly) different deck."""
        cids = list(self.col.find_notes(query=""))
        cid = data.draw(st.sampled_from(cids), "mv card: cid")
        old: int = self.col.decks.for_card_ids([cid])[0]
        dids: Set[int] = set(map(lambda d: d.id, self.col.decks.all_names_and_ids()))
        dids -= {DEFAULT_DID, old}
        new: int = data.draw(st.sampled_from(list(dids)), "mv card: did")
        self.col.set_deck([cid], deck_id=new)

    @precondition(lambda self: self.col.note_count() >= 1)
    @rule(data=st.data())
    def remove_note(self, data: st.DataObject) -> None:
        """Remove a note randomly selected note from the collection."""
        nids = list(self.col.find_notes(query=""))
        nid = data.draw(st.sampled_from(nids), "rm note: nid")
        self.col.remove_notes([nid])

    @rule(data=st.data())
    def add_deck(self, data: st.DataObject) -> None:
        """Add a new deck by creating a child node."""
        deck_name_ids: List[DeckNameId] = list(self.col.decks.all_names_and_ids())
        parent: DeckNameId = data.draw(st.sampled_from(deck_name_ids), "parent")
        names = set(map(lambda x: x[0], self.col.decks.children(parent.id)))
        names_st = st.text(min_size=1).filter(lambda s: s not in names)
        name = data.draw(names_st, "add deck: deckname")
        if self.freeze:
            self.freezer.tick()
        _ = self.col.decks.id(f"{parent.name}::{name}", create=True)

    @precondition(lambda self: len(list(self.col.decks.all_names_and_ids())) >= 2)
    @rule(data=st.data())
    def remove_deck(self, data: st.DataObject) -> None:
        """Remove a deck if one exists."""
        dids: Set[int] = set(map(lambda d: d.id, self.col.decks.all_names_and_ids()))
        dids -= {DEFAULT_DID}
        did: int = data.draw(st.sampled_from(list(dids)), "rm deck: did")
        _ = self.col.decks.remove([did])

    @precondition(lambda self: len(list(self.col.decks.all_names_and_ids())) >= 2)
    @rule(data=st.data())
    def rename_deck(self, data: st.DataObject) -> None:
        """Rename a deck."""
        dids: Set[int] = set(map(lambda d: d.id, self.col.decks.all_names_and_ids()))
        dids -= {DEFAULT_DID}
        did: int = data.draw(st.sampled_from(list(dids)), "rename deck: did")
        name: str = data.draw(st.text(), "rename deck: name")
        self.col.decks.rename(did, name)

    @precondition(lambda self: len(list(self.col.decks.all_names_and_ids())) >= 2)
    @rule(data=st.data())
    def reparent_deck(self, data: st.DataObject) -> None:
        """Move a deck."""
        dids: Set[int] = set(map(lambda d: d.id, self.col.decks.all_names_and_ids()))
        srcs = dids - {DEFAULT_DID}
        did: int = data.draw(st.sampled_from(list(srcs)), "mv deck: did")
        dsts = {ROOT_DID} | dids - {did}
        dst: int = data.draw(st.sampled_from(list(dsts)), "mv deck: dst")
        self.col.decks.reparent([did], dst)

    @rule(data=st.data())
    def add_notetype(self, data=st.DataObject) -> None:
        """Add a new notetype."""
        nchars = st.characters(blacklist_characters=['"'], blacklist_categories=["Cs"])
        name: str = data.draw(st.text(min_size=1, alphabet=nchars), "add nt: name")
        nt: NotetypeDict = self.col.models.new(name)

        fname = data.draw(fnames())
        field: FieldDict = self.col.models.new_field(fname)

        # TODO: Add more fields.
        nt["flds"] = [field]

        # TODO: Add more templates, and add afmts.
        frepl: str = "{{" + fname + "}}"
        qfmt: str = data.draw(st.text(), "add nt: qfmt")
        idxs = st.integers(min_value=0, max_value=len(qfmt))
        k: int = data.draw(idxs, "add nt: frepl idx")
        qfmt = qfmt[:k] + frepl + qfmt[k:]
        tname: str = data.draw(st.text(min_size=1), "add nt: tname")
        tmpl: TemplateDict = self.col.models.new_template(tname)
        tmpl["qfmt"] = qfmt
        nt["tmpls"] = [tmpl]

        self.col.models.add_dict(nt)
        nt = self.col.models.by_name(name)

    def teardown(self) -> None:
        """Cleanup the state of the system."""
        did = self.col.decks.id("dummy", create=True)
        self.col.decks.remove([did])
        self.col.close(save=True, downgrade=True)
        assert str(self.path) != str(EMPTY.col_file)
        assert F.md5(self.path) != F.md5(EMPTY.col_file)
        p = subprocess.run(
            ["sqldiff", str(EMPTY.col_file), str(self.path)],
            capture_output=True,
            check=True,
        )
        block = p.stdout.decode()
        # logger.debug(block)
        parser = get_parser(filename="sqlite.lark", start="diff")
        transformer = SQLiteTransformer()
        tree = parser.parse(block)
        stmts = transformer.transform(tree)
        logger.debug(pp.pformat(stmts))

        shutil.rmtree(self.tempd)
        if self.freeze:
            self.freezer.stop()


AnkiCollection.TestCase.settings = settings(
    max_examples=50,
    stateful_step_count=20,
    verbosity=Verbosity.normal,
    deadline=None,
)
TestAnkiCollection = AnkiCollection.TestCase
