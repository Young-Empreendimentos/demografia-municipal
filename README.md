# Demografia Municipal (Brasil / foco RS)

Selecione um município (por nome ou código IBGE) e obtenha as séries históricas de
**população, nascimentos, óbitos, crescimento vegetativo e saldo migratório**, com
gráficos, tabela, resumo e citação das fontes. Funciona para qualquer município do
Brasil; o foco inicial é o Rio Grande do Sul.

## Fontes de dados

Via **[Base dos Dados](https://basedosdados.org) (BigQuery)**:

| Série        | Tabela                                        | Método |
|--------------|-----------------------------------------------|--------|
| Nascimentos  | `basedosdados.br_ms_sinasc.microdados`        | SINASC/MS, contagem por município de residência |
| Óbitos       | `basedosdados.br_ms_sim.microdados`           | SIM/MS, contagem por município de residência |
| População    | `basedosdados.br_ibge_populacao.municipio`    | IBGE (estimativas + censos) |
| Nomes/códigos| `basedosdados.br_bd_diretorios_brasil.municipio` | IBGE |

As consultas ficam em **cache local (parquet)** na pasta `cache/`. A segunda
execução para a mesma UF **não reconsulta o BigQuery** (controle de custo). Use
`--force` para limpar o cache e reconsultar.

## 1. Instalação

```bash
pip install -r requirements.txt
```

Dependências principais: `basedosdados`, `pandas`, `matplotlib`, `pyarrow`,
`unidecode`, `streamlit`, `openpyxl`.

## 2. Configurar o `billing_project_id` (Google Cloud)

O pacote `basedosdados` cobra as consulta no **seu** projeto do Google Cloud
(existe uma cota gratuita mensal generosa do BigQuery).

1. Crie/escolha um projeto em <https://console.cloud.google.com> e ative a
   **BigQuery API**. Anote o *Project ID*.
2. Autentique-se localmente (uma vez):

   ```bash
   pip install google-cloud-bigquery
   gcloud auth application-default login
   ```

   (Alternativa: aponte `GOOGLE_APPLICATION_CREDENTIALS` para um JSON de
   *service account*.)
3. Informe o Project ID ao app por **uma** destas vias (a primeira que existir vence):
   - variável de ambiente `BILLING_PROJECT_ID`
   - variável de ambiente `GOOGLE_CLOUD_PROJECT`
   - arquivo `.billing_project` (uma linha com o id) na pasta do projeto:

     ```bash
     echo meu-projeto-gcp-123 > .billing_project
     ```

## 3. Executar

### Baixar o Brasil inteiro de uma vez (recomendado)

```bash
python demografia.py --baixar-brasil
```

Faz **duas** varreduras grandes (SINASC e SIM) + população/diretório (baratos) e
grava o **cache nacional** (`cache/*-BR.parquet`). Como as tabelas são
particionadas por `ano`, baixar o país todo custa ~o mesmo que uma única UF, e o
resultado tem só ~130 mil linhas por tabela (poucos MB). Depois disso, **qualquer
município ou UF é servido do cache local, sem novas consultas ao BigQuery**. Os
"descartados" (id de residência nulo) já saem dessa mesma leitura, sem custo extra.

### CLI

```bash
python demografia.py --municipio "Bagé"
python demografia.py --municipio "Porto Alegre" --uf RS
python demografia.py --id 4301602
python demografia.py --uf RS --agregado          # série do estado todo (validação)
python demografia.py --municipio "Bagé" --formato xlsx --sem-graficos
python demografia.py --municipio "Bagé" --force  # ignora cache e reconsulta
```

Saídas (em `output/`): tabela no terminal, 3 gráficos em PNG
(população; nascimentos × óbitos com área do vegetativo; saldo migratório anual),
resumo, seção de fontes/ressalvas e arquivos `*_serie.csv`, `*_intercensos.csv`,
`*.xlsx`.

### Uniformizar rebaseamentos do IBGE (opcional)

As estimativas anuais do IBGE são periodicamente **rebaseadas** (Contagem 2007,
cada censo), criando saltos artificiais na série. Como o saldo migratório é um
resíduo, esses saltos viram picos falsos de migração. O modo `--suavizar`
reconstrói a população a partir das **âncoras censitárias** pela equação de
balanço demográfico e distribui o saldo migratório suavemente:

```bash
python demografia.py --municipio "Bagé" --suavizar            # uniforme (default)
python demografia.py --municipio "Bagé" --suavizar proporcional
```

- **uniforme** — mesmo nº de migrantes por ano dentro de cada intervalo.
- **proporcional** — proporcional à população (taxa de migração ~constante).

A série reconstruída passa **exatamente** pelos censos e não tem os saltos. O
saldo migratório *acumulado* é conservado (a suavização só redistribui dentro de
cada intervalo). O modo bruto continua o padrão — é mais honesto expor os
artefatos por default.

### Ranking municipal dentro da UF

```bash
python demografia.py --uf RS --ranking                  # 2010–2022 (default)
python demografia.py --uf RS --ranking --intervalo 2000-2010
```

Lista todos os municípios da UF pelo saldo migratório (método do resíduo com as
pontas em anos de censo — população robusta, sem rebaseamento). Mostra os 15
maiores e 15 menores e exporta o ranking completo em CSV. No **app** (modo
"Ranking do estado") a tabela é ordenável por clique em qualquer coluna, com
escolha entre **saldo total** e **% da população** e do intervalo censitário.

### App Streamlit

```bash
python -m streamlit run app.py --server.port 8501
```

Ou dê dois cliques em **`Abrir App Demografia.bat`**. Acesse
**http://localhost:8501**. Barra lateral com dois modos:
- **Município / Estado** — série histórica, gráficos, cálculos, uniformização
  opcional, e o saldo migratório **em % da população** (coluna `saldo_pct` e
  métrica de % acumulado).
- **Ranking do estado** — todos os municípios ordenados por saldo total ou %,
  ordenação por clique, download CSV.

## 4. Cálculos

- **Crescimento vegetativo(t)** = nascimentos(t) − óbitos(t).
- **Saldo migratório (método do resíduo)** — saldo LÍQUIDO (não separa entrada/saída):
  - *Série anual (aproximação):* `Saldo(t) ≈ (Pop(t+1) − Pop(t)) − vegetativo(t)`.
  - *Intercensitário (robusto):* `Saldo = (Pop_censo_final − Pop_censo_inicial) − Σ vegetativo`,
    para 2000–2010 e 2010–2022 (vegetativo somado nos anos `[inicial, final-1]`).
- **Saldo %** = saldo ÷ população inicial.

## 5. Ressalvas (também exibidas na saída)

- Eventos por **residência**; residentes que tiveram o evento em outra UF podem faltar.
- Registros **sem município de residência** (id nulo) são excluídos dos totais
  municipais — o volume descartado é reportado.
- Ao agregar "todos do RS", filtramos `id_municipio` iniciado em **43** (o filtro
  `sigla_uf` das tabelas de eventos é por UF de **ocorrência** e incluiria municípios
  de outras UFs).
- **Fronteira temporal:** eventos por ano-calendário vs. janela censitária
  (referência de julho) geram leve descasamento — use para tendência/ranking, não
  como número exato.
- População: cada ano é marcado como **censo** (2000/2010/2022) ou **estimativa**.

## 6. Critérios de aceite

- Roda para "Bagé" e "Porto Alegre" produzindo tabela + 3 gráficos + fontes.
- Agregado RS 2010–2022 esperado (soma dos 497 municípios): Δpop ≈ +186 mil,
  vegetativo ≈ +625 mil, saldo migratório ≈ −438 mil
  (`python demografia.py --uf RS --agregado`).
- Cache funcionando (2ª execução sem reconsultar o BigQuery).

## 6b. Avaliação metodológica (resumo)

Revisão contra fontes oficiais (IBGE, DATASUS, IUSSP/ONU) e literatura demográfica
(Cedeplar/UFMG, REBEP, DEE-RS):

- **Adequado** para saldo migratório líquido do RS em nível estadual, de agregados
  e de municípios médios/grandes. É o *método do resíduo* clássico, aplicado com as
  escolhas corretas (âncora nos censos, contagem por residência, UF de cobertura
  vital alta e estável — Sul >98–99%).
- **Ressalvas**: (1) o resíduo é líquido e "contaminado" por erros de censo e
  sub-registro — não é migração pura; (2) municípios pequenos: saldo da ordem do
  ruído (mantidos, mas interprete com cautela); (3) fronteira temporal: somamos
  anos-calendário inteiros, o que superestima ~1 ano de vegetativo (censo tem
  referência em agosto) — por isso os números servem para tendência/ranking, não
  como valor exato; (4) esconde fluxos brutos.
- **Validação**: não há número oficial de resíduo *municipal* publicado. O dado do
  DEE-RS (−77,8 mil, −0,72%, 2017–2022) é por quesito *data-fixa* (bruto, 5 anos) e
  **não** é diretamente comparável. Triangule sinal/ordem de grandeza com o quesito
  data-fixa do Censo 2022 e a Razão de Sobrevivência Censitária (CSMR).

A seção "Fontes e ressalvas" impressa pela CLI/app traz esses pontos e a referência.

**Correções implementadas (ativas por padrão, configuráveis em `config.py`):**
- **Fronteira temporal** — fraciona os anos de ponta (censos com referência em
  ~1º/ago), somando exatamente `fim − ini` anos. Desligar: `DEMOG_FRACIONAR=0`.
  Efeito no RS 2010–2022: saldo passa de ~−439 mil para ~−395 mil.
- **Sub-registro** — corrige nascimentos/óbitos por `1/cobertura` (coberturas
  regionais aproximadas; RS ≈ ×1,01/×1,02). Substitua pelos valores oficiais via
  `fatores_subregistro.csv` (`sigla_uf, fator_nascimentos, fator_obitos`).
  Desligar: `DEMOG_SUBREGISTRO=0`.
- **Pequenas áreas** — municípios com pop. < `DEMOG_LIMIAR_PEQUENO` (5.000) são
  **sinalizados** (⚠), nunca removidos.

**Documentação completa:** [`METODOLOGIA.md`](METODOLOGIA.md) — também disponível
no app (modo "Metodologia").

## 7. Alternativa sem BigQuery (opcional)

`datasus_source.py` traz nascimentos/óbitos via **DATASUS** (`pip install pysus`),
mantendo a mesma interface. População via SIDRA/IBGE fica como ponto de extensão.
Para usar:

```python
import datasus_source as data_sources
import calculations
calculations.data_sources = data_sources
```

## 8. Teste offline

`python test_offline.py` semeia o cache com dados sintéticos e valida toda a lógica
de cálculo (vegetativo, saldos anual e intercensitário, filtro do agregado,
exportação e gráficos) **sem** tocar no BigQuery.

## Estrutura

```
config.py          # billing_project_id, janela temporal, diretórios
data_sources.py    # consultas BigQuery + cache parquet
municipios.py      # resolução nome/código IBGE (normaliza acentos)
calculations.py    # vegetativo, saldos, resumo, agregado de UF
reporting.py       # gráficos, texto de fontes/ressalvas, export CSV/XLSX
demografia.py      # CLI
app.py             # Streamlit
datasus_source.py  # fonte alternativa (opcional)
test_offline.py    # teste da lógica sem BigQuery
```
