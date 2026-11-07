"""El estado de la red de PostgreSQL: qué reglas admiten equipos de fuera (DEV31 F4c, C1.9; B07)."""

from semaforo.bd.acceso import analyze_rules, parse_hba

LOCAL_ONLY = """\
# TYPE  DATABASE  USER  ADDRESS       METHOD
local   all       all                 scram-sha-256
host    all       all   127.0.0.1/32  scram-sha-256
host    all       all   ::1/128       scram-sha-256
local   replication all               scram-sha-256
host    replication all 127.0.0.1/32  scram-sha-256
"""


def test_the_standard_file_of_this_laptop_admits_nobody_from_outside() -> None:
    rules = parse_hba(LOCAL_ONLY)
    assert len(rules) == 5
    assert analyze_rules(rules) == []


def test_a_rule_for_a_network_or_for_everyone_is_flagged() -> None:
    text = LOCAL_ONLY + "host all all 192.168.1.0/24 scram-sha-256\nhost all all 0.0.0.0/0 md5\n"
    flagged = analyze_rules(parse_hba(text))
    assert flagged == [
        "host all all 192.168.1.0/24 scram-sha-256",
        "host all all 0.0.0.0/0 md5",
    ]


def test_the_keywords_that_reach_the_servers_own_addresses_are_flagged() -> None:
    text = "host all all samehost trust\nhost all all samenet trust\nhost all all all md5\n"
    assert len(analyze_rules(parse_hba(text))) == 3


def test_an_address_and_a_mask_in_separate_columns_are_read_as_one() -> None:
    text = (
        "host all all 127.0.0.1 255.255.255.255 scram-sha-256\n"
        "host all all 10.0.0.0 255.0.0.0 md5\n"
    )
    rules = parse_hba(text)
    assert [rule.address for rule in rules] == ["127.0.0.1 255.255.255.255", "10.0.0.0 255.0.0.0"]
    assert analyze_rules(rules) == ["host all all 10.0.0.0 255.0.0.0 md5"]


def test_a_rule_that_rejects_does_not_admit_anyone() -> None:
    text = "host all all 0.0.0.0/0 reject\nhostssl all all 10.0.0.0/8 reject\n"
    assert analyze_rules(parse_hba(text)) == []


def test_ssl_variants_and_host_names_are_analyzed_too() -> None:
    text = (
        "hostssl all all 10.1.0.0/16 scram-sha-256\n"
        "hostnossl all all localhost scram-sha-256\n"
        "host all all otro-equipo.local scram-sha-256\n"
    )
    assert analyze_rules(parse_hba(text)) == [
        "hostssl all all 10.1.0.0/16 scram-sha-256",
        "host all all otro-equipo.local scram-sha-256",
    ]


def test_comments_blank_lines_and_includes_are_ignored() -> None:
    text = "\n# solo comentarios\ninclude otro.conf\nhost all all 127.0.0.1/32 trust  # local\n"
    rules = parse_hba(text)
    assert [rule.text() for rule in rules] == ["host all all 127.0.0.1/32 trust"]
