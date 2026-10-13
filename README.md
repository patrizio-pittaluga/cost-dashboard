# Moneta 2.2 — Fondo comune e gestione del capitale (release estesa)

**Data:** 13 ottobre 2026  
**Origine:** versione 2.2 primo rilascio, derivata da Moneta 2.1  
**Sito di destinazione:** https://moneta.ilsitodipatrizio.it  
**Stato:** codice e test locali completati; **non è stato effettuato il deploy nell'account AWS**.

Questa versione estende il primo rilascio di Moneta 2.2 con **storni contabili tracciati**, **portafoglio investimenti con costo storico**, **motore di segnalazioni spiegabili** e **simulatore di liquidità e risparmio**. Mantiene inserimento rapido, preferiti, scadenze, PWA, account Cognito e bilanci condivisi.

## Prima di aggiornare: sicurezza dei dati

1. **Non cancellare** gli stack `moneta-frontend`, `moneta-backend`, la tabella DynamoDB o il pool utenti Cognito.
2. Fai un **backup nativo DynamoDB** prima del deploy (vedi sotto). Il JSON esportato dall'interfaccia **non** include l'intero registro contabile né le schede investimento.
3. Conserva una copia del precedente ZIP 2.2: durante il rollback non registrare nuovi anticipi, rimborsi o storni con una versione vecchia dell'app.
4. Verifica account e regione AWS prima di lanciare qualunque comando.

### Backup DynamoDB — AWS CloudShell

```bash
aws sts get-caller-identity
TABLE_NAME="$(aws cloudformation describe-stacks --region eu-south-1 \
  --stack-name moneta-backend \
  --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue | [0]" \
  --output text)"
printf 'Tabella selezionata: %s\n' "$TABLE_NAME"
aws dynamodb create-backup --region eu-south-1 --table-name "$TABLE_NAME" \
  --backup-name "moneta-pre-full-22-$(date +%Y%m%d-%H%M)"
```

Il backup può comportare costi di archiviazione aggiuntivi. Aspetta di verificare il completamento prima del deploy; evita backup o rollback senza aver controllato lo stato nella Console.

## Installazione / aggiornamento

Carica lo ZIP `moneta-2.2-completa-aws.zip` in AWS CloudShell e decomprimilo:

```bash
unzip moneta-2.2-completa-aws.zip
cd moneta-2.2-completa
python3 scripts/sync_lambda.py
python3 -m unittest discover -s tests -v
bash scripts/deploy.sh
```

Lo script aggiorna gli **stack esistenti** `moneta-frontend` (us-east-1) e `moneta-backend` (eu-south-1). La distribuzione Lambda avviene tramite il bucket S3 privato già impiegato dalla 2.1. **Non occorre creare nuovi utenti**, reinstallare Cognito o migrare la tabella. Gli eventuali parametri del dominio sono letti dagli stack esistenti.

Dopo l'aggiornamento apri https://moneta.ilsitodipatrizio.it/, aggiorna la pagina e riavvia l'app installata se necessario. La cache PWA passa a `moneta-static-v2.2.1`.

## Novità — Fondo comune

Nello spazio condiviso **Casa → Fondo comune**, è possibile:

- registrare versamenti e rimborsi parziali, attribuendo quote esplicite ai membri;
- **stornare** un versamento, un anticipo o un rimborso attraverso il pulsante **«Storna questa operazione»**;
- indicare una motivazione obbligatoria e vedere lo storno nel registro, preservando le voci originali;
- correggere un anticipo già rimborsato seguendo l'ordine: **prima storna i rimborsi, poi l'anticipo**, infine registra l'operazione corretta.

Lo storno crea **movimenti di compensazione** e un record immutabile con riferimento all'originale. Non cancella la registrazione, non riutilizza l'ID originale e non effettua pagamenti bancari. Un membro può stornare i propri movimenti, il proprietario del fondo può stornare anche quelli degli altri membri **ancora attivi**. Il lettore non può scrivere. Il server verifica i ruoli all'interno della transazione atomica.

**Cosa significa contabilmente:** uno storno annulla l'effetto registrato; non necessariamente corrisponde al movimento reale avvenuto in banca. Se i soldi sono già passati tra conti, la registrazione deve rappresentare la realtà, non una cancellazione fittizia. Uno storno può far scendere il saldo del fondo sotto zero; Moneta registra il saldo, ma non blocca la spesa bancaria.

### Operazioni non stornabili automaticamente

La versione non storna un anticipo mentre ci sono rimborsi non ancora stornati o quando il beneficiario è stato rimosso dal fondo. In questi casi è necessaria una rettifica amministrativa controllata; non aggirare il blocco aggiungendo movimenti artificiali.

## Novità — Portafoglio investimenti

Nel **bilancio personale → Insights**:

- crea/modifica/elimina schede `investment`, `other`, `debt`, `cash_outside_ledger`;
- per gli investimenti registra **classe**, **ticker o ISIN**, **quantità**, **prezzo unitario EUR**, **costo storico totale** e **commissioni**;
- se specifichi quantità e prezzo, il valore viene calcolato al centesimo; in alternativa inserisci direttamente il valore stimato;
- visualizza **valore aggregato, peso percentuale, plus/minusvalenza non realizzata** e data dell'ultima valutazione;
- ricevi segnalazioni per valutazioni oltre 30 giorni e posizioni che superano il 40% del portafoglio (soglie informative, non raccomandazioni).

Le valutazioni si aggiornano **manualmente**; nessun recupero prezzi di mercato, conversione valutaria, integrazione broker o conto corrente. Il costo storico deve includere i costi di acquisto; le commissioni indicate a parte sono **informative e già incluse nel costo**. I rendimenti sono calcoli grezzi prima delle imposte, senza dividendi e senza metodologia time-weighted. Gli investimenti in divisa diversa dall'euro vanno prima convertiti manualmente: il sistema non conosce i tassi di cambio.

**Attenzione al patrimonio:** Moneta somma gli investimenti registrati al saldo di cassa ricostruito dai movimenti. Per evitare doppi conteggi, un acquisto finanziato dalla cassa tracciata deve avere anche l'appropriata uscita di cassa registrata. Questa versione **non** automatizza il collegamento tra compravendite di titoli e movimenti del conto e non distingue ancora automaticamente gli acquisti di investimento dai consumi nei grafici storici. Non attribuisce automaticamente il saldo del fondo comune al patrimonio individuale.

Le modifiche a una scheda patrimoniale usano un numero di revisione e un controllo condizionale in DynamoDB per segnalare modifiche concorrenti (`409`): ricarica la pagina se un altro dispositivo ha già salvato.

## Novità — Simulatore e consigli

**Insights → Simula la tua liquidità** produce, per 1–36 mesi:

- scenario di base (media mensile degli ultimi tre mesi **completi**);
- scenario modificato con riserva accantonata mensilmente, spese mensili extra, minori entrate e una spesa imprevista iniziale;
- liquidità stimata, riserva cumulata e somma delle due, mese per mese;
- avvisi sui dati insufficienti e su periodi di liquidità negativa.

Una riserva è trattata come **trasferimento interno**, non come spesa né come guadagno. Il motore non applica rendimenti, tassi di mercato, inflazione, imposte aggiuntive o analisi AI. Le scadenze future non vengono sommate **di nuovo** alla media delle spese: sarebbe un potenziale doppio conteggio. Le proiezioni sono puramente indicative e migliorano soltanto con dati completi.

I consigli aggiungono controlli di copertura delle spese essenziali, budget del mese completo precedente, concentrazione e vecchiaia delle valutazioni. Non fanno ordini d'investimento né garantiscono risultati futuri.

## Nuove API — tutte dietro JWT Cognito

| Rotta | Ambito | Azione |
|---|---|---|
| `POST /fund/operations/{id}/reverse?spaceId=...` | membro autore o proprietario, in scrittura | Storno con `{ "reason": "..." }` |
| `PUT /capital/items/{id}` | utente personale | Aggiorna la scheda intera, con `revision` |
| `POST /insights/simulate` | utente personale | Calcola lo scenario senza salvare dati |

Tutte le API precedenti restano disponibili. DynamoDB usa la **stessa tabella**: aggiunge `REV#...`, `LEDGER#rev-...` e correzioni `TX#...` nello spazio condiviso e in quelli personali coinvolti. `TransactWriteItems` garantisce atomicità; il controllo `ADV#version` protegge la concorrenza nei rimborsi e negli storni. Solo l'endpoint per i costi AWS è accessibile al gruppo Cognito `Admins`; i dati finanziari privati degli altri utenti non sono accessibili all'Admin.

### Modifiche CloudFormation

Il confronto con il primo rilascio Moneta 2.2 mostra **43 risorse precedenti identiche**, **3 nuove rotte API**, **nessuna risorsa rimossa**. Nessun nuovo database, servizio AI o servizio sempre acceso. I costi variabili possono crescere per più richieste / operazioni; AWS Budgets da circa 3 USD resta un avviso per **l'intero account**, incluse le regioni Milano, Virginia e i servizi globali, non un limite rigido.

## Verifiche locali eseguite

```bash
python3 scripts/sync_lambda.py
python3 -m unittest discover -s tests -v
node --check frontend/app.js
bash -n scripts/deploy.sh
```

Sono stati eseguiti **112 test automatici** localmente, inclusi i test legacy. Il confronto del template CloudFormation è stato effettuato sul codice. Il browser headless in questo ambiente blocca la navigazione locale: **non è stato completato un collaudo grafico con smartphone o in un account AWS reale**.

## Checklist dopo il deploy

1. **Bilancio personale**: vecchi movimenti, budget, PWA e login Cognito ancora funzionanti.
2. **Fondo**: con A registra versamento 20 € → fondo +20 €, personale A −20 €, nessun nuovo consumo nei grafici.
3. **Storno versamento**: usa **Storna** con motivo → saldi tornano al valore iniziale, storico originale conservato e marcato come stornato.
4. **Anticipo B**: A paga 10 € e attribuisce 5 € ad A e 5 € a B → saldo fondo invariato, debito B verso A 5 €.
5. **Rimborso B**: B registra 2 € → saldo B −2 €, A +2 €, debito residuo 3 €; nessuna doppia spesa.
6. **Storno anticipo**: non deve riuscire prima dello storno del rimborso. Correggi prima il rimborso; poi l'anticipo.
7. **Patrimonio**: crea una posizione ETF in euro con quantità, prezzo e costo; modifica e controlla risultato e data.
8. **Simulatore**: modifica riserva e spese impreviste. La proiezione deve spiegare le ipotesi e distinguere riserva dalla cassa.
9. **Privacy**: un estraneo al fondo deve ricevere 403; un `viewer` non può stornare; `Admins` non può leggere gli Insights altrui.
10. **AWS**: controlla `UPDATE_COMPLETE`, Lambda CloudWatch, budget, PWA / cache e comportamento su almeno due smartphone/browser.

In caso di errore interrompi l'utilizzo condiviso, preserva il backup e raccogli il messaggio CloudFormation/CloudWatch. Il rollback del codice non annulla i movimenti e gli storni già registrati: verifica sempre la compatibilità contabile prima di tornare a una versione precedente.


## Aggiornamento 2.2.2 — Accesso e primo avvio

- Pagina iniziale Moneta rinnovata, senza riferimenti tecnici al provider di autenticazione.
- Tour introduttivo di sei passaggi al primo accesso per account **su questo browser/dispositivo**; si può saltare e ripetere da **Budget e dati → Rivedi il tour di Moneta**. La preferenza viene conservata in localStorage per identificativo account, non nel database: su un nuovo dispositivo il tour viene riproposto.
- Il form username/password e il codice MFA restano sulle pagine ospitate da **Amazon Cognito**. Questo pacchetto migliora la schermata Moneta prima del reindirizzamento, **non** lo stile dei campi Cognito. Per personalizzare i campi reali occorre configurare il branding della Managed Login di Cognito separatamente nella console AWS (verificando il tipo di login supportato dal pool). Non sostituire il flusso OAuth PKCE con un form di credenziali gestito da Moneta.
- Non sono necessarie modifiche allo schema DynamoDB o alle Lambda per questa release. La cache PWA passa a `moneta-static-v2.2.2`.
