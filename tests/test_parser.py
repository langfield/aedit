"""Tests for markdown note Lark grammar."""
from pathlib import Path

import pytest

from loguru import logger
from beartype import beartype

from lark import Lark
from lark.exceptions import (
    UnexpectedToken,
    UnexpectedInput,
    UnexpectedCharacters,
    VisitError,
)

import ki
from ki import NoteTransformer

# pylint: disable=too-many-lines, missing-function-docstring

BAD_ASCII_CONTROLS = ["\0", "\a", "\b", "\v", "\f"]


@beartype
def get_parser(filename: str, start: str) -> Lark:
    """Return a parser."""
    # Read grammar.
    grammar_path = Path(ki.__file__).resolve().parent / filename
    grammar = grammar_path.read_text(encoding="UTF-8")

    # Instantiate parser.
    parser = Lark(grammar, start=start, parser="lalr")

    return parser


@beartype
def debug_lark_error(err: UnexpectedInput) -> None:
    """Print an exception."""
    logger.error(f"accepts: {err.accepts}")
    logger.error(f"column: {err.column}")
    logger.error(f"expected: {err.expected}")
    logger.error(f"line: {err.line}")
    logger.error(f"pos_in_stream: {err.pos_in_stream}")
    logger.error(f"token: {err.token}")
    logger.error(f"token_history: {err.token_history}")
    logger.error(f"\n{err}")


TOO_MANY_HASHES_TITLE = r"""## Note
```
guid: 123412341234
notetype: Basic
```

### Tags
```
```

## Front
r

## Back
s
"""


def test_too_many_hashes_for_title():
    """Do too many hashes in title cause parse error?"""
    note = TOO_MANY_HASHES_TITLE
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 1
    assert err.column == 2
    assert err.token == "# Note\n"
    assert len(err.token_history) == 1
    prev = err.token_history.pop()
    assert str(prev) == "#"


TOO_FEW_HASHES_TITLE = r""" Note
```
guid: 123412341234
notetype: Basic
```

### Tags
```
```

## Front
r

## Back
s
"""


def test_too_few_hashes_for_title():
    """Do too few hashes in title cause parse error?"""
    note = TOO_FEW_HASHES_TITLE
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 1
    assert err.column == 2
    assert err.token == "Note"
    assert len(err.token_history) == 1
    assert err.token_history.pop() is None


TOO_FEW_HASHES_FIELDNAME = r"""# Note
```
guid: 123412341234
notetype: Basic
```

### Tags
```
```

# Front
r

## Back
s
"""


def test_too_few_hashes_for_fieldname():
    """Do too many hashes in fieldname cause parse error?"""
    note = TOO_FEW_HASHES_FIELDNAME
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 11
    assert err.column == 1
    assert err.token == "# Front\n"
    assert err.expected == set(["FIELDSENTINEL"])
    assert len(err.token_history) == 1
    prev = err.token_history.pop()
    assert str(prev) == "\n"


TOO_MANY_HASHES_FIELDNAME = r"""# Note
```
guid: 123412341234
notetype: Basic
```

### Tags
```
```

### Front
r

## Back
s
"""


def test_too_many_hashes_for_fieldname():
    """Do too many hashes in fieldname cause parse error?"""
    note = TOO_MANY_HASHES_FIELDNAME
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 11
    assert err.column == 3
    assert err.token == "# Front\n"
    assert err.expected == set(["ANKINAME"])
    assert len(err.token_history) == 1
    prev = err.token_history.pop()
    assert str(prev) == "##"


MISSING_FIELDNAME = r"""# Note
```
guid: 123412341234
notetype: Basic
```

### Tags
```
```

##    
r

## Back
s
"""


def test_missing_fieldname():
    """Does a missing fieldname raise a parse error?"""
    note = MISSING_FIELDNAME
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 11
    assert err.column == 7
    assert err.token == "\n"
    assert err.expected == set(["ANKINAME"])
    assert len(err.token_history) == 1
    prev = err.token_history.pop()
    assert str(prev) == "##"


MISSING_TITLE = r"""#
```
guid: 123412341234
notetype: Basic
```

### Tags
```
```

## a
r

## b
s
"""


def test_missing_title():
    """Does a missing title raise a parse error?"""
    note = MISSING_TITLE
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 1
    assert err.column == 2
    assert err.token == "\n"
    assert err.expected == set(["TITLENAME"])
    assert len(err.token_history) == 1
    prev = err.token_history.pop()
    assert str(prev) == "#"


MISSING_MODEL = r"""# a
```
guid: 123412341234
notetype:
```

### Tags
```
```

## a
r

## b
s
"""


def test_missing_model():
    """Does a missing model raise a parse error?"""
    note = MISSING_MODEL
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 4
    assert err.column == 1
    assert err.token == "notetype"
    assert err.expected == set(["NOTETYPE"])
    assert len(err.token_history) == 1
    prev = err.token_history.pop()
    assert str(prev) == "guid: 123412341234\n"


WHITESPACE_MODEL = r"""# a
```
guid: 123412341234
notetype:          	
```

### Tags
```
```

## a
r

## b
s
"""


def test_whitespace_model():
    """Does a whitespace model raise a parse error?"""
    note = WHITESPACE_MODEL
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 4
    assert err.column == 1
    assert err.token == "notetype"
    assert err.expected == set(["NOTETYPE"])
    assert len(err.token_history) == 1
    prev = err.token_history.pop()
    assert str(prev) == "guid: 123412341234\n"


FIELDNAME_VALIDATION = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## @@@@@
r

## b
s
"""

BAD_FIELDNAME_CHARS = [":", "{", "}", '"'] + BAD_ASCII_CONTROLS


def test_bad_field_single_char_name_validation():
    """Do invalid fieldname characters raise an error?"""
    template = FIELDNAME_VALIDATION
    parser = get_parser(filename="grammar.lark", start="note")
    for char in BAD_FIELDNAME_CHARS:
        note = template.replace("@@@@@", char)
        with pytest.raises(UnexpectedInput) as exc:
            parser.parse(note)
        err = exc.value

        assert err.line == 11
        assert err.column == 4
        assert len(err.token_history) == 1
        prev = err.token_history.pop()
        assert str(prev) == "##"
        if isinstance(err, UnexpectedToken):
            assert err.token in char + "\n"
            assert err.expected == set(["ANKINAME"])
        if isinstance(err, UnexpectedCharacters):
            assert err.char == char


def test_bad_field_multi_char_name_validation():
    """Do invalid fieldname characters raise an error?"""
    template = FIELDNAME_VALIDATION
    parser = get_parser(filename="grammar.lark", start="note")
    for char in BAD_FIELDNAME_CHARS:
        fieldname = "aa" + char + "aa"
        note = template.replace("@@@@@", fieldname)
        with pytest.raises(UnexpectedInput) as exc:
            parser.parse(note)
        err = exc.value
        assert err.line == 11
        assert err.column == 6
        assert len(err.token_history) == 1
        prev = err.token_history.pop()
        assert str(prev) == fieldname[:2]
        if isinstance(err, UnexpectedToken):
            assert err.token in fieldname[2:] + "\n"
            assert err.expected == set(["NEWLINE"])
        if isinstance(err, UnexpectedCharacters):
            assert err.char == char


BAD_START_FIELDNAME_CHARS = ["#", "/", "^"] + BAD_FIELDNAME_CHARS


def test_fieldname_start_validation():
    """Do bad start characters in fieldnames raise an error?"""
    template = FIELDNAME_VALIDATION
    parser = get_parser(filename="grammar.lark", start="note")
    for char in BAD_START_FIELDNAME_CHARS:
        fieldname = char + "a"
        note = template.replace("@@@@@", fieldname)
        with pytest.raises(UnexpectedInput) as exc:
            parser.parse(note)
        err = exc.value
        assert err.line == 11
        assert err.column == 4
        assert len(err.token_history) == 1
        prev = err.token_history.pop()
        assert str(prev) == "##"
        if isinstance(err, UnexpectedToken):
            assert err.token in fieldname + "\n"
            assert err.expected == set(["ANKINAME"])
        if isinstance(err, UnexpectedCharacters):
            assert err.char == char


FIELD_CONTENT_VALIDATION = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
@@@@@

## b
s
"""


def test_field_content_validation():
    """Do ascii control characters in fields raise an error?"""
    template = FIELD_CONTENT_VALIDATION
    parser = get_parser(filename="grammar.lark", start="note")
    for char in BAD_ASCII_CONTROLS:
        field = char + "a"
        note = template.replace("@@@@@", field)
        with pytest.raises(UnexpectedCharacters) as exc:
            parser.parse(note)
        err = exc.value
        assert err.line == 12
        assert err.column == 1
        assert err.char == char
        assert len(err.token_history) == 1
        prev = err.token_history.pop()
        assert str(prev) == "\n"


NO_POST_HEADER_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```## a
r

## b
s
"""

ONE_POST_HEADER_NEWLINE = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```
## a
r

## b
s
"""

TWO_POST_HEADER_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
r

## b
s
"""

THREE_POST_HEADER_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```


## a
r

## b
s
"""


def test_header_needs_two_trailing_newlines():
    """
    Does parser raise an error if there are not exactly 2 newlines after note
    header?
    """
    parser = get_parser(filename="grammar.lark", start="note")
    note = NO_POST_HEADER_NEWLINES
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 9
    assert err.column == 1
    assert err.token == "```## a"
    assert err.expected == {"TAGNAME", "TRIPLEBACKTICKS"}

    note = ONE_POST_HEADER_NEWLINE
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 10
    assert err.column == 1
    assert err.token == "##"
    assert err.expected == {"NEWLINE"}

    note = TWO_POST_HEADER_NEWLINES

    note = THREE_POST_HEADER_NEWLINES
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(note)
    err = exc.value
    assert err.line == 11
    assert err.column == 1
    assert err.token == "\n"
    assert err.expected == {"FIELDSENTINEL"}


ONE_POST_NON_TERMINATING_FIELD_NEWLINE = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
r
## b
s
"""

TWO_POST_NON_TERMINATING_FIELD_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
r

## b
s
"""


def test_non_terminating_field_needs_at_least_two_trailing_newlines():
    """
    Does transformer raise an error if there are not at least 2 newlines after
    the content of a nonterminating field?
    """
    parser = get_parser(filename="grammar.lark", start="note")
    transformer = NoteTransformer()

    tree = parser.parse(ONE_POST_NON_TERMINATING_FIELD_NEWLINE)
    with pytest.raises(VisitError) as exc:
        transformer.transform(tree)
    err = exc.value.orig_exc
    assert "Nonterminating fields" in str(err)

    tree = parser.parse(TWO_POST_NON_TERMINATING_FIELD_NEWLINES)
    transformer.transform(tree)


EMPTY_FIELD_ZERO_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
## b
s
"""


def test_empty_field_is_still_checked_for_newline_count():
    parser = get_parser(filename="grammar.lark", start="note")
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(EMPTY_FIELD_ZERO_NEWLINES)
    err = exc.value
    assert err.line == 12
    assert err.column == 1
    assert err.token == "##"
    assert err.expected == {"EMPTYFIELD", "FIELDLINE"}


EMPTY_FIELD_ONE_NEWLINE = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a

## b
s
"""


def test_empty_field_with_only_one_newline_raises_error():
    parser = get_parser(filename="grammar.lark", start="note")
    transformer = NoteTransformer()

    tree = parser.parse(EMPTY_FIELD_ONE_NEWLINE)
    with pytest.raises(VisitError) as exc:
        transformer.transform(tree)
    err = exc.value.orig_exc
    assert "Nonterminating fields" in str(err)


EMPTY_FIELD_TWO_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a


## b
s
"""

EMPTY_FIELD_THREE_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a



## b
s
"""


def test_empty_field_with_at_least_two_newlines_parse():
    """
    Do empty fields with at least two newlines get parsed and transformed OK?
    """
    parser = get_parser(filename="grammar.lark", start="note")
    transformer = NoteTransformer()

    tree = parser.parse(EMPTY_FIELD_TWO_NEWLINES)
    transformer.transform(tree)

    tree = parser.parse(EMPTY_FIELD_THREE_NEWLINES)
    transformer.transform(tree)


def test_empty_field_preserves_extra_newlines():
    """
    Are newlines beyond the 2 needed for padding preserved in otherwise-empty
    fields?
    """
    parser = get_parser(filename="grammar.lark", start="note")
    transformer = NoteTransformer()
    tree = parser.parse(EMPTY_FIELD_THREE_NEWLINES)
    flatnote = transformer.transform(tree)
    assert flatnote.fields["a"] == "\n"


LAST_FIELD_SINGLE_TRAILING_NEWLINE = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
r

## b
s
"""


def test_last_field_only_needs_one_trailing_empty_line():
    parser = get_parser(filename="grammar.lark", start="note")
    transformer = NoteTransformer()
    tree = parser.parse(LAST_FIELD_SINGLE_TRAILING_NEWLINE)
    transformer.transform(tree)


LAST_FIELD_NO_TRAILING_NEWLINE = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
r

## b
s"""


def test_last_field_needs_one_trailing_newline():
    parser = get_parser(filename="grammar.lark", start="note")
    NoteTransformer()
    with pytest.raises(UnexpectedToken) as exc:
        parser.parse(LAST_FIELD_NO_TRAILING_NEWLINE)
    err = exc.value
    assert err.line == 15
    assert err.column == 1
    assert err.token == "s"
    assert err.expected == {"EMPTYFIELD", "FIELDLINE"}


LAST_FIELD_FIVE_TRAILING_NEWLINES = r"""# a
```
guid: 123412341234
notetype: a
```

### Tags
```
```

## a
r

## b
s




"""


def test_last_field_newlines_are_preserved():
    parser = get_parser(filename="grammar.lark", start="note")
    transformer = NoteTransformer()
    tree = parser.parse(LAST_FIELD_FIVE_TRAILING_NEWLINES)
    flatnote = transformer.transform(tree)
    assert flatnote.fields["b"] == "s\n\n\n\n"


TAG_VALIDATION = r"""# a
```
guid: 123412341234
notetype: 0a
```

### Tags
```
@@@@@
```

## a
r

## b
s
"""

BAD_TAG_CHARS = ['"', "\u3000", " "] + BAD_ASCII_CONTROLS


def test_tag_validation():
    """Do ascii control characters and quotes in tag names raise an error?"""
    template = TAG_VALIDATION
    parser = get_parser(filename="grammar.lark", start="note")
    for char in BAD_TAG_CHARS:
        tags = f"subtle\n{char}\nheimdall"
        note = template.replace("@@@@@", tags)
        with pytest.raises(UnexpectedInput) as exc:
            parser.parse(note)
        err = exc.value
        assert err.line == 10
        assert err.column in (1, 2)
        assert len(err.token_history) == 1
        prev = err.token_history.pop()
        assert str(prev) == "\n"
        if isinstance(err, UnexpectedToken):
            remainder = "\n".join(tags.split("\n")[1:]) + "\n"
            assert err.token in remainder
            assert err.expected == set(["TAGNAME", "TRIPLEBACKTICKS"])
        if isinstance(err, UnexpectedCharacters):
            assert err.char == char


def test_parser_handles_special_characters_in_guid():
    """In particular, does it allow colons?"""
    parser = get_parser(filename="grammar.lark", start="note")
    good = Path("tests/data/notes/special_characters_in_guid.md").read_text(
        encoding="UTF-8"
    )
    try:
        parser.parse(good)
    except UnexpectedToken as err:
        raise err


def test_parser_goods():
    """Try all good note examples."""
    parser = get_parser(filename="grammar.lark", start="note")
    goods = Path("tests/data/notes/good.md").read_text(encoding="UTF-8").split("---\n")
    for good in goods:
        try:
            parser.parse(good)
        except UnexpectedToken as err:
            raise err


def test_transformer():
    """Try out transformer."""
    parser = get_parser(filename="grammar.lark", start="note")
    note = Path("tests/data/notes/noteLARK.md").read_text(encoding="UTF-8")
    tree = parser.parse(note)
    transformer = NoteTransformer()
    transformer.transform(tree)


def test_transformer_goods():
    """Try all good note examples."""
    parser = get_parser(filename="grammar.lark", start="note")
    transformer = NoteTransformer()
    goods = Path("tests/data/notes/good.md").read_text(encoding="UTF-8").split("---\n")
    for good in goods:
        try:
            tree = parser.parse(good)
            transformer.transform(tree)
        except (UnexpectedToken, VisitError) as err:
            raise err


def main():
    """Parse all notes in main collection."""
    parse_collection()


def parse_collection():
    """Parse all notes in a collection."""
    transformer = NoteTransformer()
    grammar_path = Path(ki.__file__).resolve().parent / "grammar.lark"
    grammar = grammar_path.read_text(encoding="UTF-8")
    parser = Lark(grammar, start="file", parser="lalr", transformer=transformer)
    for path in set((Path.home() / "collection").iterdir()):
        if path.suffix == ".md":
            note = path.read_text(encoding="UTF-8")
            parser.parse(note)


if __name__ == "__main__":
    main()
