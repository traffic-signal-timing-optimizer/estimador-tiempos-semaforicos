-- Archivo generado por scripts/bd_esquema.py desde docs/bd/esquema.toml (versión 1.2.0-candidato).
-- No se edita a mano: se cambia el esquema y se vuelve a generar.

CREATE SCHEMA control;
COMMENT ON SCHEMA control IS 'Quién cargó qué, con qué huella, los hitos del procedimiento y las incidencias de integridad.';
CREATE SCHEMA caso;
COMMENT ON SCHEMA caso IS 'El cruce: movimientos, clases de vehículo, tramos, grupos de verde, plan vigente, aforos y calibración.';
CREATE SCHEMA experimento;
COMMENT ON SCHEMA experimento IS 'Familias y escenarios de demanda, su reparto en particiones y los protocolos de medición.';
CREATE SCHEMA simulacion;
COMMENT ON SCHEMA simulacion IS 'Lo que produce SUMO: planes, corridas, resultados, vehículos, eventos, colas, búsquedas, etiquetas y comparadores.';
CREATE SCHEMA aprendizaje;
COMMENT ON SCHEMA aprendizaje IS 'Conjuntos de entrenamiento, entrenamientos, métricas, modelos, selección y consultas al modelo.';
CREATE SCHEMA evaluacion;
COMMENT ON SCHEMA evaluacion IS 'Evaluación final: experimentos, comparaciones, diferencias emparejadas, indicadores y costos.';
CREATE SCHEMA vistas;
COMMENT ON SCHEMA vistas IS 'Vistas del panel y consultas.';

CREATE DOMAIN control.huella AS text CHECK (VALUE ~ '^[0-9a-f]{64}$');
COMMENT ON DOMAIN control.huella IS 'Huella SHA-256 en hexadecimal minúscula (64 caracteres).';

CREATE TABLE control.cargas (
    carga_id text NOT NULL,
    inicio timestamptz NOT NULL,
    fin timestamptz,
    estado text NOT NULL,
    comando jsonb NOT NULL,
    version_paquete text NOT NULL,
    commit_codigo text,
    arbol_limpio boolean,
    version_postgres text NOT NULL,
    version_esquema text NOT NULL,
    artefactos_leidos integer,
    artefactos_cargados integer,
    artefactos_rechazados integer,
    filas_por_tabla jsonb,
    huella_contenido control.huella,
    CONSTRAINT cargas_pk PRIMARY KEY (carga_id),
    CONSTRAINT cargas_estado_regla CHECK (estado IN ('running','completed','rejected','interrupted')),
    CONSTRAINT cargas_artefactos_leidos_regla CHECK (artefactos_leidos >= 0),
    CONSTRAINT cargas_artefactos_cargados_regla CHECK (artefactos_cargados >= 0),
    CONSTRAINT cargas_artefactos_rechazados_regla CHECK (artefactos_rechazados >= 0),
    CONSTRAINT cargas_fin_posterior CHECK (fin IS NULL OR fin >= inicio),
    CONSTRAINT cargas_en_curso_sin_fin CHECK ((estado = 'running') = (fin IS NULL))
);
COMMENT ON TABLE control.cargas IS 'Cada vez que el cargador escribe en la base.';
COMMENT ON COLUMN control.cargas.carga_id IS 'Identificador de la carga: fecha UTC de inicio y 8 caracteres aleatorios.';
COMMENT ON COLUMN control.cargas.inicio IS 'Momento en que empieza la carga.';
COMMENT ON COLUMN control.cargas.fin IS 'Momento en que termina; vacío mientras está en curso o si se interrumpió.';
COMMENT ON COLUMN control.cargas.estado IS 'running (en curso), completed (completa), rejected (rechazada) o interrupted (interrumpida).';
COMMENT ON COLUMN control.cargas.comando IS 'Argumentos del comando, sin rutas de la máquina.';
COMMENT ON COLUMN control.cargas.version_paquete IS 'Versión del paquete semaforo que cargó.';
COMMENT ON COLUMN control.cargas.commit_codigo IS 'Commit del código que cargó; vacío si no se pudo leer.';
COMMENT ON COLUMN control.cargas.arbol_limpio IS 'Si el código no tenía cambios sin commit; vacío si no se pudo saber.';
COMMENT ON COLUMN control.cargas.version_postgres IS 'Versión exacta del servidor.';
COMMENT ON COLUMN control.cargas.version_esquema IS 'Última migración aplicada.';
COMMENT ON COLUMN control.cargas.artefactos_leidos IS 'Archivos revisados.';
COMMENT ON COLUMN control.cargas.artefactos_cargados IS 'Archivos que entraron.';
COMMENT ON COLUMN control.cargas.artefactos_rechazados IS 'Archivos que no entraron, con motivo en artefactos o conflictos.';
COMMENT ON COLUMN control.cargas.filas_por_tabla IS 'Filas insertadas por tabla.';
COMMENT ON COLUMN control.cargas.huella_contenido IS 'Huella del contenido completo de la base al terminar (QA36).';

CREATE TABLE control.artefactos (
    artefacto_id text NOT NULL,
    raiz text NOT NULL,
    ruta_relativa text NOT NULL,
    tipo text NOT NULL,
    tamano_bytes bigint NOT NULL,
    sha256 control.huella NOT NULL,
    manifiesto_id text,
    estado text NOT NULL,
    alcance text NOT NULL,
    motivo text,
    registrado_en timestamptz NOT NULL,
    carga_id text NOT NULL,
    CONSTRAINT artefactos_pk PRIMARY KEY (artefacto_id),
    CONSTRAINT artefactos_unica_1 UNIQUE (raiz, ruta_relativa),
    CONSTRAINT artefactos_raiz_regla CHECK (raiz IN ('datos','repositorio')),
    CONSTRAINT artefactos_tamano_bytes_regla CHECK (tamano_bytes >= 0),
    CONSTRAINT artefactos_estado_regla CHECK (estado IN ('intact','unknown','not_loadable','rejected')),
    CONSTRAINT artefactos_alcance_regla CHECK (alcance IN ('global','escenarios','desconocido')),
    CONSTRAINT artefactos_motivo_si_no_intacto CHECK (estado = 'intact' OR motivo IS NOT NULL)
);
COMMENT ON TABLE control.artefactos IS 'Cada archivo que la base conoce, con su huella. Es el enlace de cada fila con su original.';
COMMENT ON COLUMN control.artefactos.artefacto_id IS 'Raíz y ruta, por ejemplo datos:ejecuciones/<run_id>/outputs/tripinfo.xml.';
COMMENT ON COLUMN control.artefactos.raiz IS 'datos (carpeta de datos) o repositorio (actas del repositorio de código).';
COMMENT ON COLUMN control.artefactos.ruta_relativa IS 'Ruta dentro de la raíz, con «/», sin la ruta de la máquina.';
COMMENT ON COLUMN control.artefactos.tipo IS 'Clase de archivo (lista controlada en el cargador): manifest, inputs_manifest, case, scenario, split, protocol, tripinfo, fcd, cohort, reconciliation, summary, timing, sumo_log, metrics, trace, label, coverage, comparators, parameters, replica, quality, model_manifest, model_file, response, evaluation, minutes, other.';
COMMENT ON COLUMN control.artefactos.tamano_bytes IS 'Tamaño del archivo. Unidad: bytes.';
COMMENT ON COLUMN control.artefactos.sha256 IS 'Huella del contenido, recalculada al cargar.';
COMMENT ON COLUMN control.artefactos.manifiesto_id IS 'Manifiesto que declara este archivo; vacío si es un manifiesto o un acta.';
COMMENT ON COLUMN control.artefactos.estado IS 'intact (huella coincide), unknown (sin manifiesto reconocido), not_loadable (no se pudo leer) o rejected (rechazado por conflicto).';
COMMENT ON COLUMN control.artefactos.alcance IS 'global, escenarios o desconocido. Los desconocidos quedan ocultos hasta clasificarlos.';
COMMENT ON COLUMN control.artefactos.motivo IS 'Por qué no está intact; vacío si lo está.';
COMMENT ON COLUMN control.artefactos.registrado_en IS 'Cuándo se registró.';
COMMENT ON COLUMN control.artefactos.carga_id IS 'Carga que escribió la fila.';

CREATE TABLE control.archivo_escenarios (
    artefacto_id text NOT NULL,
    escenario_id text NOT NULL,
    carga_id text NOT NULL,
    CONSTRAINT archivo_escenarios_pk PRIMARY KEY (artefacto_id, escenario_id)
);
COMMENT ON TABLE control.archivo_escenarios IS 'Escenarios a los que corresponde un archivo. Todos deben ser visibles para mostrar el archivo.';
COMMENT ON COLUMN control.archivo_escenarios.artefacto_id IS 'Archivo vinculado.';
COMMENT ON COLUMN control.archivo_escenarios.escenario_id IS 'Escenario vinculado.';
COMMENT ON COLUMN control.archivo_escenarios.carga_id IS 'Carga que escribió la fila.';

CREATE TABLE control.entornos (
    entorno_id control.huella NOT NULL,
    version_sumo text,
    version_python text NOT NULL,
    sistema_operativo text NOT NULL,
    commit_codigo text,
    codigo_modificado boolean,
    motivo_sin_commit text,
    librerias jsonb NOT NULL,
    ubicacion text,
    proveedor_nube text,
    tipo_maquina text,
    region text,
    procesador text,
    nucleos integer,
    memoria_gb double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT entornos_pk PRIMARY KEY (entorno_id),
    CONSTRAINT entornos_codigo_modificado_regla CHECK (codigo_modificado IS NULL OR commit_codigo IS NOT NULL),
    CONSTRAINT entornos_ubicacion_regla CHECK (ubicacion IS NULL OR ubicacion IN ('local','nube')),
    CONSTRAINT entornos_nucleos_regla CHECK (nucleos IS NULL OR nucleos > 0),
    CONSTRAINT entornos_memoria_gb_regla CHECK (memoria_gb IS NULL OR memoria_gb > 0),
    CONSTRAINT entornos_commit_o_motivo CHECK (commit_codigo IS NOT NULL OR motivo_sin_commit IS NOT NULL),
    CONSTRAINT entornos_nube_con_proveedor CHECK (ubicacion IS DISTINCT FROM 'nube' OR proveedor_nube IS NOT NULL)
);
COMMENT ON TABLE control.entornos IS 'Versiones y equipo con que se produjo un resultado.';
COMMENT ON COLUMN control.entornos.entorno_id IS 'Huella de los valores de esta fila.';
COMMENT ON COLUMN control.entornos.version_sumo IS 'Versión de SUMO; vacía en procesos sin SUMO.';
COMMENT ON COLUMN control.entornos.version_python IS 'Versión de Python.';
COMMENT ON COLUMN control.entornos.sistema_operativo IS 'Sistema operativo.';
COMMENT ON COLUMN control.entornos.commit_codigo IS 'Commit del proyecto con que corrió el proceso; vacío en las corridas anteriores a DEV31 F2.';
COMMENT ON COLUMN control.entornos.codigo_modificado IS 'Verdadero si, al correr, los archivos que git sigue tenían cambios sin confirmar (el commit no describe todo el código). Los archivos nuevos sin seguir no cuentan. Vacío si no hay commit.';
COMMENT ON COLUMN control.entornos.motivo_sin_commit IS 'Por qué falta el commit, por ejemplo «no registrado antes de DEV31».';
COMMENT ON COLUMN control.entornos.librerias IS 'Versiones de librerías relevantes; objeto vacío si no aplica.';
COMMENT ON COLUMN control.entornos.ubicacion IS 'Dónde corrió el proceso: «local» (la computadora del proyecto) o «nube» (cualquier proveedor). Se declara con SEMAFORO_UBICACION; sin declaración, local, salvo que el equipo se presente como máquina de una nube conocida. Vacío en las corridas anteriores a DEV31 F2 (no registrado). El manifiesto guarda «local» o «cloud»; la base lo traduce a «local» o «nube».';
COMMENT ON COLUMN control.entornos.proveedor_nube IS 'Proveedor de la nube cuando ubicacion = nube (por ejemplo AWS, Azure o Google Cloud), declarado con SEMAFORO_NUBE_PROVEEDOR o tomado del equipo; «no identificado» si no se sabe. Vacío si es local.';
COMMENT ON COLUMN control.entornos.tipo_maquina IS 'Tipo o modelo de la máquina virtual que reporta la nube (SEMAFORO_NUBE_TIPO_MAQUINA o el equipo). Vacío si es local o si no se conoce.';
COMMENT ON COLUMN control.entornos.region IS 'Región o centro de datos de la nube (SEMAFORO_NUBE_REGION). Vacío si es local o si no se declaró.';
COMMENT ON COLUMN control.entornos.procesador IS 'Modelo del procesador tal como lo reporta el sistema operativo (I7). Ejemplo: AMD Ryzen 9 4900HS with Radeon Graphics.';
COMMENT ON COLUMN control.entornos.nucleos IS 'Número de núcleos lógicos del equipo (I7).';
COMMENT ON COLUMN control.entornos.memoria_gb IS 'Memoria RAM total del equipo o de la máquina virtual, con un decimal (I7). Unidad: GB.';
COMMENT ON COLUMN control.entornos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN control.entornos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE control.hitos (
    hito_id text NOT NULL,
    tipo text NOT NULL,
    registrado_en timestamptz NOT NULL,
    protocolo_id text,
    particion_id text,
    modelo_id text,
    experimento_id text,
    seleccion_id text,
    huella_seleccion control.huella,
    huella_objeto control.huella NOT NULL,
    commit_codigo text,
    responsable text NOT NULL,
    notas text,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT hitos_pk PRIMARY KEY (hito_id),
    CONSTRAINT hitos_tipo_regla CHECK (tipo IN ('protocol_frozen','split_frozen','model_frozen','test_opened')),
    CONSTRAINT hitos_objeto_segun_tipo CHECK ((tipo = 'protocol_frozen' AND protocolo_id IS NOT NULL) OR (tipo = 'split_frozen' AND particion_id IS NOT NULL) OR (tipo = 'model_frozen' AND modelo_id IS NOT NULL AND seleccion_id IS NOT NULL AND huella_seleccion IS NOT NULL) OR (tipo = 'test_opened' AND experimento_id IS NOT NULL AND particion_id IS NOT NULL))
);
COMMENT ON TABLE control.hitos IS 'Pasos fechados del procedimiento que el jurado puede pedir: congelar el protocolo, la partición y el modelo, y abrir la prueba.';
COMMENT ON COLUMN control.hitos.hito_id IS 'Identificador del hito.';
COMMENT ON COLUMN control.hitos.tipo IS 'protocol_frozen, split_frozen, model_frozen o test_opened.';
COMMENT ON COLUMN control.hitos.registrado_en IS 'Cuándo se registró.';
COMMENT ON COLUMN control.hitos.protocolo_id IS 'Protocolo congelado (tipo protocol_frozen).';
COMMENT ON COLUMN control.hitos.particion_id IS 'Partición congelada, o cuya prueba se abre.';
COMMENT ON COLUMN control.hitos.modelo_id IS 'Modelo congelado (tipo model_frozen).';
COMMENT ON COLUMN control.hitos.experimento_id IS 'Experimento cuya prueba se abre (tipo test_opened).';
COMMENT ON COLUMN control.hitos.seleccion_id IS 'Selección fijada al congelar el modelo; no cambia con selecciones posteriores.';
COMMENT ON COLUMN control.hitos.huella_seleccion IS 'Huella de la selección fijada al congelar el modelo.';
COMMENT ON COLUMN control.hitos.huella_objeto IS 'Huella del objeto en el momento del hito.';
COMMENT ON COLUMN control.hitos.commit_codigo IS 'Commit que contiene el acta y la huella; da la fecha externa al subirse a GitHub.';
COMMENT ON COLUMN control.hitos.responsable IS 'Quién registró el hito.';
COMMENT ON COLUMN control.hitos.notas IS 'Aclaraciones del acta.';
COMMENT ON COLUMN control.hitos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN control.hitos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE control.conflictos (
    conflicto_id text NOT NULL,
    tipo text NOT NULL,
    tabla_destino text,
    clave text,
    huella_cargada control.huella,
    huella_nueva control.huella,
    detalle text NOT NULL,
    detectado_en timestamptz NOT NULL,
    decision text,
    decidido_en timestamptz,
    decidido_por text,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT conflictos_pk PRIMARY KEY (conflicto_id),
    CONSTRAINT conflictos_tipo_regla CHECK (tipo IN ('key_conflict','hash_mismatch','not_loadable','preliminary_now_test')),
    CONSTRAINT conflictos_decision_regla CHECK (decision IS NULL OR decision IN ('kept_existing','new_version','discarded','accepted_risk')),
    CONSTRAINT conflictos_decision_completa CHECK ((decision IS NULL) = (decidido_en IS NULL) AND (decision IS NULL) = (decidido_por IS NULL))
);
COMMENT ON TABLE control.conflictos IS 'Incidencias de integridad: una clave que llega con otro contenido, una huella que dejó de coincidir, un archivo que no se pudo cargar o un escenario preliminar que después aparece en prueba.';
COMMENT ON COLUMN control.conflictos.conflicto_id IS 'Identificador.';
COMMENT ON COLUMN control.conflictos.tipo IS 'key_conflict (clave repetida con otro contenido), hash_mismatch (la huella dejó de coincidir), not_loadable (no se pudo cargar) o preliminary_now_test (escenario preliminar asignado después a prueba).';
COMMENT ON COLUMN control.conflictos.tabla_destino IS 'Tabla donde chocó la clave.';
COMMENT ON COLUMN control.conflictos.clave IS 'Clave natural en conflicto.';
COMMENT ON COLUMN control.conflictos.huella_cargada IS 'Huella que ya estaba en la base.';
COMMENT ON COLUMN control.conflictos.huella_nueva IS 'Huella que llegó o que se recalculó.';
COMMENT ON COLUMN control.conflictos.detalle IS 'Explicación del problema.';
COMMENT ON COLUMN control.conflictos.detectado_en IS 'Cuándo se detectó.';
COMMENT ON COLUMN control.conflictos.decision IS 'kept_existing, new_version, discarded o accepted_risk; vacía mientras está pendiente.';
COMMENT ON COLUMN control.conflictos.decidido_en IS 'Cuándo se decidió.';
COMMENT ON COLUMN control.conflictos.decidido_por IS 'Quién decidió.';
COMMENT ON COLUMN control.conflictos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN control.conflictos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE control.replicas (
    replica_id text NOT NULL,
    run_id_a text NOT NULL,
    run_id_b text NOT NULL,
    creada_en timestamptz NOT NULL,
    semilla_a integer,
    semilla_b integer,
    entradas_iguales boolean NOT NULL,
    diferencias_entrada jsonb NOT NULL,
    tolerancia jsonb NOT NULL,
    archivos jsonb NOT NULL,
    veredicto text NOT NULL,
    motivos jsonb NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT replicas_pk PRIMARY KEY (replica_id),
    CONSTRAINT replicas_veredicto_regla CHECK (veredicto IN ('equivalent','different')),
    CONSTRAINT replicas_corridas_distintas CHECK (run_id_a <> run_id_b)
);
COMMENT ON TABLE control.replicas IS 'Comparación de una corrida con su réplica (QA09, I8).';
COMMENT ON COLUMN control.replicas.replica_id IS 'Identificador de la comparación.';
COMMENT ON COLUMN control.replicas.run_id_a IS 'Corrida original.';
COMMENT ON COLUMN control.replicas.run_id_b IS 'Corrida que la repite.';
COMMENT ON COLUMN control.replicas.creada_en IS 'Cuándo se comparó.';
COMMENT ON COLUMN control.replicas.semilla_a IS 'Semilla de la original.';
COMMENT ON COLUMN control.replicas.semilla_b IS 'Semilla de la réplica.';
COMMENT ON COLUMN control.replicas.entradas_iguales IS 'Si las entradas son idénticas.';
COMMENT ON COLUMN control.replicas.diferencias_entrada IS 'Entradas que difieren.';
COMMENT ON COLUMN control.replicas.tolerancia IS 'Tolerancia numérica usada.';
COMMENT ON COLUMN control.replicas.archivos IS 'Cada archivo comparado, con su regla y si coincide.';
COMMENT ON COLUMN control.replicas.veredicto IS 'equivalent (equivalentes) o different (distintas).';
COMMENT ON COLUMN control.replicas.motivos IS 'Motivos del veredicto.';
COMMENT ON COLUMN control.replicas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN control.replicas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.casos (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    origen text NOT NULL,
    descripcion text NOT NULL,
    estado_representacion text NOT NULL,
    red_ruta text,
    red_sha256 control.huella,
    tick_s double precision NOT NULL,
    ciclo_min_s double precision NOT NULL,
    ciclo_max_s double precision NOT NULL,
    politica_frontera text NOT NULL,
    evidencia_restricciones jsonb NOT NULL,
    huella_caso control.huella NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT casos_pk PRIMARY KEY (caso_id, caso_version),
    CONSTRAINT casos_origen_regla CHECK (origen IN ('synthetic','field')),
    CONSTRAINT casos_estado_representacion_regla CHECK (estado_representacion IN ('synthetic_fixture','unverified','calibrated','validated')),
    CONSTRAINT casos_tick_s_regla CHECK (tick_s > 0),
    CONSTRAINT casos_ciclo_min_s_regla CHECK (ciclo_min_s > 0),
    CONSTRAINT casos_ciclo_ordenado CHECK (ciclo_min_s <= ciclo_max_s),
    CONSTRAINT casos_red_completa CHECK ((red_ruta IS NULL) = (red_sha256 IS NULL))
);
COMMENT ON TABLE caso.casos IS 'Versión del cruce tal como se representa.';
COMMENT ON COLUMN caso.casos.caso_id IS 'Identificador del cruce, por ejemplo caso-001.';
COMMENT ON COLUMN caso.casos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.casos.origen IS 'synthetic (sintético) o field (de campo).';
COMMENT ON COLUMN caso.casos.descripcion IS 'Descripción del caso.';
COMMENT ON COLUMN caso.casos.estado_representacion IS 'synthetic_fixture, unverified, calibrated o validated.';
COMMENT ON COLUMN caso.casos.red_ruta IS 'Ruta de la red SUMO del caso.';
COMMENT ON COLUMN caso.casos.red_sha256 IS 'Huella de la red SUMO.';
COMMENT ON COLUMN caso.casos.tick_s IS 'Paso de tiempo de los planes. Unidad: s.';
COMMENT ON COLUMN caso.casos.ciclo_min_s IS 'Ciclo mínimo permitido. Unidad: s.';
COMMENT ON COLUMN caso.casos.ciclo_max_s IS 'Ciclo máximo permitido. Unidad: s.';
COMMENT ON COLUMN caso.casos.politica_frontera IS 'Cómo se tratan los semáforos vecinos.';
COMMENT ON COLUMN caso.casos.evidencia_restricciones IS 'Fuentes que sustentan las restricciones.';
COMMENT ON COLUMN caso.casos.huella_caso IS 'Huella del case.json, la que citan los manifiestos de entradas.';
COMMENT ON COLUMN caso.casos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.casos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.movimientos (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    movimiento_id text NOT NULL,
    orden integer NOT NULL,
    acceso text NOT NULL,
    carriles_entrada jsonb NOT NULL,
    aristas_salida jsonb NOT NULL,
    tls_id text NOT NULL,
    indices_enlace jsonb NOT NULL,
    flujo_min_vph double precision NOT NULL,
    flujo_max_vph double precision NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT movimientos_pk PRIMARY KEY (caso_id, caso_version, movimiento_id),
    CONSTRAINT movimientos_orden_regla CHECK (orden >= 0),
    CONSTRAINT movimientos_flujo_min_vph_regla CHECK (flujo_min_vph >= 0),
    CONSTRAINT movimientos_dominio_ordenado CHECK (flujo_min_vph <= flujo_max_vph)
);
COMMENT ON TABLE caso.movimientos IS 'Cada movimiento del cruce, con su acceso, carriles y dominio de demanda.';
COMMENT ON COLUMN caso.movimientos.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.movimientos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.movimientos.movimiento_id IS 'Código del movimiento, por ejemplo M07.';
COMMENT ON COLUMN caso.movimientos.orden IS 'Posición en la lista del caso; fija el orden de las entradas del modelo.';
COMMENT ON COLUMN caso.movimientos.acceso IS 'Acceso (entrada del cruce) del movimiento.';
COMMENT ON COLUMN caso.movimientos.carriles_entrada IS 'Carriles por los que entra.';
COMMENT ON COLUMN caso.movimientos.aristas_salida IS 'Calles por las que sale.';
COMMENT ON COLUMN caso.movimientos.tls_id IS 'Semáforo de SUMO que lo controla.';
COMMENT ON COLUMN caso.movimientos.indices_enlace IS 'Índices de señal del semáforo.';
COMMENT ON COLUMN caso.movimientos.flujo_min_vph IS 'Límite inferior del dominio de demanda. Unidad: veh/h.';
COMMENT ON COLUMN caso.movimientos.flujo_max_vph IS 'Límite superior del dominio de demanda. Unidad: veh/h.';
COMMENT ON COLUMN caso.movimientos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.movimientos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.tipos_vehiculo (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    clase_id text NOT NULL,
    orden integer NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT tipos_vehiculo_pk PRIMARY KEY (caso_id, caso_version, clase_id),
    CONSTRAINT tipos_vehiculo_orden_regla CHECK (orden >= 0)
);
COMMENT ON TABLE caso.tipos_vehiculo IS 'Clases de vehículo del caso.';
COMMENT ON COLUMN caso.tipos_vehiculo.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.tipos_vehiculo.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.tipos_vehiculo.clase_id IS 'Clase como la usa el caso: passenger (auto), motorcycle (moto), bus o truck (camión).';
COMMENT ON COLUMN caso.tipos_vehiculo.orden IS 'Posición en la lista; fija el orden de las proporciones en las entradas del modelo.';
COMMENT ON COLUMN caso.tipos_vehiculo.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.tipos_vehiculo.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.tramos (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    tramo_id text NOT NULL,
    orden integer NOT NULL,
    tipo text NOT NULL,
    minimo_s double precision NOT NULL,
    maximo_s double precision NOT NULL,
    estados jsonb NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT tramos_pk PRIMARY KEY (caso_id, caso_version, tramo_id),
    CONSTRAINT tramos_orden_regla CHECK (orden >= 0),
    CONSTRAINT tramos_tipo_regla CHECK (tipo IN ('variable','fixed')),
    CONSTRAINT tramos_minimo_s_regla CHECK (minimo_s >= 0),
    CONSTRAINT tramos_limites_ordenados CHECK (minimo_s <= maximo_s),
    CONSTRAINT tramos_fijo_sin_rango CHECK (tipo = 'variable' OR minimo_s = maximo_s)
);
COMMENT ON TABLE caso.tramos IS 'Tramos de la secuencia fija de fases, con sus límites.';
COMMENT ON COLUMN caso.tramos.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.tramos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.tramos.tramo_id IS 'Código del tramo, por ejemplo t5.';
COMMENT ON COLUMN caso.tramos.orden IS 'Posición en la secuencia.';
COMMENT ON COLUMN caso.tramos.tipo IS 'variable (lo ajusta el modelo) o fixed (fijo: ámbar o todo rojo).';
COMMENT ON COLUMN caso.tramos.minimo_s IS 'Duración mínima. Unidad: s.';
COMMENT ON COLUMN caso.tramos.maximo_s IS 'Duración máxima. Unidad: s.';
COMMENT ON COLUMN caso.tramos.estados IS 'Estado de cada semáforo durante el tramo.';
COMMENT ON COLUMN caso.tramos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.tramos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.grupos_verde (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    grupo_id text NOT NULL,
    minimo_s double precision NOT NULL,
    maximo_s double precision NOT NULL,
    proposito text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT grupos_verde_pk PRIMARY KEY (caso_id, caso_version, grupo_id),
    CONSTRAINT grupos_verde_minimo_s_regla CHECK (minimo_s >= 0),
    CONSTRAINT grupos_verde_proposito_regla CHECK (proposito IN ('vehicle','pedestrian')),
    CONSTRAINT grupos_verde_verde_ordenado CHECK (minimo_s <= maximo_s)
);
COMMENT ON TABLE caso.grupos_verde IS 'Grupos de verde: lo que debe recibir verde junto, con su mínimo y máximo.';
COMMENT ON COLUMN caso.grupos_verde.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.grupos_verde.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.grupos_verde.grupo_id IS 'Identificador del grupo.';
COMMENT ON COLUMN caso.grupos_verde.minimo_s IS 'Verde mínimo del grupo. Unidad: s.';
COMMENT ON COLUMN caso.grupos_verde.maximo_s IS 'Verde máximo del grupo. Unidad: s.';
COMMENT ON COLUMN caso.grupos_verde.proposito IS 'vehicle (vehicular) o pedestrian (peatonal).';
COMMENT ON COLUMN caso.grupos_verde.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.grupos_verde.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.grupo_tramo (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    grupo_id text NOT NULL,
    tramo_id text NOT NULL,
    orden integer NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT grupo_tramo_pk PRIMARY KEY (caso_id, caso_version, grupo_id, tramo_id),
    CONSTRAINT grupo_tramo_orden_regla CHECK (orden >= 0)
);
COMMENT ON TABLE caso.grupo_tramo IS 'Qué tramos dan verde a cada grupo.';
COMMENT ON COLUMN caso.grupo_tramo.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.grupo_tramo.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.grupo_tramo.grupo_id IS 'Grupo de verde.';
COMMENT ON COLUMN caso.grupo_tramo.tramo_id IS 'Tramo del grupo.';
COMMENT ON COLUMN caso.grupo_tramo.orden IS 'Posición del tramo dentro del grupo.';
COMMENT ON COLUMN caso.grupo_tramo.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.grupo_tramo.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.planes_observados (
    plan_observado_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    plan_id control.huella NOT NULL,
    fuente text NOT NULL,
    variacion_horaria text NOT NULL,
    confirmado_por text NOT NULL,
    carpeta_programa text NOT NULL,
    reglas_incumplidas jsonb NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT planes_observados_pk PRIMARY KEY (plan_observado_id)
);
COMMENT ON TABLE caso.planes_observados IS 'Plan vigente del semáforo real, con su fuente.';
COMMENT ON COLUMN caso.planes_observados.plan_observado_id IS 'Caso y carpeta del programa, por ejemplo caso-001:20261031T041338Z_63437585.';
COMMENT ON COLUMN caso.planes_observados.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.planes_observados.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.planes_observados.plan_id IS 'Duraciones del plan vigente.';
COMMENT ON COLUMN caso.planes_observados.fuente IS 'De dónde sale el plan.';
COMMENT ON COLUMN caso.planes_observados.variacion_horaria IS 'Si cambia por hora o día.';
COMMENT ON COLUMN caso.planes_observados.confirmado_por IS 'Quién lo confirmó y cuándo.';
COMMENT ON COLUMN caso.planes_observados.carpeta_programa IS 'Carpeta del programa derivado en datos/derivados/programas.';
COMMENT ON COLUMN caso.planes_observados.reglas_incumplidas IS 'Reglas del caso que incumple; lista vacía si cumple todas.';
COMMENT ON COLUMN caso.planes_observados.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.planes_observados.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.aforos (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    observacion_id text NOT NULL,
    movimiento_id text NOT NULL,
    clase_id text NOT NULL,
    fuente_id text NOT NULL,
    origen text NOT NULL,
    inicio timestamptz NOT NULL,
    fin timestamptz NOT NULL,
    conteo integer NOT NULL,
    estado_calidad text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT aforos_pk PRIMARY KEY (caso_id, caso_version, observacion_id, movimiento_id, clase_id),
    CONSTRAINT aforos_origen_regla CHECK (origen IN ('synthetic','field')),
    CONSTRAINT aforos_conteo_regla CHECK (conteo >= 0),
    CONSTRAINT aforos_periodo_valido CHECK (fin > inicio)
);
COMMENT ON TABLE caso.aforos IS 'Conteos de vehículos por movimiento, periodo y clase (I1).';
COMMENT ON COLUMN caso.aforos.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.aforos.caso_version IS 'Versión del caso con que se importó.';
COMMENT ON COLUMN caso.aforos.observacion_id IS 'Identificador de la observación (periodo contado).';
COMMENT ON COLUMN caso.aforos.movimiento_id IS 'Movimiento contado.';
COMMENT ON COLUMN caso.aforos.clase_id IS 'Clase de vehículo.';
COMMENT ON COLUMN caso.aforos.fuente_id IS 'Video o registro de procedencia.';
COMMENT ON COLUMN caso.aforos.origen IS 'synthetic o field.';
COMMENT ON COLUMN caso.aforos.inicio IS 'Inicio del periodo, con zona horaria.';
COMMENT ON COLUMN caso.aforos.fin IS 'Fin del periodo.';
COMMENT ON COLUMN caso.aforos.conteo IS 'Vehículos contados; nunca negativo. Un cero es un cero observado, no un faltante. Unidad: veh.';
COMMENT ON COLUMN caso.aforos.estado_calidad IS 'Estado del conteo; hoy solo observed (otros valores pendientes del PO).';
COMMENT ON COLUMN caso.aforos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.aforos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.aforos_control (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    observacion_id text NOT NULL,
    movimiento_id text NOT NULL,
    clase_id text NOT NULL,
    fuente_id text NOT NULL,
    origen text NOT NULL,
    inicio timestamptz NOT NULL,
    fin timestamptz NOT NULL,
    conteo integer NOT NULL,
    estado_calidad text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT aforos_control_pk PRIMARY KEY (caso_id, caso_version, observacion_id, movimiento_id, clase_id),
    CONSTRAINT aforos_control_origen_regla CHECK (origen IN ('synthetic','field')),
    CONSTRAINT aforos_control_conteo_regla CHECK (conteo >= 0),
    CONSTRAINT aforos_control_periodo_valido CHECK (fin > inicio)
);
COMMENT ON TABLE caso.aforos_control IS 'Conteos manuales de control, para medir el error de los aforos (I1).';
COMMENT ON COLUMN caso.aforos_control.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.aforos_control.caso_version IS 'Versión del caso con que se importó.';
COMMENT ON COLUMN caso.aforos_control.observacion_id IS 'Identificador de la observación de control.';
COMMENT ON COLUMN caso.aforos_control.movimiento_id IS 'Movimiento contado.';
COMMENT ON COLUMN caso.aforos_control.clase_id IS 'Clase de vehículo.';
COMMENT ON COLUMN caso.aforos_control.fuente_id IS 'Quién o qué hizo el conteo de control.';
COMMENT ON COLUMN caso.aforos_control.origen IS 'synthetic o field.';
COMMENT ON COLUMN caso.aforos_control.inicio IS 'Inicio del periodo.';
COMMENT ON COLUMN caso.aforos_control.fin IS 'Fin del periodo.';
COMMENT ON COLUMN caso.aforos_control.conteo IS 'Vehículos contados a mano. Unidad: veh.';
COMMENT ON COLUMN caso.aforos_control.estado_calidad IS 'Estado del conteo.';
COMMENT ON COLUMN caso.aforos_control.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.aforos_control.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.calidad_aforos (
    reporte_id text NOT NULL,
    fila integer NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    observacion_id text,
    fuente_control_id text,
    inicio timestamptz NOT NULL,
    fin timestamptz NOT NULL,
    movimiento_id text NOT NULL,
    clase_id text NOT NULL,
    observado integer,
    control integer,
    error_absoluto integer,
    error_relativo double precision,
    motivo_error_relativo text,
    estado text NOT NULL,
    motivo_estado text,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT calidad_aforos_pk PRIMARY KEY (reporte_id, fila),
    CONSTRAINT calidad_aforos_fila_regla CHECK (fila >= 1),
    CONSTRAINT calidad_aforos_estado_regla CHECK (estado IN ('comparable','only_observed','only_control','not_comparable','excluded')),
    CONSTRAINT calidad_aforos_relativo_o_motivo CHECK (estado <> 'comparable' OR error_relativo IS NOT NULL OR motivo_error_relativo IS NOT NULL)
);
COMMENT ON TABLE caso.calidad_aforos IS 'Comparación de cada aforo con su control: error absoluto y relativo, y estado (I1).';
COMMENT ON COLUMN caso.calidad_aforos.reporte_id IS 'Carpeta del reporte de calidad.';
COMMENT ON COLUMN caso.calidad_aforos.fila IS 'Número de fila en calidad.csv.';
COMMENT ON COLUMN caso.calidad_aforos.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.calidad_aforos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.calidad_aforos.observacion_id IS 'Observación comparada; vacía si solo hay control.';
COMMENT ON COLUMN caso.calidad_aforos.fuente_control_id IS 'Fuente del control; vacía si solo hay observación.';
COMMENT ON COLUMN caso.calidad_aforos.inicio IS 'Inicio del periodo.';
COMMENT ON COLUMN caso.calidad_aforos.fin IS 'Fin del periodo.';
COMMENT ON COLUMN caso.calidad_aforos.movimiento_id IS 'Movimiento.';
COMMENT ON COLUMN caso.calidad_aforos.clase_id IS 'Clase de vehículo.';
COMMENT ON COLUMN caso.calidad_aforos.observado IS 'Conteo del aforo; vacío si no hay. Unidad: veh.';
COMMENT ON COLUMN caso.calidad_aforos.control IS 'Conteo de control; vacío si no hay. Unidad: veh.';
COMMENT ON COLUMN caso.calidad_aforos.error_absoluto IS 'Observado menos control. Unidad: veh.';
COMMENT ON COLUMN caso.calidad_aforos.error_relativo IS 'Error absoluto entre el control; vacío si el control es cero. Unidad: fracción.';
COMMENT ON COLUMN caso.calidad_aforos.motivo_error_relativo IS 'Por qué el error relativo está vacío.';
COMMENT ON COLUMN caso.calidad_aforos.estado IS 'comparable, only_observed, only_control, not_comparable o excluded.';
COMMENT ON COLUMN caso.calidad_aforos.motivo_estado IS 'Motivo del estado, por ejemplo de la exclusión.';
COMMENT ON COLUMN caso.calidad_aforos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.calidad_aforos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.reportes_calidad (
    reporte_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    observado_sha256 control.huella NOT NULL,
    control_sha256 control.huella NOT NULL,
    ventana_inicio timestamptz NOT NULL,
    ventana_fin timestamptz NOT NULL,
    ventana_declarada boolean NOT NULL,
    ventana_s double precision NOT NULL,
    cubierto_s double precision NOT NULL,
    cobertura double precision NOT NULL,
    cumple_minimo boolean,
    cobertura_por_movimiento jsonb NOT NULL,
    huecos jsonb NOT NULL,
    solapes jsonb NOT NULL,
    fuera_de_ventana jsonb NOT NULL,
    ventanas_por_estado jsonb NOT NULL,
    faltantes jsonb NOT NULL,
    exclusiones jsonb NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT reportes_calidad_pk PRIMARY KEY (reporte_id),
    CONSTRAINT reportes_calidad_cobertura_regla CHECK (cobertura BETWEEN 0 AND 1)
);
COMMENT ON TABLE caso.reportes_calidad IS 'Resumen de cada reporte de calidad: ventana, cobertura por movimiento, huecos, faltantes y exclusiones (I1).';
COMMENT ON COLUMN caso.reportes_calidad.reporte_id IS 'Carpeta del reporte.';
COMMENT ON COLUMN caso.reportes_calidad.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.reportes_calidad.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.reportes_calidad.observado_sha256 IS 'Huella del archivo de aforos.';
COMMENT ON COLUMN caso.reportes_calidad.control_sha256 IS 'Huella del archivo de control.';
COMMENT ON COLUMN caso.reportes_calidad.ventana_inicio IS 'Inicio de la ventana evaluada.';
COMMENT ON COLUMN caso.reportes_calidad.ventana_fin IS 'Fin de la ventana evaluada.';
COMMENT ON COLUMN caso.reportes_calidad.ventana_declarada IS 'Si la ventana la declaró el usuario o se dedujo.';
COMMENT ON COLUMN caso.reportes_calidad.ventana_s IS 'Duración de la ventana. Unidad: s.';
COMMENT ON COLUMN caso.reportes_calidad.cubierto_s IS 'Tiempo con datos. Unidad: s.';
COMMENT ON COLUMN caso.reportes_calidad.cobertura IS 'Cubierto entre ventana. Unidad: fracción.';
COMMENT ON COLUMN caso.reportes_calidad.cumple_minimo IS 'Si alcanza la cobertura mínima; vacío si no hay mínimo fijado.';
COMMENT ON COLUMN caso.reportes_calidad.cobertura_por_movimiento IS 'Cobertura de cada movimiento.';
COMMENT ON COLUMN caso.reportes_calidad.huecos IS 'Intervalos sin datos.';
COMMENT ON COLUMN caso.reportes_calidad.solapes IS 'Observaciones que se solapan.';
COMMENT ON COLUMN caso.reportes_calidad.fuera_de_ventana IS 'Observaciones fuera de la ventana.';
COMMENT ON COLUMN caso.reportes_calidad.ventanas_por_estado IS 'Cantidad de filas por estado.';
COMMENT ON COLUMN caso.reportes_calidad.faltantes IS 'Combinaciones esperadas sin conteo.';
COMMENT ON COLUMN caso.reportes_calidad.exclusiones IS 'Filas excluidas, con su motivo.';
COMMENT ON COLUMN caso.reportes_calidad.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.reportes_calidad.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.calibracion_intentos (
    intento_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    numero integer NOT NULL,
    conjunto text NOT NULL,
    parametros jsonb NOT NULL,
    congelado boolean NOT NULL,
    corridas jsonb NOT NULL,
    registrado_en timestamptz NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT calibracion_intentos_pk PRIMARY KEY (intento_id),
    CONSTRAINT calibracion_intentos_numero_regla CHECK (numero >= 1),
    CONSTRAINT calibracion_intentos_conjunto_regla CHECK (conjunto IN ('calibration','validation'))
);
COMMENT ON TABLE caso.calibracion_intentos IS 'Cada intento de ajustar los parámetros de SUMO, separado entre ajuste y validación (I2).';
COMMENT ON COLUMN caso.calibracion_intentos.intento_id IS 'Identificador del intento.';
COMMENT ON COLUMN caso.calibracion_intentos.caso_id IS 'Caso.';
COMMENT ON COLUMN caso.calibracion_intentos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN caso.calibracion_intentos.numero IS 'Orden del intento.';
COMMENT ON COLUMN caso.calibracion_intentos.conjunto IS 'calibration (ajuste) o validation (comprobación); nunca se mezclan.';
COMMENT ON COLUMN caso.calibracion_intentos.parametros IS 'Cada parámetro con su valor, rango, valor inicial, fuente y justificación.';
COMMENT ON COLUMN caso.calibracion_intentos.congelado IS 'Si es la configuración final congelada.';
COMMENT ON COLUMN caso.calibracion_intentos.corridas IS 'run_id de las corridas usadas.';
COMMENT ON COLUMN caso.calibracion_intentos.registrado_en IS 'Cuándo se hizo el intento.';
COMMENT ON COLUMN caso.calibracion_intentos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.calibracion_intentos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE caso.calibracion_contraste (
    intento_id text NOT NULL,
    variable text NOT NULL,
    metrica text NOT NULL,
    alcance text NOT NULL,
    unidad text NOT NULL,
    observado double precision,
    simulado double precision,
    error double precision,
    error_maximo double precision,
    cumple boolean,
    evidencia_piloto text,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT calibracion_contraste_pk PRIMARY KEY (intento_id, variable, metrica, alcance),
    CONSTRAINT calibracion_contraste_variable_regla CHECK (variable IN ('volume','queue','travel_time'))
);
COMMENT ON TABLE caso.calibracion_contraste IS 'Observado frente a simulado por variable, con el criterio fijado antes (I2).';
COMMENT ON COLUMN caso.calibracion_contraste.intento_id IS 'Intento evaluado.';
COMMENT ON COLUMN caso.calibracion_contraste.variable IS 'volume (volumen), queue (cola) o travel_time (tiempo de recorrido).';
COMMENT ON COLUMN caso.calibracion_contraste.metrica IS 'Métrica de comparación, por ejemplo GEH o error relativo.';
COMMENT ON COLUMN caso.calibracion_contraste.alcance IS 'Movimiento, acceso o periodo comparado.';
COMMENT ON COLUMN caso.calibracion_contraste.unidad IS 'Unidad de la variable.';
COMMENT ON COLUMN caso.calibracion_contraste.observado IS 'Valor de campo.';
COMMENT ON COLUMN caso.calibracion_contraste.simulado IS 'Valor de SUMO.';
COMMENT ON COLUMN caso.calibracion_contraste.error IS 'Error según la métrica.';
COMMENT ON COLUMN caso.calibracion_contraste.error_maximo IS 'Error máximo admitido por el protocolo.';
COMMENT ON COLUMN caso.calibracion_contraste.cumple IS 'Si cumple el criterio; vacío si no hay criterio.';
COMMENT ON COLUMN caso.calibracion_contraste.evidencia_piloto IS 'Evidencia del piloto que justifica el criterio.';
COMMENT ON COLUMN caso.calibracion_contraste.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN caso.calibracion_contraste.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE experimento.familias (
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    familia_id text NOT NULL,
    origen text NOT NULL,
    variantes integer,
    semillas integer,
    rangos_demanda jsonb,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT familias_pk PRIMARY KEY (caso_id, caso_version, familia_id),
    CONSTRAINT familias_origen_regla CHECK (origen IN ('synthetic','field_derived')),
    CONSTRAINT familias_variantes_regla CHECK (variantes IS NULL OR variantes >= 1),
    CONSTRAINT familias_semillas_regla CHECK (semillas IS NULL OR semillas >= 1)
);
COMMENT ON TABLE experimento.familias IS 'Familias (grupos) de escenarios: un patrón de demanda con sus variantes.';
COMMENT ON COLUMN experimento.familias.caso_id IS 'Caso.';
COMMENT ON COLUMN experimento.familias.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN experimento.familias.familia_id IS 'Identificador del grupo de escenarios.';
COMMENT ON COLUMN experimento.familias.origen IS 'synthetic o field_derived.';
COMMENT ON COLUMN experimento.familias.variantes IS 'Variantes de flujo que genera la familia; vacío si no hay especificación.';
COMMENT ON COLUMN experimento.familias.semillas IS 'Semillas de llegada por variante.';
COMMENT ON COLUMN experimento.familias.rangos_demanda IS 'Rango de flujo y composición por movimiento.';
COMMENT ON COLUMN experimento.familias.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN experimento.familias.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE experimento.escenarios (
    escenario_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    familia_id text NOT NULL,
    origen text NOT NULL,
    preliminar boolean NOT NULL,
    request_id text NOT NULL,
    origen_solicitud text NOT NULL,
    inicio_observacion timestamptz NOT NULL,
    fin_observacion timestamptz NOT NULL,
    fuentes jsonb NOT NULL,
    politica_frontera text NOT NULL,
    calentamiento_s double precision NOT NULL,
    medicion_s double precision NOT NULL,
    vaciado_max_s double precision NOT NULL,
    semilla_demanda integer NOT NULL,
    demanda_ruta text,
    demanda_sha256 control.huella,
    huella_escenario control.huella NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT escenarios_pk PRIMARY KEY (escenario_id),
    CONSTRAINT escenarios_unica_1 UNIQUE (escenario_id, familia_id),
    CONSTRAINT escenarios_origen_regla CHECK (origen IN ('synthetic','field_derived')),
    CONSTRAINT escenarios_origen_solicitud_regla CHECK (origen_solicitud IN ('synthetic','field')),
    CONSTRAINT escenarios_calentamiento_s_regla CHECK (calentamiento_s >= 0),
    CONSTRAINT escenarios_medicion_s_regla CHECK (medicion_s > 0),
    CONSTRAINT escenarios_vaciado_max_s_regla CHECK (vaciado_max_s >= 0),
    CONSTRAINT escenarios_demanda_completa CHECK ((demanda_ruta IS NULL) = (demanda_sha256 IS NULL))
);
COMMENT ON TABLE experimento.escenarios IS 'Un escenario de demanda: familia, semilla, ventana de medición y origen.';
COMMENT ON COLUMN experimento.escenarios.escenario_id IS 'Identificador, por ejemplo ESC-SINT-001.';
COMMENT ON COLUMN experimento.escenarios.caso_id IS 'Caso.';
COMMENT ON COLUMN experimento.escenarios.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN experimento.escenarios.familia_id IS 'Familia (grupo) del escenario.';
COMMENT ON COLUMN experimento.escenarios.origen IS 'synthetic o field_derived.';
COMMENT ON COLUMN experimento.escenarios.preliminar IS 'Verdadero si se cargó sin partición congelada, con autorización explícita en la carga.';
COMMENT ON COLUMN experimento.escenarios.request_id IS 'Solicitud de demanda del escenario.';
COMMENT ON COLUMN experimento.escenarios.origen_solicitud IS 'synthetic o field.';
COMMENT ON COLUMN experimento.escenarios.inicio_observacion IS 'Inicio del periodo que representa.';
COMMENT ON COLUMN experimento.escenarios.fin_observacion IS 'Fin del periodo que representa.';
COMMENT ON COLUMN experimento.escenarios.fuentes IS 'Fuentes de la demanda.';
COMMENT ON COLUMN experimento.escenarios.politica_frontera IS 'Política de frontera.';
COMMENT ON COLUMN experimento.escenarios.calentamiento_s IS 'Arranque que no se mide. Unidad: s.';
COMMENT ON COLUMN experimento.escenarios.medicion_s IS 'Intervalo medido. Unidad: s.';
COMMENT ON COLUMN experimento.escenarios.vaciado_max_s IS 'Tiempo máximo para que terminen los vehículos. Unidad: s.';
COMMENT ON COLUMN experimento.escenarios.semilla_demanda IS 'Semilla con la que se generó la demanda.';
COMMENT ON COLUMN experimento.escenarios.demanda_ruta IS 'Archivo de demanda materializada, si existe.';
COMMENT ON COLUMN experimento.escenarios.demanda_sha256 IS 'Huella de ese archivo.';
COMMENT ON COLUMN experimento.escenarios.huella_escenario IS 'Huella del escenario completo.';
COMMENT ON COLUMN experimento.escenarios.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN experimento.escenarios.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE experimento.demanda (
    escenario_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    movimiento_id text NOT NULL,
    clase_id text NOT NULL,
    flujo_vph double precision NOT NULL,
    proporcion double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT demanda_pk PRIMARY KEY (escenario_id, movimiento_id, clase_id),
    CONSTRAINT demanda_flujo_vph_regla CHECK (flujo_vph >= 0),
    CONSTRAINT demanda_proporcion_regla CHECK (proporcion IS NULL OR proporcion BETWEEN 0 AND 1),
    CONSTRAINT demanda_cero_sin_composicion CHECK ((flujo_vph = 0) = (proporcion IS NULL))
);
COMMENT ON TABLE experimento.demanda IS 'Demanda de cada movimiento y clase en un escenario. Es la entrada del modelo.';
COMMENT ON COLUMN experimento.demanda.escenario_id IS 'Escenario.';
COMMENT ON COLUMN experimento.demanda.caso_id IS 'Caso.';
COMMENT ON COLUMN experimento.demanda.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN experimento.demanda.movimiento_id IS 'Movimiento.';
COMMENT ON COLUMN experimento.demanda.clase_id IS 'Clase de vehículo; si el flujo es cero, una fila por clase del caso.';
COMMENT ON COLUMN experimento.demanda.flujo_vph IS 'Demanda total del movimiento (se repite en cada clase). Unidad: veh/h.';
COMMENT ON COLUMN experimento.demanda.proporcion IS 'Parte del flujo de esta clase; vacía si el flujo es cero (composición no aplica). Unidad: fracción.';
COMMENT ON COLUMN experimento.demanda.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN experimento.demanda.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE experimento.particiones (
    particion_id text NOT NULL,
    politica text NOT NULL,
    semilla integer NOT NULL,
    congelada boolean NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT particiones_pk PRIMARY KEY (particion_id),
    CONSTRAINT particiones_semilla_regla CHECK (semilla >= 0),
    CONSTRAINT particiones_congelada_regla CHECK (congelada)
);
COMMENT ON TABLE experimento.particiones IS 'Particiones congeladas del conjunto de escenarios.';
COMMENT ON COLUMN experimento.particiones.particion_id IS 'Identificador.';
COMMENT ON COLUMN experimento.particiones.politica IS 'Política de reparto usada.';
COMMENT ON COLUMN experimento.particiones.semilla IS 'Semilla del reparto.';
COMMENT ON COLUMN experimento.particiones.congelada IS 'Siempre verdadera: una partición sin congelar no se carga.';
COMMENT ON COLUMN experimento.particiones.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN experimento.particiones.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE experimento.asignaciones (
    particion_id text NOT NULL,
    escenario_id text NOT NULL,
    familia_id text NOT NULL,
    asignacion text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT asignaciones_pk PRIMARY KEY (particion_id, escenario_id),
    CONSTRAINT asignaciones_unica_1 UNIQUE (escenario_id),
    CONSTRAINT asignaciones_asignacion_regla CHECK (asignacion IN ('train','validation','test'))
);
COMMENT ON TABLE experimento.asignaciones IS 'A qué parte de la partición va cada escenario (entrenamiento, validación o prueba). Es la base del cegado.';
COMMENT ON COLUMN experimento.asignaciones.particion_id IS 'Partición.';
COMMENT ON COLUMN experimento.asignaciones.escenario_id IS 'Escenario.';
COMMENT ON COLUMN experimento.asignaciones.familia_id IS 'Familia del escenario.';
COMMENT ON COLUMN experimento.asignaciones.asignacion IS 'train (entrenamiento), validation (validación) o test (prueba).';
COMMENT ON COLUMN experimento.asignaciones.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN experimento.asignaciones.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE experimento.protocolos (
    protocolo_id text NOT NULL,
    estado text NOT NULL,
    proposito text NOT NULL,
    definicion_metrica text NOT NULL,
    politica_cohorte text NOT NULL,
    politica_censura text NOT NULL,
    regla_censura_alternativa text,
    presupuesto_busqueda integer NOT NULL,
    limite_intentos integer NOT NULL,
    finalistas integer NOT NULL,
    epsilon_empate_s double precision NOT NULL,
    umbral_cola_mps double precision NOT NULL,
    umbral_detencion_mps double precision NOT NULL,
    muestreo_cola_s double precision NOT NULL,
    carriles_zona jsonb NOT NULL,
    nivel_confianza double precision NOT NULL,
    remuestreos_bootstrap integer NOT NULL,
    margen_aceptacion_s double precision,
    tolerancia_error_conteo double precision,
    tolerancia_ajuste_simulacion double precision,
    referencia_aprobacion text,
    criterios_calibracion jsonb NOT NULL,
    agregacion_grupos text NOT NULL,
    pesos_grupos_ruta text,
    politica_reajuste text NOT NULL,
    tolerancia_numerica double precision NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT protocolos_pk PRIMARY KEY (protocolo_id),
    CONSTRAINT protocolos_estado_regla CHECK (estado IN ('draft','frozen')),
    CONSTRAINT protocolos_proposito_regla CHECK (proposito IN ('synthetic_fixture','main_experiment')),
    CONSTRAINT protocolos_politica_censura_regla CHECK (politica_censura IN ('complete_cohort_or_no_label','approved_alternative')),
    CONSTRAINT protocolos_presupuesto_busqueda_regla CHECK (presupuesto_busqueda >= 0),
    CONSTRAINT protocolos_limite_intentos_regla CHECK (limite_intentos >= 0),
    CONSTRAINT protocolos_finalistas_regla CHECK (finalistas >= 0),
    CONSTRAINT protocolos_epsilon_empate_s_regla CHECK (epsilon_empate_s >= 0),
    CONSTRAINT protocolos_umbral_cola_mps_regla CHECK (umbral_cola_mps >= 0),
    CONSTRAINT protocolos_umbral_detencion_mps_regla CHECK (umbral_detencion_mps >= 0),
    CONSTRAINT protocolos_muestreo_cola_s_regla CHECK (muestreo_cola_s > 0),
    CONSTRAINT protocolos_nivel_confianza_regla CHECK (nivel_confianza > 0 AND nivel_confianza < 1),
    CONSTRAINT protocolos_remuestreos_bootstrap_regla CHECK (remuestreos_bootstrap >= 0),
    CONSTRAINT protocolos_agregacion_grupos_regla CHECK (agregacion_grupos IN ('equal_group_weight','declared_field_weights')),
    CONSTRAINT protocolos_politica_reajuste_regla CHECK (politica_reajuste IN ('train_only','train_plus_validation_after_selection')),
    CONSTRAINT protocolos_tolerancia_numerica_regla CHECK (tolerancia_numerica >= 0)
);
COMMENT ON TABLE experimento.protocolos IS 'Reglas de medición, búsqueda y decisión fijadas antes del experimento.';
COMMENT ON COLUMN experimento.protocolos.protocolo_id IS 'Identificador.';
COMMENT ON COLUMN experimento.protocolos.estado IS 'draft (borrador) o frozen (congelado). La fecha de congelamiento está en hitos.';
COMMENT ON COLUMN experimento.protocolos.proposito IS 'synthetic_fixture (desarrollo sintético) o main_experiment (experimento principal).';
COMMENT ON COLUMN experimento.protocolos.definicion_metrica IS 'Qué se mide como demora, cola y detención.';
COMMENT ON COLUMN experimento.protocolos.politica_cohorte IS 'Qué vehículos forman la cohorte medida.';
COMMENT ON COLUMN experimento.protocolos.politica_censura IS 'complete_cohort_or_no_label o approved_alternative.';
COMMENT ON COLUMN experimento.protocolos.regla_censura_alternativa IS 'Regla aprobada si no es la de cohorte completa.';
COMMENT ON COLUMN experimento.protocolos.presupuesto_busqueda IS 'Candidatos que consumen presupuesto.';
COMMENT ON COLUMN experimento.protocolos.limite_intentos IS 'Máximo de planes generados.';
COMMENT ON COLUMN experimento.protocolos.finalistas IS 'Candidatos que pasan a la reevaluación.';
COMMENT ON COLUMN experimento.protocolos.epsilon_empate_s IS 'Diferencia de demora bajo la que hay empate. Unidad: s.';
COMMENT ON COLUMN experimento.protocolos.umbral_cola_mps IS 'Velocidad bajo la que un vehículo está en cola. Unidad: m/s.';
COMMENT ON COLUMN experimento.protocolos.umbral_detencion_mps IS 'Velocidad bajo la que cuenta una detención. Unidad: m/s.';
COMMENT ON COLUMN experimento.protocolos.muestreo_cola_s IS 'Cada cuánto se mide la cola. Unidad: s.';
COMMENT ON COLUMN experimento.protocolos.carriles_zona IS 'Carriles de la zona medida.';
COMMENT ON COLUMN experimento.protocolos.nivel_confianza IS 'Nivel de los intervalos de confianza. Unidad: fracción.';
COMMENT ON COLUMN experimento.protocolos.remuestreos_bootstrap IS 'Remuestreos para los intervalos.';
COMMENT ON COLUMN experimento.protocolos.margen_aceptacion_s IS 'Margen admitido frente a la búsqueda; vacío mientras no se fije. Unidad: s.';
COMMENT ON COLUMN experimento.protocolos.tolerancia_error_conteo IS 'Tolerancia de error de aforos (I1).';
COMMENT ON COLUMN experimento.protocolos.tolerancia_ajuste_simulacion IS 'Tolerancia de ajuste de SUMO (I2).';
COMMENT ON COLUMN experimento.protocolos.referencia_aprobacion IS 'Acta o aprobación que lo respalda.';
COMMENT ON COLUMN experimento.protocolos.criterios_calibracion IS 'Criterios de calibración.';
COMMENT ON COLUMN experimento.protocolos.agregacion_grupos IS 'equal_group_weight o declared_field_weights.';
COMMENT ON COLUMN experimento.protocolos.pesos_grupos_ruta IS 'Archivo de pesos por grupo, si aplica.';
COMMENT ON COLUMN experimento.protocolos.politica_reajuste IS 'train_only o train_plus_validation_after_selection.';
COMMENT ON COLUMN experimento.protocolos.tolerancia_numerica IS 'Tolerancia para comparar réplicas.';
COMMENT ON COLUMN experimento.protocolos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN experimento.protocolos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE experimento.protocolo_semillas (
    protocolo_id text NOT NULL,
    etapa text NOT NULL,
    semilla integer NOT NULL,
    orden integer NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT protocolo_semillas_pk PRIMARY KEY (protocolo_id, etapa, semilla),
    CONSTRAINT protocolo_semillas_unica_1 UNIQUE (protocolo_id, semilla),
    CONSTRAINT protocolo_semillas_etapa_regla CHECK (etapa IN ('search','finalists','final')),
    CONSTRAINT protocolo_semillas_orden_regla CHECK (orden >= 0)
);
COMMENT ON TABLE experimento.protocolo_semillas IS 'Semillas de cada etapa del protocolo. La base impide que una semilla esté en dos etapas.';
COMMENT ON COLUMN experimento.protocolo_semillas.protocolo_id IS 'Protocolo.';
COMMENT ON COLUMN experimento.protocolo_semillas.etapa IS 'search (búsqueda), finalists (finalistas) o final (prueba final).';
COMMENT ON COLUMN experimento.protocolo_semillas.semilla IS 'Valor de la semilla.';
COMMENT ON COLUMN experimento.protocolo_semillas.orden IS 'Posición dentro de la etapa.';
COMMENT ON COLUMN experimento.protocolo_semillas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN experimento.protocolo_semillas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.planes (
    plan_id control.huella NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    duraciones_s jsonb NOT NULL,
    ciclo_s double precision NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT planes_pk PRIMARY KEY (plan_id),
    CONSTRAINT planes_ciclo_s_regla CHECK (ciclo_s > 0)
);
COMMENT ON TABLE simulacion.planes IS 'Un plan de tiempos: la duración de cada tramo y el ciclo.';
COMMENT ON COLUMN simulacion.planes.plan_id IS 'Huella del vector de duraciones en el orden de los tramos del caso.';
COMMENT ON COLUMN simulacion.planes.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.planes.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.planes.duraciones_s IS 'Duración de cada tramo, por tramo_id (si se aprueba plan_tramos, pasa a esa tabla). Unidad: s.';
COMMENT ON COLUMN simulacion.planes.ciclo_s IS 'Suma de todos los tramos. Unidad: s.';
COMMENT ON COLUMN simulacion.planes.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.planes.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.plan_tramos (
    plan_id control.huella NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    tramo_id text NOT NULL,
    duracion_s double precision NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT plan_tramos_pk PRIMARY KEY (plan_id, tramo_id),
    CONSTRAINT plan_tramos_duracion_s_regla CHECK (duracion_s >= 0)
);
COMMENT ON TABLE simulacion.plan_tramos IS 'Duración de cada tramo de un plan, en filas. Permite consultar «el t5 de todos los planes» y exige que el tramo exista en el caso.';
COMMENT ON COLUMN simulacion.plan_tramos.plan_id IS 'Plan.';
COMMENT ON COLUMN simulacion.plan_tramos.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.plan_tramos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.plan_tramos.tramo_id IS 'Tramo.';
COMMENT ON COLUMN simulacion.plan_tramos.duracion_s IS 'Duración del tramo. Unidad: s.';
COMMENT ON COLUMN simulacion.plan_tramos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.plan_tramos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.corridas (
    run_id text NOT NULL,
    estado text NOT NULL,
    creada_en timestamptz NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    escenario_id text NOT NULL,
    etapa text NOT NULL,
    semilla_sumo integer,
    semilla_demanda integer,
    protocolo_id text,
    plan_id control.huella,
    programa_id text,
    tls_id text,
    red_sha256 control.huella,
    programa_sha256 control.huella,
    rutas_sha256 control.huella,
    tipos_sha256 control.huella,
    entradas_sha256 control.huella,
    politica_frontera text,
    paso_s double precision,
    calentamiento_s double precision,
    medicion_s double precision,
    vaciado_max_s double precision,
    fin_s double precision,
    inicio_cohorte_s double precision,
    fin_cohorte_s double precision,
    vehiculos_total integer,
    vehiculos_cohorte integer,
    vehiculos_calentamiento integer,
    opciones_sumo jsonb,
    limitaciones jsonb,
    comando jsonb NOT NULL,
    entorno_id control.huella NOT NULL,
    codigo_salida integer,
    error jsonb,
    reintento_de text,
    terminacion text,
    inicio_ejecucion timestamptz,
    fin_ejecucion timestamptz,
    duracion_s double precision,
    limite_tiempo_s double precision,
    memoria_pico_bytes bigint,
    bytes_salida bigint,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT corridas_pk PRIMARY KEY (run_id),
    CONSTRAINT corridas_estado_regla CHECK (estado IN ('succeeded','failed','cancelled')),
    CONSTRAINT corridas_etapa_regla CHECK (etapa IN ('search','finalists','final','diagnostic')),
    CONSTRAINT corridas_terminacion_regla CHECK (terminacion IS NULL OR terminacion IN ('completed','sumo_error','timeout','cancelled','output_budget','memory_budget','not_started')),
    CONSTRAINT corridas_duracion_s_regla CHECK (duracion_s IS NULL OR duracion_s >= 0),
    CONSTRAINT corridas_exito_con_codigo_cero CHECK (estado <> 'succeeded' OR codigo_salida = 0),
    CONSTRAINT corridas_etapa_con_plan_y_protocolo CHECK (etapa = 'diagnostic' OR (plan_id IS NOT NULL AND protocolo_id IS NOT NULL))
);
COMMENT ON TABLE simulacion.corridas IS 'Una simulación de SUMO: escenario, plan, semilla, etapa, estado, versiones y huellas de sus entradas.';
COMMENT ON COLUMN simulacion.corridas.run_id IS 'Identificador de la corrida.';
COMMENT ON COLUMN simulacion.corridas.estado IS 'succeeded (exitosa), failed (fallida) o cancelled (cancelada).';
COMMENT ON COLUMN simulacion.corridas.creada_en IS 'Cuándo se creó.';
COMMENT ON COLUMN simulacion.corridas.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.corridas.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.corridas.escenario_id IS 'Escenario simulado.';
COMMENT ON COLUMN simulacion.corridas.etapa IS 'search, finalists, final o diagnostic (corrida fuera de una búsqueda o evaluación).';
COMMENT ON COLUMN simulacion.corridas.semilla_sumo IS 'Semilla de SUMO.';
COMMENT ON COLUMN simulacion.corridas.semilla_demanda IS 'Semilla de la demanda materializada.';
COMMENT ON COLUMN simulacion.corridas.protocolo_id IS 'Protocolo; vacío si el manifiesto no lo dice y ninguna búsqueda lo usa.';
COMMENT ON COLUMN simulacion.corridas.plan_id IS 'Plan aplicado; vacío si el programa no corresponde a un plan del caso.';
COMMENT ON COLUMN simulacion.corridas.programa_id IS 'Identificador del programa de SUMO.';
COMMENT ON COLUMN simulacion.corridas.tls_id IS 'Semáforo programado.';
COMMENT ON COLUMN simulacion.corridas.red_sha256 IS 'Huella de la red.';
COMMENT ON COLUMN simulacion.corridas.programa_sha256 IS 'Huella del programa.';
COMMENT ON COLUMN simulacion.corridas.rutas_sha256 IS 'Huella de las rutas: la demanda materializada, igual entre alternativas comparadas.';
COMMENT ON COLUMN simulacion.corridas.tipos_sha256 IS 'Huella de los tipos de vehículo.';
COMMENT ON COLUMN simulacion.corridas.entradas_sha256 IS 'Huella del manifiesto de entradas completo.';
COMMENT ON COLUMN simulacion.corridas.politica_frontera IS 'Política de frontera.';
COMMENT ON COLUMN simulacion.corridas.paso_s IS 'Paso de simulación. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.calentamiento_s IS 'Arranque sin medir. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.medicion_s IS 'Intervalo medido. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.vaciado_max_s IS 'Vaciado máximo. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.fin_s IS 'Fin de la simulación. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.inicio_cohorte_s IS 'Desde cuándo se mide la cohorte. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.fin_cohorte_s IS 'Hasta cuándo se mide la cohorte. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.vehiculos_total IS 'Vehículos pedidos en total. Unidad: veh.';
COMMENT ON COLUMN simulacion.corridas.vehiculos_cohorte IS 'Vehículos de la cohorte. Unidad: veh.';
COMMENT ON COLUMN simulacion.corridas.vehiculos_calentamiento IS 'Vehículos del calentamiento. Unidad: veh.';
COMMENT ON COLUMN simulacion.corridas.opciones_sumo IS 'Opciones de SUMO usadas.';
COMMENT ON COLUMN simulacion.corridas.limitaciones IS 'Limitaciones declaradas de la corrida.';
COMMENT ON COLUMN simulacion.corridas.comando IS 'Comando con que se lanzó SUMO.';
COMMENT ON COLUMN simulacion.corridas.entorno_id IS 'Versiones usadas.';
COMMENT ON COLUMN simulacion.corridas.codigo_salida IS 'Código con que terminó SUMO.';
COMMENT ON COLUMN simulacion.corridas.error IS 'Error tipado si falló.';
COMMENT ON COLUMN simulacion.corridas.reintento_de IS 'Corrida anterior si es un reintento.';
COMMENT ON COLUMN simulacion.corridas.terminacion IS 'completed, sumo_error, timeout, cancelled, output_budget, memory_budget o not_started.';
COMMENT ON COLUMN simulacion.corridas.inicio_ejecucion IS 'Cuándo arrancó SUMO.';
COMMENT ON COLUMN simulacion.corridas.fin_ejecucion IS 'Cuándo terminó.';
COMMENT ON COLUMN simulacion.corridas.duracion_s IS 'Tiempo de cálculo (I7). Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.limite_tiempo_s IS 'Tiempo máximo permitido. Unidad: s.';
COMMENT ON COLUMN simulacion.corridas.memoria_pico_bytes IS 'Memoria máxima usada. Unidad: bytes.';
COMMENT ON COLUMN simulacion.corridas.bytes_salida IS 'Tamaño de las salidas. Unidad: bytes.';
COMMENT ON COLUMN simulacion.corridas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.corridas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.resultados_corrida (
    run_id text NOT NULL,
    artefacto_metricas_id text,
    modo text NOT NULL,
    fin_limite_s double precision NOT NULL,
    fin_simulado_s double precision,
    vehiculos_declarados integer,
    vehiculos_cargados integer NOT NULL,
    vehiculos_insertados integer NOT NULL,
    vehiculos_en_red integer NOT NULL,
    vehiculos_esperando integer NOT NULL,
    viajes_terminados integer NOT NULL,
    viajes_sin_terminar integer NOT NULL,
    teletransportes_total integer NOT NULL,
    teletransportes_atasco integer NOT NULL,
    teletransportes_cruce integer NOT NULL,
    teletransportes_carril integer NOT NULL,
    choques integer NOT NULL,
    avisos_sumo integer NOT NULL,
    demora_salida_media_s double precision,
    demanda_insatisfecha boolean NOT NULL,
    hallazgos jsonb NOT NULL,
    version_metricas text,
    protocolo_metricas_id text,
    estado_protocolo_metricas text,
    definicion_demora text,
    origen_caso text,
    origen_demanda text,
    origen_evidencia text,
    cohorte_solicitada integer,
    cohorte_terminada integer,
    cohorte_sin_terminar integer,
    cohorte_no_insertada integer,
    estado_demora text,
    suma_demora_s double precision,
    demora_media_s double precision,
    perdida_tiempo_media_s double precision,
    demora_salida_media_cohorte_s double precision,
    cota_inf_demora_s double precision,
    cota_inf_perdida_tiempo_s double precision,
    cota_inf_demora_salida_s double precision,
    vehiculos_calentamiento integer,
    zona_disponible boolean,
    motivo_zona_no_disponible text,
    carriles_zona jsonb,
    umbral_cola_mps double precision,
    umbral_detencion_mps double precision,
    muestreo_cola_s double precision,
    inicio_medicion_s double precision,
    fin_medicion_s double precision,
    estado_cola text,
    ticks_esperados integer,
    ticks_observados integer,
    cobertura_cola double precision,
    vehiculo_ticks bigint,
    cola_media_veh double precision,
    cola_maxima_veh integer,
    estado_detenciones text,
    detenciones_solicitados integer,
    detenciones_total integer,
    detenciones_media double precision,
    cota_inf_detenciones double precision,
    pasos_fcd integer,
    pasos_cola_s double precision[],
    pasos_en_ventana boolean[],
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT resultados_corrida_pk PRIMARY KEY (run_id),
    CONSTRAINT resultados_corrida_modo_regla CHECK (modo IN ('smoke','base')),
    CONSTRAINT resultados_corrida_vehiculos_cargados_regla CHECK (vehiculos_cargados >= 0),
    CONSTRAINT resultados_corrida_vehiculos_insertados_regla CHECK (vehiculos_insertados >= 0),
    CONSTRAINT resultados_corrida_vehiculos_en_red_regla CHECK (vehiculos_en_red >= 0),
    CONSTRAINT resultados_corrida_vehiculos_esperando_regla CHECK (vehiculos_esperando >= 0),
    CONSTRAINT resultados_corrida_viajes_terminados_regla CHECK (viajes_terminados >= 0),
    CONSTRAINT resultados_corrida_viajes_sin_terminar_regla CHECK (viajes_sin_terminar >= 0),
    CONSTRAINT resultados_corrida_teletransportes_total_regla CHECK (teletransportes_total >= 0),
    CONSTRAINT resultados_corrida_teletransportes_atasco_regla CHECK (teletransportes_atasco >= 0),
    CONSTRAINT resultados_corrida_teletransportes_cruce_regla CHECK (teletransportes_cruce >= 0),
    CONSTRAINT resultados_corrida_teletransportes_carril_regla CHECK (teletransportes_carril >= 0),
    CONSTRAINT resultados_corrida_choques_regla CHECK (choques >= 0),
    CONSTRAINT resultados_corrida_avisos_sumo_regla CHECK (avisos_sumo >= 0),
    CONSTRAINT resultados_corrida_estado_protocolo_metricas_regla CHECK (estado_protocolo_metricas IS NULL OR estado_protocolo_metricas IN ('draft','frozen')),
    CONSTRAINT resultados_corrida_origen_caso_regla CHECK (origen_caso IS NULL OR origen_caso IN ('synthetic','field')),
    CONSTRAINT resultados_corrida_origen_demanda_regla CHECK (origen_demanda IS NULL OR origen_demanda IN ('synthetic','field')),
    CONSTRAINT resultados_corrida_origen_evidencia_regla CHECK (origen_evidencia IS NULL OR origen_evidencia IN ('synthetic','field')),
    CONSTRAINT resultados_corrida_estado_demora_regla CHECK (estado_demora IS NULL OR estado_demora IN ('complete','censored','empty')),
    CONSTRAINT resultados_corrida_estado_cola_regla CHECK (estado_cola IS NULL OR estado_cola IN ('complete','incomplete','empty')),
    CONSTRAINT resultados_corrida_estado_detenciones_regla CHECK (estado_detenciones IS NULL OR estado_detenciones IN ('complete','censored','empty')),
    CONSTRAINT resultados_corrida_pasos_cola_s_regla CHECK (array_position(pasos_cola_s, NULL) IS NULL AND 0 <= ALL(pasos_cola_s) AND 'Infinity'::double precision > ALL(pasos_cola_s)),
    CONSTRAINT resultados_corrida_pasos_en_ventana_regla CHECK (array_position(pasos_en_ventana, NULL) IS NULL),
    CONSTRAINT resultados_corrida_demora_completa CHECK (estado_demora IS DISTINCT FROM 'complete' OR demora_media_s IS NOT NULL),
    CONSTRAINT resultados_corrida_demora_censurada CHECK (estado_demora IS DISTINCT FROM 'censored' OR (demora_media_s IS NULL AND cota_inf_demora_s IS NOT NULL)),
    CONSTRAINT resultados_corrida_zona_con_motivo CHECK (zona_disponible IS DISTINCT FROM false OR motivo_zona_no_disponible IS NOT NULL)
);
COMMENT ON TABLE simulacion.resultados_corrida IS 'Resultados de una corrida: lo que reporta SUMO y las métricas de la cohorte y la zona calculadas por el código oficial (DEV19).';
COMMENT ON COLUMN simulacion.resultados_corrida.run_id IS 'Corrida.';
COMMENT ON COLUMN simulacion.resultados_corrida.artefacto_metricas_id IS 'Archivo de métricas publicado; vacío si la corrida aún no tiene métricas.';
COMMENT ON COLUMN simulacion.resultados_corrida.modo IS 'smoke (prueba corta) o base.';
COMMENT ON COLUMN simulacion.resultados_corrida.fin_limite_s IS 'Fin previsto. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.fin_simulado_s IS 'Hasta dónde llegó la simulación. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.vehiculos_declarados IS 'Vehículos declarados en la demanda. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.vehiculos_cargados IS 'Vehículos que SUMO cargó. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.vehiculos_insertados IS 'Vehículos que entraron a la red. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.vehiculos_en_red IS 'Vehículos todavía en la red al final. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.vehiculos_esperando IS 'Vehículos esperando entrar al final. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.viajes_terminados IS 'Viajes terminados. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.viajes_sin_terminar IS 'Viajes sin terminar. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.teletransportes_total IS 'Teletransportes en toda la red.';
COMMENT ON COLUMN simulacion.resultados_corrida.teletransportes_atasco IS 'Teletransportes por atasco.';
COMMENT ON COLUMN simulacion.resultados_corrida.teletransportes_cruce IS 'Teletransportes al ceder el paso.';
COMMENT ON COLUMN simulacion.resultados_corrida.teletransportes_carril IS 'Teletransportes por carril equivocado.';
COMMENT ON COLUMN simulacion.resultados_corrida.choques IS 'Choques.';
COMMENT ON COLUMN simulacion.resultados_corrida.avisos_sumo IS 'Avisos en el registro de SUMO.';
COMMENT ON COLUMN simulacion.resultados_corrida.demora_salida_media_s IS 'Espera media para entrar, de todos los vehículos. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.demanda_insatisfecha IS 'Si quedó demanda sin atender.';
COMMENT ON COLUMN simulacion.resultados_corrida.hallazgos IS 'Observaciones de la corrida (avisos, teletransportes, choques...).';
COMMENT ON COLUMN simulacion.resultados_corrida.version_metricas IS 'Versión del formato de métricas.';
COMMENT ON COLUMN simulacion.resultados_corrida.protocolo_metricas_id IS 'Protocolo con que se calcularon las métricas.';
COMMENT ON COLUMN simulacion.resultados_corrida.estado_protocolo_metricas IS 'draft o frozen.';
COMMENT ON COLUMN simulacion.resultados_corrida.definicion_demora IS 'Definición de demora usada.';
COMMENT ON COLUMN simulacion.resultados_corrida.origen_caso IS 'synthetic o field.';
COMMENT ON COLUMN simulacion.resultados_corrida.origen_demanda IS 'synthetic o field.';
COMMENT ON COLUMN simulacion.resultados_corrida.origen_evidencia IS 'field solo si caso y demanda lo son; si no, synthetic (auditoría A03).';
COMMENT ON COLUMN simulacion.resultados_corrida.cohorte_solicitada IS 'Vehículos de la cohorte pedidos. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.cohorte_terminada IS 'Vehículos de la cohorte que terminaron. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.cohorte_sin_terminar IS 'Vehículos de la cohorte que no terminaron. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.cohorte_no_insertada IS 'Vehículos de la cohorte que no entraron. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.estado_demora IS 'complete (cohorte completa), censored (incompleta: solo cota inferior) o empty (sin vehículos).';
COMMENT ON COLUMN simulacion.resultados_corrida.suma_demora_s IS 'Suma de demoras de la cohorte. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.demora_media_s IS 'Demora media por vehículo (pérdida de tiempo más espera de salida); vacía si la cohorte no terminó. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.perdida_tiempo_media_s IS 'Media de la pérdida de tiempo (timeLoss). Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.demora_salida_media_cohorte_s IS 'Media de la espera de salida de la cohorte. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.cota_inf_demora_s IS 'Demora media mínima cuando la cohorte no terminó. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.cota_inf_perdida_tiempo_s IS 'Cota inferior de la pérdida de tiempo. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.cota_inf_demora_salida_s IS 'Cota inferior de la espera de salida. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.vehiculos_calentamiento IS 'Vehículos del calentamiento (fuera de la cohorte). Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.zona_disponible IS 'Si hay datos de la zona (cola y detenciones).';
COMMENT ON COLUMN simulacion.resultados_corrida.motivo_zona_no_disponible IS 'Por qué no hay datos de la zona.';
COMMENT ON COLUMN simulacion.resultados_corrida.carriles_zona IS 'Carriles medidos.';
COMMENT ON COLUMN simulacion.resultados_corrida.umbral_cola_mps IS 'Umbral de cola usado. Unidad: m/s.';
COMMENT ON COLUMN simulacion.resultados_corrida.umbral_detencion_mps IS 'Umbral de detención usado. Unidad: m/s.';
COMMENT ON COLUMN simulacion.resultados_corrida.muestreo_cola_s IS 'Muestreo de la cola. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.inicio_medicion_s IS 'Inicio de la medición de la zona. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.fin_medicion_s IS 'Fin de la medición de la zona. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.estado_cola IS 'complete, incomplete o empty.';
COMMENT ON COLUMN simulacion.resultados_corrida.ticks_esperados IS 'Muestras de cola esperadas.';
COMMENT ON COLUMN simulacion.resultados_corrida.ticks_observados IS 'Muestras de cola observadas.';
COMMENT ON COLUMN simulacion.resultados_corrida.cobertura_cola IS 'Observadas entre esperadas. Unidad: fracción.';
COMMENT ON COLUMN simulacion.resultados_corrida.vehiculo_ticks IS 'Suma de vehículos en cola en todas las muestras.';
COMMENT ON COLUMN simulacion.resultados_corrida.cola_media_veh IS 'Cola media en la zona. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.cola_maxima_veh IS 'Cola máxima en la zona. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.estado_detenciones IS 'complete, censored o empty.';
COMMENT ON COLUMN simulacion.resultados_corrida.detenciones_solicitados IS 'Vehículos considerados para detenciones. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_corrida.detenciones_total IS 'Detenciones totales.';
COMMENT ON COLUMN simulacion.resultados_corrida.detenciones_media IS 'Detenciones por vehículo.';
COMMENT ON COLUMN simulacion.resultados_corrida.cota_inf_detenciones IS 'Cota inferior de detenciones por vehículo.';
COMMENT ON COLUMN simulacion.resultados_corrida.pasos_fcd IS 'Pasos leídos del archivo de posiciones.';
COMMENT ON COLUMN simulacion.resultados_corrida.pasos_cola_s IS 'Momento finito y no negativo de cada paso de la serie de cola, en orden estricto (la misma para todos los accesos de la corrida). Vacío sin zona. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_corrida.pasos_en_ventana IS 'Si cada paso cuenta para la cola del resumen (intervalo de medición y momento de muestreo), en el mismo orden que pasos_cola_s. Los demás pasos (calentamiento, vaciado) se guardan, pero no entran en las medias. Vacío sin zona.';
COMMENT ON COLUMN simulacion.resultados_corrida.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.resultados_corrida.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.resultados_acceso (
    run_id text NOT NULL,
    acceso text NOT NULL,
    con_cohorte boolean NOT NULL,
    solicitados integer,
    terminados integer,
    sin_terminar integer,
    no_insertados integer,
    estado_demora text,
    suma_demora_s double precision,
    demora_media_s double precision,
    perdida_tiempo_media_s double precision,
    demora_salida_media_s double precision,
    cota_inf_demora_s double precision,
    cota_inf_perdida_tiempo_s double precision,
    cota_inf_demora_salida_s double precision,
    estado_cola text,
    ticks_esperados integer,
    ticks_observados integer,
    cobertura_cola double precision,
    vehiculo_ticks bigint,
    cola_media_veh double precision,
    cola_maxima_veh integer,
    estado_detenciones text,
    detenciones_solicitados integer,
    detenciones_total integer,
    detenciones_media double precision,
    cota_inf_detenciones double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT resultados_acceso_pk PRIMARY KEY (run_id, acceso),
    CONSTRAINT resultados_acceso_estado_demora_regla CHECK (estado_demora IS NULL OR estado_demora IN ('complete','censored','empty')),
    CONSTRAINT resultados_acceso_estado_cola_regla CHECK (estado_cola IS NULL OR estado_cola IN ('complete','incomplete','empty')),
    CONSTRAINT resultados_acceso_estado_detenciones_regla CHECK (estado_detenciones IS NULL OR estado_detenciones IN ('complete','censored','empty')),
    CONSTRAINT resultados_acceso_cohorte_y_demora CHECK ((con_cohorte AND solicitados IS NOT NULL AND terminados IS NOT NULL AND sin_terminar IS NOT NULL AND no_insertados IS NOT NULL AND estado_demora IS NOT NULL AND suma_demora_s IS NOT NULL) OR (NOT con_cohorte AND solicitados IS NULL AND terminados IS NULL AND sin_terminar IS NULL AND no_insertados IS NULL AND estado_demora IS NULL AND suma_demora_s IS NULL AND demora_media_s IS NULL AND perdida_tiempo_media_s IS NULL AND demora_salida_media_s IS NULL AND cota_inf_demora_s IS NULL AND cota_inf_perdida_tiempo_s IS NULL AND cota_inf_demora_salida_s IS NULL))
);
COMMENT ON TABLE simulacion.resultados_acceso IS 'Demora, cola y detenciones por acceso del cruce (I6 por acceso).';
COMMENT ON COLUMN simulacion.resultados_acceso.run_id IS 'Corrida.';
COMMENT ON COLUMN simulacion.resultados_acceso.acceso IS 'Acceso: approach_id del caso o, para carriles de la zona sin movimiento, su calle.';
COMMENT ON COLUMN simulacion.resultados_acceso.con_cohorte IS 'Si el acceso tiene vehículos de la cohorte y por eso datos de demora; si no, solo puede tener cola y detenciones.';
COMMENT ON COLUMN simulacion.resultados_acceso.solicitados IS 'Vehículos de la cohorte por este acceso. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_acceso.terminados IS 'Terminados. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_acceso.sin_terminar IS 'Sin terminar. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_acceso.no_insertados IS 'No insertados. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_acceso.estado_demora IS 'complete, censored o empty; vacío sin cohorte.';
COMMENT ON COLUMN simulacion.resultados_acceso.suma_demora_s IS 'Suma de demoras; vacía sin cohorte. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_acceso.demora_media_s IS 'Demora media; vacía si está censurada. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_acceso.perdida_tiempo_media_s IS 'Pérdida de tiempo media. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_acceso.demora_salida_media_s IS 'Espera de salida media. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_acceso.cota_inf_demora_s IS 'Cota inferior de la demora. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_acceso.cota_inf_perdida_tiempo_s IS 'Cota inferior de la pérdida de tiempo. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_acceso.cota_inf_demora_salida_s IS 'Cota inferior de la espera de salida. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_acceso.estado_cola IS 'complete, incomplete o empty; vacío sin zona.';
COMMENT ON COLUMN simulacion.resultados_acceso.ticks_esperados IS 'Muestras esperadas.';
COMMENT ON COLUMN simulacion.resultados_acceso.ticks_observados IS 'Muestras observadas.';
COMMENT ON COLUMN simulacion.resultados_acceso.cobertura_cola IS 'Cobertura de la cola. Unidad: fracción.';
COMMENT ON COLUMN simulacion.resultados_acceso.vehiculo_ticks IS 'Suma de vehículos en cola.';
COMMENT ON COLUMN simulacion.resultados_acceso.cola_media_veh IS 'Cola media. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_acceso.cola_maxima_veh IS 'Cola máxima. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_acceso.estado_detenciones IS 'complete, censored o empty.';
COMMENT ON COLUMN simulacion.resultados_acceso.detenciones_solicitados IS 'Vehículos considerados. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_acceso.detenciones_total IS 'Detenciones.';
COMMENT ON COLUMN simulacion.resultados_acceso.detenciones_media IS 'Detenciones por vehículo.';
COMMENT ON COLUMN simulacion.resultados_acceso.cota_inf_detenciones IS 'Cota inferior de detenciones.';
COMMENT ON COLUMN simulacion.resultados_acceso.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.resultados_acceso.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.resultados_movimiento (
    run_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    movimiento_id text NOT NULL,
    solicitados integer NOT NULL,
    terminados integer NOT NULL,
    sin_terminar integer NOT NULL,
    no_insertados integer NOT NULL,
    estado_demora text NOT NULL,
    suma_demora_s double precision NOT NULL,
    demora_media_s double precision,
    perdida_tiempo_media_s double precision,
    demora_salida_media_s double precision,
    cota_inf_demora_s double precision,
    cota_inf_perdida_tiempo_s double precision,
    cota_inf_demora_salida_s double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT resultados_movimiento_pk PRIMARY KEY (run_id, movimiento_id),
    CONSTRAINT resultados_movimiento_estado_demora_regla CHECK (estado_demora IN ('complete','censored','empty'))
);
COMMENT ON TABLE simulacion.resultados_movimiento IS 'Demora por movimiento del cruce.';
COMMENT ON COLUMN simulacion.resultados_movimiento.run_id IS 'Corrida.';
COMMENT ON COLUMN simulacion.resultados_movimiento.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.resultados_movimiento.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.resultados_movimiento.movimiento_id IS 'Movimiento.';
COMMENT ON COLUMN simulacion.resultados_movimiento.solicitados IS 'Vehículos de la cohorte en el movimiento. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_movimiento.terminados IS 'Terminados. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_movimiento.sin_terminar IS 'Sin terminar. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_movimiento.no_insertados IS 'No insertados. Unidad: veh.';
COMMENT ON COLUMN simulacion.resultados_movimiento.estado_demora IS 'complete, censored o empty.';
COMMENT ON COLUMN simulacion.resultados_movimiento.suma_demora_s IS 'Suma de demoras. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_movimiento.demora_media_s IS 'Demora media. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_movimiento.perdida_tiempo_media_s IS 'Pérdida de tiempo media. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_movimiento.demora_salida_media_s IS 'Espera de salida media. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_movimiento.cota_inf_demora_s IS 'Cota inferior de la demora. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_movimiento.cota_inf_perdida_tiempo_s IS 'Cota inferior de la pérdida de tiempo. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_movimiento.cota_inf_demora_salida_s IS 'Cota inferior de la espera de salida. Unidad: s.';
COMMENT ON COLUMN simulacion.resultados_movimiento.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.resultados_movimiento.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.vehiculos (
    run_id text NOT NULL,
    vehiculo_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    movimiento_id text NOT NULL,
    clase_id text NOT NULL,
    en_cohorte boolean NOT NULL,
    salida_programada_s double precision NOT NULL,
    estado text NOT NULL,
    entrada_real_s double precision,
    llegada_s double precision,
    carril_salida text,
    demora_salida_s double precision,
    carril_llegada text,
    duracion_s double precision,
    recorrido_m double precision,
    espera_s double precision,
    esperas integer,
    tiempo_detenido_s double precision,
    perdida_tiempo_s double precision,
    factor_velocidad double precision,
    tipo_sumo text,
    vaporizado boolean,
    acceso text,
    perdida_tiempo_cohorte_s double precision,
    demora_salida_cohorte_s double precision,
    fuente_demora_salida text,
    detenciones integer,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT vehiculos_pk PRIMARY KEY (run_id, vehiculo_id),
    CONSTRAINT vehiculos_estado_regla CHECK (estado IN ('finished','unfinished','not_inserted')),
    CONSTRAINT vehiculos_fuente_demora_salida_regla CHECK (fuente_demora_salida IS NULL OR fuente_demora_salida IN ('sumo','schedule')),
    CONSTRAINT vehiculos_terminado_con_llegada CHECK (estado <> 'finished' OR llegada_s IS NOT NULL),
    CONSTRAINT vehiculos_no_insertado_sin_entrada CHECK (estado <> 'not_inserted' OR entrada_real_s IS NULL)
);
COMMENT ON TABLE simulacion.vehiculos IS 'Cada vehículo de una corrida: qué pidió, qué le pasó y cuánto tiempo perdió.';
COMMENT ON COLUMN simulacion.vehiculos.run_id IS 'Corrida.';
COMMENT ON COLUMN simulacion.vehiculos.vehiculo_id IS 'Identificador del vehículo en SUMO.';
COMMENT ON COLUMN simulacion.vehiculos.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.vehiculos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.vehiculos.movimiento_id IS 'Movimiento que realiza.';
COMMENT ON COLUMN simulacion.vehiculos.clase_id IS 'Clase de vehículo.';
COMMENT ON COLUMN simulacion.vehiculos.en_cohorte IS 'Si cuenta para la demora oficial (salida pedida dentro de la ventana de medición).';
COMMENT ON COLUMN simulacion.vehiculos.salida_programada_s IS 'Hora de salida pedida. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.estado IS 'finished (terminó), unfinished (no terminó) o not_inserted (no entró).';
COMMENT ON COLUMN simulacion.vehiculos.entrada_real_s IS 'Hora en que entró; vacía si no entró. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.llegada_s IS 'Hora de llegada; vacía si no terminó. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.carril_salida IS 'Carril donde entró.';
COMMENT ON COLUMN simulacion.vehiculos.demora_salida_s IS 'departDelay: espera antes de entrar. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.carril_llegada IS 'Carril donde terminó.';
COMMENT ON COLUMN simulacion.vehiculos.duracion_s IS 'Duración del viaje. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.recorrido_m IS 'Largo del recorrido. Unidad: m.';
COMMENT ON COLUMN simulacion.vehiculos.espera_s IS 'waitingTime: tiempo casi detenido. No es la demora de control. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.esperas IS 'waitingCount: veces que quedó casi detenido.';
COMMENT ON COLUMN simulacion.vehiculos.tiempo_detenido_s IS 'stopTime: tiempo en paradas programadas. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.perdida_tiempo_s IS 'timeLoss: tiempo perdido por ir más lento que la velocidad ideal. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.factor_velocidad IS 'speedFactor del conductor.';
COMMENT ON COLUMN simulacion.vehiculos.tipo_sumo IS 'vType de SUMO.';
COMMENT ON COLUMN simulacion.vehiculos.vaporizado IS 'Si SUMO lo retiró.';
COMMENT ON COLUMN simulacion.vehiculos.acceso IS 'Acceso del movimiento; vacío fuera de la cohorte.';
COMMENT ON COLUMN simulacion.vehiculos.perdida_tiempo_cohorte_s IS 'Pérdida de tiempo usada en la demora oficial (incluye viajes sin terminar hasta el fin). Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.demora_salida_cohorte_s IS 'Espera de salida usada en la demora oficial. Unidad: s.';
COMMENT ON COLUMN simulacion.vehiculos.fuente_demora_salida IS 'sumo (medida) o schedule (calculada con el horario, si no entró).';
COMMENT ON COLUMN simulacion.vehiculos.detenciones IS 'Detenciones del vehículo en la zona; vacío fuera de la cohorte o sin zona.';
COMMENT ON COLUMN simulacion.vehiculos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.vehiculos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.eventos (
    run_id text NOT NULL,
    orden integer NOT NULL,
    tiempo_s double precision,
    tipo text NOT NULL,
    subtipo text,
    vehiculo_id text,
    otro_vehiculo_id text,
    carril_id text,
    texto text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT eventos_pk PRIMARY KEY (run_id, orden),
    CONSTRAINT eventos_orden_regla CHECK (orden >= 1),
    CONSTRAINT eventos_tipo_regla CHECK (tipo IN ('teleport','collision','warning','error'))
);
COMMENT ON TABLE simulacion.eventos IS 'Teletransportes, choques, avisos y errores del registro de SUMO.';
COMMENT ON COLUMN simulacion.eventos.run_id IS 'Corrida.';
COMMENT ON COLUMN simulacion.eventos.orden IS 'Posición de la línea en el registro.';
COMMENT ON COLUMN simulacion.eventos.tiempo_s IS 'Momento de simulación; vacío si la línea no lo trae. Unidad: s.';
COMMENT ON COLUMN simulacion.eventos.tipo IS 'teleport, collision, warning o error.';
COMMENT ON COLUMN simulacion.eventos.subtipo IS 'Causa: jam, yield, wrong_lane, o la etapa del choque.';
COMMENT ON COLUMN simulacion.eventos.vehiculo_id IS 'Vehículo involucrado.';
COMMENT ON COLUMN simulacion.eventos.otro_vehiculo_id IS 'Segundo vehículo en un choque.';
COMMENT ON COLUMN simulacion.eventos.carril_id IS 'Carril.';
COMMENT ON COLUMN simulacion.eventos.texto IS 'Línea original, guardada tal cual y escapada al mostrarla.';
COMMENT ON COLUMN simulacion.eventos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.eventos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.cola_por_acceso (
    run_id text NOT NULL,
    acceso text NOT NULL,
    vehiculos_en_cola integer[] NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT cola_por_acceso_pk PRIMARY KEY (run_id, acceso),
    CONSTRAINT cola_por_acceso_vehiculos_en_cola_regla CHECK (array_position(vehiculos_en_cola, NULL) IS NULL AND 0 <= ALL(vehiculos_en_cola))
);
COMMENT ON TABLE simulacion.cola_por_acceso IS 'Cola de cada acceso de la zona, paso a paso, como un arreglo por acceso. Los momentos de los pasos y cuáles cuentan para la cola del resumen están una sola vez por corrida, en resultados_corrida (pasos_cola_s y pasos_en_ventana). La vista vistas.cola_por_segundo muestra una fila por corrida, acceso y paso, como antes.';
COMMENT ON COLUMN simulacion.cola_por_acceso.run_id IS 'Corrida.';
COMMENT ON COLUMN simulacion.cola_por_acceso.acceso IS 'Acceso: una clave de zone.queue_series.vehicles_by_access.';
COMMENT ON COLUMN simulacion.cola_por_acceso.vehiculos_en_cola IS 'Vehículos no negativos del acceso con velocidad menor o igual que el umbral de cola, en los carriles de la zona, en cada paso (un número por paso, en el orden de pasos_cola_s de la corrida). Un paso que la FCD no trae no tiene valor: no se rellena con cero. Unidad: veh.';
COMMENT ON COLUMN simulacion.cola_por_acceso.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.cola_por_acceso.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.busquedas (
    busqueda_id text NOT NULL,
    escenario_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    protocolo_id text NOT NULL,
    estado_protocolo text NOT NULL,
    metodo text NOT NULL,
    version_busqueda text NOT NULL,
    version_reglas text NOT NULL,
    version_identidad text,
    version_bitacora text,
    semilla integer NOT NULL,
    presupuesto integer NOT NULL,
    cuenta_presupuesto text NOT NULL,
    presupuesto_usado integer NOT NULL,
    limite_intentos integer NOT NULL,
    intentos integer NOT NULL,
    duplicados integer NOT NULL,
    inviables integer NOT NULL,
    inviables_por_regla jsonb NOT NULL,
    cuadricula_factible bigint,
    limite_cuadricula bigint NOT NULL,
    tamano_espacio bigint,
    agotado boolean NOT NULL,
    estado_plan_vigente text NOT NULL,
    estado_webster text,
    finalistas integer NOT NULL,
    epsilon_empate_s double precision NOT NULL,
    semillas_busqueda jsonb NOT NULL,
    semillas_finalistas jsonb NOT NULL,
    opciones_sumo jsonb NOT NULL,
    huella_candidatos control.huella NOT NULL,
    regla_seleccion text NOT NULL,
    estado_seleccion text NOT NULL,
    motivo_sin_referencia text,
    cobertura jsonb NOT NULL,
    simulaciones integer NOT NULL,
    interrumpida boolean NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT busquedas_pk PRIMARY KEY (busqueda_id),
    CONSTRAINT busquedas_estado_protocolo_regla CHECK (estado_protocolo IN ('draft','frozen')),
    CONSTRAINT busquedas_metodo_regla CHECK (metodo IN ('grid','sampling')),
    CONSTRAINT busquedas_presupuesto_regla CHECK (presupuesto >= 0),
    CONSTRAINT busquedas_presupuesto_usado_regla CHECK (presupuesto_usado >= 0),
    CONSTRAINT busquedas_intentos_regla CHECK (intentos >= 0),
    CONSTRAINT busquedas_duplicados_regla CHECK (duplicados >= 0),
    CONSTRAINT busquedas_inviables_regla CHECK (inviables >= 0),
    CONSTRAINT busquedas_estado_plan_vigente_regla CHECK (estado_plan_vigente IN ('absent','included','excluded','duplicate')),
    CONSTRAINT busquedas_estado_webster_regla CHECK (estado_webster IS NULL OR estado_webster IN ('absent','included','excluded','duplicate')),
    CONSTRAINT busquedas_estado_seleccion_regla CHECK (estado_seleccion IN ('reference','no_reference')),
    CONSTRAINT busquedas_motivo_sin_referencia_regla CHECK (motivo_sin_referencia IS NULL OR motivo_sin_referencia IN ('no_candidates','no_eligible_candidate','no_eligible_finalist')),
    CONSTRAINT busquedas_simulaciones_regla CHECK (simulaciones >= 0),
    CONSTRAINT busquedas_motivo_si_sin_referencia CHECK ((estado_seleccion = 'no_reference') = (motivo_sin_referencia IS NOT NULL))
);
COMMENT ON TABLE simulacion.busquedas IS 'Búsqueda del mejor plan para un escenario: presupuesto, semillas, identidad y resultado de la selección.';
COMMENT ON COLUMN simulacion.busquedas.busqueda_id IS 'Identificador de la búsqueda.';
COMMENT ON COLUMN simulacion.busquedas.escenario_id IS 'Escenario.';
COMMENT ON COLUMN simulacion.busquedas.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.busquedas.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.busquedas.protocolo_id IS 'Protocolo.';
COMMENT ON COLUMN simulacion.busquedas.estado_protocolo IS 'draft o frozen al momento de buscar.';
COMMENT ON COLUMN simulacion.busquedas.metodo IS 'grid (cuadrícula) o sampling (muestreo).';
COMMENT ON COLUMN simulacion.busquedas.version_busqueda IS 'Versión del algoritmo de búsqueda.';
COMMENT ON COLUMN simulacion.busquedas.version_reglas IS 'Huella de las reglas de factibilidad.';
COMMENT ON COLUMN simulacion.busquedas.version_identidad IS 'Versión de la identidad (1.0.0 o 2.0.0 tras A01).';
COMMENT ON COLUMN simulacion.busquedas.version_bitacora IS 'Versión de la bitácora.';
COMMENT ON COLUMN simulacion.busquedas.semilla IS 'Semilla del generador de candidatos.';
COMMENT ON COLUMN simulacion.busquedas.presupuesto IS 'Candidatos que pueden consumir presupuesto.';
COMMENT ON COLUMN simulacion.busquedas.cuenta_presupuesto IS 'Qué cuenta como presupuesto.';
COMMENT ON COLUMN simulacion.busquedas.presupuesto_usado IS 'Candidatos que lo consumieron.';
COMMENT ON COLUMN simulacion.busquedas.limite_intentos IS 'Máximo de planes generados.';
COMMENT ON COLUMN simulacion.busquedas.intentos IS 'Planes generados.';
COMMENT ON COLUMN simulacion.busquedas.duplicados IS 'Planes repetidos descartados.';
COMMENT ON COLUMN simulacion.busquedas.inviables IS 'Planes descartados por reglas.';
COMMENT ON COLUMN simulacion.busquedas.inviables_por_regla IS 'Descartes por cada regla.';
COMMENT ON COLUMN simulacion.busquedas.cuadricula_factible IS 'Planes factibles de la cuadrícula; vacío con muestreo.';
COMMENT ON COLUMN simulacion.busquedas.limite_cuadricula IS 'Tope de la cuadrícula.';
COMMENT ON COLUMN simulacion.busquedas.tamano_espacio IS 'Planes posibles.';
COMMENT ON COLUMN simulacion.busquedas.agotado IS 'Si se agotaron los intentos.';
COMMENT ON COLUMN simulacion.busquedas.estado_plan_vigente IS 'absent, included, excluded o duplicate.';
COMMENT ON COLUMN simulacion.busquedas.estado_webster IS 'absent, included, excluded o duplicate; vacío en búsquedas anteriores a DEV15 F4.';
COMMENT ON COLUMN simulacion.busquedas.finalistas IS 'Candidatos reevaluados.';
COMMENT ON COLUMN simulacion.busquedas.epsilon_empate_s IS 'Umbral de empate. Unidad: s.';
COMMENT ON COLUMN simulacion.busquedas.semillas_busqueda IS 'Semillas de la etapa de búsqueda.';
COMMENT ON COLUMN simulacion.busquedas.semillas_finalistas IS 'Semillas de finalistas.';
COMMENT ON COLUMN simulacion.busquedas.opciones_sumo IS 'Opciones de SUMO.';
COMMENT ON COLUMN simulacion.busquedas.huella_candidatos IS 'Huella de la lista de candidatos.';
COMMENT ON COLUMN simulacion.busquedas.regla_seleccion IS 'Regla con que se eligió (texto y versión).';
COMMENT ON COLUMN simulacion.busquedas.estado_seleccion IS 'reference (hay ganador) o no_reference.';
COMMENT ON COLUMN simulacion.busquedas.motivo_sin_referencia IS 'no_candidates, no_eligible_candidate o no_eligible_finalist.';
COMMENT ON COLUMN simulacion.busquedas.cobertura IS 'Elegibles y descartados por motivo, en búsqueda y finalistas.';
COMMENT ON COLUMN simulacion.busquedas.simulaciones IS 'Corridas usadas.';
COMMENT ON COLUMN simulacion.busquedas.interrumpida IS 'Si se cortó antes de terminar.';
COMMENT ON COLUMN simulacion.busquedas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.busquedas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.candidatos (
    busqueda_id text NOT NULL,
    candidato_id text NOT NULL,
    plan_id control.huella NOT NULL,
    origen text NOT NULL,
    consume_presupuesto boolean NOT NULL,
    orden integer NOT NULL,
    elegible_busqueda boolean,
    puntaje_busqueda_s double precision,
    cola_media_busqueda_veh double precision,
    detenciones_media_busqueda double precision,
    problemas_busqueda jsonb,
    semillas_faltantes_busqueda jsonb,
    posicion_busqueda integer,
    finalista boolean NOT NULL,
    elegible_finalistas boolean,
    puntaje_finalistas_s double precision,
    cola_media_finalistas_veh double precision,
    detenciones_media_finalistas double precision,
    problemas_finalistas jsonb,
    semillas_faltantes_finalistas jsonb,
    posicion_finalistas integer,
    ganador boolean NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT candidatos_pk PRIMARY KEY (busqueda_id, candidato_id),
    CONSTRAINT candidatos_origen_regla CHECK (origen IN ('grid','sampled','current_plan','webster')),
    CONSTRAINT candidatos_orden_regla CHECK (orden >= 0),
    CONSTRAINT candidatos_ganador_es_finalista CHECK (NOT ganador OR (finalista AND elegible_finalistas))
);
COMMENT ON TABLE simulacion.candidatos IS 'Cada plan que evaluó una búsqueda, con su resultado en la etapa de búsqueda y, si llegó, en la de finalistas.';
COMMENT ON COLUMN simulacion.candidatos.busqueda_id IS 'Búsqueda.';
COMMENT ON COLUMN simulacion.candidatos.candidato_id IS 'Identificador del candidato.';
COMMENT ON COLUMN simulacion.candidatos.plan_id IS 'Plan evaluado.';
COMMENT ON COLUMN simulacion.candidatos.origen IS 'grid, sampled, current_plan o webster.';
COMMENT ON COLUMN simulacion.candidatos.consume_presupuesto IS 'Si cuenta para el presupuesto.';
COMMENT ON COLUMN simulacion.candidatos.orden IS 'Posición en la lista de candidatos.';
COMMENT ON COLUMN simulacion.candidatos.elegible_busqueda IS 'Si fue elegible en la búsqueda.';
COMMENT ON COLUMN simulacion.candidatos.puntaje_busqueda_s IS 'Demora media en la búsqueda. Unidad: s.';
COMMENT ON COLUMN simulacion.candidatos.cola_media_busqueda_veh IS 'Cola media en la búsqueda. Unidad: veh.';
COMMENT ON COLUMN simulacion.candidatos.detenciones_media_busqueda IS 'Detenciones por vehículo en la búsqueda.';
COMMENT ON COLUMN simulacion.candidatos.problemas_busqueda IS 'Problemas por tipo en la búsqueda.';
COMMENT ON COLUMN simulacion.candidatos.semillas_faltantes_busqueda IS 'Semillas sin resultado en la búsqueda.';
COMMENT ON COLUMN simulacion.candidatos.posicion_busqueda IS 'Lugar en el ranking de la búsqueda.';
COMMENT ON COLUMN simulacion.candidatos.finalista IS 'Si pasó a la reevaluación.';
COMMENT ON COLUMN simulacion.candidatos.elegible_finalistas IS 'Si fue elegible como finalista.';
COMMENT ON COLUMN simulacion.candidatos.puntaje_finalistas_s IS 'Demora media como finalista. Unidad: s.';
COMMENT ON COLUMN simulacion.candidatos.cola_media_finalistas_veh IS 'Cola media como finalista. Unidad: veh.';
COMMENT ON COLUMN simulacion.candidatos.detenciones_media_finalistas IS 'Detenciones como finalista.';
COMMENT ON COLUMN simulacion.candidatos.problemas_finalistas IS 'Problemas por tipo como finalista.';
COMMENT ON COLUMN simulacion.candidatos.semillas_faltantes_finalistas IS 'Semillas sin resultado como finalista.';
COMMENT ON COLUMN simulacion.candidatos.posicion_finalistas IS 'Lugar en el ranking de finalistas.';
COMMENT ON COLUMN simulacion.candidatos.ganador IS 'Si es el plan elegido como etiqueta.';
COMMENT ON COLUMN simulacion.candidatos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.candidatos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.candidato_semillas (
    busqueda_id text NOT NULL,
    candidato_id text NOT NULL,
    etapa text NOT NULL,
    semilla integer NOT NULL,
    run_id text,
    estado_corrida text,
    demora_media_s double precision,
    cola_media_veh double precision,
    detenciones_media double precision,
    teletransportes integer NOT NULL,
    choques integer NOT NULL,
    problemas jsonb NOT NULL,
    mensaje text,
    clase_incidente text,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT candidato_semillas_pk PRIMARY KEY (busqueda_id, candidato_id, etapa, semilla),
    CONSTRAINT candidato_semillas_etapa_regla CHECK (etapa IN ('search','finalists')),
    CONSTRAINT candidato_semillas_estado_corrida_regla CHECK (estado_corrida IS NULL OR estado_corrida IN ('succeeded','failed','cancelled')),
    CONSTRAINT candidato_semillas_teletransportes_regla CHECK (teletransportes >= 0),
    CONSTRAINT candidato_semillas_choques_regla CHECK (choques >= 0),
    CONSTRAINT candidato_semillas_clase_incidente_regla CHECK (clase_incidente IS NULL OR clase_incidente IN ('clean','isolated_incident','collapse'))
);
COMMENT ON TABLE simulacion.candidato_semillas IS 'Resultado de un candidato con cada semilla, con su clasificación según la regla C.';
COMMENT ON COLUMN simulacion.candidato_semillas.busqueda_id IS 'Búsqueda.';
COMMENT ON COLUMN simulacion.candidato_semillas.candidato_id IS 'Candidato.';
COMMENT ON COLUMN simulacion.candidato_semillas.etapa IS 'search o finalists.';
COMMENT ON COLUMN simulacion.candidato_semillas.semilla IS 'Semilla.';
COMMENT ON COLUMN simulacion.candidato_semillas.run_id IS 'Corrida; vacía si no llegó a crearse.';
COMMENT ON COLUMN simulacion.candidato_semillas.estado_corrida IS 'succeeded, failed o cancelled.';
COMMENT ON COLUMN simulacion.candidato_semillas.demora_media_s IS 'Demora media; vacía si la cohorte no terminó. Unidad: s.';
COMMENT ON COLUMN simulacion.candidato_semillas.cola_media_veh IS 'Cola media. Unidad: veh.';
COMMENT ON COLUMN simulacion.candidato_semillas.detenciones_media IS 'Detenciones por vehículo.';
COMMENT ON COLUMN simulacion.candidato_semillas.teletransportes IS 'Teletransportes.';
COMMENT ON COLUMN simulacion.candidato_semillas.choques IS 'Choques.';
COMMENT ON COLUMN simulacion.candidato_semillas.problemas IS 'run_failed, evaluation_failed, cohort_incomplete, teleports, collisions o zone_incomplete.';
COMMENT ON COLUMN simulacion.candidato_semillas.mensaje IS 'Mensaje de error.';
COMMENT ON COLUMN simulacion.candidato_semillas.clase_incidente IS 'clean (limpia), isolated_incident (incidente aislado) o collapse (colapso), según la regla C; vacía en búsquedas anteriores.';
COMMENT ON COLUMN simulacion.candidato_semillas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.candidato_semillas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.etiquetas (
    etiqueta_id text NOT NULL,
    escenario_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    busqueda_id text NOT NULL,
    protocolo_id text NOT NULL,
    estado text NOT NULL,
    plan_id control.huella,
    verdes_s jsonb,
    candidatos_cantidad integer NOT NULL,
    simulaciones_cantidad integer NOT NULL,
    estado_evidencia text NOT NULL,
    motivo text,
    red_sha256 control.huella NOT NULL,
    creada_en timestamptz NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT etiquetas_pk PRIMARY KEY (etiqueta_id),
    CONSTRAINT etiquetas_estado_regla CHECK (estado IN ('reference','no_reference')),
    CONSTRAINT etiquetas_candidatos_cantidad_regla CHECK (candidatos_cantidad >= 0),
    CONSTRAINT etiquetas_simulaciones_cantidad_regla CHECK (simulaciones_cantidad >= 0),
    CONSTRAINT etiquetas_estado_evidencia_regla CHECK (estado_evidencia IN ('fixture_only','evaluated')),
    CONSTRAINT etiquetas_plan_si_referencia CHECK ((estado = 'reference') = (plan_id IS NOT NULL)),
    CONSTRAINT etiquetas_motivo_si_sin_referencia CHECK (estado = 'reference' OR motivo IS NOT NULL)
);
COMMENT ON TABLE simulacion.etiquetas IS 'El mejor plan encontrado para un escenario, o «sin referencia» con su motivo. Son los ejemplos de entrenamiento.';
COMMENT ON COLUMN simulacion.etiquetas.etiqueta_id IS 'Identificador.';
COMMENT ON COLUMN simulacion.etiquetas.escenario_id IS 'Escenario.';
COMMENT ON COLUMN simulacion.etiquetas.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.etiquetas.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.etiquetas.busqueda_id IS 'Búsqueda que la produjo.';
COMMENT ON COLUMN simulacion.etiquetas.protocolo_id IS 'Protocolo.';
COMMENT ON COLUMN simulacion.etiquetas.estado IS 'reference (con plan) o no_reference.';
COMMENT ON COLUMN simulacion.etiquetas.plan_id IS 'Plan ganador; vacío sin referencia.';
COMMENT ON COLUMN simulacion.etiquetas.verdes_s IS 'Verde de cada grupo del plan ganador. Unidad: s.';
COMMENT ON COLUMN simulacion.etiquetas.candidatos_cantidad IS 'Candidatos evaluados.';
COMMENT ON COLUMN simulacion.etiquetas.simulaciones_cantidad IS 'Corridas usadas.';
COMMENT ON COLUMN simulacion.etiquetas.estado_evidencia IS 'fixture_only (solo prueba sintética) o evaluated.';
COMMENT ON COLUMN simulacion.etiquetas.motivo IS 'Motivo de no_reference.';
COMMENT ON COLUMN simulacion.etiquetas.red_sha256 IS 'Huella de la red usada.';
COMMENT ON COLUMN simulacion.etiquetas.creada_en IS 'Cuándo se publicó.';
COMMENT ON COLUMN simulacion.etiquetas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.etiquetas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE simulacion.comparadores (
    comparador_id text NOT NULL,
    escenario_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    origen_caso text NOT NULL,
    origen_demanda text NOT NULL,
    origen_evidencia text NOT NULL,
    plan_observado_id text NOT NULL,
    webster_estado text NOT NULL,
    webster_adaptacion text NOT NULL,
    conjunto_parametros text NOT NULL,
    provisional boolean NOT NULL,
    webster_ciclo_s double precision,
    webster_plan_id control.huella,
    webster_reglas_incumplidas jsonb NOT NULL,
    webster_problemas jsonb NOT NULL,
    y_critico double precision,
    tiempo_perdido_s double precision,
    ciclo_recorrido_s double precision,
    carriles_criticos jsonb,
    tramos_perdidos jsonb,
    saturacion_vph_carril double precision NOT NULL,
    equivalencias_vehiculo jsonb NOT NULL,
    estado_parametros text NOT NULL,
    parametros jsonb NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT comparadores_pk PRIMARY KEY (comparador_id),
    CONSTRAINT comparadores_origen_caso_regla CHECK (origen_caso IN ('synthetic','field')),
    CONSTRAINT comparadores_origen_demanda_regla CHECK (origen_demanda IN ('synthetic','field')),
    CONSTRAINT comparadores_origen_evidencia_regla CHECK (origen_evidencia IN ('synthetic','field')),
    CONSTRAINT comparadores_webster_estado_regla CHECK (webster_estado IN ('applicable','not_applicable')),
    CONSTRAINT comparadores_saturacion_vph_carril_regla CHECK (saturacion_vph_carril > 0),
    CONSTRAINT comparadores_estado_parametros_regla CHECK (estado_parametros IN ('provisional','approved')),
    CONSTRAINT comparadores_plan_si_aplica CHECK ((webster_estado = 'applicable') = (webster_plan_id IS NOT NULL))
);
COMMENT ON TABLE simulacion.comparadores IS 'Referencias de comparación de un escenario: el plan vigente y Webster, con su aplicabilidad y sus parámetros.';
COMMENT ON COLUMN simulacion.comparadores.comparador_id IS 'Carpeta de la publicación.';
COMMENT ON COLUMN simulacion.comparadores.escenario_id IS 'Escenario.';
COMMENT ON COLUMN simulacion.comparadores.caso_id IS 'Caso.';
COMMENT ON COLUMN simulacion.comparadores.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN simulacion.comparadores.origen_caso IS 'synthetic o field.';
COMMENT ON COLUMN simulacion.comparadores.origen_demanda IS 'synthetic o field.';
COMMENT ON COLUMN simulacion.comparadores.origen_evidencia IS 'synthetic o field.';
COMMENT ON COLUMN simulacion.comparadores.plan_observado_id IS 'Plan vigente.';
COMMENT ON COLUMN simulacion.comparadores.webster_estado IS 'applicable (aplica) o not_applicable (no aplica).';
COMMENT ON COLUMN simulacion.comparadores.webster_adaptacion IS 'Variante de Webster, por ejemplo webster-solapes-v1.';
COMMENT ON COLUMN simulacion.comparadores.conjunto_parametros IS 'Conjunto de parámetros, por ejemplo webster-parametros-v2.';
COMMENT ON COLUMN simulacion.comparadores.provisional IS 'Si los parámetros siguen sin aprobación del especialista (DEC08).';
COMMENT ON COLUMN simulacion.comparadores.webster_ciclo_s IS 'Ciclo que da la fórmula, sin recortar. Unidad: s.';
COMMENT ON COLUMN simulacion.comparadores.webster_plan_id IS 'Plan de Webster; vacío si no aplica.';
COMMENT ON COLUMN simulacion.comparadores.webster_reglas_incumplidas IS 'Reglas del caso que incumple el plan de Webster.';
COMMENT ON COLUMN simulacion.comparadores.webster_problemas IS 'Por qué no aplica (código, sujeto y mensaje).';
COMMENT ON COLUMN simulacion.comparadores.y_critico IS 'Suma de relaciones de flujo del recorrido crítico.';
COMMENT ON COLUMN simulacion.comparadores.tiempo_perdido_s IS 'Tiempo perdido L del recorrido crítico. Unidad: s.';
COMMENT ON COLUMN simulacion.comparadores.ciclo_recorrido_s IS 'Ciclo que exige el recorrido crítico. Unidad: s.';
COMMENT ON COLUMN simulacion.comparadores.carriles_criticos IS 'Carriles del recorrido crítico.';
COMMENT ON COLUMN simulacion.comparadores.tramos_perdidos IS 'Tramos que cuentan como tiempo perdido.';
COMMENT ON COLUMN simulacion.comparadores.saturacion_vph_carril IS 'Saturación por carril usada. Unidad: veh/h.';
COMMENT ON COLUMN simulacion.comparadores.equivalencias_vehiculo IS 'Equivalencia de cada clase en autos.';
COMMENT ON COLUMN simulacion.comparadores.estado_parametros IS 'provisional o approved.';
COMMENT ON COLUMN simulacion.comparadores.parametros IS 'parametros.json completo.';
COMMENT ON COLUMN simulacion.comparadores.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN simulacion.comparadores.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.conjuntos (
    conjunto_id text NOT NULL,
    particion_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    orden_entradas jsonb NOT NULL,
    orden_salidas jsonb NOT NULL,
    etiquetas_entrenamiento integer NOT NULL,
    etiquetas_validacion integer NOT NULL,
    etiquetas_excluidas integer NOT NULL,
    motivos_exclusion jsonb NOT NULL,
    huella_conjunto control.huella NOT NULL,
    creado_en timestamptz NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT conjuntos_pk PRIMARY KEY (conjunto_id),
    CONSTRAINT conjuntos_etiquetas_entrenamiento_regla CHECK (etiquetas_entrenamiento >= 0),
    CONSTRAINT conjuntos_etiquetas_validacion_regla CHECK (etiquetas_validacion >= 0),
    CONSTRAINT conjuntos_etiquetas_excluidas_regla CHECK (etiquetas_excluidas >= 0)
);
COMMENT ON TABLE aprendizaje.conjuntos IS 'Conjunto de datos de entrenamiento: qué etiquetas, de qué partición y en qué orden de variables.';
COMMENT ON COLUMN aprendizaje.conjuntos.conjunto_id IS 'Identificador.';
COMMENT ON COLUMN aprendizaje.conjuntos.particion_id IS 'Partición de la que sale.';
COMMENT ON COLUMN aprendizaje.conjuntos.caso_id IS 'Caso.';
COMMENT ON COLUMN aprendizaje.conjuntos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN aprendizaje.conjuntos.orden_entradas IS 'Orden exacto de las variables de entrada (flujos y proporciones).';
COMMENT ON COLUMN aprendizaje.conjuntos.orden_salidas IS 'Orden de los tramos variables que predice el modelo.';
COMMENT ON COLUMN aprendizaje.conjuntos.etiquetas_entrenamiento IS 'Etiquetas de train.';
COMMENT ON COLUMN aprendizaje.conjuntos.etiquetas_validacion IS 'Etiquetas de validation.';
COMMENT ON COLUMN aprendizaje.conjuntos.etiquetas_excluidas IS 'Etiquetas excluidas (por ejemplo no_reference).';
COMMENT ON COLUMN aprendizaje.conjuntos.motivos_exclusion IS 'Motivo de cada exclusión.';
COMMENT ON COLUMN aprendizaje.conjuntos.huella_conjunto IS 'Huella del conjunto completo.';
COMMENT ON COLUMN aprendizaje.conjuntos.creado_en IS 'Cuándo se armó.';
COMMENT ON COLUMN aprendizaje.conjuntos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.conjuntos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.conjunto_etiquetas (
    conjunto_id text NOT NULL,
    etiqueta_id text NOT NULL,
    asignacion text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT conjunto_etiquetas_pk PRIMARY KEY (conjunto_id, etiqueta_id),
    CONSTRAINT conjunto_etiquetas_asignacion_regla CHECK (asignacion IN ('train','validation'))
);
COMMENT ON TABLE aprendizaje.conjunto_etiquetas IS 'Qué etiquetas entran a cada conjunto. La base impide meter una etiqueta de prueba.';
COMMENT ON COLUMN aprendizaje.conjunto_etiquetas.conjunto_id IS 'Conjunto.';
COMMENT ON COLUMN aprendizaje.conjunto_etiquetas.etiqueta_id IS 'Etiqueta.';
COMMENT ON COLUMN aprendizaje.conjunto_etiquetas.asignacion IS 'train o validation; nunca test.';
COMMENT ON COLUMN aprendizaje.conjunto_etiquetas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.conjunto_etiquetas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.entrenamientos (
    entrenamiento_id text NOT NULL,
    conjunto_id text NOT NULL,
    algoritmo text NOT NULL,
    configuracion jsonb NOT NULL,
    semilla integer,
    particiones_entrenamiento jsonb NOT NULL,
    politica_reajuste text NOT NULL,
    version_libreria text,
    entorno_id control.huella NOT NULL,
    estado text NOT NULL,
    inicio timestamptz NOT NULL,
    fin timestamptz,
    duracion_s double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT entrenamientos_pk PRIMARY KEY (entrenamiento_id),
    CONSTRAINT entrenamientos_algoritmo_regla CHECK (algoritmo IN ('median','xgboost_per_output')),
    CONSTRAINT entrenamientos_politica_reajuste_regla CHECK (politica_reajuste IN ('train_only','train_plus_validation_after_selection')),
    CONSTRAINT entrenamientos_estado_regla CHECK (estado IN ('succeeded','failed')),
    CONSTRAINT entrenamientos_duracion_s_regla CHECK (duracion_s IS NULL OR duracion_s >= 0)
);
COMMENT ON TABLE aprendizaje.entrenamientos IS 'Cada entrenamiento: algoritmo, configuración, semilla, versiones y costo inicial (I7).';
COMMENT ON COLUMN aprendizaje.entrenamientos.entrenamiento_id IS 'Identificador.';
COMMENT ON COLUMN aprendizaje.entrenamientos.conjunto_id IS 'Conjunto usado.';
COMMENT ON COLUMN aprendizaje.entrenamientos.algoritmo IS 'median (mediana) o xgboost_per_output (un XGBoost por salida).';
COMMENT ON COLUMN aprendizaje.entrenamientos.configuracion IS 'Hiperparámetros y opciones; objeto vacío para la mediana.';
COMMENT ON COLUMN aprendizaje.entrenamientos.semilla IS 'Semilla fija; vacía si el algoritmo no usa azar.';
COMMENT ON COLUMN aprendizaje.entrenamientos.particiones_entrenamiento IS 'train o train y validation (reajuste tras la selección).';
COMMENT ON COLUMN aprendizaje.entrenamientos.politica_reajuste IS 'train_only o train_plus_validation_after_selection.';
COMMENT ON COLUMN aprendizaje.entrenamientos.version_libreria IS 'Versión exacta de XGBoost; vacía para la mediana.';
COMMENT ON COLUMN aprendizaje.entrenamientos.entorno_id IS 'Versiones y equipo.';
COMMENT ON COLUMN aprendizaje.entrenamientos.estado IS 'succeeded o failed.';
COMMENT ON COLUMN aprendizaje.entrenamientos.inicio IS 'Cuándo empezó.';
COMMENT ON COLUMN aprendizaje.entrenamientos.fin IS 'Cuándo terminó.';
COMMENT ON COLUMN aprendizaje.entrenamientos.duracion_s IS 'Costo inicial de entrenar (I7). Unidad: s.';
COMMENT ON COLUMN aprendizaje.entrenamientos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.entrenamientos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.curva_aprendizaje (
    entrenamiento_id text NOT NULL,
    salida text NOT NULL,
    vuelta integer NOT NULL,
    metrica text NOT NULL,
    error_entrenamiento double precision,
    error_validacion double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT curva_aprendizaje_pk PRIMARY KEY (entrenamiento_id, salida, vuelta),
    CONSTRAINT curva_aprendizaje_vuelta_regla CHECK (vuelta >= 0)
);
COMMENT ON TABLE aprendizaje.curva_aprendizaje IS 'Error por vuelta de entrenamiento, con datos de entrenamiento y de validación. Muestra si el modelo aprende o se sobreajusta.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.entrenamiento_id IS 'Entrenamiento.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.salida IS 'Tramo variable predicho, por ejemplo t5.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.vuelta IS 'Número de vuelta (árbol) del entrenamiento.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.metrica IS 'Métrica registrada, por ejemplo error absoluto medio.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.error_entrenamiento IS 'Error con datos de entrenamiento. Unidad: s.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.error_validacion IS 'Error con datos de validación. Unidad: s.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.curva_aprendizaje.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.metricas_modelo (
    entrenamiento_id text NOT NULL,
    particion_id text NOT NULL,
    asignacion text NOT NULL,
    metrica text NOT NULL,
    alcance text NOT NULL,
    valor double precision,
    unidad text NOT NULL,
    numerador integer,
    denominador integer,
    version_calculo text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT metricas_modelo_pk PRIMARY KEY (entrenamiento_id, asignacion, metrica, alcance),
    CONSTRAINT metricas_modelo_asignacion_regla CHECK (asignacion IN ('train','validation','test')),
    CONSTRAINT metricas_modelo_metrica_regla CHECK (metrica IN ('mae','feasibility_original','feasibility_final','coverage','rejections','inference_failures')),
    CONSTRAINT metricas_modelo_fraccion_coherente CHECK (numerador IS NULL OR denominador IS NULL OR (numerador >= 0 AND numerador <= denominador))
);
COMMENT ON TABLE aprendizaje.metricas_modelo IS 'Métricas de cada entrenamiento por partición: error (I5), factibilidad y cobertura (I4), con numerador y denominador.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.entrenamiento_id IS 'Entrenamiento.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.particion_id IS 'Partición evaluada.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.asignacion IS 'train, validation o test (test solo visible tras la apertura).';
COMMENT ON COLUMN aprendizaje.metricas_modelo.metrica IS 'mae, feasibility_original, feasibility_final, coverage, rejections o inference_failures.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.alcance IS 'cycle, el verde de un grupo, un tramo, o all.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.valor IS 'Valor de la métrica; vacío si no hay casos.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.unidad IS 's, fracción o casos.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.numerador IS 'Casos que cumplen.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.denominador IS 'Casos considerados.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.version_calculo IS 'Versión del código que calculó la métrica.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.metricas_modelo.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.errores_por_escenario (
    modelo_id text NOT NULL,
    escenario_id text NOT NULL,
    salida text NOT NULL,
    etiqueta_id text NOT NULL,
    predicho_original_s double precision,
    predicho_final_s double precision,
    referencia_s double precision NOT NULL,
    error_original_s double precision,
    error_final_s double precision,
    estado_prediccion text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT errores_por_escenario_pk PRIMARY KEY (modelo_id, escenario_id, salida),
    CONSTRAINT errores_por_escenario_estado_prediccion_regla CHECK (estado_prediccion IN ('accepted','corrected','rejected','invalid_input','out_of_domain','failed'))
);
COMMENT ON TABLE aprendizaje.errores_por_escenario IS 'Error de cada modelo en cada escenario y salida, antes y después de la corrección.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.modelo_id IS 'Modelo.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.escenario_id IS 'Escenario.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.salida IS 'cycle, el verde de un grupo o un tramo.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.etiqueta_id IS 'Etiqueta de referencia.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.predicho_original_s IS 'Lo que propuso el modelo. Unidad: s.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.predicho_final_s IS 'Lo que quedó tras la corrección. Unidad: s.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.referencia_s IS 'Valor de la etiqueta. Unidad: s.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.error_original_s IS 'Original menos referencia. Unidad: s.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.error_final_s IS 'Final menos referencia. Unidad: s.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.estado_prediccion IS 'accepted, corrected, rejected, invalid_input, out_of_domain o failed.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.errores_por_escenario.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.modelos (
    modelo_id text NOT NULL,
    estado_manifiesto text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    algoritmo text NOT NULL,
    orden_entradas jsonb NOT NULL,
    orden_tramos_variables jsonb NOT NULL,
    version_reglas text NOT NULL,
    particion_id text NOT NULL,
    conjunto_id text NOT NULL,
    entrenamiento_id text NOT NULL,
    particiones_entrenamiento jsonb NOT NULL,
    archivos jsonb NOT NULL,
    entorno jsonb NOT NULL,
    dominio jsonb,
    huella_paquete control.huella,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT modelos_pk PRIMARY KEY (modelo_id),
    CONSTRAINT modelos_estado_manifiesto_regla CHECK (estado_manifiesto IN ('draft','frozen')),
    CONSTRAINT modelos_algoritmo_regla CHECK (algoritmo IN ('median','xgboost_per_output'))
);
COMMENT ON TABLE aprendizaje.modelos IS 'Paquete del modelo entrenado. Su congelamiento es un hito; el paquete no cambia.';
COMMENT ON COLUMN aprendizaje.modelos.modelo_id IS 'Identificador.';
COMMENT ON COLUMN aprendizaje.modelos.estado_manifiesto IS 'draft o frozen, tal como se publicó.';
COMMENT ON COLUMN aprendizaje.modelos.caso_id IS 'Caso.';
COMMENT ON COLUMN aprendizaje.modelos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN aprendizaje.modelos.algoritmo IS 'median o xgboost_per_output.';
COMMENT ON COLUMN aprendizaje.modelos.orden_entradas IS 'Orden de las variables de entrada.';
COMMENT ON COLUMN aprendizaje.modelos.orden_tramos_variables IS 'Orden de los tramos que predice.';
COMMENT ON COLUMN aprendizaje.modelos.version_reglas IS 'Huella de las reglas de factibilidad.';
COMMENT ON COLUMN aprendizaje.modelos.particion_id IS 'Partición usada.';
COMMENT ON COLUMN aprendizaje.modelos.conjunto_id IS 'Conjunto usado.';
COMMENT ON COLUMN aprendizaje.modelos.entrenamiento_id IS 'Entrenamiento que lo produjo.';
COMMENT ON COLUMN aprendizaje.modelos.particiones_entrenamiento IS 'train o train y validation.';
COMMENT ON COLUMN aprendizaje.modelos.archivos IS 'Archivos del modelo con su huella (JSON; nunca pickle).';
COMMENT ON COLUMN aprendizaje.modelos.entorno IS 'Versiones de librerías del paquete.';
COMMENT ON COLUMN aprendizaje.modelos.dominio IS 'Dominio de demanda que acepta; vacío hasta DEV17.';
COMMENT ON COLUMN aprendizaje.modelos.huella_paquete IS 'Huella del paquete completo.';
COMMENT ON COLUMN aprendizaje.modelos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.modelos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.seleccion (
    seleccion_id text NOT NULL,
    particion_id text NOT NULL,
    protocolo_id text NOT NULL,
    huella_seleccion control.huella NOT NULL,
    criterios jsonb NOT NULL,
    candidatos jsonb NOT NULL,
    modelo_ganador_id text NOT NULL,
    motivo text NOT NULL,
    decidido_en timestamptz NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT seleccion_pk PRIMARY KEY (seleccion_id),
    CONSTRAINT seleccion_unica_1 UNIQUE (modelo_ganador_id)
);
COMMENT ON TABLE aprendizaje.seleccion IS 'Decisión de elegir un modelo, con el orden de criterios fijado antes y los candidatos comparados (QA19).';
COMMENT ON COLUMN aprendizaje.seleccion.seleccion_id IS 'Identificador.';
COMMENT ON COLUMN aprendizaje.seleccion.particion_id IS 'Partición con cuya validación se eligió.';
COMMENT ON COLUMN aprendizaje.seleccion.protocolo_id IS 'Protocolo aplicado, obligatorio y congelado antes del modelo.';
COMMENT ON COLUMN aprendizaje.seleccion.huella_seleccion IS 'Huella del registro inmutable de selección.';
COMMENT ON COLUMN aprendizaje.seleccion.criterios IS 'Orden de criterios: factibilidad, cobertura, error en validación y costo.';
COMMENT ON COLUMN aprendizaje.seleccion.candidatos IS 'Modelos comparados y sus métricas de validación.';
COMMENT ON COLUMN aprendizaje.seleccion.modelo_ganador_id IS 'Modelo elegido.';
COMMENT ON COLUMN aprendizaje.seleccion.motivo IS 'Explicación de la decisión.';
COMMENT ON COLUMN aprendizaje.seleccion.decidido_en IS 'Cuándo se decidió.';
COMMENT ON COLUMN aprendizaje.seleccion.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.seleccion.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.consultas (
    request_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    modelo_id text,
    escenario_id text,
    origen text NOT NULL,
    inicio_observacion timestamptz NOT NULL,
    fin_observacion timestamptz NOT NULL,
    fuentes jsonb NOT NULL,
    demanda jsonb NOT NULL,
    estado text NOT NULL,
    duraciones_originales_s jsonb,
    plan_id control.huella,
    verdes_s jsonb,
    tiempos_ms jsonb NOT NULL,
    version_reglas text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT consultas_pk PRIMARY KEY (request_id),
    CONSTRAINT consultas_origen_regla CHECK (origen IN ('synthetic','field')),
    CONSTRAINT consultas_estado_regla CHECK (estado IN ('accepted','corrected','rejected','invalid_input','out_of_domain','failed')),
    CONSTRAINT consultas_plan_si_aceptado CHECK ((estado IN ('accepted','corrected')) = (plan_id IS NOT NULL))
);
COMMENT ON TABLE aprendizaje.consultas IS 'Cada consulta al modelo: entrada, propuesta original, plan final o rechazo, y tiempo por etapa (I4, I7).';
COMMENT ON COLUMN aprendizaje.consultas.request_id IS 'Identificador de la consulta.';
COMMENT ON COLUMN aprendizaje.consultas.caso_id IS 'Caso.';
COMMENT ON COLUMN aprendizaje.consultas.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN aprendizaje.consultas.modelo_id IS 'Modelo; vacío si se rechazó antes de cargar un modelo.';
COMMENT ON COLUMN aprendizaje.consultas.escenario_id IS 'Escenario del que sale la solicitud, si sale de uno.';
COMMENT ON COLUMN aprendizaje.consultas.origen IS 'synthetic o field.';
COMMENT ON COLUMN aprendizaje.consultas.inicio_observacion IS 'Inicio del periodo de la demanda.';
COMMENT ON COLUMN aprendizaje.consultas.fin_observacion IS 'Fin del periodo.';
COMMENT ON COLUMN aprendizaje.consultas.fuentes IS 'Fuentes de la demanda.';
COMMENT ON COLUMN aprendizaje.consultas.demanda IS 'Demanda por movimiento con su composición (entrada).';
COMMENT ON COLUMN aprendizaje.consultas.estado IS 'accepted (aceptado), corrected (corregido), rejected (rechazado), invalid_input, out_of_domain o failed.';
COMMENT ON COLUMN aprendizaje.consultas.duraciones_originales_s IS 'Lo que propuso el modelo antes de corregir. Unidad: s.';
COMMENT ON COLUMN aprendizaje.consultas.plan_id IS 'Plan final; vacío si no hay plan.';
COMMENT ON COLUMN aprendizaje.consultas.verdes_s IS 'Verde de cada grupo del plan final. Unidad: s.';
COMMENT ON COLUMN aprendizaje.consultas.tiempos_ms IS 'Tiempo de cada etapa de la consulta. Unidad: ms.';
COMMENT ON COLUMN aprendizaje.consultas.version_reglas IS 'Huella de las reglas usadas.';
COMMENT ON COLUMN aprendizaje.consultas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.consultas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.consulta_tramos (
    request_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    tramo_id text NOT NULL,
    duracion_original_s double precision,
    duracion_final_s double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT consulta_tramos_pk PRIMARY KEY (request_id, tramo_id)
);
COMMENT ON TABLE aprendizaje.consulta_tramos IS 'Duración propuesta y final de cada tramo en una consulta.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.request_id IS 'Consulta.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.caso_id IS 'Caso.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.tramo_id IS 'Tramo.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.duracion_original_s IS 'Lo que propuso el modelo; vacío en tramos fijos. Unidad: s.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.duracion_final_s IS 'Lo que quedó; vacío si se rechazó. Unidad: s.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.consulta_tramos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE aprendizaje.consulta_reglas (
    request_id text NOT NULL,
    orden integer NOT NULL,
    codigo text NOT NULL,
    campo text,
    mensaje text NOT NULL,
    artefacto_referido text,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT consulta_reglas_pk PRIMARY KEY (request_id, orden),
    CONSTRAINT consulta_reglas_orden_regla CHECK (orden >= 0)
);
COMMENT ON TABLE aprendizaje.consulta_reglas IS 'Reglas incumplidas y errores de cada consulta.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.request_id IS 'Consulta.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.orden IS 'Posición en la lista de errores.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.codigo IS 'Código, por ejemplo PLAN_INFEASIBLE u OUT_OF_DOMAIN.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.campo IS 'Campo afectado.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.mensaje IS 'Explicación.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.artefacto_referido IS 'Artefacto mencionado por el error.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN aprendizaje.consulta_reglas.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE evaluacion.experimentos (
    experimento_id text NOT NULL,
    caso_id text NOT NULL,
    caso_version text NOT NULL,
    protocolo_id text NOT NULL,
    particion_id text NOT NULL,
    modelo_id text NOT NULL,
    seleccion_id text NOT NULL,
    alternativas jsonb NOT NULL,
    creado_en timestamptz NOT NULL,
    huella_experimento control.huella NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT experimentos_pk PRIMARY KEY (experimento_id),
    CONSTRAINT experimentos_unica_1 UNIQUE (particion_id)
);
COMMENT ON TABLE evaluacion.experimentos IS 'Experimento de evaluación: protocolo, partición y modelo congelados. Su apertura es un hito.';
COMMENT ON COLUMN evaluacion.experimentos.experimento_id IS 'Identificador.';
COMMENT ON COLUMN evaluacion.experimentos.caso_id IS 'Caso.';
COMMENT ON COLUMN evaluacion.experimentos.caso_version IS 'Versión del caso.';
COMMENT ON COLUMN evaluacion.experimentos.protocolo_id IS 'Protocolo congelado.';
COMMENT ON COLUMN evaluacion.experimentos.particion_id IS 'Partición cuya prueba se usa.';
COMMENT ON COLUMN evaluacion.experimentos.modelo_id IS 'Modelo congelado.';
COMMENT ON COLUMN evaluacion.experimentos.seleccion_id IS 'Selección fijada al congelar ese modelo.';
COMMENT ON COLUMN evaluacion.experimentos.alternativas IS 'Alternativas comparadas: modelo, mediana, vigente, Webster y búsqueda.';
COMMENT ON COLUMN evaluacion.experimentos.creado_en IS 'Cuándo se preparó.';
COMMENT ON COLUMN evaluacion.experimentos.huella_experimento IS 'Huella de lo congelado.';
COMMENT ON COLUMN evaluacion.experimentos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN evaluacion.experimentos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE evaluacion.comparaciones (
    comparacion_id text NOT NULL,
    experimento_id text NOT NULL,
    escenario_id text NOT NULL,
    alternativa text NOT NULL,
    semilla integer NOT NULL,
    aplicable boolean NOT NULL,
    motivo_no_aplicable text,
    run_id text,
    plan_id control.huella,
    request_id text,
    etiqueta_id text,
    comparador_id text,
    rutas_sha256 control.huella,
    red_sha256 control.huella,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT comparaciones_pk PRIMARY KEY (comparacion_id),
    CONSTRAINT comparaciones_unica_1 UNIQUE (experimento_id, escenario_id, alternativa, semilla),
    CONSTRAINT comparaciones_alternativa_regla CHECK (alternativa IN ('model','median','current_plan','webster','search')),
    CONSTRAINT comparaciones_motivo_si_no_aplica CHECK (aplicable OR motivo_no_aplicable IS NOT NULL)
);
COMMENT ON TABLE evaluacion.comparaciones IS 'Una alternativa aplicada a un escenario de prueba con una semilla final, con las huellas que prueban que todas usaron la misma demanda.';
COMMENT ON COLUMN evaluacion.comparaciones.comparacion_id IS 'Identificador.';
COMMENT ON COLUMN evaluacion.comparaciones.experimento_id IS 'Experimento.';
COMMENT ON COLUMN evaluacion.comparaciones.escenario_id IS 'Escenario de prueba.';
COMMENT ON COLUMN evaluacion.comparaciones.alternativa IS 'model, median, current_plan, webster o search.';
COMMENT ON COLUMN evaluacion.comparaciones.semilla IS 'Semilla final.';
COMMENT ON COLUMN evaluacion.comparaciones.aplicable IS 'Si la alternativa se pudo calcular.';
COMMENT ON COLUMN evaluacion.comparaciones.motivo_no_aplicable IS 'Por qué no; vacío si aplica.';
COMMENT ON COLUMN evaluacion.comparaciones.run_id IS 'Corrida que la mide; vacía si no aplica.';
COMMENT ON COLUMN evaluacion.comparaciones.plan_id IS 'Plan aplicado.';
COMMENT ON COLUMN evaluacion.comparaciones.request_id IS 'Consulta que dio el plan (modelo y mediana).';
COMMENT ON COLUMN evaluacion.comparaciones.etiqueta_id IS 'Etiqueta que dio el plan (búsqueda).';
COMMENT ON COLUMN evaluacion.comparaciones.comparador_id IS 'Comparadores que dieron el plan (vigente y Webster).';
COMMENT ON COLUMN evaluacion.comparaciones.rutas_sha256 IS 'Huella de la demanda materializada; igual en todas las alternativas del mismo escenario y semilla.';
COMMENT ON COLUMN evaluacion.comparaciones.red_sha256 IS 'Huella de la red.';
COMMENT ON COLUMN evaluacion.comparaciones.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN evaluacion.comparaciones.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE evaluacion.diferencias (
    diferencia_id text NOT NULL,
    experimento_id text NOT NULL,
    comparacion_a_id text NOT NULL,
    comparacion_b_id text NOT NULL,
    metrica text NOT NULL,
    alcance text NOT NULL,
    valor_a double precision,
    valor_b double precision,
    diferencia double precision,
    unidad text NOT NULL,
    censurada boolean NOT NULL,
    veredicto text NOT NULL,
    tolerancia double precision,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT diferencias_pk PRIMARY KEY (diferencia_id),
    CONSTRAINT diferencias_metrica_regla CHECK (metrica IN ('delay','queue','stops')),
    CONSTRAINT diferencias_veredicto_regla CHECK (veredicto IN ('a_lower','b_lower','equal','undetermined','not_comparable')),
    CONSTRAINT diferencias_par_distinto CHECK (comparacion_a_id <> comparacion_b_id)
);
COMMENT ON TABLE evaluacion.diferencias IS 'Diferencia emparejada entre dos alternativas en un escenario y una semilla (I6).';
COMMENT ON COLUMN evaluacion.diferencias.diferencia_id IS 'Identificador.';
COMMENT ON COLUMN evaluacion.diferencias.experimento_id IS 'Experimento.';
COMMENT ON COLUMN evaluacion.diferencias.comparacion_a_id IS 'Primera alternativa.';
COMMENT ON COLUMN evaluacion.diferencias.comparacion_b_id IS 'Segunda alternativa.';
COMMENT ON COLUMN evaluacion.diferencias.metrica IS 'delay (demora), queue (cola) o stops (detenciones).';
COMMENT ON COLUMN evaluacion.diferencias.alcance IS 'total o un acceso.';
COMMENT ON COLUMN evaluacion.diferencias.valor_a IS 'Valor de a.';
COMMENT ON COLUMN evaluacion.diferencias.valor_b IS 'Valor de b.';
COMMENT ON COLUMN evaluacion.diferencias.diferencia IS 'a menos b; vacía si no es comparable.';
COMMENT ON COLUMN evaluacion.diferencias.unidad IS 's, veh o detenciones por vehículo.';
COMMENT ON COLUMN evaluacion.diferencias.censurada IS 'Si alguna tiene viajes sin terminar o cola incompleta.';
COMMENT ON COLUMN evaluacion.diferencias.veredicto IS 'a_lower, b_lower, equal, undetermined o not_comparable.';
COMMENT ON COLUMN evaluacion.diferencias.tolerancia IS 'Tolerancia del empate.';
COMMENT ON COLUMN evaluacion.diferencias.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN evaluacion.diferencias.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE evaluacion.indicadores (
    indicador_id text NOT NULL,
    experimento_id text NOT NULL,
    indicador text NOT NULL,
    metrica text NOT NULL,
    alternativa_a text NOT NULL,
    alternativa_b text,
    alcance text NOT NULL,
    valor double precision,
    unidad text NOT NULL,
    numerador integer,
    denominador integer,
    faltantes integer,
    ic_nivel double precision,
    ic_inferior double precision,
    ic_superior double precision,
    remuestreos integer,
    semilla_remuestreo integer,
    agregacion text,
    version_calculo text NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT indicadores_pk PRIMARY KEY (indicador_id),
    CONSTRAINT indicadores_indicador_regla CHECK (indicador IN ('I4','I5','I6','I7')),
    CONSTRAINT indicadores_intervalo_ordenado CHECK (ic_inferior IS NULL OR ic_superior IS NULL OR ic_inferior <= ic_superior)
);
COMMENT ON TABLE evaluacion.indicadores IS 'Indicadores finales I4 a I7: valor, numerador, denominador, faltantes e intervalo de confianza.';
COMMENT ON COLUMN evaluacion.indicadores.indicador_id IS 'Identificador.';
COMMENT ON COLUMN evaluacion.indicadores.experimento_id IS 'Experimento.';
COMMENT ON COLUMN evaluacion.indicadores.indicador IS 'I4, I5, I6 o I7.';
COMMENT ON COLUMN evaluacion.indicadores.metrica IS 'Métrica concreta, por ejemplo diferencia de demora.';
COMMENT ON COLUMN evaluacion.indicadores.alternativa_a IS 'Alternativa evaluada.';
COMMENT ON COLUMN evaluacion.indicadores.alternativa_b IS 'Referencia comparada; vacía si no es una diferencia.';
COMMENT ON COLUMN evaluacion.indicadores.alcance IS 'global, una familia o un acceso.';
COMMENT ON COLUMN evaluacion.indicadores.valor IS 'Valor del indicador.';
COMMENT ON COLUMN evaluacion.indicadores.unidad IS 'Unidad.';
COMMENT ON COLUMN evaluacion.indicadores.numerador IS 'Casos que cumplen.';
COMMENT ON COLUMN evaluacion.indicadores.denominador IS 'Casos considerados.';
COMMENT ON COLUMN evaluacion.indicadores.faltantes IS 'Pares sin resultado, que no se ocultan.';
COMMENT ON COLUMN evaluacion.indicadores.ic_nivel IS 'Nivel del intervalo.';
COMMENT ON COLUMN evaluacion.indicadores.ic_inferior IS 'Límite inferior.';
COMMENT ON COLUMN evaluacion.indicadores.ic_superior IS 'Límite superior.';
COMMENT ON COLUMN evaluacion.indicadores.remuestreos IS 'Remuestreos del bootstrap por grupos.';
COMMENT ON COLUMN evaluacion.indicadores.semilla_remuestreo IS 'Semilla del bootstrap.';
COMMENT ON COLUMN evaluacion.indicadores.agregacion IS 'Cómo se agregan los grupos.';
COMMENT ON COLUMN evaluacion.indicadores.version_calculo IS 'Versión del código que lo calculó.';
COMMENT ON COLUMN evaluacion.indicadores.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN evaluacion.indicadores.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

CREATE TABLE evaluacion.costos (
    costo_id text NOT NULL,
    proceso_tipo text NOT NULL,
    proceso_id text NOT NULL,
    etapa text NOT NULL,
    duracion_s double precision NOT NULL,
    simulaciones integer,
    consultas integer,
    entorno_id control.huella NOT NULL,
    medido_en timestamptz NOT NULL,
    carga_id text NOT NULL,
    artefacto_id text NOT NULL,
    CONSTRAINT costos_pk PRIMARY KEY (costo_id),
    CONSTRAINT costos_proceso_tipo_regla CHECK (proceso_tipo IN ('search','label_generation','training','query_cold','query_warm','evaluation')),
    CONSTRAINT costos_etapa_regla CHECK (etapa IN ('initial','query','evaluation')),
    CONSTRAINT costos_duracion_s_regla CHECK (duracion_s >= 0)
);
COMMENT ON TABLE evaluacion.costos IS 'Costo computacional de cada proceso, separado en inicial, por consulta y de evaluación (I7).';
COMMENT ON COLUMN evaluacion.costos.costo_id IS 'Identificador.';
COMMENT ON COLUMN evaluacion.costos.proceso_tipo IS 'search, label_generation, training, query_cold, query_warm o evaluation.';
COMMENT ON COLUMN evaluacion.costos.proceso_id IS 'Identificador del proceso medido; sin clave foránea porque puede venir de varias tablas.';
COMMENT ON COLUMN evaluacion.costos.etapa IS 'initial (costo inicial), query (por consulta) o evaluation.';
COMMENT ON COLUMN evaluacion.costos.duracion_s IS 'Tiempo total. Unidad: s.';
COMMENT ON COLUMN evaluacion.costos.simulaciones IS 'Corridas incluidas, si aplica.';
COMMENT ON COLUMN evaluacion.costos.consultas IS 'Consultas incluidas, si aplica.';
COMMENT ON COLUMN evaluacion.costos.entorno_id IS 'Equipo y versiones.';
COMMENT ON COLUMN evaluacion.costos.medido_en IS 'Cuándo se midió.';
COMMENT ON COLUMN evaluacion.costos.carga_id IS 'Carga que escribió la fila.';
COMMENT ON COLUMN evaluacion.costos.artefacto_id IS 'Archivo de datos/ (o acta del repositorio) del que sale la fila.';

-- Relaciones: se agregan al final para que el orden de las tablas no importe.
ALTER TABLE control.artefactos ADD CONSTRAINT artefactos_fk_1 FOREIGN KEY (manifiesto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE control.artefactos ADD CONSTRAINT artefactos_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE control.archivo_escenarios ADD CONSTRAINT archivo_escenarios_fk_1 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE control.archivo_escenarios ADD CONSTRAINT archivo_escenarios_fk_2 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE control.archivo_escenarios ADD CONSTRAINT archivo_escenarios_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE control.entornos ADD CONSTRAINT entornos_fk_1 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE control.entornos ADD CONSTRAINT entornos_fk_2 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE control.hitos ADD CONSTRAINT hitos_fk_1 FOREIGN KEY (protocolo_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE control.hitos ADD CONSTRAINT hitos_fk_2 FOREIGN KEY (particion_id) REFERENCES experimento.particiones (particion_id);
ALTER TABLE control.hitos ADD CONSTRAINT hitos_fk_3 FOREIGN KEY (modelo_id) REFERENCES aprendizaje.modelos (modelo_id);
ALTER TABLE control.hitos ADD CONSTRAINT hitos_fk_4 FOREIGN KEY (experimento_id) REFERENCES evaluacion.experimentos (experimento_id);
ALTER TABLE control.hitos ADD CONSTRAINT hitos_fk_5 FOREIGN KEY (seleccion_id) REFERENCES aprendizaje.seleccion (seleccion_id);
ALTER TABLE control.hitos ADD CONSTRAINT hitos_fk_6 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE control.hitos ADD CONSTRAINT hitos_fk_7 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE control.conflictos ADD CONSTRAINT conflictos_fk_1 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE control.conflictos ADD CONSTRAINT conflictos_fk_2 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE control.replicas ADD CONSTRAINT replicas_fk_1 FOREIGN KEY (run_id_a) REFERENCES simulacion.corridas (run_id);
ALTER TABLE control.replicas ADD CONSTRAINT replicas_fk_2 FOREIGN KEY (run_id_b) REFERENCES simulacion.corridas (run_id);
ALTER TABLE control.replicas ADD CONSTRAINT replicas_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE control.replicas ADD CONSTRAINT replicas_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.casos ADD CONSTRAINT casos_fk_1 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.casos ADD CONSTRAINT casos_fk_2 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.movimientos ADD CONSTRAINT movimientos_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE caso.movimientos ADD CONSTRAINT movimientos_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.movimientos ADD CONSTRAINT movimientos_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.tipos_vehiculo ADD CONSTRAINT tipos_vehiculo_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE caso.tipos_vehiculo ADD CONSTRAINT tipos_vehiculo_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.tipos_vehiculo ADD CONSTRAINT tipos_vehiculo_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.tramos ADD CONSTRAINT tramos_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE caso.tramos ADD CONSTRAINT tramos_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.tramos ADD CONSTRAINT tramos_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.grupos_verde ADD CONSTRAINT grupos_verde_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE caso.grupos_verde ADD CONSTRAINT grupos_verde_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.grupos_verde ADD CONSTRAINT grupos_verde_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.grupo_tramo ADD CONSTRAINT grupo_tramo_fk_1 FOREIGN KEY (caso_id, caso_version, grupo_id) REFERENCES caso.grupos_verde (caso_id, caso_version, grupo_id);
ALTER TABLE caso.grupo_tramo ADD CONSTRAINT grupo_tramo_fk_2 FOREIGN KEY (caso_id, caso_version, tramo_id) REFERENCES caso.tramos (caso_id, caso_version, tramo_id);
ALTER TABLE caso.grupo_tramo ADD CONSTRAINT grupo_tramo_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.grupo_tramo ADD CONSTRAINT grupo_tramo_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.planes_observados ADD CONSTRAINT planes_observados_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE caso.planes_observados ADD CONSTRAINT planes_observados_fk_2 FOREIGN KEY (plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE caso.planes_observados ADD CONSTRAINT planes_observados_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.planes_observados ADD CONSTRAINT planes_observados_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.aforos ADD CONSTRAINT aforos_fk_1 FOREIGN KEY (caso_id, caso_version, movimiento_id) REFERENCES caso.movimientos (caso_id, caso_version, movimiento_id);
ALTER TABLE caso.aforos ADD CONSTRAINT aforos_fk_2 FOREIGN KEY (caso_id, caso_version, clase_id) REFERENCES caso.tipos_vehiculo (caso_id, caso_version, clase_id);
ALTER TABLE caso.aforos ADD CONSTRAINT aforos_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.aforos ADD CONSTRAINT aforos_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.aforos_control ADD CONSTRAINT aforos_control_fk_1 FOREIGN KEY (caso_id, caso_version, movimiento_id) REFERENCES caso.movimientos (caso_id, caso_version, movimiento_id);
ALTER TABLE caso.aforos_control ADD CONSTRAINT aforos_control_fk_2 FOREIGN KEY (caso_id, caso_version, clase_id) REFERENCES caso.tipos_vehiculo (caso_id, caso_version, clase_id);
ALTER TABLE caso.aforos_control ADD CONSTRAINT aforos_control_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.aforos_control ADD CONSTRAINT aforos_control_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.calidad_aforos ADD CONSTRAINT calidad_aforos_fk_1 FOREIGN KEY (reporte_id) REFERENCES caso.reportes_calidad (reporte_id);
ALTER TABLE caso.calidad_aforos ADD CONSTRAINT calidad_aforos_fk_2 FOREIGN KEY (caso_id, caso_version, movimiento_id) REFERENCES caso.movimientos (caso_id, caso_version, movimiento_id);
ALTER TABLE caso.calidad_aforos ADD CONSTRAINT calidad_aforos_fk_3 FOREIGN KEY (caso_id, caso_version, clase_id) REFERENCES caso.tipos_vehiculo (caso_id, caso_version, clase_id);
ALTER TABLE caso.calidad_aforos ADD CONSTRAINT calidad_aforos_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.calidad_aforos ADD CONSTRAINT calidad_aforos_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.reportes_calidad ADD CONSTRAINT reportes_calidad_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE caso.reportes_calidad ADD CONSTRAINT reportes_calidad_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.reportes_calidad ADD CONSTRAINT reportes_calidad_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.calibracion_intentos ADD CONSTRAINT calibracion_intentos_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE caso.calibracion_intentos ADD CONSTRAINT calibracion_intentos_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.calibracion_intentos ADD CONSTRAINT calibracion_intentos_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE caso.calibracion_contraste ADD CONSTRAINT calibracion_contraste_fk_1 FOREIGN KEY (intento_id) REFERENCES caso.calibracion_intentos (intento_id);
ALTER TABLE caso.calibracion_contraste ADD CONSTRAINT calibracion_contraste_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE caso.calibracion_contraste ADD CONSTRAINT calibracion_contraste_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE experimento.familias ADD CONSTRAINT familias_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE experimento.familias ADD CONSTRAINT familias_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE experimento.familias ADD CONSTRAINT familias_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE experimento.escenarios ADD CONSTRAINT escenarios_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE experimento.escenarios ADD CONSTRAINT escenarios_fk_2 FOREIGN KEY (caso_id, caso_version, familia_id) REFERENCES experimento.familias (caso_id, caso_version, familia_id);
ALTER TABLE experimento.escenarios ADD CONSTRAINT escenarios_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE experimento.escenarios ADD CONSTRAINT escenarios_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE experimento.demanda ADD CONSTRAINT demanda_fk_1 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE experimento.demanda ADD CONSTRAINT demanda_fk_2 FOREIGN KEY (caso_id, caso_version, movimiento_id) REFERENCES caso.movimientos (caso_id, caso_version, movimiento_id);
ALTER TABLE experimento.demanda ADD CONSTRAINT demanda_fk_3 FOREIGN KEY (caso_id, caso_version, clase_id) REFERENCES caso.tipos_vehiculo (caso_id, caso_version, clase_id);
ALTER TABLE experimento.demanda ADD CONSTRAINT demanda_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE experimento.demanda ADD CONSTRAINT demanda_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE experimento.particiones ADD CONSTRAINT particiones_fk_1 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE experimento.particiones ADD CONSTRAINT particiones_fk_2 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE experimento.asignaciones ADD CONSTRAINT asignaciones_fk_1 FOREIGN KEY (particion_id) REFERENCES experimento.particiones (particion_id);
ALTER TABLE experimento.asignaciones ADD CONSTRAINT asignaciones_fk_2 FOREIGN KEY (escenario_id, familia_id) REFERENCES experimento.escenarios (escenario_id, familia_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE experimento.asignaciones ADD CONSTRAINT asignaciones_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE experimento.asignaciones ADD CONSTRAINT asignaciones_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE experimento.protocolos ADD CONSTRAINT protocolos_fk_1 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE experimento.protocolos ADD CONSTRAINT protocolos_fk_2 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE experimento.protocolo_semillas ADD CONSTRAINT protocolo_semillas_fk_1 FOREIGN KEY (protocolo_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE experimento.protocolo_semillas ADD CONSTRAINT protocolo_semillas_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE experimento.protocolo_semillas ADD CONSTRAINT protocolo_semillas_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.planes ADD CONSTRAINT planes_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE simulacion.planes ADD CONSTRAINT planes_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.planes ADD CONSTRAINT planes_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.plan_tramos ADD CONSTRAINT plan_tramos_fk_1 FOREIGN KEY (plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE simulacion.plan_tramos ADD CONSTRAINT plan_tramos_fk_2 FOREIGN KEY (caso_id, caso_version, tramo_id) REFERENCES caso.tramos (caso_id, caso_version, tramo_id);
ALTER TABLE simulacion.plan_tramos ADD CONSTRAINT plan_tramos_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.plan_tramos ADD CONSTRAINT plan_tramos_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_2 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_3 FOREIGN KEY (protocolo_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_4 FOREIGN KEY (plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_5 FOREIGN KEY (entorno_id) REFERENCES control.entornos (entorno_id);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_6 FOREIGN KEY (reintento_de) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_7 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.corridas ADD CONSTRAINT corridas_fk_8 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.resultados_corrida ADD CONSTRAINT resultados_corrida_fk_1 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.resultados_corrida ADD CONSTRAINT resultados_corrida_fk_2 FOREIGN KEY (artefacto_metricas_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.resultados_corrida ADD CONSTRAINT resultados_corrida_fk_3 FOREIGN KEY (protocolo_metricas_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE simulacion.resultados_corrida ADD CONSTRAINT resultados_corrida_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.resultados_corrida ADD CONSTRAINT resultados_corrida_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.resultados_acceso ADD CONSTRAINT resultados_acceso_fk_1 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.resultados_acceso ADD CONSTRAINT resultados_acceso_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.resultados_acceso ADD CONSTRAINT resultados_acceso_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.resultados_movimiento ADD CONSTRAINT resultados_movimiento_fk_1 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.resultados_movimiento ADD CONSTRAINT resultados_movimiento_fk_2 FOREIGN KEY (caso_id, caso_version, movimiento_id) REFERENCES caso.movimientos (caso_id, caso_version, movimiento_id);
ALTER TABLE simulacion.resultados_movimiento ADD CONSTRAINT resultados_movimiento_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.resultados_movimiento ADD CONSTRAINT resultados_movimiento_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.vehiculos ADD CONSTRAINT vehiculos_fk_1 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.vehiculos ADD CONSTRAINT vehiculos_fk_2 FOREIGN KEY (caso_id, caso_version, movimiento_id) REFERENCES caso.movimientos (caso_id, caso_version, movimiento_id);
ALTER TABLE simulacion.vehiculos ADD CONSTRAINT vehiculos_fk_3 FOREIGN KEY (caso_id, caso_version, clase_id) REFERENCES caso.tipos_vehiculo (caso_id, caso_version, clase_id);
ALTER TABLE simulacion.vehiculos ADD CONSTRAINT vehiculos_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.vehiculos ADD CONSTRAINT vehiculos_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.eventos ADD CONSTRAINT eventos_fk_1 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.eventos ADD CONSTRAINT eventos_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.eventos ADD CONSTRAINT eventos_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.cola_por_acceso ADD CONSTRAINT cola_por_acceso_fk_1 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.cola_por_acceso ADD CONSTRAINT cola_por_acceso_fk_2 FOREIGN KEY (run_id) REFERENCES simulacion.resultados_corrida (run_id);
ALTER TABLE simulacion.cola_por_acceso ADD CONSTRAINT cola_por_acceso_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.cola_por_acceso ADD CONSTRAINT cola_por_acceso_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.busquedas ADD CONSTRAINT busquedas_fk_1 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE simulacion.busquedas ADD CONSTRAINT busquedas_fk_2 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE simulacion.busquedas ADD CONSTRAINT busquedas_fk_3 FOREIGN KEY (protocolo_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE simulacion.busquedas ADD CONSTRAINT busquedas_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.busquedas ADD CONSTRAINT busquedas_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.candidatos ADD CONSTRAINT candidatos_fk_1 FOREIGN KEY (busqueda_id) REFERENCES simulacion.busquedas (busqueda_id);
ALTER TABLE simulacion.candidatos ADD CONSTRAINT candidatos_fk_2 FOREIGN KEY (plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE simulacion.candidatos ADD CONSTRAINT candidatos_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.candidatos ADD CONSTRAINT candidatos_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.candidato_semillas ADD CONSTRAINT candidato_semillas_fk_1 FOREIGN KEY (busqueda_id, candidato_id) REFERENCES simulacion.candidatos (busqueda_id, candidato_id);
ALTER TABLE simulacion.candidato_semillas ADD CONSTRAINT candidato_semillas_fk_2 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE simulacion.candidato_semillas ADD CONSTRAINT candidato_semillas_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.candidato_semillas ADD CONSTRAINT candidato_semillas_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.etiquetas ADD CONSTRAINT etiquetas_fk_1 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE simulacion.etiquetas ADD CONSTRAINT etiquetas_fk_2 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE simulacion.etiquetas ADD CONSTRAINT etiquetas_fk_3 FOREIGN KEY (busqueda_id) REFERENCES simulacion.busquedas (busqueda_id);
ALTER TABLE simulacion.etiquetas ADD CONSTRAINT etiquetas_fk_4 FOREIGN KEY (protocolo_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE simulacion.etiquetas ADD CONSTRAINT etiquetas_fk_5 FOREIGN KEY (plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE simulacion.etiquetas ADD CONSTRAINT etiquetas_fk_6 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.etiquetas ADD CONSTRAINT etiquetas_fk_7 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE simulacion.comparadores ADD CONSTRAINT comparadores_fk_1 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE simulacion.comparadores ADD CONSTRAINT comparadores_fk_2 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE simulacion.comparadores ADD CONSTRAINT comparadores_fk_3 FOREIGN KEY (plan_observado_id) REFERENCES caso.planes_observados (plan_observado_id);
ALTER TABLE simulacion.comparadores ADD CONSTRAINT comparadores_fk_4 FOREIGN KEY (webster_plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE simulacion.comparadores ADD CONSTRAINT comparadores_fk_5 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE simulacion.comparadores ADD CONSTRAINT comparadores_fk_6 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.conjuntos ADD CONSTRAINT conjuntos_fk_1 FOREIGN KEY (particion_id) REFERENCES experimento.particiones (particion_id);
ALTER TABLE aprendizaje.conjuntos ADD CONSTRAINT conjuntos_fk_2 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE aprendizaje.conjuntos ADD CONSTRAINT conjuntos_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.conjuntos ADD CONSTRAINT conjuntos_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.conjunto_etiquetas ADD CONSTRAINT conjunto_etiquetas_fk_1 FOREIGN KEY (conjunto_id) REFERENCES aprendizaje.conjuntos (conjunto_id);
ALTER TABLE aprendizaje.conjunto_etiquetas ADD CONSTRAINT conjunto_etiquetas_fk_2 FOREIGN KEY (etiqueta_id) REFERENCES simulacion.etiquetas (etiqueta_id);
ALTER TABLE aprendizaje.conjunto_etiquetas ADD CONSTRAINT conjunto_etiquetas_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.conjunto_etiquetas ADD CONSTRAINT conjunto_etiquetas_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.entrenamientos ADD CONSTRAINT entrenamientos_fk_1 FOREIGN KEY (conjunto_id) REFERENCES aprendizaje.conjuntos (conjunto_id);
ALTER TABLE aprendizaje.entrenamientos ADD CONSTRAINT entrenamientos_fk_2 FOREIGN KEY (entorno_id) REFERENCES control.entornos (entorno_id);
ALTER TABLE aprendizaje.entrenamientos ADD CONSTRAINT entrenamientos_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.entrenamientos ADD CONSTRAINT entrenamientos_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.curva_aprendizaje ADD CONSTRAINT curva_aprendizaje_fk_1 FOREIGN KEY (entrenamiento_id) REFERENCES aprendizaje.entrenamientos (entrenamiento_id);
ALTER TABLE aprendizaje.curva_aprendizaje ADD CONSTRAINT curva_aprendizaje_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.curva_aprendizaje ADD CONSTRAINT curva_aprendizaje_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.metricas_modelo ADD CONSTRAINT metricas_modelo_fk_1 FOREIGN KEY (entrenamiento_id) REFERENCES aprendizaje.entrenamientos (entrenamiento_id);
ALTER TABLE aprendizaje.metricas_modelo ADD CONSTRAINT metricas_modelo_fk_2 FOREIGN KEY (particion_id) REFERENCES experimento.particiones (particion_id);
ALTER TABLE aprendizaje.metricas_modelo ADD CONSTRAINT metricas_modelo_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.metricas_modelo ADD CONSTRAINT metricas_modelo_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.errores_por_escenario ADD CONSTRAINT errores_por_escenario_fk_1 FOREIGN KEY (modelo_id) REFERENCES aprendizaje.modelos (modelo_id);
ALTER TABLE aprendizaje.errores_por_escenario ADD CONSTRAINT errores_por_escenario_fk_2 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE aprendizaje.errores_por_escenario ADD CONSTRAINT errores_por_escenario_fk_3 FOREIGN KEY (etiqueta_id) REFERENCES simulacion.etiquetas (etiqueta_id);
ALTER TABLE aprendizaje.errores_por_escenario ADD CONSTRAINT errores_por_escenario_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.errores_por_escenario ADD CONSTRAINT errores_por_escenario_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.modelos ADD CONSTRAINT modelos_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE aprendizaje.modelos ADD CONSTRAINT modelos_fk_2 FOREIGN KEY (particion_id) REFERENCES experimento.particiones (particion_id);
ALTER TABLE aprendizaje.modelos ADD CONSTRAINT modelos_fk_3 FOREIGN KEY (conjunto_id) REFERENCES aprendizaje.conjuntos (conjunto_id);
ALTER TABLE aprendizaje.modelos ADD CONSTRAINT modelos_fk_4 FOREIGN KEY (entrenamiento_id) REFERENCES aprendizaje.entrenamientos (entrenamiento_id);
ALTER TABLE aprendizaje.modelos ADD CONSTRAINT modelos_fk_5 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.modelos ADD CONSTRAINT modelos_fk_6 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.seleccion ADD CONSTRAINT seleccion_fk_1 FOREIGN KEY (particion_id) REFERENCES experimento.particiones (particion_id);
ALTER TABLE aprendizaje.seleccion ADD CONSTRAINT seleccion_fk_2 FOREIGN KEY (protocolo_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE aprendizaje.seleccion ADD CONSTRAINT seleccion_fk_3 FOREIGN KEY (modelo_ganador_id) REFERENCES aprendizaje.modelos (modelo_id);
ALTER TABLE aprendizaje.seleccion ADD CONSTRAINT seleccion_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.seleccion ADD CONSTRAINT seleccion_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.consultas ADD CONSTRAINT consultas_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE aprendizaje.consultas ADD CONSTRAINT consultas_fk_2 FOREIGN KEY (modelo_id) REFERENCES aprendizaje.modelos (modelo_id);
ALTER TABLE aprendizaje.consultas ADD CONSTRAINT consultas_fk_3 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE aprendizaje.consultas ADD CONSTRAINT consultas_fk_4 FOREIGN KEY (plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE aprendizaje.consultas ADD CONSTRAINT consultas_fk_5 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.consultas ADD CONSTRAINT consultas_fk_6 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.consulta_tramos ADD CONSTRAINT consulta_tramos_fk_1 FOREIGN KEY (request_id) REFERENCES aprendizaje.consultas (request_id);
ALTER TABLE aprendizaje.consulta_tramos ADD CONSTRAINT consulta_tramos_fk_2 FOREIGN KEY (caso_id, caso_version, tramo_id) REFERENCES caso.tramos (caso_id, caso_version, tramo_id);
ALTER TABLE aprendizaje.consulta_tramos ADD CONSTRAINT consulta_tramos_fk_3 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.consulta_tramos ADD CONSTRAINT consulta_tramos_fk_4 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE aprendizaje.consulta_reglas ADD CONSTRAINT consulta_reglas_fk_1 FOREIGN KEY (request_id) REFERENCES aprendizaje.consultas (request_id);
ALTER TABLE aprendizaje.consulta_reglas ADD CONSTRAINT consulta_reglas_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE aprendizaje.consulta_reglas ADD CONSTRAINT consulta_reglas_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE evaluacion.experimentos ADD CONSTRAINT experimentos_fk_1 FOREIGN KEY (caso_id, caso_version) REFERENCES caso.casos (caso_id, caso_version);
ALTER TABLE evaluacion.experimentos ADD CONSTRAINT experimentos_fk_2 FOREIGN KEY (protocolo_id) REFERENCES experimento.protocolos (protocolo_id);
ALTER TABLE evaluacion.experimentos ADD CONSTRAINT experimentos_fk_3 FOREIGN KEY (particion_id) REFERENCES experimento.particiones (particion_id);
ALTER TABLE evaluacion.experimentos ADD CONSTRAINT experimentos_fk_4 FOREIGN KEY (modelo_id) REFERENCES aprendizaje.modelos (modelo_id);
ALTER TABLE evaluacion.experimentos ADD CONSTRAINT experimentos_fk_5 FOREIGN KEY (seleccion_id) REFERENCES aprendizaje.seleccion (seleccion_id);
ALTER TABLE evaluacion.experimentos ADD CONSTRAINT experimentos_fk_6 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE evaluacion.experimentos ADD CONSTRAINT experimentos_fk_7 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_1 FOREIGN KEY (experimento_id) REFERENCES evaluacion.experimentos (experimento_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_2 FOREIGN KEY (escenario_id) REFERENCES experimento.escenarios (escenario_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_3 FOREIGN KEY (run_id) REFERENCES simulacion.corridas (run_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_4 FOREIGN KEY (plan_id) REFERENCES simulacion.planes (plan_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_5 FOREIGN KEY (request_id) REFERENCES aprendizaje.consultas (request_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_6 FOREIGN KEY (etiqueta_id) REFERENCES simulacion.etiquetas (etiqueta_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_7 FOREIGN KEY (comparador_id) REFERENCES simulacion.comparadores (comparador_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_8 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE evaluacion.comparaciones ADD CONSTRAINT comparaciones_fk_9 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE evaluacion.diferencias ADD CONSTRAINT diferencias_fk_1 FOREIGN KEY (experimento_id) REFERENCES evaluacion.experimentos (experimento_id);
ALTER TABLE evaluacion.diferencias ADD CONSTRAINT diferencias_fk_2 FOREIGN KEY (comparacion_a_id) REFERENCES evaluacion.comparaciones (comparacion_id);
ALTER TABLE evaluacion.diferencias ADD CONSTRAINT diferencias_fk_3 FOREIGN KEY (comparacion_b_id) REFERENCES evaluacion.comparaciones (comparacion_id);
ALTER TABLE evaluacion.diferencias ADD CONSTRAINT diferencias_fk_4 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE evaluacion.diferencias ADD CONSTRAINT diferencias_fk_5 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE evaluacion.indicadores ADD CONSTRAINT indicadores_fk_1 FOREIGN KEY (experimento_id) REFERENCES evaluacion.experimentos (experimento_id);
ALTER TABLE evaluacion.indicadores ADD CONSTRAINT indicadores_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE evaluacion.indicadores ADD CONSTRAINT indicadores_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);
ALTER TABLE evaluacion.costos ADD CONSTRAINT costos_fk_1 FOREIGN KEY (entorno_id) REFERENCES control.entornos (entorno_id);
ALTER TABLE evaluacion.costos ADD CONSTRAINT costos_fk_2 FOREIGN KEY (carga_id) REFERENCES control.cargas (carga_id);
ALTER TABLE evaluacion.costos ADD CONSTRAINT costos_fk_3 FOREIGN KEY (artefacto_id) REFERENCES control.artefactos (artefacto_id);

CREATE INDEX corridas_ix_escenario_id ON simulacion.corridas (escenario_id);
CREATE INDEX corridas_ix_plan_id ON simulacion.corridas (plan_id);
CREATE INDEX corridas_ix_protocolo_id_etapa ON simulacion.corridas (protocolo_id, etapa);
