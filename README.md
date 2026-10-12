# Bilancio personale AWS — Milano + CloudFront pay-as-you-go senza WAF

Tre stack CloudFormation indipendenti. Repository pronto per Git.

| Stack | Regione | Contenuto |
|---|---|---|
| `bilancio-budget` | `us-east-1` | Budget mensile dell'intero account AWS, notifiche email |
| `bilancio-frontend` | `us-east-1` | CloudFront pay-as-you-go senza WAF, S3 privato + OAC (senza WAF) |
| `bilancio-backend` | `eu-south-1` **Milano** | Cognito Lite, HTTP API, Lambda **Python 3.13**, DynamoDB |

Il dominio personalizzato (`spese.ilsitodipatrizio.it` su GoDaddy) è volutamente rimandato. Il primo indirizzo HTTPS sarà `https://d...cloudfront.net/`.

## 0. Prerequisiti

- AWS CLI v2, Bash, Python 3.9+ sul computer di deploy. `python3 -m unittest discover -s tests -v` usa anche `boto3` e `PyYAML` installati localmente. **Non** servono queste due librerie per lanciare il deploy.
- La regione `eu-south-1` deve essere abilitata per l'account; il solo DNS è rimandato.

## 1. Budget PRIMA di creare le altre risorse

```bash
./scripts/deploy_budget.sh tua-email@example.com
```

Imposta **4 USD/mese sull'intero account**, avvisi al 50%, 75%, 100% e previsione 100%. Puoi modificare `MonthlyLimitUSD` nel comando. Non garantisce un tetto di spesa rigido: **i budget inviano avvisi, non disabilitano le risorse**. I costi AWS sono espressi in USD; un limite 4 USD non equivale esattamente a 5 EUR. Controllare fattura, IVA ed eventuali risorse preesistenti.

## 2. Deploy frontend e backend

```bash
# facoltativo: imposta un prefisso Cognito univoco nella regione eu-south-1
# export COGNITO_PREFIX=bilancio-123456789012
./scripts/deploy.sh
```

Lo script:

1. Copia `lambda/index.py` (sorgente modificabile) nella proprietà inline `Code.ZipFile` di `cloudformation/backend.yml` tramite `scripts/sync_lambda.py`.
3. Legge l'output `CloudFrontDomain` e lo passa come parametro a `cloudformation/backend.yml`, distribuito **solo in Milano** con `--capabilities CAPABILITY_IAM`.
4. Genera `frontend/config.json` con URL API e configurazione **pubblica** Cognito, carica HTML/JS in S3, invalida la cache CloudFront.
5. Stampa URL del sito, nome User Pool e URL API.

**Mai inserire password, segreti Cognito o chiavi AWS nei file frontend.** `config.json` contiene soltanto URL e client ID pubblico ed è escluso da Git.

### Deploy manuale CloudFormation senza lo script

Se desideri eseguire i template uno per volta:

```bash
aws cloudformation deploy --region us-east-1 --stack-name bilancio-frontend \
  --template-file cloudformation/frontend.yml

aws cloudformation describe-stacks --region us-east-1 --stack-name bilancio-frontend \
  --query 'Stacks[0].Outputs' --output table

python3 scripts/sync_lambda.py

aws cloudformation deploy --region eu-south-1 --stack-name bilancio-backend \
  --template-file cloudformation/backend.yml --capabilities CAPABILITY_IAM \
  --parameter-overrides CloudFrontDomain=d123456abcdef.cloudfront.net CognitoDomainPrefix=bilancio-IL-TUO-ACCOUNT
```

**Sostituisci** l'esempio `CloudFrontDomain` con l'output reale. Per utilizzare il sito occorre anche caricare `frontend/index.html`, `frontend/app.js` e `frontend/config.json` nel bucket; `./scripts/deploy.sh` automatizza questa parte. Lo script è quindi la strada più semplice.

## 3. Creare l'unico utente Cognito e attivare MFA

1. Console AWS → **Cognito** → regione **Europe (Milan) / eu-south-1** → User pools → pool in output dello stack `bilancio-backend`.
2. Crea **manualmente un solo utente**, con il tuo indirizzo email. La registrazione pubblica è disabilitata (`AllowAdminCreateUserOnly: true`). Imposta una password temporanea e usa la procedura di primo accesso per sceglierne una definitiva.
3. Apri l'URL CloudFront generato, premi **Accedi con Cognito**. Alla prima autenticazione completa il cambio password e **registra il TOTP** con un'app Authenticator; Cognito richiede MFA per poter finalizzare l'accesso.
4. Verifica che una richiesta a `GET /state` senza `Authorization` restituisca **401** da API Gateway, e che con JWT ID token ma non access token venga rifiutata dalla Lambda (**403**).

**Nota pratica:** gli utenti amministrativamente creati con password permanente potrebbero richiedere una procedura di enrollment TOTP diversa. Usa il normale flusso di password temporanea, che avvia la configurazione guidata nella Hosted UI classica. Non impostare `MfaConfiguration` su OPTIONAL per aggirare difficoltà di onboarding: si perde la garanzia MFA.

## 4. Sicurezza e modello dati

- *Prima del login*: `index.html`, `app.js` e `config.json` sono file statici accessibili, ma non contengono movimenti, budget, token, password o credenziali. L'interfaccia della dashboard resta nascosta.
- *Dopo il login*: OAuth2 Authorization Code + **PKCE**. Cognito Lite classic Hosted UI con username/password e **TOTP obbligatorio**. Il token di accesso sta in `sessionStorage`, non viene caricato su S3 e scade dopo **30 minuti** (nessun refresh token persistente).
- API Gateway HTTP API usa `JWT Authorizer` su **tutte le cinque route**. La Lambda valida ulteriormente `token_use == access` e `client_id` di Cognito. Senza JWT valido nessuna operazione legge DynamoDB.
- La Lambda ignora qualsiasi identità utente nel body; la chiave `PK = USER#<sub>` è ottenuta solo dai claim validati. I movimenti e i budget degli utenti sono isolati per `sub`.
- IAM Lambda concede soltanto `Query`, `PutItem`, `DeleteItem` **sulla tabella specifica**; niente `Scan` e niente accesso alla console. DynamoDB usa il default **AWS-owned key** per cifrare gratuitamente i dati a riposo.
- Bucket S3 con public access block + Origin Access Control e bucket policy che autorizza solo la distribuzione CloudFront. Nessun hosting website pubblico S3.
- Retention CloudWatch Lambda: 7 giorni. `DeletionPolicy: Retain` per DynamoDB, bucket e Cognito (non cancellare dati per errore). Dopo una cancellazione dello stack, **le risorse con Retain possono continuare a generare costi**.
- Le persone con privilegi amministrativi sull'account AWS o in possesso di un access token valido potrebbero accedere ai dati. MFA non è una protezione contro un account AWS compromesso o un token già rubato. Proteggi l'account AWS con MFA e ruoli IAM limitati.

### Endpoint

| Metodo | Path | Funzione |
|---|---|---|
| GET | `/state` | Movimenti e budget propri |
| POST | `/transactions` | Inserimento movimento |
| PUT | `/transactions/{id}` | Modifica movimento |
| DELETE | `/transactions/{id}` | Rimozione movimento |
| PUT | `/budgets/{category}` | Impostazione budget di categoria |

### Sviluppo del codice Python

Modifica `lambda/index.py` e rilancia `./scripts/deploy.sh`. Questo genera il codice inline CloudFormation. La stessa Lambda usa **boto3 incluso nel runtime Lambda Python** e non richiede librerie esterne. Quando serviranno più file o dipendenze, passeremo a ZIP versione S3, SAM o CDK.

## 5. Costi e limitazioni


DynamoDB **PROVISIONED 5 RCU / 5 WCU** sfrutta il free tier di 25 unità di ciascun tipo a livello di regione/payer account, purché queste non siano già consumate da altre tabelle. Impostazione volutamente semplice per un utente. In caso di carico elevato può essere necessario aumentare la capacità (con costi). Non è presente backup automatico: usa il pulsante **Esporta JSON** della dashboard. L'export non è una funzione di ripristino.


## 6. GoDaddy / dominio personalizzato (solo in futuro)

Quando avrai recuperato accesso ai DNS, potremo:

1. richiedere un certificato ACM in `us-east-1` per `spese.ilsitodipatrizio.it`;
2. associare il certificato e la `Alias` CloudFront nel template frontend;
3. aggiungere `CustomFrontendDomain=spese.ilsitodipatrizio.it` allo stack backend per OAuth callback e CORS;
4. creare CNAME GoDaddy del sottodominio verso la distribuzione CloudFront e i record di validazione ACM.

Non è necessario acquistare o trasferire il dominio su Route 53.

## 7. Test offline

```bash
python3 -m pip install --user pyyaml boto3
python3 -m unittest discover -s tests -v
python3 -m py_compile lambda/index.py
node --check frontend/app.js
```

I test coprono letture senza JWT, ID token scartati, client estranei, separazione per utente e operazioni CRUD. **Non sostituiscono** la validazione CloudFormation e il test end-to-end nel tuo account. Per una verifica AWS senza deploy puoi usare `aws cloudformation validate-template --region ... --template-body file://...` per ogni template. La validazione non dimostra che il tuo account sia idoneo al piano Free.

## Variante PAYG e controllo costi
Il frontend usa CloudFront a consumo senza Web ACL AWS WAF e senza PricingPlanManager. Il budget AWS è un avviso, NON un limite di fatturazione. Per il tuo tetto di 4 EUR complessivi, imposta prudentemente `MonthlyLimitUSD=3` (conversione e imposte possono variare). Evita di abilitare WAF, CloudFront real-time logs, NAT Gateway, ALB e SMS Cognito. Verifica ogni settimana AWS Cost Explorer e gli avvisi budget. Il free tier standard CloudFront può ridurre o azzerare i costi per traffico personale, ma non garantisce una spesa massima.
