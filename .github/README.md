<!-- prettier-ignore -->
<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../docs/brand/overturedb-logo-stacked-dark.svg" />
  <img src="../docs/brand/overturedb-logo-stacked-light.svg" alt="OvertureDB" width="260" />
</picture>

<br>

*Community-curated artwork and theme music catalog for [Overture](https://github.com/AutoGitr/Overture)*

</div>

## Overview

OvertureDB provides consistent posters, backgrounds, and theme music for your media library. The public catalog stores curated selections as metadata, image URLs, and YouTube IDs for Overture to match against your movies and shows. It does not host or redistribute image or audio files.

---

## Highlights

- **Visual consistency**: Matching poster sets across franchises, director collections, and TV seasons.
- **Real background scenes**: Genuine shots from the movie or episode - no "photoshopped" character collages or floating heads.
- **Criterion artwork**: Authentic, modern-formatted Criterion posters for films distributed by Criterion.
- **Curated themes**: 1-2 minute standalone audio clips without dialogue intros, YouTube promos, or watermarks.

---

## Contributing via Overture

Using [Overture](https://github.com/AutoGitr/Overture) makes complying with catalog rules easy:

- **Enforces aspect ratios**: Verifies dimensions to guarantee images stay within the 1% aspect ratio margin.
- **Known resolutions & sorting**: Detects exact pixel dimensions and sorts candidates by resolution, surfacing the highest-quality artwork first.
- **True image validation**: Checks file signatures to guarantee authentic JPEG and PNG files, filtering out corrupt or unsupported formats.
- **Correct links**: Outputs approved HTTPS URLs in the required format (such as direct ThePosterDB API paths and TMDB image links).
- **Accurate external IDs**: Automatically pairs verified TMDB, TVDB, and IMDb IDs from your media server match, eliminating typos.
- **One-click submissions**: Clicking the contribution link opens a prefilled GitHub issue form with all titles, IDs, and URLs ready to submit.

---

## Documentation

- **[Selection Guidelines](../docs/selection-guidelines.md)** - Image rules, aspect ratio limits, allowed hosts, theme audio rules, examples, and established poster sets.
- **[Contributing & Development](CONTRIBUTING.md)** - Development environment setup, testing, validation scripts, and schema contracts.
- **[Security Policy](SECURITY.md)** - Vulnerability reporting and disclosure.

---

## Published Catalog

The catalog validates and publishes daily to GitHub Pages:
- `catalog.json` and `catalog.json.gz`: Complete catalog records.
- `SHA256SUMS`: Checksums for file integrity.

---

## Licensing & Provenance

Artwork URLs point to approved public hosts (ThePosterDB, TMDB, Fanart.tv, TheTVDB, Plex Static) and theme IDs point to YouTube. Code and schemas are licensed under [LICENSE](LICENSE). Third-party notices are in [licenses/THIRD_PARTY_NOTICES.md](../licenses/THIRD_PARTY_NOTICES.md).
