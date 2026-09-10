"""El catálogo de tipos documentales del archivo del cliente.

Son datos, no reglas: la lista de tipos que el archivo reconoce y las formas con
que cada uno aparece impreso. Vive aparte del algoritmo que los busca porque es
lo que más se toca -- añadir un tipo es rutina, cambiar cómo se reconocen no --
y tenerlos juntos obligaba a navegar cuatrocientas líneas de datos para llegar a
la lógica, o al revés.

Ninguna palabra que no esté aquí puede acabar en el nombre de un archivo. Un
papel que no se reconozca sale sin tipo -- que es lo honesto -- en vez de con el
tipo más parecido, que es como un expediente termina teniendo cuatro "facturas"
que nadie facturó.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TipoDocumental:
    """Un tipo del catálogo, y lo que hay que leer para reconocerlo.

    ``nombre`` es el del listado del cliente y es lo único que llega al nombre de
    un archivo. ``frases`` son las formas con que ese tipo aparece impreso: el
    propio nombre, las erratas que trae el listado de origen y los sinónimos que
    usa el papel. Un tipo sin frases existe en el catálogo pero no se reconoce
    solo -- lo pone una persona.
    """

    nombre: str
    frases: tuple[str, ...] = ()


# -----------------------------------------------------------------------------
#  El catálogo
# -----------------------------------------------------------------------------
#  Es el listado de tipos documentales del archivo del cliente, filtrado. El
#  listado de origen trae el mismo tipo escrito de varias maneras -- "CAMBIO DE
#  UBICACION A CONTADOR" dos veces, "PAGO NO APLICADO" junto a "PAGOS NO
#  APLICADOS", "REFACTURACCION" junto a "REFATURACCION" -- y ninguna de esas
#  variantes se ha borrado: la que se eligió como nombre canónico es la que
#  nombra el archivo, y las demás se quedan como frases que también lo delatan.
#  Así el nombre en disco es uno solo y no se pierde ninguna pista.
#
#  Las frases se escriben ya normalizadas -- mayúsculas, sin acentos, sin
#  puntuación -- porque es la forma contra la que se comparan.
# -----------------------------------------------------------------------------

CATALOGO: tuple[TipoDocumental, ...] = (
    #: Los tres que siguen no venían en el listado del cliente y sí en el papel:
    #: los reconocía la lista de rótulos que este catálogo sustituyó, y se
    #: añadieron a petición del operador para no perder el corte ni el nombre.
    TipoDocumental("ACTA DE INSPECCION ELECTRICA", ("ACTA DE INSPECCION ELECTRICA",)),
    TipoDocumental("ACTA DE IRREGULARIDAD", ("ACTA DE IRREGULARIDAD",)),
    TipoDocumental(
        "ACTA DE REVISION E INSTALACION ELECTRICA",
        ("ACTA DE REVISION E INSTALACION ELECTRICA", "ACTA DE REVISION E INSTALACION"),
    ),
    TipoDocumental(
        "ACTA DE SUSPENSION CORTE Y RECONEXION",
        ("ACTA DE SUSPENSION CORTE Y RECONEXION", "SUSPENSION CORTE Y RECONEXION"),
    ),
    TipoDocumental(
        "ACTA DECLARACION CON FINES EXTRAPROCESALES",
        (
            "ACTA DECLARACION CON FINES EXTRAPROCESALES",
            "DECLARACION CON FINES EXTRAPROCESALES",
            "DECLARACION CON FINES EXTRA PROCESALES",
        ),
    ),
    TipoDocumental("AJUSTE DE CARGOS VARIOS", ("AJUSTE DE CARGOS VARIOS",)),
    TipoDocumental("AMPLIACION DE TERMINOS", ("AMPLIACION DE TERMINOS",)),
    TipoDocumental("ANEXO A RECLAMO", ("ANEXO A RECLAMO",)),
    TipoDocumental("ANEXOS", ("ANEXOS",)),
    TipoDocumental("APORTE DE DOCUMENTOS", ("APORTE DE DOCUMENTOS",)),
    TipoDocumental("AUMENTO DE CARGA", ("AUMENTO DE CARGA",)),
    TipoDocumental("AUTORIZACION", ("AUTORIZACION",)),
    TipoDocumental(
        "AUTORIZACION DE TRATAMIENTO DE DATOS PERSONALES",
        (
            "AUTORIZACION DE TRATAMIENTO DE DATOS PERSONALES",
            "AUTORIZACION PARA EL TRATAMIENTO DE DATOS PERSONALES",
            "AUTORIZACION DE TRATAMIENTO DE DATOS",
        ),
    ),
    TipoDocumental(
        "AUTORIZACION PARA LA NOTIFICACION ELECTRONICA",
        (
            "AUTORIZACION PARA LA NOTIFICACION ELECTRONICA",
            "AUTORIZACION PARA NOTIFICACION ELECTRONICA",
            "AUTORIZO LA NOTIFICACION ELECTRONICA",
        ),
    ),
    TipoDocumental(
        "AUTORIZACION PARA LA NOTIFICACION PERSONAL",
        (
            "AUTORIZACION PARA LA NOTIFICACION PERSONAL",
            "AUTORIZACION PARA NOTIFICACION PERSONAL",
        ),
    ),
    TipoDocumental("CAMBIO DE FECHA DE PAGO", ("CAMBIO DE FECHA DE PAGO",)),
    TipoDocumental("CARTA DE INSTRUCCIONES", ("CARTA DE INSTRUCCIONES",)),
    TipoDocumental("CAMBIO DE TITULAR", ("CAMBIO DE TITULAR",)),
    TipoDocumental(
        "CAMBIO DE UBICACION A CONTADOR",
        ("CAMBIO DE UBICACION A CONTADOR", "CAMBIO DE UBICACION DEL CONTADOR"),
    ),
    TipoDocumental(
        "CAMBIO Y/O ACTUALIZACION DE DATOS BASICOS",
        (
            "CAMBIO Y/O ACTUALIZACION DE DATOS BASICOS",
            "CAMBIO YO ACTUALIZACION DE DATOS BASICOS",
            "CAMBIO O ACTUALIZACION DE DATOS BASICOS",
            "ACTUALIZACION DE DATOS BASICOS",
        ),
    ),
    TipoDocumental("CERTIFICADO CATASTRAL NACIONAL", ("CERTIFICADO CATASTRAL NACIONAL",)),
    TipoDocumental("CERTIFICADO DE DEFUNCION", ("CERTIFICADO DE DEFUNCION",)),
    TipoDocumental(
        "CERTIFICADO DE ESTRATO SOCIOECONOMICO",
        ("CERTIFICADO DE ESTRATO SOCIOECONOMICO", "CERTIFICADO DE ESTRATO"),
    ),
    TipoDocumental("CERTIFICADO DE GESTION DE COBRO", ("CERTIFICADO DE GESTION DE COBRO",)),
    TipoDocumental("CERTIFICADO DE NOMENCLATURA", ("CERTIFICADO DE NOMENCLATURA",)),
    TipoDocumental(
        "CERTIFICADO DE TRADICION",
        ("CERTIFICADO DE TRADICION Y LIBERTAD", "CERTIFICADO DE TRADICION"),
    ),
    TipoDocumental(
        "CITACION PARA NOTIFICACION PERSONAL",
        (
            "CITACION PARA NOTIFICACION PERSONAL",
            "CITACION PARA LA NOTIFICACION PERSONAL",
            "CITACION PARA NOTIFICACION",
        ),
    ),
    TipoDocumental("COBROS ACUMULADOS", ("COBROS ACUMULADOS", "COBRO ACUMULADO")),
    TipoDocumental("COMPROBANTE DE PAGO", ("COMPROBANTE DE PAGO",)),
    TipoDocumental("COMUNICACION", ("COMUNICACION",)),
    TipoDocumental(
        "CONSTANCIA DE CONTRATACION DE SERVICIO",
        ("CONSTANCIA DE CONTRATACION DE SERVICIO", "CONSTANCIA DE CONTRATACION"),
    ),
    TipoDocumental(
        "CONSTANCIA DE NOTIFICACION PERSONAL", ("CONSTANCIA DE NOTIFICACION PERSONAL",)
    ),
    TipoDocumental(
        "CONSTANCIA DE RECEPCION DE PETICIONES QUEJAS Y RECLAMOS",
        (
            "CONSTANCIA DE RECEPCION DE PETICIONES QUEJAS Y RECLAMOS",
            "CONSTANCIA DE RECEPCION DE PETICIONES",
        ),
    ),
    TipoDocumental(
        "CONSTANCIA DE VISITA REALIZADA EN EL INMUEBLE",
        (
            "CONSTANCIA DE VISITA REALIZADA EN EL INMUEBLE",
            "CONSTANCIA DE VISITA AL INMUEBLE",
            "CONSTANCIA DE VISITA",
        ),
    ),
    TipoDocumental(
        "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION",
        (
            "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION VERBAL",
            "CONSTANCIA DEL CONTENIDO DE LA RECLAMACION",
            "RECIBI CONSTANCIA DEL CONTENIDO",
        ),
    ),
    TipoDocumental("CONTRATO DE TRANSACCION", ("CONTRATO DE TRANSACCION",)),
    TipoDocumental("CONVENIO DE PAGO", ("CONVENIO DE PAGO", "ACUERDO DE PAGO")),
    TipoDocumental("DAÑO MEDIDOR", ("DANO MEDIDOR", "DANO EN EL MEDIDOR")),
    TipoDocumental(
        "DECLARACION BAJO GRAVEDAD DE JURAMENTO",
        (
            "DECLARACION BAJO LA GRAVEDAD DE JURAMENTO",
            "DECLARACION BAJO GRAVEDAD DE JURAMENTO",
            "BAJO LA GRAVEDAD DE JURAMENTO",
        ),
    ),
    TipoDocumental(
        "DECLARACION DE CUMPLIMIENTO DEL RETIE",
        ("DECLARACION DE CUMPLIMIENTO DEL RETIE", "CUMPLIMIENTO DEL RETIE"),
    ),
    TipoDocumental("DERECHO DE PETICION", ("DERECHO DE PETICION",)),
    TipoDocumental(
        "DESISTIMIENTO DEL RECLAMO",
        ("DESISTIMIENTO DEL RECLAMO", "DESISTIMIENTO DE RECLAMO", "DESISTIMIENTO"),
    ),
    TipoDocumental(
        "DEVOLUCION O TRASLADO DE SALDO A FAVOR",
        (
            "DEVOLUCION O TRASLADO DE SALDO A FAVOR",
            "DEVOLUCION DE SALDO A FAVOR",
            "TRASLADO DE SALDO A FAVOR",
        ),
    ),
    TipoDocumental(
        "DOCUMENTO DE IDENTIDAD",
        (
            "IDENTIFICACION PERSONAL CEDULA DE CIUDADANIA",
            "DOCUMENTO DE IDENTIDAD",
            "CEDULA DE CIUDADANIA",
            "TARJETA DE IDENTIDAD",
            # La carátula empieza por ahí, y es lo que queda legible cuando el
            # escáner destroza el resto: la cédula medida llegó como
            # "REFUBWCA DE COLOMSIá / IDENTIFICAGIOí^! JiMAL / CEDULA DE
            # CíÜDADÁINIA". Ninguna otra cosa del archivo se titula así.
            "REPUBLICA DE COLOMBIA",
        ),
    ),
    TipoDocumental(
        "DOCUMENTO PENDIENTE",
        ("DOCUMENTACION PENDIENTE", "DOCUMENTO PENDIENTE", "DOCUMENTO FALTANTE"),
    ),
    TipoDocumental(
        "ENTREGA INOPORTUNA DE LA FACTURA",
        ("ENTREGA INOPORTUNA DE LA FACTURA", "ENTREGA INOPORTUNA"),
    ),
    TipoDocumental(
        "ESTADO DE CUENTA DEL SERVICIO",
        ("ESTADO DE CUENTA DEL SERVICIO", "ESTADO DE CUENTA"),
    ),
    TipoDocumental("ESTRATO INCORRECTO", ("ESTRATO INCORRECTO",)),
    TipoDocumental("EXPEDIENTE", ("EXPEDIENTE",)),
    TipoDocumental(
        "FACTURA",
        ("FACTURA DE SERVICIOS PUBLICOS", "FACTURA DE VENTA", "FACTURA"),
    ),
    TipoDocumental("GESTION DE COBRO", ("GESTION DE COBRO",)),
    TipoDocumental(
        "INCONFORMIDAD CON EL CONSUMO FACTURADO",
        ("INCONFORMIDAD CON EL CONSUMO FACTURADO", "INCONFORMIDAD CON EL CONSUMO"),
    ),
    TipoDocumental("INMUEBLE DESOCUPADO", ("INMUEBLE DESOCUPADO",)),
    TipoDocumental("INSTALACION Y CENSO DE CARGA", ("INSTALACION Y CENSO DE CARGA",)),
    TipoDocumental("LEY HABEAS DATA", ("LEY HABEAS DATA", "HABEAS DATA")),
    #: Se imprime con el nombre entero -- "Liquidación del Consumo No registrado
    #: Pendiente Por Facturar" -- y también abreviado. Las dos formas delatan el
    #: mismo papel.
    TipoDocumental(
        "LIQUIDACION DEL CONSUMO",
        (
            "LIQUIDACION DEL CONSUMO NO REGISTRADO PENDIENTE POR FACTURAR",
            "LIQUIDACION DEL CONSUMO NO REGISTRADO",
            "LIQUIDACION DEL CONSUMO",
        ),
    ),
    TipoDocumental(
        "MATERIALES INCLUIDOS EN CADA ITEM DE INSTALACION Y CENSO DE CARGA",
        (
            "MATERIALES INCLUIDOS EN CADA ITEM DE INSTALACION Y CENSO DE CARGA",
            "MATERIALES INCLUIDOS EN CADA ITEM",
        ),
    ),
    TipoDocumental("NOTIFICACION DE ESTRATO", ("NOTIFICACION DE ESTRATO",)),
    TipoDocumental("NOTIFICACION PERSONAL", ("NOTIFICACION PERSONAL",)),
    TipoDocumental("NOTIFICACION PERSONAL ESCRITA", ("NOTIFICACION PERSONAL ESCRITA",)),
    TipoDocumental("NOTIFICACION PERSONAL RECLAMOS", ("NOTIFICACION PERSONAL RECLAMOS",)),
    TipoDocumental(
        "NOTIFICACION POR AVISO",
        ("NOTIFICACION POR AVISO", "AVISO DE NOTIFICACION"),
    ),
    #: Su propio tipo, y no un sinónimo del anterior como estaba. Son dos
    #: papeles distintos que además vienen seguidos: la publicación certifica
    #: que el aviso se fijó, y la notificación es lo que se le envió al
    #: usuario. Cada uno con su consecutivo. Leídos como el mismo tipo, la
    #: entrega mostraba dos archivos contiguos llamados igual, que es como se
    #: ve un documento partido por la mitad.
    TipoDocumental(
        "PUBLICACION DEL AVISO",
        ("PUBLICACION DEL AVISO", "PUBLICACION DE AVISO"),
    ),
    TipoDocumental("ORDEN DE SERVICIO", ("ORDEN DE SERVICIO",)),
    TipoDocumental("OTORGAMIENTO DE PODER", ("OTORGAMIENTO DE PODER",)),
    TipoDocumental("PAGARE", ("PAGARE",)),
    TipoDocumental("PAGO INCORRECTO", ("PAGO INCORRECTO",)),
    TipoDocumental("PAGO NO APLICADO", ("PAGOS NO APLICADOS", "PAGO NO APLICADO")),
    TipoDocumental("PAGO NO REPORTADO", ("PAGOS NO REPORTADOS", "PAGO NO REPORTADO")),
    TipoDocumental("PAZ Y SALVO", ("PAZ Y SALVO",)),
    TipoDocumental("PETICION", ("PETICION",)),
    TipoDocumental("PQR", ("PQR",)),
    TipoDocumental("PQR VERBALES", ("RECLAMO PQR VERBALES", "PQR VERBALES")),
    TipoDocumental("PROVISION DE SERVICIO", ("PROVISION DE SERVICIO",)),
    TipoDocumental(
        "PROYECCION Y AUTORIZACION PARA REFACTURACCION DE COMSUMOS",
        (
            "PROYECCION Y AUTORIZACION PARA REFACTURACCION DE COMSUMOS",
            "PROYECCION O AUTORIZACION PARA REFATURACCION DE COMSUMOS",
            "AUTORIZACION PARA REFACTURACION DE CONSUMOS",
            "REFACTURACION DE CONSUMOS",
        ),
    ),
    TipoDocumental("QUEJA", ("QUEJA",)),
    TipoDocumental("RECIBO", ("RECIBO",)),
    #: Sin "RECLAMACION" a propósito, y se probó a ponerla. El papel escribe
    #: "Asunto: Reclamación No. RE3120202200134" en la RESPUESTA a una
    #: reclamación, no en la reclamación: ese número es el del expediente, y
    #: leerlo como tipo bautizaba "RECLAMO" a los tres oficios que la
    #: contestan. Es el mismo modo de fallo que el código de caso -- nombra el
    #: asunto del que se habla, no el papel que se tiene delante.
    TipoDocumental("RECLAMO", ("RECLAMO",)),
    TipoDocumental(
        "RECLAMO POR CONSUMO ESTIMADO",
        ("RECLAMO POR CONSUMO ESTIMADO", "CONSUMO ESTIMADO"),
    ),
    TipoDocumental(
        "RECONOCIMIENTO DE DEUDA Y PROPUESTA DE ACUERDO DE PAGO",
        (
            "RECONOCIMIENTO DE DEUDA Y PROPUESTA DE ACUERDO DE PAGO",
            "RECONOCIMIENTO DE DEUDA",
        ),
    ),
    TipoDocumental("RECURSO DE QUEJA", ("RECURSOS DE QUEJAS", "RECURSO DE QUEJA")),
    TipoDocumental("RECURSO DE REPOSICION", ("RECURSO DE REPOSICION",)),
    TipoDocumental(
        "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
        (
            "RECURSO DE REPOSICION Y SUBSIDIARIAMENTE EL DE APELACION",
            "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION",
            "RECURSO DE REPOSICION Y EN SUBSIDIO EL DE APELACION",
            "REPOSICION Y EN SUBSIDIO APELACION",
        ),
    ),
    TipoDocumental("RECURSO EXTEMPORANEO", ("RECURSO EXTEMPORANEO",)),
    TipoDocumental("RESPUESTA RADICADO", ("RESPUESTA AL RADICADO", "RESPUESTA RADICADO")),
    TipoDocumental(
        "RETIRO DEFINITIVO DE SERVICIOS PUBLICOS DOMICILIARIOS",
        (
            "RETIRO DEFINITIVO DE SERVICIOS PUBLICOS DOMICILIARIOS",
            "RETIRO DEFINITIVO DEL SERVICIO",
        ),
    ),
    TipoDocumental("REVISION DE DEUDA", ("REVISION DE DEUDA",)),
    TipoDocumental("REVISION DE MEDIDOR", ("REVISION DEL MEDIDOR", "REVISION DE MEDIDOR")),
    TipoDocumental(
        "SOLICITUD DE ROMPIMIENTO DE SOLIDARIDAD",
        ("SOLICITUD DE ROMPIMIENTO DE SOLIDARIDAD", "ROMPIMIENTO DE SOLIDARIDAD"),
    ),
    TipoDocumental(
        "SOLICITUD DE SERVICIO ELECTRICO EN BAJA TENSION",
        (
            "SOLICITUD DE SERVICIO ELECTRICO EN BAJA TENSION",
            "SOLICITUD DE SERVICIO ELECTRICO",
        ),
    ),
    TipoDocumental(
        "SOLICITUD DESCUENTO SEGURO",
        ("SOLICITUD DE DESCUENTO DE SEGURO", "SOLICITUD DESCUENTO SEGURO"),
    ),
    TipoDocumental("SOPORTE", ("SOPORTE",)),
    TipoDocumental(
        "TALLER DE USO RESPONSABLE DE LA ENERGIA",
        ("TALLER DE USO RESPONSABLE DE LA ENERGIA", "USO RESPONSABLE DE LA ENERGIA"),
    ),
    TipoDocumental("TERMINACION DE CONTRATO", ("TERMINACION DE CONTRATO",)),
    #: Sin frases a propósito: "TMP" es una marca del sistema de gestión, no algo
    #: que ningún papel lleve impreso. Está en el catálogo porque el listado del
    #: cliente lo tiene y alguien puede querer ponerlo a mano; nunca se reconoce
    #: solo. Con tres letras, además, cualquier tolerancia lo encontraría dentro
    #: de una palabra corriente.
    TipoDocumental("TMP"),
    TipoDocumental(
        "TRASLADO POR COMPETENCIA",
        ("TRASLADO POR COMPETENCIAS", "TRASLADO POR COMPETENCIA", "TRASLADO DE COMPETENCIA"),
    ),
)

#: El catálogo por nombre, para que quien reciba un tipo escrito a mano pueda
#: comprobar que existe antes de que acabe en el nombre de un archivo.
POR_NOMBRE: dict[str, TipoDocumental] = {tipo.nombre: tipo for tipo in CATALOGO}

#: Todas las frases buscables, de la más larga a la más corta. El orden es la
#: regla de desempate y por eso se fija una vez aquí: entre "RECURSO DE
#: REPOSICION" y "RECURSO DE REPOSICION EN SUBSIDIO DE APELACION" gana la
#: segunda, que es la que distingue un recurso del otro.
FRASES: tuple[tuple[str, TipoDocumental], ...] = tuple(
    sorted(
        ((frase, tipo) for tipo in CATALOGO for frase in tipo.frases),
        key=lambda par: len(par[0]),
        reverse=True,
    )
)
