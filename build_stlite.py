"""
Gera uma versão 100% estática do app (stlite) que roda no NAVEGADOR, sem
servidor/VM. Produz a pasta `docs/` com:
  • index.html  — carrega o stlite (via CDN) e monta o app;
  • cache/*.csv — o cache nacional convertido para CSV (sem pyarrow no navegador);
  • .nojekyll   — evita o processamento Jekyll no GitHub Pages.

A pasta se chama `docs/` porque o GitHub Pages serve nativamente de `/docs`
(além da raiz). Também funciona em qualquer host estático (intranet, SharePoint,
bucket S3) — é só copiar a pasta.

Rodar:  python build_stlite.py
Testar: python -m http.server 8080 --directory docs   → http://localhost:8080
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

import config

BASE = config.BASE_DIR
WEB = BASE / "docs"          # GitHub Pages serve nativamente de /docs
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

# ---------------------------------------------------------------------------
# Autenticação (Supabase + Google) — porta de entrada do site.
# Estes blocos são injetados no index.html como texto literal (por isso ficam
# fora da f-string do template: assim não é preciso escapar as chaves { }).
# ATENÇÃO: se mexer no login, mantenha igual ao que está em docs/index.html.
# ---------------------------------------------------------------------------
STYLE_CSS = """
    :root { --indigo:#4f46e5; --indigo-esc:#4338ca; --tinta:#1e293b; --cinza:#64748b; }
    #loading { font-family: sans-serif; padding: 2rem; color: #444; }
    .auth-wrap { min-height:100vh; display:flex; align-items:center; justify-content:center;
      font-family: system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
      background:linear-gradient(160deg,#eef2ff 0%,#f8fafc 55%); padding:1.5rem; box-sizing:border-box; }
    .auth-card { background:#fff; border:1px solid #e2e8f0; border-radius:16px;
      box-shadow:0 10px 30px rgba(30,41,59,.08); padding:2.5rem 2.25rem; max-width:410px; width:100%;
      text-align:center; box-sizing:border-box; }
    .auth-card h1 { font-size:1.35rem; color:var(--tinta); margin:0 0 .4rem; }
    .auth-card p { color:var(--cinza); font-size:.95rem; line-height:1.55; margin:0 0 1.5rem; }
    .auth-emoji { font-size:2.6rem; margin-bottom:.6rem; }
    .btn-google { display:inline-flex; align-items:center; gap:.7rem; justify-content:center;
      width:100%; padding:.8rem 1rem; border:1px solid #e2e8f0; border-radius:10px; background:#fff;
      color:var(--tinta); font-size:1rem; font-weight:600; cursor:pointer; transition:.15s;
      box-sizing:border-box; }
    .btn-google:hover { border-color:var(--indigo); box-shadow:0 2px 10px rgba(79,70,229,.18); }
    .btn-google svg { width:20px; height:20px; flex:0 0 auto; }
    .auth-erro { color:#b91c1c; font-size:.9rem; margin-top:1rem; }
    .auth-nota { color:#94a3b8; font-size:.78rem; margin-top:1.5rem; }
    .btn-sec { margin-top:1.2rem; background:none; border:none; color:var(--indigo); cursor:pointer;
      font-size:.9rem; text-decoration:underline; }
    #topbar { display:none; align-items:center; justify-content:flex-end; gap:.75rem;
      font-family:system-ui,sans-serif; font-size:.85rem; color:var(--cinza);
      padding:.5rem 1rem; background:#f8fafc; border-bottom:1px solid #e2e8f0; }
    #topbar .email { font-weight:600; color:var(--tinta); }
    #topbar button { padding:.35rem .8rem; border:1px solid #e2e8f0; border-radius:8px;
      background:#fff; color:var(--tinta); cursor:pointer; font-size:.8rem; }
    #topbar button:hover { border-color:var(--indigo); color:var(--indigo); }
    .spin { width:34px; height:34px; border:3px solid #e2e8f0; border-top-color:var(--indigo);
      border-radius:50%; animation:girar .8s linear infinite; margin:0 auto 1.1rem; }
    @keyframes girar { to { transform:rotate(360deg); } }
"""

# Config do Supabase (chave publicável — segura de expor no cliente; o acesso é
# controlado por RLS/políticas no Supabase). Domínio de e-mail liberado:
SUPABASE_URL = "https://vvtympzatclvjaqucebr.supabase.co"
SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ2dHltcHphdGNsdmphcXVjZWJyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzA0NTI1NzYsImV4cCI6MjA4NjAyODU3Nn0.C8vWcljx6veAQ0hCi0ms7Ixm6NxhSdWBDeRgUy2Kz50"
DOMINIO_PERMITIDO = "youngempreendimentos.com.br"

# Bloco JS do "porteiro": tudo desde o import do supabase-js até abrir o mount().
GATE_ANTES = f"""    import {{ createClient }} from
      "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";

    // Autenticação (Supabase + Google). Acesso restrito ao domínio da Young.
    const SUPABASE_URL = "{SUPABASE_URL}";
    const SUPABASE_ANON = "{SUPABASE_ANON}";
    const DOMINIO_PERMITIDO = "{DOMINIO_PERMITIDO}";
    const supabase = createClient(SUPABASE_URL, SUPABASE_ANON);

    const root = document.getElementById("root");
    const topbar = document.createElement("div");
    topbar.id = "topbar";
    document.body.insertBefore(topbar, root);

    const googleSvg =
      '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">' +
      '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>' +
      '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>' +
      '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.28-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>' +
      '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>';

    function telaLogin(erro) {{
      topbar.style.display = "none";
      root.innerHTML =
        '<div class="auth-wrap"><div class="auth-card">' +
        '<div class="auth-emoji">📊</div>' +
        '<h1>Demografia Municipal</h1>' +
        '<p>Ferramenta interna da Young. Entre com sua conta Google ' +
        '<b>@' + DOMINIO_PERMITIDO + '</b> para acessar.</p>' +
        '<button class="btn-google" id="btn-login">' + googleSvg + ' Entrar com Google</button>' +
        (erro ? '<div class="auth-erro">' + erro + '</div>' : '') +
        '<div class="auth-nota">Acesso restrito a e-mails @' + DOMINIO_PERMITIDO + '</div>' +
        '</div></div>';
      document.getElementById("btn-login").onclick = entrar;
    }}

    function telaNegado(email) {{
      topbar.style.display = "none";
      root.innerHTML =
        '<div class="auth-wrap"><div class="auth-card">' +
        '<div class="auth-emoji">🚫</div>' +
        '<h1>Acesso restrito</h1>' +
        '<p>A conta <b>' + email + '</b> não pertence ao domínio ' +
        '<b>@' + DOMINIO_PERMITIDO + '</b>, então não tem acesso a este sistema.</p>' +
        '<button class="btn-sec" id="btn-trocar">Entrar com outra conta</button>' +
        '</div></div>';
      document.getElementById("btn-trocar").onclick = async function () {{
        await supabase.auth.signOut();
        telaLogin();
      }};
    }}

    function telaCarregando(msg) {{
      root.innerHTML =
        '<div class="auth-wrap"><div class="auth-card">' +
        '<div class="spin"></div><p>' + msg + '</p></div></div>';
    }}

    async function entrar() {{
      telaCarregando("Redirecionando para o Google…");
      const {{ error }} = await supabase.auth.signInWithOAuth({{
        provider: "google",
        options: {{
          redirectTo: window.location.origin + window.location.pathname,
          queryParams: {{ hd: DOMINIO_PERMITIDO, prompt: "select_account" }},
        }},
      }});
      if (error) telaLogin("Não foi possível iniciar o login: " + error.message);
    }}

    function mostrarBarra(email) {{
      topbar.innerHTML =
        '<span>Conectado como <span class="email">' + email + '</span></span>' +
        '<button id="btn-sair">Sair</button>';
      topbar.style.display = "flex";
      document.getElementById("btn-sair").onclick = async function () {{
        await supabase.auth.signOut();
        window.location.reload();
      }};
    }}

    let appIniciado = false;
    function decidir(session) {{
      if (!session) {{ telaLogin(); return; }}
      const email = (session.user.email || "").toLowerCase();
      const dominio = email.split("@")[1] || "";
      if (dominio !== DOMINIO_PERMITIDO) {{
        if (!appIniciado) telaNegado(email);
        return;
      }}
      if (appIniciado) return;
      appIniciado = true;
      history.replaceState({{}}, document.title, window.location.pathname);
      mostrarBarra(email);
      telaCarregando("Carregando o app (a primeira vez baixa o Python no navegador — pode levar ~10–20 s)…");
      startApp();
    }}

    supabase.auth.onAuthStateChange(function (evento, session) {{
      if (evento === "SIGNED_OUT") {{
        appIniciado = false;
        telaLogin();
        return;
      }}
      decidir(session);
    }});

    // Avaliação inicial. No retorno do Google (URL com ?code=) deixamos o
    // onAuthStateChange (SIGNED_IN) resolver, para não piscar a tela de login.
    if (!/[?&#](code|access_token|error)=/.test(window.location.href)) {{
      supabase.auth.getSession().then(function (r) {{ decidir(r.data.session); }});
    }}

    function startApp() {{
      mount("""

GATE_DEPOIS = "    }"


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
  <style>{STYLE_CSS}  </style>
</head>
<body>
  <div id="root">
    <div id="loading">Carregando…</div>
  </div>
  <script type="module">
    import {{ mount }} from
      "https://cdn.jsdelivr.net/npm/@stlite/browser@{STLITE_VER}/build/stlite.js";
{GATE_ANTES}
      {{
        entrypoint: "app.py",
        requirements: [{reqs_js}],
        files: {{
{files_js}
        }},
      }},
      root,
    );
{GATE_DEPOIS}
  </script>
</body>
</html>
"""
    (WEB / "index.html").write_text(html, encoding="utf-8")
    (WEB / ".nojekyll").write_text("", encoding="utf-8")  # Pages: sem Jekyll
    tam = (WEB / "index.html").stat().st_size / 1024
    print(f"Gerado: {WEB / 'index.html'} ({tam:.0f} KB)")
    print(f"Dados CSV em: {WEB_CACHE} ({len(csv_nomes)} arquivos)")
    print("Teste local:  python -m http.server 8080 --directory docs")
    print("Depois abra:  http://localhost:8080")


if __name__ == "__main__":
    main()
