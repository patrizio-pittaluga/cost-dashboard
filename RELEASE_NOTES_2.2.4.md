# Moneta 2.2.4 — Ricorrenze e gestione utenti

- Anche l’inserimento rapido offre una spunta Ricorrente e apre automaticamente i dettagli per impostare la frequenza.
- Modulo Nuovo movimento: checkbox Ripeti, frequenza, intervallo, data fine; crea una regola anziché contabilizzare subito un movimento duplicato. La prima occorrenza è registrata dallo scheduler. Per un movimento già esistente, la ripetizione non viene mostrata.
- Le ricorrenze esistenti restano gestibili dal menu Ricorrenze.
- Menu Gestione utenti esclusivo Admins: elenco pool, creazione con password temporanea, reset temporaneo, disabilitazione e riabilitazione account.
- Permessi IAM limitati allo specifico pool; API richiedono token valido e controllo server-side del gruppo Admins.
- Disabilitare un account richiede AdminUserGlobalSignOut; il JWT authorizer può continuare ad accettare token già emessi fino a scadenza; password non memorizzate in DynamoDB.
- IMPORTANTISSIMO: l'email di invito richiede configurazione adeguata di Cognito. La password temporanea va condivisa tramite canale sicuro.
- La creazione di una ricorrenza non contabilizza immediatamente il movimento iniziale; questo è affidato allo scheduler.
- Nessuna modifica diretta ai dati DynamoDB, nessuna nuova tabella. Effettuare backup prima del deploy.
