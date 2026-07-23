# Metodologia — Saldo migratório municipal pelo método do resíduo

Este documento descreve, de forma completa e detalhada, toda a metodologia usada
no app de demografia municipal: fontes, definições, o método do resíduo, as
variantes de cálculo, as correções aplicadas, as ressalvas e como validar os
resultados. Foi revisado contra fontes oficiais (IBGE, DATASUS, IUSSP/ONU) e a
literatura demográfica brasileira (Cedeplar/UFMG, REBEP, DEE‑RS).

---

## 1. Objetivo e escopo

Estimar, para cada município do Brasil (foco no Rio Grande do Sul), as séries
históricas de **população, nascimentos, óbitos, crescimento vegetativo e saldo
migratório líquido**, no período 2000–2022, e permitir comparações e rankings
dentro de uma UF.

O **saldo migratório líquido** é o objeto central e o mais delicado: não é
medido diretamente, e sim **estimado por resíduo** da equação de balanço
demográfico.

---

## 2. Fontes de dados

| Série | Tabela (Base dos Dados / BigQuery) | Órgão | Observação |
|---|---|---|---|
| População | `br_ibge_populacao.municipio` | IBGE | Censos (2000, 2010, 2022) + estimativas anuais |
| Nascimentos | `br_ms_sinasc.microdados` | Ministério da Saúde (SINASC) | Contagem por município de **residência** da mãe |
| Óbitos | `br_ms_sim.microdados` | Ministério da Saúde (SIM) | Contagem por município de **residência** |
| Nomes/códigos | `br_bd_diretorios_brasil.municipio` | IBGE | `id_municipio` (7 díg.), `nome`, `sigla_uf` |

Os dados são baixados uma vez (via BigQuery ou por importação dos CSVs
exportados do console) e ficam em **cache local (parquet)**. Nascimentos e
óbitos são agregados **por município de residência e ano**, descartando
registros sem município de residência (id nulo), cujo volume é reportado à
parte.

---

## 3. Definições

**Crescimento vegetativo (ou natural)** de um ano *t*:

```
vegetativo(t) = nascimentos(t) − óbitos(t)
```

**Equação de balanço demográfico** (identidade fundamental da demografia): a
variação da população entre dois instantes é igual ao crescimento natural mais
o saldo migratório líquido:

```
Pop(t+1) − Pop(t) = [nascimentos − óbitos] + [imigrantes − emigrantes]
                  = vegetativo(t)            + migração_líquida(t)
```

**Saldo migratório líquido** é, portanto, o **resíduo**:

```
migração_líquida = variação populacional − crescimento vegetativo
```

É **líquido**: mede entradas menos saídas, não os fluxos brutos. Dois
municípios com saldo zero podem ter rotatividade enorme ou nenhuma.

---

## 4. Método do resíduo — fundamentação

O método é clássico e canônico na demografia, conhecido como *residual method*
ou *vital statistics method*. Ele decorre diretamente da equação de balanço:
isolando a migração como resíduo entre a variação populacional observada (por
dois censos) e o crescimento natural medido pelas estatísticas vitais.

Pressuposto central (Demopædia/IUSSP): as **omissões e dupla‑contagens devem ser
semelhantes nos dois censos**. E uma consequência que precisa estar sempre
explícita:

> O resíduo captura a migração líquida **somada a todos os erros dos demais
> componentes** (erro de contagem censitária + sub‑registro de nascimentos e
> óbitos). Qualquer erro em população, nascimentos ou óbitos aparece como
> "migração". Por isso o resíduo é, em parte, uma "lata de lixo" de erros.

No Brasil, a tradição do Cedeplar/UFMG (José Alberto Magno de Carvalho, Rigotti)
usa o método indireto/residual há décadas, justamente porque fornece o **saldo
líquido do período intercensitário completo** sem exigir os quesitos migratórios
do censo.

---

## 5. Variantes de cálculo

### 5.1. Intercensitária (robusta) — recomendada

Usa como âncoras os **anos de censo** (população mais confiável):

```
saldo(ini→fim) = [Pop_censo(fim) − Pop_censo(ini)] − Σ vegetativo no período
```

Intervalos: 2000–2010 e 2010–2022. Como as pontas são censos, este cálculo **não
sofre** com os rebaseamentos das estimativas anuais.

### 5.2. Anual (aproximação)

Usa as estimativas anuais de população:

```
saldo(t) ≈ [Pop(t+1) − Pop(t)] − vegetativo(t)
```

Serve para visualizar a dinâmica ano a ano, mas herda o ruído e os **saltos de
rebaseamento** das estimativas (ver §7).

### 5.3. Saldo em %

```
saldo_pct = saldo ÷ população inicial × 100
```

Permite comparar municípios de portes diferentes (um saldo de −1.000 é enorme
numa cidade de 3.000 e desprezível numa de 1.000.000).

---

## 6. Reconstrução / uniformização de rebaseamentos

As estimativas anuais do IBGE usam o método matemático **AiBi** (Madeira &
Simões, 1972): projetam a população municipal pela razão entre a tendência de
crescimento do município (entre os dois últimos censos) e a da UF. Isso tem duas
consequências:

1. **Não incorpora migração recente por dado direto** — extrapola tendências.
2. **Rebaseamento pós‑censo cria saltos**: quando um novo censo chega, a série é
   re‑ancorada, gerando descontinuidades artificiais.

O modo **"uniformizar rebaseamentos"** reconstrói a população ano a ano a partir
dos censos, pela equação de balanço:

```
Pop_suave(t+1) = Pop_suave(t) + vegetativo(t) + migração_suave(t)
```

O saldo migratório **total** de cada intervalo é fixado pelas âncoras
censitárias e distribuído entre os anos de duas formas:

- **uniforme**: mesmo número de migrantes por ano;
- **proporcional**: proporcional à população (taxa de migração ~constante).

A série reconstruída passa **exatamente** pelos censos e não tem saltos.
**Importante**: a distribuição é uma **suposição de suavização**, não uma
medição anual — ela não capta choques migratórios concentrados em um único ano.

---

## 7. Ranking municipal

Para cada município da UF, calcula o saldo migratório do intervalo
intercensitário (default 2010–2022) pelo método do resíduo, com as pontas em
anos de censo. Ordenável por **saldo total** ou **% da população**. Todos os
municípios são mantidos (nenhum é removido); os pequenos são apenas
**sinalizados** (ver §8.3).

---

## 8. Correções aplicadas

As correções são controladas por parâmetros em `config.py` e podem ser
ligadas/desligadas. Por padrão, **todas estão ativas**.

### 8.1. Fronteira temporal

Os censos têm data de referência em **~1º de agosto** (2000, 2010 e 2022),
enquanto os eventos vitais são somados por ano‑calendário (jan–dez). Somar os
anos de ponta inteiros inclui meses fora do intervalo censo‑a‑censo e
**superestima o crescimento vegetativo** (empurra o saldo para mais negativo).

Correção: ponderamos os anos de ponta pela fração de meses dentro do intervalo.
Com referência em agosto (mês *M* = 8):

```
peso(ano inicial) = (13 − M)/12 = 5/12   (ago–dez)
peso(ano final)   = (M − 1)/12  = 7/12   (jan–jul)
peso(anos do meio) = 1
```

A soma dos pesos é exatamente `fim − ini` (ex.: 12 anos para 2010–2022, não 13).
O próprio IBGE fraciona os anos de ponta ao montar a equação de balanço.

**Efeito no RS 2010–2022**: o vegetativo cai de ~625 mil (anos inteiros) para
~581 mil, e o saldo migratório passa de ~−439 mil para ~−395 mil.

### 8.2. Sub‑registro de nascimentos e óbitos

O SINASC/SIM não captam 100% dos eventos, e a cobertura **varia por região e no
tempo**. Como o resíduo herda esse sub‑registro, corrigimos as contagens
dividindo pela cobertura estimada:

```
evento_corrigido = evento_observado ÷ cobertura = evento_observado × fator
                   (fator = 1/cobertura ≥ 1)
```

Coberturas **aproximadas** por Grande Região (padrão do app; **substitua pelos
fatores oficiais do IBGE por UF/ano** para rigor):

| Região | Cobertura nascimentos | Cobertura óbitos |
|---|---|---|
| Sul | 0,99 | 0,98 |
| Sudeste | 0,99 | 0,98 |
| Centro‑Oeste | 0,98 | 0,96 |
| Nordeste | 0,95 | 0,90 |
| Norte | 0,93 | 0,88 |

No **RS** (Sul), os fatores são pequenos: nascimentos ×1,0101 e óbitos ×1,0204 —
coerente com a cobertura alta e estável do Sul (>98–99% na literatura Scielo/
RIPSA). Fora do Sul/Sudeste, e no início da série, a correção é mais relevante.

**Override**: crie um arquivo `fatores_subregistro.csv` na pasta do projeto com
colunas `sigla_uf, fator_nascimentos, fator_obitos` (valores oficiais do IBGE) e
ele terá precedência sobre os defaults regionais.

### 8.3. Sinalização de pequenas áreas

Em municípios pequenos, o saldo migratório pode ser da **mesma ordem de grandeza
do ruído** (erro censitário + sub‑registro). Municípios com população inicial
abaixo do limiar (padrão **5.000**) são **sinalizados** (⚠), mas **nunca
removidos** — o número, ainda que ruidoso, é preservado.

---

## 9. Ressalvas e limitações

1. **Resíduo = migração + erros.** Não é migração pura; absorve erro censitário e
   sub‑registro residual.
2. **Só líquido, nunca bruto.** Não distingue quem entrou de quem saiu, nem
   origem/destino.
3. **Pequenas áreas.** Saldo individual pouco confiável; use com cautela e/ou
   agregue (microrregiões, COREDEs).
4. **Residência × ocorrência.** Contamos por residência (correto para o
   balanço), mas há pequeno vazamento de residentes com evento em outra UF, e
   erro de preenchimento da variável de residência.
5. **Universo da UF.** No agregado "todos do RS" filtramos `id_municipio`
   iniciado em 43; o filtro por `sigla_uf` das tabelas de eventos é por UF de
   **ocorrência** e incluiria municípios de outras UFs.
6. **Reconstrução é suavização**, não medição anual.
7. **Estimativas anuais (AiBi)** não devem ser usadas para migração — por isso
   ancoramos nos censos.

---

## 10. Validação e triangulação

**Não existe** número oficial publicado de saldo migratório **municipal** pelo
resíduo 2010–2022 para colar como *ground truth*. Estratégias de validação:

- **Agregado estadual coerente**: a soma dos municípios do RS 2010–2022 deve
  reproduzir o saldo estadual pela mesma equação de balanço IBGE (censo→censo −
  vegetativo). É a validação conceitualmente idêntica.
- **DEE‑RS (Cadernos RS no Censo 2022, nov/2025)**: reporta, pelo quesito
  **data‑fixa 2017–2022**, saldo líquido de **−77,8 mil** e taxa de **−0,72%**.
  ⚠ **Não é diretamente comparável**: é fluxo bruto, 5 anos, só sobreviventes que
  mudaram de município de referência — período e conceito diferentes do resíduo
  2010–2022. Use apenas como referência de **sinal e ordem de grandeza**.
- **Razão de Sobrevivência Censitária (CSMR)**: estima migração líquida por idade
  sem depender do SINASC/SIM (imune ao sub‑registro vital). Boa checagem cruzada.
- **Quesito data‑fixa do Censo 2022**: fluxos diretos por origem‑destino.

Regra prática: convergência de **sinal e ordem de grandeza** entre resíduo,
CSMR e quesito censitário é a melhor validação disponível.

---

## 11. Alternativas metodológicas

| Técnica | O que dá | Quando é preferível |
|---|---|---|
| **Resíduo / estatísticas vitais** (este app) | Saldo líquido do período intercensitário completo | Saldo coerente com o balanço; período não coincide com data‑fixa; boas estatísticas vitais (caso do RS) |
| **Quesito data‑fixa** (censo) | Fluxos brutos, origem‑destino, 5 anos | Precisa de volumes de im/emigrantes e origens |
| **Última etapa** (censo) | Movimento direto mais recente | Análise de fluxos, sem referência temporal fixa |
| **Razão de Sobrevivência Censitária (CSMR)** | Migração líquida por idade/sexo, sem estatísticas vitais | Estrutura etária da migração; onde o registro vital é ruim |

O resíduo é superior quando o objetivo é o **saldo líquido coerente com o balanço
demográfico do período intercensitário** e há boa cobertura vital. Os quesitos
censitários são superiores para **fluxos brutos e origem‑destino**.

---

## 12. Veredito

A metodologia do resíduo **ancorada em censos, com correção de fronteira e de
sub‑registro, é adequada** para o saldo migratório líquido do RS em nível
estadual, de agregados (microrregiões/COREDEs) e de municípios médios/grandes.
Para municípios pequenos, os valores são mantidos, mas devem ser lidos como
aproximações ruidosas (sinalizados no app). Para fluxos brutos e origem‑destino,
o método é inadequado por construção — use os quesitos censitários.

---

## 13. Referências

- Demopædia (IUSSP/ONU) — *Vital statistics method* / *Residual method*:
  http://en-ii.demopaedia.org/wiki/Vital_statistics_method
- Preston, Heuveline & Guillot, *Demography: Measuring and Modeling Population
  Processes*: https://archive.org/details/demographymeasur0000pres
- IUSSP — *Tools for Demographic Estimation*:
  https://demographicestimation.iussp.org/
- IOM — *Migration Data Portal* (métodos):
  https://www.migrationdataportal.org/
- IBGE — Estimativas de população (método AiBi):
  https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html
- IBGE — Estimativas de sub‑registro:
  https://www.ibge.gov.br/estatisticas/sociais/populacao/26176-estimativa-do-sub-registro.html
- Cobertura SINASC/SIM (Scielo/RIPSA):
  https://www.scielo.br/j/csc/a/tyC6hXgsk54svFYk5KPGzhc/
- Rigotti (Cedeplar/UFMG) — técnicas indiretas de migração:
  https://repositorio.ufmg.br/server/api/core/bitstreams/1c62be65-009f-4d4b-954b-716ee8f22855/content
- DATASUS — Estatísticas vitais: https://datasus.saude.gov.br/estatisticas-vitais/
- DEE‑RS — *Cadernos RS no Censo 2022: Migração e Fecundidade* (nov/2025):
  https://dee.rs.gov.br/censo-2022-aponta-mudancas-nos-padroes-de-fecundidade-e-destaca-os-principais-fluxos-migratorios-no-rs
- Censo 2022 (data de referência): https://censo2022.ibge.gov.br/

*As coberturas de sub‑registro embutidas no app são aproximações regionais; para
publicação, substitua pelos valores oficiais do IBGE por UF/ano.*
