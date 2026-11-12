---
sidebar_position: 1
title: How to contribute
description: Submitting selections with Overture or by hand, and changing an existing entry.
---

# How to contribute

Every submission is an issue on GitHub, checked by a bot and approved by a
maintainer; approved ones reach the catalog with its next daily update. Read
the [selection guidelines](selection-guidelines.md) first: they decide what is
accepted.

## With Overture (recommended)

[Overture](/overture) finds gaps in the catalog, checks candidates and
prepares submissions; use the guidelines to judge visual consistency,
suitability and theme quality.

1. In Overture, set the **OvertureDB Status** filter to **Incomplete** to find
   titles that still need selections.
2. Choose artwork and a theme. Overture checks image formats, dimensions and
   links against the catalog rules.
3. Click the GitHub button on the title (**Contribute issue**) to open a
   prefilled issue, add a reason if replacing existing selections, review it
   and submit it. The bot shows the dataset diff directly in its preview.

What Overture does for you:

- **Find missing selections**: filter for incomplete OvertureDB items to see
  where contributions are needed.
- **Workflow and auto-advance**: enable auto-advance in settings to move from
  poster to background to theme to the next item as you make selections.
- **Aspect ratio limits**: verifies pixel dimensions against the 1% rule (2:3
  for posters, 16:9 for backgrounds).
- **Known resolutions and sorting**: detects exact dimensions and sorts
  candidates by resolution, highest first.
- **True image validation**: checks image file headers for authentic JPEG and
  PNG files.
- **Direct links**: converts every artwork link to the full-size original form
  the catalog stores.
- **Accurate external IDs**: pairs TMDB, TVDB and IMDb IDs from your media
  server match.
- **Prefilled submissions**: **Contribute issue** on a title, collection or
  OvertureDB draft opens its issue form with the title, year, external IDs,
  artwork links, theme and season posters filled in.

To submit many titles at once, use **OvertureDB -> Export selections** in
Overture and attach the ZIP to a
[bulk contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml).
Bulk contributions add missing items and values and keep imported ThemerrDB
themes; to change or remove an existing value, use the movie, show or
collection form.

## Manually

Fill in the form yourself:

- **[Movie](https://github.com/AutoGitr/OvertureDB/issues/new?template=movie.yml)**:
  title, year, external IDs, poster URL, background URL and YouTube ID.
- **[Show](https://github.com/AutoGitr/OvertureDB/issues/new?template=show.yml)**:
  the same as a movie, plus season poster URLs (`season_number=url`).
- **[Collection](https://github.com/AutoGitr/OvertureDB/issues/new?template=collection.yml)**:
  title, TMDB collection ID, poster URL, consistent poster URL, background URL
  and YouTube ID. Collections are identified by their TMDB collection ID only.

Links from the [allowed sources](sources.md) in any form are converted to the
stored form on submission.

## Changing an existing entry

Use the movie, show or collection form. To replace an identifier, artwork or
theme, or to remove the entry, explain why in **Reason for modification**
(such as a wrong TMDB ID, higher resolution, or a dead link).

The daily health check reports broken artwork and themes, and artwork below
the recommended resolution. Changed entries with reported findings are
rechecked on the next daily run, so accepted fixes clear from the report
promptly.

## What happens next

A preview comment shows validation results, the selections and the diff.
Single-entry submissions are rejected for unreachable artwork, new artwork
outside the 1% rule, or a new theme that is removed or private on YouTube or
shorter than 20 seconds or longer than 10 minutes, and warn about new artwork
below the recommended resolution. A maintainer then approves or rejects the
submission; approved changes are committed to `main` and published with the
next daily update. See [Review](../maintainers/review.md) for the details.

Report bugs and suggestions about the catalog or its automation with the
[report form](https://github.com/AutoGitr/OvertureDB/issues/new?template=report.yml).
