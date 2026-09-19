"""Units made of other units: the schema of one holds the whole schema of another.

*De re publica bene mereri* (``mereor -sp-> de; de -reg-> res; res -amod-> publicus;
mereor -advmod-> bene``) holds *res publica* (``res -amod-> publicus``). Components are found
from the schemas of the units the user may see: nothing is written to record them.
"""

from dataclasses import dataclass
from functools import reduce
from operator import or_

from django.core.exceptions import ValidationError
from django.db.models import Q

from .schema import SLOT, base, node_cases, parse_schema, required_edges, schema_lemmas
from .spotting import visible_units

MAX_COMPONENTS = 6
MAX_CONTAINERS = 20


@dataclass
class Component:
    """A unit and its schema, part of a larger schema or holding a smaller one."""

    unit: object
    edges: list

    @property
    def lemmas(self):
        return schema_lemmas(self.edges)


def _same_relation(first, second):
    """A relation without subtype covers its subtypes: reg covers reg:abl."""
    return first == second or first == base(second) or second == base(first)


def contains(outer, inner):
    """Whether every relation of the schema ``inner`` is one of ``outer``, which has more.

    Only required relations count: an optional one neither makes a unit part of another nor
    keeps it out. A word given a case in ``inner`` has it in ``outer``.
    """
    outer, inner = required_edges(outer), required_edges(inner)
    if not inner or len(inner) >= len(outer):
        return False
    outer_cases = node_cases(outer)
    if any(outer_cases.get(node) != case for node, case in node_cases(inner).items()):
        return False
    relations = {(edge.head, edge.dependent): edge.relations for edge in outer}
    return all(
        any(
            _same_relation(first, second)
            for first in edge.relations
            for second in relations.get((edge.head, edge.dependent), ())
        )
        for edge in inner
    )


def _with_schemas(units):
    for unit in units:
        try:
            yield unit, parse_schema(unit.schema)
        except ValidationError:
            continue


def components(user, edges):
    """The units the user may see whose schema is part of ``edges``, the largest first."""
    lemmas = [lemma for lemma in schema_lemmas(edges) if lemma != SLOT]
    if len(edges) < 2:
        return []
    # A schema is stored from its root, which is one of these lemmas, maybe with its case.
    starts = reduce(
        or_,
        (
            Q(schema__startswith=f"{lemma} -") | Q(schema__startswith=f"{lemma}:")
            for lemma in lemmas
        ),
    )
    units = visible_units(user).filter(starts).order_by("reference_form", "pk")
    found = [
        Component(unit, inner) for unit, inner in _with_schemas(units) if contains(edges, inner)
    ]
    found.sort(key=lambda component: -len(component.edges))
    return found[:MAX_COMPONENTS]


def containers(user, unit):
    """The units the user may see whose schema holds the whole schema of ``unit``."""
    try:
        inner = parse_schema(unit.schema)
    except ValidationError:
        return []
    if not inner:
        return []
    units = visible_units(user).exclude(pk=unit.pk)
    for lemma in schema_lemmas(inner):
        units = units.filter(schema__contains=lemma)
    found = _with_schemas(units.order_by("reference_form", "pk"))
    return [Component(other, outer) for other, outer in found if contains(outer, inner)][
        :MAX_CONTAINERS
    ]


def schema_parts(edges, found):
    """The relations of a schema as shown, and the components not shown in it.

    The relations of a component are grouped under its name, in the place of the first one;
    components sharing a relation with a larger one already grouped are only listed.
    """
    grouped, others, owner = [], [], {}
    for component in found:
        keys = {(edge.head, edge.dependent) for edge in component.edges}
        if keys & owner.keys():
            others.append(component)
            continue
        owner.update(dict.fromkeys(keys, len(grouped)))
        grouped.append(component)
    parts, shown = [], set()
    for edge in edges:
        group = owner.get((edge.head, edge.dependent))
        if group is None:
            parts.append({"edge": edge})
        elif group not in shown:
            shown.add(group)
            members = [e for e in edges if owner.get((e.head, e.dependent)) == group]
            parts.append({"component": grouped[group], "edges": members})
    return parts, others
