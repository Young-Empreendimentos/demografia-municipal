"""
Gráficos (matplotlib), texto de fontes/ressalvas e exportação (CSV/XLSX).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # backend sem tela; a CLI salva PNGs
import matplotlib.pyplot as plt
import pandas as pd

import config


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def grafico_populacao(serie: pd.DataFrame, titulo: str, ax=None):
    ax = ax or plt.gca()
    tem_suave = "populacao_suave" in serie.columns
    label_bruto = "Estimativa IBGE (bruta)" if tem_suave else None
    ax.plot(serie["ano"], serie["populacao"], marker="o", color="#1f77b4",
            alpha=0.45 if tem_suave else 1.0, label=label_bruto)
    if tem_suave:
        # série reconstruída (sem os saltos de rebaseamento)
        ax.plot(serie["ano"], serie["populacao_suave"], marker="o",
                color="#ff7f0e", label="Reconstruída (suave)")
    # destaca anos de censo
    censo = serie[serie["tipo_populacao"] == "censo"]
    ax.scatter(
        censo["ano"], censo["populacao"], color="#d62728", zorder=5,
        label="Censo", s=60,
    )
    ax.set_title(f"População — {titulo}")
    ax.set_xlabel("Ano")
    ax.set_ylabel("População")
    ax.grid(True, alpha=0.3)
    ax.legend()
    return ax


def grafico_nasc_obitos(serie: pd.DataFrame, titulo: str, ax=None):
    ax = ax or plt.gca()
    ax.plot(serie["ano"], serie["nascimentos"], marker="o",
            color="#2ca02c", label="Nascimentos")
    ax.plot(serie["ano"], serie["obitos"], marker="o",
            color="#d62728", label="Óbitos")
    # área do crescimento vegetativo (nascimentos acima de óbitos)
    ax.fill_between(
        serie["ano"], serie["nascimentos"], serie["obitos"],
        where=serie["nascimentos"] >= serie["obitos"],
        color="#2ca02c", alpha=0.15, label="Vegetativo (+)",
    )
    ax.fill_between(
        serie["ano"], serie["nascimentos"], serie["obitos"],
        where=serie["nascimentos"] < serie["obitos"],
        color="#d62728", alpha=0.15, label="Vegetativo (−)",
    )
    ax.set_title(f"Nascimentos × Óbitos — {titulo}")
    ax.set_xlabel("Ano")
    ax.set_ylabel("Eventos/ano")
    ax.grid(True, alpha=0.3)
    ax.legend()
    return ax


def grafico_saldo(serie: pd.DataFrame, titulo: str, ax=None):
    ax = ax or plt.gca()
    # No modo suavizado, usa o saldo reconstruído (sem os picos de rebaseamento).
    coluna = "saldo_migratorio_suave" if "saldo_migratorio_suave" in serie.columns \
        else "saldo_migratorio"
    dados = serie.dropna(subset=[coluna])
    cores = ["#1f77b4" if v >= 0 else "#d62728" for v in dados[coluna]]
    ax.bar(dados["ano"], dados[coluna], color=cores)
    ax.axhline(0, color="black", linewidth=0.8)
    sufixo = " (reconstruído)" if coluna.endswith("suave") else ""
    ax.set_title(f"Saldo migratório líquido anual{sufixo} — {titulo}")
    ax.set_xlabel("Ano")
    ax.set_ylabel("Saldo (pessoas)")
    ax.grid(True, alpha=0.3)
    return ax


def figura_completa(serie: pd.DataFrame, titulo: str):
    """Monta uma figura 3-em-1 (usada tanto pela CLI quanto pelo Streamlit)."""
    fig, axes = plt.subplots(3, 1, figsize=(10, 13))
    grafico_populacao(serie, titulo, axes[0])
    grafico_nasc_obitos(serie, titulo, axes[1])
    grafico_saldo(serie, titulo, axes[2])
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Fontes e ressalvas
# ---------------------------------------------------------------------------
FONTES = {
    "populacao": (
        "População: IBGE (estimativas anuais + anos censitários) via Base dos "
        "Dados — br_ibge_populacao.municipio. Anos de censo (2000/2010/2022) são "
        "contagem; demais anos são estimativa."
    ),
    "nascimentos": (
        "Nascimentos: SINASC/Ministério da Saúde via Base dos Dados — "
        "br_ms_sinasc.microdados, contados por município de RESIDÊNCIA."
    ),
    "obitos": (
        "Óbitos: SIM/Ministério da Saúde via Base dos Dados — "
        "br_ms_sim.microdados, contados por município de RESIDÊNCIA."
    ),
    "vegetativo": (
        "Crescimento vegetativo: cálculo próprio = nascimentos − óbitos (por ano)."
    ),
    "saldo_migratorio": (
        "Saldo migratório: cálculo próprio pelo método do resíduo "
        "(Δpopulação − crescimento vegetativo). É um saldo LÍQUIDO (não separa "
        "entradas de saídas; inclui migração interna, internacional e "
        "reconciliação estatística)."
    ),
    "diretorio": (
        "Nomes/códigos de município: IBGE via Base dos Dados — "
        "br_bd_diretorios_brasil.municipio."
    ),
}

RESSALVAS = [
    "Eventos contados por município de RESIDÊNCIA; residentes que tiveram o "
    "evento em outra UF podem faltar (pequeno vazamento).",
    "Registros sem município de residência (id nulo) são excluídos dos totais "
    "municipais (volume reportado à parte).",
    "Saldo migratório é LÍQUIDO — não distingue quem entrou de quem saiu.",
    "Ao agregar 'todos do RS', filtramos id_municipio iniciados em 43; o filtro "
    "sigla_uf pega a UF de OCORRÊNCIA e incluiria municípios de outras UFs.",
    "O resíduo é um saldo 'contaminado': além da migração líquida, ele absorve "
    "erros de contagem censitária e de sub-registro de nascimentos/óbitos. Não "
    "é migração pura.",
    "Pequenas áreas: em municípios pequenos o saldo pode ser da ordem do próprio "
    "ruído (erro censitário + sub-registro). Os valores são mantidos (nada é "
    "descartado), mas interprete municípios pequenos com cautela.",
]

# Notas de validação/triangulação: como conferir a ordem de grandeza do saldo.
VALIDACAO = [
    "Este saldo é pelo MÉTODO DO RESÍDUO no período intercensitário completo "
    "(ex.: 2010–2022, ~12 anos) e é LÍQUIDO.",
    "NÃO é diretamente comparável ao dado de migração do Censo por quesito "
    "'data-fixa'. Ex.: o DEE-RS (Cadernos RS no Censo 2022) reporta, por "
    "data-fixa 2017–2022, saldo líquido de −77,8 mil e taxa de −0,72% — mas "
    "isso é fluxo BRUTO, 5 anos, só sobreviventes que mudaram de município de "
    "referência; conceito e período diferentes.",
    "Para validar sinal e ordem de grandeza, triangule com: (a) o quesito "
    "data-fixa do Censo 2022; (b) a Razão de Sobrevivência Censitária (CSMR), "
    "que estima migração líquida sem depender de SINASC/SIM. Convergência de "
    "sinal entre os métodos é a melhor checagem disponível.",
    "Referência: DEE-RS, 'Cadernos RS no Censo 2022: Migração e Fecundidade' "
    "(nov/2025) — dee.rs.gov.br.",
]


def texto_correcoes(sigla_uf: str | None = None) -> list[str]:
    """Lista as correções metodológicas ativas (lê o estado de config)."""
    linhas = []
    if config.FRACIONAR_FRONTEIRA:
        linhas.append(
            "Fronteira temporal: CORRIGIDA — os anos de ponta são ponderados "
            "pela fração de meses dentro do intervalo censitário (censos com "
            "referência em ~1º/ago), somando exatamente (fim − ini) anos.")
    else:
        linhas.append(
            "Fronteira temporal: NÃO corrigida — soma de anos-calendário "
            "inteiros superestima ~1 ano de vegetativo.")
    if config.APLICAR_SUBREGISTRO:
        nota = ""
        if sigla_uf:
            fat = config.fatores_subregistro(sigla_uf)
            nota = (f" Fatores {sigla_uf}: nascimentos ×{fat['nascimentos']}, "
                    f"óbitos ×{fat['obitos']} [{fat['fonte']}].")
        linhas.append(
            "Sub-registro: CORRIGIDO — nascimentos/óbitos multiplicados por "
            "1/cobertura. Coberturas regionais APROXIMADAS (substitua pelos "
            "fatores oficiais do IBGE por UF/ano via fatores_subregistro.csv)."
            + nota)
    else:
        linhas.append("Sub-registro: NÃO corrigido (contagens brutas do SINASC/SIM).")
    linhas.append(
        f"Pequenas áreas: municípios com população < {config.LIMIAR_PEQUENA_AREA:,} "
        "são SINALIZADOS (nunca removidos); nesses casos o saldo pode ser da "
        "ordem do ruído.")
    return linhas


def texto_fontes(sigla_uf: str | None = None) -> str:
    linhas = ["FONTES", "------"]
    linhas += [f"• {v}" for v in FONTES.values()]
    linhas += ["", "CORREÇÕES APLICADAS", "-------------------"]
    linhas += [f"• {v}" for v in texto_correcoes(sigla_uf)]
    linhas += ["", "RESSALVAS", "---------"]
    linhas += [f"• {v}" for v in RESSALVAS]
    linhas += ["", "VALIDAÇÃO / TRIANGULAÇÃO", "------------------------"]
    linhas += [f"• {v}" for v in VALIDACAO]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def exportar(
    serie: pd.DataFrame,
    intercensos: pd.DataFrame,
    resumo: dict,
    nome_base: str,
    formato: str = "ambos",
) -> list[Path]:
    """Exporta série, intervalos e resumo. `formato`: 'csv', 'xlsx' ou 'ambos'."""
    gerados: list[Path] = []
    base = config.OUTPUT_DIR / nome_base

    resumo_df = pd.DataFrame([resumo]) if resumo else pd.DataFrame()

    if formato in ("csv", "ambos"):
        p1 = base.with_name(f"{nome_base}_serie.csv")
        serie.to_csv(p1, index=False, encoding="utf-8-sig")
        gerados.append(p1)
        if not intercensos.empty:
            p2 = base.with_name(f"{nome_base}_intercensos.csv")
            intercensos.to_csv(p2, index=False, encoding="utf-8-sig")
            gerados.append(p2)

    if formato in ("xlsx", "ambos"):
        p3 = base.with_name(f"{nome_base}.xlsx")
        try:
            with pd.ExcelWriter(p3, engine="openpyxl") as xw:
                serie.to_excel(xw, sheet_name="serie_anual", index=False)
                if not intercensos.empty:
                    intercensos.to_excel(
                        xw, sheet_name="intercensos", index=False
                    )
                if not resumo_df.empty:
                    resumo_df.to_excel(xw, sheet_name="resumo", index=False)
            gerados.append(p3)
        except ImportError:
            # openpyxl ausente: XLSX é opcional, seguimos com CSV
            pass

    return gerados
