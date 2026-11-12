---
sidebar_position: 3
title: Sources
description: The artwork hosts the catalog accepts and the link form it stores.
---

# Sources

Every entry stores the full-size original over HTTPS, without query strings
or fragments. Submitted links are converted to that form; links on these
hosts that do not name an image (sets, pages, viewers) are rejected.

| Source          | Priority            | Stored link                                   | Also accepted (automatically converted on submission)                   |
| :-------------- | :------------------ | :-------------------------------------------- | :---------------------------------------------------------------------- |
| **TMDB**        | Primary & preferred | `https://image.tmdb.org/t/p/original/<file>`  | Any other size (`w342`, `w780`, ...) and `themoviedb.org` image links.  |
| **ThePosterDB** | Secondary           | `https://theposterdb.com/api/assets/<id>`     | Poster pages (`/poster/<id>`), `/view` links and `www.theposterdb.com`. |
| **Fanart.tv**   | Secondary           | `https://assets.fanart.tv/fanart/<path>`      | `/preview/` thumbnails and `fanart.tv` links.                           |
| **TheTVDB**     | Secondary           | `https://artworks.thetvdb.com/banners/<path>` | `_t` thumbnails, `_cache/` links and `thetvdb.com` links.               |
| **Plex Static** | Secondary           | `https://metadata-static.plex.tv/<path>`      |                                                                         |

Images must be JPEG (`.jpg`, `.jpeg`) or PNG (`.png`) files. Consistent
collection posters are accepted from TMDB and ThePosterDB only.

The rules live in `schema/contract.py`, which Overture uses too, so a link
Overture accepts is a link the catalog accepts.
