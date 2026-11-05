"""DEV14 F2: la mutación que sobrevivió, con las pruebas nuevas."""

E = "src/semaforo/referencias/evaluation.py"
TESTS = ["tests/integration/test_search_sumo.py"]
MUTATIONS = [
    (E, '    if manifest.status != "succeeded":', "    if False:", "corrida fallida evaluada"),
    (
        E,
        "    except DomainError as error:\n        return failed_seed(",
        "    except ZeroDivisionError as error:\n        return failed_seed(",
        "error de medición no atrapado",
    ),
]
