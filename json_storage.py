"""Share atomic writes for the coin and media catalogs."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomically(path: Path, data: dict[str, Any]) -> None:
    """Keep the temporary file on the destination filesystem for atomic replacement."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=4)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
