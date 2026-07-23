"""
App Streamlit para demografia municipal.

Rodar:
    streamlit run app.py   (ou dê dois cliques em "Abrir App Demografia.bat")

Dois modos (menu na barra lateral):
  • Município / Estado — série histórica, gráficos e cálculos de uma cidade ou
    do agregado estadual.
  • Ranking do estado — todos os municípios da UF ordenados por saldo migratório
    (total ou % da população), com ordenação por clique nas colunas.
"""
from __future__ import annotations

import streamlit as st

import calculations
import config
import data_sources
import municipios
import reporting

st.set_page_config(page_title="Demografia Municipal", layout="wide")
st.title("📊 Demografia municipal — Brasil (foco RS)")
st.caption(
    "População, nascimentos, óbitos, crescimento vegetativo e saldo migratório. "
    f"Período: {config.ANO_INICIAL}–{config.ANO_FINAL}."
)

# --- Estado do cache / billing ---------------------------------------------
_cache_nacional = bool(
    list(config.CACHE_DIR.glob("populacao-BR_*.parquet"))
    or list(config.CACHE_DIR.glob("populacao-BR_*.csv"))
)
if _cache_nacional:
    st.success("Cache nacional carregado — todos os municípios do Brasil "
               "disponíveis localmente, sem consultar o BigQuery.")
elif not config.get_billing_project_id():
    st.warning(
        "billing_project_id do Google Cloud não configurado e sem cache nacional. "
        "Defina `BILLING_PROJECT_ID`/`.billing_project`, ou importe os CSVs "
        "(importar_csv.py). Sem isso, só é possível visualizar UFs já em cache."
    )

# ---------------------------------------------------------------------------
# Barra lateral: modo e UF
# ---------------------------------------------------------------------------
modo_app = st.sidebar.radio(
    "Modo", ["Município / Estado", "Ranking do estado", "Metodologia"])
uf = st.sidebar.selectbox(
    "UF", ["RS", "SC", "PR", "SP", "MG", "RJ", "BA", "Outra..."]
)
if uf == "Outra...":
    uf = st.sidebar.text_input("Digite a sigla da UF", value="RS").upper()


@st.cache_data(show_spinner="Carregando diretório de municípios...")
def _municipios_uf(sigla_uf: str):
    return municipios.listar_por_uf(sigla_uf)


@st.cache_data(show_spinner="Consultando/lendo cache...")
def _serie_municipio(id_municipio: str, sigla_uf: str):
    return calculations.construir_serie_municipio(id_municipio, sigla_uf)


@st.cache_data(show_spinner="Agregando UF...")
def _serie_uf(sigla_uf: str):
    return calculations.construir_serie_uf(sigla_uf)


@st.cache_data(show_spinner="Calculando ranking...")
def _ranking(sigla_uf: str, intervalo: tuple[int, int]):
    return calculations.ranking_uf(sigla_uf, intervalo)


# ===========================================================================
# MODO 1: Município / Estado
# ===========================================================================
if modo_app == "Município / Estado":
    try:
        lista = _municipios_uf(uf)
        nomes = lista["nome"].tolist()
    except Exception as exc:
        st.error(f"Não foi possível carregar municípios de {uf}: {exc}")
        st.stop()

    col1, col2 = st.columns([1, 2])
    with col1:
        modo_sel = st.radio("Selecionar por", ["Nome", "Código IBGE"],
                            horizontal=True)
    with col2:
        if modo_sel == "Nome":
            nome_sel = st.selectbox("Município", nomes)
            id_sel = lista[lista["nome"] == nome_sel]["id_municipio"].iloc[0]
        else:
            id_sel = st.text_input("Código IBGE (7 dígitos)", value="4301602")

    agregado = st.checkbox(f"Mostrar agregado do estado ({uf}) em vez do município")

    col_s1, col_s2 = st.columns([1, 2])
    with col_s1:
        suavizar = st.checkbox(
            "Uniformizar rebaseamentos do IBGE",
            help="Reconstrói a população a partir dos censos (equação de "
                 "balanço), removendo os saltos das revisões de estimativa.")
    with col_s2:
        metodo = st.radio(
            "Distribuição do saldo migratório", ["uniforme", "proporcional"],
            horizontal=True, disabled=not suavizar,
            help="uniforme: mesmo nº de migrantes/ano. proporcional: "
                 "proporcional à população (taxa ~constante).")

    if st.button("Gerar análise", type="primary"):
        try:
            if agregado:
                serie = _serie_uf(uf)
                titulo = f"{uf} (agregado)"
            else:
                muni = municipios.resolver(id_sel, sigla_uf=uf)
                serie = _serie_municipio(muni.id_municipio, uf)
                titulo = str(muni)
        except Exception as exc:
            st.error(f"Erro: {exc}")
            st.stop()

        if serie.empty:
            st.warning("Sem dados para o período.")
            st.stop()

        if suavizar:
            serie = calculations.reconstruir_serie(serie, metodo=metodo)
            st.info(f"Modo suavizado ativo (reconstrução intercensitária "
                    f"'{metodo}'): população ancorada nos censos, sem os saltos "
                    f"de rebaseamento das estimativas.")

        intercensos = calculations.saldo_intercensitario(serie)
        resumo = calculations.resumir(serie)

        if resumo.get("pequena_area"):
            st.warning("⚠ **Pequena área**: município pequeno — o saldo "
                       "migratório pode ser da ordem do ruído (erro censitário + "
                       "sub-registro). Valores mantidos; interprete com cautela.")

        # Resumo em métricas
        st.subheader(f"Resumo — {titulo}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Pico populacional", f"{resumo['populacao_pico']:,}",
                  f"em {resumo['ano_pico_populacional']}")
        m2.metric("Vegetativo acumulado", f"{resumo['vegetativo_acumulado']:,}")
        m3.metric("Saldo migratório acum.",
                  f"{resumo['saldo_migratorio_acumulado']:,}")
        # taxa % acumulada = saldo acumulado ÷ população inicial da série
        pop0 = int(serie.iloc[0]["populacao"])
        taxa = resumo["saldo_migratorio_acumulado"] / pop0 * 100
        m4.metric("Saldo migratório acum. (% da pop. inicial)", f"{taxa:.1f}%")

        # Gráficos
        st.subheader("Gráficos")
        st.pyplot(reporting.figura_completa(serie, titulo))

        # Tabelas
        st.subheader("Série anual")
        st.caption("A coluna **saldo_pct** é o saldo migratório do ano em % da "
                   "população daquele ano.")
        st.dataframe(serie, use_container_width=True)

        if not intercensos.empty:
            st.subheader("Saldo migratório intercensitário (método robusto)")
            st.dataframe(intercensos, use_container_width=True)

        csv = serie.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("Baixar série (CSV)", csv,
                           file_name=f"{titulo}_serie.csv", mime="text/csv")

        st.subheader("Fontes, correções e ressalvas")
        st.text(reporting.texto_fontes(uf))

# ===========================================================================
# MODO 2: Ranking do estado
# ===========================================================================
elif modo_app == "Ranking do estado":
    st.subheader(f"Ranking municipal — {uf}")

    intervalos = {f"{a}–{b}": (a, b) for a, b in config.INTERVALOS_CENSO}
    col_r1, col_r2, col_r3 = st.columns([1, 1, 1])
    with col_r1:
        rot_int = st.selectbox("Intervalo intercensitário",
                               list(intervalos.keys()),
                               index=len(intervalos) - 1)
    with col_r2:
        metrica = st.radio("Ordenar por", ["Saldo total", "% da população"],
                           horizontal=True)
    with col_r3:
        sentido = st.radio("Ordem", ["Maiores primeiro", "Menores primeiro"],
                           horizontal=True)

    intervalo = intervalos[rot_int]

    try:
        rk = _ranking(uf, intervalo)
    except Exception as exc:
        st.error(f"Não foi possível calcular o ranking de {uf}: {exc}")
        st.stop()

    coluna = "saldo_migratorio" if metrica == "Saldo total" else "saldo_pct"
    asc = sentido == "Menores primeiro"
    rk = rk.sort_values(coluna, ascending=asc).reset_index(drop=True)
    rk.index += 1  # posição no ranking (1..N)

    st.caption(
        f"{len(rk)} municípios de {uf}, intervalo {rot_int}. Método do resíduo "
        "com pontas em anos de censo (população robusta). **Clique no cabeçalho "
        "de qualquer coluna para reordenar.** `saldo_pct` = saldo ÷ população "
        f"de {intervalo[0]}."
    )

    # métricas de topo: destaques
    d1, d2 = st.columns(2)
    top = rk.sort_values(coluna, ascending=False).iloc[0]
    bot = rk.sort_values(coluna, ascending=False).iloc[-1]
    def _fmt(v: float) -> str:
        if coluna == "saldo_pct":
            return f"{v:.1f}%"
        return f"{v:,.0f}".replace(",", ".")

    d1.metric(f"Maior {metrica.lower()}", f"{top['nome']}", _fmt(top[coluna]))
    d2.metric(f"Menor {metrica.lower()}", f"{bot['nome']}", _fmt(bot[coluna]))

    rk_show = rk.copy()
    rk_show["Pequena área"] = rk_show["pequena_area"].map({True: "⚠", False: ""})
    df_show = rk_show.rename(columns={
        "nome": "Município", "pop_inicial": f"Pop. {intervalo[0]}",
        "pop_final": f"Pop. {intervalo[1]}", "delta_pop": "Δ Pop.",
        "vegetativo": "Vegetativo", "saldo_migratorio": "Saldo migratório",
        "saldo_pct": "Saldo %",
    })[["Município", f"Pop. {intervalo[0]}", f"Pop. {intervalo[1]}",
        "Δ Pop.", "Vegetativo", "Saldo migratório", "Saldo %", "Pequena área"]]
    st.dataframe(df_show, use_container_width=True, height=560)
    st.caption("⚠ = pequena área (pop. inicial < "
               f"{config.LIMIAR_PEQUENA_AREA:,}): saldo mais sujeito a ruído. "
               "Nenhum município é removido.")

    csv = rk.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("Baixar ranking (CSV)", csv,
                       file_name=f"ranking_{uf}_{intervalo[0]}_{intervalo[1]}.csv",
                       mime="text/csv")

# ===========================================================================
# MODO 3: Metodologia
# ===========================================================================
else:
    doc = config.BASE_DIR / "METODOLOGIA.md"
    if doc.exists():
        st.markdown(doc.read_text(encoding="utf-8"))
        st.download_button("Baixar metodologia (Markdown)",
                           doc.read_text(encoding="utf-8"),
                           file_name="METODOLOGIA.md", mime="text/markdown")
    else:
        st.error("Arquivo METODOLOGIA.md não encontrado.")
