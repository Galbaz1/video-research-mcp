# Video Research: van probleem naar oplossing

Nederlandse tekstversie van de [interactieve gids](index.html) bij de **v0.8.0-rc.4**-broninventaris.
Release- en bronlinks gebruiken de vaste tag. Controleer de release en registry vóór installatie.

De kernserver heeft 120 MCP-tools; de afzonderlijk aangesloten explainer- en agentservers hebben 32 en 2 tools. Het pakket bevat 24 skills. De Claude-installer heeft 24 skillentries plus ondersteunende resources. Bekijk [installatie en configuratie](https://github.com/Galbaz1/video-research-mcp/blob/main/docs/tutorials/GETTING_STARTED.md) vóór gebruik.

Provider- en runtimevoorwaarden staan per route. Modelinterpretaties zijn geen onafhankelijk geverifieerde feiten. Stock zoeken/downloaden is niet aangesloten; bestaande materialen samenstellen is beschikbaar. Lokale ASR heeft nog geen gekwalificeerde deadline voor de totale intake. Brede vergelijkende kwalificatie is onvolledig. De RC4-bron bevat de broncorrecties; controleer publicatie en de geïnstalleerde versie afzonderlijk.

Alle exacte ingangen en releasebronnen staan in [catalog.json](catalog.json).

## Een video begrijpen

**Probleem:** Wat zegt deze video over mijn vraag?

**Resultaat:** Een gerichte analyse met bronmomenten, onzekerheden en vervolgvragen.

**Nodig:** Kernserver en Gemini; YouTube Data API alleen als je metadata wilt ophalen.

**Eerste prompt:**

```text
Analyseer deze video: <YouTube-URL>. Leg uit hoe <onderwerp> werkt. Verwijs naar bronmomenten, benoem wat niet zichtbaar is en stel twee vervolgvragen.
```

- **Kies de bron.** Gebruik metadata bij een YouTube-video; geef een lokaal bestand direct aan de analyseroute. [video_metadata](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/youtube.py#L81)
- **Analyseer gericht.** Gebruik video_analyze voor één bron; kies windows bij een lang bestand of batch voor meerdere lokale bestanden. Batch selecteert lokaal, maar verstrekt de videobestanden aan Gemini voor mogelijk betaalde analyse. [video_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video.py#L117), [video_analyze_windows](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_windows.py#L23), [video_batch_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_batch.py#L31)
- **Vraag door.** Maak alleen bij meerdere vragen een sessie en hergebruik die context. [video_create_session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video.py#L426), [video_continue_session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video.py#L550)


## Spraak naar tekst omzetten

**Probleem:** Ik wil een transcript met tijdstempels.

**Resultaat:** Ondertitel- of transcriptieregels met herkomst, export en behouden gedeeltelijke resultaten.

**Nodig:** Lokale bron en eventuele ondertitels; FFmpeg/ffprobe voor audio. ASR vraagt een expliciete backend. Lokale ASR heeft nog geen gekwalificeerde totale intake-deadline.

**Eerste prompt:**

```text
Maak een transcript van <bestand>. Gebruik eerst mijn ondertitels. Toon tijdstempels en ontbrekende stukken. Vraag toestemming en noem de backend vóór ASR.
```

- **Controleer bron en audio.** Inspecteer het lokale bestand en bepaal welk interval nodig is. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_read.py#L28)
- **Kies ondertitels of ASR.** Ondertitels gaan voor. Modelwoorden en sprekerlabels blijven interpretaties. [audio_transcribe](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/audio_transcribe.py#L27)
- **Bewaar alleen als gewenst.** Neem het transcript op als bron voor later onderzoek. [source_ingest](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/ingestion.py#L36)


## Een vraag beantwoorden met bronnen

**Probleem:** Ik wil een controleerbaar antwoord op een afgebakende vraag.

**Resultaat:** Een antwoord met bronverwijzingen, tegenargumenten en open vragen.

**Nodig:** Gemini voor planning en synthese; zoekproviders alleen voor de gekozen zoekroute.

**Eerste prompt:**

```text
Onderzoek <vraag> voor <doelgroep>. Begrens tot <periode>. Maak eerst een plan, zoek primaire bronnen en onderscheid bronfeiten, interpretatie en onbekenden.
```

- **Begrens de vraag.** Een plan start zelf geen onderzoek. [research_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/research.py#L119)
- **Verzamel bronnen.** Kies Gemini Search of een geconfigureerde zoekprovider en lees de relevante pagina’s. [web_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/search.py#L24), [web_search_provider](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/search_provider.py#L26), [web_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/search_provider.py#L46)
- **Werk het antwoord uit.** research_execute kan aangeleverde of opgehaalde bronnen gebruiken. research_deep synthetiseert en haalt zelf geen nieuwe bronnen op. [research_execute](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/research_execute.py#L24), [research_deep](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/research.py#L39), [research_assess_evidence](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/research.py#L177)


## Wetenschappelijke literatuur verkennen

**Probleem:** Welke papers en tegenbevindingen passen bij mijn vraag?

**Resultaat:** Een begrensde literatuurlijst en vergelijking van daadwerkelijk gelezen bronnen.

**Nodig:** Semantic Scholar voor metadata; Gemini voor documentanalyse.

**Eerste prompt:**

```text
Zoek papers over <vraag>. Geef een selectie met DOI of paper-ID. Scheid metadata van gelezen volledige teksten en vergelijk methode en beperkingen.
```

- **Zoek papers.** Zoek titels, auteurs en publicatiemetadata. [research_paper_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/academic.py#L49), [research_author_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/academic.py#L233)
- **Volg relevante verwijzingen.** Lees details, citaties en aanbevelingen voor geselecteerde papers. [research_paper_details](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/academic.py#L106), [research_paper_citations](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/academic.py#L141), [research_paper_recommendations](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/academic.py#L191)
- **Lees de volledige tekst.** Geef beschikbare documenten expliciet mee; metadata is geen gelezen paper. [research_document](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/research_document.py#L55)


## Een document uitlezen en vergelijken

**Probleem:** Ik wil weten wat mijn documenten werkelijk onderbouwen.

**Resultaat:** Bronpassages met pagina of locatie en een afzonderlijke vergelijking.

**Nodig:** Originele bestanden; afzonderlijk geïnstalleerde Poppler (pdftotext en pdfimages op PATH) voor ingebouwde PDF-extractie met source_ingest, niet gebundeld in het pakket. Docling is optioneel. Gemini voor interpretatie.

**Eerste prompt:**

```text
Lees <documenten>. Bewaar paginaverwijzingen. Vergelijk wat ze zeggen over <vraag> en toon passages naast de interpretatie.
```

- **Lees de originele bron.** Bewaar de bronidentiteit en locaties; begin niet met een los opnieuw geschreven document. Controleer de installatievoorwaarden van source_ingest: https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/docs/integrations/source-ingestion.md. [source_ingest](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/ingestion.py#L36)
- **Controleer de extractie.** Lees de relevante pagina’s of elementen opnieuw. [source_ingest_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/ingestion.py#L67)
- **Vergelijk inhoud.** Kies gezamenlijke documentanalyse of een specifiek outputschema. [content_batch_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/content_batch.py#L174), [content_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/content.py#L242), [research_document](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/research_document.py#L55)


## Gebeurtenissen in beeld en geluid vinden

**Probleem:** Waar in deze opname gebeurt <gebeurtenis>?

**Resultaat:** Ondersteunde tijdsintervallen met bronbeelden of audiovensters en zichtbare ontbrekende dekking.

**Nodig:** Lokale media, FFmpeg/ffprobe en Gemini voor de geselecteerde AV-analyse.

**Eerste prompt:**

```text
Zoek <gebeurtenis> in <bestand> tussen <begin> en <eind>. Geef de ondersteunende beelden en audio aan. Meld onzekerheid en gemiste dekking.
```

- **Inspecteer het interval.** Meet de bron en bekijk het storyboard. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_read.py#L28), [video_storyboard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_scenes.py#L66)
- **Kies één analyse.** Caption, count, ground en music zijn alternatieven voor verschillende vragen. [media_caption_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_perceive.py#L48), [media_count_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_perceive.py#L64), [media_ground_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_perceive.py#L83), [media_analyze_music](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_perceive.py#L99)
- **Controleer bronmomenten.** Bekijk frames of exporteer een fragment. Een modelschatting is geen fysiek geverifieerde telling. [video_frames](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_read.py#L120), [video_clip_export](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/image.py#L132)


## Een afbeelding lezen of bewerken

**Probleem:** Ik wil tekst, objecten of een uitsnede uit dit beeld.

**Resultaat:** Een brongebonden OCR-resultaat, modelinterpretatie of deterministische bewerking.

**Nodig:** Pillow; lokale OCR vraagt Tesseract of Apple Vision. Vision en segmentatie vragen een afzonderlijke provider.

**Eerste prompt:**

```text
Lees <afbeelding>. Begin met een inspecteerbare weergave. Gebruik OCR voor tekst en label modelinterpretaties apart. Bewaar het origineel bij een uitsnede.
```

- **Bekijk de bron.** Lever echte pixels; een modelbeschrijving staat daar los van. [image_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_read.py#L50)
- **Kies OCR of vision.** Lokale OCR en model-OCR zijn aparte routes; segmentatie vraagt een externe dienst. [image_ocr](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/image.py#L105), [vision_ocr](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/vision.py#L41), [vision_chat](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/vision.py#L23), [image_segment](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/segmentation.py#L27)
- **Bewerk indien nodig.** Crop en image_edit zijn deterministische bewerkingen; controleer het manifest. [image_crop](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media.py#L37), [image_edit](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/image.py#L43), [image_manifest_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/image.py#L76)


## Bestaande footage monteren

**Probleem:** Ik wil bestaande clips in een korte montage gebruiken.

**Resultaat:** Een gecontroleerde hard-cutmontage met goedgekeurde bronmomenten.

**Nodig:** Lokale clips, FFmpeg/ffprobe en toegang tot de bronbestanden.

**Eerste prompt:**

```text
Maak een montageplan voor <clips> van ongeveer <duur>. Toon eerst scènepreviews. Monteer pas na mijn goedkeuring en controleer audio en volledige decode.
```

- **Bekijk scènes.** Detecteer cuts en maak een storyboard. [video_detect_scenes](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_scenes.py#L42), [video_storyboard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_scenes.py#L66)
- **Bereid de montage voor.** De prepare-route maakt previews; leg de gekozen momenten expliciet vast. [media_edit_footage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/footage_edit.py#L29)
- **Assembleer na goedkeuring.** Gebruik dezelfde bron- en plangegevens; lees de werkelijke uitkomst. [media_edit_footage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/footage_edit.py#L29), [job_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/jobs.py#L19)


## Van onderzoek naar een explainer

**Probleem:** Ik wil een video maken van onderbouwd onderzoek.

**Resultaat:** Een goedgekeurd plan, gebonden script en een gerenderde video met afzonderlijke inhoudscontrole.

**Nodig:** Aparte explainercompanion. Upstream video_explainer CLI voor de gekozen generatiestappen; renderer, Node en FFmpeg/ffprobe. Providers en sleutels per generatieactie.

**Eerste prompt:**

```text
Maak een explainerplan voor <onderwerp> op basis van <bronnen>. Controleer de beschikbare companion en renderer. Laat me plan en claims goedkeuren voordat je genereert of rendert.
```

- **Controleer en maak een project.** Lees prerequisites en maak een project in de geconfigureerde omgeving. [explainer_doctor](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/doctor.py#L17), [explainer_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L27)
- **Plan en bind de inhoud.** Geef bronmateriaal mee, keur het plan goed en kies één generatiestap. [explainer_inject](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L55), [explainer_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/planning.py#L20), [explainer_step](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/pipeline.py#L164)
- **Render en beoordeel.** Volg de renderjob en controleer claims, leesbaarheid en audio apart. De factchecktool verwerkt aangeleverde waarnemingen. [explainer_render_start](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_jobs.py#L70), [explainer_render_poll](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_jobs.py#L150), [explainer_render_factcheck](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_factcheck.py#L25)


## Een kleine interactieve les maken

**Probleem:** Ik wil een begrensde diagramles met vertelling.

**Resultaat:** Een zelfstandige HTML-les en lokale video binnen het vaste drie-scènedomein.

**Nodig:** Educational-explainer skill, lesson.py, lokaal audio-/bronmateriaal en media-afhankelijkheden. Alleen de beschreven drie-scènevoorbeelden.

**Eerste prompt:**

```text
Maak een les binnen het educational-explainer-domein over <ondersteund voorbeeld>. Gebruik mijn vertelling. Valideer eerst de specificatie en controleer de HTML en video afzonderlijk.
```

- **Kies een ondersteund voorbeeld.** De skill beschrijft de eindige lesdomeinen; vrije lessen vragen een andere productieroute. [educational-explainer](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/educational-explainer/SKILL.md#L1)
- **Valideer en bouw.** Gebruik de CLI validate en build met exacte bron- en audio-invoer. [education-lesson](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/educational-explainer/scripts/lesson.py#L1)
- **Controleer het resultaat.** Gebruik check voor bron-/uitvoerbinding; leesbaarheid en verstaanbaarheid vragen eigen beoordeling. [education-lesson](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/educational-explainer/scripts/lesson.py#L1)


## Van demonstratie naar instructie

**Probleem:** Ik wil de stappen uit een opname hergebruiken.

**Resultaat:** Brongebonden instructies of een overdraagbare skill met expliciete ontbrekende informatie.

**Nodig:** Gemini voor interpretatie; lokale frames voor een PDF. De video-to-skill validators voeren de taak niet uit.

**Eerste prompt:**

```text
Beschrijf de stappen uit <opname> voor <taak>. Verwijs naar bronmomenten, vul ontbrekende handelingen niet in en maak daarna een herbruikbare instructie.
```

- **Onderzoek de demonstratie.** Bekijk de relevante bronmomenten. [video_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video.py#L117), [media_ground_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_perceive.py#L83)
- **Maak leesbare instructies.** De PDF-route gebruikt echte bronframes; de skillroute bewaart stappen en brongegevens. [video_note_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_note.py#L22), [video-to-skill](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/video-to-skill/SKILL.md#L1)
- **Valideer vóór verpakken.** Structuur en herkomstcontrole bewijzen geen geslaagde uitvoering van de beschreven taak. [video-skill-validate](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/scripts/validate_video_skill.py#L1), [video-skill-package](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/scripts/package_video_skill.py#L1)


## Eerder onderzoek terugvinden

**Probleem:** Ik wil zoeken in mijn opgeslagen kennis.

**Resultaat:** Relevante opgeslagen objecten en bronverwijzingen; optionele synthese blijft modeloutput.

**Nodig:** WEAVIATE_URL, toegang tot de gekozen collecties en de zoek-/embeddingconfiguratie: hybrid/semantic vragen vectorisatie, keyword gebruikt BM25. Gemini-samenvatting en Cohere-reranking zijn afzonderlijke optionele providerstappen; QueryAgent is optioneel voor een antwoord.

**Eerste prompt:**

```text
Zoek eerder onderzoek over <onderwerp> in <collectie>. Geef de bronobjecten terug. Maak alleen een samenvatting als die optie beschikbaar is en label haar als interpretatie.
```

- **Bekijk collecties.** Lees beschikbare schema’s en aantallen. [knowledge_schema](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/knowledge/schema.py#L25), [knowledge_stats](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/knowledge/retrieval.py#L101)
- **Zoek en lees de bronobjecten.** Gebruik knowledge_search, fetch en related; knowledge_query is verouderd. Zonder Weaviate-configuratie geeft search lege resultaten; ook zoekfouten kunnen resultaten beperken. Dat bewijst niet dat er geen opgeslagen kennis is. [knowledge_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/knowledge/search.py#L30), [knowledge_fetch](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/knowledge/retrieval.py#L166), [knowledge_related](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/knowledge/retrieval.py#L35)
- **Vraag alleen indien gewenst een antwoord.** knowledge_ask vraagt de optionele QueryAgent. [knowledge_ask](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/knowledge/agent.py#L73)


## Publieksreacties begrijpen

**Probleem:** Welke vragen of bezwaren staan in deze reacties?

**Resultaat:** Een begrensde steekproef met exacte citaten en transparante kenmerken.

**Nodig:** YouTube Data API voor acquisitie; audience_manage bewaart en analyseert aangeleverde reacties lokaal.

**Eerste prompt:**

```text
Lees een begrensde selectie reacties op <video>. Groepeer vragen en bezwaren, geef exacte citaten en behandel de steekproef niet als het hele publiek.
```

- **Bekijk kanaalcontext.** Lees alleen de benodigde metadata of uploadpagina. [youtube_channel_inspect](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/youtube_channels.py#L17), [youtube_channel_catalog](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/youtube_channels.py#L38)
- **Haal de steekproef op.** Behoud de gekozen omvang en sortering. [video_comments](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/youtube.py#L122)
- **Bewaar en vergelijk.** Werk met brongebonden citaten; inferentie via een model is een afzonderlijke keuze. [audience_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/audience.py#L23)


## Ruimtelijke visualisatie verkennen · experimenteel

**Probleem:** Ik wil een ruimtelijke schets bij bronbeelden.

**Resultaat:** Een gekozen externe route met expliciete voorwaarden; geometrie en fysieke juistheid vragen eigen controle.

**Nodig:** Afzonderlijk geconfigureerde externe bron en runtime. Deze routes zijn geen algemeen gekwalificeerde native voorziening van RC3.

**Eerste prompt:**

```text
Verken een ruimtelijke visualisatie voor <bronbeelden>. Controleer eerst welke externe route werkelijk beschikbaar is. Benoem geometrische aannames en begin geen lokale modeluitvoering zonder geschikte runtime.
```

- **Kies bronbeelden.** Haal de benodigde frames op. [video_frames](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_read.py#L120)
- **Controleer de externe route.** De spatial skill en adapter zijn experimenteel; aanwezigheid is geen uitvoeringsbewijs. [spatial-video-analysis](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/spatial-video-analysis/SKILL.md#L1), [spatial-session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/scripts/spatial_session.py#L1)
- **Kies een visualisatieomgeving.** Blender en FreeCAD hebben afzonderlijke prerequisites. [research-visualization-blender](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/research-visualization-blender/SKILL.md#L1), [research-visualization-freecad](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/research-visualization-freecad/SKILL.md#L1)


## Hardwaregedrag simuleren · experimenteel

**Probleem:** Ik wil een simulator lezen of aanpassen.

**Resultaat:** Simulatiewaarden en vastgelegde wijzigingen; geen fysieke hardwarewaarneming.

**Nodig:** Expliciete simulatorregistratie en passende toestemming voor wijzigingen.

**Eerste prompt:**

```text
Bekijk <simulator>. Lees eerst apparaten, metadata en limieten. Stel een wijziging voor en voer die pas uit met de vereiste toestemming.
```

- **Lees apparaten en limieten.** Discovery beschrijft de simulator. [mhs_discover](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/hardware.py#L66), [mhs_meta_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/hardware.py#L107)
- **Inspecteer de toestand.** Health en read bewijzen geen fysieke aanwezigheid. [mhs_health_check](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/hardware.py#L88), [mhs_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/hardware.py#L123)
- **Wijzig alleen expliciet.** Write en reset veranderen simulatorstate en vragen de toepasselijke toestemming. [mhs_write](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/hardware.py#L141), [mhs_reset](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/hardware.py#L170)


## Installeren en beschikbaarheid controleren

**Probleem:** Welke onderdelen heb ik nodig voor mijn taak?

**Resultaat:** Een gekozen kernserver of companion met gecontroleerde configuratie.

**Nodig:** Python ≥3.11 en uv/uvx voor MCP; Node ≥22 voor de npm-installer. De native Codex-plugin koppelt de kernserver; companions verbind je apart.

**Eerste prompt:**

```text
Controleer welke video-research-tools en skills verbonden zijn. Toon ontbrekende configuratie voor <taak>, zonder sleutels te tonen. Installeer of wijzig niets zonder mijn opdracht.
```

- **Kies de ingang.** Codex heeft 24 verpakte skills. De Claude-installer heeft 24 skillentries plus ondersteunende resources. [native-codex-plugin](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/plugin.json#L1), [plugin-installer](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/bin/install.js#L1)
- **Lees configuratie.** provider_capabilities beschrijft routes en test geen providerverbinding. [infra_configure](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/infra.py#L101), [provider_capabilities](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/text_provider.py#L43)
- **Volg eigen werk.** Lees een bestaande job; vraag annulering alleen als dat gewenst is. [job_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/jobs.py#L19), [job_cancel](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/jobs.py#L43)


## De herkomst van een beeld zoeken

**Probleem:** Waar komt dit beeld of fragment vandaan?

**Resultaat:** Kandidaatpagina’s met afzonderlijke visuele en tekstuele controle.

**Nodig:** Een exact lokaal PNG-frame; ingeschakelde Serper-route en SERPER_API_KEY. Uitvoering van reverse_search_frame uploadt het geselecteerde PNG altijd publiek naar Uguu, controleert de hosted bytes en stuurt daarna de URL naar Serper Lens. Concrete toestemming voor publicatie, inzending en mogelijk betaald gebruik is vereist. Een dry-run publiceert niets.

**Eerste prompt:**

```text
Zoek de herkomst van <beeld>. Geef kandidaten met bronpagina’s. Publiceer mijn beeld niet zonder toestemming en verifieer matches aan uiterlijk, tekst en context.
```

- **Kies een exact beeld.** Haal één bronframe op. [video_frame](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_read.py#L81)
- **Zoek kandidaten.** Kies een lokale dry-run zonder upload of uitvoering van reverse_search_frame met publieke PNG-upload naar Uguu, bytecontrole en daaropvolgende URL-inzending naar Serper Lens. web_search_provider is een afzonderlijke tekstzoekroute; die vervangt deze framezoekroute niet. [reverse_search_frame](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/search_provider.py#L66), [web_search_provider](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/search_provider.py#L26)
- **Controleer de pagina’s.** Een zoekmatch is nog geen vastgestelde oorsprong. [web_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/search_provider.py#L46)


## Vertelling en visuele assets maken

**Probleem:** Ik wil audio of beelden voor een video produceren.

**Resultaat:** Providerartefacten die nog op inhoud, kwaliteit en samenhang beoordeeld moeten worden.

**Nodig:** Afzonderlijk beschikbare generators en geconfigureerde providers. De kernserver heeft geen ingebouwde afbeelding-, TTS- of clipgenerator.

**Eerste prompt:**

```text
Maak een assetplan voor <video>. Controleer echte generators, invoer en kosten vóór uitvoering. Begin met één voorbeeld en beoordeel beeld en audio voordat je opschaalt.
```

- **Kies een beschikbare generator.** Deze skills begeleiden gebruik; ze voegen geen generator toe. [tts-production](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/tts-production/SKILL.md#L1), [image-generation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/image-generation/SKILL.md#L1), [video-generation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/skills/video-generation/SKILL.md#L1)
- **Gebruik de companion indien aangesloten.** Narratie vraagt een goedgekeurd gebonden script; muziek en SFX gebruiken gekozen upstream routes. [explainer_narration](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L77), [explainer_music](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L53), [explainer_sound](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L25)
- **Inspecteer en meng.** Meet bronmedia en meng bestaande projectaudio afzonderlijk. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/media_read.py#L28), [audio_dsp_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/audio_dsp.py#L29), [explainer_audio_mix](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio_mix.py#L18)


## Bestaande materialen samenstellen

**Probleem:** Ik heb eigen beelden en clips en wil daar een video van maken.

**Resultaat:** Een lokale MP4 volgens een vastgelegde volgorde en timing.

**Nodig:** Aparte explainercompanion, geconfigureerd project, lokale materialen met gebruiksverklaringen en FFmpeg/ffprobe. Stock zoeken/downloaden is niet aangesloten.

**Eerste prompt:**

```text
Stel mijn bestaande materialen <bestanden> samen tot <duur>. Gebruik alleen deze bestanden. Leg volgorde, timing en gebruiksverklaringen vast en controleer de volledige MP4.
```

- **Maak of kies een project.** Gebruik een bestaande projectomgeving; create gebruikt de upstream CLI. [explainer_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L27), [explainer_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L112)
- **Leg het plan en de materialen vast.** Bind scènes, script en de expliciet aangeleverde bronnen. [explainer_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/planning.py#L20)
- **Assembleer en controleer.** Gebruik lokale materialen; deze route zoekt of downloadt geen stock. [explainer_materials_assemble](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/materials.py#L18)


## Bronnen en notities lokaal hergebruiken

**Probleem:** Ik wil passages uit mijn eigen bronnen terugvinden en delen.

**Resultaat:** Lokale collecties, citeerbare passages, notities en leesbare exports.

**Nodig:** Bestaande lokale bronrecords; geen Weaviate of modelprovider nodig voor deze recordbewerkingen.

**Eerste prompt:**

```text
Orden <bronrecords> in een collectie. Zoek passages over <vraag>, bewaar notities met exacte verwijzingen en exporteer een leesbaar overzicht.
```

- **Orden en zoek.** Werk met de aangeleverde bronrecords en een begrensde zoekvraag. [collections_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/collections.py#L26), [corpus_retrieve](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/corpus.py#L27)
- **Bewaar context.** Koppel notities of wiki-revisies aan exacte passages. [notebook_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/notebooks.py#L23), [wiki_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/wiki.py#L27)
- **Deel brongegevens.** Controleer welke brongegevens geschikt zijn om te delen. [evidence_export](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/evidence_export.py#L24)


## Een video vertalen · experimenteel

**Probleem:** Ik wil gesproken vertaling bij mijn video.

**Resultaat:** Een brongebonden vertaalplan en mogelijke render; stemkwaliteit en beluistering blijven afzonderlijke controles.

**Nodig:** Optionele geconfigureerde dubbingservice voor stems, VAD en TTS; lokale media en FFmpeg/ffprobe. Goedgekeurde stemreferenties.

**Eerste prompt:**

```text
Bereid vertaling van <video> naar <taal> voor. Controleer eerst de dubbingservice. Maak alleen een analyse en plan; vraag goedkeuring vóór synthese en beoordeel de uiteindelijke audio.
```

- **Controleer en bereid voor.** Ontbrekende service is een stopvoorwaarde. [check_dubbing_service](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L32), [prepare_video_translation_project](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L43)
- **Controleer het vertaalplan.** Werk met exacte bronmomenten, sprekertoewijzingen en slots. [get_video_translation_state](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L152), [validate_video_translation_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L169)
- **Render na goedkeuring.** Technische levering en beluisterde stemkwaliteit zijn aparte uitkomsten. [render_video_translation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L187), [validate_video_translation_delivery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L212)


## Filmcommentaar maken

**Probleem:** Ik wil uitleg bij geselecteerde filmfragmenten.

**Resultaat:** Een goedgekeurd commentaarplan, afzonderlijk uitgevoerde segmentgroepen en gecontroleerde levering.

**Nodig:** Aparte explainercompanion; lokale bronvideo, FFmpeg/ffprobe en een geschikte uitvoerroute voor de goedgekeurde segmentgroepen.

**Eerste prompt:**

```text
Bereid commentaar voor bij <video> over <vraag>. Leg exacte bronmomenten en vertelling vast. Laat me het plan en de segmentgroepen goedkeuren voordat je deelrenders maakt.
```

- **Maak en controleer het plan.** Koppel het project aan de exacte bronvideo. [commentary_prepare](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L39), [commentary_validate_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L87)
- **Leg segmentgroepen vast.** Approve geeft uitvoeringsscope; de tool voert geen deelrender uit. Die uitvoering vraagt een afzonderlijke geschikte route. [commentary_freeze_shards](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L105), [commentary_approve_shard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L125)
- **Voeg bestaande deelrenders samen.** Pas na geslaagde deeluitkomsten volgt assemble en leveringcontrole. [commentary_assemble](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L143), [commentary_validate_delivery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L166)


**Live- en dubbingkaarten — concrete vragen en resultaten:**

| Vraag | Resultaat | Exacte tool |
| --- | --- | --- |
| Ik wil bestaande gebeurtenissen met hun tijdstempels bewaren. | Bewaar een begrensde, onveranderlijke replay met bronidentiteiten en klokkoppelingen; deze stap neemt niets op en voert geen interpretatie uit. | [live_replay](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/live.py#L28) |
| Ik wil een deel van mijn bewaarde gebeurtenissen teruglezen. | Lees een begrensde pagina met oorspronkelijke tijdstempels, klokkoppelingen en expliciete resterende, wachtende en verloren gebeurtenissen. | [live_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/live.py#L48) |
| Ik wil weten of mijn bewaarde gebeurtenissen aan een voorwaarde voldoen. | Controleer een letterlijke tekst-, type- of telvoorwaarde binnen vaste limieten; toon gevonden bewijs of een expliciet niet-behaald resultaat, zonder corrigerende actie. | [live_monitor](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/live.py#L68) |
| Ik wil mijn bewaarde gebeurtenissessie afsluiten. | Bewaar een afsluitrecord voor de exacte sessieversie; eerdere gebeurtenissen blijven onveranderd en worden niet opnieuw verwerkt. | [live_stop](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/live.py#L88) |
| Ik wil mijn bewaarde gebeurtenissen in mijn bronbibliotheek opnemen. | Sluit de sessie af en indexeer het bewijs met de oorspronkelijke klok in de bestaande lokale bibliotheek; onzekere inzending blijft zichtbaar en wordt niet herhaald. | [live_finalize](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/live.py#L108) |
| Ik wil weten of mijn opnameomgeving beschikbaar is. | Inspecteer opgegeven paden, uitvoerbare bestanden en apparaten; toon ontbrekende mogelijkheden en onbekende opnamerechten zonder een opname te starten. | [live_capability_probe](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/live.py#L128) |
| Ik wil een begrensde scherm- of vensteropname voorbereiden. | Bereid een overdracht aan een afzonderlijk opnameproces voor, met doel, duur en bewaarscope, of meld dat de omgeving niet wordt ondersteund; deze tool start geen opname. | [live_capture_prepare](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/live.py#L148) |
| Ik wil weten of de nasynchronisatiedienst klaar is. | Controleer de geconfigureerde dienst en meld ontbrekende of ongereedstaande toegang als stopvoorwaarde; beschikbaarheid bewijst nog geen stemkwaliteit. | [check_dubbing_service](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L32) |
| Ik wil mijn video voorbereiden op gesproken vertaling. | Bereid brongebonden PCM-audio, lokale stem- en achtergrondsporen en spraakintervallen voor; bewaar de doeltaal, stijl en gekozen stopfase of meld dat de dienst niet klaar is. | [prepare_video_translation_project](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L43) |
| Ik wil spraak en achtergrondgeluid apart kunnen verwerken. | Stuur lokale PCM-audio naar de geconfigureerde dienst en bewaar alleen gecontroleerde, lokaal teruggelezen stem- en achtergrondsporen, of een expliciete fout. | [separate_dubbing_audio](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L75) |
| Ik wil weten in welke audio-intervallen wordt gesproken. | Vraag de geconfigureerde TEN-VAD-dienst om geordende spraakintervallen en gemeten duur uit het gecontroleerde stemspoor; dit levert geen transcript of sprekeridentiteit. | [detect_dubbing_speech](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L100) |
| Ik wil één goedgekeurde vertaalde zin als audio maken. | Laat de geconfigureerde dienst de zin uitspreken met een goedgekeurde lokale stemreferentie en bewaar de werkelijke WAV; stemkwaliteit en beluistering blijven afzonderlijk onbeoordeeld. | [synthesize_dubbing_speech](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L125) |
| Ik wil weten welke vertaalstap mijn project nu nodig heeft. | Lees de toestand uit de werkelijke projectbestanden: analyse, vertaling, render of beoordeling; meld ontbrekend of ongeldig bewijs. | [get_video_translation_state](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L152) |
| Ik wil mijn vertaalplan vóór uitvoering controleren. | Controleer de exacte bronkoppelingen, sprekerreferenties, zinsgroepen en tijdslots; geef de planhash en timingdiagnostiek of een validatiefout. | [validate_video_translation_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L169) |
| Ik wil mijn goedgekeurde gesproken vertaling renderen. | Render uit gecontroleerd lokaal bewijs met begrensde spraaksynthese en technische controles; geef gemeten uitvoerbestanden en rapporten, met beluistering nog apart open. | [render_video_translation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L187) |
| Ik wil controleren of mijn vertaalde video technisch klopt. | Controleer uitvoerhashes, alle streams, volledige decode en de audiomix; rapporteer technische uitkomsten en aangeleverde luisterbeoordeling afzonderlijk. | [validate_video_translation_delivery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/src/video_research_mcp/tools/video_dubbing.py#L212) |
