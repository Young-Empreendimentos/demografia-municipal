"""
Acesso às fontes de dados via Base dos Dados (BigQuery), com cache local em
parquet para controle de custo.

Fontes:
  * Nascimentos : basedosdados.br_ms_sinasc.microdados   (SINASC/MS)
  * Óbitos      : basedosdados.br_ms_sim.microdados       (SIM/MS)
  * População   : basedosdados.br_ibge_populacao.municipio (IBGE)
  * Diretório   : basedosdados.br_bd_diretorios_brasil.municipio

Cada função de consulta grava o resultado em `cache/<chave>.parquet`. Numa
segunda execução com os mesmos parâmetros, os dados vêm do parquet e NENHUMA
consulta é feita ao BigQuery (a menos que force=True).

As contagens de nascimentos/óbitos são feitas por `id_municipio_residencia`.
Registros sem município de residência (id nulo) são naturalmente descartados
pelo GROUP BY do BigQuery; o volume descartado é reportado à parte por
`contar_descartados_sem_residencia`.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

import config

# ---------------------------------------------------------------------------
# Camada de cache
# ---------------------------------------------------------------------------
def _cache_path(chave: str) -> Path:
    """Nome de arquivo seguro derivado de uma chave textual."""
    slug = hashlib.md5(chave.encode("utf-8")).hexdigest()[:16]
    return config.CACHE_DIR / f"{chave.split('|')[0]}_{slug}.parquet"


def _ler_cache(chave: str) -> pd.DataFrame | None:
    caminho = _cache_path(chave)
    if caminho.exists():
        return pd.read_parquet(caminho)
    return None


def _gravar_cache(chave: str, df: pd.DataFrame) -> None:
    df.to_parquet(_cache_path(chave), index=False)


# ---------------------------------------------------------------------------
# Execução de SQL no BigQuery (lazy import do basedosdados)
# ---------------------------------------------------------------------------
def _run_query(sql: str) -> pd.DataFrame:
    """Executa uma query no BigQuery via basedosdados.

    O import é adiado para dentro da função para que o resto do programa
    (ex.: leitura de cache, testes) funcione mesmo sem o pacote instalado.
    """
    billing = config.get_billing_project_id()
    if not billing:
        raise RuntimeError(
            "billing_project_id não configurado. Defina a variável de ambiente "
            "BILLING_PROJECT_ID ou crie o arquivo `.billing_project`. "
            "Veja o README."
        )
    try:
        import basedosdados as bd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Pacote `basedosdados` não instalado. Rode: pip install basedosdados"
        ) from exc

    return bd.read_sql(sql, billing_project_id=billing)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def carregar_diretorio_municipios(force: bool = False) -> pd.DataFrame:
    """Tabela de diretório: id_municipio (7 díg.), nome, sigla_uf.

    Colunas retornadas: id_municipio (str), nome (str), sigla_uf (str).
    """
    chave = "diretorio-municipios"
    if not force:
        cache = _ler_cache(chave)
        if cache is not None:
            return cache

    sql = """
        SELECT id_municipio, nome, sigla_uf
        FROM `basedosdados.br_bd_diretorios_brasil.municipio`
    """
    df = _run_query(sql)
    df["id_municipio"] = df["id_municipio"].astype(str)
    _gravar_cache(chave, df)
    return df


# ---------------------------------------------------------------------------
# Modo NACIONAL (Brasil inteiro) — baixa uma vez, serve todos os municípios.
#
# Custo: como as tabelas de eventos são particionadas por `ano`, o BigQuery lê
# as MESMAS colunas/bytes das partições selecionadas independentemente de haver
# ou não filtro por UF. Ou seja, baixar o Brasil todo custa ~o mesmo que baixar
# uma única UF; o resultado (parquet) tem só ~130 mil linhas por tabela.
#
# Quando um cache nacional (`*-BR.parquet`) existe, os loaders por UF fatiam
# dele (por prefixo do id_municipio = residência) SEM nova consulta ao BigQuery.
# ---------------------------------------------------------------------------
def carregar_populacao_br(force: bool = False) -> pd.DataFrame:
    """População anual (IBGE) de TODOS os municípios do Brasil."""
    chave = "populacao-BR"
    if not force:
        cache = _ler_cache(chave)
        if cache is not None:
            return cache
    sql = f"""
        SELECT ano, id_municipio, populacao
        FROM `basedosdados.br_ibge_populacao.municipio`
        WHERE ano BETWEEN {config.ANO_INICIAL} AND {config.ANO_FINAL}
    """
    df = _run_query(sql)
    df["id_municipio"] = df["id_municipio"].astype(str)
    df["ano"] = df["ano"].astype(int)
    df["populacao"] = df["populacao"].astype("int64")
    _gravar_cache(chave, df)
    return df


def _carregar_eventos_br_raw(
    tabela: str, coluna_saida: str, force: bool
) -> pd.DataFrame:
    """Contagem de eventos por RESIDÊNCIA e ano, Brasil todo — INCLUINDO as
    linhas sem município de residência (id nulo), que formam seu próprio grupo.

    Guardar as linhas de id nulo aqui permite reportar os "descartados" sem uma
    segunda varredura da tabela (economia de custo). O cache bruto tem a chave
    `<coluna>-BR`. As linhas de id nulo são separadas na leitura pública.
    """
    chave = f"{coluna_saida}-BR"
    if not force:
        cache = _ler_cache(chave)
        if cache is not None:
            return cache
    # Sem 'IS NOT NULL': o id nulo vira um grupo (descartados), na MESMA leitura.
    sql = f"""
        SELECT dados.ano AS ano,
               dados.id_municipio_residencia AS id_municipio,
               COUNT(*) AS {coluna_saida}
        FROM `{tabela}` AS dados
        WHERE dados.ano BETWEEN {config.ANO_INICIAL} AND {config.ANO_FINAL}
        GROUP BY ano, id_municipio
    """
    df = _run_query(sql)
    # id_municipio pode ser nulo (descartados) -> tipo nullable string
    df["id_municipio"] = df["id_municipio"].astype("string")
    df["ano"] = df["ano"].astype(int)
    df[coluna_saida] = df[coluna_saida].astype("int64")
    _gravar_cache(chave, df)
    return df


def _carregar_eventos_br(
    tabela: str, coluna_saida: str, force: bool
) -> pd.DataFrame:
    """Versão municipal-utilizável: exclui as linhas de id nulo (descartados)."""
    raw = _carregar_eventos_br_raw(tabela, coluna_saida, force)
    return raw[raw["id_municipio"].notna()].reset_index(drop=True)


def carregar_nascimentos_br(force: bool = False) -> pd.DataFrame:
    return _carregar_eventos_br(
        "basedosdados.br_ms_sinasc.microdados", "nascimentos", force
    )


def carregar_obitos_br(force: bool = False) -> pd.DataFrame:
    return _carregar_eventos_br(
        "basedosdados.br_ms_sim.microdados", "obitos", force
    )


def contar_descartados_br() -> pd.DataFrame:
    """Descartados nacionais (id de residência nulo), extraídos do cache bruto
    já baixado — SEM nova consulta. Colunas: fonte, ano, descartados.
    Retorna vazio se o cache nacional ainda não existe."""
    linhas = []
    for tabela, coluna, fonte in [
        ("basedosdados.br_ms_sinasc.microdados", "nascimentos", "nascimentos"),
        ("basedosdados.br_ms_sim.microdados", "obitos", "obitos"),
    ]:
        cache = _ler_cache(f"{coluna}-BR")
        if cache is None:
            continue
        nulos = cache[cache["id_municipio"].isna()]
        for _, r in nulos.iterrows():
            linhas.append(
                {"fonte": fonte, "ano": int(r["ano"]),
                 "descartados": int(r[coluna])}
            )
    return pd.DataFrame(linhas, columns=["fonte", "ano", "descartados"])


def baixar_brasil(force: bool = False) -> dict[str, int]:
    """Baixa e cacheia as tabelas nacionais de uma vez (2 varreduras: SINASC e
    SIM; população e diretório são baratos). Depois, tudo é servido do cache
    local. Retorna contagem de linhas municipais por tabela."""
    dire = carregar_diretorio_municipios(force)
    pop = carregar_populacao_br(force)
    nasc = carregar_nascimentos_br(force)
    obit = carregar_obitos_br(force)
    return {
        "diretorio": len(dire),
        "populacao": len(pop),
        "nascimentos": len(nasc),
        "obitos": len(obit),
    }


# ---------------------------------------------------------------------------
# Loaders por UF (fatiam do cache nacional se existir; senão consultam a UF)
# ---------------------------------------------------------------------------
def _fatiar_uf(nacional: pd.DataFrame, sigla_uf: str) -> pd.DataFrame:
    """Filtra o cache nacional para uma UF pelo prefixo do id_municipio."""
    prefixo = config.prefixo_uf(sigla_uf)
    mask = nacional["id_municipio"].str.startswith(prefixo, na=False)
    # devolve id como str simples (não nullable) para consistência a jusante
    out = nacional[mask].copy()
    out["id_municipio"] = out["id_municipio"].astype(str)
    return out.reset_index(drop=True)


def carregar_populacao(sigla_uf: str, force: bool = False) -> pd.DataFrame:
    """População anual (IBGE) de uma UF.

    Se o cache nacional existir, fatia dele; senão consulta só a UF.
    Colunas: ano (int), id_municipio (str), populacao (int).
    """
    if not force and _ler_cache("populacao-BR") is not None:
        return _fatiar_uf(carregar_populacao_br(), sigla_uf)

    chave = f"populacao-{sigla_uf}"
    if not force:
        cache = _ler_cache(chave)
        if cache is not None:
            return cache
    sql = f"""
        SELECT ano, id_municipio, populacao
        FROM `basedosdados.br_ibge_populacao.municipio`
        WHERE sigla_uf = '{sigla_uf}'
          AND ano BETWEEN {config.ANO_INICIAL} AND {config.ANO_FINAL}
    """
    df = _run_query(sql)
    df["id_municipio"] = df["id_municipio"].astype(str)
    df["ano"] = df["ano"].astype(int)
    df["populacao"] = df["populacao"].astype("int64")
    _gravar_cache(chave, df)
    return df


def _carregar_eventos(
    tabela: str, coluna_saida: str, sigla_uf: str, force: bool
) -> pd.DataFrame:
    """Contagem de eventos vitais por município de RESIDÊNCIA e ano, para uma UF.

    Se o cache nacional existir, fatia dele; senão consulta só a UF (filtro por
    UF de OCORRÊNCIA). Retorna: ano (int), id_municipio (str), <coluna_saida> (int).
    """
    if not force and _ler_cache(f"{coluna_saida}-BR") is not None:
        return _fatiar_uf(_carregar_eventos_br(tabela, coluna_saida, False), sigla_uf)

    chave = f"{coluna_saida}-{sigla_uf}"
    if not force:
        cache = _ler_cache(chave)
        if cache is not None:
            return cache
    sql = f"""
        SELECT dados.ano AS ano,
               dados.id_municipio_residencia AS id_municipio,
               COUNT(*) AS {coluna_saida}
        FROM `{tabela}` AS dados
        WHERE dados.sigla_uf = '{sigla_uf}'
          AND dados.ano BETWEEN {config.ANO_INICIAL} AND {config.ANO_FINAL}
          AND dados.id_municipio_residencia IS NOT NULL
        GROUP BY ano, id_municipio
    """
    df = _run_query(sql)
    df["id_municipio"] = df["id_municipio"].astype(str)
    df["ano"] = df["ano"].astype(int)
    df[coluna_saida] = df[coluna_saida].astype("int64")
    _gravar_cache(chave, df)
    return df


def carregar_nascimentos(sigla_uf: str, force: bool = False) -> pd.DataFrame:
    return _carregar_eventos(
        "basedosdados.br_ms_sinasc.microdados", "nascimentos", sigla_uf, force
    )


def carregar_obitos(sigla_uf: str, force: bool = False) -> pd.DataFrame:
    return _carregar_eventos(
        "basedosdados.br_ms_sim.microdados", "obitos", sigla_uf, force
    )


def contar_descartados_sem_residencia(
    sigla_uf: str, force: bool = False
) -> pd.DataFrame:
    """Quantifica eventos SEM município de residência (id nulo), por fonte e ano.

    Serve para reportar o volume descartado dos totais municipais.
    Colunas: fonte (str), ano (int), descartados (int).
    """
    chave = f"descartados-{sigla_uf}"
    if not force:
        cache = _ler_cache(chave)
        if cache is not None:
            return cache

    def _q(tabela: str, fonte: str) -> pd.DataFrame:
        sql = f"""
            SELECT dados.ano AS ano, COUNT(*) AS descartados
            FROM `{tabela}` AS dados
            WHERE dados.sigla_uf = '{sigla_uf}'
              AND dados.ano BETWEEN {config.ANO_INICIAL} AND {config.ANO_FINAL}
              AND dados.id_municipio_residencia IS NULL
            GROUP BY ano
        """
        d = _run_query(sql)
        d["fonte"] = fonte
        return d

    df = pd.concat(
        [
            _q("basedosdados.br_ms_sinasc.microdados", "nascimentos"),
            _q("basedosdados.br_ms_sim.microdados", "obitos"),
        ],
        ignore_index=True,
    )
    if not df.empty:
        df["ano"] = df["ano"].astype(int)
        df["descartados"] = df["descartados"].astype("int64")
    _gravar_cache(chave, df)
    return df
