"""Convierte los expedientes académicos en filas del FUID.

El equivalente de `diploma_fuid` para el otro documento que produce Registro y
Control Académico. Las reglas son las mismas del instructivo del formato -- lo
que no aplica se escribe N/A, nunca se deja en blanco -- y lo que cambia es qué
sabe decir cada papel:

  * De un libro de diplomas se lee una fecha de graduación, que es un día
    concreto, y por eso la fecha inicial y la final son la misma.
  * De un expediente académico se leen **años**, uno por curso -- "PRIMER AÑO
    1.950" hasta "SEXTO AÑO 1.955" -- y ésas sí son fechas extremas de verdad:
    la primera es el año en que el expediente abre y la última, aquel en que
    cierra.

Un expediente ocupa varias hojas y una sola fila. El número de folios es el
recuento de sus hojas, no una constante: es lo que el instructivo pide y es lo
único que permite cuadrar la planilla con el empaste.

El año se escribe con sus cuatro cifras y nada más. El encabezado del formato
pide DD-MM-AAAA, pero el cartón no dice el día ni el mes: ponerle un 01-01
delante sería inventarse una fecha exacta a partir de una que no lo es, y eso es
justamente lo que el instructivo prohíbe cuando manda escribir N/A donde no hay
dato.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.matricula import StudentRecord
from .fuid import NO_APLICA, FuidRow, Ubicacion


def asunto(registro: StudentRecord) -> str:
    """Lo que identifica el expediente: el estudiante, y su carrera si consta."""
    nombre = (registro.nombre or "").strip()
    carrera = (registro.carrera or "").strip()
    if nombre and carrera:
        return f"{nombre} - {carrera}"
    return nombre or carrera or NO_APLICA


def notas(registro: StudentRecord) -> str:
    """Lo relevante que no cabe en ninguna columna del formato.

    El instructivo reserva esta columna justamente para eso. Aquí va el período
    de la última matrícula y el curso que el estudiante llevaba, que son lo que
    permite situar el expediente sin abrirlo, y las páginas que ocupa dentro del
    PDF de origen, que es como se vuelve a él.
    """
    partes: list[str] = []
    if registro.periodo:
        partes.append(f"Período {registro.periodo}")
    if registro.anio_en_curso:
        partes.append(f"Año {registro.anio_en_curso}")
    if registro.page_numbers:
        primera, ultima = registro.page_numbers[0], registro.page_numbers[-1]
        donde = (
            f"Página {primera} del documento de origen"
            if primera == ultima
            else f"Páginas {primera} a {ultima} del documento de origen"
        )
        partes.append(donde)
    return ". ".join(partes)


def filas_de_expedientes(
    registros: Sequence[StudentRecord],
    *,
    nombre_del_archivo: str,
    ubicacion: Ubicacion | None = None,
    desde: int = 1,
) -> list[FuidRow]:
    """Una fila por estudiante, en el orden en que están en el PDF."""
    donde = ubicacion or Ubicacion()
    upd = donde.carpeta_de(nombre_del_archivo)

    return [
        FuidRow(
            orden=desde + desplazamiento,
            codigo_trd=donde.codigo_trd,
            asunto=asunto(registro),
            # El número de identificación de la unidad documental. En estos
            # expedientes es el código del estudiante -- "51-8710099" -- que es
            # con lo que la Universidad los cita.
            consecutivo_inicial=registro.codigo or NO_APLICA,
            consecutivo_final=NO_APLICA,
            fecha_inicial=registro.fecha_inicial or NO_APLICA,
            fecha_final=registro.fecha_final or NO_APLICA,
            caja=donde.caja,
            carpeta=upd,
            # Estos expedientes no van empastados en tomos: son hojas sueltas en
            # carpeta, así que la columna que el instructivo reserva a los
            # empastes queda declarada como no aplicable.
            tomo=NO_APLICA,
            otro=donde.otro,
            folios=registro.folios,
            folios_siar=registro.folios,
            soporte=NO_APLICA,
            frecuencia=NO_APLICA,
            notas=notas(registro),
        )
        for desplazamiento, registro in enumerate(registros)
    ]
