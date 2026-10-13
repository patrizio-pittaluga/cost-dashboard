# Moneta 2.2.3 — Tour guidato interattivo

Il tutorial viene mostrato una sola volta per account e browser al primo accesso, e può essere riavviato da «Budget e dati → Rivedi il tour di Moneta».

In sei passaggi la guida apre le sezioni principali dell'app e illumina i comandi pertinenti, senza effettuare inserimenti o altre operazioni sui dati. Sono disponibili Avanti, Indietro e Salta. Il risultato della visita è memorizzato soltanto nel browser, separatamente per account; dopo la pulizia del database il tutorial non ricompare se lo stesso browser lo ha già completato o saltato: avviarlo manualmente dalle impostazioni.

Su smartphone la scheda guida si posiziona in alto o in basso per lasciare visibile, ove possibile, l'elemento evidenziato. Il layout è adattivo e si aggiorna a rotazione e ridimensionamento dello schermo.

## Installazione

Caricare lo ZIP su AWS CloudShell, quindi:

```bash
unzip moneta-2.2.3-tour-interattivo.zip
cd moneta-2.2-completa
python3 -m unittest discover -s tests -q
bash scripts/deploy.sh
```

Questa versione aggiorna il frontend e la cache della PWA, mantenendo invariato il backend applicativo e il database. Non è stato eseguito un deploy nell'account AWS del proprietario.

## Verifica manuale

1. Aprire «Budget e dati → Rivedi il tour di Moneta».
2. Controllare i sei passaggi sia da desktop sia da smartphone.
3. Provare «Indietro», «Avanti», «Salta» e il tasto Escape.
4. Verificare che il tutorial non inserisca operazioni e che il ripristino del tour funzioni.
5. Dopo il deploy, aggiornare la PWA se è ancora visibile la precedente interfaccia.
