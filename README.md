# OvertureDB

<p align="center">
  <b>The open, curated catalog of premium artwork sets and verified theme music for <a href="https://github.com/AutoGitr/Overture">Overture</a>.</b>
</p>

---

## Overview

**OvertureDB** is a community-driven metadata catalog dedicated to elevating personal media libraries. It provides hand-curated, high-resolution poster collections, authentic background scenes, and verified theme music selections for movies and television series.

Rather than hosting or redistributing copyrighted media files, OvertureDB indexes strictly verified URLs and identifiers. Users of Overture can seamlessly query OvertureDB to automatically match and apply consistent, high-standard artwork and audio directly to their Plex, Jellyfin, and Emby servers.

---

## Curation Highlights

- **Visual Harmony**: Curated sets ensure that entire franchises, director collections, and TV show seasons share a consistent aesthetic and typography.
- **Authentic Backdrops**: Backgrounds are genuine in-universe scenes captured directly from the film or episode—never artificial character collages or photoshopped floating heads.
- **High-Standard Posters**: Crisp, 2000×3000 artwork with minimal text clutter, honoring the work's original artistic identity.
- **Criterion Standards**: Criterion Collection releases utilize properly formatted Criterion artwork with authentic cover art.
- **Curated Themes**: Clean, 1–2 minute standalone theme music clips without dialogue intros, watermarks, or sponsor stings.

---

## Documentation & Guides

Whether you are contributing artwork selections, developing tooling, or integrating with OvertureDB, explore the relevant guide below:

| Guide | Description |
| :--- | :--- |
| 🎨 **[Selection Guidelines](docs/selection-guidelines.md)** | Rules for contributing artwork and themes: dimensions, allowed hosts, Criterion standards, and established poster sets. |
| 🛠️ **[Contributing & Development](CONTRIBUTING.md)** | Technical guide for developers: Python environment setup, testing suite, schema contracts, and bot workflows. |
| 🔒 **[Security Policy](.github/SECURITY.md)** | Procedures for responsibly disclosing vulnerabilities. |

---

## Catalog Distribution

The curated catalog is validated and published daily to GitHub Pages as reproducible artifacts:

- `catalog.json` and `catalog.json.gz`: The full catalog payload.
- `SHA256SUMS`: Byte-level integrity checksums.
- Canonical JSON schemas enforcing strict data validation.

---

## Licensing & Provenance

Artwork URLs link directly to approved public upstream hosts (ThePosterDB, TMDB, Fanart.tv, TheTVDB, Plex Static) and theme identifiers reference YouTube videos. Contributors and consumers remain responsible for adhering to the respective providers' terms and conditions.

Repository derivations, schemas, and automation scripts are provided under the repository's [LICENSE](LICENSE). Third-party acknowledgments are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
