-- -----------------------------------------------------------------------------
--  001 — el tipo documental y los anexos, en la fila de cada unidad
-- -----------------------------------------------------------------------------
--  `db/schema.sql` ya trae estas dos columnas, así que una base creada desde
--  cero no necesita nada de esto. Es para las que ya existen: aplicar el
--  esquema entero sobre una base con datos borraría lo que hay.
--
--  Qué añaden:
--
--    tipo          qué clase de papel es cada unidad, con el nombre del
--                  catálogo del archivo. Lo pone la clasificación, que corre
--                  después del corte. Nulo cuando nadie lo reconoció, que es
--                  un tercio de una caja real: escribir ahí el tipo más
--                  parecido es como un expediente acaba con cuatro "facturas"
--                  que nadie facturó.
--
--    rango_anexos  cuáles de sus páginas entraron como anexo y no como cuerpo.
--                  Sin esto un acta con sus cuatro fotografías es
--                  indistinguible de un acta de cinco hojas.
--
--  Las filas anteriores a esta migración quedan con las dos en NULL, que es la
--  verdad: de esos documentos no se llegó a registrar ni el tipo ni los
--  anexos, y rellenarlos ahora sería inventarlos.
--
--  Se aplica así, y es idempotente por la vía de fallar en claro si ya está:
--
--      mysql -u root -p robotpdf < db/migraciones/001-tipo-documental.sql
-- -----------------------------------------------------------------------------

ALTER TABLE resolucion
  ADD COLUMN tipo VARCHAR(80) NULL AFTER titulo,
  ADD COLUMN rango_anexos VARCHAR(255) NULL AFTER rango_paginas,
  ADD KEY ix_resolucion_tipo (tipo);

-- La vista se redefine entera: es la misma que trae `schema.sql`.
CREATE OR REPLACE VIEW v_inventario AS
SELECT
  r.codigo,
  r.titulo,
  r.tipo,
  r.archivo,
  r.paginas,
  r.rango_paginas,
  r.rango_anexos,
  r.origen_lectura,
  r.creada_en,
  r.fecha,
  d.uuid   AS documento_uuid,
  d.nombre AS documento,
  o.nombre AS operador
FROM resolucion r
JOIN documento d ON d.id = r.documento_id
LEFT JOIN operador o ON o.id = d.operador_id;
