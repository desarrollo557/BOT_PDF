from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

#: Cuánto se espera a que la persona elija antes de rendirse. Generoso: está
#: navegando su disco, no respondiendo un formulario.
TIMEOUT_SECONDS = 300.0


class PickerUnavailable(RuntimeError):
    """No hay diálogo nativo que abrir en esta máquina."""


# El diálogo se abre en el escritorio de quien ejecuta el servicio. Eso es
# exactamente lo que se quiere cuando el servicio corre en la máquina del
# operador -- y exactamente lo que NO se quiere si algún día corre en un
# servidor, porque la ventana aparecería allá, invisible, y el navegador se
# quedaría esperando.
#
# La ventana sale al frente sola, desde dentro de este mismo proceso. Se intentó
# antes empujarla desde Python con SetForegroundWindow y no sirve: Windows no
# deja que un proceso en segundo plano -- y el servicio lo es -- le robe el
# primer plano a otro. Desde aquí sí, porque quien pide el cambio es el dueño de
# la ventana. Un temporizador de Windows Forms basta: el bucle modal del diálogo
# sigue despachando mensajes, así que el tick ocurre con el diálogo ya abierto.
_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms | Out-Null
Add-Type -AssemblyName System.Drawing | Out-Null

Add-Type @'
using System;
using System.Runtime.InteropServices;
public class Frente {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr tras, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint destino, uint origen, bool unir);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr GetActiveWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();

  // La ventana del diálogo, vista desde su propio hilo. Dentro del bucle modal
  // la ventana activa del hilo ES el diálogo, así que no hay que adivinar
  // títulos ni clases -- y funciona en cualquier idioma de Windows.
  public static IntPtr Activa() { return GetActiveWindow(); }

  public static void Subir(IntPtr h) {
    // Cada paso por separado falla en algún caso; los tres juntos, no.
    SetWindowPos(h, new IntPtr(-1), 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040);
    uint hiloDelFrente = GetWindowThreadProcessId(GetForegroundWindow(), IntPtr.Zero);
    uint hiloPropio = GetCurrentThreadId();
    AttachThreadInput(hiloPropio, hiloDelFrente, true);
    BringWindowToTop(h);
    SetForegroundWindow(h);
    AttachThreadInput(hiloPropio, hiloDelFrente, false);
    // Deja de ser "siempre encima" en cuanto está delante: una ventana clavada
    // sobre todo lo demás estorba más de lo que ayuda.
    SetWindowPos(h, new IntPtr(-2), 0, 0, 0, 0, 0x0002 | 0x0001);
  }
}
'@ | Out-Null

# La ventana dueña existe para una sola cosa: darle un padre al diálogo. Tiene
# que ser realmente invisible -- de un píxel, sin borde y transparente -- y
# tiene que estar mostrada antes de usarla. Una ventana creada y no mostrada se
# dibuja como un rectángulo blanco de 300x300 en cuanto Windows le crea el
# handle, que es lo que aparecía antes del explorador.
$owner = New-Object System.Windows.Forms.Form
$owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$owner.Location = New-Object System.Drawing.Point(0, 0)
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.TopMost = $true
$owner.Show()
$owner.Activate()

$reloj = New-Object System.Windows.Forms.Timer
$reloj.Interval = 200
$reloj.Add_Tick({
  $activa = [Frente]::Activa()
  if ($activa -ne [IntPtr]::Zero -and $activa -ne $owner.Handle) {
    [Frente]::Subir($activa)
    $reloj.Stop()
  }
})
$reloj.Start()

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $args[0]
$dialog.ShowNewFolderButton = $true
if ($args[1]) { $dialog.SelectedPath = $args[1] }

$elegido = ''
try {
  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
    $elegido = $dialog.SelectedPath
  }
} finally {
  # La limpieza nunca puede cambiar el resultado: si algo aquí falla, el
  # servicio lo leería como "no se pudo abrir" y la pantalla abriría su propio
  # explorador encima del que la persona acaba de usar.
  try { $reloj.Stop(); $reloj.Dispose(); $owner.Hide(); $owner.Dispose(); $dialog.Dispose() } catch { }
}

if ($elegido) { [Console]::Out.Write($elegido) }
exit 0
"""


def available() -> bool:
    """Si esta máquina puede mostrar una ventana."""
    if os.name != "nt":
        return False
    # Un servicio sin escritorio no puede abrir nada; mejor decirlo que colgar
    # una petición durante cinco minutos.
    return sys.stdout is not None or True


def ask_directory(title: str, initial: str | None = None) -> str | None:
    """Abre el explorador de carpetas de Windows y devuelve lo que se eligió.

    Devuelve ``None`` si la persona canceló. Bloquea mientras el diálogo está
    abierto, así que el llamador lo ejecuta fuera del bucle de eventos.
    """
    if os.name != "nt":
        raise PickerUnavailable("El explorador nativo sólo está disponible en Windows")

    start = ""
    if initial:
        candidate = Path(initial).expanduser()
        if candidate.is_dir():
            start = str(candidate)

    try:
        finished = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-STA",  # los diálogos de Windows Forms lo exigen
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _SCRIPT,
                title,
                start,
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as error:
        raise PickerUnavailable("No se encontró PowerShell en esta máquina") from error
    except subprocess.TimeoutExpired as error:
        raise PickerUnavailable(
            "El explorador quedó abierto demasiado tiempo y se canceló"
        ) from error

    if finished.returncode != 0:
        logger.warning(
            "el explorador nativo falló: %s", (finished.stderr or "").strip()[:200]
        )
        raise PickerUnavailable("No se pudo abrir el explorador de carpetas")

    return (finished.stdout or "").strip() or None
