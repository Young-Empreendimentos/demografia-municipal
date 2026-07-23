"""
Resolução de municípios: nome (com acento/maiúsculas normalizados) ou código
IBGE de 7 dígitos -> id_municipio + metadados.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from unidecode import unidecode

import config
import data_sources


@dataclass
class Municipio:
    id_municipio: str
    nome: str
    sigla_uf: str

    def __str__(self) -> str:
        return f"{self.nome}/{self.sigla_uf} ({self.id_municipio})"


def _normalizar(texto: str) -> str:
    """Remove acentos, espaços extras e caixa para comparação robusta."""
    return unidecode(str(texto)).strip().lower()


def resolver(
    consulta: str | int, sigla_uf: str | None = None
) -> Municipio:
    """Resolve um município por código IBGE (7 díg.) ou por nome.

    - Se `consulta` tiver 7 dígitos numéricos, é tratada como id_municipio.
    - Caso contrário, é tratada como nome (match exato normalizado; se houver
      mais de um no Brasil, use `sigla_uf` para desambiguar).

    Levanta ValueError com sugestões quando não há match único.
    """
    # O diretório de nomes pode não estar disponível (sem BigQuery e sem o CSV
    # de diretório importado). Nesse caso ainda resolvemos por CÓDIGO IBGE.
    try:
        diretorio = data_sources.carregar_diretorio_municipios()
    except Exception:
        diretorio = None
    consulta_str = str(consulta).strip()

    # --- Caminho 1: código IBGE ------------------------------------------
    if consulta_str.isdigit() and len(consulta_str) == 7:
        if diretorio is not None:
            linha = diretorio[diretorio["id_municipio"] == consulta_str]
            if not linha.empty:
                r = linha.iloc[0]
                return Municipio(r["id_municipio"], r["nome"], r["sigla_uf"])
        # fallback: sem diretório, derivamos a UF pelo prefixo do código
        return Municipio(
            consulta_str, f"Município {consulta_str}", config.uf_por_id(consulta_str)
        )

    # --- Caminho 2: nome (requer diretório) ------------------------------
    if diretorio is None:
        raise ValueError(
            "Busca por nome requer o diretório de municípios. Importe o CSV do "
            "diretório (--diretorio no importar_csv.py) ou rode --baixar-brasil; "
            "ou use o código IBGE de 7 dígitos."
        )
    alvo = _normalizar(consulta_str)
    diretorio = diretorio.assign(_norm=diretorio["nome"].map(_normalizar))
    candidatos = diretorio[diretorio["_norm"] == alvo]

    if sigla_uf:
        candidatos = candidatos[candidatos["sigla_uf"] == sigla_uf.upper()]

    if len(candidatos) == 1:
        r = candidatos.iloc[0]
        return Municipio(r["id_municipio"], r["nome"], r["sigla_uf"])

    if candidatos.empty:
        # busca aproximada por substring para dar sugestões úteis
        parecidos = diretorio[diretorio["_norm"].str.contains(alvo, na=False)]
        sugestoes = ", ".join(
            f"{r.nome}/{r.sigla_uf}" for r in parecidos.head(8).itertuples()
        )
        extra = f" Você quis dizer: {sugestoes}?" if sugestoes else ""
        raise ValueError(f"Município não encontrado: '{consulta}'.{extra}")

    # múltiplos estados com o mesmo nome
    ufs = ", ".join(sorted(candidatos["sigla_uf"].unique()))
    raise ValueError(
        f"'{consulta}' existe em mais de uma UF ({ufs}). "
        f"Especifique a UF (ex.: --uf RS) ou use o código IBGE de 7 dígitos."
    )


def listar_por_uf(sigla_uf: str) -> pd.DataFrame:
    """Lista municípios de uma UF (para dropdown/autocomplete), ordenados por nome."""
    diretorio = data_sources.carregar_diretorio_municipios()
    df = diretorio[diretorio["sigla_uf"] == sigla_uf.upper()].copy()
    return df.sort_values("nome").reset_index(drop=True)
