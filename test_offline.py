"""
Teste offline: semeia o cache com dados sintéticos e valida a lógica de cálculo
sem tocar no BigQuery. Prova também que o cache funciona (sem billing_project_id).

Rodar:  python test_offline.py
"""
from __future__ import annotations

import pandas as pd

import calculations
import config
import data_sources
import municipios
import reporting


def seed_cache() -> None:
    # Diretório mínimo: dois municípios do RS + um "intruso" de SC (42) que
    # aparece no filtro sigla_uf de ocorrência mas deve ser descartado no agregado.
    diretorio = pd.DataFrame(
        {
            "id_municipio": ["4300001", "4300002", "4200001"],
            "nome": ["Testópolis", "Vila Exemplo", "Intruso SC"],
            "sigla_uf": ["RS", "RS", "SC"],
        }
    )
    data_sources._gravar_cache("diretorio-municipios", diretorio)

    anos = list(range(2010, 2023))
    # População: cresce linearmente; censo 2010 e 2022 batem com estimativas.
    pop = []
    for i, mid in enumerate(["4300001", "4300002", "4200001"], start=1):
        base = 10000 * i
        for a in anos:
            pop.append({"ano": a, "id_municipio": mid,
                        "populacao": base + (a - 2010) * 100 * i})
    data_sources._gravar_cache("populacao-RS", pd.DataFrame(pop))

    # Nascimentos e óbitos constantes por ano/município.
    nasc, obit = [], []
    for i, mid in enumerate(["4300001", "4300002", "4200001"], start=1):
        for a in anos:
            nasc.append({"ano": a, "id_municipio": mid, "nascimentos": 200 * i})
            obit.append({"ano": a, "id_municipio": mid, "obitos": 120 * i})
    data_sources._gravar_cache("nascimentos-RS", pd.DataFrame(nasc))
    data_sources._gravar_cache("obitos-RS", pd.DataFrame(obit))

    # Descartados (id nulo)
    desc = pd.DataFrame(
        [{"ano": 2015, "descartados": 5, "fonte": "nascimentos"},
         {"ano": 2015, "descartados": 3, "fonte": "obitos"}]
    )
    data_sources._gravar_cache("descartados-RS", desc)


def main() -> None:
    # Isola o teste num cache temporário para não tocar no cache real (que pode
    # conter os dados nacionais já importados).
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="demog_test_"))
    config.CACHE_DIR = tmp / "cache"
    config.OUTPUT_DIR = tmp / "output"
    config.CACHE_DIR.mkdir()
    config.OUTPUT_DIR.mkdir()

    # Desliga as correções para validar a MATEMÁTICA-NÚCLEO do resíduo com os
    # números sintéticos exatos. As correções (sub-registro e fronteira) são
    # verificadas contra os dados reais, à parte.
    config.APLICAR_SUBREGISTRO = False
    config.FRACIONAR_FRONTEIRA = False

    seed_cache()

    # --- resolução por nome (com acento/caixa) e por código -----------------
    m1 = municipios.resolver("testópolis")
    assert m1.id_municipio == "4300001", m1
    m2 = municipios.resolver("4300002")
    assert m2.nome == "Vila Exemplo", m2
    print("OK: resolução por nome e por código IBGE")

    # --- série municipal ----------------------------------------------------
    serie = calculations.construir_serie_municipio("4300001", "RS")
    # vegetativo = 200 - 120 = 80/ano
    assert (serie["vegetativo"] == 80).all(), serie
    # saldo anual: pop cresce 100/ano, vegetativo 80 -> saldo = 100 - 80 = 20
    saldo_2010 = serie.loc[serie["ano"] == 2010, "saldo_migratorio"].iloc[0]
    assert saldo_2010 == 20, saldo_2010
    # último ano sem Pop(t+1) -> NaN
    assert pd.isna(serie.loc[serie["ano"] == 2022, "saldo_migratorio"].iloc[0])
    print("OK: vegetativo e saldo migratório anual")

    # --- intercensitário ----------------------------------------------------
    inter = calculations.saldo_intercensitario(serie)
    row = inter[inter["intervalo"] == "2010-2022"].iloc[0]
    # delta_pop = 100*12 = 1200; vegetativo [2010..2022] inclusive = 80*13 = 1040
    assert row["delta_pop"] == 1200, row
    assert row["vegetativo_acumulado"] == 1040, row
    assert row["saldo_migratorio"] == 160, row  # 1200 - 1040
    print("OK: saldo intercensitário")

    # --- resumo -------------------------------------------------------------
    resumo = calculations.resumir(serie)
    assert resumo["ano_pico_populacional"] == 2022, resumo
    assert resumo["vegetativo_acumulado"] == 80 * 13, resumo
    print("OK: resumo")

    # --- agregado RS: intruso de SC (4200001) deve ser excluído -------------
    agg = calculations.construir_serie_uf("RS")
    nasc_2010 = agg.loc[agg["ano"] == 2010, "nascimentos"].iloc[0]
    # só 4300001 (200) + 4300002 (400) = 600; intruso 4200001 (600) descartado
    assert nasc_2010 == 600, nasc_2010
    print("OK: agregado RS filtra id que não começa com 43")

    # --- exportação e gráficos ---------------------------------------------
    inter = calculations.saldo_intercensitario(serie)
    gerados = reporting.exportar(serie, inter, resumo, "teste_offline", "ambos")
    assert gerados, "nada exportado"
    fig = reporting.figura_completa(serie, "Teste")
    png = config.OUTPUT_DIR / "teste_offline.png"
    fig.savefig(png)
    print(f"OK: export ({len(gerados)} arquivos) e gráficos ({png.name})")

    print("\n[cenário por-UF] OK")

    testar_nacional()
    print("\nTODOS OS TESTES PASSARAM [OK]")


def testar_nacional() -> None:
    """Cenário do cache NACIONAL: seeds `*-BR` (com linhas de id nulo) e valida
    o fatiamento por UF e a contagem de descartados sem custo."""
    # limpa o cache do cenário anterior para não misturar
    for f in config.CACHE_DIR.glob("*.parquet"):
        f.unlink()

    diretorio = pd.DataFrame(
        {
            "id_municipio": ["4300001", "4300002", "4200001"],
            "nome": ["Testópolis", "Vila Exemplo", "Intruso SC"],
            "sigla_uf": ["RS", "RS", "SC"],
        }
    )
    data_sources._gravar_cache("diretorio-municipios", diretorio)

    anos = list(range(2010, 2023))
    pop = [
        {"ano": a, "id_municipio": mid, "populacao": 10000 * i + (a - 2010) * 100 * i}
        for i, mid in enumerate(["4300001", "4300002", "4200001"], start=1)
        for a in anos
    ]
    data_sources._gravar_cache("populacao-BR", pd.DataFrame(pop))

    # eventos nacionais COM linhas de id nulo (descartados)
    nasc = [
        {"ano": a, "id_municipio": mid, "nascimentos": 200 * i}
        for i, mid in enumerate(["4300001", "4300002", "4200001"], start=1)
        for a in anos
    ]
    nasc.append({"ano": 2015, "id_municipio": None, "nascimentos": 7})  # descartado
    df_nasc = pd.DataFrame(nasc)
    df_nasc["id_municipio"] = df_nasc["id_municipio"].astype("string")
    data_sources._gravar_cache("nascimentos-BR", df_nasc)

    obit = [
        {"ano": a, "id_municipio": mid, "obitos": 120 * i}
        for i, mid in enumerate(["4300001", "4300002", "4200001"], start=1)
        for a in anos
    ]
    obit.append({"ano": 2015, "id_municipio": None, "obitos": 4})  # descartado
    df_obit = pd.DataFrame(obit)
    df_obit["id_municipio"] = df_obit["id_municipio"].astype("string")
    data_sources._gravar_cache("obitos-BR", df_obit)

    # o loader por-UF deve FATIAR do cache nacional (sem consultar)
    nasc_rs = data_sources.carregar_nascimentos("RS")
    assert set(nasc_rs["id_municipio"]) == {"4300001", "4300002"}, nasc_rs
    assert nasc_rs["id_municipio"].isna().sum() == 0  # id nulo não vaza

    # série municipal continua correta vindo do cache nacional
    serie = calculations.construir_serie_municipio("4300001", "RS")
    assert (serie["vegetativo"] == 80).all()

    # descartados extraídos do cache nacional, SEM nova consulta
    desc = data_sources.contar_descartados_br()
    tot = desc.groupby("fonte")["descartados"].sum().to_dict()
    assert tot == {"nascimentos": 7, "obitos": 4}, tot

    # agregado RS exclui o intruso de SC (4200001)
    agg = calculations.construir_serie_uf("RS")
    assert agg.loc[agg["ano"] == 2010, "nascimentos"].iloc[0] == 600
    print("[cenário nacional] OK")


if __name__ == "__main__":
    main()
