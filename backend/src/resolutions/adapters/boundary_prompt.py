"""The one question asked about a box, and how an answer is read back.

Shared by every provider adapter so the prompt is written once. A boundary that
Claude and Gemini answer differently should differ because the models differ, not
because someone reworded the instructions in one of the two files.
"""

from __future__ import annotations

import json

INSTRUCTIONS = """Eres un archivista separando un expediente escaneado.

Te doy la huella de cada página de una caja. Cada huella trae:
  p   número de página
  t   el primer renglón o título de la página
  mb  hay membrete o título centrado arriba
  cf  ciudad y fecha de encabezado
  cs  número consecutivo del documento
  pg  la paginación que el papel declara ("3/5")
  fin la página termina con fórmula de despedida
  z   los últimos caracteres de la página

Te pido decidir, SOLO para las costuras que te listo, si la segunda página
empieza un documento NUEVO o CONTINUA el anterior.

Un documento nuevo suele abrir con membrete, ciudad y fecha, destinatario, o un
consecutivo distinto. Una continuación arrastra la frase cortada del final de la
página anterior, o sigue la paginación.

El texto viene de un OCR con errores: el nombre de la empresa aparece deformado
(afinia, arinia, ahnia, aPinia, aMnia). Ignora esa deformación.

No uses el número de reclamación ni el NIC para decidir: identifican el
expediente completo, no la hoja. Todas las páginas de la caja los comparten.

Responde SOLO un JSON:
{"cortes": [{"costura": "12|13", "nuevo": true, "razon": "<8 palabras>"}]}
Incluye una entrada por cada costura que te pedí, en el mismo orden."""


def build_question(pages: list[dict], seams: list[tuple[int, int]]) -> str:
    """The user half of the request: the box, then the seams in doubt."""
    huellas = "\n".join(json.dumps(page, ensure_ascii=False, separators=(",", ":")) for page in pages)
    costuras = ", ".join(f"{left}|{right}" for left, right in seams)
    return f"HUELLAS DE LA CAJA:\n{huellas}\n\nCOSTURAS A DECIDIR:\n{costuras}"


def parse_answer(text: str, seams: list[tuple[int, int]]) -> dict[tuple[int, int], bool]:
    """Read the verdicts back, keeping only seams that were actually asked.

    Anything unparseable, unexpected or missing is simply absent from the result,
    which leaves that seam undecided. A malformed reply must cost a review, never
    a wrong cut.
    """
    try:
        payload = json.loads(_strip_fence(text))
    except (json.JSONDecodeError, TypeError):
        return {}

    # Una lista, o nada. `{"cortes": null}` es JSON válido y un modelo lo
    # contesta; `payload.get("cortes", [])` devuelve ese null en vez del valor
    # por omisión, y recorrerlo levanta un TypeError que nadie atrapa: `judge`
    # llama a esto fuera de su propio `try`, así que se llevaba puesta la caja
    # entera, incluidos los cortes que la estructura ya había resuelto gratis.
    cortes = payload.get("cortes") if isinstance(payload, dict) else None
    if not isinstance(cortes, list):
        return {}

    asked = set(seams)
    answers: dict[tuple[int, int], bool] = {}
    for entry in cortes:
        if not isinstance(entry, dict):
            continue
        seam = _read_seam(entry.get("costura"))
        if seam is None or seam not in asked:
            continue
        starts = entry.get("nuevo")
        if isinstance(starts, bool):
            answers[seam] = starts
    return answers


def describe_failure(error: BaseException) -> str:
    """Qué salió mal con un proveedor, en una línea, para que se pueda arreglar.

    Los tres adaptadores degradan igual ante un fallo -- las costuras dudosas van
    a revisión y la caja no se cae -- y eso está bien. Lo que estaba mal era el
    aviso: decir sólo "no respondió" hace que un 429, un 401 y un plazo vencido se
    lean idénticos, y son tres problemas con tres arreglos distintos. Esperar,
    cambiar la llave, subir el plazo.

    Medido contra la API real de Mistral: la primera petición de una cuenta nueva
    volvió 429 "Rate limit exceeded" y el log no permitía distinguirlo de una
    llave mal puesta.
    """
    status = getattr(error, "code", None)
    if status is not None:
        reason = getattr(error, "reason", "") or ""
        return f"HTTP {status} {reason}".strip()
    return f"{type(error).__name__}: {error}"


def _strip_fence(text: str) -> str:
    """Models wrap JSON in a markdown fence often enough to handle it here."""
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]
        clean = clean.rsplit("```", 1)[0]
    return clean.strip()


def _read_seam(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str) or "|" not in value:
        return None
    left, _, right = value.partition("|")
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None


class NullBoundaryOracle:
    """The default when no provider is configured.

    Every doubt stays a doubt and goes to a human. A system with no model still
    splits everything structure can settle, which on a box with printed page
    counts is most of it.
    """

    def judge(
        self,
        pages: list[dict[str, object]],
        seams: list[tuple[int, int]],
    ) -> dict[tuple[int, int], bool]:
        return {}
