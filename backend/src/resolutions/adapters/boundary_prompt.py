"""The one question asked about a box, and how an answer is read back.

Shared by every provider adapter so the prompt is written once. A boundary that
Claude and Gemini answer differently should differ because the models differ, not
because someone reworded the instructions in one of the two files.
"""

from __future__ import annotations

import json

INSTRUCTIONS = """Eres un archivista separando un expediente escaneado de correspondencia.

Te doy la huella de cada página de una caja. Cada huella trae:
  p   número de página
  t   el título de la página, o su primer renglón si no tiene título
  mb  hay membrete o título centrado arriba
  cf  ciudad y fecha de encabezado
  cs  número consecutivo del documento
  pg  la paginación que el papel declara ("3/5")
  fin la página termina con fórmula de despedida
  z   los últimos caracteres de la página

Trabaja en dos pasos.

PASO 1 - de qué trata cada página.
Con `t` y `z`, decide el tema de cada hoja. En una caja de correspondencia de un
servicio público el repertorio es corto:
  factura o liquidación de consumo
  acta de visita, de revisión o de irregularidad
  constancia
  reclamación del usuario
  recurso de reposición o de apelación
  notificación o respuesta de la empresa
  aviso de suspensión o de cobro
  anexo, soporte o comprobante
Si una hoja no encaja en ninguno, su tema es "otro". No inventes un tipo que no
esté en esa lista.

PASO 2 - las costuras.
SOLO para las costuras que te listo, decide si la segunda página empieza un
documento NUEVO o CONTINUA el anterior. Pesa la evidencia en este orden:

  1. La paginación declarada (`pg`). Si el papel se cuenta a sí mismo, manda el
     papel: "1/5" abre y "5/5" cierra, diga lo que diga el resto.
  2. El consecutivo (`cs`). Cambia con cada documento.
  3. La continuidad del tema, que es el paso 1. Dos hojas del mismo tema y del
     mismo asunto suelen ser un documento; un cambio de tema es un borde. Un
     acta seguida de una factura son dos cosas aunque compartan el membrete.
  4. La frase cortada: si `z` de la izquierda queda a media oración y `t` de la
     derecha la retoma en minúscula, es la misma hoja partida por el escáner.
  5. La apertura: ciudad y fecha, o destinatario, en la derecha, después de una
     despedida (`fin`) en la izquierda.

Cuidado con tres trampas, las tres medidas sobre cajas reales:

  - El membrete se repite en CASI TODAS las hojas de este papel: en un expediente
    de 125 páginas apareció en 111. Que la derecha traiga `mb` no significa que
    abra un documento. Como señal de borde, `mb` vale poco.

  - No uses el número de reclamación ni el NIC para decidir: identifican el
    expediente completo, no la hoja. Todas las páginas de la caja los comparten,
    y leerlos como continuidad suelda la caja entera en un solo documento.

  - El texto viene de un OCR con errores: el nombre de la empresa aparece
    deformado (afinia, arinia, ahnia, aPinia, aMnia). Ignora esa deformación, y
    no leas un título ilegible como un tema nuevo.

Y lo más importante de todo. Si la evidencia no alcanza, dilo. Una costura sin
decidir la revisa una persona y se corrige en segundos; una costura adivinada se
convierte en un corte equivocado que nadie va a notar nunca. Preferir "baja" mil
veces es mejor que inventar una vez.

Responde SOLO un JSON con esta forma:
{"cortes": [
  {"costura": "12|13", "nuevo": true,
   "razon": "cambia de acta de visita a factura",
   "confianza": "alta"}
]}

`confianza` es "alta", "media" o "baja". Lo que marques "baja" no se usa para
cortar: va a revisión humana, así que úsala sin culpa cada vez que dudes.
`razon` en pocas palabras, diciendo en qué evidencia te apoyaste.

Puedes omitir una costura que no puedas juzgar: omitirla es lo mismo que
marcarla "baja". Nunca completes con una respuesta inventada para que la lista
quede llena."""


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
        if not isinstance(starts, bool):
            continue
        # Un veredicto que el propio modelo marcó dudoso no corta nada: va a
        # revisión, igual que una costura que no contestó. El prompt le dice que
        # use "baja" sin culpa justamente para que este camino se recorra.
        if _is_low_confidence(entry.get("confianza")):
            continue
        answers[seam] = starts
    return answers


#: Lo que el modelo puede escribir para decir "no me hagas caso en esta". Se
#: compara en minúsculas y sin espacios, porque un modelo escribe "Baja" tanto
#: como "baja".
LOW_CONFIDENCE = "baja"


def _is_low_confidence(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == LOW_CONFIDENCE


#: Cuánto de una respuesta inservible se copia al log. Suficiente para ver si es
#: prosa, otro esquema de JSON o una respuesta truncada; poco para no inundar.
UNUSABLE_SNIPPET = 220


def describe_unusable(
    text: str,
    seams: list[tuple[int, int]],
    answers: dict[tuple[int, int], bool],
) -> str | None:
    """Por qué una respuesta que llegó bien no produjo ningún veredicto.

    Devuelve `None` cuando no hay nada que reportar: alguna costura se contestó,
    o no se preguntó ninguna. La cobertura parcial no se avisa porque ya se ve en
    `model_decided` del informe.

    Existe porque un 200 inservible y un proveedor sin llave se veían idénticos
    desde afuera -- los dos dejan `model_decided` en 0 -- y distinguirlos obligaba
    a contar líneas de log contra cajas procesadas. Medido contra la API real de
    Gemini, que contestó 200 y cuya respuesta se descartó entera sin decir nada.
    """
    if not seams or answers:
        return None
    limpio = (text or "").strip()
    if not limpio:
        return f"0 de {len(seams)} costuras; la respuesta llegó vacía"
    recorte = limpio[:UNUSABLE_SNIPPET]
    if len(limpio) > UNUSABLE_SNIPPET:
        recorte += "..."
    return f"0 de {len(seams)} costuras; contestó: {recorte!r}"


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
