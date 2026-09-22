# Selection Guidelines

OvertureDB stores verified metadata, direct image links, and YouTube theme IDs. It does not host image or audio files.

---

## 1. General Rules

- **Preferred Source**: TMDB (`image.tmdb.org`) is the preferred and prioritised artwork source.
- **Aspect Ratio Margin (1% Rule)**: The aspect ratio of submitted artwork must lie within a 1% margin of the stated target aspect ratios:
  - Posters and season posters (2:3 target ratio = 0.667): allowed ratio range is 0.660 to 0.674 (for example, 2000x3000).
  - Backgrounds (16:9 target ratio = 1.778): allowed ratio range is 1.760 to 1.796 (for example, 3840x2160 or 1920x1080).
- **Represent the Item**: Artwork and audio must match the tone, genre, and aesthetic of the movie or show.
- **Visual Consistency**: Keep artwork consistent across related items in a franchise, collection or TV show seasons.
- **Criterion Collection Films**: Any Criterion film must use a properly formatted Criterion poster. It must use modern Criterion formatting (clean layout), correct aspect ratio (not stretched or distorted), and authentic Criterion cover art.
- **No Spoilers**: Do not submit artwork or theme music that spoils major plot points, twists, character deaths, or endings.
- **No Explicit or Malicious Content**: Submissions must not contain adult or explicit (NSFW) imagery, nudity, gore, hate speech, or deceptive/malicious links.
- **Document New Poster Sets**: When you use a new poster set for a franchise or collection, submit a pull request adding its link to [Established Poster Sets](#5-established-poster-sets) so future contributions stay aligned.

---

## 2. Artwork Requirements

### Posters

- Must contain the title.
- Preferably no other text (no taglines, actor lists, critic quotes, or release dates) unless it genuinely suits the item.
- 2000x3000 (2:3 aspect ratio) preferred.

### Backgrounds

- Must be a real scene or shot taken directly from the item.
- No text unless it naturally appears in the scene.
- 3840x2160 (16:9 aspect ratio) preferred; 1920x1080 minimum.
- **Never use "photoshopped" composite images** where main characters are cut out and placed together, or shown as floating heads.

### Season Posters

- Must contain the season info (for example, "Season 1").
- Preferably nothing else unless it suits the item.
- 2000x3000 preferred.
- An item's season posters must be consistent with each other.

---

## 3. Theme Audio Requirements

### Duration and Audio Quality

- Preferred length is 1 to 2 minutes.
- Clean audio only: no dialogue intros, YouTube outro promotions, watermarks, or abrupt cutoffs.

### Do Not Duplicate ThemerrDB

- Overture automatically imports ThemerrDB themes. Only add an OvertureDB theme if ThemerrDB does not have one, or if you are providing a distinctly better version.

---

## 4. Allowed Sources & URL Formats

| Source | Priority | Allowed Host | Required Format |
| :--- | :--- | :--- | :--- |
| **TMDB** | Preferred | `image.tmdb.org` | Direct image path (e.g. `/t/p/original/...`). |
| **ThePosterDB** | Secondary | `theposterdb.com`<br>`www.theposterdb.com` | Must use the direct API path: `/api/assets/<id>`.<br>Do not include trailing `/view` or URL fragments (`#`). |
| **Fanart.tv** | Secondary | `assets.fanart.tv` | Direct image path. |
| **TheTVDB** | Secondary | `artworks.thetvdb.com` | Direct image path. |
| **Plex Static** | Secondary | `metadata-static.plex.tv` | Direct static image path. |

- Images must be direct JPEG (`.jpg`, `.jpeg`) or PNG (`.png`) files.
- Use HTTPS URLs.

---

## 5. Established Poster Sets

- Use the established poster set when contributing items that belong to the series below.
- Add new sets to the table and keep it alphabetically sorted.

| Series / Category | Poster Set Link | Notes |
| :--- | :--- | :--- |
| **Apocalypse Documentaries** | https://theposterdb.com/set/398222 | Documentary series. |
| **David Attenborough Documentaries** | https://theposterdb.com/set/125988 | From TPDB user `fwlolx`. |
| **Disneynature** | https://theposterdb.com/set/11090 | |
| **James Bond** | https://theposterdb.com/set/62004 | |
| **Ken Burns Documentaries** | https://theposterdb.com/poster/218606 | From TPDB user `fwlolx`. |
| **Marvel Cinematic Universe** | https://theposterdb.com/set/87082 | |
| **Pixar Animation Studios** | https://theposterdb.com/set/97 | |
| **Pixar Shorts** | https://theposterdb.com/set/11456 | |
| **Planet Documentaries** | https://theposterdb.com/set/143160 | Use for the planet series (*Planet Earth*, *Blue Planet*, etc.). |
| **Studio Ghibli** | https://theposterdb.com/set/32965 | |
| **Walt Disney Animation Studios** | https://theposterdb.com/set/2454 | |
| **Walt Disney Animation Studios Shorts** | Posters in this style: https://theposterdb.com/poster/206944 | From TPDB users `scoobymcsnack`, `DIIIVOY`, and `HammerActually`. |

---

## 6. How to Submit

### Contributing with Overture (Strongly recommended)

Using [Overture](https://github.com/AutoGitr/Overture) helps you find gaps in the catalog, choose artwork, and prepare submissions. The app handles the technical checks; use the guidelines above to judge visual consistency, suitability, and theme quality.

- **Find missing selections**: Filter for incomplete OvertureDB items in Overture to see where contributions are needed without searching dataset files or previous issues.
- **Workflow & auto-advance**: Enable auto-advance in settings to automatically move from poster to background to theme to the next item as you make selections.
- **Aspect ratio limits**: Automatically verifies pixel dimensions to ensure candidates strictly conform to target aspect ratios within the 1% margin (2:3 for posters, 16:9 for backgrounds).
- **Known resolutions & sorting**: Detects exact dimensions and automatically sorts candidates by resolution, surfacing the highest-quality artwork first.
- **True image validation**: Checks image file headers to ensure authentic JPEG and PNG files, filtering out corrupt files or unsupported formats.
- **Guaranteed direct links**: Formats URLs directly to allowed providers using valid public HTTPS endpoints (such as direct ThePosterDB API paths and TMDB image links).
- **Accurate external IDs**: Automatically pairs TMDB, TVDB, and IMDb IDs from your media server match, eliminating typos and identity errors.
- **Prefilled submissions**: Clicking the GitHub contribution link opens a labeled issue form with title, year, external IDs, and URLs already populated, saving you from looking up IDs or copying links manually.

Review the details and click **Submit new issue**.

To contribute your complete selections at once, export your saved selections (**OvertureDB -> Export selections**) and upload the `.zip` to the [Bulk Contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml) form.

### Manual Submissions

You can also open an issue directly:
- **[Movie](https://github.com/AutoGitr/OvertureDB/issues/new?template=movie.yml)**: Title, year, external IDs, poster URL, background URL, and YouTube ID.
- **[Show](https://github.com/AutoGitr/OvertureDB/issues/new?template=show.yml)**: Same as movie, plus season poster URLs (`season_number=url`).

### Modifying an Existing Entry

- If you are changing an existing catalog entry, you **must replace the placeholder text in "Reason for modification"** with an explanation (such as higher resolution, textless artwork, or fixing a dead link). If the placeholder is left unchanged, the submission is paused to prevent accidental overwrites.

### Review and Bot Commands

Submissions are validated by an automated preview workflow. Maintainers review the issue and can run these commands in a comment:
- `@OvertureDB-bot approve` - Generates a bot PR and merges the change.
- `@OvertureDB-bot reject [reason]` - Rejects the submission and closes the issue.

Maintainers can also edit the issue description directly to adjust URLs or metadata before approving.
