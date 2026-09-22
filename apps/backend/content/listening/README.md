# Listening catalog

Episode-level clips for listening days in lesson chat. Pedagogy stays in `apps/backend/skills/`; this tree is content data for the API.

The backend picks **one** clip, persists it on `input_task.resource`, and the tutor links it in Markdown. We **link** to the publisher. We do not download, rehost, or embed.

## License

| `license` | Meaning |
| --- | --- |
| `public_domain` | Original VOA Learning English text/audio/video (credit VOA; skip AP/Reuters footage). |
| `cc_by` | Creative Commons Attribution (e.g. COERLL). |
| `link_only` | Freely watchable on the publisher’s site or YouTube; we only link. |

Never depend on a membership transcript. Each YAML row has a short synopsis and notice-points so the tutor can ask questions without the paid extras.

## How to add a clip

Append an object under `clips:` in `catalog.yaml`:

- `id` — stable slug (`es-notes-beginners-hotel-a2`)
- `language` — ISO 639-1 (`en`, `de`, `fr`, `es`, `it`)
- `cefr` — inclusive band, e.g. `[A2, B1]`
- `kind` — `video` or `audio`
- `duration_sec` — prefer 180–720
- `title`, `url`, `source`
- `topics` — `daily_life`, `travel`, `food`, `work`, `city`, `news`, `culture`
- `captions` — `target`, `dual`, or `none`
- `license` — as above
- `synopsis` — 5–10 lines the tutor can trust
- `notice_points` — 3–6 listen-for items

Do not catalog a channel homepage as one lesson. Prefer a specific episode or unit page.

Languages outside `en` / `de` / `fr` / `es` / `it` have no rows: that day’s input becomes reading.

## Sources (hubs — not catalog rows)

**English:** [VOA Learning English](https://learningenglish.voanews.com/) (public domain original material); [ManyThings VOA stories](https://www.manythings.org/voa/stories/); Easy English / Easy Languages (link-only, dual subs).

**German:** [Goethe-Institut Mein Weg nach Deutschland](https://www.goethe.de/prj/mwd/de/deu/ewd.html); Extra auf Deutsch; [DW Langsam gesprochene Nachrichten](https://www.dw.com/de/langsam-gesprochene-nachrichten/s-8030) only (not Nicos Weg / DW Learn German course); [COERLL Deutsch im Blick](https://coerll.utexas.edu/dib/) (CC BY); Easy German / Super Easy German; Slow German when the episode is free.

**French:** [TV5MONDE Apprendre](https://apprendre.tv5monde.com/); [RFI Journal en français facile](https://francaisfacile.rfi.fr/); Easy French; innerFrench episode pages with a free transcript; Podcast Français Facile.

**Spanish:** Notes in Spanish free beginner/intermediate audio; COERLL Spanish OER; Instituto Cervantes graded radio when the page is free; Easy Spanish / Super Easy Spanish (link-only); Radio Ambulante for one B2 item. Do not use News in Slow Spanish as a primary source.

**Italian:** Easy Italian / Super Easy Italian; graded beginner podcasts with a free transcript; Rai news only at B2+.
