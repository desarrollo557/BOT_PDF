"""Las altas del archivo, en un archivo de texto junto al libro mayor.

Un JSON por línea, igual que el libro mayor y por el mismo motivo: se lee con
cualquier cosa, sobrevive a que el programa se caiga a mitad de una escritura y
no obliga a instalar una base para dar de alta a seis personas.

Donde sí se aparta del libro mayor es en cómo escribe. Aquél sólo añade —un
trabajo terminado no se corrige— y éste tiene que poder sustituir y borrar, así
que reescribe el archivo entero cada vez. Sobre una lista que en este edificio
cabe en una pantalla eso son microsegundos, y a cambio no hay que reconstruir el
estado leyendo un historial de altas y bajas para saber quién está dado de alta
hoy. La reescritura va a un temporal y se sustituye de un golpe, para que un
corte de luz a mitad no deje el archivo de usuarios truncado, que es la única
forma en que este módulo puede dejar a todo el mundo fuera.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from ..domain.perfil import Perfil
from ..domain.usuario import Usuario, UsuarioInvalido

logger = logging.getLogger(__name__)


class FileUserStore:
    """Quién está dado de alta, con una línea por persona."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        #: La lectura cacheada, invalidada por el tamaño y la fecha del propio
        #: archivo. Cada petición pregunta quién es el que la manda, así que
        #: releer el archivo en cada una sería leerlo cientos de veces por caja.
        self._cache: list[Usuario] | None = None
        self._signature: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        return self._path

    # -- lectura ---------------------------------------------------------------

    def all(self) -> list[Usuario]:
        with self._lock:
            return list(self._read())

    def _read(self) -> list[Usuario]:
        if not self._path.exists():
            self._cache, self._signature = [], None
            return []
        estado = self._path.stat()
        firma = (estado.st_size, estado.st_mtime_ns)
        if self._cache is not None and firma == self._signature:
            return self._cache

        usuarios: list[Usuario] = []
        vistas: set[str] = set()
        with self._path.open("r", encoding="utf-8") as handle:
            for numero, linea in enumerate(handle, start=1):
                linea = linea.strip()
                if not linea:
                    continue
                usuario = self._parse(linea, numero)
                # Una línea repetida gana la última, que es la que se escribió
                # después. No debería haberlas -- guardar sustituye -- pero un
                # archivo editado a mano las tiene, y entonces «qué perfil tiene
                # esta persona» no puede depender de cuál se lea primero.
                if usuario is None:
                    continue
                if usuario.cedula in vistas:
                    usuarios = [u for u in usuarios if u.cedula != usuario.cedula]
                vistas.add(usuario.cedula)
                usuarios.append(usuario)

        self._cache, self._signature = usuarios, firma
        return usuarios

    def _parse(self, linea: str, numero: int) -> Usuario | None:
        """Una línea, o nada si está rota.

        Una línea ilegible se salta y se registra. Negarse a arrancar por una
        línea mal escrita dejaría a todo el archivo fuera por el alta de una
        sola persona, y quien la escribió puede arreglarla mientras los demás
        siguen trabajando.
        """
        try:
            crudo = json.loads(linea)
            return Usuario(
                cedula=str(crudo["cedula"]),
                correo=str(crudo["correo"]),
                perfil=Perfil.parse(crudo.get("perfil")),
                nombre=str(crudo.get("nombre") or ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError, UsuarioInvalido, TypeError):
            logger.warning(
                "línea %d de %s ilegible; ese usuario no se carga", numero, self._path
            )
            return None

    # -- escritura -------------------------------------------------------------

    def save(self, usuario: Usuario) -> None:
        with self._lock:
            actuales = [u for u in self._read() if u.cedula != usuario.cedula]
            self._write(actuales + [usuario])

    def delete(self, cedula: str) -> bool:
        with self._lock:
            actuales = self._read()
            quedan = [u for u in actuales if u.cedula != cedula]
            if len(quedan) == len(actuales):
                return False
            self._write(quedan)
            return True

    def _write(self, usuarios: list[Usuario]) -> None:
        """Reescribe el archivo entero, de un golpe.

        A un temporal en la misma carpeta y luego `os.replace`, que en el mismo
        sistema de archivos es atómico: o está el archivo de antes o está el de
        después, nunca uno a medias. Un archivo de usuarios truncado es la única
        avería de este módulo que deja a todo el mundo fuera.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporal = self._path.with_suffix(self._path.suffix + ".tmp")
        with temporal.open("w", encoding="utf-8", newline="\n") as handle:
            for usuario in usuarios:
                # Los cuatro datos que son, y no lo que la pantalla necesita
                # además: la etiqueta del perfil se deriva del perfil, y
                # guardarla la congelaría el día que se cambie su redacción.
                fila = {
                    "cedula": usuario.cedula,
                    "correo": usuario.correo,
                    "nombre": usuario.nombre,
                    "perfil": str(usuario.perfil),
                }
                handle.write(json.dumps(fila, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporal, self._path)
        # La caché se invalida sola por la firma del archivo, pero dejarla
        # puesta ahorra la relectura inmediata que hace la respuesta de esta
        # misma petición.
        estado = self._path.stat()
        self._cache = list(usuarios)
        self._signature = (estado.st_size, estado.st_mtime_ns)
