"""
Cálculos demográficos: crescimento vegetativo e saldo migratório (método do
resíduo), tanto na série anual (aproximação) quanto entre censos (mais robusto).

Definições
----------
Crescimento vegetativo(t) = nascimentos(t) − óbitos(t)

Saldo migratório LÍQUIDO (não separa entrada/saída; inclui migração interna,
internacional e qualquer reconciliação estatística):

  * Série anual (aproximação, usa estimativas anuais de população):
        Saldo(t) ≈ (Pop(t+1) − Pop(t)) − vegetativo(t)

  * Intercensitário (mais robusto, usa anos de censo):
        Saldo = (Pop_censo_final − Pop_censo_inicial) − Σ vegetativo no período
    Somamos o vegetativo dos anos [inicial, final] inclusive em cada intervalo
    censitário; esta convenção reproduz o agregado RS de referência (2010–2022:
    veg ≈ 625 mil, saldo ≈ −438 mil). Como o censo tem referência em julho e os
    eventos são somados por ano-calendário, há leve descasamento — use para
    tendência, não como número exato.

Saldo em % = saldo ÷ população inicial (do ano t na série anual).
"""
from __future__ import annotations

import pandas as pd

import config
import data_sources


# ---------------------------------------------------------------------------
# Correção de sub-registro (SINASC/SIM)
# ---------------------------------------------------------------------------
def _corrigir_subregistro(serie: pd.DataFrame, sigla_uf: str) -> pd.DataFrame:
    """Multiplica nascimentos/óbitos pelos fatores 1/cobertura da UF (config).
    Não faz nada se a correção estiver desligada (fatores = 1.0)."""
    fat = config.fatores_subregistro(sigla_uf)
    serie = serie.copy()
    serie["nascimentos"] = (
        (serie["nascimentos"] * fat["nascimentos"]).round(0).astype("int64")
    )
    serie["obitos"] = (
        (serie["obitos"] * fat["obitos"]).round(0).astype("int64")
    )
    return serie


def _veg_intercenso(serie_idx: pd.DataFrame, ini: int, fim: int) -> float:
    """Soma do vegetativo no intervalo [ini, fim], aplicando (ou não) a
    correção de fronteira temporal (pesos por fração de ano). `serie_idx` deve
    estar indexado por `ano` e conter a coluna 'vegetativo'."""
    if config.FRACIONAR_FRONTEIRA:
        total = 0.0
        for ano in range(ini, fim + 1):
            if ano in serie_idx.index:
                total += serie_idx.loc[ano, "vegetativo"] * config.peso_ano_intercenso(
                    ano, ini, fim
                )
        return total
    # sem correção: soma anos-calendário inteiros [ini, fim]
    return serie_idx.loc[
        (serie_idx.index >= ini) & (serie_idx.index <= fim), "vegetativo"
    ].sum()


# ---------------------------------------------------------------------------
# Série anual de um município
# ---------------------------------------------------------------------------
def construir_serie_municipio(
    id_municipio: str, sigla_uf: str
) -> pd.DataFrame:
    """Monta a série anual completa de um município.

    Colunas de saída:
        ano, tipo_populacao ('censo'/'estimativa'), populacao,
        nascimentos, obitos, vegetativo, saldo_migratorio, saldo_pct
    """
    pop = data_sources.carregar_populacao(sigla_uf)
    nasc = data_sources.carregar_nascimentos(sigla_uf)
    obit = data_sources.carregar_obitos(sigla_uf)

    pop_m = pop[pop["id_municipio"] == id_municipio][["ano", "populacao"]]
    nasc_m = nasc[nasc["id_municipio"] == id_municipio][["ano", "nascimentos"]]
    obit_m = obit[obit["id_municipio"] == id_municipio][["ano", "obitos"]]

    # A população é o "esqueleto" temporal: existe para todos os anos.
    serie = (
        pop_m.merge(nasc_m, on="ano", how="left")
        .merge(obit_m, on="ano", how="left")
        .sort_values("ano")
        .reset_index(drop=True)
    )
    # Ausência de nascimento/óbito num ano com população significa zero eventos
    # (municípios pequenos), não dado faltante.
    serie["nascimentos"] = serie["nascimentos"].fillna(0).astype("int64")
    serie["obitos"] = serie["obitos"].fillna(0).astype("int64")

    # Correção de sub-registro (SINASC/SIM): multiplica por 1/cobertura.
    serie = _corrigir_subregistro(serie, sigla_uf)

    # Marca censo vs estimativa
    serie["tipo_populacao"] = serie["ano"].map(
        lambda a: "censo" if a in config.ANOS_CENSO else "estimativa"
    )

    # Crescimento vegetativo
    serie["vegetativo"] = serie["nascimentos"] - serie["obitos"]

    # Saldo migratório anual (resíduo): usa Pop(t+1)
    pop_next = serie["populacao"].shift(-1)
    serie["saldo_migratorio"] = (pop_next - serie["populacao"]) - serie[
        "vegetativo"
    ]
    # Saldo em % da população inicial (do ano t)
    serie["saldo_pct"] = (
        serie["saldo_migratorio"] / serie["populacao"] * 100
    ).round(3)

    # Arredonda o saldo (o resíduo pode ter frações por conta dos tipos)
    serie["saldo_migratorio"] = serie["saldo_migratorio"].round(0)

    return serie[
        [
            "ano",
            "tipo_populacao",
            "populacao",
            "nascimentos",
            "obitos",
            "vegetativo",
            "saldo_migratorio",
            "saldo_pct",
        ]
    ]


# ---------------------------------------------------------------------------
# Saldo migratório intercensitário
# ---------------------------------------------------------------------------
def saldo_intercensitario(serie: pd.DataFrame) -> pd.DataFrame:
    """Calcula o saldo migratório robusto para cada intervalo censitário.

    Recebe a série anual (de `construir_serie_municipio` ou o agregado de UF) e
    retorna uma linha por intervalo com Δpop, vegetativo acumulado, saldo e %.
    """
    serie = serie.set_index("ano")
    linhas = []
    for ini, fim in config.INTERVALOS_CENSO:
        if ini not in serie.index or fim not in serie.index:
            continue
        pop_ini = serie.loc[ini, "populacao"]
        pop_fim = serie.loc[fim, "populacao"]
        # Vegetativo do período. Com FRACIONAR_FRONTEIRA (default), os anos de
        # ponta são ponderados pela fração de meses dentro do intervalo (censo
        # ~1º/ago), somando exatamente (fim − ini) anos. Sem a correção, soma os
        # anos-calendário [ini, fim] inteiros.
        veg = _veg_intercenso(serie, ini, fim)
        delta_pop = pop_fim - pop_ini
        saldo = delta_pop - veg
        linhas.append(
            {
                "intervalo": f"{ini}-{fim}",
                "pop_inicial": int(pop_ini),
                "pop_final": int(pop_fim),
                "delta_pop": int(delta_pop),
                "vegetativo_acumulado": int(veg),
                "saldo_migratorio": int(round(saldo)),
                "saldo_pct": round(saldo / pop_ini * 100, 2),
            }
        )
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------------------
# Uniformização dos rebaseamentos (reconstrução intercensitária)
# ---------------------------------------------------------------------------
def reconstruir_serie(serie: pd.DataFrame, metodo: str = "uniforme") -> pd.DataFrame:
    """Uniformiza os saltos de rebaseamento das estimativas do IBGE.

    Em vez de diferenciar as estimativas anuais (ruidosas), ancoramos nos censos
    e reconstruímos a população pela equação de balanço demográfico:
        Pop(t+1) = Pop(t) + vegetativo(t) + migração(t)
    O saldo migratório TOTAL de cada intervalo intercensitário é fixado pelas
    âncoras — Total = (Pop_censo_final − Pop_censo_inicial) − Σ vegetativo — e
    distribuído suavemente entre os anos, eliminando os picos artificiais.

    metodo:
      'uniforme'     → mesma migração absoluta por ano (Total / N).
      'proporcional' → migração proporcional à população (taxa ~constante).

    A série reconstruída passa EXATAMENTE pelos censos. Colunas adicionadas:
      populacao_suave, saldo_migratorio_suave, saldo_pct_suave.

    Nota: aqui o vegetativo do intervalo é somado em [inicial, final-1] (a forma
    exigida pela equação de balanço, para a série fechar nos censos). Por isso o
    saldo intercensitário reconstruído pode diferir levemente do valor do modo
    bruto, que soma [inicial, final] para reproduzir a referência publicada.
    """
    if metodo not in ("uniforme", "proporcional"):
        raise ValueError("metodo deve ser 'uniforme' ou 'proporcional'")

    s = serie.set_index("ano").sort_index()
    pop_suave: dict[int, float] = {}
    mig_suave: dict[int, float] = {}

    for ini, fim in config.INTERVALOS_CENSO:
        if ini not in s.index or fim not in s.index:
            continue
        transicoes = list(range(ini, fim))  # t = ini .. fim-1
        veg = s.loc[ini:fim - 1, "vegetativo"]  # N termos, um por transição
        total_mig = (s.loc[fim, "populacao"] - s.loc[ini, "populacao"]) - veg.sum()

        if metodo == "proporcional":
            pesos = s.loc[ini:fim - 1, "populacao"].astype(float)
            pesos = pesos / pesos.sum()
            mig = {t: total_mig * pesos.loc[t] for t in transicoes}
        else:  # uniforme
            mig = {t: total_mig / len(transicoes) for t in transicoes}

        pop_suave[ini] = float(s.loc[ini, "populacao"])  # âncora inicial
        for t in transicoes:
            mig_suave[t] = mig[t]
            pop_suave[t + 1] = pop_suave[t] + float(s.loc[t, "vegetativo"]) + mig[t]

    out = serie.copy()
    out["populacao_suave"] = out["ano"].map(pop_suave).round(0)
    out["saldo_migratorio_suave"] = out["ano"].map(mig_suave).round(0)
    out["saldo_pct_suave"] = (
        out["saldo_migratorio_suave"] / out["populacao_suave"] * 100
    ).round(3)
    return out


# ---------------------------------------------------------------------------
# Resumo executivo
# ---------------------------------------------------------------------------
def resumir(serie: pd.DataFrame) -> dict:
    """Métricas-resumo de uma série anual."""
    if serie.empty:
        return {}
    idx_pico = serie["populacao"].idxmax()
    linha_pico = serie.loc[idx_pico]
    # saldo anual acumulado ignora o último ano (NaN por falta de Pop(t+1))
    saldo_acum = serie["saldo_migratorio"].dropna().sum()
    pop_min = int(serie["populacao"].min())
    return {
        "ano_pico_populacional": int(linha_pico["ano"]),
        "populacao_pico": int(linha_pico["populacao"]),
        "vegetativo_acumulado": int(serie["vegetativo"].sum()),
        "saldo_migratorio_acumulado": int(round(saldo_acum)),
        "ano_min": int(serie["ano"].min()),
        "ano_max": int(serie["ano"].max()),
        # sinaliza (não remove): município pequeno → saldo mais sujeito a ruído
        "pequena_area": bool(pop_min < config.LIMIAR_PEQUENA_AREA),
    }


# ---------------------------------------------------------------------------
# Agregado estadual (para validação / ranking)
# ---------------------------------------------------------------------------
def construir_serie_uf(sigla_uf: str) -> pd.DataFrame:
    """Agrega TODOS os municípios de uma UF por ano.

    Ressalva importante: `sigla_uf` nas tabelas de eventos refere-se à UF de
    OCORRÊNCIA e pode incluir residentes de outros estados. Para o universo do
    estado, mantemos apenas `id_municipio` que começa com o código da UF (RS=43),
    tanto na população quanto nos eventos.
    """
    prefixo = _prefixo_uf(sigla_uf)

    pop = data_sources.carregar_populacao(sigla_uf)
    nasc = data_sources.carregar_nascimentos(sigla_uf)
    obit = data_sources.carregar_obitos(sigla_uf)

    def _filtra_e_soma(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
        d = df[df["id_municipio"].str.startswith(prefixo)]
        return d.groupby("ano", as_index=False)[coluna].sum()

    pop_a = _filtra_e_soma(pop, "populacao")
    nasc_a = _filtra_e_soma(nasc, "nascimentos")
    obit_a = _filtra_e_soma(obit, "obitos")

    serie = (
        pop_a.merge(nasc_a, on="ano", how="left")
        .merge(obit_a, on="ano", how="left")
        .sort_values("ano")
        .reset_index(drop=True)
    )
    serie["nascimentos"] = serie["nascimentos"].fillna(0).astype("int64")
    serie["obitos"] = serie["obitos"].fillna(0).astype("int64")
    serie = _corrigir_subregistro(serie, sigla_uf)  # sub-registro
    serie["tipo_populacao"] = serie["ano"].map(
        lambda a: "censo" if a in config.ANOS_CENSO else "estimativa"
    )
    serie["vegetativo"] = serie["nascimentos"] - serie["obitos"]
    pop_next = serie["populacao"].shift(-1)
    serie["saldo_migratorio"] = (
        (pop_next - serie["populacao"]) - serie["vegetativo"]
    ).round(0)
    serie["saldo_pct"] = (
        serie["saldo_migratorio"] / serie["populacao"] * 100
    ).round(3)
    return serie[
        [
            "ano",
            "tipo_populacao",
            "populacao",
            "nascimentos",
            "obitos",
            "vegetativo",
            "saldo_migratorio",
            "saldo_pct",
        ]
    ]


def _prefixo_uf(sigla_uf: str) -> str:
    """Código IBGE de 2 dígitos da UF (prefixo do id_municipio)."""
    return config.prefixo_uf(sigla_uf)


# ---------------------------------------------------------------------------
# Ranking municipal dentro de uma UF
# ---------------------------------------------------------------------------
def ranking_uf(sigla_uf: str, intervalo: tuple[int, int] | None = None) -> pd.DataFrame:
    """Ranking do saldo migratório de TODOS os municípios de uma UF, no
    intervalo intercensitário informado (default: o último, 2010–2022).

    Usa o método do resíduo por município: as duas pontas do intervalo são anos
    de CENSO (pop robusta). Aplica as mesmas correções da série: sub-registro
    (config) e fronteira temporal (fracionamento dos anos de ponta). Como os
    endpoints são censos, o ranking não sofre com os rebaseamentos das
    estimativas anuais.

    Colunas: id_municipio, nome, pop_inicial, pop_final, delta_pop, vegetativo,
             saldo_migratorio, saldo_pct, pequena_area (bool). Não ordenado — a
             UI ordena; ordenação default aqui é por saldo_migratorio desc.
    """
    ini, fim = intervalo or config.INTERVALOS_CENSO[-1]
    prefixo = config.prefixo_uf(sigla_uf)
    fat = config.fatores_subregistro(sigla_uf)

    pop = data_sources.carregar_populacao(sigla_uf)
    nasc = data_sources.carregar_nascimentos(sigla_uf)
    obit = data_sources.carregar_obitos(sigla_uf)

    def _uf(df: pd.DataFrame) -> pd.DataFrame:
        return df[df["id_municipio"].str.startswith(prefixo)]

    pop, nasc, obit = _uf(pop), _uf(nasc), _uf(obit)

    # vegetativo por município e ano, com correção de sub-registro
    ev = nasc.merge(obit, on=["ano", "id_municipio"], how="outer")
    ev["nascimentos"] = ev["nascimentos"].fillna(0) * fat["nascimentos"]
    ev["obitos"] = ev["obitos"].fillna(0) * fat["obitos"]
    ev["vegetativo"] = ev["nascimentos"] - ev["obitos"]

    # peso por ano (fracionamento de fronteira) e soma ponderada por município
    ev = ev[(ev["ano"] >= ini) & (ev["ano"] <= fim)].copy()
    if config.FRACIONAR_FRONTEIRA:
        ev["_peso"] = ev["ano"].map(lambda a: config.peso_ano_intercenso(a, ini, fim))
    else:
        ev["_peso"] = 1.0
    ev["_veg_p"] = ev["vegetativo"] * ev["_peso"]
    veg = ev.groupby("id_municipio")["_veg_p"].sum()

    p_ini = pop[pop["ano"] == ini].set_index("id_municipio")["populacao"]
    p_fim = pop[pop["ano"] == fim].set_index("id_municipio")["populacao"]

    df = pd.DataFrame({"pop_inicial": p_ini, "pop_final": p_fim})
    df = df.dropna(subset=["pop_inicial", "pop_final"])  # exige as duas pontas
    df["vegetativo"] = veg.reindex(df.index).fillna(0)
    df["pop_inicial"] = df["pop_inicial"].astype("int64")
    df["pop_final"] = df["pop_final"].astype("int64")
    df["vegetativo"] = df["vegetativo"].round(0).astype("int64")
    df["delta_pop"] = df["pop_final"] - df["pop_inicial"]
    df["saldo_migratorio"] = (df["delta_pop"] - df["vegetativo"]).round(0).astype("int64")
    df["saldo_pct"] = (df["saldo_migratorio"] / df["pop_inicial"] * 100).round(2)
    # sinaliza pequenas áreas (NÃO remove) — saldo pode ser da ordem do ruído
    df["pequena_area"] = df["pop_inicial"] < config.LIMIAR_PEQUENA_AREA

    df = df.reset_index().rename(columns={"index": "id_municipio"})

    # nomes (se o diretório estiver disponível)
    try:
        dire = data_sources.carregar_diretorio_municipios()
        df = df.merge(dire[["id_municipio", "nome"]], on="id_municipio", how="left")
    except Exception:
        df["nome"] = df["id_municipio"]
    df["nome"] = df["nome"].fillna(df["id_municipio"])

    cols = ["id_municipio", "nome", "pop_inicial", "pop_final", "delta_pop",
            "vegetativo", "saldo_migratorio", "saldo_pct", "pequena_area"]
    return df[cols].sort_values("saldo_migratorio", ascending=False).reset_index(drop=True)
