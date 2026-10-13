# Moneta 2.1.0 — Note di rilascio

- Inserimento rapido desktop/mobile + salvataggio consecutivo.
- Preferiti privati per utente/spazio, con creazione e rimozione.
- Calendario delle scadenze ricorrenti e singole, vista mensile ed elenco.
- Creazione, modifica, cancellazione e conferma della scadenza singola con idempotenza e collegamento contabile atomico.
- PWA con file pubblici in cache, senza storage offline di dati finanziari.
- Nuovo pacchetto Lambda in bucket S3 privato `eu-south-1`: CloudFormation backend sotto limite template; mantenimento della Lambda esistente.
- Nuove rotte HTTP API JWT e record `PLAN#`/`FAV#` nella tabella esistente.
- Nessuna modifica distruttiva prevista a Cognito, DynamoDB o dati preesistenti.
- Verifiche offline: suite unittest, controllo sintassi Python/JS/bash, esecuzione mock dell'interfaccia mobile.

**Non verificato:** deploy AWS e accesso Cognito reale nell'account dell'utente. Seguire README e collaudo dopo deploy.
