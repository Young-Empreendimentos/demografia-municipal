"""
Gera uma versão 100% estática do app (stlite) que roda no NAVEGADOR, sem
servidor/VM. Produz a pasta `web/` com:
  • index.html  — carrega o stlite (via CDN) e monta o app;
  • cache/*.csv — o cache nacional convertido para CSV (sem pyarrow no navegador).

Basta hospedar a pasta `web/` em qualquer servidor de arquivos estáticos
(intranet, SharePoint, GitHub Pages, bucket S3) ou abrir via um servidor local.

Rodar:  python build_stlite.py
Testar: python -m http.server 8080 --directory web   → http://localhost:8080
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

import config

BASE = config.BASE_DIR
WEB = BASE / "web"
WEB_CACHE = WEB / "cache"

# Módulos Python embutidos no HTML (ordem não importa; o entrypoint é app.py).
MODULOS = [
    "config.py", "data_sources.py", "municipios.py",
    "calculations.py", "reporting.py", "app.py",
]
# Documentos de texto também embutidos (lidos pelo app).
DOCS = ["METODOLOGIA.md"]

STLITE_VER = "0.85.1"
REQUIREMENTS = ["pandas", "matplotlib", "unidecode"]


def _esc_js_template(texto: str) -> str:
    """Escapa uma string para dentro de um template literal JS (crases)."""
    return (
        texto.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("${", "\\${")
    )


def _converter_cache_para_csv() -> list[str]:
    """Converte cada parquet do cache em CSV dentro de web/cache/ (mesmo nome).
    Retorna a lista de nomes de arquivo CSV gerados."""
    WEB_CACHE.mkdir(parents=True, exist_ok=True)
    nomes = []
    for pq in sorted(config.CACHE_DIR.glob("*.parquet")):
        df = pd.read_parquet(pq)
        destino = WEB_CACHE / (pq.stem + ".csv")
        df.to_csv(destino, index=False, encoding="utf-8")
        nomes.append(destino.name)
    if not nomes:
        raise SystemExit(
            "Nenhum parquet em cache/. Rode --baixar-brasil ou importar_csv.py "
            "antes de gerar o site."
        )
    return nomes


def _bloco_files(csv_nomes: list[str]) -> str:
    """Monta o objeto JS `files` com módulos/docs inline e CSVs por URL."""
    linhas = []
    for nome in MODULOS + DOCS:
        conteudo = (BASE / nome).read_text(encoding="utf-8")
        linhas.append(f'    "{nome}": `{_esc_js_template(conteudo)}`,')
    # dados como arquivos carregados por URL relativa (ficam em web/cache/)
    for nome in csv_nomes:
        linhas.append(f'    "cache/{nome}": {{ url: "./cache/{nome}" }},')
    return "\n".join(linhas)


def main() -> None:
    if WEB.exists():
        shutil.rmtree(WEB)
    WEB.mkdir(parents=True)
    csv_nomes = _converter_cache_para_csv()
    files_js = _bloco_files(csv_nomes)
    reqs_js = ", ".join(f'"{r}"' for r in REQUIREMENTS)

    html = f"""<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Demografia Municipal — Brasil/RS</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/@stlite/browser@{STLITE_VER}/build/stlite.css" />
  <style>
    #loading {{ font-family: sans-serif; padding: 2rem; color: #444; }}
  </style>
</head>
<body>
  <div id="root">
    <div id="loading">Carregando o app (primeira vez baixa o Python no
      navegador — pode levar ~10–20 s)…</div>
  </div>
  <script type="module">
    import {{ mount }} from
      "https://cdn.jsdelivr.net/npm/@stlite/browser@{STLITE_VER}/build/stlite.js";
    mount(
      {{
        entrypoint: "app.py",
        requirements: [{reqs_js}],
        files: {{
{files_js}
        }},
      }},
      document.getElementById("root"),
    );
  </script>
</body>
</html>
"""
    (WEB / "index.html").write_text(html, encoding="utf-8")
    tam = (WEB / "index.html").stat().st_size / 1024
    print(f"Gerado: {WEB / 'index.html'} ({tam:.0f} KB)")
    print(f"Dados CSV em: {WEB_CACHE} ({len(csv_nomes)} arquivos)")
    print("Teste local:  python -m http.server 8080 --directory web")
    print("Depois abra:  http://localhost:8080")


if __name__ == "__main__":
    main()
