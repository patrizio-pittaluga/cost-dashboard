# Moneta 2.2 — Release estesa

- Aggiunto storno guidato di versamenti, anticipi e rimborsi con motivo obbligatorio, audit e compensazioni non distruttive.
- Aggiunti controlli per impedire lo storno di un anticipo non completamente riconciliato.
- Aggiunta la vista "Portafoglio investimenti" con quote percentuali, costi storici, data valorizzazione e plus/minusvalenze non realizzate.
- Aggiunti aggiornamento delle schede patrimoniali e controllo ottimistico delle revisioni.
- Aggiunto simulatore della liquidità fino a 36 mesi con ipotesi trasparenti, senza rendimenti finanziari presunti.
- Esteso il motore di Insights con segnalazioni su concentrazione, valutazioni datate e budget mensili.
- Esclusi dal conteggio dei consumi gli storni e le operazioni annullate, mantenendo l'effetto corretto sui saldi contabili.
- Conservati gli account Cognito, gli spazi personali e familiari e i record esistenti.
- Tre rotte JWT nuove in CloudFormation; nessuna risorsa preesistente modificata o rimossa.
- Cache statica PWA aggiornata alla versione v2.2.1.
- Suite automatica: 112 test locali; deploy e visual QA live ancora da eseguire.
