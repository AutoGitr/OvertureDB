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

## Catalog at a glance

<!-- prettier-ignore -->
<a href="https://autogitr.github.io/OvertureDB/stats.json">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://autogitr.github.io/OvertureDB/stats-dark.svg" />
    <img src="https://autogitr.github.io/OvertureDB/stats-light.svg" alt="OvertureDB statistics: totals for movies, shows, posters, backgrounds, season posters and themes; movie and show coverage for posters, backgrounds, themes and core selections." width="840" />
  </picture>
</a>

Generated automatically from the validated catalog on every daily publication. [Download the statistics](https://autogitr.github.io/OvertureDB/stats.json) for exact totals and movie/show breakdowns. The snapshot date and revision identify the source data; GitHub may briefly cache the image after an update.

<details>
<summary>How the numbers are counted</summary>

- **Movies / shows:** catalog entries, including titles that currently have only a theme.
- **Posters / backgrounds:** non-empty selections for movies and shows. Season posters are counted separately.
- **Season posters:** recorded season selections, including season 0 (specials). The catalog does not list every expected season, so this is not a season-completeness percentage.
- **Themes:** all OvertureDB and ThemerrDB theme selections. A title with both contributes two themes, but counts once in theme coverage.
- **Coverage:** titles with a selection divided by all catalog titles of that media type. **Core complete** means a poster, background and at least one theme; it does not imply complete season artwork or a fresh live-link check.
- Totals count selections, not unique image files or YouTube videos. Shared assets count once for each title or season using them.

</details>

Want to help fill the gaps? [Contribute missing artwork or themes](#contributing-via-overture).

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
