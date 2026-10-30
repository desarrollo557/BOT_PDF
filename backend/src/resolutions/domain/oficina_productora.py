"""La oficina productora de una carpeta: lo que dice la cabecera de su FUID.

La plantilla FO-GD-008 trae escrito «OFICINA PRODUCTORA: FACULTAD DE
INGENIERIA», y las carpetas del REPOSITORIO UDC son de Enfermería, Odontología,
Secretaría General, Medicina y Derecho. El operador eligió el 2026-10-29 que
cada FUID lleve la de su carpeta.

Se saca, por este orden, de:

1. lo que escriba el operador al lanzar la carpeta;
2. el inventario del cliente que traiga la carpeta (``adapters/inventario_del_cliente.py``):
   «18-RESOLUCIONES INTERNAS Y ACTAS 3303» no nombra su facultad, pero su Excel
   dice «FACULTAD DE DERECHO Y CIENCIAS POLITICAS»;
3. el nombre de la carpeta: «17. FACULTAD DE MEDICINA 3261- 3268 P».

Si nada la dice, la cabecera queda como la trae la plantilla.
"""

from __future__ import annotations

import re
import unicodedata

#: Las facultades de la Universidad de Cartagena por la palabra que las nombra
#: en una carpeta. Va primero lo más largo: «CIENCIAS SOCIALES» antes que nada
#: que contenga «SOCIALES».
_FACULTADES = (
    ("CIENCIAS SOCIALES", "FACULTAD DE CIENCIAS SOCIALES Y EDUCACION"),
    ("CIENCIAS ECONOMICAS", "FACULTAD DE CIENCIAS ECONOMICAS"),
    ("CIENCIAS EXACTAS", "FACULTAD DE CIENCIAS EXACTAS Y NATURALES"),
    ("CIENCIAS FARMACEUTICAS", "FACULTAD DE CIENCIAS FARMACEUTICAS"),
    ("CIENCIAS HUMANAS", "FACULTAD DE CIENCIAS HUMANAS"),
    ("ENFERMERIA", "FACULTAD DE ENFERMERIA"),
    ("ODONTOLOGIA", "FACULTAD DE ODONTOLOGIA"),
    ("MEDICINA", "FACULTAD DE MEDICINA"),
    ("DERECHO", "FACULTAD DE DERECHO Y CIENCIAS POLITICAS"),
    ("INGENIERIA", "FACULTAD DE INGENIERIA"),
)
#: Las que no son una facultad. Se miran después, para que «SECRETARIA
#: ACADEMICA DE LA FACULTAD DE MEDICINA» sea de Medicina.
_OTRAS = (("SECRETARIA", "SECRETARIA GENERAL"),)


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sin_tildes.upper()).split())


def oficina_de_la_ruta(ruta: str) -> str | None:
    """La oficina que nombra la carpeta, de la más honda a la raíz; ``None`` si ninguna.

    «Z:\\…\\REPOSITORIO UDC\\14. ENFERMERIA 3277-3283 P» es «FACULTAD DE
    ENFERMERIA». Se mira cada carpeta por separado, de dentro afuera: la más
    cercana a los PDF es la que mejor dice de quién son.
    """
    partes = [p for p in re.split(r"[\\/]+", ruta or "") if p]
    for parte in reversed(partes):
        plana = f" {_plano(parte)} "
        for tabla in (_FACULTADES, _OTRAS):
            for palabra, oficina in tabla:
                if f" {palabra} " in plana:
                    return oficina
    return None


def oficina_escrita(valor: object) -> str | None:
    """Lo que escribió el operador, en mayúsculas y sin espacios de más; ``None`` si nada."""
    texto = " ".join(str(valor or "").split()).upper()
    return texto[:120] or None
