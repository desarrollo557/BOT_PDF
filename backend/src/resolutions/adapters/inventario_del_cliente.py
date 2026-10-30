"""Lo que dice de una carpeta el inventario con que el cliente la entregó.

Las carpetas del REPOSITORIO UDC traen a veces, sueltas en su raíz, el Excel del
cliente: «RESOLUCIONES INTERNAS Y ACTAS.xlsx», «ACTAS DE CONSEJO DE FACULTAD DE
ODONTOLOGIA NUEVO.xlsx», una fila por UPD con su «OFICINA PRODUCTORA». Es lo que
mejor dice la cabecera del FUID cuando el nombre de la carpeta no nombra su
facultad: «18-RESOLUCIONES INTERNAS Y ACTAS 3303» es de Derecho y sólo su Excel
lo dice (ver ``domain/oficina_productora.py``).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

#: El encabezado de la columna, tal cual en los Excel del cliente.
_CABECERA = "OFICINA PRODUCTORA"
#: Cuántas filas se miran buscando el encabezado, y cuántas columnas: los del
#: cliente declaran 16 384 columnas (A1:XFD82) y recorrerlas todas tarda.
_FILAS_DE_CABECERA = 20
_COLUMNAS = 40


def es_del_bot(nombre: str) -> bool:
    """Si el Excel lo dejó el propio bot: un general, un FUID, un inventario o un temporal."""
    return nombre.startswith(("00.", "~$")) or any(
        sufijo in nombre for sufijo in ("__FUID", "__inventario")
    )


def oficina_del_excel(ruta: Path) -> str | None:
    """La oficina productora que más se repite en un Excel del cliente, o ``None``."""
    from openpyxl import load_workbook

    try:
        libro = load_workbook(ruta, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - un Excel que no se abre no dice nada
        logger.debug("no se pudo abrir %s", ruta, exc_info=True)
        return None
    cuenta: Counter[str] = Counter()
    try:
        for hoja in libro.worksheets:
            columna: int | None = None
            for numero, fila in enumerate(hoja.iter_rows(max_col=_COLUMNAS, values_only=True), start=1):
                if columna is None:
                    if numero > _FILAS_DE_CABECERA:
                        break
                    columna = next(
                        (
                            indice
                            for indice, valor in enumerate(fila)
                            if isinstance(valor, str) and " ".join(valor.split()).upper() == _CABECERA
                        ),
                        None,
                    )
                    continue
                valor = fila[columna] if columna < len(fila) else None
                if isinstance(valor, str) and valor.strip():
                    cuenta[" ".join(valor.split()).upper()] += 1
    finally:
        libro.close()
    return cuenta.most_common(1)[0][0] if cuenta else None


def _plano(valor: object) -> str:
    return " ".join(str(valor or "").split()).upper()


def _por_upd(ruta: Path, rotulo: str, convertir) -> dict[str, object]:
    """La columna ``rotulo`` del Excel del cliente, por UPD; lo que ``convertir`` no acepte, fuera."""
    from openpyxl import load_workbook

    try:
        libro = load_workbook(ruta, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - un Excel que no se abre no dice nada
        logger.debug("no se pudo abrir %s", ruta, exc_info=True)
        return {}
    hallados: dict[str, object] = {}
    try:
        for hoja in libro.worksheets:
            columnas: tuple[int, int] | None = None
            for numero, fila in enumerate(hoja.iter_rows(max_col=_COLUMNAS, values_only=True), start=1):
                if columnas is None:
                    if numero > _FILAS_DE_CABECERA:
                        break
                    rotulos = [_plano(valor) for valor in fila]
                    if rotulo in rotulos and "UPD" in rotulos:
                        columnas = (rotulos.index(rotulo), rotulos.index("UPD"))
                    continue
                de_valor, de_upd = columnas
                upd = _plano(fila[de_upd] if de_upd < len(fila) else None).replace(" ", "")
                valor = convertir(fila[de_valor] if de_valor < len(fila) else None)
                if upd.startswith("UPD") and valor is not None:
                    hallados[upd] = valor
    finally:
        libro.close()
    return hallados


def _caja(valor: object) -> str | None:
    """«00C003362»; también la del cliente con un cero de más («000C003261»)."""
    hallada = re.search(r"(\d{2}C\d{6})$", _plano(valor).replace(" ", ""))
    return hallada.group(1) if hallada else None


def cajas_por_upd(ruta: Path) -> dict[str, str]:
    """La caja que el cliente anota de cada UPD: la que dice la fila cuando la ruta no la dice.

    «20.ACTAS DE GRADO 3362» trae sus dos PDF sueltos, sin subcarpeta de caja, y
    su FUID salía con la caja vacía; el Excel del cliente dice «00C003362».
    """
    return _por_upd(ruta, "CAJA", _caja)  # type: ignore[return-value]


def folios_por_upd(ruta: Path) -> dict[str, int]:
    """Los folios -- las hojas de papel -- que el cliente anotó de cada UPD, o nada si no los trae.

    Su Excel trae «FOLIOS» (las hojas) e «IMÁGENES» (las páginas escaneadas):
    «UPD3860000» tiene 101 folios y 199 imágenes, porque casi todas sus hojas se
    escanearon por las dos caras. El bot cuenta páginas y no sabe cuántas hojas
    hay; el operador eligió el 2026-10-30 que «No. de folios» lleve las hojas del
    cliente cuando se inventaría el PDF entero.
    """
    return _por_upd(ruta, "FOLIOS", _folios)  # type: ignore[return-value]


def _folios(valor: object) -> int | None:
    return int(valor) if isinstance(valor, int | float) and valor > 0 else None


def oficina_de_la_carpeta(carpeta: Path) -> str | None:
    """La oficina de los Excel del cliente sueltos en ``carpeta``, sin entrar en subcarpetas."""
    try:
        excels = sorted(
            (ruta for ruta in carpeta.glob("*.xlsx") if ruta.is_file() and not es_del_bot(ruta.name)),
            key=lambda ruta: ruta.name.lower(),
        )
    except OSError:
        return None
    for ruta in excels:
        if oficina := oficina_del_excel(ruta):
            return oficina
    return None
