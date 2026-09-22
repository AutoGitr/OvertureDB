# OvertureDB

Public catalog of community-curated posters, backgrounds, and theme song links for [Overture](https://github.com/AutoGitr/Overture).

OvertureDB indexes metadata, image URLs, and YouTube IDs so media server users can match clean, consistent artwork and music across their libraries. It does not host or redistribute image or audio files.

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
