## Qué cambia

<!-- Una o dos frases. Qué hace distinto el sistema después de este PR. -->

## Por qué

<!-- El problema real, no la solución. Si hay issue, referenciala: Closes #123 -->

## Cómo se probó

<!-- Marcá lo que corriste de verdad, no lo que debería andar. -->

- [ ] `pytest -q` en `backend/` — verde
- [ ] `npm run check && npm run test && npm run build` en `web/` — verde
- [ ] `python scripts/check_layers.py` — las capas siguen en su sitio
- [ ] Probado contra el servicio corriendo (no sólo con las pruebas):
      endpoints tocados y sus casos de error

## Impacto

- [ ] Cambia el esquema de la base (`db/schema.sql`) → describir la migración
- [ ] Cambia un endpoint que el front ya consume
- [ ] Cambia el formato de nombres de archivo o el criterio de agrupación
- [ ] Ninguno de los anteriores

## Datos reales

- [ ] Ninguna cifra que muestra la interfaz viene de un valor fijo, de un
      ejemplo o de una estimación: todas salen de la corrida o de la base.
