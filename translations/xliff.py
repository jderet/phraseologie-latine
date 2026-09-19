"""Reading an XLIFF 1.2 file sent back by translation software.

The file is read safely: a document type or an entity declaration is refused outright, the
size is limited, and nothing outside the file is ever fetched."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from django.utils.translation import gettext

from .services import normalize_sentence

MAX_BYTES = 2 * 1024 * 1024
MAX_UNITS = 5000
FORBIDDEN = ("<!doctype", "<!entity")

XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")

# XLIFF states read back as statuses of the working text.
STATUSES = {
    "translated": "translated",
    "signed-off": "reviewed",
    "final": "reviewed",
}


class XliffError(ValueError):
    pass


@dataclass(frozen=True)
class Unit:
    id: str
    target: str
    state: str


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_xliff(data):
    """The translation units of an XLIFF 1.2 file: [Unit] with their target and state."""
    if len(data) > MAX_BYTES:
        raise XliffError(gettext("Le fichier dépasse 2 Mo."))
    # Decoded first, strictly: another encoding (UTF-16) could hide a declaration from the check.
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise XliffError(gettext("Le fichier doit être encodé en UTF-8.")) from error
    lowered = text.lower()
    if any(mark in lowered for mark in FORBIDDEN):
        raise XliffError(gettext("Ce fichier XML déclare un type de document : il est refusé."))
    text = XML_DECLARATION.sub("", text, count=1)
    try:
        # Safe without defusedxml: the XML attacks (entity expansion, external entities) all
        # need a document type declaration, refused above, and nothing is ever fetched.
        root = ET.fromstring(text)  # noqa: S314
    except ET.ParseError as error:
        raise XliffError(gettext("Ce fichier n’est pas un XML lisible.")) from error
    if _local(root.tag) != "xliff":
        raise XliffError(gettext("Ce fichier n’est pas un fichier XLIFF."))
    units = []
    for element in root.iter():
        if _local(element.tag) != "trans-unit":
            continue
        target = next((child for child in element if _local(child.tag) == "target"), None)
        if target is None:
            continue
        units.append(
            Unit(
                id=element.get("id", ""),
                target=normalize_sentence("".join(target.itertext())),
                state=target.get("state", ""),
            )
        )
        if len(units) > MAX_UNITS:
            raise XliffError(gettext("Le fichier contient trop de phrases."))
    return units
