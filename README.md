# Moneta — installazione pulita AWS

**Moneta** è una dashboard privata per entrate, uscite, saldo e ricorrenze. Questa release usa **solo nomi stack `moneta-*`**. Se l'app precedente era `bilancio`, non effettueremo alcuna migrazione: hai confermato che non ci sono dati da conservare.

## Architettura

| Stack | Regione | Servizi |
|---|---|---|
| `moneta-frontend` | `us-east-1` | Bucket S3 privato, CloudFront pay-as-you-go, Origin Access Control |
| `moneta-backend` | `eu-south-1` (Milano) | User Pool Cognito Lite con MFA TOTP obbligatorio, HTTP API protetta da JWT, Lambda Python 3.13, DynamoDB, EventBridge Scheduler, CloudWatch |
| `moneta-budget` | `us-east-1` | AWS Budgets, budget mensile di 3 USD per tutto l'account e avvisi email |

Non usiamo AWS WAF a pagamento, ALB, EC2, NAT Gateway, Route 53, PricingPlanManager, SMS MFA o concorrenza Lambda riservata. GoDaddy rimane indipendente: per ora usiamo il dominio HTTPS CloudFront di AWS. I file frontend non contengono dati finanziari; quelli sono visibili solo dopo il login Cognito. Le API verificano il token JWT e l'identità del client.

## Prerequisiti

- AWS CLI v2 autenticata tramite CloudShell oppure IAM Identity Center/SSO (nessuna access key permanente obbligatoria).
- Accesso AWS con autorizzazioni per CloudFormation, IAM, Cognito, DynamoDB, Lambda, CloudFront, S3, EventBridge Scheduler, Cost Explorer e AWS Budgets.
- Python 3.9+ per gli script, `bash` per il deploy. `boto3` è già disponibile nel runtime Lambda; per i test locali servono `boto3` e `PyYAML`.
- Consapevolezza che **cancellare gli stack originali distrugge gli utenti Cognito/MFA e qualsiasi dato precedente**. Non tocca altri stack AWS, né dominio GoDaddy, né account AWS.

## 1. Crea prima il nuovo budget (manteniamo attivi gli avvisi durante la pulizia)

Dalla radice del progetto:

```bash
./scripts/deploy_budget.sh tua-email@example.com
```

Il comando crea **`moneta-budget`** a `us-east-1` con soglia predefinita **3 USD** (margine rispetto all'obiettivo 4 EUR mensili). Puoi modificare la soglia in `cloudformation/budget.yml` o nello script. Questa è una notifica, **non** un tetto/blocco automatico dei costi. Potrebbero esserci temporaneamente due budget fino alla rimozione del vecchio.

## 2. Controlla l'inventario dei vecchi stack (non cancella nulla)

```bash
python3 scripts/cleanup_legacy.py
```

Mostra gli oggetti associati esattamente a questi stack:

- `bilancio-backend` in `eu-south-1`;
- `bilancio-frontend` in `us-east-1`;
- `bilancio-budget` in `us-east-1`.

**Importante:** la precedente infrastruttura impostava `DeletionPolicy: Retain` su Cognito User Pool, tabella DynamoDB e bucket S3. La sola eliminazione CloudFormation lascerebbe queste risorse nell'account, con possibili costi residui. Lo script le individua tramite CloudFormation e le elimina solo dopo aver eliminato i vecchi stack. Per il User Pool prima disattiva `DeletionProtection`. Se il bucket è versionato, lo script si ferma prima di svuotarlo; se un'operazione fallisce, controlla manualmente le risorse residue e non rilanciare comandi alla cieca.

## 3. Elimina definitivamente l'app precedente

**Solo dopo aver controllato l'inventario e verificato di essere nell'account AWS corretto:**

```bash
aws sts get-caller-identity --query Account --output text
python3 scripts/cleanup_legacy.py --execute --confirm-account 123456789012
```

Sostituisci `123456789012` con **il tuo** Account ID mostrato dal comando precedente. Non mettere l'Account ID nel repository. Lo script richiede che `moneta-budget` sia già nello stato `CREATE_COMPLETE` o `UPDATE_COMPLETE`. Non elimina mai gli stack `moneta-*`.

Se il vecchio stack aveva un altro nome, **non** modificare lo script per usare nomi generici: identifica prima il nome e l'origine delle risorse AWS dalla console. Se il vecchio User Pool o bucket è stato creato fuori da CloudFormation o i suoi stack sono già stati rimossi con `Retain`, questi oggetti **non** possono essere ritrovati automaticamente dallo script: controlla manualmente le risorse residue.

## 4. Nuovo deploy con nomi Moneta

```bash
python3 scripts/sync_lambda.py
aws cloudformation validate-template --template-body file://cloudformation/frontend.yml --region us-east-1
aws cloudformation validate-template --template-body file://cloudformation/backend.yml --region eu-south-1
aws cloudformation validate-template --template-body file://cloudformation/budget.yml --region us-east-1
./scripts/deploy.sh
```

Vengono creati `moneta-frontend` e `moneta-backend`. La Lambda è definita in `lambda/index.py`, sincronizzata nello YAML con `scripts/sync_lambda.py` e include operazioni CRUD e generazione automatica dei movimenti ricorrenti. Alla fine lo script crea `frontend/config.json` **solo localmente**, lo pubblica sul bucket S3 privato e invalida CloudFront. `config.json` contiene identificatori pubblici OAuth e URL, mai username o password; rimane escluso da Git.

Lo script controlla che i vecchi stack `bilancio-frontend` e `bilancio-backend` non esistano ancora, così non crea due installazioni parallele. Per il login usa il prefisso Cognito `moneta-<account-id>`; se è già occupato puoi impostare `COGNITO_PREFIX=moneta-personale-univoco ./scripts/deploy.sh` per scegliere un prefisso alternativo.

**Dovrai creare un nuovo utente Cognito** a Milano, e configurare una nuova password e MFA TOTP. Le identità del vecchio User Pool non vengono migrate.

## 5. Funzionalità e costi

- Home con **saldo attuale**, entrate/uscite, ultimi sette movimenti e grafici a linee degli ultimi sei mesi.
- Movimenti manuali con inserimento, modifica, eliminazione ed esportazione.
- Regole di ricorrenza settimanali, mensili, trimestrali e annuali, modificabili, sospendibili e con intervalli 1–12. EventBridge Scheduler richiama la Lambda ogni giorno alle **06:10 Europe/Rome**: le scritture con ID deterministico e controllo di esistenza evitano doppioni.
- Costi AWS dell'intero account tramite Cost Explorer, con cache di 24 ore per ridurre le chiamate (Cost Explorer può addebitare circa $0.01 per richiesta; l'importo dipende dal listino vigente).
- Budget AWS mensile 3 USD per l'intero account, con avvisi al 50%, 75%, 100% e sul superamento previsto.
- DynamoDB provisioned 5 RCU/5 WCU, senza PITR; CloudWatch log 7 giorni, HTTP API throttling a 2 richieste/s e burst 5. Non sono garanzie di spesa massima.

**Il tuo tetto desiderato è 4 EUR/mese.** AWS pay-as-you-go non offre una garanzia assoluta di non superarlo: i budget inviano avvisi ma non arrestano automaticamente la fatturazione. Controlla i costi e tieni attiva l'MFA dell'identità amministrativa AWS.

## 6. Test locali

```bash
python3 -m pip install boto3 pyyaml
python3 -m unittest discover -s tests -v
python3 -m py_compile lambda/index.py
bash -n scripts/deploy.sh scripts/deploy_budget.sh
node --check frontend/app.js
```

La suite valida logica Lambda e consistenza delle risorse, ma **non** equivale a un deploy reale su AWS. L'autenticazione Cognito, il funzionamento HTTPS e la disponibilità delle quote si verificano nel tuo account dopo il deploy.

## 7. Gestione successiva del dominio

Quando potrai accedere a GoDaddy, aggiungeremo `moneta.ilsitodipatrizio.com` e un certificato ACM gratuito per CloudFront in `us-east-1`, con record CNAME di validazione e di instradamento. GoDaddy resta registrar e gestore DNS. Questa configurazione **non** è inclusa nel deploy attuale.
