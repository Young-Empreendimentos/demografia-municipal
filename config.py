"""
Configuração central do app de demografia municipal.

O único parâmetro que você PRECISA definir é o `billing_project_id` do Google
Cloud, usado pelo pacote `basedosdados` para faturar as consultas ao BigQuery.

Ordem de resolução do billing_project_id (a primeira que existir vence):
  1. variável de ambiente BILLING_PROJECT_ID
  2. variável de ambiente GOOGLE_CLOUD_PROJECT
  3. arquivo local `.billing_project` (uma linha com o id do projeto)

Consulte o README para instruções de autenticação (`gcloud auth ...`).
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Diretórios
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Janela temporal padrão
# ---------------------------------------------------------------------------
# SINASC/SIM têm boa cobertura a partir de ~1996; população IBGE por município
# começa em 2000. Restringimos a partir de 2000 por padrão, mas o usuário pode
# ampliar. 2022 é o último censo consolidado.
ANO_INICIAL = int(os.environ.get("DEMOG_ANO_INICIAL", 2000))
ANO_FINAL = int(os.environ.get("DEMOG_ANO_FINAL", 2022))

# Anos censitários conhecidos (o restante da série IBGE é estimativa anual).
ANOS_CENSO = {2000, 2010, 2022}

# Intervalos intercensitários usados no cálculo robusto do saldo migratório.
INTERVALOS_CENSO = [(2000, 2010), (2010, 2022)]

# ---------------------------------------------------------------------------
# Correção de fronteira temporal
# ---------------------------------------------------------------------------
# Os censos têm data de referência em ~1º de agosto (2000, 2010 e 2022). Os
# eventos vitais são somados por ano-calendário. Sem correção, somar os anos
# de ponta inteiros inclui meses fora do intervalo censo-a-censo e superestima
# o crescimento vegetativo. Com FRACIONAR_FRONTEIRA=True, ponderamos os anos de
# ponta pela fração de meses dentro do intervalo (ano inicial: ago–dez = 5/12;
# ano final: jan–jul = 7/12), somando exatamente (fim − ini) anos.
MES_REFERENCIA_CENSO = int(os.environ.get("DEMOG_MES_CENSO", 8))  # agosto
FRACIONAR_FRONTEIRA = os.environ.get("DEMOG_FRACIONAR", "1") not in ("0", "false", "False")


def peso_ano_intercenso(ano: int, ini: int, fim: int) -> float:
    """Peso (0..1) do ano-calendário `ano` dentro do intervalo censitário
    [ini, fim], considerando a data de referência dos censos (mês
    MES_REFERENCIA_CENSO). Fora do intervalo → 0. Soma dos pesos = fim − ini."""
    m = MES_REFERENCIA_CENSO
    if ano < ini or ano > fim:
        return 0.0
    if ano == ini:
        return (13 - m) / 12.0  # de 1º/ago a 31/dez = 5/12 (m=8)
    if ano == fim:
        return (m - 1) / 12.0   # de 1º/jan a 1º/ago = 7/12 (m=8)
    return 1.0

# ---------------------------------------------------------------------------
# Sinalização de pequenas áreas (NÃO remove nada; apenas marca)
# ---------------------------------------------------------------------------
# Em municípios pequenos o saldo migratório pode ser da ordem do ruído (erro
# censitário + sub-registro). Marcamos, mas mantemos todos os valores.
LIMIAR_PEQUENA_AREA = int(os.environ.get("DEMOG_LIMIAR_PEQUENO", 5000))

# ---------------------------------------------------------------------------
# Correção de sub-registro de nascimentos/óbitos (SINASC/SIM)
# ---------------------------------------------------------------------------
# O resíduo herda o sub-registro dos eventos vitais. Corrigimos dividindo a
# contagem pela COBERTURA estimada (fator = 1/cobertura ≥ 1). As coberturas
# abaixo são APROXIMADAS, por Grande Região, baseadas na literatura (Scielo/
# RIPSA/IBGE): Sul e Sudeste têm cobertura alta e estável; Norte e Nordeste,
# menor (sobretudo no início da série). SUBSTITUA pelos fatores oficiais do
# IBGE por UF/ano (Estimativas de Sub-Registro) para rigor — ou forneça um CSV
# `fatores_subregistro.csv` (colunas: sigla_uf, fator_nascimentos, fator_obitos).
APLICAR_SUBREGISTRO = os.environ.get("DEMOG_SUBREGISTRO", "1") not in ("0", "false", "False")

# Grande Região de cada UF
UF_REGIAO = {
    "RO": "Norte", "AC": "Norte", "AM": "Norte", "RR": "Norte", "PA": "Norte",
    "AP": "Norte", "TO": "Norte",
    "MA": "Nordeste", "PI": "Nordeste", "CE": "Nordeste", "RN": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "AL": "Nordeste", "SE": "Nordeste",
    "BA": "Nordeste",
    "MG": "Sudeste", "ES": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "SC": "Sul", "RS": "Sul",
    "MS": "Centro-Oeste", "MT": "Centro-Oeste", "GO": "Centro-Oeste",
    "DF": "Centro-Oeste",
}

# Cobertura APROXIMADA por região {nascimentos, obitos}. Valores conservadores.
COBERTURA_REGIAO = {
    "Sul":          {"nascimentos": 0.99, "obitos": 0.98},
    "Sudeste":      {"nascimentos": 0.99, "obitos": 0.98},
    "Centro-Oeste": {"nascimentos": 0.98, "obitos": 0.96},
    "Nordeste":     {"nascimentos": 0.95, "obitos": 0.90},
    "Norte":        {"nascimentos": 0.93, "obitos": 0.88},
}


def fatores_subregistro(sigla_uf: str) -> dict:
    """Fatores de correção {nascimentos, obitos} (=1/cobertura) para a UF.

    Precedência: CSV `fatores_subregistro.csv` (se existir, por UF) sobre os
    defaults regionais aproximados. Retorna {'nascimentos':1.0,'obitos':1.0} se
    a correção estiver desligada.
    """
    if not APLICAR_SUBREGISTRO:
        return {"nascimentos": 1.0, "obitos": 1.0, "fonte": "desligado"}

    # CSV opcional do usuário (valores oficiais do IBGE, por UF)
    csv = BASE_DIR / "fatores_subregistro.csv"
    if csv.exists():
        import csv as _csv
        with csv.open(encoding="utf-8-sig") as fh:
            for row in _csv.DictReader(fh):
                if row.get("sigla_uf", "").upper() == sigla_uf.upper():
                    return {
                        "nascimentos": float(row["fator_nascimentos"]),
                        "obitos": float(row["fator_obitos"]),
                        "fonte": "csv",
                    }

    regiao = UF_REGIAO.get(sigla_uf.upper(), "Sul")
    cob = COBERTURA_REGIAO[regiao]
    return {
        "nascimentos": round(1.0 / cob["nascimentos"], 4),
        "obitos": round(1.0 / cob["obitos"], 4),
        "fonte": f"aproximado ({regiao})",
    }

# Código IBGE de 2 dígitos por UF (prefixo do id_municipio de 7 dígitos).
UF_COD = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15",
    "AP": "16", "TO": "17", "MA": "21", "PI": "22", "CE": "23",
    "RN": "24", "PB": "25", "PE": "26", "AL": "27", "SE": "28",
    "BA": "29", "MG": "31", "ES": "32", "RJ": "33", "SP": "35",
    "PR": "41", "SC": "42", "RS": "43", "MS": "50", "MT": "51",
    "GO": "52", "DF": "53",
}


def prefixo_uf(sigla_uf: str) -> str:
    """Prefixo (2 díg.) do id_municipio para a UF; ValueError se desconhecida."""
    try:
        return UF_COD[sigla_uf.upper()]
    except KeyError as exc:
        raise ValueError(f"UF desconhecida: {sigla_uf}") from exc


# mapa inverso: prefixo (2 díg.) -> sigla da UF
_COD_UF = {v: k for k, v in UF_COD.items()}


def uf_por_id(id_municipio: str) -> str:
    """Sigla da UF a partir do id_municipio de 7 dígitos (pelos 2 primeiros)."""
    prefixo = str(id_municipio)[:2]
    try:
        return _COD_UF[prefixo]
    except KeyError as exc:
        raise ValueError(f"Prefixo de UF desconhecido em {id_municipio}") from exc

# ---------------------------------------------------------------------------
# billing_project_id
# ---------------------------------------------------------------------------
def get_billing_project_id() -> str | None:
    """Descobre o billing_project_id conforme a ordem documentada acima."""
    for var in ("BILLING_PROJECT_ID", "GOOGLE_CLOUD_PROJECT"):
        val = os.environ.get(var)
        if val:
            return val.strip()

    arquivo = BASE_DIR / ".billing_project"
    if arquivo.exists():
        conteudo = arquivo.read_text(encoding="utf-8").strip()
        if conteudo:
            return conteudo
    return None
