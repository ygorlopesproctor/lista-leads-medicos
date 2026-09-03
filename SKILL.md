---
name: lista-leads-medicos
description: >-
  Use SEMPRE que o time da MadScale/Black Sales precisar montar uma LISTA DE
  LEADS de médicos para prospecção ativa do SDR — puxar contatos por
  especialidade + região e devolver uma planilha organizada. Gatilhos:
  "puxa 20 endocrinologistas na Tijuca", "monta uma lista de leads de
  ginecologistas em BH", "preciso de médicos pra prospecção do SDR", "lista de
  [especialidade] em [cidade/bairro]", "gera leads pro comercial", "acha os
  dermatos de Ipanema com Instagram e telefone", "planilha de prospecção de
  nutrólogos", "/lista-leads". Roda o Apify (Google Maps + Instagram), CRUZA os
  dois lados (quem veio do Google ganha o Instagram; quem veio do Instagram
  ganha a ficha do Google, nota e nº de avaliações) e entrega um Google Sheets
  nativo no Drive com nome, @, site, WhatsApp, endereço, nota e avaliações.
  Use mesmo quando o usuário não disser "lead" ou "Apify" explicitamente — se o
  pedido é uma lista de médicos de uma especialidade numa região, é esta skill.
  NÃO confundir com `plano-de-acao`/`kickoff` (essas analisam UM médico já
  escolhido); esta DESCOBRE VÁRIOS médicos do zero para prospecção.
---

# Lista de Leads de Médicos (para o SDR)

Gera, em um comando, uma **planilha de prospecção ativa**: o SDR responde 5
perguntas e recebe um Google Sheets com os médicos de uma especialidade numa
região, já com Instagram, site, WhatsApp/telefone, endereço, nota do Google e
número de avaliações.

O valor está no **cruzamento**: quando a gente descobre um médico pelo Google,
não dá pra ver o Instagram dele ali — e vice-versa. Esta skill fecha os dois
lados automaticamente, para o SDR não ter que caçar dado a dado.

## Passo 1 — Perguntar ao usuário (nesta ordem)

Faça as perguntas de forma objetiva (pode ser tudo numa mensagem só). Só avance
quando tiver o essencial (especialidade, cidade e quantidade); o resto tem
default sensato.

1. **Especialidade** — ex: endocrinologista, ginecologista, dermatologista.
2. **Nicho/sub-nicho** (opcional) — ex: emagrecimento, menopausa, estética
   íntima. Refina a busca; deixe em branco se o usuário não tiver.
3. **Onde** — bairro (opcional) + **cidade** + **estado (UF)**. Ex: Tijuca ·
   Rio de Janeiro · RJ.
4. **Quantidade** de contatos — ex: 20.
5. **Fonte** — de onde partir a descoberta:
   - **Google Maps** → melhor cobertura de telefone, endereço, nota e
     avaliações; a skill tenta achar o Instagram de cada um.
   - **Instagram** → melhor para quem trabalha o perfil (bio, @, seguidores); a
     skill tenta achar a ficha do Google, a nota e as avaliações.

   Na dúvida, recomende **Google Maps** — costuma render lista mais completa de
   dados de contato para o SDR.

## Passo 2 — Rodar o motor

O scraping, o cruzamento e a montagem do CSV são determinísticos e ficam no
script. Rode-o com os parâmetros coletados:

```bash
python scripts/gerar_leads.py \
  --especialidade "endocrinologista" \
  --nicho "" \
  --cidade "Rio de Janeiro" --estado "RJ" --bairro "Tijuca" \
  --quantidade 20 \
  --fonte google \
  --out "leads-endocrino-tijuca.csv"
```

- Windows/PowerShell: rode com `PYTHONUTF8=1` no ambiente para não quebrar
  acentuação. No Bash (Git Bash) use `export PYTHONUTF8=1` antes.
- O script escolhe **sozinho** o token Apify com orçamento no mês (prefere a
  conta reserva; a do time costuma estourar o limite de USD 5). Para forçar um
  token, exporte `APIFY_TOKEN` antes de rodar.
- Buscas grandes levam alguns minutos (o script usa runs assíncronos com
  polling, então **não** estoura em buscas amplas). Se o comando demorar, rode
  em background e acompanhe o arquivo `.csv`.
- O script imprime no final um JSON com `total`, `com_instagram`, `com_google` e
  o caminho do arquivo — use isso para relatar a cobertura ao usuário.

Detalhes dos actors, campos de saída e parâmetros: veja
`references/apify-actors.md`. Leia esse arquivo se precisar ajustar a busca
(ex: médico com 2 endereços, categoria vindo errada, refinar por nicho).

## Passo 3 — Virar Google Sheets no Drive

O usuário quer a lista como **Google Sheets nativo**. O caminho é subir o CSV
pelo conector do Google Drive, que **converte CSV em planilha automaticamente**:

1. Leia o conteúdo do `.csv` gerado. O script já **higieniza** os campos
   (remove separadores exóticos que vêm nos títulos do Google, tipo `׀`, e
   chars de controle), então o conteúdo é seguro para reproduzir fielmente.
2. Chame `mcp__claude_ai_Google_Drive__create_file` com:
   - `title`: nome claro, ex: `Leads — Endocrinologistas Tijuca (2026-09-02)`.
   - `textContent`: o conteúdo do CSV (preferir `textContent` a `base64Content`
     — texto legível é mais fácil de reproduzir sem corromper).
   - `contentMimeType`: `text/csv` (a conversão para Google Sheets é o default —
     **não** passe `disableConversionToGoogleType`).
3. Pegue o `viewUrl` retornado e entregue ao usuário como o link da planilha.

Se o conector do Drive não estiver disponível na sessão, entregue o `.csv`
(e avise que é só importar no Sheets/Excel) em vez de travar.

## Colunas da planilha

Nesta ordem (é o que o SDR usa):

`Nome · Categoria · Instagram · Seguidores IG · Site · WhatsApp/Telefone ·
Endereço · Rua · Cidade · Estado · Google Maps · Total Score · Qtd Avaliações ·
Match Google↔IG`

- **Total Score** = nota do Google (0–5). **Qtd Avaliações** = nº de reviews.
- **Match Google↔IG** diz de onde veio o vínculo cruzado: `site` (achou o @ no
  site/linktree da ficha), `busca` (casou por nome numa busca) ou vazio (não
  achou). Serve para o SDR saber o quanto confiar naquela linha.

## Regras que não se quebram

- **Nunca invente dado.** Se não achou o Instagram, o telefone ou a nota, deixa
  a célula em branco. Uma planilha honesta com lacunas vale mais para o SDR do
  que uma "completa" com chute — dado errado queima o vendedor na abordagem.
- **Cobertura é best-effort.** O cruzamento casa por nome+cidade e não fecha
  100% (médico sem ficha no Google, homônimo, @ sem o nome real). Relate a
  cobertura real ao usuário (ex: "18/20 com Instagram, 15/20 com nota do
  Google") em vez de prometer perfeição.
- **Confirme antes de puxar muito.** Cada lead custa centavos de Apify, mas
  quantidades grandes (50+) gastam tempo e orçamento — confirme o número com o
  usuário se ele pedir algo alto.
- **Duas Tijucas, dois Jardins, etc.** Bairros com nome ambíguo (Tijuca vs
  Barra da Tijuca) confundem a busca. Se a região for ambígua, confirme qual
  antes de rodar — poupa uma lista errada.

## Depois de entregar

Ofereça o próximo passo natural do funil (sem encadear sozinho): "quer que eu
já prepare o roteiro de abordagem do SDR pra essa lista?" ou "quer que eu filtre
só os que têm nota do Google abaixo de X (dor de reputação)?". Deixe o usuário
decidir.
