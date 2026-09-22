# Selection Guidelines

Movies and TV Shows are refered to as items in this document.

---

## 1. General Rules

- **Represent the item**: Artwork and audio must match the tone and style of the movie or show.
- **Consistency**: Keep artwork consistent across related items (franchises, collections, seasons etc.).

- **No spoilers**: Do not submit artwork or theme music that spoils major plot points, twists, character deaths, or endings.
- **No explicit or malicious content**: Submissions must not contain adult or explicit (NSFW) imagery, gore, hate speech, or deceptive/malicious links.
- **Submit new sets to docs**: When you use a new poster set for a franchise or collection, submit a pull request adding it to [Established Poster Sets](#5-established-poster-sets) so future contributions stay aligned.

---

## 2. Artwork Requirements

### Posters
- Must contain the title.
- Preferably no other text (no taglines, actor lists, critic quotes, or release dates) unless it genuinely suits the item.
- 2000×3000 (2:3 aspect ratio) preferred.
- Any item distributed by Criterion must use the poster they use for the item on their website. Many Criterion posters have been stretched out since they do not make their cover art in the 2:3 aspect ratio, so only use ones that have been properly reformatted without stretching.

### Backgrounds
- Must be a real scene or shot taken directly from the item.
- No text unless it naturally appears in the scene.
- 3840×2160 (16:9 aspect ratio) preferred; 1920×1080 minimum.
- **Never use "photoshopped" composite images** where main characters are cut out and placed together, or shown as floating heads.

### Season Posters
- Must contain the season info (e.g., "Season 1").
- Preferably nothing else unless it suits the item.
- 2000×3000 preferred.
- An item's season posters must be consistent with each other.

---

## 3. Theme Audio Requirements

- Preferred length is **1 to 2 minutes**.
- Clean audio only: no dialogue intros, YouTube outro promotions, watermarks, or abrupt cutoffs.
- **Do not duplicate ThemerrDB**: Overture automatically imports ThemerrDB themes. Only add an OvertureDB theme if ThemerrDB does not have one, or if you are providing a distinctly better version.

---

## 4. Allowed Sources & URL Formats

Artwork URLs must use public HTTPS on one of these allowed hosts:

| Source | Allowed Host | Required Format |
| :--- | :--- | :--- |
| **ThePosterDB** | `theposterdb.com`<br>`www.theposterdb.com` | Must use the direct API path: `/api/assets/<id>`.<br>Do not include trailing `/view` or URL fragments (`#`). |
| **TMDB** | `image.tmdb.org` | Direct image path (e.g. `/t/p/original/...`). |
| **Fanart.tv** | `assets.fanart.tv` | Direct image path. |
| **TheTVDB** | `artworks.thetvdb.com` | Direct image path. |
| **Plex Static** | `metadata-static.plex.tv` | Direct static image path. |

Images must be direct JPEG (`.jpg`, `.jpeg`) or PNG (`.png`) files.

---

## 5. Established Poster Sets

When contributing items that belong to these series, use the established set to keep the catalog consistent:

| Series / Category | Poster Set Link | Notes |
| :--- | :--- | :--- |
| **Apocalypse Documentaries** | https://theposterdb.com/set/398222 | Documentary series. |
| **David Attenborough Documentaries** | https://theposterdb.com/set/125988 | From TPDB user `fwlolx`. |
| **David Attenborough (Planet Documentaries)** | https://theposterdb.com/set/143160 | Use for the planet series (*Planet Earth*, *Blue Planet*, etc.). |
| **James Bond** | https://theposterdb.com/set/62004 | |
| **Ken Burns Documentaries** | https://theposterdb.com/poster/218606 | From TPDB user `fwlolx`. |
| **Disneynature** | https://theposterdb.com/set/11090 | |
| **Pixar Animation Studios** | https://theposterdb.com/set/97 | |
| **Pixar Shorts** | https://theposterdb.com/set/11456 | |
| **Studio Ghibli** | https://theposterdb.com/set/32965 | |
| **Marvel Cinematic Universe** | https://theposterdb.com/set/87082 | |

| **Walt Disney Animation Studios** | https://theposterdb.com/set/2454 | |
| **Walt Disney Animation Studios Shorts** | Posters in this style: https://theposterdb.com/poster/206944 | From TPDB users `scoobymcsnack`, `DIIIVOY`, and `HammerActually`. |
---

## 6. How to Submit

### Contributing with Overture (Recommended)
If you use [Overture](https://github.com/AutoGitr/Overture), contributing is effortless:
1. Select your artwork and theme in Overture.
2. Click the GitHub contribution link on the item.
3. The issue template opens prefilled with the title, year, external IDs (TMDB, TVDB, IMDb), artwork URLs, and YouTube ID. You never have to look up external IDs or copy anything manually.
4. Review the details and click **Submit new issue**.

To contribute your full library at once, export your saved selections (**OvertureDB -> Export selections**) and upload the `.zip` to the [Bulk Contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml) form.

### Manual Submissions
You can also open an issue directly:
- **[Movie](https://github.com/AutoGitr/OvertureDB/issues/new?template=movie.yml)**: Title, year, external IDs, poster URL, background URL, and YouTube ID.
- **[Show](https://github.com/AutoGitr/OvertureDB/issues/new?template=show.yml)**: Same as movie, plus season poster URLs (`season_number=url`).

### Modifying an Existing Entry
If you are changing an existing catalog entry, you **must replace the placeholder text in "Reason for modification"** with an explanation (such as higher resolution, textless artwork, or fixing a dead link). If the placeholder is left unchanged, the submission is paused to prevent accidental overwrites.

### Review and Bot Commands
Submissions are validated by an automated preview workflow. Maintainers review the issue and can run these commands in a comment:
- `@OvertureDB-bot approve` — Generates a bot PR and merges the change.
- `@OvertureDB-bot reject [reason]` — Rejects the submission and closes the issue.

Maintainers can also edit the issue description directly to adjust URLs or metadata before approving.
