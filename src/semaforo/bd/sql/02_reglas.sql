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
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM control.hitos
        WHERE tipo = 'test_opened' AND particion_id = p_particion
    )
$$;
COMMENT ON FUNCTION control.prueba_abierta(text) IS
    'Verdadero si existe un hito test_opened para esa partición.';

CREATE VIEW control.escenarios_cegados WITH (security_invoker = true) AS
    SELECT a.escenario_id, a.particion_id
    FROM experimento.asignaciones AS a
    WHERE a.asignacion = 'test' AND NOT control.prueba_abierta(a.particion_id);
COMMENT ON VIEW control.escenarios_cegados IS
    'Escenarios asignados a test en una partición cuya prueba no tiene hito de apertura. Es la base del cegado.';

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
        SELECT particion_id INTO v_particion FROM aprendizaje.modelos WHERE modelo_id = NEW.modelo_id;
        IF NOT EXISTS (
            SELECT 1 FROM control.hitos WHERE tipo = 'split_frozen' AND particion_id = v_particion
        ) THEN
            RAISE EXCEPTION 'antes de congelar el modelo % hay que congelar su partición %',
                NEW.modelo_id, v_particion USING ERRCODE = 'SM001';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM control.hitos WHERE tipo = 'protocol_frozen') THEN
            RAISE EXCEPTION 'antes de congelar el modelo % hay que congelar un protocolo', NEW.modelo_id
                USING ERRCODE = 'SM001';
        END IF;
    ELSIF NEW.tipo = 'test_opened' THEN
        SELECT particion_id, protocolo_id, modelo_id INTO v_particion, v_protocolo, v_modelo
        FROM evaluacion.experimentos WHERE experimento_id = NEW.experimento_id;
        IF v_particion IS DISTINCT FROM NEW.particion_id THEN
            RAISE EXCEPTION 'la partición % no es la del experimento %', NEW.particion_id,
                NEW.experimento_id USING ERRCODE = 'SM001';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM control.hitos WHERE tipo = 'model_frozen' AND modelo_id = v_modelo)
            OR NOT EXISTS (
                SELECT 1 FROM control.hitos WHERE tipo = 'protocol_frozen' AND protocolo_id = v_protocolo
            )
            OR NOT EXISTS (
                SELECT 1 FROM control.hitos WHERE tipo = 'split_frozen' AND particion_id = v_particion
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
    v_pasos jsonb;
    v_ventana jsonb;
BEGIN
    SELECT r.pasos_cola_s, r.pasos_en_ventana INTO v_pasos, v_ventana
    FROM simulacion.resultados_corrida AS r
    WHERE r.run_id = NEW.run_id;
    IF v_pasos IS NULL OR v_ventana IS NULL
        OR jsonb_array_length(NEW.vehiculos_en_cola) <> jsonb_array_length(v_pasos)
        OR jsonb_array_length(v_pasos) <> jsonb_array_length(v_ventana) THEN
        RAISE EXCEPTION 'la cola del acceso % de la corrida % no tiene un valor por paso',
            NEW.acceso, NEW.run_id USING ERRCODE = 'SM006';
    END IF;
    RETURN NEW;
END
$$;
COMMENT ON FUNCTION simulacion.validar_cola() IS
    'Cada acceso tiene un valor de cola por cada paso de la serie de su corrida.';
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
-- Vistas (B12): el panel y las consultas guardadas leen siempre vistas. «security_invoker» hace
-- que el cegado se aplique a quien consulta: el usuario de lectura no ve la prueba cerrada.

CREATE VIEW vistas.zona_escenario WITH (security_invoker = true) AS
    SELECT
        e.escenario_id, e.caso_id, e.caso_version, e.familia_id, e.origen, e.preliminar,
        a.particion_id, a.asignacion,
        CASE WHEN a.asignacion = 'test' THEN 'prueba' ELSE 'desarrollo' END AS zona,
        CASE WHEN a.asignacion = 'test' THEN control.prueba_abierta(a.particion_id) END
            AS prueba_abierta
    FROM experimento.escenarios AS e
    LEFT JOIN experimento.asignaciones AS a ON a.escenario_id = e.escenario_id;
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
    LEFT JOIN simulacion.resultados_corrida AS r ON r.run_id = c.run_id;
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
    WHERE v.en_cohorte;
COMMENT ON VIEW vistas.vehiculos_cohorte IS
    'Vehículos de la cohorte con su demora (pérdida de tiempo más espera de salida, según la definición del protocolo).';

-- Una fila por corrida, acceso y paso, como antes del arreglo por acceso. ROWS FROM recorre los
-- tres arreglos a la vez (el disparador validar_cola() garantiza que tienen la misma longitud).
CREATE VIEW vistas.cola_por_segundo WITH (security_invoker = true) AS
    SELECT q.run_id, q.acceso,
        s.tiempo_txt::double precision AS tiempo_s,
        s.veh_txt::integer AS vehiculos_en_cola,
        s.ventana_txt::boolean AS en_ventana
    FROM simulacion.cola_por_acceso AS q
    JOIN simulacion.resultados_corrida AS r ON r.run_id = q.run_id
    CROSS JOIN LATERAL ROWS FROM (
        jsonb_array_elements_text(r.pasos_cola_s),
        jsonb_array_elements_text(q.vehiculos_en_cola),
        jsonb_array_elements_text(r.pasos_en_ventana)
    ) AS s(tiempo_txt, veh_txt, ventana_txt);
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
    LEFT JOIN simulacion.etiquetas AS t ON t.busqueda_id = b.busqueda_id;
COMMENT ON VIEW vistas.busquedas_resumen IS
    'Una fila por búsqueda con su etiqueta, sus candidatos elegibles y sus motivos de descarte.';

CREATE VIEW vistas.etiquetas_entrenamiento WITH (security_invoker = true) AS
    SELECT
        t.etiqueta_id, t.escenario_id, t.caso_id, t.caso_version, t.protocolo_id, t.plan_id,
        t.verdes_s, a.particion_id, a.asignacion
    FROM simulacion.etiquetas AS t
    JOIN experimento.asignaciones AS a ON a.escenario_id = t.escenario_id
    WHERE t.estado = 'reference' AND a.asignacion IN ('train', 'validation');
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
    FROM aprendizaje.consultas AS q;
COMMENT ON VIEW vistas.consultas_resumen IS
    'Consultas con su estado, sus tiempos y sus reglas incumplidas.';

CREATE VIEW vistas.indicadores_finales WITH (security_invoker = true) AS
    SELECT
        i.indicador_id, i.experimento_id, x.protocolo_id, x.particion_id, x.modelo_id,
        i.indicador, i.metrica, i.alternativa_a, i.alternativa_b, i.alcance, i.valor, i.unidad,
        i.numerador, i.denominador, i.faltantes, i.ic_nivel, i.ic_inferior, i.ic_superior,
        i.remuestreos, i.semilla_remuestreo, i.agregacion, i.version_calculo
    FROM evaluacion.indicadores AS i
    JOIN evaluacion.experimentos AS x ON x.experimento_id = i.experimento_id;
COMMENT ON VIEW vistas.indicadores_finales IS
    'Indicadores I4 a I7 del experimento final con sus intervalos. Vacía hasta la apertura.';
