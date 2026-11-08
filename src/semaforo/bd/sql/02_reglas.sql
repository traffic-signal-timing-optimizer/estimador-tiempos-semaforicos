-- Base «semaforo»: funciones, disparadores, índices de los hitos y vistas (DEV31 F3).
-- Escrito a mano. Se aplica después de 01_tablas.sql (generado) y antes de 03_seguridad.sql.
-- Lo que hace cada función está descrito en docs/bd/esquema.toml («funciones» y «vistas»).
--
-- Códigos de error propios (SQLSTATE) para que el cargador los distinga:
--   SM001 orden de los hitos; SM002 asignación de una familia; SM003 escenario preliminar a prueba;
--   SM004 corrida final o semilla fuera de su etapa; SM005 etiqueta fuera de su partición;
--   SM006 cola con un valor que no corresponde a un paso de su corrida; SM009 solo agregar.

-- ---------------------------------------------------------------------------------------------
-- Cegado de la prueba: la zona se deduce de las asignaciones y de los hitos (acta de F1).

CREATE FUNCTION control.prueba_abierta(p_particion text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, control AS $$
    SELECT EXISTS (
        SELECT 1 FROM control.hitos
        WHERE tipo = 'test_opened' AND particion_id = p_particion
    )
$$;
COMMENT ON FUNCTION control.prueba_abierta(text) IS
    'Verdadero si existe un hito test_opened para esa partición.';

-- La versión es la huella de estos archivos: no se puede escribir aquí. Esta función queda
-- vacía y apply_schema la reemplaza al terminar, dentro de la misma transacción.
CREATE FUNCTION control.version_esquema() RETURNS text LANGUAGE sql IMMUTABLE
    AS $$ SELECT NULL::text $$;

CREATE VIEW control.escenarios_cegados WITH (security_invoker = true) AS
    SELECT a.escenario_id, a.particion_id
    FROM experimento.asignaciones AS a
    WHERE a.asignacion = 'test' AND NOT control.prueba_abierta(a.particion_id);
COMMENT ON VIEW control.escenarios_cegados IS
    'Escenarios asignados a test en una partición cuya prueba no tiene hito de apertura. Es la base del cegado.';

CREATE FUNCTION control.escenario_visible(p_escenario text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, control AS $$
    SELECT NOT EXISTS (
        SELECT 1 FROM control.escenarios_cegados
        WHERE escenario_id = p_escenario
    )
$$;
COMMENT ON FUNCTION control.escenario_visible(text) IS
    'Filtro explícito de las vistas del panel, que se evalúan con permisos de su dueño.';

CREATE FUNCTION control.archivo_visible(p_artefacto text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, control AS $$
    SELECT EXISTS (
        SELECT 1 FROM control.artefactos AS archivo
        WHERE archivo.artefacto_id = p_artefacto
          AND (
              archivo.alcance = 'global'
              OR (
                  archivo.alcance = 'escenarios'
                  AND EXISTS (
                      SELECT 1 FROM control.archivo_escenarios AS enlace
                      WHERE enlace.artefacto_id = archivo.artefacto_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM control.archivo_escenarios AS enlace
                      JOIN control.escenarios_cegados AS cegado
                        ON cegado.escenario_id = enlace.escenario_id
                      WHERE enlace.artefacto_id = archivo.artefacto_id
                  )
              )
          )
    )
$$;
COMMENT ON FUNCTION control.archivo_visible(text) IS
    'La misma regla de cegado se usa en control.artefactos y control.archivo_escenarios.';

-- ---------------------------------------------------------------------------------------------
-- Solo agregar (B2), con las dos excepciones declaradas: cerrar una carga y decidir un conflicto.

CREATE FUNCTION control.bloquear_cambios() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND TG_TABLE_SCHEMA = 'control' THEN
        IF TG_TABLE_NAME = 'cargas' THEN
            IF OLD.estado = 'running' AND NEW.estado <> 'running'
                AND (NEW.carga_id, NEW.inicio, NEW.comando, NEW.version_paquete,
                     NEW.commit_codigo, NEW.arbol_limpio, NEW.version_postgres,
                     NEW.version_esquema)
                    IS NOT DISTINCT FROM
                    (OLD.carga_id, OLD.inicio, OLD.comando, OLD.version_paquete,
                     OLD.commit_codigo, OLD.arbol_limpio, OLD.version_postgres,
                     OLD.version_esquema)
            THEN
                RETURN NEW;
            END IF;
        ELSIF TG_TABLE_NAME = 'conflictos' THEN
            IF OLD.decision IS NULL AND NEW.decision IS NOT NULL
                AND (NEW.conflicto_id, NEW.tipo, NEW.tabla_destino, NEW.clave,
                     NEW.huella_cargada, NEW.huella_nueva, NEW.detalle, NEW.detectado_en,
                     NEW.carga_id, NEW.artefacto_id)
                    IS NOT DISTINCT FROM
                    (OLD.conflicto_id, OLD.tipo, OLD.tabla_destino, OLD.clave,
                     OLD.huella_cargada, OLD.huella_nueva, OLD.detalle, OLD.detectado_en,
                     OLD.carga_id, OLD.artefacto_id)
            THEN
                RETURN NEW;
            END IF;
        END IF;
    END IF;
    RAISE EXCEPTION 'la tabla %.% solo admite agregar filas: % rechazado',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'SM009';
END
$$;
COMMENT ON FUNCTION control.bloquear_cambios() IS
    'Rechaza UPDATE, DELETE y TRUNCATE en todas las tablas, salvo cerrar una carga y decidir un conflicto.';

-- ---------------------------------------------------------------------------------------------
-- Orden de los hitos: protocolo y partición congelados antes que el modelo; modelo congelado
-- antes de abrir la prueba. Un solo hito de cada tipo por objeto.

CREATE UNIQUE INDEX hitos_un_protocolo ON control.hitos (protocolo_id) WHERE tipo = 'protocol_frozen';
CREATE UNIQUE INDEX hitos_una_particion ON control.hitos (particion_id) WHERE tipo = 'split_frozen';
CREATE UNIQUE INDEX hitos_un_modelo ON control.hitos (modelo_id) WHERE tipo = 'model_frozen';
CREATE UNIQUE INDEX hitos_un_experimento ON control.hitos (experimento_id) WHERE tipo = 'test_opened';

CREATE FUNCTION control.validar_hito() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_particion text;
    v_protocolo text;
    v_modelo text;
    v_seleccion text;
    v_huella_seleccion text;
    v_fecha_seleccion timestamptz;
BEGIN
    IF NEW.tipo = 'protocol_frozen' THEN
        IF NOT EXISTS (
            SELECT 1 FROM experimento.protocolos
            WHERE protocolo_id = NEW.protocolo_id AND estado = 'frozen'
        ) THEN
            RAISE EXCEPTION 'el protocolo % no está cargado como congelado (frozen)', NEW.protocolo_id
                USING ERRCODE = 'SM001';
        END IF;
    ELSIF NEW.tipo = 'model_frozen' THEN
        SELECT m.particion_id, s.protocolo_id, s.seleccion_id, s.huella_seleccion, s.decidido_en
        INTO v_particion, v_protocolo, v_seleccion, v_huella_seleccion, v_fecha_seleccion
        FROM aprendizaje.modelos AS m
        JOIN aprendizaje.seleccion AS s ON s.modelo_ganador_id = m.modelo_id
        WHERE m.modelo_id = NEW.modelo_id;
        IF v_seleccion IS NULL OR v_seleccion IS DISTINCT FROM NEW.seleccion_id
            OR v_huella_seleccion IS DISTINCT FROM NEW.huella_seleccion
            OR NOT EXISTS (
                SELECT 1 FROM aprendizaje.seleccion
                WHERE seleccion_id = v_seleccion AND particion_id = v_particion
            ) OR v_fecha_seleccion > NEW.registrado_en
        THEN
            RAISE EXCEPTION 'la selección del modelo % no coincide con la selección fijada antes del hito',
                NEW.modelo_id USING ERRCODE = 'SM001';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM control.hitos WHERE tipo = 'split_frozen' AND particion_id = v_particion
                AND registrado_en < NEW.registrado_en
        ) THEN
            RAISE EXCEPTION 'antes de congelar el modelo % hay que congelar su partición %',
                NEW.modelo_id, v_particion USING ERRCODE = 'SM001';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM control.hitos WHERE tipo = 'protocol_frozen'
                AND protocolo_id = v_protocolo AND registrado_en < NEW.registrado_en
        ) THEN
            RAISE EXCEPTION 'antes de congelar el modelo % hay que congelar el protocolo % de su selección',
                NEW.modelo_id, v_protocolo
                USING ERRCODE = 'SM001';
        END IF;
    ELSIF NEW.tipo = 'test_opened' THEN
        SELECT particion_id, protocolo_id, modelo_id, seleccion_id
        INTO v_particion, v_protocolo, v_modelo, v_seleccion
        FROM evaluacion.experimentos WHERE experimento_id = NEW.experimento_id;
        IF v_particion IS DISTINCT FROM NEW.particion_id THEN
            RAISE EXCEPTION 'la partición % no es la del experimento %', NEW.particion_id,
                NEW.experimento_id USING ERRCODE = 'SM001';
        END IF;
        IF NOT EXISTS (
                SELECT 1 FROM control.hitos AS h
                JOIN aprendizaje.seleccion AS s ON s.seleccion_id = h.seleccion_id
                JOIN aprendizaje.modelos AS m ON m.modelo_id = h.modelo_id
                WHERE h.tipo = 'model_frozen' AND h.modelo_id = v_modelo
                    AND h.seleccion_id = v_seleccion
                    AND h.huella_seleccion = s.huella_seleccion
                    AND s.modelo_ganador_id = v_modelo
                    AND s.particion_id = v_particion AND m.particion_id = v_particion
                    AND s.protocolo_id = v_protocolo
                    AND h.registrado_en < NEW.registrado_en
            )
            OR NOT EXISTS (
                SELECT 1 FROM control.hitos WHERE tipo = 'protocol_frozen'
                    AND protocolo_id = v_protocolo AND registrado_en < NEW.registrado_en
            )
            OR NOT EXISTS (
                SELECT 1 FROM control.hitos WHERE tipo = 'split_frozen'
                    AND particion_id = v_particion AND registrado_en < NEW.registrado_en
            )
        THEN
            RAISE EXCEPTION 'la prueba del experimento % solo se abre con su protocolo, su partición y su modelo congelados antes',
                NEW.experimento_id USING ERRCODE = 'SM001';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
COMMENT ON FUNCTION control.validar_hito() IS
    'Exige el orden de los hitos: protocolo y partición congelados antes que el modelo; modelo congelado antes de abrir la prueba.';
CREATE TRIGGER validar_hito BEFORE INSERT ON control.hitos
    FOR EACH ROW EXECUTE FUNCTION control.validar_hito();

-- ---------------------------------------------------------------------------------------------
-- Asignaciones: una familia completa va a una sola partición y asignación, y un escenario
-- cargado como preliminar no pasa a prueba. Se comprueba al confirmar la transacción, porque la
-- partición y sus escenarios se cargan juntos.

CREATE FUNCTION experimento.validar_asignacion() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.asignacion = 'test' AND EXISTS (
        SELECT 1 FROM experimento.escenarios WHERE escenario_id = NEW.escenario_id AND preliminar
    ) THEN
        RAISE EXCEPTION 'el escenario % se cargó como preliminar y no puede pasar a prueba',
            NEW.escenario_id USING ERRCODE = 'SM003';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM experimento.asignaciones AS otra
        JOIN experimento.escenarios AS suyo ON suyo.escenario_id = otra.escenario_id
        JOIN experimento.escenarios AS nuevo ON nuevo.escenario_id = NEW.escenario_id
        WHERE otra.familia_id = NEW.familia_id
          AND suyo.caso_id = nuevo.caso_id AND suyo.caso_version = nuevo.caso_version
          AND (otra.particion_id <> NEW.particion_id OR otra.asignacion <> NEW.asignacion)
    ) THEN
        RAISE EXCEPTION 'la familia % no va completa a una sola partición y asignación', NEW.familia_id
            USING ERRCODE = 'SM002';
    END IF;
    RETURN NULL;
END
$$;
COMMENT ON FUNCTION experimento.validar_asignacion() IS
    'Una familia completa va a una sola partición y asignación; un escenario cargado como preliminar no puede pasar a test.';
CREATE CONSTRAINT TRIGGER validar_asignacion AFTER INSERT ON experimento.asignaciones
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION experimento.validar_asignacion();

-- ---------------------------------------------------------------------------------------------
-- Corridas: la etapa final solo en escenarios asignados a prueba, y la semilla de una búsqueda,
-- de finalistas o final pertenece a esa etapa del protocolo.

CREATE FUNCTION simulacion.validar_corrida() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.etapa = 'final' AND NOT EXISTS (
        SELECT 1 FROM experimento.asignaciones
        WHERE escenario_id = NEW.escenario_id AND asignacion = 'test'
    ) THEN
        RAISE EXCEPTION 'la corrida % es final y su escenario % no está asignado a prueba',
            NEW.run_id, NEW.escenario_id USING ERRCODE = 'SM004';
    END IF;
    IF NEW.etapa IN ('search', 'finalists', 'final') AND NOT EXISTS (
        SELECT 1 FROM experimento.protocolo_semillas
        WHERE protocolo_id = NEW.protocolo_id AND etapa = NEW.etapa AND semilla = NEW.semilla_sumo
    ) THEN
        RAISE EXCEPTION 'la semilla % de la corrida % no es de la etapa % del protocolo %',
            NEW.semilla_sumo, NEW.run_id, NEW.etapa, NEW.protocolo_id USING ERRCODE = 'SM004';
    END IF;
    RETURN NEW;
END
$$;
COMMENT ON FUNCTION simulacion.validar_corrida() IS
    'La etapa final solo en escenarios asignados a test; la semilla debe pertenecer a la etapa del protocolo.';
CREATE TRIGGER validar_corrida BEFORE INSERT ON simulacion.corridas
    FOR EACH ROW EXECUTE FUNCTION simulacion.validar_corrida();

-- La cola de cada acceso tiene un valor por paso de la serie de su corrida (DEV31 F4, arreglo por
-- acceso). La clave foránea hace que la corrida ya esté escrita (resultados_corrida va primero).
CREATE FUNCTION simulacion.validar_cola() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_pasos double precision[];
    v_ventana boolean[];
BEGIN
    SELECT r.pasos_cola_s, r.pasos_en_ventana INTO v_pasos, v_ventana
    FROM simulacion.resultados_corrida AS r
    WHERE r.run_id = NEW.run_id;
    IF v_pasos IS NULL OR v_ventana IS NULL
        OR cardinality(NEW.vehiculos_en_cola) <> cardinality(v_pasos)
        OR cardinality(v_pasos) <> cardinality(v_ventana)
        OR EXISTS (
            SELECT 1 FROM generate_subscripts(v_pasos, 1) AS s(i)
            WHERE s.i > 1 AND v_pasos[s.i] <= v_pasos[s.i - 1]
        ) THEN
        RAISE EXCEPTION 'la cola del acceso % de la corrida % no tiene un valor por paso',
            NEW.acceso, NEW.run_id USING ERRCODE = 'SM006';
    END IF;
    RETURN NEW;
END
$$;
COMMENT ON FUNCTION simulacion.validar_cola() IS
    'Cada acceso tiene un valor por paso; los tiempos son estrictamente crecientes.';
CREATE TRIGGER validar_cola BEFORE INSERT ON simulacion.cola_por_acceso
    FOR EACH ROW EXECUTE FUNCTION simulacion.validar_cola();

-- ---------------------------------------------------------------------------------------------
-- Conjuntos de entrenamiento: una etiqueta entra con la asignación que su escenario tiene en la
-- partición del conjunto (nunca test, que además impide la regla de la columna).

CREATE FUNCTION aprendizaje.validar_conjunto_etiqueta() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_asignacion text;
BEGIN
    SELECT a.asignacion INTO v_asignacion
    FROM aprendizaje.conjuntos AS c
    JOIN simulacion.etiquetas AS e ON e.etiqueta_id = NEW.etiqueta_id
    JOIN experimento.asignaciones AS a
        ON a.particion_id = c.particion_id AND a.escenario_id = e.escenario_id
    WHERE c.conjunto_id = NEW.conjunto_id;
    IF v_asignacion IS DISTINCT FROM NEW.asignacion THEN
        RAISE EXCEPTION 'la etiqueta % no tiene la asignación % en la partición del conjunto %',
            NEW.etiqueta_id, NEW.asignacion, NEW.conjunto_id USING ERRCODE = 'SM005';
    END IF;
    RETURN NEW;
END
$$;
COMMENT ON FUNCTION aprendizaje.validar_conjunto_etiqueta() IS
    'Una etiqueta entra a un conjunto solo si su escenario está asignado a train o validation en la misma partición.';
CREATE TRIGGER validar_conjunto_etiqueta BEFORE INSERT ON aprendizaje.conjunto_etiquetas
    FOR EACH ROW EXECUTE FUNCTION aprendizaje.validar_conjunto_etiqueta();

-- ---------------------------------------------------------------------------------------------
-- Vistas (B12): las aprobadas para el panel tienen filtros explícitos, pues el panel carece de
-- permisos de tabla y las lee con permisos del dueño. La vista de cargas no se concede al panel.

CREATE VIEW vistas.zona_escenario WITH (security_invoker = true) AS
    SELECT
        e.escenario_id, e.caso_id, e.caso_version, e.familia_id, e.origen, e.preliminar,
        a.particion_id, a.asignacion,
        CASE WHEN a.asignacion = 'test' THEN 'prueba' ELSE 'desarrollo' END AS zona,
        CASE WHEN a.asignacion = 'test' THEN control.prueba_abierta(a.particion_id) END
            AS prueba_abierta
    FROM experimento.escenarios AS e
    LEFT JOIN experimento.asignaciones AS a ON a.escenario_id = e.escenario_id
    WHERE control.escenario_visible(e.escenario_id);
COMMENT ON VIEW vistas.zona_escenario IS
    'Cada escenario con su partición, su asignación, su zona (desarrollo o prueba) y si su prueba ya se abrió.';

CREATE VIEW vistas.estado_hitos WITH (security_invoker = true) AS
    SELECT
        h.hito_id, h.tipo, h.registrado_en, h.protocolo_id, h.particion_id, h.modelo_id,
        h.experimento_id, h.huella_objeto, h.commit_codigo, h.responsable, h.notas,
        a.ruta_relativa AS acta, a.sha256 AS acta_sha256
    FROM control.hitos AS h
    JOIN control.artefactos AS a ON a.artefacto_id = h.artefacto_id;
COMMENT ON VIEW vistas.estado_hitos IS
    'Línea de tiempo de los hitos del procedimiento, con su acta y su commit.';

CREATE VIEW vistas.estado_cargas WITH (security_invoker = true) AS
    SELECT
        c.carga_id, c.estado, c.inicio, c.fin, c.version_paquete, c.commit_codigo,
        c.arbol_limpio, c.version_postgres, c.version_esquema, c.artefactos_leidos,
        c.artefactos_cargados, c.artefactos_rechazados, c.huella_contenido,
        (SELECT count(*) FROM control.artefactos AS a
            WHERE a.carga_id = c.carga_id AND a.estado <> 'intact') AS artefactos_no_intactos,
        (SELECT count(*) FROM control.conflictos AS f
            WHERE f.carga_id = c.carga_id AND f.decision IS NULL) AS conflictos_pendientes
    FROM control.cargas AS c;
COMMENT ON VIEW vistas.estado_cargas IS
    'Cargas, artefactos cargados y rechazados, y conflictos pendientes.';

CREATE VIEW vistas.corridas_resumen WITH (security_invoker = true) AS
    SELECT
        c.run_id, c.caso_id, c.caso_version, c.escenario_id, e.familia_id, c.plan_id, p.ciclo_s,
        c.etapa, c.estado, c.semilla_sumo, c.protocolo_id, c.duracion_s, c.terminacion,
        r.vehiculos_insertados, r.viajes_terminados, r.viajes_sin_terminar,
        r.teletransportes_total, r.choques, r.avisos_sumo, r.estado_demora, r.demora_media_s,
        r.cota_inf_demora_s, r.estado_cola, r.cola_media_veh, r.cola_maxima_veh,
        r.estado_detenciones, r.detenciones_media, r.origen_evidencia
    FROM simulacion.corridas AS c
    JOIN experimento.escenarios AS e ON e.escenario_id = c.escenario_id
    LEFT JOIN simulacion.planes AS p ON p.plan_id = c.plan_id
    LEFT JOIN simulacion.resultados_corrida AS r ON r.run_id = c.run_id
    WHERE control.escenario_visible(c.escenario_id);
COMMENT ON VIEW vistas.corridas_resumen IS
    'Una fila por corrida con su escenario, familia, plan, etapa, estado y resultados principales.';

CREATE VIEW vistas.vehiculos_cohorte WITH (security_invoker = true) AS
    SELECT
        v.run_id, v.vehiculo_id, v.caso_id, v.caso_version, v.movimiento_id, v.clase_id,
        v.acceso, v.estado, v.salida_programada_s, v.perdida_tiempo_cohorte_s,
        v.demora_salida_cohorte_s,
        v.perdida_tiempo_cohorte_s + v.demora_salida_cohorte_s AS demora_s,
        v.fuente_demora_salida, v.detenciones
    FROM simulacion.vehiculos AS v
    JOIN simulacion.corridas AS c ON c.run_id = v.run_id
    WHERE v.en_cohorte AND control.escenario_visible(c.escenario_id);
COMMENT ON VIEW vistas.vehiculos_cohorte IS
    'Vehículos de la cohorte con su demora (pérdida de tiempo más espera de salida, según la definición del protocolo).';

-- Una fila por corrida, acceso y paso. ROWS FROM recorre los tres arreglos nativos a la vez;
-- validar_cola() garantiza que tienen la misma longitud.
CREATE VIEW vistas.cola_por_segundo WITH (security_invoker = true) AS
    SELECT q.run_id, q.acceso,
        s.tiempo_s, s.vehiculos_en_cola, s.en_ventana
    FROM simulacion.cola_por_acceso AS q
    JOIN simulacion.resultados_corrida AS r ON r.run_id = q.run_id
    JOIN simulacion.corridas AS c ON c.run_id = q.run_id
    CROSS JOIN LATERAL ROWS FROM (
        unnest(r.pasos_cola_s),
        unnest(q.vehiculos_en_cola),
        unnest(r.pasos_en_ventana)
    ) AS s(tiempo_s, vehiculos_en_cola, en_ventana)
    WHERE control.escenario_visible(c.escenario_id);
COMMENT ON VIEW vistas.cola_por_segundo IS
    'Cola por corrida, acceso y paso. El panel y las consultas leen esta vista, nunca la tabla.';

CREATE VIEW vistas.busquedas_resumen WITH (security_invoker = true) AS
    SELECT
        b.busqueda_id, b.escenario_id, b.caso_id, b.caso_version, b.protocolo_id, b.metodo,
        b.presupuesto, b.presupuesto_usado, b.intentos, b.simulaciones, b.interrumpida,
        b.estado_seleccion, b.motivo_sin_referencia,
        t.etiqueta_id, t.estado AS estado_etiqueta, t.plan_id AS plan_ganador_id,
        (SELECT count(*) FROM simulacion.candidatos AS c
            WHERE c.busqueda_id = b.busqueda_id) AS candidatos,
        (SELECT count(*) FROM simulacion.candidatos AS c
            WHERE c.busqueda_id = b.busqueda_id AND c.elegible_busqueda) AS elegibles_busqueda,
        (SELECT count(*) FROM simulacion.candidatos AS c
            WHERE c.busqueda_id = b.busqueda_id AND c.finalista) AS finalistas,
        (SELECT count(*) FROM simulacion.candidatos AS c
            WHERE c.busqueda_id = b.busqueda_id AND c.elegible_finalistas) AS elegibles_finalistas,
        b.cobertura AS motivos_descarte
    FROM simulacion.busquedas AS b
    LEFT JOIN simulacion.etiquetas AS t ON t.busqueda_id = b.busqueda_id
    WHERE control.escenario_visible(b.escenario_id);
COMMENT ON VIEW vistas.busquedas_resumen IS
    'Una fila por búsqueda con su etiqueta, sus candidatos elegibles y sus motivos de descarte.';

CREATE VIEW vistas.etiquetas_entrenamiento WITH (security_invoker = true) AS
    SELECT
        t.etiqueta_id, t.escenario_id, t.caso_id, t.caso_version, t.protocolo_id, t.plan_id,
        t.verdes_s, a.particion_id, a.asignacion
    FROM simulacion.etiquetas AS t
    JOIN experimento.asignaciones AS a ON a.escenario_id = t.escenario_id
    WHERE t.estado = 'reference' AND a.asignacion IN ('train', 'validation')
        AND control.escenario_visible(t.escenario_id);
COMMENT ON VIEW vistas.etiquetas_entrenamiento IS
    'Etiquetas con referencia y la asignación de su escenario (solo train y validation).';

CREATE VIEW vistas.metricas_modelos WITH (security_invoker = true) AS
    SELECT
        m.entrenamiento_id, e.algoritmo, e.conjunto_id, m.particion_id, m.metrica, m.alcance,
        m.unidad,
        max(m.valor) FILTER (WHERE m.asignacion = 'train') AS valor_entrenamiento,
        max(m.valor) FILTER (WHERE m.asignacion = 'validation') AS valor_validacion,
        max(m.valor) FILTER (WHERE m.asignacion = 'test') AS valor_prueba
    FROM aprendizaje.metricas_modelo AS m
    JOIN aprendizaje.entrenamientos AS e ON e.entrenamiento_id = m.entrenamiento_id
    WHERE m.asignacion <> 'test' OR control.prueba_abierta(m.particion_id)
    GROUP BY m.entrenamiento_id, e.algoritmo, e.conjunto_id, m.particion_id, m.metrica,
        m.alcance, m.unidad;
COMMENT ON VIEW vistas.metricas_modelos IS
    'Métricas de cada entrenamiento por partición, en columnas, para comparar la mediana con XGBoost.';

CREATE VIEW vistas.consultas_resumen WITH (security_invoker = true) AS
    SELECT
        q.request_id, q.caso_id, q.caso_version, q.modelo_id, q.escenario_id, q.origen,
        q.estado, q.plan_id, q.verdes_s, q.tiempos_ms, q.version_reglas,
        (SELECT count(*) FROM aprendizaje.consulta_reglas AS r
            WHERE r.request_id = q.request_id) AS reglas_incumplidas,
        (SELECT coalesce(jsonb_agg(r.codigo ORDER BY r.orden), '[]'::jsonb)
            FROM aprendizaje.consulta_reglas AS r WHERE r.request_id = q.request_id) AS codigos
    FROM aprendizaje.consultas AS q
    WHERE q.escenario_id IS NULL OR control.escenario_visible(q.escenario_id);
COMMENT ON VIEW vistas.consultas_resumen IS
    'Consultas con su estado, sus tiempos y sus reglas incumplidas.';

CREATE VIEW vistas.indicadores_finales WITH (security_invoker = true) AS
    SELECT
        i.indicador_id, i.experimento_id, x.protocolo_id, x.particion_id, x.modelo_id,
        i.indicador, i.metrica, i.alternativa_a, i.alternativa_b, i.alcance, i.valor, i.unidad,
        i.numerador, i.denominador, i.faltantes, i.ic_nivel, i.ic_inferior, i.ic_superior,
        i.remuestreos, i.semilla_remuestreo, i.agregacion, i.version_calculo
    FROM evaluacion.indicadores AS i
    JOIN evaluacion.experimentos AS x ON x.experimento_id = i.experimento_id
    WHERE EXISTS (
        SELECT 1 FROM control.hitos AS h
        WHERE h.tipo = 'test_opened' AND h.experimento_id = i.experimento_id
    );
COMMENT ON VIEW vistas.indicadores_finales IS
    'Indicadores I4 a I7 del experimento final con sus intervalos. Vacía hasta la apertura.';

-- ---------------------------------------------------------------------------------------------
-- Vistas de entradas y de procedencia para el panel (DEV31 F5). El panel las lee con permisos del
-- dueño, que no está sujeto al cegado por filas: cada una lleva su filtro explícito. El caso y los
-- protocolos son públicos (ADR07); lo que cuelga de un escenario se filtra por ese escenario. Las
-- semillas de la etapa final no se muestran: son parte de lo que la prueba mantiene reservado.

CREATE VIEW vistas.estado_base WITH (security_invoker = true) AS
    SELECT
        control.version_esquema() AS version_esquema,
        u.carga_id AS ultima_carga_id, u.estado AS ultima_carga_estado, u.fin AS ultima_carga_fin,
        u.commit_codigo, u.arbol_limpio, u.version_postgres, u.huella_contenido,
        (SELECT count(*) FROM control.conflictos AS f WHERE f.decision IS NULL)
            AS conflictos_pendientes,
        (SELECT count(*) FROM control.artefactos AS a WHERE a.alcance = 'desconocido')
            AS archivos_alcance_desconocido
    FROM (SELECT 1) AS una
    LEFT JOIN LATERAL (
        SELECT c.* FROM control.cargas AS c
        WHERE c.estado = 'completed' AND c.huella_contenido IS NOT NULL
        ORDER BY c.inicio DESC, c.carga_id DESC LIMIT 1
    ) AS u ON true;
COMMENT ON VIEW vistas.estado_base IS
    'Versión del esquema, última carga completa con su huella, conflictos pendientes y archivos de alcance desconocido. Solo conteos globales: no dice cuántos archivos o filas tiene la prueba.';

CREATE VIEW vistas.caso_resumen WITH (security_invoker = true) AS
    SELECT
        c.caso_id, c.caso_version, c.origen, c.descripcion, c.estado_representacion, c.red_ruta,
        c.red_sha256, c.tick_s, c.ciclo_min_s, c.ciclo_max_s, c.politica_frontera,
        c.evidencia_restricciones, c.huella_caso,
        a.ruta_relativa AS archivo, a.sha256 AS archivo_sha256,
        (SELECT coalesce(array_agg(t.clase_id ORDER BY t.orden), '{}'::text[])
            FROM caso.tipos_vehiculo AS t
            WHERE t.caso_id = c.caso_id AND t.caso_version = c.caso_version) AS clases
    FROM caso.casos AS c
    JOIN control.artefactos AS a ON a.artefacto_id = c.artefacto_id;
COMMENT ON VIEW vistas.caso_resumen IS
    'El caso: identidad, origen, límites del ciclo, clases de vehículo y su archivo con huella.';

CREATE VIEW vistas.caso_movimientos WITH (security_invoker = true) AS
    SELECT
        m.caso_id, m.caso_version, m.movimiento_id, m.orden, m.acceso, m.carriles_entrada,
        m.aristas_salida, m.flujo_min_vph, m.flujo_max_vph
    FROM caso.movimientos AS m;
COMMENT ON VIEW vistas.caso_movimientos IS
    'Los movimientos del caso: de qué acceso salen, por qué carriles y qué flujo admiten.';

CREATE VIEW vistas.caso_tramos WITH (security_invoker = true) AS
    SELECT
        t.caso_id, t.caso_version, t.tramo_id, t.orden, t.tipo, t.minimo_s, t.maximo_s, t.estados,
        (SELECT coalesce(
                jsonb_agg(
                    jsonb_build_object(
                        'grupo_id', g.grupo_id, 'minimo_s', g.minimo_s, 'maximo_s', g.maximo_s,
                        'proposito', g.proposito
                    ) ORDER BY g.grupo_id
                ),
                '[]'::jsonb
            )
            FROM caso.grupo_tramo AS gt
            JOIN caso.grupos_verde AS g
                ON g.caso_id = gt.caso_id AND g.caso_version = gt.caso_version
                AND g.grupo_id = gt.grupo_id
            WHERE gt.caso_id = t.caso_id AND gt.caso_version = t.caso_version
                AND gt.tramo_id = t.tramo_id) AS grupos
    FROM caso.tramos AS t;
COMMENT ON VIEW vistas.caso_tramos IS
    'Los tramos del programa del semáforo, una fila por tramo, con sus límites y sus grupos de verde.';

CREATE VIEW vistas.planes_resumen WITH (security_invoker = true) AS
    SELECT
        p.plan_id, p.caso_id, p.caso_version, p.ciclo_s, p.duraciones_s,
        o.plan_observado_id IS NOT NULL AS es_plan_observado,
        o.fuente AS fuente_observada, o.variacion_horaria, o.confirmado_por
    FROM simulacion.planes AS p
    LEFT JOIN caso.planes_observados AS o ON o.plan_id = p.plan_id
    WHERE o.plan_observado_id IS NOT NULL
        OR EXISTS (
            SELECT 1 FROM simulacion.corridas AS c
            WHERE c.plan_id = p.plan_id AND control.escenario_visible(c.escenario_id)
        )
        OR EXISTS (
            SELECT 1 FROM simulacion.candidatos AS n
            JOIN simulacion.busquedas AS b ON b.busqueda_id = n.busqueda_id
            WHERE n.plan_id = p.plan_id AND control.escenario_visible(b.escenario_id)
        )
        OR EXISTS (
            SELECT 1 FROM simulacion.comparadores AS k
            WHERE k.webster_plan_id = p.plan_id AND control.escenario_visible(k.escenario_id)
        );
COMMENT ON VIEW vistas.planes_resumen IS
    'Los planes con sus duraciones, solo si los usa algo visible; marca el plan observado del caso.';

CREATE VIEW vistas.escenarios_detalle WITH (security_invoker = true) AS
    SELECT
        e.escenario_id, e.caso_id, e.caso_version, e.familia_id, e.origen, e.preliminar,
        e.request_id, e.origen_solicitud, e.inicio_observacion, e.fin_observacion, e.fuentes,
        e.politica_frontera, e.calentamiento_s, e.medicion_s, e.vaciado_max_s, e.semilla_demanda,
        e.demanda_sha256, e.huella_escenario,
        a.ruta_relativa AS archivo, a.sha256 AS archivo_sha256
    FROM experimento.escenarios AS e
    JOIN control.artefactos AS a ON a.artefacto_id = e.artefacto_id
    WHERE control.escenario_visible(e.escenario_id);
COMMENT ON VIEW vistas.escenarios_detalle IS
    'Los datos de entrada de cada escenario visible: ventana, tiempos, semilla de demanda y su archivo con huella.';

CREATE VIEW vistas.demanda_escenario WITH (security_invoker = true) AS
    SELECT
        d.escenario_id, d.caso_id, d.caso_version, d.movimiento_id, d.clase_id, d.flujo_vph,
        d.proporcion
    FROM experimento.demanda AS d
    WHERE control.escenario_visible(d.escenario_id);
COMMENT ON VIEW vistas.demanda_escenario IS
    'La demanda de cada escenario visible, por movimiento y clase de vehículo.';

CREATE VIEW vistas.protocolos_resumen WITH (security_invoker = true) AS
    SELECT
        p.protocolo_id, p.estado, p.proposito, p.definicion_metrica, p.politica_cohorte,
        p.politica_censura, p.presupuesto_busqueda, p.finalistas, p.epsilon_empate_s,
        p.umbral_cola_mps, p.umbral_detencion_mps, p.muestreo_cola_s, p.carriles_zona,
        p.nivel_confianza, p.remuestreos_bootstrap, p.margen_aceptacion_s,
        (SELECT coalesce(array_agg(s.semilla ORDER BY s.orden), '{}'::integer[])
            FROM experimento.protocolo_semillas AS s
            WHERE s.protocolo_id = p.protocolo_id AND s.etapa = 'search') AS semillas_busqueda,
        (SELECT coalesce(array_agg(s.semilla ORDER BY s.orden), '{}'::integer[])
            FROM experimento.protocolo_semillas AS s
            WHERE s.protocolo_id = p.protocolo_id AND s.etapa = 'finalists') AS semillas_finalistas
    FROM experimento.protocolos AS p;
COMMENT ON VIEW vistas.protocolos_resumen IS
    'Las reglas de cada protocolo y sus semillas de búsqueda y de finalistas; las de la etapa final quedan fuera.';

CREATE VIEW vistas.corridas_procedencia WITH (security_invoker = true) AS
    SELECT
        c.run_id, c.reintento_de, c.creada_en, c.semilla_demanda, c.paso_s, c.calentamiento_s,
        c.medicion_s, c.vaciado_max_s, c.fin_s, c.vehiculos_total, c.vehiculos_cohorte,
        c.red_sha256, c.programa_sha256, c.rutas_sha256, c.tipos_sha256, c.entradas_sha256,
        c.limitaciones, c.error, c.memoria_pico_bytes,
        r.protocolo_metricas_id, r.estado_protocolo_metricas, r.version_metricas,
        r.definicion_demora, r.origen_caso, r.origen_demanda, r.zona_disponible,
        r.motivo_zona_no_disponible, r.inicio_medicion_s, r.fin_medicion_s, r.cobertura_cola,
        r.cohorte_solicitada, r.cohorte_terminada, r.cohorte_sin_terminar, r.cohorte_no_insertada,
        r.teletransportes_atasco, r.teletransportes_cruce, r.teletransportes_carril,
        r.perdida_tiempo_media_s, r.demora_salida_media_cohorte_s, r.demanda_insatisfecha,
        e.version_sumo, e.commit_codigo, e.codigo_modificado,
        m.ruta_relativa AS manifiesto, m.sha256 AS manifiesto_sha256,
        x.ruta_relativa AS metricas, x.sha256 AS metricas_sha256
    FROM simulacion.corridas AS c
    LEFT JOIN simulacion.resultados_corrida AS r ON r.run_id = c.run_id
    LEFT JOIN control.entornos AS e ON e.entorno_id = c.entorno_id
    LEFT JOIN control.artefactos AS m ON m.artefacto_id = c.artefacto_id
    LEFT JOIN control.artefactos AS x ON x.artefacto_id = r.artefacto_metricas_id
    WHERE control.escenario_visible(c.escenario_id);
COMMENT ON VIEW vistas.corridas_procedencia IS
    'De dónde sale cada corrida visible: entradas con su huella, versión de SUMO, commit, protocolo de sus métricas, manifiesto y archivo de métricas.';

CREATE VIEW vistas.resultados_acceso WITH (security_invoker = true) AS
    SELECT
        r.run_id, r.acceso, r.con_cohorte, r.solicitados, r.terminados, r.sin_terminar,
        r.no_insertados, r.estado_demora, r.demora_media_s, r.perdida_tiempo_media_s,
        r.demora_salida_media_s, r.cota_inf_demora_s, r.estado_cola, r.cobertura_cola,
        r.cola_media_veh, r.cola_maxima_veh, r.estado_detenciones, r.detenciones_media
    FROM simulacion.resultados_acceso AS r
    JOIN simulacion.corridas AS c ON c.run_id = r.run_id
    WHERE control.escenario_visible(c.escenario_id);
COMMENT ON VIEW vistas.resultados_acceso IS
    'Demora, cola y detenciones de cada acceso en cada corrida visible; con_cohorte dice si la demora puede existir.';

CREATE VIEW vistas.resultados_movimiento WITH (security_invoker = true) AS
    SELECT
        r.run_id, r.caso_id, r.caso_version, r.movimiento_id, r.solicitados, r.terminados,
        r.sin_terminar, r.no_insertados, r.estado_demora, r.demora_media_s,
        r.perdida_tiempo_media_s, r.demora_salida_media_s, r.cota_inf_demora_s
    FROM simulacion.resultados_movimiento AS r
    JOIN simulacion.corridas AS c ON c.run_id = r.run_id
    WHERE control.escenario_visible(c.escenario_id);
COMMENT ON VIEW vistas.resultados_movimiento IS
    'Demora de cada movimiento en cada corrida visible.';

CREATE VIEW vistas.candidatos_resumen WITH (security_invoker = true) AS
    SELECT
        n.busqueda_id, b.escenario_id, n.candidato_id, n.plan_id, p.ciclo_s, n.origen,
        n.consume_presupuesto, n.orden, n.elegible_busqueda, n.puntaje_busqueda_s,
        n.cola_media_busqueda_veh, n.detenciones_media_busqueda, n.problemas_busqueda,
        n.semillas_faltantes_busqueda, n.posicion_busqueda, n.finalista, n.elegible_finalistas,
        n.puntaje_finalistas_s, n.cola_media_finalistas_veh, n.detenciones_media_finalistas,
        n.problemas_finalistas, n.semillas_faltantes_finalistas, n.posicion_finalistas, n.ganador
    FROM simulacion.candidatos AS n
    JOIN simulacion.busquedas AS b ON b.busqueda_id = n.busqueda_id
    JOIN simulacion.planes AS p ON p.plan_id = n.plan_id
    WHERE control.escenario_visible(b.escenario_id);
COMMENT ON VIEW vistas.candidatos_resumen IS
    'Cada plan probado en una búsqueda visible: su origen, si fue elegible, su puntaje y sus motivos de descarte.';

CREATE VIEW vistas.candidato_semillas WITH (security_invoker = true) AS
    SELECT
        s.busqueda_id, s.candidato_id, s.etapa, s.semilla, s.run_id, s.estado_corrida,
        s.demora_media_s, s.cola_media_veh, s.detenciones_media, s.teletransportes, s.choques,
        s.problemas, s.clase_incidente
    FROM simulacion.candidato_semillas AS s
    JOIN simulacion.busquedas AS b ON b.busqueda_id = s.busqueda_id
    WHERE control.escenario_visible(b.escenario_id);
COMMENT ON VIEW vistas.candidato_semillas IS
    'El resultado de cada plan en cada semilla de una búsqueda visible, con su corrida.';

CREATE VIEW vistas.comparadores_resumen WITH (security_invoker = true) AS
    SELECT
        k.comparador_id, k.escenario_id, k.caso_id, k.caso_version, k.origen_caso,
        k.origen_demanda, k.origen_evidencia, k.plan_observado_id, k.webster_estado,
        k.webster_adaptacion, k.conjunto_parametros, k.provisional, k.webster_ciclo_s,
        k.webster_plan_id, k.webster_reglas_incumplidas, k.webster_problemas, k.y_critico,
        k.tiempo_perdido_s, k.ciclo_recorrido_s, k.saturacion_vph_carril, k.estado_parametros
    FROM simulacion.comparadores AS k
    WHERE control.escenario_visible(k.escenario_id);
COMMENT ON VIEW vistas.comparadores_resumen IS
    'Los comparadores de cada escenario visible: el plan observado y el estado de Webster con sus motivos.';

-- Una exclusión decidida es un registro público del procedimiento, con su decisión y su acta.
-- Un archivo que cuelga de un escenario cegado no aparece; el de alcance desconocido, sí: se
-- decidió justamente porque no se pudo ligar a ningún escenario.
CREATE VIEW vistas.exclusiones WITH (security_invoker = true) AS
    SELECT
        f.conflicto_id, a.ruta_relativa AS archivo, a.sha256 AS archivo_sha256, a.alcance, f.tipo,
        f.detalle, f.decision, f.decidido_en, f.decidido_por
    FROM control.conflictos AS f
    JOIN control.artefactos AS a ON a.artefacto_id = f.artefacto_id
    WHERE f.decision IS NOT NULL
        AND (a.alcance = 'desconocido' OR control.archivo_visible(a.artefacto_id));
COMMENT ON VIEW vistas.exclusiones IS
    'Los archivos excluidos con una decisión registrada: qué archivo, por qué, qué se decidió y quién.';
