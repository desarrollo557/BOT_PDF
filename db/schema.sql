-- =============================================================================
--  robotpdf — modelo de datos del separador de resoluciones
--  MySQL 8.0+ / InnoDB / utf8mb4
-- =============================================================================
--
--  Escala de diseño: 400.000 páginas por día. Con ~20 páginas por documento y
--  ~1 resolución cada 4 páginas, eso son al año, sobre 260 días hábiles:
--
--      documento    ~5,2 M filas   ~1,2 GB con índices
--      resolucion  ~26,0 M filas   ~7,0 GB con índices
--      revision     ~5,2 M filas   ~0,8 GB con índices
--
--  Dos decisiones sostienen ese volumen y conviene entenderlas antes de tocar
--  nada:
--
--  1. NO hay una fila por página. Serían 104 M de filas al año para responder
--     preguntas que contestan cinco contadores. Lo que sí se guarda es la
--     excepción -- la página que fue a revisión, la que se corrigió -- y el
--     histograma agregado. La tabla `pagina_leida` existe al final, comentada,
--     para cuando haga falta análisis por página con retención acotada.
--
--  2. La clave primaria es un BIGINT autoincremental, no el UUID. InnoDB
--     agrupa físicamente las filas por la clave primaria: con un UUID aleatorio
--     cada inserción cae en una página distinta, y esa clave se copia dentro de
--     cada índice secundario. El UUID vive igual, como `uuid` único, porque es
--     el identificador que ya usa la API.
-- =============================================================================

DROP DATABASE IF EXISTS robotpdf;

CREATE DATABASE robotpdf
  DEFAULT CHARACTER SET utf8mb4
  -- Acento-insensible a propósito: buscar "maria" tiene que encontrar "María".
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE robotpdf;


-- -----------------------------------------------------------------------------
--  operador — quién estaba en la consola
-- -----------------------------------------------------------------------------
--  No hay contraseña detrás de este nombre. Es atribución, nunca autorización:
--  sirve para responder "quién procesó esto" y para separar turnos, y ninguna
--  consulta de esta base debe conceder ni negar nada en función de él.
--
--  Normalizado en su propia tabla para que filtrar por operador sea un JOIN
--  indexado en vez de comparar cadenas, y para que corregir un nombre mal
--  escrito sea una fila y no un UPDATE masivo.
-- -----------------------------------------------------------------------------
CREATE TABLE operador (
  id            SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre        VARCHAR(60)  NOT NULL,
  puesto        VARCHAR(60)  NULL,
  visto_primero DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  visto_ultimo  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                             ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_operador_nombre (nombre)
) ENGINE=InnoDB;


-- -----------------------------------------------------------------------------
--  corrida — un lote, una carpeta vigilada, o una carga suelta
-- -----------------------------------------------------------------------------
--  Los tres agrupan documentos y se consultan igual ("qué se procesó en esta
--  corrida"), así que son una sola tabla con un discriminador. Las columnas de
--  carpeta quedan nulas para las otras dos: separarlas en tres tablas obligaría
--  a un UNION en cada pantalla del archivo para no ganar nada.
-- -----------------------------------------------------------------------------
CREATE TABLE corrida (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  uuid           CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  tipo           ENUM('individual','lote','carpeta') NOT NULL,
  nombre         VARCHAR(160) NULL,
  operador_id    SMALLINT UNSIGNED NULL,

  -- Sólo para tipo='carpeta'.
  origen         VARCHAR(500) NULL,
  destino        VARCHAR(500) NULL,
  destino_original ENUM('dejar','apartar','borrar') NULL,
  vigila         TINYINT(1)   NOT NULL DEFAULT 0,

  estado         ENUM('en_curso','terminada','detenida','fallida')
                 NOT NULL DEFAULT 'en_curso',
  iniciada_en    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  terminada_en   DATETIME(3)  NULL,
  error          VARCHAR(500) NULL,

  -- Totales de la corrida. Se mantienen al cerrar cada documento porque el
  -- informe se lee mucho después, cuando los documentos pueden haber sido
  -- purgados, y un informe que cae a cero afirma algo falso.
  documentos     INT UNSIGNED NOT NULL DEFAULT 0,
  documentos_fallidos INT UNSIGNED NOT NULL DEFAULT 0,
  resoluciones   INT UNSIGNED NOT NULL DEFAULT 0,
  paginas        INT UNSIGNED NOT NULL DEFAULT 0,
  bytes_origen   BIGINT UNSIGNED NOT NULL DEFAULT 0,
  entregados     INT UNSIGNED NOT NULL DEFAULT 0,

  PRIMARY KEY (id),
  UNIQUE KEY uq_corrida_uuid (uuid),
  KEY ix_corrida_iniciada (iniciada_en DESC),
  KEY ix_corrida_estado (estado, iniciada_en DESC),
  KEY ix_corrida_operador (operador_id, iniciada_en DESC),
  CONSTRAINT fk_corrida_operador FOREIGN KEY (operador_id)
    REFERENCES operador (id) ON DELETE SET NULL
) ENGINE=InnoDB;


-- -----------------------------------------------------------------------------
--  documento — un PDF de origen, procesado una vez
-- -----------------------------------------------------------------------------
--  El mismo archivo procesado dos veces son dos documentos: son dos corridas,
--  con dos resultados que pueden diferir. Unificarlos escondería justo la
--  comparación que alguien querría hacer.
-- -----------------------------------------------------------------------------
CREATE TABLE documento (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  uuid           CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  corrida_id     BIGINT UNSIGNED NOT NULL,
  operador_id    SMALLINT UNSIGNED NULL,

  -- El nombre que le puso el operador, no el generado con que se almacenó.
  nombre         VARCHAR(255) NOT NULL,
  bytes          BIGINT UNSIGNED NOT NULL DEFAULT 0,

  estado         ENUM('en_cola','procesando','terminado','fallido')
                 NOT NULL DEFAULT 'en_cola',
  error          VARCHAR(1000) NULL,

  iniciado_en    DATETIME(3)  NULL,
  terminado_en   DATETIME(3)  NULL,
  -- Columna generada e indexada: el archivo agrupa por día, y sin esto cada
  -- consulta aplicaría DATE() sobre cada fila y perdería el índice.
  fecha          DATE AS (DATE(terminado_en)) STORED,

  -- Contadores del documento. Denormalizados a propósito: la tarjeta del
  -- archivo los muestra los cuatro, y calcularlos sería cuatro agregaciones
  -- por tarjeta sobre las tablas grandes.
  paginas        INT UNSIGNED NOT NULL DEFAULT 0,
  resoluciones   INT UNSIGNED NOT NULL DEFAULT 0,
  en_revision    INT UNSIGNED NOT NULL DEFAULT 0,
  en_cuarentena  INT UNSIGNED NOT NULL DEFAULT 0,
  correcciones   INT UNSIGNED NOT NULL DEFAULT 0,

  -- Histograma del cascade: dónde se resolvió cada página. Cinco contadores en
  -- lugar de 20 M de filas al año.
  pag_capa_texto INT UNSIGNED NOT NULL DEFAULT 0,
  pag_ocr_banda  INT UNSIGNED NOT NULL DEFAULT 0,
  pag_ocr_total  INT UNSIGNED NOT NULL DEFAULT 0,
  pag_vision     INT UNSIGNED NOT NULL DEFAULT 0,
  pag_ilegible   INT UNSIGNED NOT NULL DEFAULT 0,
  consultas_vision INT UNSIGNED NOT NULL DEFAULT 0,

  PRIMARY KEY (id),
  UNIQUE KEY uq_documento_uuid (uuid),
  KEY ix_documento_fecha (fecha DESC, terminado_en DESC),
  KEY ix_documento_corrida (corrida_id, terminado_en DESC),
  KEY ix_documento_operador (operador_id, terminado_en DESC),
  KEY ix_documento_estado (estado, terminado_en DESC),
  -- Cubre el filtro "sólo lo que necesita revisión" sin tocar la fila.
  KEY ix_documento_revision (en_revision, terminado_en DESC),
  KEY ix_documento_nombre (nombre(64)),
  FULLTEXT KEY ft_documento_nombre (nombre),
  CONSTRAINT fk_documento_corrida FOREIGN KEY (corrida_id)
    REFERENCES corrida (id) ON DELETE CASCADE,
  CONSTRAINT fk_documento_operador FOREIGN KEY (operador_id)
    REFERENCES operador (id) ON DELETE SET NULL
) ENGINE=InnoDB;


-- -----------------------------------------------------------------------------
--  resolucion — un PDF generado. El producto del sistema.
-- -----------------------------------------------------------------------------
--  La tabla grande: ~26 M de filas al año. Todo lo que se busca aquí está
--  indexado, y lo que no cabe en un índice B-tree (buscar palabras dentro del
--  título) tiene FULLTEXT.
-- -----------------------------------------------------------------------------
CREATE TABLE resolucion (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  documento_id   BIGINT UNSIGNED NOT NULL,

  -- El número tal como quedó tras normalizar. ASCII: son dígitos y, con OCR
  -- dañado, letras latinas; no necesita utf8mb4 y ocupa la cuarta parte.
  codigo         VARCHAR(32) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  -- Lo que leyó el OCR antes de normalizar, para poder auditar una corrección.
  codigo_crudo   VARCHAR(64) CHARACTER SET ascii COLLATE ascii_general_ci NULL,
  titulo         VARCHAR(400) NULL,

  archivo        VARCHAR(255) NOT NULL,
  paginas        SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  pagina_desde   SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  pagina_hasta   SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  -- Rangos, no la lista: "12-51" en vez de cuarenta enteros.
  rango_paginas  VARCHAR(255) NULL,

  -- Cómo se decidió el número, para poder medir el coste después.
  origen_lectura ENUM('capa_texto','ocr_banda','ocr_total','vision','contexto','manual')
                 NOT NULL DEFAULT 'capa_texto',
  confianza      DECIMAL(4,3) NULL,
  corregida      TINYINT(1) NOT NULL DEFAULT 0,

  creada_en      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  fecha          DATE AS (DATE(creada_en)) STORED,

  PRIMARY KEY (id),
  -- Un documento no puede producir dos archivos con el mismo nombre, y esto es
  -- lo que lo impide de verdad, no una comprobación en la aplicación.
  UNIQUE KEY uq_resolucion_archivo (documento_id, archivo),
  KEY ix_resolucion_codigo (codigo, creada_en DESC),
  KEY ix_resolucion_documento (documento_id),
  KEY ix_resolucion_fecha (fecha DESC),
  KEY ix_resolucion_origen (origen_lectura),
  FULLTEXT KEY ft_resolucion_titulo (titulo),
  CONSTRAINT fk_resolucion_documento FOREIGN KEY (documento_id)
    REFERENCES documento (id) ON DELETE CASCADE
) ENGINE=InnoDB;


-- -----------------------------------------------------------------------------
--  revision — la página que la máquina se negó a adivinar
-- -----------------------------------------------------------------------------
--  Sólo la excepción llega aquí. Es la cola de trabajo de una persona, así que
--  se indexa por lo que esa persona filtra: motivo y si ya está resuelta.
-- -----------------------------------------------------------------------------
CREATE TABLE revision (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  documento_id   BIGINT UNSIGNED NOT NULL,
  pagina         SMALLINT UNSIGNED NOT NULL,
  motivo         ENUM('sin_codigo','conflicto','no_copiada','no_leida','otro')
                 NOT NULL,
  detalle        VARCHAR(1000) NULL,

  resuelta       TINYINT(1) NOT NULL DEFAULT 0,
  resuelta_en    DATETIME(3) NULL,
  resuelta_por   SMALLINT UNSIGNED NULL,
  -- A qué resolución acabó perteneciendo, cuando alguien lo decide.
  resolucion_id  BIGINT UNSIGNED NULL,

  creada_en      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

  PRIMARY KEY (id),
  UNIQUE KEY uq_revision_pagina (documento_id, pagina),
  KEY ix_revision_pendiente (resuelta, motivo, creada_en DESC),
  KEY ix_revision_documento (documento_id),
  CONSTRAINT fk_revision_documento FOREIGN KEY (documento_id)
    REFERENCES documento (id) ON DELETE CASCADE,
  CONSTRAINT fk_revision_operador FOREIGN KEY (resuelta_por)
    REFERENCES operador (id) ON DELETE SET NULL,
  CONSTRAINT fk_revision_resolucion FOREIGN KEY (resolucion_id)
    REFERENCES resolucion (id) ON DELETE SET NULL
) ENGINE=InnoDB;


-- -----------------------------------------------------------------------------
--  correccion — el ruido de OCR que se absorbió, y quedó registrado
-- -----------------------------------------------------------------------------
--  Una corrección aplicada en silencio es indistinguible de un error. Ésta es
--  la tabla que hace que "el sistema cambió 04I2 por 0412" sea auditable.
-- -----------------------------------------------------------------------------
CREATE TABLE correccion (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  documento_id   BIGINT UNSIGNED NOT NULL,
  pagina         SMALLINT UNSIGNED NOT NULL,
  leido          VARCHAR(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  aplicado       VARCHAR(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  distancia      TINYINT UNSIGNED NOT NULL,
  origen         ENUM('automatica','manual') NOT NULL DEFAULT 'automatica',
  operador_id    SMALLINT UNSIGNED NULL,
  creada_en      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

  PRIMARY KEY (id),
  KEY ix_correccion_documento (documento_id, pagina),
  CONSTRAINT fk_correccion_documento FOREIGN KEY (documento_id)
    REFERENCES documento (id) ON DELETE CASCADE,
  CONSTRAINT fk_correccion_operador FOREIGN KEY (operador_id)
    REFERENCES operador (id) ON DELETE SET NULL
) ENGINE=InnoDB;


-- -----------------------------------------------------------------------------
--  entrega — una resolución copiada a una carpeta de destino
-- -----------------------------------------------------------------------------
--  Se guarda el nombre con que quedó, que no siempre es el generado: dos
--  documentos pueden producir el mismo número y el segundo se entrega como
--  "(2)". Sin esto, el registro apunta a un archivo que no existe.
-- -----------------------------------------------------------------------------
CREATE TABLE entrega (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  resolucion_id  BIGINT UNSIGNED NOT NULL,
  corrida_id     BIGINT UNSIGNED NOT NULL,
  destino        VARCHAR(500) NOT NULL,
  archivo        VARCHAR(255) NOT NULL,
  bytes          BIGINT UNSIGNED NOT NULL DEFAULT 0,
  entregada_en   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

  PRIMARY KEY (id),
  KEY ix_entrega_resolucion (resolucion_id),
  KEY ix_entrega_corrida (corrida_id, entregada_en DESC),
  CONSTRAINT fk_entrega_resolucion FOREIGN KEY (resolucion_id)
    REFERENCES resolucion (id) ON DELETE CASCADE,
  CONSTRAINT fk_entrega_corrida FOREIGN KEY (corrida_id)
    REFERENCES corrida (id) ON DELETE CASCADE
) ENGINE=InnoDB;


-- =============================================================================
--  Vistas — las tres preguntas que hace la aplicación, ya resueltas
-- =============================================================================

-- El archivo, grano "por documento": una fila por tarjeta.
CREATE OR REPLACE VIEW v_archivo_documentos AS
SELECT
  d.uuid            AS documento_uuid,
  d.nombre          AS documento,
  d.terminado_en    AS procesado_en,
  d.fecha           AS fecha,
  d.resoluciones,
  d.paginas,
  d.bytes,
  d.en_revision,
  d.estado,
  o.nombre          AS operador,
  c.uuid            AS corrida_uuid,
  c.tipo            AS corrida_tipo,
  c.nombre          AS corrida_nombre
FROM documento d
LEFT JOIN operador o ON o.id = d.operador_id
JOIN corrida c       ON c.id = d.corrida_id;

-- El archivo, grano "por resolución": el inventario.
CREATE OR REPLACE VIEW v_inventario AS
SELECT
  r.codigo,
  r.titulo,
  r.archivo,
  r.paginas,
  r.rango_paginas,
  r.origen_lectura,
  r.creada_en,
  r.fecha,
  d.uuid   AS documento_uuid,
  d.nombre AS documento,
  o.nombre AS operador
FROM resolucion r
JOIN documento d ON d.id = r.documento_id
LEFT JOIN operador o ON o.id = d.operador_id;

-- La cola de revisión, con el documento al que pertenece cada página.
CREATE OR REPLACE VIEW v_revision_pendiente AS
SELECT
  rv.id,
  rv.pagina,
  rv.motivo,
  rv.detalle,
  rv.creada_en,
  d.uuid   AS documento_uuid,
  d.nombre AS documento,
  o.nombre AS operador
FROM revision rv
JOIN documento d ON d.id = rv.documento_id
LEFT JOIN operador o ON o.id = d.operador_id
WHERE rv.resuelta = 0;

-- Producción por día: lo que se pone en un tablero sin agregar nada en vivo.
CREATE OR REPLACE VIEW v_produccion_diaria AS
SELECT
  d.fecha,
  COUNT(*)                                  AS documentos,
  SUM(d.resoluciones)                       AS resoluciones,
  SUM(d.paginas)                            AS paginas,
  SUM(d.bytes)                              AS bytes,
  SUM(d.en_revision)                        AS en_revision,
  SUM(d.estado = 'fallido')                 AS fallidos,
  SUM(d.pag_vision)                         AS paginas_al_modelo,
  ROUND(100 * SUM(d.pag_vision) / NULLIF(SUM(d.paginas), 0), 3) AS pct_al_modelo
FROM documento d
WHERE d.fecha IS NOT NULL
GROUP BY d.fecha;


-- =============================================================================
--  OPCIONAL — análisis por página
-- =============================================================================
--  Descomentar sólo si hace falta responder preguntas por página que los cinco
--  contadores de `documento` no contestan: aprender dónde cae el número en cada
--  plantilla, o medir la confianza del OCR por zona.
--
--  Cuesta ~104 M de filas al año. Por eso va particionada por mes y con una
--  retención explícita: sin purga, en dos años es la tabla más grande de la
--  base y la única que nadie consulta.
-- =============================================================================
--
-- CREATE TABLE pagina_leida (
--   documento_id  BIGINT UNSIGNED NOT NULL,
--   pagina        SMALLINT UNSIGNED NOT NULL,
--   origen        ENUM('capa_texto','ocr_banda','ocr_total','vision','ninguno')
--                 NOT NULL,
--   codigo        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_general_ci NULL,
--   confianza     DECIMAL(4,3) NULL,
--   ambigua       TINYINT(1) NOT NULL DEFAULT 0,
--   creada_en     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
--   PRIMARY KEY (documento_id, pagina, creada_en),
--   KEY ix_pagina_origen (origen, creada_en)
-- ) ENGINE=InnoDB
-- PARTITION BY RANGE (TO_DAYS(creada_en)) (
--   PARTITION p2026_09 VALUES LESS THAN (TO_DAYS('2026-10-01')),
--   PARTITION p2026_10 VALUES LESS THAN (TO_DAYS('2026-11-01')),
--   PARTITION pmax     VALUES LESS THAN MAXVALUE
-- );
--
--  Purga de un mes:  ALTER TABLE pagina_leida DROP PARTITION p2026_09;
--  (instantáneo; un DELETE de 8 M de filas no lo es)


-- =============================================================================
--  Usuario de aplicación
-- =============================================================================
--  El servicio no debe conectarse como root. Estos permisos son los que
--  necesita y ninguno más: no puede crear ni borrar tablas, así que un fallo
--  del programa no puede perder el esquema.
--
--  Reemplace la contraseña antes de ejecutarlo.
-- =============================================================================
--
-- CREATE USER IF NOT EXISTS 'robotpdf_app'@'localhost'
--   IDENTIFIED BY 'CAMBIE-ESTA-CONTRASENA';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON robotpdf.* TO 'robotpdf_app'@'localhost';
-- FLUSH PRIVILEGES;
