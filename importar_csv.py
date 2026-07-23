"""
Importa resultados CSV exportados do console do BigQuery para o cache nacional,
SEM precisar de autenticação nem do pacote basedosdados.

Use quando você rodou as queries no console web e baixou os resultados. Os CSVs
devem ter os cabeçalhos:
    nascimentos : ano, id_municipio, nascimentos
    obitos      : ano, id_municipio, obitos
    populacao   : ano, id_municipio, populacao
    diretorio   : id_municipio, nome, sigla_uf   (opcional; habilita busca por nome)

Exemplo:
    python importar_csv.py \
        --nascimentos "C:/.../nasc.csv" \
        --obitos "C:/.../obit.csv" \
        --populacao "C:/.../pop.csv" \
        [--diretorio "C:/.../dir.csv"]
"""
from __future__ import annotations

import argparse

import pandas as pd

import config
import data_sources


def _descartar_valor_nulo(df: pd.DataFrame, coluna: str, path: str) -> pd.DataFrame:
    """Remove linhas com valor nulo na coluna de medida (gaps da fonte)."""
    n_nulos = int(df[coluna].isna().sum())
    if n_nulos:
        print(f"  aviso: {n_nulos} linha(s) de {path} sem '{coluna}' (descartadas)")
        df = df[df[coluna].notna()]
    return df


def _importar_eventos(path: str, coluna: str) -> int:
    df = pd.read_csv(path)
    faltando = {"ano", "id_municipio", coluna} - set(df.columns)
    if faltando:
        raise ValueError(f"{path}: colunas ausentes {faltando}. Achei {list(df.columns)}")
    df = _descartar_valor_nulo(df, coluna, path)
    # id como string nullable (pode haver id nulo = descartados, se a query não filtrou)
    df["id_municipio"] = df["id_municipio"].astype("string")
    df["ano"] = df["ano"].astype(int)
    df[coluna] = df[coluna].astype("int64")
    df = df[["ano", "id_municipio", coluna]]
    data_sources._gravar_cache(f"{coluna}-BR", df)
    return len(df)


def _importar_populacao(path: str) -> int:
    df = pd.read_csv(path)
    faltando = {"ano", "id_municipio", "populacao"} - set(df.columns)
    if faltando:
        raise ValueError(f"{path}: colunas ausentes {faltando}. Achei {list(df.columns)}")
    df = _descartar_valor_nulo(df, "populacao", path)
    df["id_municipio"] = df["id_municipio"].astype(str)
    df["ano"] = df["ano"].astype(int)
    df["populacao"] = df["populacao"].astype("int64")
    df = df[["ano", "id_municipio", "populacao"]]
    data_sources._gravar_cache("populacao-BR", df)
    return len(df)


def _importar_diretorio(path: str) -> int:
    df = pd.read_csv(path)
    faltando = {"id_municipio", "nome", "sigla_uf"} - set(df.columns)
    if faltando:
        raise ValueError(f"{path}: colunas ausentes {faltando}. Achei {list(df.columns)}")
    df["id_municipio"] = df["id_municipio"].astype(str)
    df = df[["id_municipio", "nome", "sigla_uf"]]
    data_sources._gravar_cache("diretorio-municipios", df)
    return len(df)


def main() -> int:
    p = argparse.ArgumentParser(description="Importa CSVs do BigQuery para o cache.")
    p.add_argument("--nascimentos")
    p.add_argument("--obitos")
    p.add_argument("--populacao")
    p.add_argument("--diretorio")
    args = p.parse_args()

    if not any([args.nascimentos, args.obitos, args.populacao, args.diretorio]):
        p.error("informe ao menos um arquivo (--nascimentos/--obitos/--populacao/--diretorio)")

    if args.nascimentos:
        n = _importar_eventos(args.nascimentos, "nascimentos")
        print(f"nascimentos-BR: {n:,} linhas")
    if args.obitos:
        n = _importar_eventos(args.obitos, "obitos")
        print(f"obitos-BR: {n:,} linhas")
    if args.populacao:
        n = _importar_populacao(args.populacao)
        print(f"populacao-BR: {n:,} linhas")
    if args.diretorio:
        n = _importar_diretorio(args.diretorio)
        print(f"diretorio-municipios: {n:,} linhas")

    print(f"Cache em: {config.CACHE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
