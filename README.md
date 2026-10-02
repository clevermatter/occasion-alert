# Occasion-alert

Zoekt elk half uur op **AutoScout24** en **viaBOVAG** naar een **Renault Clio E-Tech hybride tot €18.000 en maximaal 90.000 km, binnen 50 km van Venray**. AutoTrack gebruikt hetzelfde aanbod als AutoScout24 en is daarom niet apart nodig. Gaspedaal blokkeert de servers van GitHub en staat daarom uit. Je krijgt een Telegram-bericht bij:

- 🚗 een **nieuwe auto** die aan je eisen voldoet
- 📉 een **prijsverlaging** van een auto die je al eerder zag

Staat dezelfde auto op meerdere sites, dan herkent de bot dat aan dezelfde kilometerstand en hetzelfde bouwjaar. Je krijgt dan één bericht met links naar alle sites. Bij de allereerste run krijg je één overzicht van alles wat er op dat moment te koop staat.

## Installeren (± 10 minuten)

1. **Maak een nieuwe repository** op GitHub, bijvoorbeeld `occasion-alert`.
   - **Public** = gratis minuten.
   - **Private** kost ongeveer 1.000 van je 2.000 gratis minuten per maand. Samen met je Marktplaats-bot kom je dan boven de limiet. Kies in dat geval public, of zet de cron in de workflow op elk uur (`0 5-21 * * *`).
2. **Upload alle bestanden**, inclusief de map `.github/workflows/`. Dat kan via *Add file → Upload files*: sleep de hele map erin.
3. **Voeg twee secrets toe** via *Settings → Secrets and variables → Actions → New repository secret*:
   - `TELEGRAM_BOT_TOKEN`: het token van je bot. Je kunt dezelfde bot gebruiken als voor de Marktplaats-meldingen.
   - `TELEGRAM_CHAT_ID`: je eigen chat-ID. Voor meerdere ontvangers scheid je de ID's met komma's.
4. Ga naar het tabblad **Actions** → *Occasion alert* → **Run workflow**. Binnen een minuut krijg je het overzichtsbericht.

## Timer (cron-job.org)

De ingebouwde timer van GitHub slaat regelmatig runs over. Daarom start [cron-job.org](https://cron-job.org) de bot elk half uur via de GitHub-API, net als bij de Marktplaats-bots:

- **URL:** `https://api.github.com/repos/clevermatter/occasion-alert/actions/workflows/occasion-alert.yml/dispatches`
- **Methode:** `POST`
- **Headers:** `Accept: application/vnd.github+json` en `Authorization: Bearer <je GitHub-token>`
- **Body:** `{"ref":"main"}`

Het token moet voor deze repository de rechten *Actions: Read and write* hebben. De GitHub-timer blijft als reserve aan. Dubbele runs zijn geen probleem, want de bot meldt elke auto maar één keer.

## Zoekopdracht aanpassen

Wijzig `config.json` (dat kan direct op GitHub met het potloodje):

| Veld | Betekenis |
|---|---|
| `max_prijs_euro` / `min_prijs_euro` | Prijsgrenzen. |
| `min_bouwjaar` / `max_kilometerstand` | Bijvoorbeeld `2021` en `80000`. `null` betekent geen filter. |
| `postcode` / `straal_km` | Het zoekgebied. Geldt voor alle bronnen. |
| `titel_moet_bevatten` | Woorden die in de titel moeten staan. |
| `moet_een_van_bevatten` | Minstens één van deze woorden moet in de advertentie staan. |
| `uitsluiten` | Advertenties met deze woorden in de titel worden overgeslagen. |
| `autoscout24` | `merk` en `model` zoals in de URL van AutoScout24. `brandstof` `"2"` = elektro/benzine (hybride). |
| `viabovag` | `pad` en `brandstof` zoals in de URL van viaBOVAG, en de `plaats` voor de afstand. viaBOVAG kent alleen vaste filterstappen; de bot filtert daarna zelf precies op jouw grenzen. |
| `gaspedaal` | Staat uit, omdat Gaspedaal de servers van GitHub blokkeert. |
| `marktplaats` | Staat standaard uit. Zet `"aan": true` als je ook particuliere verkopers wilt zien. |

Een andere auto zoeken, bijvoorbeeld een Toyota Yaris hybride? Pas `naam`, `titel_moet_bevatten`, de AutoScout-`merk`/`model` (`toyota`/`yaris`) en het viaBOVAG-`pad` (`merk-toyota/model-yaris`) aan.

Wil je opnieuw een volledig overzicht ontvangen? Verwijder dan `state.json`.

## Als het niet werkt

- **Eén bron werkt niet**: de andere bron blijft gewoon doorzoeken. Mislukt een bron drie keer achter elkaar, dan krijg je een ⚠️-bericht in Telegram. Waarschijnlijk blokkeert de site dan de servers van GitHub of is de site veranderd.
- **Rood kruisje bij Actions**: alle bronnen zijn mislukt. Open de run om de log te bekijken; GitHub stuurt je dan ook een e-mail.
- **De push van `state.json` mislukt**: zet onder *Settings → Actions → General → Workflow permissions* de optie op *Read and write*.
- **Lokaal testen** kan met `python occasion_alert.py --dry-run`. De berichten verschijnen dan alleen in je terminal en er wordt niets verstuurd of opgeslagen. Met `--test-telegram` stuur je één testbericht; daarvoor moeten de twee secrets als omgevingsvariabelen zijn ingesteld.

De Gaspedaal-link opent de zoekresultaten met die auto gemarkeerd. Van daaruit klik je door naar de site van de verkoper.

Let op: GitHub zet geplande workflows in een publieke repository uit na 60 dagen zonder activiteit in de repository. Je krijgt dan een e-mail en kunt de workflow met één klik weer aanzetten.
