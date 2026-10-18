"""The experiment command: it must come from the user, never from an LLM.

The objectives LLM proposes a run command it found in the prompt, but the command is only accepted
if it appears word for word (ignoring differences in whitespace) in something the user wrote: the
question, the spec, a steering instruction, or a file they attached. Otherwise the run asks the user
for it. Shell syntax (pipes, &&) is allowed because the user typed it themselves.
"""

from __future__ import annotations

import re
import shlex
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from pruner.core.models import RunCommand

SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".mjs", ".ts", ".rb", ".pl", ".R", ".jl")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _lines(text: str) -> list[str]:
    """The text's lines with runs of spaces/tabs collapsed (a command never spans lines)."""
    return [" ".join(line.split()) for line in text.splitlines()]


_CLOSERS = set("`'\")")
_SENTENCE_END = set(".,;:!?")


def _whole_command_at(line: str, start: int, needle: str) -> bool:
    """Whether `needle` at line[start:] is a whole command, not a piece of a longer one: it must
    start at a word boundary and must not stop in the middle of a word or before more arguments
    (a next word that starts with "-", or holds "=", "/" or "." , or is a number)."""
    before = line[start - 1] if start > 0 else " "
    if not (before.isspace() or before in _CLOSERS or before in "(:"):
        return False
    rest = line[start + len(needle):]
    if not rest:
        return True
    first = rest[0]
    if first in _CLOSERS:
        return True
    if first in _SENTENCE_END:
        return len(rest) == 1 or rest[1].isspace()
    if not first.isspace():
        return False  # it stops inside a word: "rm -rf build" inside "rm -rf build/tmp"
    nxt = rest.split()[0] if rest.split() else ""
    looks_like_argument = (nxt.startswith("-") or any(c in nxt for c in "=/.")
                           or nxt.replace(".", "").isdigit() or nxt[:1] in "\"'$")
    return not looks_like_argument


def clean_candidate(candidate: str) -> str:
    """Strip what an LLM tends to wrap a command in: backticks, quotes, a leading `$ ` prompt."""
    text = _squash(candidate).strip().strip("`").strip()
    text = re.sub(r"^\$\s+", "", text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    return text


def find_source(command: str, sources: Mapping[str, str]) -> str | None:
    """The name of the first source that contains `command` word for word as a whole command
    (not a shortened piece of a longer one), or None."""
    needle = _squash(command)
    if not needle:
        return None
    for name, text in sources.items():
        for line in _lines(text):
            start = line.find(needle)
            while start != -1:
                if _whole_command_at(line, start, needle):
                    return name
                start = line.find(needle, start + 1)
    return None


def missing_scripts(command: str, root: Path) -> list[str]:
    """Script files the command names (e.g. `bench.py`) that do not exist under `root`."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    missing = []
    for t in tokens:
        is_script = t.endswith(SCRIPT_SUFFIXES) and not t.startswith("-") and "=" not in t
        if is_script and not Path(t).is_absolute() and not (root / t).exists():
            missing.append(t)
    return missing


def _placeholder_re(placeholder: str) -> re.Pattern[str]:
    """`placeholder` where it is not part of a longer word: the N in `experiment-N.json`, not the
    one in `NAME`."""
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(placeholder)}(?![A-Za-z0-9_])")


def has_placeholder(command: str, placeholder: str) -> bool:
    """Whether `placeholder` sits inside a path-like word of the command (never a whole word:
    in `-n N` it would be an argument the user meant literally)."""
    pattern = _placeholder_re(placeholder)
    return any(pattern.search(w) and w.strip("'\"") != placeholder for w in command.split())


def fill_placeholder(text: str, placeholder: str, number: int) -> str:
    """`text` with `placeholder` replaced by `number` inside path-like words only: a word that is
    the placeholder alone (`-n N`) is left as written, as has_placeholder() says."""
    pattern = _placeholder_re(placeholder)

    def fill(word: re.Match[str]) -> str:
        w = word.group()
        return w if w.strip("'\"") == placeholder else pattern.sub(str(number), w)

    return re.sub(r"\S+", fill, text)


def _word_path(word: str) -> str:
    """The path in a command word: `--output=runs/x.json` -> `runs/x.json`, quotes stripped."""
    if word.startswith("-") and "=" in word:
        word = word.split("=", 1)[1]
    return word.strip("'\"")


def numbered(command: str, placeholder: str, root: Path, taken: set[int],
             result_file: str | None = None) -> tuple[int, str]:
    """The smallest experiment number not in `taken` whose filled-in paths (the command's and
    the result file's) do not exist yet under `root` (an evaluator may refuse to overwrite an
    earlier result, and a stale result file would be read as this run's), and the command."""
    pattern = _placeholder_re(placeholder)
    words = [w for w in command.split() if pattern.search(w) and w.strip("'\"") != placeholder]
    if result_file and pattern.search(result_file):
        words.append(result_file)
    n = 1
    while True:
        if n not in taken and not any(
                (root / _word_path(fill_placeholder(w, placeholder, n))).exists()
                for w in words):
            return n, fill_placeholder(command, placeholder, n)
        n += 1


def runnable(command: str) -> str:
    """The command as it will run: a bare `python`/`python3` that is not on PATH becomes the
    interpreter running this server. The stored text is never changed."""
    first, _, rest = command.partition(" ")
    if first in ("python", "python3") and shutil.which(first) is None:
        return f"{shlex.quote(sys.executable)} {rest}".strip()
    return command


def verify_command(candidate: str | None, sources: Mapping[str, str], root: Path, *,
                   result_hint: str | None = None) -> tuple[RunCommand | None, str]:
    """(the command, "") if `candidate` is the user's own text and its scripts exist, else
    (None, why it was refused). `sources` maps a name ("question", "spec", a file path) to text;
    names that are files count as source "file", the rest as "prompt"."""
    if not candidate or not candidate.strip():
        return None, "no run command was found in the prompt or the attached files"
    text = clean_candidate(candidate)
    name = find_source(text, sources)
    if name is None:
        return None, (f"the proposed command {text!r} is not written word for word in the "
                      f"prompt or the attached files")
    missing = missing_scripts(text, root)
    if missing:
        return None, f"the command names {', '.join(missing)}, which does not exist in {root}"
    source = "file" if name not in ("question", "spec") and not name.startswith("instruction")\
        else "prompt"
    hint = result_hint.strip() if result_hint and result_hint.strip() else None
    return RunCommand(text=text, source=source, source_name=name, result_file=hint), ""
