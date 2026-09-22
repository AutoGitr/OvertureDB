<!-- prettier-ignore -->
<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./docs/brand/overturedb-logo-stacked-dark.svg" />
  <img src="./docs/brand/overturedb-logo-stacked-light.svg" alt="OvertureDB" width="260" />
</picture>

<br>

*Community-curated artwork and theme music catalog for [Overture](https://github.com/AutoGitr/Overture)*

</div>

## Overview

OvertureDB helps you find consistent posters, backgrounds, and theme music for your media library. The public catalog stores curated selections as metadata, image URLs, and YouTube IDs for Overture to match against your movies and shows. It does not host or redistribute image or audio files.

---

## Highlights

- **Visual consistency**: Matching poster sets across franchises, director collections, and TV seasons.
- **Real background scenes**: Genuine shots from the movie or episode—no "photoshopped" character collages or floating heads.
- **Criterion artwork**: Authentic, modern-formatted Criterion posters for films distributed by Criterion.
- **Curated themes**: 1–2 minute standalone audio clips without dialogue intros, YouTube promos, or watermarks.
- **Effortless contributions via Overture**: Select your artwork and theme in Overture, click the GitHub contribution link, and the issue form opens with all titles, IDs, and URLs prefilled. You never have to look up external IDs or copy anything manually.

---

## Documentation

- **[Selection Guidelines](docs/selection-guidelines.md)** — Image rules, resolutions, allowed hosts, theme audio rules, and established poster sets.
- **[Contributing & Development](CONTRIBUTING.md)** — Development environment setup, testing, validation scripts, and schema contracts.
- **[Security Policy](.github/SECURITY.md)** — Vulnerability reporting and disclosure.

---

## Published Catalog

The catalog validates and publishes daily to GitHub Pages:
- `catalog.json` and `catalog.json.gz`: Complete catalog records.
- `SHA256SUMS`: Checksums for file integrity.

---

## Licensing & Provenance

Artwork URLs point to approved public hosts (ThePosterDB, TMDB, Fanart.tv, TheTVDB, Plex Static) and theme IDs point to YouTube. Code and schemas are licensed under [LICENSE](LICENSE). Third-party notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
