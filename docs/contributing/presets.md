---
sidebar_position: 5
title: Presets
description: Contributing ready-made collections, sets and groups from Overture.
---

# Presets

A preset is a ready-made set of collections, collection sets and groups, such
as Holidays, Decades or TMDB charts, that anyone can add to their libraries
from Overture's gallery. What adding one creates belongs to the person who added
it; when the preset changes, Overture offers them the changes, which they may
take or leave.

## Contributing a preset

1. In Overture, build the collections and groups as you would for yourself.
2. Open **Collections → Presets → Export**, choose the groups and collections,
   and export them. Overture downloads `overture-collections.json` and lists
   what it left out and why.
3. Click the GitHub button beside the export to open the preset form, attach
   the file under **Preset file**, give the preset a title, description and
   category, and submit it. The bot previews what the preset adds and what it
   needs, such as a TMDB token.

## Changing or removing a preset

Open the preset form again and give the preset's ID, the name of its file in
`data/presets/` without `.json`, under **Preset ID**, with a reason under
**Reason for modification**. With a new file it replaces the preset, under a
new title if you give one, and removes images the preset no longer links; with
**Remove this preset** ticked it removes the preset and its images. A new
preset whose title makes an ID that exists is refused, so a published preset
is never replaced by accident.

## What a preset may hold

- Criteria every install can test: no folders, no collections picked by ID,
  and nothing only a library filter tests. Labels are allowed but are only
  useful where the labels exist.
- No requests for missing titles, member labels or Radarr and Sonarr tags.
  Those act on someone's servers, so the person adding a preset chooses them.
- At most 50 collections and 10 groups.

## Images

A collection may start with a poster and a background. On the form, write one
line per image, such as `Christmas poster: <link>`:

- Link an image on TMDB, ThePosterDB, fanart.tv or TheTVDB, as the
  [sources](sources.md) describe.
- Or attach a JPEG or PNG you made or may share. Posters are 2:3 and at least
  1000×1500; backgrounds are 16:9 and at least 1280×720; neither may be larger
  than 5 MB. The bot saves a fresh copy without metadata in
  `data/presets/<preset>/`, and OvertureDB publishes it under the repository
  licence.

Sets take their art from their group's automatic art settings, such as
generated posters.
