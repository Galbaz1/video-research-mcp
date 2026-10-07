# Video Research: van probleem naar oplossing

Nederlandse tekstversie van de [interactieve gids](https://galbaz1.github.io/video-research-mcp/guide/).
Dit is de RC6/RC4-kandidaatbron: publicatie en installatiecontrole staan nog open.
Bronlinks gebruiken de toekomstige vaste tag `v0.8.0-rc.6` en werken na publicatie.

De kernserver heeft 120 tools; de apart aangesloten explainer- en agentservers
hebben 39 en twee tools. Het pakket bevat 24 skills. Begin met
[installatie en configuratie](https://github.com/Galbaz1/video-research-mcp/blob/main/docs/tutorials/GETTING_STARTED.md).
Kies hieronder je probleem, controleer de voorwaarden en volg de stappen.

Stock zoeken/downloaden is niet aangesloten. Lokale ASR-intaketiming en de
behouden renderer-timingfout blijven open. Providerkwaliteit, volledige
securityreview en brede vergelijkende acceptatie zijn niet vastgesteld.
De HTTP-beeld/video-routes vereisen geen upstream CLI; andere pipelinefuncties
hebben hun eigen voorwaarden. Modelleerresultaten controleer je tegen de bron.

Alle exacte ingangen staan in [catalog.json](catalog.json); routes in
[journeys.json](journeys.json). [Engelse documentatie](../README.md) ·
[Probleem melden](https://github.com/Galbaz1/video-research-mcp/issues).

## Een video begrijpen

**Probleem:** Wat zegt deze video over mijn vraag?

**Resultaat:** Een gerichte analyse met bronmomenten, onzekerheden en vervolgvragen.

**Nodig:** Kernserver en Gemini; YouTube Data API alleen als je metadata wilt ophalen.

**Eerste prompt:**

```text
Analyseer deze video: <YouTube-URL>. Leg uit hoe <onderwerp> werkt. Verwijs naar bronmomenten, benoem wat niet zichtbaar is en stel twee vervolgvragen.
```

- **Kies de bron.** Gebruik metadata bij een YouTube-video; geef een lokaal bestand direct aan de analyseroute. [video_metadata](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube.py#L81)
- **Analyseer gericht.** Gebruik video_analyze voor één bron; kies windows bij een lang bestand of batch voor meerdere lokale bestanden. Batch selecteert lokaal, maar verstrekt de videobestanden aan Gemini voor mogelijk betaalde analyse. [video_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L117), [video_analyze_windows](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_windows.py#L23), [video_batch_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_batch.py#L31)
- **Vraag door.** Maak alleen bij meerdere vragen een sessie en hergebruik die context. [video_create_session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L426), [video_continue_session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L550)

## Spraak naar tekst omzetten

**Probleem:** Ik wil een transcript met tijdstempels.

**Resultaat:** Ondertitel- of transcriptieregels met herkomst, export en behouden gedeeltelijke resultaten.

**Nodig:** Lokale bron en eventuele ondertitels; FFmpeg/ffprobe voor audio. ASR vraagt een expliciete backend. Lokale ASR heeft nog geen gekwalificeerde totale intake-deadline.

**Eerste prompt:**

```text
Maak een transcript van <bestand>. Gebruik eerst mijn ondertitels. Toon tijdstempels en ontbrekende stukken. Vraag toestemming en noem de backend vóór ASR.
```

- **Controleer bron en audio.** Inspecteer het lokale bestand en bepaal welk interval nodig is. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L28)
- **Kies ondertitels of ASR.** Ondertitels gaan voor. Modelwoorden en sprekerlabels blijven interpretaties. [audio_transcribe](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/audio_transcribe.py#L27)
- **Bewaar alleen als gewenst.** Neem het transcript op als bron voor later onderzoek. [source_ingest](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/ingestion.py#L36)

## Een vraag beantwoorden met bronnen

**Probleem:** Ik wil een controleerbaar antwoord op een afgebakende vraag.

**Resultaat:** Een antwoord met bronverwijzingen, tegenargumenten en open vragen.

**Nodig:** Gemini voor planning en synthese; zoekproviders alleen voor de gekozen zoekroute.

**Eerste prompt:**

```text
Onderzoek <vraag> voor <doelgroep>. Begrens tot <periode>. Maak eerst een plan, zoek primaire bronnen en onderscheid bronfeiten, interpretatie en onbekenden.
```

- **Begrens de vraag.** Een plan start zelf geen onderzoek. [research_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research.py#L119)
- **Verzamel bronnen.** Kies Gemini Search of een geconfigureerde zoekprovider en lees de relevante pagina’s. [web_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search.py#L24), [web_search_provider](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L26), [web_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L46)
- **Werk het antwoord uit.** research_execute kan aangeleverde of opgehaalde bronnen gebruiken. research_deep synthetiseert en haalt zelf geen nieuwe bronnen op. [research_execute](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research_execute.py#L24), [research_deep](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research.py#L39), [research_assess_evidence](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research.py#L177)

## Wetenschappelijke literatuur verkennen

**Probleem:** Welke papers en tegenbevindingen passen bij mijn vraag?

**Resultaat:** Een begrensde literatuurlijst en vergelijking van daadwerkelijk gelezen bronnen.

**Nodig:** Semantic Scholar voor metadata; Gemini voor documentanalyse.

**Eerste prompt:**

```text
Zoek papers over <vraag>. Geef een selectie met DOI of paper-ID. Scheid metadata van gelezen volledige teksten en vergelijk methode en beperkingen.
```

- **Zoek papers.** Zoek titels, auteurs en publicatiemetadata. [research_paper_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L49), [research_author_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L233)
- **Volg relevante verwijzingen.** Lees details, citaties en aanbevelingen voor geselecteerde papers. [research_paper_details](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L106), [research_paper_citations](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L141), [research_paper_recommendations](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L191)
- **Lees de volledige tekst.** Geef beschikbare documenten expliciet mee; metadata is geen gelezen paper. [research_document](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research_document.py#L55)

## Een document uitlezen en vergelijken

**Probleem:** Ik wil weten wat mijn documenten werkelijk onderbouwen.

**Resultaat:** Bronpassages met pagina of locatie en een afzonderlijke vergelijking.

**Nodig:** Originele bestanden; afzonderlijk geïnstalleerde Poppler (pdftotext en pdfimages op PATH) voor ingebouwde PDF-extractie met source_ingest, niet gebundeld in het pakket. Docling is optioneel. Gemini voor interpretatie.

**Eerste prompt:**

```text
Lees <documenten>. Bewaar paginaverwijzingen. Vergelijk wat ze zeggen over <vraag> en toon passages naast de interpretatie.
```

- **Lees de originele bron.** Bewaar de bronidentiteit en locaties; begin niet met een los opnieuw geschreven document. Controleer de installatievoorwaarden van source_ingest: https://github.com/Galbaz1/video-research-mcp/blob/019c59eafa70315f9f751227eef168bc22ec818e/docs/integrations/source-ingestion.md. [source_ingest](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/ingestion.py#L36)
- **Controleer de extractie.** Lees de relevante pagina’s of elementen opnieuw. [source_ingest_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/ingestion.py#L67)
- **Vergelijk inhoud.** Kies gezamenlijke documentanalyse of een specifiek outputschema. [content_batch_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/content_batch.py#L174), [content_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/content.py#L242), [research_document](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research_document.py#L55)

## Gebeurtenissen in beeld en geluid vinden

**Probleem:** Waar in deze opname gebeurt <gebeurtenis>?

**Resultaat:** Ondersteunde tijdsintervallen met bronbeelden of audiovensters en zichtbare ontbrekende dekking.

**Nodig:** Lokale media, FFmpeg/ffprobe en Gemini voor de geselecteerde AV-analyse.

**Eerste prompt:**

```text
Zoek <gebeurtenis> in <bestand> tussen <begin> en <eind>. Geef de ondersteunende beelden en audio aan. Meld onzekerheid en gemiste dekking.
```

- **Inspecteer het interval.** Meet de bron en bekijk het storyboard. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L28), [video_storyboard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_scenes.py#L66)
- **Kies één analyse.** Caption, count, ground en music zijn alternatieven voor verschillende vragen. [media_caption_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L48), [media_count_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L64), [media_ground_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L83), [media_analyze_music](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L99)
- **Controleer bronmomenten.** Bekijk frames of exporteer een fragment. Een modelschatting is geen fysiek geverifieerde telling. [video_frames](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L120), [video_clip_export](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L132)

## Een afbeelding lezen of bewerken

**Probleem:** Ik wil tekst, objecten of een uitsnede uit dit beeld.

**Resultaat:** Een brongebonden OCR-resultaat, modelinterpretatie of deterministische bewerking.

**Nodig:** Pillow; lokale OCR vraagt Tesseract of Apple Vision. Vision en segmentatie vragen een afzonderlijke provider.

**Eerste prompt:**

```text
Lees <afbeelding>. Begin met een inspecteerbare weergave. Gebruik OCR voor tekst en label modelinterpretaties apart. Bewaar het origineel bij een uitsnede.
```

- **Bekijk de bron.** Lever echte pixels; een modelbeschrijving staat daar los van. [image_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L50)
- **Kies OCR of vision.** Lokale OCR en model-OCR zijn aparte routes; segmentatie vraagt een externe dienst. [image_ocr](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L105), [vision_ocr](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/vision.py#L41), [vision_chat](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/vision.py#L23), [image_segment](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/segmentation.py#L27)
- **Bewerk indien nodig.** Crop en image_edit zijn deterministische bewerkingen; controleer het manifest. [image_crop](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media.py#L37), [image_edit](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L43), [image_manifest_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L76)

## Bestaande footage monteren

**Probleem:** Ik wil bestaande clips in een korte montage gebruiken.

**Resultaat:** Een gecontroleerde hard-cutmontage met goedgekeurde bronmomenten.

**Nodig:** Lokale clips, FFmpeg/ffprobe en toegang tot de bronbestanden.

**Eerste prompt:**

```text
Maak een montageplan voor <clips> van ongeveer <duur>. Toon eerst scènepreviews. Monteer pas na mijn goedkeuring en controleer audio en volledige decode.
```

- **Bekijk scènes.** Detecteer cuts en maak een storyboard. [video_detect_scenes](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_scenes.py#L42), [video_storyboard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_scenes.py#L66)
- **Bereid de montage voor.** De prepare-route maakt previews; leg de gekozen momenten expliciet vast. [media_edit_footage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/footage_edit.py#L29)
- **Assembleer na goedkeuring.** Gebruik dezelfde bron- en plangegevens; lees de werkelijke uitkomst. [media_edit_footage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/footage_edit.py#L29), [job_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/jobs.py#L19)

## Van onderzoek naar een explainer

**Probleem:** Ik wil een video maken van onderbouwd onderzoek.

**Resultaat:** Een goedgekeurd plan, gebonden script en een gerenderde video met afzonderlijke inhoudscontrole.

**Nodig:** Aparte explainercompanion. Upstream video_explainer CLI voor de gekozen generatiestappen; renderer, Node en FFmpeg/ffprobe. Providers en sleutels per generatieactie.

**Eerste prompt:**

```text
Maak een explainerplan voor <onderwerp> op basis van <bronnen>. Controleer de beschikbare companion en renderer. Laat me plan en claims goedkeuren voordat je genereert of rendert.
```

- **Controleer en maak een project.** Lees prerequisites en maak een project in de geconfigureerde omgeving. [explainer_doctor](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/doctor.py#L17), [explainer_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L27)
- **Plan en bind de inhoud.** Geef bronmateriaal mee, keur het plan goed en kies één generatiestap. [explainer_inject](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L55), [explainer_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/planning.py#L20), [explainer_step](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/pipeline.py#L164)
- **Render en beoordeel.** Volg de renderjob en controleer claims, leesbaarheid en audio apart. De factchecktool verwerkt aangeleverde waarnemingen. [explainer_render_start](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_jobs.py#L70), [explainer_render_poll](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_jobs.py#L150), [explainer_render_factcheck](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_factcheck.py#L25)

## Een kleine interactieve les maken

**Probleem:** Ik wil een begrensde diagramles met vertelling.

**Resultaat:** Een zelfstandige HTML-les en lokale video binnen het vaste drie-scènedomein.

**Nodig:** Educational-explainer skill, lesson.py, lokaal audio-/bronmateriaal en media-afhankelijkheden. Alleen de beschreven drie-scènevoorbeelden.

**Eerste prompt:**

```text
Maak een les binnen het educational-explainer-domein over <ondersteund voorbeeld>. Gebruik mijn vertelling. Valideer eerst de specificatie en controleer de HTML en video afzonderlijk.
```

- **Kies een ondersteund voorbeeld.** De skill beschrijft de eindige lesdomeinen; vrije lessen vragen een andere productieroute. [educational-explainer](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/educational-explainer/SKILL.md#L1)
- **Valideer en bouw.** Gebruik de CLI validate en build met exacte bron- en audio-invoer. [education-lesson](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/educational-explainer/scripts/lesson.py#L1)
- **Controleer het resultaat.** Gebruik check voor bron-/uitvoerbinding; leesbaarheid en verstaanbaarheid vragen eigen beoordeling. [education-lesson](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/educational-explainer/scripts/lesson.py#L1)

## Van demonstratie naar instructie

**Probleem:** Ik wil de stappen uit een opname hergebruiken.

**Resultaat:** Brongebonden instructies of een overdraagbare skill met expliciete ontbrekende informatie.

**Nodig:** Gemini voor interpretatie; lokale frames voor een PDF. De video-to-skill validators voeren de taak niet uit.

**Eerste prompt:**

```text
Beschrijf de stappen uit <opname> voor <taak>. Verwijs naar bronmomenten, vul ontbrekende handelingen niet in en maak daarna een herbruikbare instructie.
```

- **Onderzoek de demonstratie.** Bekijk de relevante bronmomenten. [video_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L117), [media_ground_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L83)
- **Maak leesbare instructies.** De PDF-route gebruikt echte bronframes; de skillroute bewaart stappen en brongegevens. [video_note_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_note.py#L22), [video-to-skill](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/video-to-skill/SKILL.md#L1)
- **Valideer vóór verpakken.** Structuur en herkomstcontrole bewijzen geen geslaagde uitvoering van de beschreven taak. [video-skill-validate](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/scripts/validate_video_skill.py#L1), [video-skill-package](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/scripts/package_video_skill.py#L1)

## Eerder onderzoek terugvinden

**Probleem:** Ik wil zoeken in mijn opgeslagen kennis.

**Resultaat:** Relevante opgeslagen objecten en bronverwijzingen; optionele synthese blijft modeloutput.

**Nodig:** WEAVIATE_URL, toegang tot de gekozen collecties en de zoek-/embeddingconfiguratie: hybrid/semantic vragen vectorisatie, keyword gebruikt BM25. Gemini-samenvatting en Cohere-reranking zijn afzonderlijke optionele providerstappen; QueryAgent is optioneel voor een antwoord.

**Eerste prompt:**

```text
Zoek eerder onderzoek over <onderwerp> in <collectie>. Geef de bronobjecten terug. Maak alleen een samenvatting als die optie beschikbaar is en label haar als interpretatie.
```

- **Bekijk collecties.** Lees beschikbare schema’s en aantallen. [knowledge_schema](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/schema.py#L25), [knowledge_stats](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/retrieval.py#L101)
- **Zoek en lees de bronobjecten.** Gebruik knowledge_search, fetch en related; knowledge_query is verouderd. Zonder Weaviate-configuratie geeft search lege resultaten; ook zoekfouten kunnen resultaten beperken. Dat bewijst niet dat er geen opgeslagen kennis is. [knowledge_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/search.py#L30), [knowledge_fetch](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/retrieval.py#L166), [knowledge_related](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/retrieval.py#L35)
- **Vraag alleen indien gewenst een antwoord.** knowledge_ask vraagt de optionele QueryAgent. [knowledge_ask](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/agent.py#L73)

## Publieksreacties begrijpen

**Probleem:** Welke vragen of bezwaren staan in deze reacties?

**Resultaat:** Een begrensde steekproef met exacte citaten en transparante kenmerken.

**Nodig:** YouTube Data API voor acquisitie; audience_manage bewaart en analyseert aangeleverde reacties lokaal.

**Eerste prompt:**

```text
Lees een begrensde selectie reacties op <video>. Groepeer vragen en bezwaren, geef exacte citaten en behandel de steekproef niet als het hele publiek.
```

- **Bekijk kanaalcontext.** Lees alleen de benodigde metadata of uploadpagina. [youtube_channel_inspect](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube_channels.py#L17), [youtube_channel_catalog](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube_channels.py#L38)
- **Haal de steekproef op.** Behoud de gekozen omvang en sortering. [video_comments](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube.py#L122)
- **Bewaar en vergelijk.** Werk met brongebonden citaten; inferentie via een model is een afzonderlijke keuze. [audience_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/audience.py#L23)

## Ruimtelijke visualisatie verkennen · experimenteel

**Probleem:** Ik wil een ruimtelijke schets bij bronbeelden.

**Resultaat:** Een gekozen externe route met expliciete voorwaarden; geometrie en fysieke juistheid vragen eigen controle.

**Nodig:** Afzonderlijk geconfigureerde externe bron en runtime. Deze routes zijn geen algemeen gekwalificeerde native voorziening van RC3.

**Eerste prompt:**

```text
Verken een ruimtelijke visualisatie voor <bronbeelden>. Controleer eerst welke externe route werkelijk beschikbaar is. Benoem geometrische aannames en begin geen lokale modeluitvoering zonder geschikte runtime.
```

- **Kies bronbeelden.** Haal de benodigde frames op. [video_frames](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L120)
- **Controleer de externe route.** De spatial skill en adapter zijn experimenteel; aanwezigheid is geen uitvoeringsbewijs. [spatial-video-analysis](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/spatial-video-analysis/SKILL.md#L1), [spatial-session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/scripts/spatial_session.py#L1)
- **Kies een visualisatieomgeving.** Blender en FreeCAD hebben afzonderlijke prerequisites. [research-visualization-blender](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/research-visualization-blender/SKILL.md#L1), [research-visualization-freecad](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/research-visualization-freecad/SKILL.md#L1)

## Hardwaregedrag simuleren · experimenteel

**Probleem:** Ik wil een simulator lezen of aanpassen.

**Resultaat:** Simulatiewaarden en vastgelegde wijzigingen; geen fysieke hardwarewaarneming.

**Nodig:** Expliciete simulatorregistratie en passende toestemming voor wijzigingen.

**Eerste prompt:**

```text
Bekijk <simulator>. Lees eerst apparaten, metadata en limieten. Stel een wijziging voor en voer die pas uit met de vereiste toestemming.
```

- **Lees apparaten en limieten.** Discovery beschrijft de simulator. [mhs_discover](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L66), [mhs_meta_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L107)
- **Inspecteer de toestand.** Health en read bewijzen geen fysieke aanwezigheid. [mhs_health_check](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L88), [mhs_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L123)
- **Wijzig alleen expliciet.** Write en reset veranderen simulatorstate en vragen de toepasselijke toestemming. [mhs_write](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L141), [mhs_reset](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L170)

## Installeren en beschikbaarheid controleren

**Probleem:** Welke onderdelen heb ik nodig voor mijn taak?

**Resultaat:** Een gekozen kernserver of companion met gecontroleerde configuratie.

**Nodig:** Python ≥3.11 en uv/uvx voor MCP; Node ≥22 voor de npm-installer. De native Codex-plugin koppelt de kernserver; companions verbind je apart.

**Eerste prompt:**

```text
Controleer welke video-research-tools en skills verbonden zijn. Toon ontbrekende configuratie voor <taak>, zonder sleutels te tonen. Installeer of wijzig niets zonder mijn opdracht.
```

- **Kies de ingang.** Codex heeft 24 verpakte skills. De Claude-installer heeft 24 skillentries plus ondersteunende resources. [native-codex-plugin](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/plugin.json#L1), [plugin-installer](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/bin/install.js#L1)
- **Lees configuratie.** provider_capabilities beschrijft routes en test geen providerverbinding. [infra_configure](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/infra.py#L101), [provider_capabilities](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/text_provider.py#L43)
- **Volg eigen werk.** job_status leest ondersteunde kernjobs. Voor gegenereerde media: companion image finalize/poll of video poll met een expliciete operatie; job_cancel is alleen voor kern-videojobs. [job_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/jobs.py#L19), [job_cancel](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/jobs.py#L50)

## De herkomst van een beeld zoeken

**Probleem:** Waar komt dit beeld of fragment vandaan?

**Resultaat:** Kandidaatpagina’s met afzonderlijke visuele en tekstuele controle.

**Nodig:** Een exact lokaal PNG-frame; ingeschakelde Serper-route en SERPER_API_KEY. Uitvoering van reverse_search_frame uploadt het geselecteerde PNG altijd publiek naar Uguu, controleert de hosted bytes en stuurt daarna de URL naar Serper Lens. Concrete toestemming voor publicatie, inzending en mogelijk betaald gebruik is vereist. Een dry-run publiceert niets.

**Eerste prompt:**

```text
Zoek de herkomst van <beeld>. Geef kandidaten met bronpagina’s. Publiceer mijn beeld niet zonder toestemming en verifieer matches aan uiterlijk, tekst en context.
```

- **Kies een exact beeld.** Haal één bronframe op. [video_frame](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L81)
- **Zoek kandidaten.** Kies een lokale dry-run zonder upload of uitvoering van reverse_search_frame met publieke PNG-upload naar Uguu, bytecontrole en daaropvolgende URL-inzending naar Serper Lens. web_search_provider is een afzonderlijke tekstzoekroute; die vervangt deze framezoekroute niet. [reverse_search_frame](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L66), [web_search_provider](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L26)
- **Controleer de pagina’s.** Een zoekmatch is nog geen vastgestelde oorsprong. [web_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L46)

## Vertelling en visuele assets maken

**Probleem:** Ik wil audio of beelden voor een video produceren.

**Resultaat:** Providerartefacten die nog op inhoud, kwaliteit en samenhang beoordeeld moeten worden.

**Nodig:** Kernserver genereert geen beelden/TTS/clips. Kies de aparte HTTP-companionroute hieronder of een afzonderlijk beschikbare providerworkflow. CLI-narratie/muziek/SFX vragen upstreamvoorwaarden.

**Eerste prompt:**

```text
Maak een assetplan voor <video>. Controleer echte generators, invoer en kosten vóór uitvoering. Begin met één voorbeeld en beoordeel beeld en audio voordat je opschaalt.
```

- **Kies een beschikbare generator.** Deze skills begeleiden gebruik; ze voegen geen generator toe. [tts-production](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/tts-production/SKILL.md#L1), [image-generation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/image-generation/SKILL.md#L1), [video-generation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/video-generation/SKILL.md#L1)
- **Gebruik de companion indien aangesloten.** Narratie vraagt een goedgekeurd gebonden script; muziek en SFX gebruiken gekozen upstream routes. [explainer_narration](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L77), [explainer_music](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L53), [explainer_sound](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L25)
- **Inspecteer en meng.** Meet bronmedia en meng bestaande projectaudio afzonderlijk. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L28), [audio_dsp_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/audio_dsp.py#L29), [explainer_audio_mix](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio_mix.py#L18)

## Bestaande materialen samenstellen

**Probleem:** Ik heb eigen beelden en clips en wil daar een video van maken.

**Resultaat:** Een lokale MP4 volgens een vastgelegde volgorde en timing.

**Nodig:** Aparte explainercompanion, geconfigureerd project, lokale materialen met gebruiksverklaringen en FFmpeg/ffprobe. Stock zoeken/downloaden is niet aangesloten.

**Eerste prompt:**

```text
Stel mijn bestaande materialen <bestanden> samen tot <duur>. Gebruik alleen deze bestanden. Leg volgorde, timing en gebruiksverklaringen vast en controleer de volledige MP4.
```

- **Maak of kies een project.** Gebruik een bestaande projectomgeving; create gebruikt de upstream CLI. [explainer_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L27), [explainer_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L112)
- **Leg het plan en de materialen vast.** Bind scènes, script en de expliciet aangeleverde bronnen. [explainer_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/planning.py#L20)
- **Assembleer en controleer.** Gebruik lokale materialen; deze route zoekt of downloadt geen stock. [explainer_materials_assemble](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/materials.py#L18)

## Bronnen en notities lokaal hergebruiken

**Probleem:** Ik wil passages uit mijn eigen bronnen terugvinden en delen.

**Resultaat:** Lokale collecties, citeerbare passages, notities en leesbare exports.

**Nodig:** Bestaande lokale bronrecords; geen Weaviate of modelprovider nodig voor deze recordbewerkingen.

**Eerste prompt:**

```text
Orden <bronrecords> in een collectie. Zoek passages over <vraag>, bewaar notities met exacte verwijzingen en exporteer een leesbaar overzicht.
```

- **Orden en zoek.** Werk met de aangeleverde bronrecords en een begrensde zoekvraag. [collections_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/collections.py#L26), [corpus_retrieve](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/corpus.py#L27)
- **Bewaar context.** Koppel notities of wiki-revisies aan exacte passages. [notebook_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/notebooks.py#L23), [wiki_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/wiki.py#L27)
- **Deel brongegevens.** Controleer welke brongegevens geschikt zijn om te delen. [evidence_export](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/evidence_export.py#L24)

## Een video vertalen · experimenteel

**Probleem:** Ik wil gesproken vertaling bij mijn video.

**Resultaat:** Een brongebonden vertaalplan en mogelijke render; stemkwaliteit en beluistering blijven afzonderlijke controles.

**Nodig:** Optionele geconfigureerde dubbingservice voor stems, VAD en TTS; lokale media en FFmpeg/ffprobe. Goedgekeurde stemreferenties.

**Eerste prompt:**

```text
Bereid vertaling van <video> naar <taal> voor. Controleer eerst de dubbingservice. Maak alleen een analyse en plan; vraag goedkeuring vóór synthese en beoordeel de uiteindelijke audio.
```

- **Controleer en bereid voor.** Ontbrekende service is een stopvoorwaarde. [check_dubbing_service](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L32), [prepare_video_translation_project](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L43)
- **Controleer het vertaalplan.** Werk met exacte bronmomenten, sprekertoewijzingen en slots. [get_video_translation_state](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L152), [validate_video_translation_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L169)
- **Render na goedkeuring.** Technische levering en beluisterde stemkwaliteit zijn aparte uitkomsten. [render_video_translation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L187), [validate_video_translation_delivery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L212)

## Filmcommentaar maken

**Probleem:** Ik wil uitleg bij geselecteerde filmfragmenten.

**Resultaat:** Een goedgekeurd commentaarplan, afzonderlijk uitgevoerde segmentgroepen en gecontroleerde levering.

**Nodig:** Aparte explainercompanion; lokale bronvideo, FFmpeg/ffprobe en een geschikte uitvoerroute voor de goedgekeurde segmentgroepen.

**Eerste prompt:**

```text
Bereid commentaar voor bij <video> over <vraag>. Leg exacte bronmomenten en vertelling vast. Laat me het plan en de segmentgroepen goedkeuren voordat je deelrenders maakt.
```

- **Maak en controleer het plan.** Koppel het project aan de exacte bronvideo. [commentary_prepare](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L39), [commentary_validate_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L87)
- **Leg segmentgroepen vast.** Approve geeft uitvoeringsscope; de tool voert geen deelrender uit. Die uitvoering vraagt een afzonderlijke geschikte route. [commentary_freeze_shards](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L105), [commentary_approve_shard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L125)
- **Voeg bestaande deelrenders samen.** Pas na geslaagde deeluitkomsten volgt assemble en leveringcontrole. [commentary_assemble](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L143), [commentary_validate_delivery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L166)

## Een afbeelding maken, bewerken of vertalen

**Probleem:** Ik wil een nieuw beeld, een edit met referenties of vertaalde tekst in een beeld.

**Resultaat:** Lokaal opgeslagen PNG/JPG met bronpins, hashes en volledige rasterdecode; semantiek en stijl beoordeel je apart.

**Nodig:** Aparte explainercompanion met generation-extra; regionale DashScope-configuratie en een bestaand project. Exacte script-/scènepins en actuele gepinde prijs-, toegangs- en offertedeclaraties. Werkelijke toestemming voor inzending en kosten is apart vereist. Pillow/HTTPX via generation-extra. Text/edit: qwen-image-2.0-pro. Vertaling: qwen-mt-image in Beijing, reeds publieke HTTPS-bron; Chinees of Engels aan één kant. Geen upstream CLI.

**Eerste prompt:**

```text
Kies tekst, edit of vertaling voor <beeldtaak>. Controleer companion, regio, bronnen en actuele offerte. Leg bronpins en kosten vast; vraag mijn echte toestemming vóór inzending. Bewaar job-ID en controleer de opgeslagen bestanden.
```

- **Bereid bron en offerte voor.** Volg https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/docs/integrations/image-generation.md. Pin script/scène, referenties en actuele prijs/toegang/offerte. spend_authorized=true is een invoerbevestiging, geen menselijke bevoegdheid. [explainer_image_generation_submit](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L17)
- **Bewaar of herstel expliciet.** Finalize voor synchrone beelden; poll voor vertaling/herstel. Elke fetch krijgt een operation_id, dezelfde principal en authorize=true. Gebruik geen core job_status. [explainer_image_generation_finalize](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L57), [explainer_image_generation_poll](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L37)
- **Controleer uitkomst en grenzen.** Bekijk assets, hashes en decode; betaalde providerkwaliteit en identiteit/stijl blijven ongekwalificeerd. Bij UNKNOWN eerst oorspronkelijke taak reconciliëren. Synchrone cancel is niet ondersteund. [explainer_image_generation_cancel](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L77)

## Een korte video maken uit tekst of frames

**Probleem:** Ik wil een synthetische clip met tekst, een eerste frame of eerste plus laatste frame.

**Resultaat:** Een opgeslagen MP4 met script-/scène-identiteit, bron-/verzoekhashes en volledige decode; beeld- en geluidskwaliteit blijven apart.

**Nodig:** Aparte explainercompanion met generation-extra; regionale DashScope-configuratie en een bestaand project. Exacte script-/scènepins en actuele gepinde prijs-, toegangs- en offertedeclaraties. Werkelijke toestemming voor inzending en kosten is apart vereist. FFmpeg/ffprobe; Wan text/frame-modellen en expliciete video-endpointconfiguratie. Geen upstream CLI. S2V/HappyHorse zijn afzonderlijke optionele opvolgers zonder geaccepteerde kwalificatie hier.

**Eerste prompt:**

```text
Bereid één korte synthetische clip voor over <scène>. Kies tekst of eerste/laatste frame en pin script, scène en referenties. Controleer quote en grenzen. Vraag toestemming vóór inzending; inspecteer de volledig gedecodeerde MP4.
```

- **Begrens en dien eenmaal in.** Volg https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/docs/integrations/generation.md. Tekst/frame: gehele 2–15 seconden, 720P/1080P, toegelaten ratio. Framepins en verwachte dimensies zijn expliciet. spend_authorized is geen werkelijke kostenbevoegdheid. [explainer_generation_submit](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/generation.py#L17)
- **Fetch en controleer expliciet.** Eén poll per operation_id/principal/authorize; geen achtergrondloop en geen core job_status. Alleen toegelaten HTTPS-uitvoer, opgeslagen hashes, dimensies/duur en volledige decode. [explainer_generation_poll](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/generation.py#L37)
- **Herstel of annuleer gecontroleerd.** UNKNOWN vraagt reconciliatie van de oorspronkelijke taak, geen nieuw logical_job_id. Cancel alleen na verse PENDING en aparte bevestiging. Provider/creatieve kwaliteit, volledige securityreview en programma-acceptatie blijven open. [explainer_generation_cancel](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/generation.py#L57)
