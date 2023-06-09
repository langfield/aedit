#!/usr/bin/env python3
"""Type-safe, non Anki-specific functions."""

# pylint: disable=import-self, too-many-return-statements
# pylint: disable=no-value-for-parameter

import os
import re
import sys
import stat
import errno
import shutil
import hashlib
import tempfile
import functools
import subprocess
import unicodedata
from types import TracebackType
from pathlib import Path
from itertools import chain
from functools import reduce, partial, update_wrapper, wraps

import git
from tqdm import tqdm
from colorama import Fore, Style

from beartype import beartype
from beartype.typing import (
    List,
    Union,
    Generator,
    Tuple,
    Callable,
    Any,
    Type,
    FrozenSet,
    Iterable,
    TypeVar,
)

import ki.functional as F
from ki.types import (
    File,
    Dir,
    EmptyDir,
    NoPath,
    NoFile,
    Link,
    WindowsLink,
    Singleton,
    PseudoFile,
    KiRev,
    Rev,
)

_has_type_hint_support = sys.version_info[:2] >= (3, 5)

T = TypeVar("T")

UTF8 = "UTF-8"
GIT = ".git"
GITMODULES_FILE = ".gitmodules"
PIPE = subprocess.PIPE
STDOUT = subprocess.STDOUT
BRANCH_NAME = "main"

# Emoji regex character classes.
EMOJIS = "\U0001F600-\U0001F64F"
PICTOGRAPHS = "\U0001F300-\U0001F5FF"
TRANSPORTS = "\U0001F680-\U0001F6FF"
FLAGS = "\U0001F1E0-\U0001F1FF"

# Regex to filter out bad stuff from filenames.
SLUG_REGEX = re.compile(r"[^\w\s\-" + EMOJIS + PICTOGRAPHS + TRANSPORTS + FLAGS + "]")


@beartype
def curried(func: Callable[[Any, ...], T]) -> Callable[[Any, ...], T]:
    """A decorator that makes the function curried

    Usage example:

    >>> @curried
    ... def sum5(a, b, c, d, e):
    ...     return a + b + c + d + e
    ...
    >>> sum5(1)(2)(3)(4)(5)
    15
    >>> sum5(1, 2, 3)(4, 5)
    15
    """

    def _args_len(func):
        # pylint: disable=import-outside-toplevel
        good = True
        try:
            from inspect import signature

            signature(func)
        except TypeError:
            good = False

        if good and _has_type_hint_support:
            from inspect import signature

            args = signature(func).parameters
        else:
            from inspect import getfullargspec

            args = getfullargspec(func).args

        return len(args)

    @wraps(func)
    def _curried(*args, **kwargs):
        f = func
        count = 0
        while isinstance(f, partial):
            if f.args:
                count += len(f.args)
            f = f.func

        if count == _args_len(f) - len(args):
            return func(*args, **kwargs)

        para_func = partial(func, *args, **kwargs)
        if hasattr(f, "__name__"):
            update_wrapper(para_func, f)
        return curried(para_func)

    def _curried_lambda(*args, **kwargs):
        return partial(func, *args, **kwargs)

    if func.__name__ == "<lambda>":
        return _curried_lambda

    return _curried


def rmtree2(path: str) -> None:
    """On windows, rmtree fails for readonly dirs."""

    def handle_remove_readonly(
        func: Callable[..., Any],
        path: str,
        exc: Tuple[Type[OSError], OSError, TracebackType],
    ) -> None:
        excvalue = exc[1]
        if func in (os.rmdir, os.remove, os.unlink) and excvalue.errno == errno.EACCES:
            for p in (path, os.path.dirname(path)):
                os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
            func(path)
        else:
            raise excvalue

    shutil.rmtree(path, ignore_errors=False, onerror=handle_remove_readonly)


@beartype
def rmtree(target: Dir) -> NoFile:
    """Equivalent to `shutil.rmtree()`, but annihilates read-only files on Windows."""
    rmtree2(str(target))
    return NoFile(target)


@beartype
def copytree(source: Dir, target: NoFile) -> Dir:
    """Call shutil.copytree()."""
    shutil.copytree(source, target, symlinks=True)
    return Dir(target.resolve())


@beartype
def movetree(source: Dir, target: NoFile) -> Dir:
    """Call shutil.move()."""
    shutil.move(source, target)
    return Dir(target.resolve())


@beartype
def cwd() -> Dir:
    """Call Path.cwd()."""
    return Dir(Path.cwd().resolve())


@beartype
def is_root(path: Union[File, Dir]) -> bool:
    """Check if 'path' is a root directory (e.g., '/' on Unix or 'C:\' on Windows)."""
    # Links and `~`s are resolved before checking.
    path = path.resolve()
    return len(path.parents) == 0


@functools.cache
@beartype
def shallow_walk(
    directory: Dir,
) -> Tuple[Dir, List[Dir], List[File]]:
    """Walk only the top-level directory with `os.walk()`."""
    # pylint: disable=redefined-outer-name
    root, dirs, files = next(os.walk(directory))
    root = Dir(root)
    dirs = [Dir(root / d) for d in dirs]
    # TODO: Treat symlinks.
    files = [File(root / f) for f in files]
    return root, dirs, files


@beartype
def walk(
    directory: Dir,
) -> FrozenSet[Union[File, PseudoFile, Link, NoFile]]:
    """Get all file-like leaves in a directory, recursively."""
    # pylint: disable=redefined-outer-name
    leaves = frozenset()
    for root, _, files in os.walk(directory):
        root = Dir(root)
        leaves |= frozenset({F.chk(root / f) for f in files})
    return leaves


# TODO: Remove `resolve: bool` parameter, and test symlinks before resolving.
@beartype
def chk(
    path: Path,
    resolve: bool = True,
) -> Union[File, Dir, EmptyDir, PseudoFile, NoPath, NoFile, Link]:
    """Test whether `path` is a file, a directory, or something else."""
    if resolve:
        path = path.resolve()
    if path.is_file():
        return File(path)
    if path.is_dir():
        if is_empty(Dir(path)):
            return EmptyDir(path)
        return Dir(path)
    if path.exists():
        return PseudoFile(path)
    if os.path.islink(path):
        return Link(path)
    if path.parent.is_dir():
        return NoFile(path)
    return NoPath(path)


@beartype
def touch(directory: Dir, name: str) -> File:
    """Touch a file."""
    path = directory / singleton(name)
    path.touch()
    return File(path.resolve())


@beartype
def write(path: Union[File, NoFile], text: str) -> File:
    """Write text to a file."""
    with open(path, "w+", encoding="UTF-8") as f:
        f.write(text)
    return File(path)


@beartype
def writeb(path: Union[File, NoFile], bs: bytes) -> File:
    """Write text to a file."""
    with open(path, "wb") as f:
        f.write(bs)
    return File(path)


@beartype
def symlink(path: NoFile, target: Path) -> Union[Link, WindowsLink]:
    """Link `path` to `target`."""
    if sys.platform == "win32":
        with open(path, "w", encoding="UTF-8") as f:
            f.write(str(target.as_posix()))
            return WindowsLink(path)

    # Treat POSIX systems.
    os.symlink(target, path)
    return Link(path)


@beartype
def mksubdir(directory: EmptyDir, suffix: Path) -> EmptyDir:
    """
    Make a subdirectory of an empty directory (with parents).

    Returns
    -------
    EmptyDir
        The created subdirectory.
    """
    subdir = directory / suffix
    subdir.mkdir(parents=True)
    directory.__class__ = Dir
    return EmptyDir(subdir.resolve())


@beartype
def force_mkdir(path: Path) -> Dir:
    """Make a directory (with parents, ok if it already exists)."""
    path.mkdir(parents=True, exist_ok=True)
    return Dir(path.resolve())


@beartype
def chdir(directory: Dir) -> Dir:
    """Changes working directory and returns old cwd."""
    old: Dir = F.cwd()
    os.chdir(directory)
    return old


@beartype
def parent(path: Union[File, Dir]) -> Dir:
    """
    Get the parent of a path that exists.  If the path points to the filesystem
    root, we return itself.
    """
    if is_root(path):
        return Dir(path.resolve())
    return Dir(path.parent)


@beartype
def mkdtemp() -> EmptyDir:
    """Make a temporary directory (in /tmp)."""
    return EmptyDir(tempfile.mkdtemp()).resolve()


@beartype
def copyfile(source: File, target: Union[File, NoFile]) -> File:
    """Safely copy a file to a valid location."""
    shutil.copyfile(source, target)
    return File(target.resolve())


@beartype
def rglob(d: Dir, pattern: str) -> List[File]:
    """Call d.rglob() and returns only files."""
    files = filter(lambda p: isinstance(p, File), map(F.chk, d.rglob(pattern)))
    return list(files)


@beartype
def is_empty(directory: Dir) -> bool:
    """Check if directory is empty, quickly."""
    return not next(os.scandir(directory), None)


@beartype
def root(repo: git.Repo) -> Dir:
    """Get working directory of a repo."""
    return Dir(repo.working_dir).resolve()


@beartype
def gitd(repo: git.Repo) -> Dir:
    """Get git directory of a repo."""
    return Dir(repo.git_dir).resolve()


@beartype
def singleton(name: str) -> Singleton:
    """Removes all forward slashes and returns a Singleton pathlib.Path."""
    return Singleton(name.replace("/", ""))


@beartype
def md5(path: File) -> str:
    """Compute md5sum of file at `path`."""
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


@beartype
def rev_exists(repo: git.Repo, rev: str) -> bool:
    """Check if git commit reference exists in repository."""
    try:
        repo.git.rev_parse("--verify", rev)
    except git.GitCommandError:
        return False
    return True


@beartype
def get_batches(lst: List[File], n: int) -> Generator[File, None, None]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


@beartype
def slugify(value: str) -> str:
    """
    Taken from [1]. Convert spaces or repeated dashes to single dashes. Remove
    characters that aren't alphanumerics, underscores, or hyphens. Convert to
    lowercase. Also strip leading and trailing whitespace, dashes, and
    underscores.

    [1] https://github.com/django/django/blob/master/django/utils/text.py
    """
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(SLUG_REGEX, "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


@beartype
def ki_rev_to_rev(ki_rev: KiRev) -> Rev:
    """Convert a ki repository commit rev to a git repository commit rev."""
    return Rev(ki_rev.kirepo.repo, ki_rev.sha)


@beartype
def mkdir(path: NoPath) -> EmptyDir:
    """Make a directory (with parents)."""
    path.mkdir(parents=True)
    return EmptyDir(path)


@beartype
def unlink(file: Union[File, Link, WindowsLink]) -> NoFile:
    """Safely unlink a file."""
    os.unlink(file)
    return NoFile(file)


@curried
@beartype
def rmsm(repo: git.Repo, sm: git.Submodule) -> git.Commit:
    """Remove a git submodule."""
    # Remove the submodule root and delete its .git directory.
    sm_root = Path(sm.module().working_tree_dir)
    repo.git.rm(sm_root, cached=True)
    dotgit = F.chk(sm_root / GIT)
    if isinstance(dotgit, Dir):
        F.rmtree(dotgit)
    else:
        dotgit.unlink(missing_ok=True)

    # Directory `sm_root` should still exist after `git.rm()` call.
    repo.git.add(sm_root)
    return repo.index.commit(f"Add submodule `{sm.name}` as ordinary directory.")


@beartype
def unsubmodule(repo: git.Repo) -> git.Repo:
    """
    Un-submodule all the git submodules (converts them to ordinary subdirs and
    destroys commit history). Commit the changes to the main repository.
    """
    _: List[git.Commit] = list(map(F.rmsm(repo), repo.submodules))
    gitmodules_file: Path = F.root(repo) / GITMODULES_FILE
    if gitmodules_file.exists():
        repo.git.rm(gitmodules_file)
        _ = repo.index.commit("Remove `.gitmodules` file.")
    return repo


@beartype
def init(targetdir: Dir) -> Tuple[git.Repo, str]:
    """Run `git init`, returning the repo and initial branch name."""
    branch = BRANCH_NAME
    try:
        repo = git.Repo.init(targetdir, initial_branch=BRANCH_NAME)
    except git.GitCommandError:
        branch = "master"
        repo = git.Repo.init(targetdir)
    return repo, branch


@beartype
def isfile(p: Path) -> bool:
    """Check if `p` is a File."""
    return isinstance(p, File)


@beartype
def cat(xs: Iterable[Iterable[T]]) -> Iterable[T]:
    """Concatenate some iterables."""
    return chain.from_iterable(xs)


@beartype
def commitall(repo: git.Repo, msg: str) -> git.Commit:
    """Commit all contents of a git repository."""
    repo.git.add(all=True)
    return repo.index.commit(msg)


@curried
@beartype
def git_rm(repo: git.Repo, path: str) -> str:
    """Remove a path in a repo."""
    repo.git.rm(path)
    return path


@beartype
def yellow(s: str) -> None:
    """Print a message to the console in yellow."""
    print(f"{Fore.YELLOW}{s}{Style.RESET_ALL}")


@beartype
def red(s: str) -> None:
    """Print a message to the console in red."""
    print(f"{Fore.RED}{s}{Style.RESET_ALL}")


@beartype
def progressbar(xs: Iterable[T], s: str) -> Iterable[T]:
    """Print a progress bar for an iterable."""
    ys: Iterable[T] = tqdm(xs, ncols=80)
    ys.set_description(s)
    return ys


@beartype
def starfilter(
    f: Callable[[Any, ...], bool], xs: Iterable[Tuple[Any, ...]]
) -> Iterable[Tuple[Any, ...]]:
    """Filter an iterable, automatically unpacking tuple arguments."""
    return filter(lambda x: f(*x), xs)


@beartype
def part(p: Callable[[T], bool], xs: Iterable[T]) -> Tuple[Iterable[T], Iterable[T]]:
    """Partition a list on a boolean predicate (Trues, Falses)."""
    return reduce(lambda s, x: s[not p(x)].append(x) or s, xs, ([], []))
