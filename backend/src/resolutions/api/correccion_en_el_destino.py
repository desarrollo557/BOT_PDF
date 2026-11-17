"""El nombre corregido en la Revisión, llevado al destino cuando la corrida ya no está en memoria (2026-11-17).

Con la corrida en memoria, ``FolderRunner.corregir_nombre`` (actas) y
``corregir_nombre_del_fuid`` (diplomas y matrículas) llevan la corrección a lo
entregado con lo que la corrida sabe. Tras un reinicio no queda la corrida, pero
sí lo que la Revisión guardó del trabajo al terminar (``donde_se_entrega``):
las rutas exactas de su espejo, de la carpeta de sus PDF, de sus dos
constancias y del FUID general. Con ellas se corrige lo mismo, en el disco:

- **el PDF entregado**, si su nombre lleva el de la persona; nunca pisa otro;
- **las constancias**: sus archivos y su fila, para que la corrida siguiente no
  lo dé por faltante y no lo vuelva a procesar y a pagar;
- **los FUID**: el de su carpeta o su libro y el general, cambiando sólo la
  celda de su asunto (``cambiar_el_asunto``).

Lo que no se puede, se dice. Un destino de red sin la corrida abierta no tiene
credenciales -- viven en memoria, no se guardan --: la corrección queda en el
trabajo y en el padrón, y el aviso lo cuenta.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from ..adapters import red_smb
from ..adapters.fuid_inventory import cambiar_el_asunto
from . import constancia as constancias
from .errores import explicar_fallo
from .retomar import SUFIJO_DEL_FUID

logger = logging.getLogger(__name__)


def corregir_en_el_destino(
    donde: Mapping[str, str] | None, pagina: int, viejo: Mapping[str, object], nuevo: Mapping[str, object]
) -> list[str]:
    """Lleva el nombre corregido a lo entregado, por las rutas guardadas. Devuelve lo que no se pudo hacer.

    ``viejo`` y ``nuevo`` traen «nombre», «archivo» (el nombre del PDF),
    «salida» (su ruta dentro del trabajo, la misma en el espejo de las actas),
    «asunto» (el de su fila) y «asunto_del_fuid» (como va escrito en el FUID);
    ``nuevo``, además, «revision_del_nombre» y, en una fila del FUID, «notas».
    """
    if not donde:
        return ["no se guardó dónde se entregó este documento: el destino no se corrigió"]
    if any(red_smb.por_smb(str(ruta)) for ruta in donde.values() if ruta):
        return [
            "el destino es una carpeta de red y su corrida ya no está abierta: sin sus credenciales no se "
            "puede escribir en él. La corrección quedó en el trabajo y en el padrón"
        ]
    espejo, carpeta = Path(donde.get("espejo") or ""), Path(donde.get("carpeta") or "")
    avisos: list[str] = []
    avisos += _el_pdf(espejo, carpeta, viejo, nuevo)
    for clave in ("constancia_de_actas", "constancia"):
        ruta = donde.get(clave)
        constancia = constancias.leer(Path(ruta)) if ruta else None
        if constancia is not None and _en_la_constancia(constancia, pagina, viejo, nuevo):
            try:
                constancias.escribir(Path(ruta), constancia)
            except OSError as error:
                avisos.append(f"no se pudo actualizar la constancia «{Path(ruta).name}»: {explicar_fallo(error)}")
    antes, despues = str(viejo.get("asunto_del_fuid") or ""), str(nuevo.get("asunto_del_fuid") or "")
    if antes and despues and antes != despues:
        rutas: list[Path] = []
        for lugar in (espejo, carpeta):
            try:
                rutas += sorted(lugar.glob(f"*{SUFIJO_DEL_FUID}")) if lugar.is_dir() else []
            except OSError:
                pass
        if donde.get("general"):
            rutas.append(Path(donde["general"]))
        for ruta in dict.fromkeys(rutas):
            try:
                if ruta.is_file():
                    cambiar_el_asunto(ruta, antes, despues)
            except Exception as error:  # noqa: BLE001 - lo demás ya se corrigió; se dice qué faltó
                avisos.append(f"no se pudo corregir el FUID «{ruta.name}»: {explicar_fallo(error)}")
    return avisos


def _el_pdf(espejo: Path, carpeta: Path, viejo: Mapping[str, object], nuevo: Mapping[str, object]) -> list[str]:
    """Renombra el PDF entregado: en el espejo de las actas por su salida, o en la carpeta de sus PDF."""
    antes_de, despues_de = str(viejo.get("archivo") or ""), str(nuevo.get("archivo") or "")
    if not antes_de or not despues_de or antes_de == despues_de:
        return []
    candidatos: list[tuple[Path, Path]] = []
    if viejo.get("salida") and nuevo.get("salida"):
        candidatos.append((espejo / str(viejo["salida"]), espejo / str(nuevo["salida"])))
    candidatos.append((carpeta / antes_de, carpeta / despues_de))
    for antes, despues in candidatos:
        try:
            if not antes.is_file():
                continue
            if despues.exists():
                return [f"en el destino ya hay un «{despues.name}»: no se renombró «{antes.name}»"]
            os.replace(antes, despues)
            return []
        except OSError as error:
            return [f"no se pudo renombrar «{antes.name}» en el destino: {explicar_fallo(error)}"]
    return [f"no se encontró «{antes_de}» en el destino: no se renombró"]


def _en_la_constancia(constancia, pagina: int, viejo: Mapping[str, object], nuevo: Mapping[str, object]) -> bool:
    """La constancia con el PDF y la fila de la persona corregidos; si cambió algo."""
    cambio = False
    antes_de, despues_de = str(viejo.get("archivo") or ""), str(nuevo.get("archivo") or "")
    for archivo in constancia.archivos:
        ruta = str(archivo.get("ruta") or "")
        if viejo.get("salida") and ruta == viejo["salida"] and nuevo.get("salida"):
            archivo["ruta"] = nuevo["salida"]
            cambio = True
        elif antes_de and despues_de != antes_de and (ruta == antes_de or ruta.endswith("/" + antes_de)):
            archivo["ruta"] = ruta[: len(ruta) - len(antes_de)] + despues_de
            cambio = True
    for fila in constancia.actas:
        datos = fila.get("fuid") if isinstance(fila.get("fuid"), dict) else None
        if datos is not None:
            # Una fila hecha del FUID (una matrícula): por su página y su asunto.
            if datos.get("pagina_inicial") == pagina and datos.get("asunto") == viejo.get("asunto"):
                datos["nombre"] = nuevo.get("nombre")
                datos["revision_del_nombre"] = nuevo.get("revision_del_nombre")
                if nuevo.get("asunto"):
                    datos["asunto"] = nuevo["asunto"]
                if antes_de and despues_de:
                    datos["notas"] = str(datos.get("notas") or "").replace(
                        f"Archivo: {antes_de}", f"Archivo: {despues_de}"
                    )
                cambio = True
        elif (
            fila.get("pagina_inicial") == pagina
            and fila.get("nombre") == viejo.get("nombre")
            and (fila.get("archivo_generado") or "") == antes_de
        ):
            fila["nombre"] = nuevo.get("nombre")
            fila["archivo_generado"] = despues_de or fila.get("archivo_generado")
            fila["revision_del_nombre"] = nuevo.get("revision_del_nombre")
            if nuevo.get("asunto"):
                fila["asunto"] = nuevo["asunto"]
            cambio = True
    return cambio
