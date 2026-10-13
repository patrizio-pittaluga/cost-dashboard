# Moneta 2.1 — Più comoda

**Versione:** 2.1.0 · **Data:** 13 ottobre 2026  
**Sito attuale:** https://moneta.ilsitodipatrizio.it  
**Scopo:** aggiornare in-place Moneta 2.0, senza cancellare dati, pool Cognito, MFA, bilanci condivisi o dashboard AWS.

## Novità

- **Inserimento rapido:** su desktop “Registra subito” e su smartphone pulsante `+` fisso in basso. Campi essenziali (tipo, importo, descrizione, categoria, data, origine pagamento nei fondi condivisi); “Salva e continua”; “Altri dettagli” apre il modulo completo.
- **Preferiti personali:** contrassegna un movimento abituale nel modulo rapido oppure con `☆` dallo storico. Richiamalo con un tocco per precompilare la spesa; modifica importo/data prima di salvare. Un preferito è privato dell'utente, separato per bilancio e salvato in DynamoDB (non nel browser).
- **Calendario:** vista mensile delle regole ricorrenti attive e delle scadenze singole; evidenzia previste, scadute e già registrate. La dashboard mostra le prossime scadenze. Le previsioni non influenzano il saldo prima della contabilizzazione.
- **Scadenze singole:** crea/modifica/elimina una scadenza; “Segna pagata” chiede la data reale di registrazione e crea una sola transazione contabilizzata, con protezione dai duplicati. Per un fondo familiare rispetta `Fondo comune` / `Denaro personale` e crea il collegamento personale atomico.
- **Dashboard e navigazione mobile:** nuovo percorso di accesso rapido, calendario, dock inferiore, menu “Altro” per le sezioni secondarie; permessi `Admins` invariati.
- **PWA:** icone 192/512, manifesto, service worker e modalità standalone. Il service worker salva in cache soltanto HTML/CSS/JS, manifesto e icone **pubblici**; **mai** `config.json`, token, movimenti o risposte API.

## Dove finiscono i dati

Le righe DynamoDB esistenti `USER#... / TX#...`, `REC#...`, `B#...`, `SPACE#...` restano nel medesimo schema. Le nuove entità condividono la stessa tabella:

| PK | SK | Contenuto |
| --- | --- | --- |
| `USER#sub` | `FAV#fav-...` | Preferito individuale con `spaceId` associato |
| `USER#sub` | `PLAN#p-...` | Scadenza singola personale |
| `SPACE#s-...` | `PLAN#p-...` | Scadenza singola familiare |
| Spazio originale | `TX#plan-p-...` | Movimento reale associato a una scadenza completata |
| `USER#sub` | `TX#link-...` | Proiezione personale collegata a scadenza familiare completata |

Sono aggiunte **sette rotte JWT autenticate**: `GET/POST /favorites`, `DELETE /favorites/{id}`, `POST /planned`, `PUT/DELETE /planned/{id}`, `POST /planned/{id}/complete`. Tutte le rotte con `spaceId` verificano il ruolo lato Lambda; un lettore non può modificare. Il gruppo Cognito `Admins` è limitato alle dashboard AWS e non aggira la separazione dei dati.

## 1. Prima del deploy

**Non eliminare stack, User Pool, tabella DynamoDB o CloudFront. Non eseguire `cleanup_legacy.py`.**

1. Dall'app attualmente online esporta un backup JSON del bilancio personale e dei bilanci condivisi che gestisci. Conserva lo ZIP del codice Moneta 2.0 per eventuale rollback.
2. Opzionale, ma consigliato: esegui anche un backup nativo della tabella DynamoDB (può comportare costi AWS). Da AWS CloudShell:

```bash
TABLE_NAME="$(aws cloudformation describe-stacks --region eu-south-1 \
  --stack-name moneta-backend --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue | [0]" --output text)"
aws dynamodb create-backup --region eu-south-1 \
  --table-name "$TABLE_NAME" --backup-name "moneta-prima-2-1-$(date +%Y%m%d)"
```

3. Controlla account AWS e status:

```bash
aws sts get-caller-identity
aws cloudformation describe-stacks --region eu-south-1 \
  --stack-name moneta-backend --query 'Stacks[0].StackStatus' --output text
aws cloudformation describe-stacks --region us-east-1 \
  --stack-name moneta-frontend --query 'Stacks[0].StackStatus' --output text
```

## 2. Caricare il progetto in AWS CloudShell

Carica `moneta-2.1-aggiornamento-aws.zip` in **CloudShell**, poi:

```bash
unzip moneta-2.1-aggiornamento-aws.zip
cd moneta-2.1
```

Il pacchetto contiene tutto il sorgente. **Non copiare soltanto `app.js` o `index.py`**: occorrono anche le nuove rotte CloudFormation, il manifesto PWA, il service worker e lo script di distribuzione.

## 3. Verifiche prima della pubblicazione

In CloudShell Python 3, AWS CLI e bash sono già disponibili. I test di struttura CloudFormation richiedono `PyYAML`; i test backend richiedono `boto3` e `botocore` (normalmente presenti). Sul proprio PC `node` è utile per validare il JavaScript.

```bash
python3 scripts/sync_lambda.py
python3 -m unittest discover -s tests -v
python3 -m py_compile lambda/index.py
bash -n scripts/deploy.sh
node --check frontend/app.js    # se Node.js è disponibile
node --check frontend/sw.js     # se Node.js è disponibile
```

I test sono locali con AWS simulato: **non dimostrano da soli che il deploy in AWS reale sia riuscito**.

## 4. Deploy sugli stack esistenti

```bash
bash scripts/deploy.sh
```

Lo script esegue nell'ordine:

1. Prepara `dist/moneta-lambda.zip` con `lambda/index.py`.
2. Aggiorna lo stack CloudFront/S3 **esistente** in `us-east-1`, mantenendo dominio e certificato.
3. Crea **se necessario** un bucket S3 privato per i pacchetti Lambda nella regione Milano (`moneta-deploy-<account>-eu-south-1`) con blocco accesso pubblico e cifratura SSE-S3. Carica il file ZIP con un nome identificato da hash SHA-256.
4. Aggiorna lo stack `moneta-backend` in `eu-south-1`. La risorsa Lambda mantiene stesso logical ID e stesso `FunctionName`, ma ora legge il codice da S3 regionale anziché dal campo inline `ZipFile` (che era vicino al limite CloudFormation).
5. Aggiorna il frontend statico, imposta `no-store` per `config.json` e `sw.js`, pubblica manifesto e icone e invalida la cache CloudFront.

**Nota sui costi:** il bucket regionale di deploy è **una nuova risorsa privata** con un costo storage normalmente minimo, ma non zero garantito. I vecchi pacchetti versionati per hash restano disponibili per rollback. AWS Budgets continua a monitorare l'**intero account**, entrambe le regioni e CloudFront, con soglia indicativa di 3 USD/mese; non interrompe automaticamente le spese.

### Controlli CloudFormation dopo il deploy

```bash
aws cloudformation describe-stacks --region eu-south-1 \
  --stack-name moneta-backend --query 'Stacks[0].StackStatus' --output text
aws cloudformation describe-stacks --region us-east-1 \
  --stack-name moneta-frontend --query 'Stacks[0].StackStatus' --output text
```

Verifica `UPDATE_COMPLETE` / `CREATE_COMPLETE`. In caso di rollback automatico leggi gli eventi CloudFormation e i log CloudWatch prima di ripetere la procedura. Assicurati che DynamoDB e User Pool **non** siano stati sostituiti.

## 5. Collaudo funzionale

1. Apri https://moneta.ilsitodipatrizio.it in browser e fai **Ctrl+F5** per aggiornare. Verifica tutti i movimenti preesistenti e lo stesso saldo personale.
2. Apri `+` / **Registra subito**, salva una piccola spesa di prova; usa **Salva e continua** e verifica categoria, data e saldo.
3. Salva un preferito, richiamalo dai chip nella dashboard, modifica importo e registra; controlla che il preferito non compaia in un secondo utente.
4. In **Scadenze**, crea una scadenza singola; controlla che **non** modifichi il saldo prima della conferma. Usa **Segna pagata** scegliendo la data effettiva; verifica un solo nuovo movimento e lo stato “Registrata”. Riprova la conferma: non devono crearsi doppioni.
5. Controlla che ricorrenze mensili, settimanali, trimestrali e annuali appaiano nel calendario, senza generare movimenti futuri solo perché visualizzate.
6. In uno spazio familiare testa un pagamento dal **fondo comune** (saldo personale invariato) e uno con **denaro personale** (saldo personale diminuisce, quello del fondo resta invariato).
7. Prova con un secondo utente Cognito: non deve leggere il bilancio privato o le scadenze altrui; un membro `viewer` può leggere ma non creare pagamenti. Solo il gruppo `Admins` può usare la dashboard Costi AWS.
8. Su smartphone prova **Aggiungi alla schermata Home**, apri Moneta come app installata, autentica l'utente con MFA. Chiudi e riapri l'app per verificare il percorso di accesso. **Offline** è disponibile solo l'interfaccia pubblica: per autenticazione e dati serve la rete.

## 6. Limiti e scelte volute

- Non vengono inviate notifiche push/email di scadenza; l'agenda va aperta in Moneta.
- I preferiti restano privati, ma si possono creare più preferiti identici; massimo 40 per account. Le scadenze singole massimo 200 per bilancio.
- Le ricorrenze continuano ad essere **registrate automaticamente** dal job EventBridge esistente quando maturano, non dal calendario.
- Il completamento di una scadenza singola crea un movimento con data di pagamento esplicitamente scelta; non modifica la regola di una ricorrenza.
- Se una scadenza è già stata completata, non può essere modificata o cancellata direttamente: per correggerla, modifica/elimina il movimento contabile e gestisci la riconciliazione con attenzione. La scadenza mantiene traccia del completamento.
- La PWA non supporta inserimento di movimenti offline, allegati, sincronizzazione offline o notifiche push.
- Non è inclusa una procedura automatica di import/ripristino JSON; prima dell'upgrade va sempre tenuto un backup.

## 7. Rollback

Conserva ZIP versione 2.0 e la copia dei dati. Il nuovo backend usa un pacchetto Lambda in S3; se vuoi ripristinare 2.0, puoi distribuire il **vecchio progetto con il vecchio `deploy.sh`**, ripristinando il codice inline, dopo aver verificato che lo stack non richieda ancora i nuovi parametri. Il rollback del codice **non cancella** le righe `PLAN#` e `FAV#` aggiunte; la vecchia app le ignorerà. Un rollback di codice **non** sostituisce un eventuale restore DynamoDB.

## 8. Checklist sicurezza

- L'autenticazione continua tramite **Cognito JWT access token e MFA**.
- Anche i nuovi endpoint controllano l'eventuale `spaceId` e i permessi lato Lambda, non si affidano solo ai pulsanti nascosti.
- Scadenze e preferiti sono dati DynamoDB, non `localStorage`.
- `serviceWorker` non mette in cache dati autenticati, `config.json` o chiamate cross-origin alle API.
- Nessun endpoint personale diventa automaticamente accessibile a un amministratore; per i costi AWS resta `Admins`.
- AWS Budgets emette **avvisi**, non pone un limite assoluto ai costi.

**Stato della consegna:** codice e test locali preparati; **nessun deploy eseguito nel tuo account AWS** durante questa lavorazione. In caso di errori CloudFormation, non cancellare alcuno stack: recupera gli eventi e correggi l'upgrade.
