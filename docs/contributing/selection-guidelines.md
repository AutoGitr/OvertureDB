---
sidebar_position: 2
title: Selection guidelines
description: What makes a poster, background, season poster or theme acceptable.
---

# Selection guidelines

OvertureDB stores verified metadata, direct image links and YouTube theme IDs.
These rules decide what is accepted.

## General rules

- **Preferred source**: TMDB is the preferred and prioritised artwork source.
  ThePosterDB is good for franchise and collection artwork sets. See
  [Sources](sources.md).
- **Resolution**: the higher the better, as long as it doesn't compromise
  other criteria. Posters and season posters should be at least 1000x1500 and
  backgrounds at least 1600x900.
- **Aspect ratio margin (1% rule)**: the aspect ratio of submitted artwork must
  lie within a 1% margin of the target aspect ratio:
  - Posters and season posters (2:3 target ratio = 0.667): allowed ratio range
    is 0.660 to 0.674 (for example, 2000x3000).
  - Backgrounds (16:9 target ratio = 1.778): allowed ratio range is 1.760 to
    1.796 (for example, 3840x2160 or 1920x1080).
- **No theme**: when a title has no theme music, check **This title has no
  theme** instead of giving a video. The entry is then flagged `no_theme` and
  counts as theme-complete; a later theme contribution clears the flag.
- **Represent the item**: the artwork and theme should match the tone, genre
  and aesthetic of the movie or show (to some degree).
- **Visual consistency**: keep artwork consistent across a franchise,
  collection or a show's seasons. When you pick artwork from a poster set,
  such as one of the [example poster sets](example-poster-sets.md), aim to
  contribute that set's artwork for every item it covers.
- **Criterion Collection films**: any Criterion film must use a properly
  formatted Criterion poster. It must use modern Criterion formatting (clean
  layout), correct aspect ratio (not stretched or distorted) and authentic
  Criterion cover art.
- **Exceptions**: can be made to any of the rules above when a good reason is
  given or in special cases.
- **No spoilers or explicit or malicious content**: submissions must not
  contain spoilers to major plot points, adult or explicit (NSFW) imagery,
  nudity, gore, or deceptive or malicious links.

## Artwork requirements

### Posters

- Must contain the title.
- Preferably no other text unless it suits the item.

### Backgrounds

- Must be a real scene or shot taken directly from the item.
- No text unless it naturally appears in the scene.
- Never use "photoshopped" composite images where main characters are cut out
  and placed together, or shown as floating heads.

### Season posters

- Must contain the show's title and season title or info ("Season 1").
- Preferably no other text unless it suits the item.
- A show's season posters must be consistent with each other.

### Consistent collection posters

A collection can hold two posters: its own (`poster_url`), chosen like any
other poster, and a consistent one (`consistent_poster_url`) in the one layout
every consistent collection poster shares, so a library of them looks alike.
Overture users choose which of the two OvertureDB gives their TMDB collections.

- Make it with the
  [Coverlabs Silva designer](https://www.coverlabs.studio/designer/silva),
  keeping its layout and font.
- Upload it to the collection on TMDB; only when TMDB will not take it, upload
  it to ThePosterDB. Other sources are rejected for consistent posters.
- Give its link under **Consistent poster URL** in the collection form. The 1%
  rule and resolution recommendation of posters apply.

## Theme requirements

- A theme must last 20 seconds to 10 minutes; contributions outside that are
  rejected. The preferred length is 1 to 2 minutes.
- Music should begin immediately without leading silence or prolonged
  fade-ins.
- Clean audio only: no dialogue intros, YouTube outro promotions, watermarks
  or abrupt cutoffs.
- OvertureDB imports ThemerrDB's themes daily. Contributions only set
  `youtube_id_overturedb`; review links compare that field alone. A
  contributed theme must differ from the item's imported
  `youtube_id_themerrdb`, so each item has a fallback when a video is removed
  or region-restricted. Matching imported themes are omitted from
  contributions. Bulk exports cannot set or replace the imported theme, and
  their `youtube_id_themerrdb` values are ignored.

## Images

Images must be JPEG (`.jpg`, `.jpeg`) or PNG (`.png`) files, linked directly
from an [allowed source](sources.md). Uploads from your own device cannot be
contributed, since the catalog takes public links only.
