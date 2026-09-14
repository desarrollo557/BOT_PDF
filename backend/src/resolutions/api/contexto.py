"""Lo que los routers necesitan del servicio, en un solo sitio.

El estado del servicio -- los ajustes, la cola de trabajos, el libro mayor, el
barrendero, la corrida de carpetas y los cabos del pool de procesos -- vivía
como globales de `main.py`, y cada endpoint los leía por su nombre. Al partir
`main.py` en routers eso no escala: un router no puede importar `main` sin
cerrar un círculo, y un global que se lee desde diez archivos no se puede
sustituir en una prueba.

Aquí queda como un objeto que la aplicación cuelga de `app.state` y que cada
endpoint recibe por `Depends`. Las pruebas cambian lo que necesitan sobre ese
objeto y todos los routers lo ven, porque todos leen del mismo sitio.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Request

from ..adapters.ledger import InventoryLedger
from ..application.usuarios import Usuarios
from .folders import FolderRunner
from .janitor import IdleJanitor
from .jobs import JobRegistry
from .settings import Settings


@dataclass
class Contexto:
    """El puesto de trabajo del servicio: con qué atiende cada petición."""

    settings: Settings
    registry: JobRegistry
    #: El libro mayor. Se tipa por el adaptador de archivo porque es el
    #: contrato que los dos almacenes cumplen; MySQL entra por la misma puerta.
    ledger: InventoryLedger
    inventory_backend: str
    janitor: IdleJanitor
    #: Quién está dado de alta y qué se le deja hacer. Va aquí y no como global
    #: por lo mismo que lo demás: cada router pregunta por el perfil de quien
    #: manda la petición, y una prueba tiene que poder dar de alta a dos
    #: personas sin escribir en el archivo de la máquina.
    usuarios: Usuarios
    #: Con qué se procesa un documento en el proceso worker. Es un campo y no
    #: un import para que una prueba pueda poner un doble sin levantar MuPDF.
    procesar: Callable[[dict], dict]
    #: Lo que sólo existe con la aplicación arrancada.
    folders: FolderRunner | None = None
    pool: Any = None
    manager: Any = None
    progress_queue: Any = None
    #: Órdenes de pausa, reanudación y cancelación por trabajo, compartidas
    #: con los workers a través del Manager.
    controls: Any = None
    #: Qué documentos están levantando su FUID, y con qué error terminó cada
    #: uno: `None` mientras trabaja, la frase cuando falló.
    fuid_jobs: dict[str, str | None] = field(default_factory=dict)


def contexto_de(request: Request) -> Contexto:
    return request.app.state.contexto


#: El tipo que pone cada endpoint en su firma para recibir el contexto.
Ctx = Annotated[Contexto, Depends(contexto_de)]
