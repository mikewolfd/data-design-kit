"""Read build-selected source and installer-recorded distribution identities.

The build record describes the source selected by the external release builder.
PEP 610 ``direct_url.json`` describes the archive recorded by the installer. These
records identify that installation; they do not reverify installed file contents
or establish source-to-wheel reproducibility. Source checkouts have neither an
owned installed distribution nor an archive identity and retain their code version.
"""

from importlib import metadata
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import __version__

_PACKAGE = "data-design-kit"
_BUILD_RECORD = "ddk/_build.json"


def _json_object(value):
    try:
        record = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch(f"[a-f0-9]{{{length}}}", value) is not None


def _build_record(installed):
    try:
        return _json_object(Path(installed.locate_file(_BUILD_RECORD)).read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}


def distribution_identity():
    """Return available local records without hashing wheels or trusting env vars.

    Metadata for another installation, editable installs, and a shadowing source
    checkout cannot identify the code loaded here. Missing or malformed records
    leave the corresponding identity absent rather than inventing one.
    """
    identity = {"version": __version__}
    try:
        installed = metadata.distribution(_PACKAGE)
        files = {str(path) for path in installed.files or ()}
        if ("ddk/distribution.py" not in files
                or Path(installed.locate_file("ddk/distribution.py")).resolve() != Path(__file__).resolve()):
            return identity
        identity["version"] = installed.version
        if _BUILD_RECORD in files:
            record = _build_record(installed)
            if (type(record.get("formatVersion")) is int and record["formatVersion"] == 1
                    and record.get("distributionVersion") == installed.version
                    and _hex(record.get("sourceCommit"), 40) and _hex(record.get("sourceTreeSha256"), 64)):
                identity["commit"] = record["sourceCommit"]
        direct = _json_object(installed.read_text("direct_url.json"))
        archive = direct.get("archive_info", {})
        url = direct.get("url")
        if isinstance(archive, dict) and isinstance(url, str) and urlsplit(url).path.endswith(".whl"):
            hashes = archive.get("hashes")
            digest = hashes.get("sha256") if isinstance(hashes, dict) else None
            legacy = archive.get("hash")
            if "hashes" not in archive and isinstance(legacy, str) and legacy.startswith("sha256="):
                digest = legacy.removeprefix("sha256=")
            if (isinstance(legacy, str) and legacy.startswith("sha256=")
                    and digest != legacy.removeprefix("sha256=")):
                digest = None
            if _hex(digest, 64):
                identity["distributionSha256"] = digest
    except (metadata.PackageNotFoundError, OSError, UnicodeError, ValueError):
        # Identity metadata is optional for source development and index installs.
        # Retain independently available fields if one metadata file is unreadable.
        pass
    return identity
