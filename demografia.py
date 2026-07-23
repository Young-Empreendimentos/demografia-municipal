#!/usr/bin/env python
"""
Demografia municipal (Brasil / foco RS) — interface de linha de comando.

Exemplos:
    python demografia.py --municipio "Bagé"
    python demografia.py --municipio "Porto Alegre" --uf RS
    python demografia.py --id 4301602
    python demografia.py --uf RS --agregado           # série do estado todo
    python demografia.py --municipio "Bagé" --formato xlsx --sem-graficos
    python demografia.py --municipio "Bagé" --force    # ignora cache e reconsulta

Requer um billing_project_id do Google Cloud (veja o README).
"""
from __future__ import annotations

import argparse
import sys

# Em consoles Windows (cp1252) acentos podem quebrar; força UTF-8 na saída.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover
    pass

import pandas as pd

import calculations
import config
import data_sources
import municipios
import reporting


def _print_tabela(df: pd.DataFrame) -> None:
    with pd.option_context(
        "display.max_rows", None, "display.width", 200,
        "display.float_format", lambda x: f"{x:,.2f}",
    ):
        print(df.to_string(index=False))


def _relatar_descartados(sigla_uf: str) -> None:
    """Reporta o volume de eventos sem município de residência (id nulo)."""
    try:
        # No modo nacional, os descartados saem do cache já baixado (sem custo).
        desc = data_sources.contar_descartados_br()
        if desc.empty:
            desc = data_sources.contar_descartados_sem_residencia(sigla_uf)
    except Exception as exc:  # cache ausente + sem BigQuery, etc.
        print(f"(não foi possível quantificar descartados: {exc})")
        return
    if desc.empty:
        print("Nenhum evento sem município de residência no período.")
        return
    total = desc.groupby("fonte")["descartados"].sum()
    print("Eventos descartados por falta de município de residência (id nulo):")
    for fonte, qtd in total.items():
        print(f"  • {fonte}: {qtd:,} registros no período {config.ANO_INICIAL}"
              f"–{config.ANO_FINAL}")


def executar(args: argparse.Namespace) -> int:
    # ------------------------------------------------------------------ UF
    if args.agregado:
        sigla_uf = (args.uf or "RS").upper()
        titulo = f"RS (agregado — todos os municípios 43xxxxx)" if sigla_uf == "RS" \
            else f"{sigla_uf} (agregado)"
        print(f"Construindo série agregada de {sigla_uf}...")
        serie = calculations.construir_serie_uf(sigla_uf)
        nome_base = f"{sigla_uf}_agregado"
    else:
        # --------------------------------------------------- resolve município
        if args.id:
            consulta: str | int = args.id
        elif args.municipio:
            consulta = args.municipio
        else:
            print("Informe --municipio, --id ou --uf --agregado.", file=sys.stderr)
            return 2

        try:
            muni = municipios.resolver(consulta, sigla_uf=args.uf)
        except ValueError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1

        sigla_uf = muni.sigla_uf
        titulo = str(muni)
        print(f"Município: {titulo}")
        print(f"Construindo série de {muni.nome}...")
        serie = calculations.construir_serie_municipio(muni.id_municipio, sigla_uf)
        nome_base = f"{muni.nome}_{muni.id_municipio}".replace(" ", "_")

    if serie.empty:
        print("Nenhum dado encontrado para o período configurado.", file=sys.stderr)
        return 1

    # -------------------------------------------- uniformização (opcional)
    if args.suavizar:
        serie = calculations.reconstruir_serie(serie, metodo=args.suavizar)
        print(f"[modo suavizado: reconstrução intercensitária '{args.suavizar}' — "
              f"população ancorada nos censos, sem saltos de rebaseamento]")

    # ------------------------------------------------------------- cálculos
    intercensos = calculations.saldo_intercensitario(serie)
    resumo = calculations.resumir(serie)

    # -------------------------------------------------------------- saídas
    print("\n=== SÉRIE ANUAL ===")
    _print_tabela(serie)

    if not intercensos.empty:
        print("\n=== SALDO MIGRATÓRIO INTERCENSITÁRIO (método robusto) ===")
        _print_tabela(intercensos)

    print("\n=== RESUMO ===")
    print(f"Período: {resumo['ano_min']}–{resumo['ano_max']}")
    print(f"Pico populacional: {resumo['populacao_pico']:,} habitantes "
          f"em {resumo['ano_pico_populacional']}")
    print(f"Vegetativo acumulado: {resumo['vegetativo_acumulado']:,}")
    print(f"Saldo migratório acumulado (série anual): "
          f"{resumo['saldo_migratorio_acumulado']:,}")
    if args.suavizar and "saldo_migratorio_suave" in serie.columns:
        acum_suave = int(serie["saldo_migratorio_suave"].dropna().sum())
        print(f"Saldo migratório acumulado (reconstruído): {acum_suave:,}")
    if resumo.get("pequena_area"):
        print("⚠ PEQUENA ÁREA: município pequeno — o saldo migratório pode ser "
              "da ordem do ruído (erro censitário + sub-registro). "
              "Valores mantidos; interprete com cautela.")

    print()
    _relatar_descartados(sigla_uf)

    print("\n" + reporting.texto_fontes(sigla_uf))

    # -------------------------------------------------------------- gráficos
    if not args.sem_graficos:
        fig = reporting.figura_completa(serie, titulo)
        png = config.OUTPUT_DIR / f"{nome_base}_graficos.png"
        fig.savefig(png, dpi=120)
        print(f"\nGráficos salvos em: {png}")

    # ------------------------------------------------------------- exportação
    gerados = reporting.exportar(serie, intercensos, resumo, nome_base, args.formato)
    if gerados:
        print("Arquivos exportados:")
        for g in gerados:
            print(f"  • {g}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Séries demográficas municipais (população, nascimentos, "
        "óbitos, crescimento vegetativo e saldo migratório).",
    )
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--municipio", help="nome do município (acentos/caixa livres)")
    grupo.add_argument("--id", help="código IBGE de 7 dígitos")
    p.add_argument("--uf", help="sigla da UF para desambiguar nome (ex.: RS)")
    p.add_argument("--agregado", action="store_true",
                   help="série agregada da UF (use com --uf; padrão RS)")
    p.add_argument("--formato", choices=["csv", "xlsx", "ambos"], default="ambos",
                   help="formato de exportação (default: ambos)")
    p.add_argument("--suavizar", nargs="?", const="uniforme",
                   choices=["uniforme", "proporcional"],
                   help="uniformiza os rebaseamentos do IBGE reconstruindo a "
                        "população a partir dos censos (default: uniforme)")
    p.add_argument("--sem-graficos", action="store_true",
                   help="não gerar os PNGs de gráficos")
    p.add_argument("--force", action="store_true",
                   help="ignora o cache e reconsulta o BigQuery")
    p.add_argument("--baixar-brasil", action="store_true", dest="baixar_brasil",
                   help="baixa o Brasil inteiro uma vez para o cache nacional "
                        "(depois todo município/UF é servido localmente)")
    p.add_argument("--ranking", action="store_true",
                   help="exibe o ranking de saldo migratório dos municípios da "
                        "UF (use com --uf; padrão RS)")
    p.add_argument("--intervalo", help="intervalo do ranking, ex.: 2010-2022 "
                                       "(padrão: último intercensitário)")
    args = p.parse_args()

    # --force: limpa o cache forçando reconsulta na 1ª chamada.
    if args.force:
        for f in config.CACHE_DIR.glob("*.parquet"):
            f.unlink()
        print("Cache limpo (--force): as consultas serão refeitas no BigQuery.")

    # --baixar-brasil: prepara o cache nacional e encerra.
    if args.baixar_brasil:
        print("Baixando dados nacionais (SINASC, SIM, IBGE população, "
              "diretórios)... isto faz 2 varreduras grandes (SINASC e SIM).")
        cont = data_sources.baixar_brasil(force=args.force)
        print("Cache nacional pronto:")
        for k, v in cont.items():
            print(f"  • {k}: {v:,} linhas")
        print(f"Arquivos em: {config.CACHE_DIR}")
        return 0

    # --ranking: ranking municipal da UF e encerra.
    if args.ranking:
        uf = (args.uf or "RS").upper()
        intervalo = None
        if args.intervalo:
            a, b = args.intervalo.split("-")
            intervalo = (int(a), int(b))
        rk = calculations.ranking_uf(uf, intervalo)
        ini, fim = intervalo or config.INTERVALOS_CENSO[-1]
        print(f"Ranking de saldo migratório — {uf}, {ini}–{fim} "
              f"({len(rk)} municípios)\n")
        cols = ["nome", "saldo_migratorio", "saldo_pct", "delta_pop",
                "vegetativo", "pequena_area"]
        print("=== 15 MAIORES (saldo total) ===")
        _print_tabela(rk.head(15)[cols])
        print("\n=== 15 MENORES (saldo total) ===")
        _print_tabela(rk.tail(15)[cols].iloc[::-1])
        saida = config.OUTPUT_DIR / f"ranking_{uf}_{ini}_{fim}.csv"
        rk.to_csv(saida, index=False, encoding="utf-8-sig")
        print(f"\nRanking completo exportado: {saida}")
        return 0

    return executar(args)


if __name__ == "__main__":
    raise SystemExit(main())
