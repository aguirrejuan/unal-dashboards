"""Rendering the pages a model has to look at.

The five MEN resolutions are scans: `pdftotext` returns nothing, so the only way
to read them is to look. Rendering is deterministic — same file, same page, same
DPI, same bytes — which matters, because the image is the evidence the
transcription rests on and it must be reproducible alongside it.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DPI = 200


class PopplerAusente(RuntimeError):
    pass


@dataclass(frozen=True)
class Pagina:
    numero: int
    png: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.png).hexdigest()

    @property
    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png).decode()


def contar(pdf: Path) -> int:
    if shutil.which("pdfinfo") is None:
        raise PopplerAusente("pdfinfo no está en el PATH; instale poppler-utils")
    salida = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True,
                            check=True).stdout
    for linea in salida.splitlines():
        if linea.startswith("Pages:"):
            return int(linea.split()[1])
    raise ValueError(f"pdfinfo no informa el número de páginas de {pdf}")


def render(pdf: Path, numeros: list[int] | None = None, dpi: int = DPI) -> list[Pagina]:
    """Render the given pages, or every page, to PNG.

    Rendering the whole document costs tokens on pages that say nothing. Callers
    that already know which pages a citation points at should say so.
    """
    if shutil.which("pdftoppm") is None:
        raise PopplerAusente("pdftoppm no está en el PATH; instale poppler-utils")

    paginas = numeros if numeros else list(range(1, contar(pdf) + 1))
    salida = []
    # `-singlefile` and stdout do not combine: poppler writes nothing and exits
    # zero, which looks like an empty page rather than a wrong invocation.
    with tempfile.TemporaryDirectory() as tmp:
        for n in sorted(set(paginas)):
            raiz = Path(tmp) / f"p{n}"
            subprocess.run(
                ["pdftoppm", "-f", str(n), "-l", str(n), "-r", str(dpi), "-png",
                 "-singlefile", str(pdf), str(raiz)],
                capture_output=True, check=True,
            )
            png = raiz.with_suffix(".png")
            if not png.exists() or png.stat().st_size == 0:
                raise ValueError(f"{pdf.name}: la página {n} se renderizó vacía")
            salida.append(Pagina(numero=n, png=png.read_bytes()))
    return salida
