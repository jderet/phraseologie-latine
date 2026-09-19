"""The network of copies of a version, like the forks of a repository: the copies made from it,
their own copies, and how far each has drifted from the version it was copied from."""

from dataclasses import dataclass, field

from moderation.registry import can_view

from .models import TranslationVersion
from .sources import SourceHistory
from .steps import carried, shown_sentences

MAX_DEPTH = 6
MAX_NODES = 100


@dataclass
class Node:
    version: TranslationVersion
    depth: int
    differing: int | None
    children: list = field(default_factory=list)


def _texts(user, version, history):
    step, sentences = shown_sentences(user, version)
    if step is not None:
        sentences = history.project(carried(sentences), step.source_state)
    return {key: sentence.text for key, sentence in sentences.items() if sentence.text}


def copy_network(user, root):
    """Ancestors of a version (the versions it comes from, oldest first) and the tree of its
    copies the user may see, flattened in reading order: (ancestors, [Node])."""
    ancestors = []
    current = root
    while current.copied_from_id and len(ancestors) < MAX_DEPTH:
        current = current.copied_from.version
        if not can_view(user, current):
            break
        ancestors.append(current)
    history = SourceHistory(root.project.source_text)
    cache = {}

    def texts(version):
        if version.pk not in cache:
            cache[version.pk] = _texts(user, version, history)
        return cache[version.pk]

    nodes = []

    def walk(version, depth):
        copies = (
            TranslationVersion.objects.filter(copied_from__version=version)
            .select_related("author", "project")
            .order_by("created_at")
        )
        for copy in copies:
            if len(nodes) >= MAX_NODES or not can_view(user, copy):
                continue
            mine, theirs = texts(copy), texts(version)
            differing = sum(
                1 for key in set(mine) | set(theirs) if mine.get(key, "") != theirs.get(key, "")
            )
            nodes.append(Node(copy, depth, differing))
            if depth < MAX_DEPTH:
                walk(copy, depth + 1)

    walk(root, 1)
    return ancestors[::-1], nodes
