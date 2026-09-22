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

OvertureDB provides consistent posters, backgrounds, and theme music for your media library. The public catalog stores curated selections as metadata, image URLs, and YouTube IDs for Overture to match against your movies and shows. The catalog validates and publishes daily to GitHub Pages.

---

## Highlights

- **Visual consistency**: Matching poster sets across franchises, select studios, people, and TV seasons.
- **Real background scenes**: Genuine shots from the movie or episode - no "photoshopped" character collages or floating heads.
- **Criterion artwork**: Authentic, modern-formatted Criterion posters for films distributed by Criterion.
- **Curated themes**: Theme music for movies and shows without dialogue intros, YouTube promos, or watermarks.

---

## Contributing via Overture

Using [Overture](https://github.com/AutoGitr/Overture) makes both contributing and complying with catalog rules easy:

- **Avoid duplicates**: Overture has a dedicated filter for incomplete OvertureDB items, you never have to look in the dataset files or previous issues.
- **Workflow & Auto-advance**: When configured in the settings, Overture can automatically advance on selection from poster -> background -> theme -> next item.
- **Enforces aspect ratios**: Verifies dimensions to guarantee images stay within the 1% aspect ratio margin.
- **Known resolutions & sorting**: Detects exact pixel dimensions and sorts candidates by resolution, surfacing the highest-quality artwork first.
- **True image validation**: Checks file signatures to guarantee authentic JPEG and PNG files, filtering out corrupt or unsupported formats.
- **Correct links**: Ensures correct HTTPS URLs in the required format (such as direct ThePosterDB API paths and TMDB image links).
- **Accurate external IDs**: Automatically pairs verified TMDB, TVDB, and IMDb IDs from your media server match, eliminating typos.
- **One-click submissions**: Clicking the contribution link opens a labeled and prefilled GitHub issue form with all titles, IDs and URLs ready to submit.

Read the [Selection Guidelines](../docs/selection-guidelines.md) to start contributing.
