# lista-leads-medicos

Skill do Claude Code que **gera listas de leads de médicos para prospecção
ativa** (time de SDR). O operador responde 5 perguntas e recebe uma planilha
Google Sheets organizada, com os médicos de uma especialidade numa região — já
com Instagram, site, WhatsApp/telefone, endereço, nota do Google e nº de
avaliações.

O diferencial é o **cruzamento**: quando um médico é descoberto pelo Google, não
dá para ver o Instagram dele ali — e vice-versa. A skill fecha os dois lados
automaticamente.

## Como funciona

1. Pergunta: **especialidade · nicho · bairro/cidade/UF · quantidade · fonte**
   (Google Maps ou Instagram).
2. Roda o [Apify](https://apify.com):
   - `compass/crawler-google-places` (Google Maps) e/ou
   - `apify/instagram-scraper` (Instagram).
3. Cruza os lados:
   - **Google → Instagram:** lê o site/linktree da ficha e, se faltar, busca o
     perfil pelo nome.
   - **Instagram → Google:** casa cada médico com a ficha do GMB para trazer
     nota e nº de avaliações.
4. Monta um CSV e o sobe como **Google Sheets nativo** no Drive.

## Colunas da planilha

`Nome · Categoria · Instagram · Seguidores IG · Site · WhatsApp/Telefone ·
Endereço · Rua · Cidade · Estado · Google Maps · Total Score · Qtd Avaliações ·
Match Google↔IG`

A coluna **Match Google↔IG** diz de onde veio o vínculo cruzado (`site`,
`busca` ou vazio) — para o SDR saber o quanto confiar em cada linha. A skill
**nunca inventa dado**: campo sem informação fica em branco.

## Uso do motor

```bash
export APIFY_TOKEN="apify_api_xxx"          # ou configure apify_tokens.local
python scripts/gerar_leads.py \
  --especialidade "endocrinologista" \
  --cidade "Rio de Janeiro" --estado "RJ" --bairro "Tijuca" \
  --quantidade 20 \
  --fonte google \
  --out "leads.csv"
```

No Windows/PowerShell, exporte `PYTHONUTF8=1` para preservar a acentuação.
Só depende da biblioteca padrão do Python 3 — sem `pip install`.

## Configuração dos tokens Apify

O código **não contém tokens**. O motor lê a credencial de fora, nesta ordem:

1. `APIFY_TOKEN` — um único token.
2. `APIFY_TOKENS` — vários separados por vírgula; escolhe o de maior saldo.
3. `scripts/apify_tokens.local` — um token por linha (arquivo **ignorado** pelo
   Git; crie o seu localmente).

Exemplo de `scripts/apify_tokens.local`:

```
# um token por linha
apify_api_xxxxxxxxxxxxxxxxxxxx
apify_api_yyyyyyyyyyyyyyyyyyyy
```

> **Segurança:** nunca faça commit de tokens. Se um vazar, revogue e gere outro
> no painel do Apify.

## Custo aproximado

Uma lista de ~20 leads fica na casa de **US$ 0,10–0,30** de Apify. Quantidades
grandes (50+) multiplicam proporcionalmente.

## Estrutura

```
SKILL.md                    # instruções da skill (fluxo + integração com o Drive)
scripts/gerar_leads.py      # motor: Apify (Google ↔ Instagram) → CSV
references/apify-actors.md  # actors, campos, parâmetros e custos
evals/evals.json            # casos de teste
```
