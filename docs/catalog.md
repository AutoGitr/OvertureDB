---
sidebar_position: 4
title: The catalog
description: The published files, the entry format and how entries are identified.
---

# The catalog

The catalog is published to GitHub Pages at
`https://autogitr.github.io/OvertureDB/` once a day, after the ThemerrDB
import, so the day's approved contributions and imported themes go out in one
deploy. Overture downloads it from there.

## Published files

| File                                | Contents                                                      |
| ----------------------------------- | ------------------------------------------------------------- |
| `catalog.jsonl`                     | A header line, then one entry per line                        |
| `catalog.jsonl.gz`                  | The same, gzip-compressed, which Overture downloads           |
| `stats.json`                        | Totals and coverage                                           |
| `stats-light.svg`, `stats-dark.svg` | The statistics dashboard shown on the README and this site    |
| `SHA256SUMS`                        | Checksums of the files above                                  |
| `schema/entry.schema.json`          | The JSON Schema of an entry                                   |
| `schema/catalog.schema.json`        | The JSON Schema of the header line                            |
| `THIRD_PARTY_NOTICES.md`, `licenses/` | Licenses of the data the catalog derives from               |

The build is reproducible: its revision and timestamp come from the source
commit, and tests verify that the same source builds the same bytes.

## The header

The first line of `catalog.jsonl` names the schema version, when the catalog
was generated, the source commit and the notices file:

```json
{"schema_version": 3, "generated_at": "2026-11-11T14:30:00Z", "source_revision": "<commit>", "third_party_notices": "THIRD_PARTY_NOTICES.md"}
```

`schema_version` increases only when Overture could not read the catalog as
it stands; Overture reads version 3.

## Entries

Each entry is one movie, show or movie collection, stored in `data/movies/`,
`data/shows/` or `data/collections/` as `<identity>.json` and published as one
line of the catalog.

| Field                   | Movie    | Show     | Collection | Meaning                                                                                                   |
| ----------------------- | -------- | -------- | ---------- | --------------------------------------------------------------------------------------------------------- |
| `media_type`            | required | required | required   | `movie`, `show` or `collection`                                                                           |
| `title`                 | required | required | required   |                                                                                                           |
| `year`                  | required | required | never      | Release year, or `null`                                                                                   |
| `tmdb_id`               | required | required | required   | TMDB ID; a collection is identified by it alone                                                           |
| `tvdb_id`               | required | required | never      | TheTVDB ID, or `null`                                                                                     |
| `imdb_id`               | required | required | never      | IMDb ID, or `null`                                                                                        |
| `poster_url`            | required | required | required   | Direct link to the full-size poster, or `null`                                                            |
| `background_url`        | required | required | required   | Direct link to the full-size background, or `null`                                                        |
| `consistent_poster_url` | never    | never    | optional   | The collection's poster in the shared layout every consistent collection poster follows, on TMDB or ThePosterDB |
| `youtube_id_overturedb` | required | required | required   | The contributed theme's YouTube ID, or `null`                                                             |
| `youtube_id_themerrdb`  | required | required | required   | The theme imported from ThemerrDB, or `null`                                                              |
| `no_theme`              | optional | optional | optional   | The title has no theme music, so no theme is missing; then `youtube_id_overturedb` is `null`              |
| `seasons`               | never    | required | never      | Season posters, one per season number                                                                     |

A movie or show needs at least one of `tmdb_id`, `tvdb_id` and `imdb_id`.
Every artwork link is the full-size original over HTTPS, without query
strings or fragments, on one of the [allowed sources](contributing/sources.md).

## Identities

An entry's file is named by its preferred identifier, TMDB first, then TVDB,
then IMDb: `tmdb-603.json`, `tvdb-81189.json`, `imdb-tt0133093.json`. Overture
links catalog pages the same way, for example `/overturedb/shows/tvdb-81189`.
Submissions that add an identifier to an existing entry merge into it;
conflicting identifiers are refused.

## Rules

The rules an entry follows, from ID patterns and title length to the aspect
ratio tolerance, theme length and canonical link forms, live in
`schema/contract.py` beside the schemas. Overture imports the same contract,
so what Overture accepts and what the catalog accepts never differ. See
[Development](maintainers/development.md#shared-schema).
