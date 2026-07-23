"""
Fonte ALTERNATIVA (opcional) sem BigQuery: SINASC/SIM via DATASUS (pacote
`pysus`) e população via SIDRA/IBGE.

Mantém a mesma "forma" de saída de `data_sources` para que `calculations` possa
consumir sem alterações:
    carregar_nascimentos(sigla_uf) -> [ano, id_municipio, nascimentos]
    carregar_obitos(sigla_uf)      -> [ano, id_municipio, obitos]
    carregar_populacao(sigla_uf)   -> [ano, id_municipio, populacao]

Para usar, faça no seu script:
    import datasus_source as data_sources
    import calculations
    calculations.data_sources = data_sources

Observações:
  * Requer `pip install pysus`.
  * O DATASUS entrega microdados por UF/ano (arquivos DBC). Aqui contamos por
    município de RESIDÊNCIA (coluna CODMUNRES), coerente com a fonte BigQuery.
  * Os códigos IBGE do DATASUS têm 6 dígitos (sem dígito verificador). Fazemos a
    conversão para 7 dígitos usando a tabela de diretórios.
  * Implementação best-effort; valide os totais contra a fonte principal.
"""
from __future__ import annotations

import pandas as pd

import config

_ANOS = list(range(config.ANO_INICIAL, config.ANO_FINAL + 1))


def _mapa_6_para_7() -> dict[str, str]:
    """Mapa código IBGE de 6 dígitos -> 7 dígitos, via diretório da Base dos Dados.

    Se a Base dos Dados não estiver disponível, este mapeamento pode ser
    substituído por uma tabela IBGE local. Os 6 primeiros dígitos do código de 7
    correspondem ao código sem dígito verificador.
    """
    import data_sources  # reaproveita o diretório (que também tem cache)

    dire = data_sources.carregar_diretorio_municipios()
    return {mid[:6]: mid for mid in dire["id_municipio"]}


def _contar_eventos(grupo: str, sigla_uf: str, coluna_saida: str) -> pd.DataFrame:
    from pysus.online_data import SINASC, SIM  # type: ignore

    fonte = SINASC if grupo == "SINASC" else SIM
    mapa = _mapa_6_para_7()
    frames = []
    for ano in _ANOS:
        try:
            df = fonte.download(sigla_uf, ano)
        except Exception:
            continue  # ano indisponível para a UF
        if df is None or len(df) == 0:
            continue
        col_res = "CODMUNRES" if "CODMUNRES" in df.columns else None
        if col_res is None:
            continue
        d = df[[col_res]].copy()
        d = d[d[col_res].notna()]
        d["id_municipio"] = d[col_res].astype(str).str[:6].map(mapa)
        d = d[d["id_municipio"].notna()]
        contagem = (
            d.groupby("id_municipio").size().rename(coluna_saida).reset_index()
        )
        contagem["ano"] = ano
        frames.append(contagem)

    if not frames:
        return pd.DataFrame(columns=["ano", "id_municipio", coluna_saida])
    out = pd.concat(frames, ignore_index=True)
    return out[["ano", "id_municipio", coluna_saida]]


def carregar_nascimentos(sigla_uf: str, force: bool = False) -> pd.DataFrame:
    return _contar_eventos("SINASC", sigla_uf, "nascimentos")


def carregar_obitos(sigla_uf: str, force: bool = False) -> pd.DataFrame:
    return _contar_eventos("SIM", sigla_uf, "obitos")


def carregar_populacao(sigla_uf: str, force: bool = False) -> pd.DataFrame:
    """População via SIDRA/IBGE.

    Implementação deixada como ponto de extensão: use a API do SIDRA (tabelas
    6579 para estimativas e 4709/9514 para censos) ou o pacote `sidrapy`.
    Retorna colunas [ano, id_municipio, populacao].
    """
    raise NotImplementedError(
        "População via SIDRA não implementada nesta alternativa. Use a fonte "
        "principal (data_sources.carregar_populacao) ou implemente aqui via "
        "SIDRA/IBGE (tabelas 6579 e 4709/9514)."
    )


# reaproveita diretório e descartados da fonte principal
def carregar_diretorio_municipios(force: bool = False) -> pd.DataFrame:
    import data_sources

    return data_sources.carregar_diretorio_municipios(force)
