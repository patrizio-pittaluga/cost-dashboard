# Moneta 2.0 — Bilanci privati e familiari

Aggiornamento **in-place** degli stack esistenti `moneta-frontend` (us-east-1) e
`moneta-backend` (eu-south-1), senza alterare la tabella DynamoDB o ricreare
il Cognito User Pool. Dominio: **https://moneta.ilsitodipatrizio.it**.

## Cosa cambia

- Ogni account Cognito conserva il proprio bilancio personale (`USER#sub`).
- Nuovi spazi familiari (`SPACE#uuid`) con ruoli `owner`, `editor`, `viewer`.
- Uno spazio può avere più membri e ogni utente può partecipare a più spazi.
- Invitare utenti Cognito esistenti tramite email verificata; l'invito appare in app (non parte un'email automatica).
- Le spese di uno spazio condiviso compaiono anche nello storico personale **dell'autore originale**. Un movimento condiviso e la sua proiezione personale vengono scritti insieme in una transazione DynamoDB.
- **Fondo comune:** la spesa addebita il fondo, appare nel personale ma non diminuisce due volte il saldo personale.
- **Pagamento personale:** la spesa compare nel familiare e diminuisce soltanto il saldo personale dell'autore.
- **Versamento nel fondo:** entrata nel familiare + uscita nel personale di chi versa.
- Ricorrenze personali e familiari; ricorrenze familiari generate una sola volta, con proiezione personale atomica quando l'autore è ancora membro.
- Cognito group `Admins` per la dashboard costi AWS. L'applicazione **non concede a un admin l'accesso ai bilanci privati degli altri**.

## 1. Prima di modificare AWS

1. Esporta un backup JSON da **Moneta > Budget e dati** mentre la versione attuale è online.
2. Conserva una copia del repository attuale per un eventuale rollback.
3. Aggiorna l'intero progetto con i file di questo pacchetto, **non soltanto `index.py`**: servono nuove rotte API e permessi IAM.
4. In CloudShell usa le credenziali AWS normalmente impiegate per gli stack Moneta, poi controlla:

```bash
aws sts get-caller-identity
aws cloudformation describe-stacks --region eu-south-1 --stack-name moneta-backend --query 'Stacks[0].StackStatus' --output text
aws cloudformation describe-stacks --region us-east-1 --stack-name moneta-frontend --query 'Stacks[0].StackStatus' --output text
```

**Non eliminare gli stack e non eseguire `cleanup_legacy.py`** durante l'upgrade.

## 2. Validazioni locali

Dalla cartella principale di questo progetto:

```bash
python3 -m pip install boto3 pyyaml # solo se non sono installati
python3 scripts/sync_lambda.py
python3 -m unittest discover -s tests -v
python3 -m py_compile lambda/index.py
node --check frontend/app.js
bash -n scripts/*.sh
```

Lo script `sync_lambda.py` compone automaticamente il file inline `backend.yml`
partendo da `lambda/index.py`, eliminando i commenti/docstring nel solo template.
Si arresta se supera il limite AWS di **51.200 byte**. Non serve un nuovo bucket
S3 di deploy.

## 3. Deploy negli stessi stack

```bash
bash scripts/deploy.sh
```

Il comando mantiene automaticamente il dominio e il certificato ACM salvati
negli stack correnti, recupera il prefisso Cognito preesistente e rigenera
`frontend/config.json`. Pubblica frontend S3 e invalida CloudFront. Durante
l'aggiornamento, le API potrebbero essere temporaneamente indisponibili.

**Verifica il Change Set** in CloudFormation prima di applicare aggiornamenti su
risorse critiche, se vuoi un controllo aggiuntivo. Non deve sostituire
`UserPool` o `DataTable`. Il template lascia immutati i rispettivi logical ID.

### Diventa amministratore della dashboard AWS

Il deploy crea **il gruppo**, ma non iscrive automaticamente nessuno.
Per aggiungere il tuo account Cognito, dalla root del progetto:

```bash
bash scripts/add_admin.sh tua-email-cognito@example.it
```

Lo script verifica il nome dell'utente, chiede conferma e chiama
`admin-add-user-to-group`. Esci dall'app e accedi nuovamente, così Cognito
rilascia un access token con il claim `cognito:groups` aggiornato.

**Non associare ruoli IAM AWS agli utenti Moneta:** il gruppo definisce
soltanto l'accesso logico alle dashboard amministrative.

## 4. Aggiungere una persona

- Crea per la persona un account nel **medesimo** User Pool Cognito di Milano.
  Mantieni l'email verificata, una password personale e la MFA TOTP.
  Cognito continua a vietare l'auto-registrazione pubblica.
- La persona completa la sua prima autenticazione su Moneta.
- Dal tuo account crea un bilancio condiviso, selezionalo, poi apri **Bilanci condivisi > Invita**.
- L'invito è visibile nella sezione **Bilanci condivisi > Inviti ricevuti** del destinatario. Il destinatario può accettare o rifiutare. Scade dopo 7 giorni.
- Gli utenti normali non vedono **Costi AWS** né possono accedere all'endpoint `/costs` (403).

## 5. Matrice permessi

| Azione | Proprietario | Membro (editor) | Lettore (viewer) |
|---|---|---|---|
| Leggere movimenti, ricorrenze, budget | sì | sì | sì |
| Inserire, modificare o eliminare movimenti | sì | sì | no |
| Modificare ricorrenze e budget | sì | sì | no |
| Invitare o rimuovere membri | sì | no | no |

Il gruppo `Admins` **non bypassa** la verifica di appartenenza allo spazio.
Le richieste ai dati condivisi richiedono `spaceId`, verificato sulla Lambda.
Il browser non determina mai il proprietario dei dati.

## 6. Esempi contabili

| Operazione di 50 EUR | Spazio Casa | Personale di chi l'ha creata |
|---|---|---|
| Spesa pagata dal fondo | saldo fondo −50 | storico: 50 EUR, saldo invariato |
| Spesa pagata personalmente | report: −50, saldo fondo invariato | saldo personale −50 |
| Versamento personale al fondo | saldo fondo +50 | saldo personale −50 |

Ogni spesa familiare produce **una sola operazione originale**; la copia
personale è una proiezione di sola lettura. Modifiche/eliminazioni alla fonte
aggiornano/eliminano il collegamento. È possibile esportare i dati dallo
spazio selezionato.

## 7. Controlli dopo il deploy

1. Apri `https://moneta.ilsitodipatrizio.it`, accedi con l'account attuale e verifica che tutti i movimenti personali siano presenti.
2. Crea lo spazio **Casa**; registra una spesa dal fondo; torna al personale: deve comparire nello storico ma **non** ridurre il saldo personale.
3. Registra una spesa personale nello spazio Casa: deve ridurre il saldo personale, ma **non** il saldo del fondo.
4. Modifica la spesa nello spazio Casa: entrambe le viste devono mostrare l'importo aggiornato. Poi elimina un movimento di prova.
5. Prova con un altro account Cognito e verifica che senza invito non possa accedere allo spazio Casa neppure inviando manualmente richieste API.
6. Verifica ruolo viewer senza facoltà di modifica e che `/costs` restituisca `403` per i non admin.
7. Dopo una ricorrenza di test verifica che Scheduler non produca due movimenti; non avviare manualmente il tick se non necessario.

## 8. Vincoli e funzionalità future

- Questa versione non supporta ancora divisione delle spese in quote 50/50,
  trasferimento della proprietà, cancellazione completa di uno spazio,
  registrazione pubblica o notifica email degli inviti.
- I movimenti personali **già acquisiti** dall'autore rimangono nel suo storico
  anche dopo l'eventuale revoca dell'accesso allo spazio, ma non consentono di
  accedere agli altri dati del bilancio condiviso.
- Le ricorrenze familiari associate a pagamento personale vengono sospese se
  l'autore non è più membro, per evitare addebiti fantasma. Le ricorrenze
  alimentate dal fondo possono proseguire senza creare collegamenti personali
  a utenti revocati.
- Le ricorrenze sono ancora scansionate giornalmente (massimo 1500 regole):
  per molti utenti servirà un GSI con scadenze; DynamoDB rimane `PROVISIONED`
  a 5 RCU/5 WCU e il throughput va monitorato durante l'uso multiutente.
- S3+CloudFront restano pubblici **solo per l'HTML/JS statico**; i dati
  restano dietro JWT Cognito, MFA e autorizzazioni server-side.
- L'obiettivo di spesa **sotto circa 4 €/mese** non è un tetto AWS vincolante:
  i budget sono avvisi, non interruttori automatici. Verifica regolarmente il
  traffico e gli addebiti reali.
- Un utente con privilegi IAM amministrativi sull'**account AWS** può
  tecnicamente ispezionare DynamoDB al di fuori di Moneta: il limite degli admin
  applicativi non sostituisce la sicurezza dell'account cloud.
- Non sono state eseguite operazioni sul tuo account AWS in questa sessione.

## 9. Ripristino della versione precedente

Conserva lo ZIP del progetto **precedente**. Se desideri annullare il deploy,
ripristina i file di quella versione ed esegui `bash scripts/deploy.sh`.
L'archivio personale `USER#sub` non viene migrato né cancellato; le nuove righe
`SPACE#...` rimarranno nella tabella, non utilizzate dalla vecchia applicazione.

Consulta `docs/README-originale.md` per la documentazione storica del progetto.
